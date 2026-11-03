import asyncio
import sys
from pathlib import Path
from typing import Optional
import typer
from rich.console import Console

from jarvis import __version__
from jarvis.worker import JarvisWorker
from jarvis.shared_bus import SharedBusProtocol

app = typer.Typer(help="JARVIS: Autonomous Specialist Worker Agent")
console = Console()


def version_callback(value: bool):
    if value:
        console.print(f"JARVIS Worker version: [bold cyan]{__version__}[/bold cyan]")
        raise typer.Exit()


def resolve_roots(shared_root: Optional[Path], logs_root: Optional[Path]):
    s_root = shared_root or Path("D:/AI-Agents/Shared")
    if not s_root.exists():
        fallback_shared = Path.cwd().parent / "Shared"
        if fallback_shared.exists():
            s_root = fallback_shared

    l_root = logs_root or Path("D:/AI-Agents/Logs")
    if not l_root.exists():
        fallback_logs = Path.cwd().parent / "Logs"
        if fallback_logs.exists():
            l_root = fallback_logs

    return s_root, l_root


@app.callback()
def main_callback(
    version: Optional[bool] = typer.Option(
        None, "--version", "-v", help="Show version and exit", callback=version_callback, is_eager=True
    ),
):
    pass


@app.command("worker")
def worker_cmd(
    shared_root: Optional[Path] = typer.Option(None, "--shared-root", help="Path to Shared directory"),
    logs_root: Optional[Path] = typer.Option(None, "--logs-root", help="Path to Logs directory"),
    interval: float = typer.Option(1.0, "--interval", "-i", help="Polling interval in seconds"),
):
    """Start JARVIS background polling worker listener."""
    s_root, l_root = resolve_roots(shared_root, logs_root)
    console.print(f"[bold cyan]Starting JARVIS Worker listener...[/bold cyan]")
    console.print(f"Shared Directory : [yellow]{s_root}[/yellow]")
    console.print(f"Logs Directory   : [yellow]{l_root}[/yellow]")
    console.print(f"Interval         : [green]{interval}s[/green]")

    worker = JarvisWorker(shared_root=s_root, logs_root=l_root)
    try:
        asyncio.run(worker.listen(interval=interval, run_once=False))
    except (KeyboardInterrupt, SystemExit):
        console.print("\n[yellow]JARVIS Worker stopped.[/yellow]")


@app.command("run-once")
def run_once_cmd(
    shared_root: Optional[Path] = typer.Option(None, "--shared-root", help="Path to Shared directory"),
    logs_root: Optional[Path] = typer.Option(None, "--logs-root", help="Path to Logs directory"),
):
    """Process a single task from inbox if available, then exit."""
    s_root, l_root = resolve_roots(shared_root, logs_root)
    worker = JarvisWorker(shared_root=s_root, logs_root=l_root)
    result = worker.process_next_task()
    if result:
        color = "green" if result.get("success") else "red"
        console.print(f"[{color}]Task Processed:[/{color}] {result.get('message_id')}")
        console.print(f"Sender: {result.get('sender')} | Action: {result.get('action')} -> Reply: {result.get('reply_action')}")
        if result.get("output"):
            console.print(f"[green]Output:[/green] {result.get('output')}")
        if result.get("error"):
            console.print(f"[red]Error:[/red] {result.get('error')}")
    else:
        console.print("[yellow]No pending tasks in JARVIS inbox.[/yellow]")


@app.command("ping")
def ping_cmd(
    recipient: str = typer.Option("Friday", "--recipient", "-r", help="Recipient agent to ping"),
    shared_root: Optional[Path] = typer.Option(None, "--shared-root", help="Path to Shared directory"),
    logs_root: Optional[Path] = typer.Option(None, "--logs-root", help="Path to Logs directory"),
):
    """Send a heartbeat ping message to Friday inbox."""
    s_root, l_root = resolve_roots(shared_root, logs_root)
    bus = SharedBusProtocol(shared_root=s_root, logs_root=l_root, agent_name="Jarvis")
    msg_id = bus.send_message(
        recipient=recipient,
        action="ping",
        payload={"status": "online", "message": "JARVIS worker is alive and ready."},
    )
    console.print(f"[green]Ping sent to {recipient} inbox![/green] (Message ID: [bold]{msg_id}[/bold])")


def main():
    app()


if __name__ == "__main__":
    main()
