import inspect
from enum import Enum
from typing import Any, Callable, Coroutine, Dict, Union


class PermissionTier(int, Enum):
    TIER_0_SAFE = 0       # Reads, searches, git status
    TIER_1_GUARDED = 1    # File writes, standard test runs
    TIER_2_DESTRUCTIVE = 2 # Arbitrary shell commands, git reset, deletes


class PermissionDecision(str, Enum):
    ALLOW = "allow"
    DENY = "deny"
    ALLOW_ALWAYS = "allow_always"
    ALLOW_ALL_YOLO = "yolo"


Prompter = Union[
    Callable[[Dict[str, Any]], Coroutine[Any, Any, PermissionDecision]],
    Callable[[Dict[str, Any]], PermissionDecision],
]


class PermissionController:
    def __init__(self, yolo_mode: bool = False, prompter: Prompter | None = None) -> None:
        self.yolo_mode = yolo_mode
        self.prompter = prompter
        self._session_whitelist: set[str] = set()

    async def request_permission(
        self,
        tool_name: str,
        tier: PermissionTier,
        details: Dict[str, Any],
    ) -> PermissionDecision:
        if tier == PermissionTier.TIER_0_SAFE:
            return PermissionDecision.ALLOW

        if self.yolo_mode:
            return PermissionDecision.ALLOW

        target_identifier = details.get("path") or details.get("command") or ""
        whitelist_key = f"{tool_name}:{target_identifier}"
        if whitelist_key in self._session_whitelist or tool_name in self._session_whitelist:
            return PermissionDecision.ALLOW

        if self.prompter is None:
            return PermissionDecision.ALLOW

        decision = self.prompter(details)
        if inspect.isawaitable(decision):
            decision = await decision

        if decision in (PermissionDecision.ALLOW_ALL_YOLO, "yolo"):
            self.yolo_mode = True
            return PermissionDecision.ALLOW

        if decision in (PermissionDecision.ALLOW_ALWAYS, "allow_always"):
            self._session_whitelist.add(whitelist_key)
            self._session_whitelist.add(tool_name)
            return PermissionDecision.ALLOW

        return decision
