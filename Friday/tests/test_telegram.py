import os
import json
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from friday.core.permissions import PermissionController, PermissionTier, PermissionDecision
from friday.telegram.bridge import TelegramBridge, resolve_event_image
from friday.telegram.prompter import TelegramPrompter, HybridPrompter
from friday.telegram.listener import TelegramCommandListener
from typer.testing import CliRunner
from friday.cli import app


def test_telegram_authorization_whitelist():
    bridge = TelegramBridge(chat_id="12345678")
    assert bridge.is_authorized("12345678") is True
    assert bridge.is_authorized(12345678) is True
    assert bridge.is_authorized("9999999999") is False
    assert bridge.is_authorized("attacker_id") is False
    assert bridge.is_authorized("") is False


def test_resolve_event_image():
    # 'izin', 'bitirdim', 'hata' should resolve if assets exist
    p_izin = resolve_event_image("izin")
    p_bitirdim = resolve_event_image("bitirdim")
    p_hata = resolve_event_image("hata")

    assert p_izin is not None or resolve_event_image("nonexistent") is None
    assert resolve_event_image("unknown_event_xyz") is None


@pytest.mark.asyncio
async def test_telegram_send_text_notification():
    bridge = TelegramBridge(bot_token="test_token", chat_id="12345")

    mock_resp = MagicMock()
    mock_resp.json.return_value = {"ok": True, "result": {"message_id": 42}}

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp
        success = await bridge.send_notification("Task finished", title="Test Title")
        assert success is True
        assert mock_post.called
        call_kwargs = mock_post.call_args[1]
        assert "sendMessage" in mock_post.call_args[0][0]
        assert call_kwargs["json"]["chat_id"] == "12345"
        assert "Task finished" in call_kwargs["json"]["text"]


@pytest.mark.asyncio
async def test_telegram_approval_allow_callback():
    bridge = TelegramBridge(bot_token="test_token", chat_id="12345678")

    # Step 1: Send message returns message_id 101
    send_resp = MagicMock()
    send_resp.json.return_value = {"ok": True, "result": {"message_id": 101}}

    # Step 2: getUpdates returns callback with 'allow'
    updates_resp = MagicMock()
    updates_resp.json.return_value = {
        "ok": True,
        "result": [
            {
                "update_id": 1,
                "callback_query": {
                    "id": "cq_1",
                    "from": {"id": 12345678},
                    "data": "perm_mocked:allow",
                },
            }
        ],
    }

    answer_resp = MagicMock()
    answer_resp.json.return_value = {"ok": True}

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post, \
         patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get, \
         patch("uuid.uuid4") as mock_uuid:
        mock_uuid.return_value.hex = "mocked"
        mock_post.side_effect = [send_resp, answer_resp, MagicMock()]
        mock_get.return_value = updates_resp

        decision = await bridge.request_approval(
            tool_name="run_command",
            details={"command": "pytest", "reason": "Verifying code"},
            timeout=5.0,
        )

        assert decision == "allow"


@pytest.mark.asyncio
async def test_telegram_approval_ignores_unauthorized_user():
    bridge = TelegramBridge(bot_token="test_token", chat_id="12345678")

    send_resp = MagicMock()
    send_resp.json.return_value = {"ok": True, "result": {"message_id": 102}}

    # Hacker sends 'allow' with different user ID
    unauth_resp = MagicMock()
    unauth_resp.json.return_value = {
        "ok": True,
        "result": [
            {
                "update_id": 1,
                "callback_query": {
                    "id": "cq_hacker",
                    "from": {"id": 9999999999},  # Unauthorized
                    "data": "perm_mocked:allow",
                },
            }
        ],
    }

    # Then real user sends 'deny'
    auth_resp = MagicMock()
    auth_resp.json.return_value = {
        "ok": True,
        "result": [
            {
                "update_id": 2,
                "callback_query": {
                    "id": "cq_real",
                    "from": {"id": 12345678},  # Authorized
                    "data": "perm_mocked:deny",
                },
            }
        ],
    }

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post, \
         patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get, \
         patch("uuid.uuid4") as mock_uuid:
        mock_uuid.return_value.hex = "mocked"
        mock_post.return_value = send_resp
        mock_get.side_effect = [unauth_resp, auth_resp]

        decision = await bridge.request_approval(
            tool_name="delete_file",
            details={"path": "important.py"},
            timeout=5.0,
        )

        # The unauthorized callback was ignored, only authorized 'deny' was accepted!
        assert decision == "deny"


@pytest.mark.asyncio
async def test_telegram_prompter_yolo_decision():
    bridge = MagicMock(spec=TelegramBridge)
    bridge.request_approval = AsyncMock(return_value="yolo")

    prompter = TelegramPrompter(bridge=bridge)
    decision = await prompter({"tool": "write_file", "path": "test.txt"})

    assert decision == PermissionDecision.ALLOW_ALL_YOLO


@pytest.mark.asyncio
async def test_permission_controller_handles_yolo_mode():
    async def mock_prompter(details: dict) -> PermissionDecision:
        return PermissionDecision.ALLOW_ALL_YOLO

    perms = PermissionController(yolo_mode=False, prompter=mock_prompter)
    d1 = await perms.request_permission("run_command", PermissionTier.TIER_2_DESTRUCTIVE, {"command": "rm -rf"})
    assert d1 == PermissionDecision.ALLOW
    assert perms.yolo_mode is True

    # Subsequent request is auto-approved without prompting because yolo_mode is True
    d2 = await perms.request_permission("delete_file", PermissionTier.TIER_2_DESTRUCTIVE, {"path": "abc"})
    assert d2 == PermissionDecision.ALLOW


@pytest.mark.asyncio
async def test_hybrid_prompter_fastest_wins():
    # Terminal is fast, Telegram is slow
    def fast_terminal(details: dict) -> PermissionDecision:
        return PermissionDecision.ALLOW

    bridge = MagicMock(spec=TelegramBridge)
    async def slow_telegram(tool_name, details, timeout):
        await asyncio.sleep(2.0)
        return "deny"
    bridge.request_approval = slow_telegram

    prompter = HybridPrompter(
        terminal_prompter=fast_terminal,
        telegram_prompter=TelegramPrompter(bridge=bridge),
    )

    decision = await prompter({"tool": "test_tool"})
    assert decision == PermissionDecision.ALLOW


@pytest.mark.asyncio
async def test_command_listener_status_and_ping(tmp_path: Path):
    bridge = MagicMock(spec=TelegramBridge)
    bridge.send_notification = AsyncMock(return_value=True)

    listener = TelegramCommandListener(target_dir=tmp_path, bridge=bridge)

    await listener.handle_command("/ping")
    assert bridge.send_notification.called
    assert "Pong" in bridge.send_notification.call_args[0][0]

    await listener.handle_command("/status")
    assert bridge.send_notification.called
    assert "FRIDAY & JARVIS" in bridge.send_notification.call_args[0][0]

    await listener.handle_command("/yolo on")
    assert listener.yolo_mode is True

    await listener.handle_command("/yolo off")
    assert listener.yolo_mode is False


def test_cli_telegram_status_and_enable(tmp_path: Path):
    runner = CliRunner()

    res_status = runner.invoke(app, ["telegram", "status"])
    assert res_status.exit_code == 0
    assert "Telegram Entegrasyon Durumu" in res_status.output

    res_enable = runner.invoke(app, ["telegram", "enable", str(tmp_path)])
    assert res_enable.exit_code == 0
    assert "etkinleştirildi" in res_enable.output

    res_disable = runner.invoke(app, ["telegram", "disable", str(tmp_path)])
    assert res_disable.exit_code == 0
    assert "devre dışı bırakıldı" in res_disable.output


@pytest.mark.asyncio
async def test_telegram_approval_indefinite_waiting():
    bridge = TelegramBridge(bot_token="test_token", chat_id="12345678")

    send_resp = MagicMock()
    send_resp.json.return_value = {"ok": True, "result": {"message_id": 999}}

    # First polling check has no updates, second polling check receives user tap
    empty_resp = MagicMock()
    empty_resp.json.return_value = {"ok": True, "result": []}

    tap_resp = MagicMock()
    tap_resp.json.return_value = {
        "ok": True,
        "result": [
            {
                "update_id": 1,
                "callback_query": {
                    "id": "cq_1",
                    "from": {"id": 12345678},
                    "data": "perm_mocked:allow",
                },
            }
        ],
    }

    answer_resp = MagicMock()
    answer_resp.json.return_value = {"ok": True}

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post, \
         patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get, \
         patch("uuid.uuid4") as mock_uuid:
        mock_uuid.return_value.hex = "mocked"
        mock_post.side_effect = [send_resp, answer_resp, MagicMock()]
        mock_get.side_effect = [empty_resp, tap_resp]

        # timeout=None means indefinite waiting without auto-denying
        decision = await bridge.request_approval(
            tool_name="bash",
            details={"command": "npm install"},
            timeout=None,
        )

        assert decision == "allow"


@pytest.mark.asyncio
async def test_telegram_send_notification_with_permission_buttons():
    bridge = TelegramBridge(bot_token="test_token", chat_id="12345678")
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"ok": True, "result": {"message_id": 777}}

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp
        success = await bridge.send_notification("Onay gerekiyor", title="Yetki", event="izin")
        assert success is True
        assert mock_post.called

        # Verify reply_markup with buttons is present
        call_kwargs = mock_post.call_args[1]
        data = call_kwargs.get("data") or call_kwargs.get("json", {})
        assert "reply_markup" in data


@pytest.mark.asyncio
async def test_telegram_approval_text_reply():
    bridge = TelegramBridge(bot_token="test_token", chat_id="12345678")

    send_resp = MagicMock()
    send_resp.json.return_value = {"ok": True, "result": {"message_id": 888}}

    text_resp = MagicMock()
    text_resp.json.return_value = {
        "ok": True,
        "result": [
            {
                "update_id": 1,
                "message": {
                    "message_id": 889,
                    "from": {"id": 12345678},
                    "text": "Onay",
                },
            }
        ],
    }

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post, \
         patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get, \
         patch("uuid.uuid4") as mock_uuid:
        mock_uuid.return_value.hex = "mocked_text"
        mock_post.return_value = send_resp
        mock_get.return_value = text_resp

        decision = await bridge.request_approval(
            tool_name="shell",
            details={"command": "npm test"},
            timeout=5.0,
        )

        assert decision == "allow"


