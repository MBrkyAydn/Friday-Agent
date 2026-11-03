import sys
import json
from typing import Optional
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from friday.core.bus import (
    EventBus,
    AgentThoughtEvent,
    StreamChunkEvent,
    ToolCallRequestedEvent,
    ToolResultEvent,
    TaskDoneEvent,
    TaskBlockedEvent,
    SubagentProgressEvent,
    LLMFallbackEvent,
)


def _safe_symbol(symbol: str, fallback: str) -> str:
    try:
        encoding = getattr(sys.stdout, "encoding", "utf-8") or "utf-8"
        symbol.encode(encoding)
        return symbol
    except (UnicodeEncodeError, LookupError):
        return fallback


class UIRenderer:
    """Rich event bus renderer for real-time terminal display."""

    def __init__(self, bus: EventBus, console: Optional[Console] = None) -> None:
        self.bus = bus
        self.console = console or Console()
        self._subscribe_all()

    def _subscribe_all(self) -> None:
        self.bus.subscribe(AgentThoughtEvent, self.on_thought)
        self.bus.subscribe(StreamChunkEvent, self.on_stream_chunk)
        self.bus.subscribe(ToolCallRequestedEvent, self.on_tool_requested)
        self.bus.subscribe(ToolResultEvent, self.on_tool_result)
        self.bus.subscribe(TaskDoneEvent, self.on_task_done)
        self.bus.subscribe(TaskBlockedEvent, self.on_task_blocked)
        self.bus.subscribe(SubagentProgressEvent, self.on_subagent_progress)
        self.bus.subscribe(LLMFallbackEvent, self.on_llm_fallback)

    async def on_llm_fallback(self, event: LLMFallbackEvent) -> None:
        self.console.print(
            f"[bold yellow][FALLBACK][/bold yellow] Primary profile '{event.from_profile}' failed. "
            f"Falling back to '{event.to_profile}' (Reason: {event.reason})"
        )

    async def on_thought(self, event: AgentThoughtEvent) -> None:
        self.console.print(f"[bold cyan]FRIDAY:[/bold cyan] {event.thought}")

    async def on_stream_chunk(self, event: StreamChunkEvent) -> None:
        self.console.print(event.chunk, end="")

    async def on_tool_requested(self, event: ToolCallRequestedEvent) -> None:
        args_formatted = json.dumps(event.arguments, indent=2) if event.arguments else "{}"
        self.console.print(
            Panel(
                f"[yellow]{args_formatted}[/yellow]",
                title=f"[bold yellow]Tool Call: {event.tool_name} ({event.tool_call_id})[/bold yellow]",
                border_style="yellow",
            )
        )

    async def on_tool_result(self, event: ToolResultEvent) -> None:
        if event.success:
            mark = _safe_symbol("✓", "[OK]")
            self.console.print(
                f"[bold green]{mark} [{event.tool_name}][/bold green] {event.output.strip()}"
            )
        else:
            mark = _safe_symbol("✗", "[ERROR]")
            self.console.print(
                f"[bold red]{mark} [{event.tool_name}][/bold red] Error: {event.error}"
            )

    async def on_task_done(self, event: TaskDoneEvent) -> None:
        msg = f"[bold green][DONE][/bold green] {event.summary}"
        if event.evidence:
            msg += f"\n[dim]Evidence: {event.evidence.strip()}[/dim]"
        self.console.print(Panel(msg, border_style="green"))

    async def on_task_blocked(self, event: TaskBlockedEvent) -> None:
        msg = f"[bold red][BLOCKED][/bold red] {event.reason}"
        if event.diagnostics:
            msg += f"\n[dim]Diagnostics: {event.diagnostics.strip()}[/dim]"
        self.console.print(Panel(msg, border_style="red"))

    async def on_subagent_progress(self, event: SubagentProgressEvent) -> None:
        self.console.print(
            f"[magenta]Subagent [{event.role}:{event.subagent_id}]:[/magenta] {event.message}"
        )
