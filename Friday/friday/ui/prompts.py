from typing import Any, Callable, Dict, Optional
from rich.console import Console
from friday.core.permissions import PermissionDecision


class TerminalPrompter:
    """Prompts the user interactively in the terminal for guarded tool permission decisions."""

    def __init__(
        self,
        console: Optional[Console] = None,
        input_fn: Optional[Callable[[str], str]] = None,
    ) -> None:
        self.console = console or Console()
        self.input_fn = input_fn or input

    async def __call__(self, details: Dict[str, Any]) -> PermissionDecision:
        tool_name = details.get("tool") or details.get("tool_name") or "guarded_action"
        target = details.get("path") or details.get("command") or ""
        self.console.print(
            f"\n[bold yellow]Guarded Action Required:[/bold yellow] [cyan]{tool_name}[/cyan] -> [white]{target}[/white]"
        )

        prompt_text = "Allow this action? [y] Yes  [n] No  [a] Always allow for this target: "
        choice = self.input_fn(prompt_text).strip().lower()

        if choice in ("y", "yes"):
            return PermissionDecision.ALLOW
        elif choice in ("a", "always"):
            return PermissionDecision.ALLOW_ALWAYS
        else:
            return PermissionDecision.DENY
