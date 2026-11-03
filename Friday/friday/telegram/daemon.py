import os
import sys
import logging
import subprocess
from pathlib import Path
from typing import Optional, Tuple

from friday.core.jarvis_daemon import is_pid_alive, resolve_daemon_paths

logger = logging.getLogger("friday.telegram.daemon")


def get_telegram_pid_file(shared_root: Optional[Path | str] = None) -> Tuple[Path, Path]:
    s_root, l_root = resolve_daemon_paths(shared_root)
    state_dir = s_root / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    return state_dir / "telegram_listener.pid", l_root / "telegram.log"


def is_telegram_daemon_running(shared_root: Optional[Path | str] = None) -> Tuple[bool, Optional[int]]:
    pid_file, _ = get_telegram_pid_file(shared_root)
    if not pid_file.exists():
        return False, None

    try:
        pid = int(pid_file.read_text(encoding="utf-8").strip())
        if is_pid_alive(pid):
            return True, pid
        else:
            pid_file.unlink(missing_ok=True)
            return False, None
    except Exception:
        return False, None


def start_telegram_daemon(
    target_dir: Optional[Path | str] = None,
    shared_root: Optional[Path | str] = None,
) -> Optional[int]:
    """Start FRIDAY Telegram command listener as a silent background daemon."""
    running, existing_pid = is_telegram_daemon_running(shared_root)
    if running and existing_pid:
        return existing_pid

    pid_file, log_path = get_telegram_pid_file(shared_root)
    ws_dir = Path(target_dir).resolve() if target_dir else Path(r"C:\Users\brkya\Desktop\deneme")

    creationflags = 0
    if sys.platform == "win32":
        CREATE_NO_WINDOW = 0x08000000
        DETACHED_PROCESS = 0x00000008
        creationflags = CREATE_NO_WINDOW | DETACHED_PROCESS

    cmd = [
        sys.executable,
        "-m",
        "friday.telegram.listener",
        str(ws_dir),
    ]


    try:
        log_file = open(log_path, "a", encoding="utf-8")
        proc = subprocess.Popen(
            cmd,
            stdout=log_file,
            stderr=log_file,
            creationflags=creationflags,
            start_new_session=(sys.platform != "win32"),
        )
        pid = proc.pid
        pid_file.write_text(str(pid), encoding="utf-8")
        logger.info("Started FRIDAY Telegram daemon (PID: %d)", pid)
        return pid
    except Exception as exc:
        logger.error("Failed to start Telegram daemon: %s", exc)
        return None


def stop_telegram_daemon(shared_root: Optional[Path | str] = None) -> bool:
    """Stop FRIDAY Telegram daemon."""
    running, pid = is_telegram_daemon_running(shared_root)
    pid_file, _ = get_telegram_pid_file(shared_root)
    if not running or not pid:
        pid_file.unlink(missing_ok=True)
        return False

    try:
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True, timeout=5)
        else:
            os.kill(pid, 15)
        pid_file.unlink(missing_ok=True)
        return True
    except Exception:
        pid_file.unlink(missing_ok=True)
        return False
