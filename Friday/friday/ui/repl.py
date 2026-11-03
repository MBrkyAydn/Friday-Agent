import asyncio
from typing import Optional
from rich.console import Console
from rich.table import Table

from friday.core.bus import (
    EventBus,
    TaskDoneEvent,
    TaskBlockedEvent,
)
from friday.core.workspace import WorkspaceGuard
from friday.core.permissions import PermissionController
from friday.core.verifier import TaskStatus
from friday.ui.renderer import UIRenderer


class FridayREPL:
    """Prompt Toolkit and Rich interactive REPL shell for FRIDAY."""

    def __init__(
        self,
        agent: any,
        workspace: WorkspaceGuard,
        bus: EventBus,
        perms: PermissionController,
        renderer: UIRenderer,
        console: Optional[Console] = None,
        session: Optional[any] = None,
        session_manager: Optional[any] = None,
        subagent_pool: Optional[any] = None,
    ) -> None:
        self.agent = agent
        self.workspace = workspace
        self.bus = bus
        self.perms = perms
        self.renderer = renderer
        self.console = console or Console()
        self.session = session
        self.session_manager = session_manager
        self.subagent_pool = subagent_pool

    def get_prompt_string(self) -> str:
        project_name = self.workspace.target_dir.name or "project"
        return f"FRIDAY [{project_name}] ❯ "

    async def handle_input(self, user_input: str) -> bool:
        cmd = user_input.strip()
        if not cmd:
            return True

        if cmd == "/help":
            self._print_help()
            return True

        if cmd == "/yolo":
            self.perms.yolo_mode = not self.perms.yolo_mode
            status_str = "enabled" if self.perms.yolo_mode else "disabled"
            self.console.print(f"[bold cyan]YOLO mode {status_str}.[/bold cyan]")
            return True

        if cmd == "/status":
            self._print_status()
            return True

        if cmd == "/clear":
            self.console.clear()
            return True

        if cmd == "/reset":
            if getattr(self, "session", None) is not None:
                self.session.turns.clear()
                if getattr(self, "session_manager", None) is not None:
                    self.session_manager.save_session(self.session, target_dir=self.workspace.target_dir)
            self.console.print("[bold cyan]Conversation history reset.[/bold cyan]")
            return True

        if cmd == "/verify":
            await self._run_verify()
            return True

        if cmd.startswith("/use"):
            parts = cmd.split(maxsplit=1)
            if len(parts) > 1 and parts[1].strip():
                profile = parts[1].strip().lower()
                llm = getattr(self.agent, "llm", None)
                if hasattr(llm, "set_active_profile"):
                    try:
                        llm.set_active_profile(profile)
                        active_provider = getattr(llm, "active_provider", None)
                        model_name = getattr(getattr(active_provider, "config", None), "model", profile)
                        self.console.print(f"[bold cyan]Switched active profile to: {profile} ({model_name})[/bold cyan]")
                    except Exception as e:
                        self.console.print(f"[bold red]{e}[/bold red]")
                else:
                    self.console.print("[bold yellow]Multi-LLM Router is not active on current agent.[/bold yellow]")
            else:
                self.console.print("[yellow]Usage: /use <local|gemini-free|gemini-paid|groq|deepseek|claude>[/yellow]")
            return True

        if cmd.startswith("/model"):
            parts = cmd.split(maxsplit=1)
            if len(parts) > 1 and parts[1].strip():
                new_model = parts[1].strip()
                llm = getattr(self.agent, "llm", None)
                if llm is not None and hasattr(llm, "config"):
                    llm.config.model = new_model
                self.console.print(f"[bold cyan]Model switched to: {new_model}[/bold cyan]")
            else:
                llm = getattr(self.agent, "llm", None)
                current_model = getattr(getattr(llm, "config", None), "model", "unknown")
                self.console.print(f"[bold cyan]Current model: {current_model}[/bold cyan]")
            return True

        if cmd == "/subagents":
            self._print_subagents()
            return True

        if cmd == "/history":
            self._print_history()
            return True

        if cmd in ("/exit", "/quit"):
            self.console.print("[bold yellow]Exiting FRIDAY. Goodbye![/bold yellow]")
            return False

        if cmd.startswith("/"):
            self.console.print(f"[bold red]Unknown command: '{cmd}'. Type /help for available commands.[/bold red]")
            return True

        # Dispatch regular natural language instruction to agent
        if getattr(self, "session", None) is not None:
            status = await self.agent.run_turn(cmd, session=self.session)
        else:
            status = await self.agent.run_turn(cmd)
        if getattr(self, "session", None) is not None:
            status_str = str(status.value) if hasattr(status, "value") else (str(status) if status else "DONE")
            if getattr(self, "session_manager", None) is not None:
                self.session_manager.record_turn(
                    session=self.session,
                    prompt=cmd,
                    thoughts=[],
                    tool_calls=[],
                    status=status_str,
                )
                self.session_manager.save_session(self.session, target_dir=self.workspace.target_dir)
            else:
                from friday.core.session import SessionTurn
                self.session.turns.append(
                    SessionTurn(
                        user_prompt=cmd,
                        thoughts=[],
                        tool_calls=[],
                        status=status_str,
                    )
                )
        return True

    def _print_history(self) -> None:
        turns = getattr(self.session, "turns", []) if self.session else []
        if not turns:
            self.console.print("[dim]No past turns in current session.[/dim]")
            return
        table = Table(title="Session Conversation History", show_header=True, header_style="bold magenta")
        table.add_column("#", style="dim", width=4)
        table.add_column("Time", style="cyan")
        table.add_column("User Prompt", style="white")
        table.add_column("Status", style="green")
        for idx, turn in enumerate(turns, 1):
            ts = turn.timestamp.strftime("%H:%M:%S") if hasattr(turn, "timestamp") and turn.timestamp else "N/A"
            status_style = "green" if turn.status == "DONE" else "red"
            table.add_row(
                str(idx),
                ts,
                turn.user_prompt,
                f"[{status_style}]{turn.status}[/{status_style}]",
            )
        self.console.print(table)

    def _print_help(self) -> None:
        table = Table(title="Available commands", show_header=True, header_style="bold magenta")
        table.add_column("Command", style="cyan")
        table.add_column("Description", style="white")
        table.add_row("/verify", "Run mandatory automated verification tests")
        table.add_row("/yolo", "Toggle YOLO auto-approval mode on/off")
        table.add_row("/use <profile>", "Switch active LLM profile (local, gemini-free, groq, etc.)")
        table.add_row("/model <name>", "Switch active LLM model on the fly")
        table.add_row("/subagents", "List active and background subagent worker tasks")
        table.add_row("/status", "Display target workspace, permissions, and status")
        table.add_row("/history", "Display conversation turn history and statuses")
        table.add_row("/reset", "Reset current session conversation history")
        table.add_row("/clear", "Clear terminal screen")
        table.add_row("/help", "Display available commands and shortcuts")
        table.add_row("/exit, /quit", "Exit the FRIDAY interactive REPL")
        self.console.print(table)

    def _print_subagents(self) -> None:
        tasks = getattr(self.subagent_pool, "active_tasks", {}) if self.subagent_pool else {}
        if not tasks:
            self.console.print("[dim]No active subagent tasks.[/dim]")
            return
        table = Table(title="Active Subagent Tasks", show_header=True, header_style="bold magenta")
        table.add_column("Task ID", style="cyan")
        table.add_column("Status", style="green")
        for task_id, task in tasks.items():
            status = "running" if not task.done() else ("failed" if task.exception() else "done")
            table.add_row(task_id, status)
        self.console.print(table)

    def _print_status(self) -> None:
        table = Table(title="FRIDAY Agent Status", show_header=True, header_style="bold blue")
        table.add_column("Parameter", style="cyan")
        table.add_column("Value", style="green", overflow="fold")
        table.add_row("Workspace", str(self.workspace.target_dir))
        table.add_row("YOLO Mode", str(self.perms.yolo_mode))
        table.add_row("Registered Tools", str(len(getattr(self.agent, "tools", []))))
        llm = getattr(self.agent, "llm", None)
        active_model = getattr(getattr(llm, "config", None), "model", "N/A")
        table.add_row("Active Model", str(active_model))
        active_subagents = len(getattr(self.subagent_pool, "active_tasks", {})) if self.subagent_pool else 0
        table.add_row("Active Subagents", str(active_subagents))
        self.console.print(table)

    async def _run_verify(self) -> None:
        self.console.print("[cyan]Running automated verification...[/cyan]")
        verifier = getattr(self.agent, "verifier", None)
        if verifier is None:
            self.console.print("[red]No verifier configured on agent.[/red]")
            return

        status, v_res = await verifier.verify()
        if status == TaskStatus.DONE:
            await self.bus.publish(
                TaskDoneEvent(
                    task_id="manual_verify",
                    summary="Manual verification passed",
                    evidence=v_res.stdout,
                )
            )
        else:
            await self.bus.publish(
                TaskBlockedEvent(
                    task_id="manual_verify",
                    reason="Manual verification failed",
                    diagnostics=v_res.stderr or v_res.stdout,
                )
            )

    async def run(self) -> None:
        from prompt_toolkit import PromptSession

        session: PromptSession[str] = PromptSession()
        self.console.print(f"[bold green]FRIDAY ready on workspace:[/bold green] {self.workspace.target_dir}")
        self.console.print("[dim]Type your instruction or /help for commands, /exit to quit.[/dim]\n")

        while True:
            try:
                prompt_str = self.get_prompt_string()
                user_input = await session.prompt_async(prompt_str)
                continue_loop = await self.handle_input(user_input)
                if not continue_loop:
                    break
            except (KeyboardInterrupt, EOFError):
                self.console.print("\n[yellow]Session aborted by user.[/yellow]")
                break
