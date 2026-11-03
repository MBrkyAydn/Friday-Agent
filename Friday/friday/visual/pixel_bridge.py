import asyncio
import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
import uuid
import httpx

from friday.core.bus import (
    EventBus,
    ToolCallRequestedEvent,
    ToolResultEvent,
    PermissionPromptEvent,
    TaskDoneEvent,
    TaskBlockedEvent,
    UserPromptEvent,
)

logger = logging.getLogger("friday.visual.pixel_bridge")


class PixelAgentsBridge:
    """Non-blocking, fail-open bridge translating FRIDAY EventBus events

    into Pixel Agents hook payloads (POST /api/hooks/:provider).
    """

    def __init__(
        self,
        bus: EventBus,
        workspace_path: str,
        provider: str = "claude",
        session_id: Optional[str] = None,
        max_queue_size: int = 100,
    ) -> None:
        self.bus = bus
        self.workspace_path = workspace_path
        self.provider = provider
        self.session_id = session_id or f"friday-{uuid.uuid4().hex[:8]}"
        self._queue: asyncio.Queue[Dict[str, Any]] = asyncio.Queue(maxsize=max_queue_size)
        self._worker_task: Optional[asyncio.Task[None]] = None
        self._client: Optional[httpx.AsyncClient] = None
        self._unsubscribers: list = []
        self._is_running = False
        self._cooldown_until: float = 0.0

        self._setup_listeners()

    def _setup_listeners(self) -> None:
        self._unsubscribers.append(
            self.bus.subscribe(UserPromptEvent, self._handle_user_prompt)
        )
        self._unsubscribers.append(
            self.bus.subscribe(ToolCallRequestedEvent, self._handle_tool_requested)
        )
        self._unsubscribers.append(
            self.bus.subscribe(ToolResultEvent, self._handle_tool_result)
        )
        self._unsubscribers.append(
            self.bus.subscribe(PermissionPromptEvent, self._handle_permission_prompt)
        )
        self._unsubscribers.append(
            self.bus.subscribe(TaskDoneEvent, self._handle_task_done)
        )
        self._unsubscribers.append(
            self.bus.subscribe(TaskBlockedEvent, self._handle_task_blocked)
        )

    def read_server_config(self) -> Optional[Tuple[int, str]]:
        """Reads ~/.pixel-agents/server.json to obtain the active server port and auth token."""
        try:
            config_path = Path.home() / ".pixel-agents" / "server.json"
            if not config_path.is_file():
                return None
            data = json.loads(config_path.read_text(encoding="utf-8"))
            port = int(data.get("port", 0))
            token = str(data.get("token", ""))
            if port > 0 and token:
                return port, token
        except Exception as e:
            logger.debug(f"Failed to read pixel-agents server config: {e}")
        return None

    def _enqueue(self, payload: Dict[str, Any]) -> None:
        if not self._is_running:
            return
        payload["session_id"] = self.session_id
        try:
            self._queue.put_nowait(payload)
        except asyncio.QueueFull:
            try:
                self._queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
            try:
                self._queue.put_nowait(payload)
            except asyncio.QueueFull:
                pass

    async def _handle_user_prompt(self, event: UserPromptEvent) -> None:
        self._enqueue({
            "hook_event_name": "SessionStart",
            "source": "user_prompt",
            "cwd": self.workspace_path,
        })

    async def _handle_tool_requested(self, event: ToolCallRequestedEvent) -> None:
        tool_name = event.tool_name
        # Canonical normalization for Pixel Agents
        display_tool_name = "Bash" if tool_name in ("execute_command", "bash") else tool_name
        
        self._enqueue({
            "hook_event_name": "PreToolUse",
            "tool_name": display_tool_name,
            "tool_input": event.arguments,
        })

        if tool_name == "delegate_jarvis":
            self._enqueue({
                "hook_event_name": "SubagentStart",
                "agent_type": "Jarvis",
                "run_in_background": True,
                "tool_input": event.arguments,
            })

    async def _handle_tool_result(self, event: ToolResultEvent) -> None:
        self._enqueue({
            "hook_event_name": "PostToolUse",
            "tool_name": event.tool_name,
            "success": event.success,
        })

        if event.tool_name == "delegate_jarvis":
            self._enqueue({
                "hook_event_name": "SubagentStop",
                "agent_type": "Jarvis",
            })

    async def _handle_permission_prompt(self, event: PermissionPromptEvent) -> None:
        self._enqueue({
            "hook_event_name": "PermissionRequest",
            "prompt_id": event.prompt_id,
            "action_type": event.action_type,
        })

    async def _handle_task_done(self, event: TaskDoneEvent) -> None:
        self._enqueue({
            "hook_event_name": "Stop",
            "task_id": event.task_id,
        })

    async def _handle_task_blocked(self, event: TaskBlockedEvent) -> None:
        self._enqueue({
            "hook_event_name": "Stop",
            "task_id": event.task_id,
            "reason": "blocked",
        })

    async def _send_http_event(self, payload: Dict[str, Any]) -> bool:
        """Sends payload to Pixel Agents Fastify HTTP server."""
        cfg = self.read_server_config()
        if not cfg:
            return False

        port, token = cfg
        url = f"http://127.0.0.1:{port}/api/hooks/{self.provider}"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=2.0)

        try:
            resp = await self._client.post(url, json=payload, headers=headers)
            return resp.status_code in (200, 204)
        except Exception as e:
            logger.debug(f"Pixel agents hook POST failed silently: {e}")
            return False

    async def _worker_loop(self) -> None:
        while self._is_running:
            try:
                payload = await self._queue.get()
                if payload is None:
                    break
                await self._send_http_event(payload)
                self._queue.task_done()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.debug(f"Worker loop error: {e}")

    async def register_initial_session(self) -> None:
        """Emits initial SessionStart and idle Notification so FRIDAY and JARVIS appear in office."""
        self._enqueue({
            "hook_event_name": "SessionStart",
            "source": "startup",
            "cwd": self.workspace_path,
        })
        self._enqueue({
            "hook_event_name": "Notification",
            "notification_type": "idle_prompt",
        })

    async def start(self) -> None:
        if self._is_running:
            return
        self._is_running = True
        self._worker_task = asyncio.create_task(self._worker_loop())
        await self.register_initial_session()

    async def stop(self) -> None:
        self._is_running = False
        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
            self._worker_task = None

        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

        for unsub in self._unsubscribers:
            try:
                unsub()
            except Exception:
                pass
        self._unsubscribers.clear()
