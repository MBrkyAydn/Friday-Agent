import asyncio
import uuid
from typing import Any, Dict, Optional
from friday.core.permissions import PermissionDecision
from friday.dashboard.bus_bridge import ConnectionManager


class DashboardPrompter:
    def __init__(self, manager: Optional[ConnectionManager] = None) -> None:
        self.manager = manager
        self.pending_requests: Dict[str, asyncio.Future[PermissionDecision]] = {}
        self.pending_details: Dict[str, Dict[str, Any]] = {}

    async def __call__(self, details: Dict[str, Any]) -> PermissionDecision:
        req_id = str(uuid.uuid4())[:8]
        loop = asyncio.get_running_loop()
        fut: asyncio.Future[PermissionDecision] = loop.create_future()
        self.pending_requests[req_id] = fut
        self.pending_details[req_id] = details

        # Broadcast via WebSocket if manager is present
        if self.manager:
            try:
                await self.manager.broadcast({
                    "type": "permission_request",
                    "request_id": req_id,
                    "tool": details.get("tool", "unknown"),
                    "details": details,
                })
            except Exception:
                pass

        try:
            decision = await fut
            return decision
        finally:
            self.pending_requests.pop(req_id, None)
            self.pending_details.pop(req_id, None)

    def resolve(self, req_id: str, decision: PermissionDecision) -> bool:
        if req_id in self.pending_requests and not self.pending_requests[req_id].done():
            self.pending_requests[req_id].set_result(decision)
            return True
        return False
