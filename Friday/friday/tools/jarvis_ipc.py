import asyncio
from pathlib import Path
from typing import Any, Dict, Optional

from friday.core.workspace import WorkspaceGuard
from friday.core.permissions import PermissionController, PermissionTier
from friday.core.shared_bus import SharedBusProtocol
from friday.tools.base import BaseTool, ToolResult


class DelegateJarvisTool(BaseTool):
    """Tool allowing FRIDAY to delegate tasks out-of-process to the JARVIS specialist worker."""

    name = "delegate_jarvis"
    description = (
        "Delegate a task out-of-process to the JARVIS specialist worker agent via SharedBus IPC mailboxes. "
        "JARVIS executes the task in its isolated environment and returns verified results."
    )
    tier = PermissionTier.TIER_0_SAFE
    parameters: Dict[str, Any] = {
        "type": "object",
        "properties": {
            "task": {
                "type": "string",
                "description": "Natural language instruction, command, or specifications for Jarvis to execute",
            },
            "action": {
                "type": "string",
                "description": "Action verb (default: 'execute_task')",
                "default": "execute_task",
            },
            "timeout": {
                "type": "number",
                "description": "Maximum seconds to wait for Jarvis to reply (default: 30.0)",
                "default": 30.0,
            },
        },
        "required": ["task"],
    }

    def __init__(
        self,
        workspace: WorkspaceGuard,
        permissions: PermissionController,
        shared_root: Optional[Path | str] = None,
        logs_root: Optional[Path | str] = None,
        default_timeout: float = 30.0,
        poll_interval: float = 0.2,
        router: Optional[Any] = None,
    ) -> None:
        super().__init__(workspace=workspace, permissions=permissions)
        self.router = router
        if shared_root is not None:
            self.shared_root = Path(shared_root).resolve()
        else:
            candidate = self.workspace.target_dir.parent / "Shared"
            if candidate.exists():
                self.shared_root = candidate.resolve()
            else:
                self.shared_root = Path("D:/AI-Agents/Shared").resolve()

        if logs_root is not None:
            self.logs_root = Path(logs_root).resolve()
        else:
            candidate = self.workspace.target_dir.parent / "Logs"
            if candidate.exists():
                self.logs_root = candidate.resolve()
            else:
                self.logs_root = Path("D:/AI-Agents/Logs").resolve()

        self.default_timeout = default_timeout
        self.poll_interval = poll_interval
        self.bus = SharedBusProtocol(
            shared_root=self.shared_root,
            logs_root=self.logs_root,
            agent_name="Friday",
        )

    async def execute(
        self,
        task: str = "",
        action: str = "execute_task",
        timeout: Optional[float] = None,
        **kwargs: Any,
    ) -> ToolResult:
        task_text = task or kwargs.get("task_description") or kwargs.get("prompt") or ""
        if not task_text and action != "ping":
            return ToolResult(
                success=False,
                error="Task instruction cannot be empty.",
            )

        effective_timeout = float(timeout) if timeout is not None else self.default_timeout
        poll_interval = min(self.poll_interval, max(0.01, effective_timeout / 10.0))

        # Payload construction
        payload: Dict[str, Any] = {
            "task": task_text,
            "workspace_path": str(self.workspace.target_dir),
        }
        for k, v in kwargs.items():
            if k not in ("task", "task_description", "prompt", "action", "timeout", "workspace_path"):
                payload[k] = v

        if self.router and hasattr(self.router, "get_active_profile"):
            active_prof = self.router.get_active_profile()
            payload["profile"] = active_prof
            if active_prof == "local":
                payload["force_local"] = True

        # Auto-ensure JARVIS worker daemon is active in background
        try:
            from friday.core.jarvis_daemon import ensure_jarvis_worker
            ensure_jarvis_worker(shared_root=self.shared_root, logs_root=self.logs_root)
        except Exception:
            pass

        try:
            msg_id = self.bus.send_message(
                recipient="Jarvis",
                action=action,
                payload=payload,
            )
        except Exception as exc:
            return ToolResult(
                success=False,
                error=f"Failed to dispatch message to Jarvis inbox: {exc}",
            )

        # Polling loop for response in friday_inbox
        loop = asyncio.get_event_loop()
        start_time = loop.time()

        while True:
            # Check friday_inbox for matching reply
            inbox_items = self.bus.read_inbox_files()
            for msg_file, msg_data in inbox_items:
                sender = msg_data.get("sender", "")
                msg_payload = msg_data.get("payload", {})
                in_reply_to = msg_payload.get("in_reply_to") or msg_data.get("in_reply_to")

                if sender == "Jarvis" and in_reply_to == msg_id:
                    # Response matched
                    reply_action = msg_data.get("action", "")
                    self.bus.archive_message(msg_file)

                    if reply_action == "task_completed":
                        result_str = (
                            msg_payload.get("result")
                            or msg_payload.get("output")
                            or msg_payload.get("summary")
                            or "Task completed successfully by Jarvis."
                        )
                        return ToolResult(success=True, output=str(result_str))
                    elif reply_action == "task_failed":
                        err_str = msg_payload.get("error") or msg_payload.get("result") or "Jarvis task execution failed."
                        return ToolResult(success=False, error=str(err_str))
                    else:
                        is_ok = bool(msg_payload.get("success", False))
                        res_str = msg_payload.get("result") or msg_payload.get("output") or ""
                        err_str = msg_payload.get("error")
                        return ToolResult(
                            success=is_ok,
                            output=str(res_str) if is_ok else "",
                            error=str(err_str) if not is_ok else None,
                        )

            elapsed = loop.time() - start_time
            if elapsed >= effective_timeout:
                return ToolResult(
                    success=False,
                    error=f"Timeout: JARVIS did not respond to task '{msg_id}' within {effective_timeout:.1f}s.",
                )

            await asyncio.sleep(poll_interval)
