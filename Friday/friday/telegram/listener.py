import os
import sys
import re
import time
import asyncio
import logging
from pathlib import Path
from typing import Optional

from friday import __version__
from friday.core.config import load_config
from friday.core.jarvis_daemon import is_jarvis_worker_running
from friday.telegram.bridge import (
    TelegramBridge,
    APPROVAL_KEYWORDS,
    DENIAL_KEYWORDS,
    YOLO_KEYWORDS,
    ALLOW_ALWAYS_KEYWORDS,
    DECISION_LABELS,
    load_pending_approval,
    save_pending_approval,
)
from friday.telegram.prompter import TelegramPrompter

logger = logging.getLogger("friday.telegram.listener")


class TelegramCommandListener:
    """
    Background or interactive long-polling listener for Telegram remote commands.
    Strictly accepts messages only from authorized CHAT_ID.
    Supports inline approval buttons, natural language approvals ('Onay'/'Reddet'), and tasks.
    """

    def __init__(
        self,
        target_dir: Path,
        bridge: Optional[TelegramBridge] = None,
        poll_interval: float = 2.0,
    ) -> None:
        self.target_dir = Path(target_dir).resolve()
        self.bridge = bridge or TelegramBridge()
        self.poll_interval = poll_interval
        self.running: bool = False
        self.yolo_mode: bool = False

    async def get_status_text(self) -> str:
        config = load_config(self.target_dir)
        running, pid = is_jarvis_worker_running()
        jarvis_text = f"ONLINE (PID: {pid})" if running and pid else "OFFLINE"

        pending = load_pending_approval()
        pending_str = "Yok"
        if pending and pending.get("status") == "pending" and (time.time() - pending.get("created_at", 0)) < 1800:
            pending_str = f"🟡 Onay Bekleniyor (ID: {pending.get('req_id')})"

        return (
            f"<b>🤖 FRIDAY & JARVIS SİSTEM DURUMU</b>\n\n"
            f"• <b>Sürüm:</b> v{__version__}\n"
            f"• <b>Çalışma Alanı:</b> <code>{self.target_dir}</code>\n"
            f"• <b>Aktif Profil:</b> <code>{config.active_profile or 'varsayılan'}</code>\n"
            f"• <b>Model:</b> <code>{config.model}</code>\n"
            f"• <b>YOLO Modu:</b> {'Açık (Otomatik İzin)' if self.yolo_mode or config.yolo_mode else 'Kapalı (Onay İstenecek)'}\n"
            f"• <b>Bekleyen Onay:</b> {pending_str}\n"
            f"• <b>JARVIS Worker:</b> <b>{jarvis_text}</b>\n"
        )

    async def handle_command(self, text: str) -> None:
        cmd = text.strip()
        lower_cmd = cmd.lower()

        # 1. Ignore callback query markers already resolved by bridge
        if cmd.startswith("__callback__:"):
            choice = cmd.split(":", 1)[1]
            logger.info("Handled callback query from button tap: %s", choice)
            return

        # 2. System Commands
        norm = re.sub(r"^[/\s]+", "", cmd)
        norm = re.sub(r"[📊⚡📂🛑ℹ️🏓🚀🟢🔴🟡✅❌⚠️\s]+", " ", norm).strip().lower()

        if norm in ("start", "help", "yardim", "yardım"):
            help_text = (
                "<b>📱 FRIDAY TELEGRAM KOMUT MERKEZİ</b>\n\n"
                "<b>Görev Gönderme:</b>\n"
                "• Doğrudan bir talimat yazın:\n"
                "  <i>Örn: 'FastAPI auth servisi oluştur ve pytest çalıştır'</i>\n\n"
                "<b>İzin & Onay:</b>\n"
                "• İzin butonlarına tıklayabilir veya <b>'Onay'</b>, <b>'İzin ver'</b>, <b>'Reddet'</b> veya <b>'YOLO'</b> yazabilirsiniz.\n\n"
                "<b>Komutlar:</b>\n"
                "• <code>/status</code> veya <code>/durum</code> — FRIDAY ve JARVIS durumunu gösterir\n"
                "• <code>/yolo</code> veya <code>/yolo on</code> — Tam otomatik izin modunu açar\n"
                "• <code>/yolo off</code> — İzin onaylarını tekrar etkinleştirir\n"
                "• <code>/ping</code> — Ajan bağlantı testi yapar"
            )
            await self.bridge.send_notification(help_text, title="ℹ️ FRIDAY Yardım")
            return

        if norm in ("status", "durum"):
            status_text = await self.get_status_text()
            await self.bridge.send_notification(status_text, title="📊 Durum Raporu")
            return

        if norm in ("ping",):
            await self.bridge.send_notification("🏓 Pong! FRIDAY ve JARVIS hazır.", title="⚡ Bağlantı Testi")
            return

        if norm in ("yolo", "yolo ac/kapat", "yolo aç/kapat"):
            self.yolo_mode = not self.yolo_mode
            mode_text = "Açık (Otomatik İzin)" if self.yolo_mode else "Kapalı (Onay İstenecek)"
            await self.bridge.send_notification(f"🚀 YOLO Modu güncellendi: <b>{mode_text}</b>", title="⚙️ Ayar Güncellendi")
            return

        if norm in ("yolo on", "yolo ac", "yolo aç"):
            self.yolo_mode = True
            await self.bridge.send_notification("🚀 YOLO modu açıldı. Tüm işlemler otomatik onaylanacak.", title="⚙️ Ayar Güncellendi")
            return

        if norm in ("yolo off", "yolo kapat"):
            self.yolo_mode = False
            await self.bridge.send_notification("🔒 YOLO modu kapatıldı. Kritik işlemlerde butonla onay istenecek.", title="⚙️ Ayar Güncellendi")
            return


        # 3. Check for natural language permission responses
        if (
            lower_cmd in APPROVAL_KEYWORDS
            or lower_cmd in DENIAL_KEYWORDS
            or lower_cmd in YOLO_KEYWORDS
            or lower_cmd in ALLOW_ALWAYS_KEYWORDS
        ):
            pending = load_pending_approval()
            is_pending = bool(
                pending
                and pending.get("status") == "pending"
                and (time.time() - pending.get("created_at", 0)) < 1800
            )

            if is_pending:
                if lower_cmd in YOLO_KEYWORDS:
                    choice = "yolo"
                elif lower_cmd in ALLOW_ALWAYS_KEYWORDS:
                    choice = "allow_always"
                elif lower_cmd in APPROVAL_KEYWORDS:
                    choice = "allow"
                else:
                    choice = "deny"

                pending["status"] = "decided"
                pending["decision"] = choice
                save_pending_approval(pending)

                badge = DECISION_LABELS.get(choice, choice)
                await self.bridge.send_notification(
                    f"✅ Kararınız kaydedildi: <b>{badge}</b>\nİşlem devam ediyor.",
                    title="⚡ Yetki Onaylandı",
                )
                logger.info("Natural language approval resolved: %s -> %s", cmd, choice)
                return
            else:
                await self.bridge.send_notification(
                    "ℹ️ Şu anda bekleyen bir izin/onay talebi bulunmuyor.\n"
                    "Yeni bir görev başlatmak için doğrudan talimatınızı yazabilirsiniz.",
                    title="ℹ️ Bilgi",
                )
                return

        # 4. Natural language task instruction
        task_prompt = cmd
        if task_prompt.startswith("/run "):
            task_prompt = task_prompt[5:].strip()

        if not task_prompt:
            return

        await self.bridge.send_notification(
            f"Göreviniz alındı, FRIDAY ve JARVIS işleme başladı:\n\n<code>{task_prompt}</code>",
            title="🚀 Görev Başlatıldı",
        )

        try:
            from friday.cli import setup_runtime
            runtime = setup_runtime(
                target_dir=self.target_dir,
                yolo=self.yolo_mode,
            )
            # Override prompter to use Telegram approval buttons exclusively for remote tasks
            runtime["perms"].prompter = TelegramPrompter(bridge=self.bridge)
            runtime["perms"].yolo_mode = self.yolo_mode

            lead = runtime["agent"]
            session = runtime["session"]
            session_mgr = runtime["session_mgr"]

            status = await lead.run_turn(task_prompt, session=session)
            status_str = str(status.value) if hasattr(status, "value") else str(status)

            session_mgr.record_turn(
                session=session,
                prompt=task_prompt,
                thoughts=[],
                tool_calls=[],
                status=status_str,
            )
            session_mgr.save_session(session, target_dir=self.target_dir)

            if status_str in ("DONE", "TurnStatus.DONE", "success"):
                msg = f"Görev başarıyla tamamlandı!\n\n<b>Komut:</b>\n<code>{task_prompt}</code>"
                await self.bridge.send_notification(
                    message=msg,
                    title="✅ Görev Tamamlandı",
                    event="bitirdim",
                )
            else:
                msg = f"Görev tamamlanamadı veya BLOCKED durumuna geçti ({status_str}).\n\n<b>Komut:</b>\n<code>{task_prompt}</code>"
                await self.bridge.send_notification(
                    message=msg,
                    title="⚠️ Görev Durumu",
                    event="hata",
                )
        except Exception as exc:
            logger.error("Error executing remote telegram task: %s", exc)
            await self.bridge.send_notification(
                f"Görev yürütülürken hata oluştu:\n<code>{exc}</code>",
                title="❌ Yürütme Hatası",
                event="hata",
            )

    async def start(self) -> None:
        """Run long-polling loop for authorized commands and approvals."""
        self.running = True
        logger.info("Telegram command listener started on %s", self.target_dir)

        try:
            await self.bridge.send_notification(
                f"🟢 <b>FRIDAY & JARVIS Telegram Köprüsü Çevrimiçi!</b>\n\n"
                f"• <b>Çalışma Alanı:</b> <code>{self.target_dir}</code>\n"
                f"• <b>YOLO:</b> {'Açık' if self.yolo_mode else 'Kapalı'}\n\n"
                f"Aşağıdaki butonları kullanabilir veya doğrudan görev yazabilirsiniz.",
                title="⚡ FRIDAY Çevrimiçi",
            )
        except Exception as e:
            logger.debug("Failed to send startup notification: %s", e)

        while self.running:

            try:
                cmd_data = await self.bridge.poll_incoming_command()
                if cmd_data:
                    text, msg_id = cmd_data
                    logger.info("Processing command: %s (msg_id: %s)", text, msg_id)
                    await self.handle_command(text)
            except asyncio.CancelledError:
                break
            except Exception as loop_err:
                logger.debug("Listener loop error: %s", loop_err)

            await asyncio.sleep(self.poll_interval)


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "."
    listener = TelegramCommandListener(target_dir=Path(target))
    try:
        asyncio.run(listener.start())
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass

