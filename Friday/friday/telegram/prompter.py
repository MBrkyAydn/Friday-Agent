import asyncio
import inspect
import logging
from typing import Any, Callable, Dict, Optional

from friday.core.permissions import PermissionDecision, Prompter
from friday.telegram.bridge import TelegramBridge

logger = logging.getLogger("friday.telegram.prompter")


class TelegramPrompter:
    """Prompter implementation that sends an interactive 4-tier approval card to Telegram."""

    def __init__(
        self,
        bridge: Optional[TelegramBridge] = None,
        timeout: Optional[float] = None,
    ) -> None:
        self.bridge = bridge or TelegramBridge()
        self.timeout = timeout

    async def __call__(self, details: Dict[str, Any]) -> PermissionDecision:
        tool_name = details.get("tool") or details.get("tool_name") or "guarded_tool"
        choice = await self.bridge.request_approval(
            tool_name=tool_name,
            details=details,
            timeout=self.timeout,
        )
        if choice == "yolo":
            return PermissionDecision.ALLOW_ALL_YOLO
        elif choice == "allow_always":
            return PermissionDecision.ALLOW_ALWAYS
        elif choice == "allow":
            return PermissionDecision.ALLOW
        else:
            return PermissionDecision.DENY


class HybridPrompter:
    """
    Races terminal prompt and Telegram prompt in parallel.
    Whichever answers first (user tapping the button on Telegram or pressing a key in terminal)
    wins and cancels the pending prompter.
    """

    def __init__(
        self,
        terminal_prompter: Optional[Prompter] = None,
        telegram_prompter: Optional[TelegramPrompter] = None,
    ) -> None:
        self.terminal_prompter = terminal_prompter
        self.telegram_prompter = telegram_prompter

    async def __call__(self, details: Dict[str, Any]) -> PermissionDecision:
        if self.terminal_prompter is None and self.telegram_prompter is None:
            return PermissionDecision.ALLOW

        if self.terminal_prompter is None:
            assert self.telegram_prompter is not None
            return await self.telegram_prompter(details)

        if self.telegram_prompter is None:
            assert self.terminal_prompter is not None
            res = self.terminal_prompter(details)
            if inspect.isawaitable(res):
                res = await res
            return res

        # Both are active: race them
        async def run_terminal():
            try:
                res = self.terminal_prompter(details)
                if inspect.isawaitable(res):
                    res = await res
                return res
            except Exception as e:
                logger.debug("Terminal prompter error: %s", e)
                return PermissionDecision.DENY

        async def run_telegram():
            try:
                return await self.telegram_prompter(details)
            except Exception as e:
                logger.debug("Telegram prompter error: %s", e)
                return PermissionDecision.DENY

        task_term = asyncio.create_task(run_terminal())
        task_tg = asyncio.create_task(run_telegram())

        done, pending = await asyncio.wait(
            [task_term, task_tg],
            return_when=asyncio.FIRST_COMPLETED,
        )

        for p in pending:
            p.cancel()
            try:
                await p
            except (asyncio.CancelledError, Exception):
                pass

        first_task = list(done)[0]
        try:
            return first_task.result()
        except Exception:
            return PermissionDecision.DENY
