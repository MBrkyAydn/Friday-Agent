import os
import sys
import json
import uuid
import time
import asyncio
import logging
import tempfile
import subprocess
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

import httpx

logger = logging.getLogger("friday.telegram")

DEFAULT_BOT_TOKEN = os.environ.get("FRIDAY_TELEGRAM_BOT_TOKEN", "")
DEFAULT_CHAT_ID = os.environ.get("FRIDAY_TELEGRAM_CHAT_ID", "")

ASSET_DIRS = [
    r"C:\Users\brkya\.gemini\assets\notifications",
    r"C:\Users\brkya\Desktop\TG_bildirim",
]

EVENT_IMAGES = {
    "hata": "bilmiom.jpg",
    "error": "bilmiom.jpg",
    "fail": "bilmiom.jpg",
    "bitirdim": "bitirdim.jpg",
    "done": "bitirdim.jpg",
    "tamamlandi": "bitirdim.jpg",
    "complete": "bitirdim.jpg",
    "izin": "izin.png",
    "onay": "izin.png",
    "permission": "izin.png",
    "approval": "izin.png",
}

FRIDAY_PENDING_APPROVAL_FILE = Path(os.path.expanduser(r"~/.friday/pending_approval.json"))

APPROVAL_KEYWORDS = {"onay", "onayla", "onaylıyorum", "izin", "izin ver", "evet", "tamam", "ok", "yes", "allow", "kabul"}
DENIAL_KEYWORDS = {"red", "reddet", "reddedildi", "hayır", "hayir", "iptal", "iptal et", "deny", "no"}
YOLO_KEYWORDS = {"yolo", "yolo mod", "tam izin", "hepsine izin ver", "tam yetki"}
ALLOW_ALWAYS_KEYWORDS = {"hep izin ver", "projede izin ver", "hep onayla", "beyaz liste"}

DECISION_LABELS = {
    "allow": "🟢 Bu Seferlik İzin Verildi",
    "allow_always": "🟡 Bu Projede Hep İzin Verildi (Beyaz Listeye Alındı)",
    "yolo": "🚀 Tamamen İzin Verildi (YOLO Modu Aktif)",
    "deny": "🔴 Reddedildi",
}

DEFAULT_FRIDAY_KEYBOARD: Dict[str, Any] = {
    "keyboard": [
        [{"text": "📊 Durum"}, {"text": "🚀 YOLO Aç/Kapat"}],
        [{"text": "🏓 Ping"}, {"text": "ℹ️ Yardım"}],
    ],
    "resize_keyboard": True,
    "is_persistent": True,
}


def get_approval_keyboard(req_id: str) -> Dict[str, Any]:

    """Generate 4-tier interactive approval inline keyboard for Friday."""
    return {
        "inline_keyboard": [
            [
                {"text": "🟢 Onayla (İzin Ver)", "callback_data": f"perm_{req_id}:allow"},
                {"text": "🔴 Reddet", "callback_data": f"perm_{req_id}:deny"},
            ],
            [
                {"text": "🚀 Tam Yetki (YOLO)", "callback_data": f"perm_{req_id}:yolo"},
                {"text": "🟡 Bu Projede Hep İzin Ver", "callback_data": f"perm_{req_id}:allow_always"},
            ],
        ]
    }


def save_pending_approval(data: dict) -> None:
    """Save pending approval state for listener and CLI coordination."""
    try:
        FRIDAY_PENDING_APPROVAL_FILE.parent.mkdir(parents=True, exist_ok=True)
        FRIDAY_PENDING_APPROVAL_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as exc:
        logger.error("Failed to save Friday pending approval: %s", exc)


def load_pending_approval() -> Optional[dict]:
    """Load pending approval state if exists."""
    if not FRIDAY_PENDING_APPROVAL_FILE.exists():
        return None
    try:
        return json.loads(FRIDAY_PENDING_APPROVAL_FILE.read_text(encoding="utf-8"))
    except Exception:
        return None


def resolve_event_image(event_name: Optional[str]) -> Optional[str]:
    """Find absolute path to an event image from configured asset directories."""
    if not event_name:
        return None
    key = event_name.lower().strip()
    filename = EVENT_IMAGES.get(key)
    if not filename:
        return None
    for d in ASSET_DIRS:
        p = Path(d) / filename
        if p.is_file():
            return str(p.resolve())
    return None


def capture_web_ui(url: str, output_path: str, width: int = 1280, height: int = 800) -> bool:
    """Capture a headless browser screenshot of a local or remote web UI."""
    chrome_paths = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    ]
    browser = next((p for p in chrome_paths if os.path.exists(p)), None)
    if not browser:
        logger.warning("No headless browser found to capture web UI.")
        return False

    cmd = [
        browser,
        "--headless=new",
        f"--window-size={width},{height}",
        f"--screenshot={output_path}",
        "--hide-scrollbars",
        url,
    ]
    try:
        subprocess.run(cmd, check=True, timeout=15, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return os.path.exists(output_path) and os.path.getsize(output_path) > 0
    except Exception as exc:
        logger.warning("Error capturing web UI: %s", exc)
        return False


def capture_mobile_ui(output_path: str) -> bool:
    """Capture a mobile screen via ADB screencap."""
    adb_paths = [
        "adb",
        os.path.expandvars(r"%LOCALAPPDATA%\Android\Sdk\platform-tools\adb.exe"),
    ]
    for adb in adb_paths:
        try:
            with open(output_path, "wb") as f:
                res = subprocess.run([adb, "exec-out", "screencap", "-p"], stdout=f, stderr=subprocess.DEVNULL, timeout=10)
                if res.returncode == 0 and os.path.getsize(output_path) > 0:
                    return True
        except Exception:
            continue
    return False


class TelegramBridge:
    """
    Two-way communication bridge between FRIDAY and Telegram Bot API.
    Features:
    - Push notifications with event image resolution and UI capture
    - Automatic 4-tier interactive approval inline buttons on permission requests
    - Support for text approval replies ('Onay', 'Reddet', 'YOLO')
    - Strict Chat ID authorization to guarantee zero unauthorized access
    - Remote command execution listener (/status, /run, natural language prompts)
    """

    def __init__(
        self,
        bot_token: Optional[str] = None,
        chat_id: Optional[str] = None,
        base_url: Optional[str] = None,
    ) -> None:
        self.bot_token = (
            bot_token
            or os.getenv("TELEGRAM_BOT_TOKEN")
            or DEFAULT_BOT_TOKEN
        ).strip()
        self.chat_id = (
            chat_id
            or os.getenv("TELEGRAM_CHAT_ID")
            or DEFAULT_CHAT_ID
        ).strip()
        self.api_base = base_url or f"https://api.telegram.org/bot{self.bot_token}"
        self._last_update_id: int = 0

    def is_authorized(self, user_or_chat_id: Union[int, str]) -> bool:
        """Strict whitelist verification: ensure requester matches configured CHAT_ID."""
        try:
            return str(user_or_chat_id).strip() == str(self.chat_id).strip()
        except Exception:
            return False

    async def send_notification(
        self,
        message: str,
        title: str = "🔔 FRIDAY Bildirimi",
        event: Optional[str] = None,
        image_path: Optional[str] = None,
        web_url: Optional[str] = None,
        mobile: bool = False,
        keyboard: Optional[dict] = None,
        req_id: Optional[str] = None,
    ) -> bool:
        """
        Send push notification to Telegram (supports text, single photo, and albums).
        Automatically attaches 4-tier approval buttons if event is 'izin' or 'onay'.
        """
        is_permission_request = bool(event and event.lower().strip() in ("izin", "onay", "permission", "approval"))

        if is_permission_request and not keyboard:
            req_id = req_id or uuid.uuid4().hex[:6]
            keyboard = get_approval_keyboard(req_id)

        full_text = f"<b>{title}</b>\n\n{message}"
        if is_permission_request or keyboard:
            full_text += "\n\n⏳ <i>Sistem onayınızı bekliyor (Butonlara tıklayabilir veya 'Onay'/'Red' yazabilirsiniz)...</i>"

        images_to_send: List[str] = []
        temp_files: List[str] = []

        # 1. Event Image (izin.png, bitirdim.jpg, bilmiom.jpg)
        if event:
            ev_img = resolve_event_image(event)
            if ev_img:
                images_to_send.append(ev_img)

        # 2. Web UI Screenshot
        if web_url:
            tmp_web = os.path.join(tempfile.gettempdir(), f"friday_web_{os.getpid()}_{uuid.uuid4().hex[:4]}.png")
            if capture_web_ui(web_url, tmp_web):
                images_to_send.append(tmp_web)
                temp_files.append(tmp_web)

        # 3. Mobile UI Screenshot
        if mobile:
            tmp_mob = os.path.join(tempfile.gettempdir(), f"friday_mob_{os.getpid()}_{uuid.uuid4().hex[:4]}.png")
            if capture_mobile_ui(tmp_mob):
                images_to_send.append(tmp_mob)
                temp_files.append(tmp_mob)

        # 4. Custom image
        if image_path and os.path.exists(image_path) and image_path not in images_to_send:
            images_to_send.append(image_path)

        sent_msg_id: Optional[int] = None
        has_photo: bool = False

        try:
            async with httpx.AsyncClient(timeout=40.0) as client:
                # Scenario A: Album (sendMediaGroup)
                if len(images_to_send) > 1:
                    url = f"{self.api_base}/sendMediaGroup"
                    media = []
                    files = {}
                    opened_files = []
                    for idx, img_p in enumerate(images_to_send):
                        attach_name = f"photo_{idx}"
                        f_obj = open(img_p, "rb")
                        opened_files.append(f_obj)
                        files[attach_name] = (Path(img_p).name, f_obj, "image/jpeg")
                        item = {"type": "photo", "media": f"attach://{attach_name}"}
                        if idx == 0:
                            item["caption"] = full_text
                            item["parse_mode"] = "HTML"
                        media.append(item)

                    try:
                        res = await client.post(
                            url,
                            data={"chat_id": self.chat_id, "media": json.dumps(media)},
                            files=files,
                        )
                        res_json = res.json()
                        result_items = res_json.get("result", [])
                        if result_items:
                            sent_msg_id = result_items[0].get("message_id")
                            has_photo = True

                        if keyboard:
                            res_kb = await client.post(
                                f"{self.api_base}/sendMessage",
                                json={
                                    "chat_id": self.chat_id,
                                    "text": "👇 Lütfen yetki kararınızı seçin:",
                                    "reply_markup": keyboard,
                                },
                            )
                            kb_json = res_kb.json()
                            if kb_json.get("ok"):
                                sent_msg_id = kb_json.get("result", {}).get("message_id")
                                has_photo = False

                        return bool(res_json.get("ok"))
                    finally:
                        for f in opened_files:
                            f.close()

                # Scenario B: Single Photo (sendPhoto with persistent or inline keyboard)
                elif len(images_to_send) == 1:
                    url = f"{self.api_base}/sendPhoto"
                    with open(images_to_send[0], "rb") as f_obj:
                        files = {"photo": (Path(images_to_send[0]).name, f_obj, "image/jpeg")}
                        data = {
                            "chat_id": self.chat_id,
                            "caption": full_text,
                            "parse_mode": "HTML",
                        }
                        markup = keyboard if keyboard else DEFAULT_FRIDAY_KEYBOARD
                        data["reply_markup"] = json.dumps(markup)

                        res = await client.post(url, data=data, files=files)
                        res_json = res.json()
                        if res_json.get("ok"):
                            sent_msg_id = res_json.get("result", {}).get("message_id")
                            has_photo = True
                            return True
                        return False

                # Scenario C: Plain Text (sendMessage with persistent or inline keyboard)
                else:
                    url = f"{self.api_base}/sendMessage"
                    payload = {
                        "chat_id": self.chat_id,
                        "text": full_text,
                        "parse_mode": "HTML",
                    }
                    payload["reply_markup"] = keyboard if keyboard else DEFAULT_FRIDAY_KEYBOARD

                    res = await client.post(url, json=payload)
                    res_json = res.json()
                    if res_json.get("ok"):
                        sent_msg_id = res_json.get("result", {}).get("message_id")
                        has_photo = False
                        return True
                    return False


        except Exception as exc:
            logger.error("Failed to send telegram notification: %s", exc)
            return False
        finally:
            if keyboard and req_id:
                save_pending_approval({
                    "req_id": req_id,
                    "title": title,
                    "message": message,
                    "full_text": full_text,
                    "status": "pending",
                    "decision": None,
                    "created_at": time.time(),
                    "message_id": sent_msg_id,
                    "has_photo": has_photo,
                })
            for t in temp_files:
                try:
                    if os.path.exists(t):
                        os.remove(t)
                except Exception:
                    pass

    async def request_approval(
        self,
        tool_name: str,
        details: Dict[str, Any],
        timeout: Optional[float] = None,
    ) -> str:
        """
        Send an interactive 4-tier approval card to Telegram with inline buttons:
        1. 🟢 Bu Seferlik İzin Ver (allow)
        2. 🟡 Bu Projede Hep İzin Ver (allow_always)
        3. 🚀 Tamamen İzin Ver (yolo)
        4. 🔴 Reddet (deny)

        Strictly awaits callback query OR text reply from authorized CHAT_ID.
        Returns: 'allow', 'allow_always', 'yolo', or 'deny'.
        """
        req_id = uuid.uuid4().hex[:6]
        cb_prefix = f"perm_{req_id}"

        target = details.get("path") or details.get("command") or details.get("target") or "workspace"
        reason = details.get("reason") or details.get("description") or "Kritik/korumalı işlem yürütme"

        card_text = (
            f"<b>⚠️ FRIDAY YETKİ TALEBİ</b>\n\n"
            f"<b>🔧 Araç:</b> <code>{tool_name}</code>\n"
            f"<b>🎯 Hedef:</b> <code>{target}</code>\n"
            f"<b>📝 Detay:</b> {reason}\n\n"
            f"⏳ <i>Sistem onayınızı bekliyor (Butonlara tıklayabilir veya 'Onay'/'Red' yazabilirsiniz)...</i>"
        )

        keyboard = get_approval_keyboard(req_id)
        ev_img = resolve_event_image("izin")
        message_id: Optional[int] = None
        has_photo = False

        async with httpx.AsyncClient(timeout=15.0) as client:
            try:
                if ev_img and os.path.exists(ev_img):
                    with open(ev_img, "rb") as f_obj:
                        res = await client.post(
                            f"{self.api_base}/sendPhoto",
                            data={
                                "chat_id": self.chat_id,
                                "caption": card_text,
                                "parse_mode": "HTML",
                                "reply_markup": json.dumps(keyboard),
                            },
                            files={"photo": (Path(ev_img).name, f_obj, "image/png")},
                        )
                        res_json = res.json()
                        if res_json.get("ok"):
                            message_id = res_json.get("result", {}).get("message_id")
                            has_photo = True
                if not message_id:
                    res = await client.post(
                        f"{self.api_base}/sendMessage",
                        json={
                            "chat_id": self.chat_id,
                            "text": card_text,
                            "parse_mode": "HTML",
                            "reply_markup": keyboard,
                        },
                    )
                    res_json = res.json()
                    if res_json.get("ok"):
                        message_id = res_json.get("result", {}).get("message_id")
            except Exception as exc:
                logger.error("Failed to send approval card: %s", exc)
                return "deny"

        if not message_id:
            logger.error("Could not obtain message_id for telegram approval card.")
            return "deny"

        save_pending_approval({
            "req_id": req_id,
            "tool_name": tool_name,
            "card_text": card_text,
            "status": "pending",
            "decision": None,
            "created_at": time.time(),
            "message_id": message_id,
            "has_photo": has_photo,
        })

        # Polling loop for callback query OR text reply from authorized user
        loop_start = asyncio.get_event_loop().time()
        decision = "deny"

        async with httpx.AsyncClient(timeout=10.0) as client:
            while timeout is None or (asyncio.get_event_loop().time() - loop_start) < timeout:
                # 1. Check if background listener already handled this
                pending = load_pending_approval()
                if pending and pending.get("req_id") == req_id and pending.get("status") == "decided":
                    return pending.get("decision", "deny")

                try:
                    res = await client.get(
                        f"{self.api_base}/getUpdates",
                        params={"offset": self._last_update_id + 1, "timeout": 2},
                    )
                    updates = res.json().get("result", [])
                    for up in updates:
                        up_id = up.get("update_id", 0)
                        if up_id > self._last_update_id:
                            self._last_update_id = up_id

                        # A: Callback Query (Button Tap)
                        cq = up.get("callback_query")
                        if cq:
                            sender_id = cq.get("from", {}).get("id")
                            if not self.is_authorized(sender_id):
                                continue

                            cb_data = cq.get("data", "")
                            if cb_data.startswith(f"{cb_prefix}:"):
                                decision_choice = cb_data.split(":", 1)[1]
                                cq_id = cq.get("id")

                                try:
                                    await client.post(
                                        f"{self.api_base}/answerCallbackQuery",
                                        json={"callback_query_id": cq_id, "text": f"Seçiminiz: {decision_choice}"},
                                    )
                                except Exception:
                                    pass

                                decision = decision_choice
                                status_badge = DECISION_LABELS.get(decision, decision)
                                updated_text = f"{card_text}\n\n<b>✅ KARAR:</b> <b>{status_badge}</b>"

                                await self._edit_approval_message(client, message_id, updated_text, has_photo)

                                if pending:
                                    pending["status"] = "decided"
                                    pending["decision"] = decision
                                    save_pending_approval(pending)

                                return decision

                        # B: Text Message (User typing 'Onay', 'Reddet', etc.)
                        msg = up.get("message")
                        if msg:
                            sender_id = msg.get("from", {}).get("id") or msg.get("chat", {}).get("id")
                            if not self.is_authorized(sender_id):
                                continue

                            msg_text = msg.get("text", "").lower().strip()
                            choice = None
                            if msg_text in YOLO_KEYWORDS:
                                choice = "yolo"
                            elif msg_text in ALLOW_ALWAYS_KEYWORDS:
                                choice = "allow_always"
                            elif msg_text in APPROVAL_KEYWORDS:
                                choice = "allow"
                            elif msg_text in DENIAL_KEYWORDS:
                                choice = "deny"

                            if choice:
                                decision = choice
                                status_badge = DECISION_LABELS.get(decision, decision)
                                updated_text = f"{card_text}\n\n<b>✅ KARAR:</b> <b>{status_badge}</b> (Mesajla)"

                                try:
                                    await client.post(
                                        f"{self.api_base}/sendMessage",
                                        json={
                                            "chat_id": self.chat_id,
                                            "text": f"✅ Kararınız kaydedildi: <b>{status_badge}</b>\nİşlem devam ediyor.",
                                            "parse_mode": "HTML",
                                            "reply_to_message_id": msg.get("message_id"),
                                        },
                                    )
                                except Exception:
                                    pass

                                await self._edit_approval_message(client, message_id, updated_text, has_photo)

                                if pending:
                                    pending["status"] = "decided"
                                    pending["decision"] = decision
                                    save_pending_approval(pending)

                                return decision

                except asyncio.CancelledError:
                    raise
                except Exception as poll_err:
                    logger.debug("Polling error: %s", poll_err)

                await asyncio.sleep(0.5)

        # Timeout reached
        if timeout is not None:
            try:
                timeout_text = f"{card_text}\n\n<b>⏱️ ZAMAN AŞIMI:</b> <i>Belirlenen süre ({int(timeout)}s) içinde cevap alınamadığı için işlem otomatik reddedildi.</i>"
                async with httpx.AsyncClient(timeout=5.0) as client:
                    await self._edit_approval_message(client, message_id, timeout_text, has_photo)
            except Exception:
                pass

        return "deny"

    async def _edit_approval_message(self, client: httpx.AsyncClient, message_id: int, text: str, has_photo: bool):
        """Helper to update Telegram approval message text or photo caption."""
        try:
            if has_photo:
                await client.post(
                    f"{self.api_base}/editMessageCaption",
                    json={
                        "chat_id": self.chat_id,
                        "message_id": message_id,
                        "caption": text,
                        "parse_mode": "HTML",
                    },
                )
            else:
                await client.post(
                    f"{self.api_base}/editMessageText",
                    json={
                        "chat_id": self.chat_id,
                        "message_id": message_id,
                        "text": text,
                        "parse_mode": "HTML",
                    },
                )
        except Exception:
            pass

    async def poll_incoming_command(self) -> Optional[Tuple[str, str]]:
        """
        Poll for the next pending text command OR approval button press from authorized user.
        Returns (command_or_text, message_id) or None.
        """
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.get(
                    f"{self.api_base}/getUpdates",
                    params={"offset": self._last_update_id + 1, "timeout": 2},
                )
                updates = res.json().get("result", [])
                for up in updates:
                    up_id = up.get("update_id", 0)
                    if up_id > self._last_update_id:
                        self._last_update_id = up_id

                    # 1. Check Callback Query (Button Press)
                    cq = up.get("callback_query")
                    if cq:
                        sender_id = cq.get("from", {}).get("id")
                        cq_msg = cq.get("message", {})
                        chat_id = cq_msg.get("chat", {}).get("id")
                        chat_type = cq_msg.get("chat", {}).get("type", "")
                        if chat_type != "private" or not self.is_authorized(sender_id) or not self.is_authorized(chat_id):
                            continue

                        cb_data = cq.get("data", "")
                        cq_id = cq.get("id")

                        try:
                            await client.post(
                                f"{self.api_base}/answerCallbackQuery",
                                json={"callback_query_id": cq_id, "text": "İşlendi"},
                            )
                        except Exception:
                            pass

                        if cb_data.startswith("perm_"):
                            parts = cb_data.split(":", 1)
                            if len(parts) == 2:
                                choice = parts[1]
                                pending = load_pending_approval()
                                if pending:
                                    pending["status"] = "decided"
                                    pending["decision"] = choice
                                    save_pending_approval(pending)

                                msg = cq.get("message", {})
                                msg_id = msg.get("message_id")
                                has_photo = bool(msg.get("photo"))
                                orig_text = msg.get("caption") if has_photo else msg.get("text")
                                if orig_text:
                                    badge = DECISION_LABELS.get(choice, choice)
                                    updated_text = f"{orig_text}\n\n<b>✅ KARAR:</b> <b>{badge}</b>"
                                    await self._edit_approval_message(client, msg_id, updated_text, has_photo)

                                return f"__callback__:{choice}", str(msg_id)

                    # 2. Check Message (Command / Prompt)
                    msg = up.get("message")
                    if not msg:
                        continue

                    chat = msg.get("chat", {})
                    chat_type = chat.get("type", "")
                    sender_id = msg.get("from", {}).get("id")
                    chat_id = chat.get("id")
                    if chat_type != "private" or not self.is_authorized(sender_id) or not self.is_authorized(chat_id):
                        continue

                    text = msg.get("text", "").strip()
                    if text:
                        return text, str(msg.get("message_id"))


        except Exception as exc:
            logger.debug("poll_incoming_command error: %s", exc)
        return None
