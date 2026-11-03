"""JARVIS Worker Background Daemon Lifecycle Manager.

Allows FRIDAY to detect, start, monitor, and stop the JARVIS specialist worker
as a silent background daemon (no pop-up terminal window) on Windows and Unix.
"""

from __future__ import annotations

import logging
import os
import signal
import subprocess
import sys
from pathlib import Path
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

DEFAULT_SHARED_ROOT = Path("D:/AI-Agents/Shared")
DEFAULT_LOGS_ROOT = Path("D:/AI-Agents/Logs")


def resolve_daemon_paths(
    shared_root: Optional[Path | str] = None,
    logs_root: Optional[Path | str] = None,
) -> Tuple[Path, Path]:
    """Resolve Shared and Logs directories."""
    if shared_root:
        s_root = Path(shared_root).resolve()
    else:
        s_root = DEFAULT_SHARED_ROOT
        if not s_root.exists():
            fallback_shared = Path.cwd().parent / "Shared"
            if fallback_shared.exists():
                s_root = fallback_shared.resolve()

    if logs_root:
        l_root = Path(logs_root).resolve()
    else:
        l_root = DEFAULT_LOGS_ROOT
        if not l_root.exists():
            fallback_logs = Path.cwd().parent / "Logs"
            if fallback_logs.exists():
                l_root = fallback_logs.resolve()

    s_root.mkdir(parents=True, exist_ok=True)
    l_root.mkdir(parents=True, exist_ok=True)
    return s_root, l_root


def is_pid_alive(pid: int) -> bool:
    """Check whether a process with the given PID is actively running."""
    if pid <= 0:
        return False

    if sys.platform == "win32":
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
            if handle:
                exit_code = ctypes.c_ulong()
                kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code))
                kernel32.CloseHandle(handle)
                # STILL_ACTIVE = 259
                return exit_code.value == 259
            return False
        except Exception:
            try:
                os.kill(pid, 0)
                return True
            except (OSError, ProcessLookupError):
                return False
    else:
        try:
            os.kill(pid, 0)
            return True
        except (OSError, ProcessLookupError):
            return False


def is_jarvis_worker_running(shared_root: Optional[Path | str] = None) -> Tuple[bool, Optional[int]]:
    """Check if JARVIS worker daemon is running.

    Returns:
        (True, pid) if active, (False, None) if inactive.
    """
    s_root, _ = resolve_daemon_paths(shared_root)
    pid_file = s_root / "state" / "jarvis_worker.pid"

    if not pid_file.exists():
        return False, None

    try:
        pid = int(pid_file.read_text(encoding="utf-8").strip())
        if is_pid_alive(pid):
            return True, pid
        else:
            # Stale PID file; clean it up
            logger.debug("Cleaning up stale JARVIS worker PID file (%d)", pid)
            pid_file.unlink(missing_ok=True)
            return False, None
    except Exception as exc:
        logger.debug("Error reading PID file %s: %s", pid_file, exc)
        return False, None


def start_jarvis_worker(
    shared_root: Optional[Path | str] = None,
    logs_root: Optional[Path | str] = None,
) -> Optional[int]:
    """Start JARVIS worker as a detached background daemon without showing a terminal window."""
    running, existing_pid = is_jarvis_worker_running(shared_root)
    if running and existing_pid:
        logger.info("JARVIS worker is already running (PID: %d)", existing_pid)
        return existing_pid

    s_root, l_root = resolve_daemon_paths(shared_root, logs_root)
    state_dir = s_root / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    pid_file = state_dir / "jarvis_worker.pid"

    log_path = l_root / "jarvis.log"

    creationflags = 0
    if sys.platform == "win32":
        # Detached process, no console window
        CREATE_NO_WINDOW = 0x08000000
        DETACHED_PROCESS = 0x00000008
        creationflags = CREATE_NO_WINDOW | DETACHED_PROCESS

    cmd = [
        sys.executable,
        "-m",
        "jarvis",
        "worker",
        "--shared-root",
        str(s_root),
        "--logs-root",
        str(l_root),
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
        logger.info("Started JARVIS worker background daemon (PID: %d)", pid)
        return pid
    except Exception as exc:
        logger.error("Failed to start JARVIS background daemon: %s", exc)
        return None


def stop_jarvis_worker(shared_root: Optional[Path | str] = None) -> bool:
    """Stop the running JARVIS worker background daemon."""
    running, pid = is_jarvis_worker_running(shared_root)
    s_root, _ = resolve_daemon_paths(shared_root)
    pid_file = s_root / "state" / "jarvis_worker.pid"

    if not running or not pid:
        if pid_file.exists():
            pid_file.unlink(missing_ok=True)
        return False

    try:
        if sys.platform == "win32":
            subprocess.run(
                ["taskkill", "/F", "/PID", str(pid)],
                capture_output=True,
                check=False,
            )
        else:
            os.kill(pid, signal.SIGTERM)
        pid_file.unlink(missing_ok=True)
        logger.info("Stopped JARVIS worker daemon (PID: %d)", pid)
        return True
    except Exception as exc:
        logger.warning("Error stopping JARVIS worker (PID: %d): %s", pid, exc)
        if pid_file.exists():
            pid_file.unlink(missing_ok=True)
        return False


def ensure_jarvis_worker(
    shared_root: Optional[Path | str] = None,
    logs_root: Optional[Path | str] = None,
) -> Tuple[bool, Optional[int]]:
    """Ensure JARVIS worker is active, starting it in background if not already running.

    Returns:
        (is_running, pid)
    """
    running, pid = is_jarvis_worker_running(shared_root)
    if running and pid:
        return True, pid

    new_pid = start_jarvis_worker(shared_root, logs_root)
    if new_pid and is_pid_alive(new_pid):
        return True, new_pid
    return False, None
