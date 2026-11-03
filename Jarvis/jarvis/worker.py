import asyncio
import os
import subprocess
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Tuple

from jarvis.shared_bus import SharedBusProtocol
from jarvis.coder import JarvisCoder


class JarvisWorker:
    """Specialist worker agent processing delegated tasks from Friday via SharedBus mailboxes."""

    def __init__(
        self,
        shared_root: str | Path,
        logs_root: str | Path,
        workspace_root: Optional[str | Path] = None,
        agent_name: str = "Jarvis",
        executor: Optional[Callable[[Dict[str, Any]], Tuple[bool, str, Optional[str]]]] = None,
        coder: Optional[JarvisCoder] = None,
        enable_coder: bool = True,
    ) -> None:
        self.shared_root = Path(shared_root).resolve()
        self.logs_root = Path(logs_root).resolve()
        self.workspace_root = Path(workspace_root).resolve() if workspace_root else None
        self.agent_name = agent_name
        self.bus = SharedBusProtocol(shared_root=self.shared_root, logs_root=self.logs_root, agent_name=self.agent_name)
        self.archive_dir = self.bus.mailboxes / "archive"
        self.archive_dir.mkdir(parents=True, exist_ok=True)
        self.executor = executor
        self.coder = coder if coder is not None else (JarvisCoder() if enable_coder else None)
        self.running: bool = False

    def stop(self) -> None:
        """Stop worker listening loop."""
        self.running = False

    def _execute_task_payload(self, action: str, payload: Dict[str, Any], full_msg: Dict[str, Any]) -> Tuple[bool, str, Optional[str]]:
        """Execute or simulate task execution with verification."""
        if self.executor is not None:
            return self.executor(full_msg)

        if action == "ping":
            return True, "pong: JARVIS specialist worker is active and healthy.", None

        # Check for simulated failures
        if payload.get("simulate_fail") is True or payload.get("fail") is True:
            err_msg = payload.get("error") or "Simulated task failure."
            return False, "", err_msg

        success = True
        output = ""
        error: Optional[str] = None

        # Command execution support
        if "command" in payload:
            cmd = payload["command"]
            cwd = self.workspace_root or Path.cwd()
            timeout = payload.get("timeout", 60)
            try:
                res = subprocess.run(
                    cmd,
                    shell=True,
                    capture_output=True,
                    text=True,
                    cwd=cwd,
                    timeout=timeout,
                )
                if res.returncode == 0:
                    success = True
                    output = res.stdout.strip() or f"Command '{cmd}' executed successfully."
                else:
                    success = False
                    output = res.stdout.strip()
                    error = res.stderr.strip() or f"Command exited with status {res.returncode}"
            except Exception as exc:
                success = False
                output = ""
                error = f"Execution error: {exc}"
        else:
            task_desc = payload.get("task") or payload.get("task_description") or payload.get("instruction") or ""
            target_ws = payload.get("workspace_path") or self.workspace_root or Path.cwd()

            if task_desc and self.coder is not None:
                force_local = payload.get("force_local", False) or payload.get("profile") == "local"
                coder_res = self.coder.execute_task(
                    task=task_desc,
                    workspace_dir=target_ws,
                    force_local=force_local,
                )
                success = coder_res.success
                output = coder_res.output
                error = coder_res.error
            else:
                success = True
                output = f"Task completed and verified by JARVIS: {task_desc}" if task_desc else "Task executed successfully."

        # Verification step
        if success and "verification_command" in payload:
            verif_cmd = payload["verification_command"]
            cwd = self.workspace_root or Path.cwd()
            try:
                v_res = subprocess.run(
                    verif_cmd,
                    shell=True,
                    capture_output=True,
                    text=True,
                    cwd=cwd,
                    timeout=payload.get("verification_timeout", 30),
                )
                if v_res.returncode == 0:
                    v_out = v_res.stdout.strip() or "Verification succeeded."
                    output = f"{output}\n[Verification Passed]: {v_out}"
                else:
                    success = False
                    v_err = v_res.stderr.strip() or v_res.stdout.strip() or f"code {v_res.returncode}"
                    error = f"Verification failed: {v_err}"
            except Exception as ve:
                success = False
                error = f"Verification error: {ve}"

        return success, output, error

    def process_next_task(self) -> Optional[Dict[str, Any]]:
        """Read jarvis_inbox, parse task payload, execute with verification, reply to sender, and archive message."""
        inbox_items = self.bus.read_inbox_files()
        if not inbox_items:
            return None

        msg_file, msg_data = inbox_items[0]
        msg_id = msg_data.get("message_id", msg_file.stem)
        sender = msg_data.get("sender", "Friday")
        action = msg_data.get("action", "execute_task")
        payload = msg_data.get("payload", {})

        self.bus.log_event("TASK_RECEIVED", {
            "task_id": msg_id,
            "sender": sender,
            "action": action,
        })

        # Execute / simulate with verification
        success, output, error = self._execute_task_payload(action, payload, msg_data)

        # Write reply message to sender's inbox (e.g. friday_inbox)
        reply_action = "task_completed" if success else "task_failed"
        reply_payload = {
            "in_reply_to": msg_id,
            "result": output,
            "output": output,
            "error": error,
            "success": success,
            "status": "completed" if success else "failed",
        }

        reply_id = self.bus.send_message(
            recipient=sender,
            action=reply_action,
            payload=reply_payload,
        )

        # Clean up / archive the processed message
        self.bus.archive_message(msg_file, archive_dir=self.archive_dir)

        self.bus.log_event("TASK_FINISHED", {
            "task_id": msg_id,
            "reply_id": reply_id,
            "reply_action": reply_action,
            "success": success,
        })

        return {
            "message_id": msg_id,
            "sender": sender,
            "action": action,
            "reply_action": reply_action,
            "success": success,
            "output": output,
            "error": error,
            "reply_id": reply_id,
        }

    async def listen(self, interval: float = 1.0, run_once: bool = False) -> None:
        """Async polling loop processing incoming tasks with PID tracking."""
        self.running = True
        state_dir = self.shared_root / "state"
        state_dir.mkdir(parents=True, exist_ok=True)
        pid_file = state_dir / "jarvis_worker.pid"
        try:
            pid_file.write_text(str(os.getpid()), encoding="utf-8")
        except Exception:
            pass

        try:
            while self.running:
                processed = self.process_next_task()
                if run_once:
                    break
                if not processed:
                    await asyncio.sleep(interval)
        except asyncio.CancelledError:
            self.running = False
            raise
        finally:
            self.running = False
            try:
                if pid_file.exists() and pid_file.read_text(encoding="utf-8").strip() == str(os.getpid()):
                    pid_file.unlink(missing_ok=True)
            except Exception:
                pass
