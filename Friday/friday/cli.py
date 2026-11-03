import os
import sys
import json
import asyncio
import typer
from pathlib import Path
from typing import Optional, Dict, Any

if sys.platform == "win32":
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    if hasattr(sys.stderr, "reconfigure"):
        try:
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

from friday import __version__
from friday.core.workspace import WorkspaceGuard
from friday.core.bus import EventBus
from friday.core.permissions import PermissionController
from friday.core.verifier import VerificationRunner
from friday.core.config import (
    FridayConfig,
    load_config,
    save_config,
    save_env_key,
    load_env_file,
    sync_env_keys,
)
from friday.core.router import MultiLLMRouter
from friday.core.session import SessionManager, Session
from friday.agent.lead import LeadAgent
from friday.agent.llm import LLMConfig, LiteLLMProvider, OllamaProvider
from friday.agent.context import ContextConfig, ContextManager
from friday.tools.filesystem import (
    ViewFileTool,
    WriteFileTool,
    EditFileTool,
    ListFilesTool,
    PrintTreeTool,
)
from friday.tools.shell import RunCommandTool
from friday.tools.search import SearchCodeTool
from friday.tools.git import GitStatusTool, GitDiffTool, GitCommitTool
from friday.tools.subagent import DelegateSubagentTool
from friday.tools.jarvis_ipc import DelegateJarvisTool
from friday.agent.subagents.pool import SubagentPool
from friday.ui.renderer import UIRenderer
from friday.ui.prompts import TerminalPrompter
from friday.ui.repl import FridayREPL
from friday.visual.pixel_bridge import PixelAgentsBridge

import click
from typer.core import TyperGroup

SUPPORTED_PROFILES = ("local", "gemini-free", "gemini-paid", "groq", "deepseek", "claude")

PROFILE_MODELS: Dict[str, str] = {
    "local": "ollama/qwen2.5-coder",
    "gemini-free": "gemini/gemini-2.5-flash",
    "gemini-paid": "gemini/gemini-2.5-pro",
    "groq": "groq/openai/gpt-oss-120b",
    "deepseek": "deepseek/deepseek-chat",
    "claude": "anthropic/claude-3-5-sonnet-20241022",
}


class FridayGroup(TyperGroup):
    def parse_args(self, ctx: click.Context, args: list[str]) -> list[str]:
        new_args = []
        i = 0
        while i < len(args):
            arg = args[i]
            if not arg.startswith("-"):
                if arg in self.commands:
                    new_args.extend(args[i:])
                    break
                else:
                    new_args.extend(["--prompt", arg])
                    i += 1
                    continue
            else:
                new_args.append(arg)
                if (
                    arg in (
                        "-p",
                        "--prompt",
                        "-m",
                        "--model",
                        "-s",
                        "--session",
                        "--api-base",
                        "--profile",
                        "--provider",
                        "-t",
                        "--telegram",
                    )
                    and i + 1 < len(args)
                ):
                    i += 1
                    new_args.append(args[i])
            i += 1
        return super().parse_args(ctx, new_args)


app = typer.Typer(cls=FridayGroup, help="FRIDAY: Autonomous Developer CLI Agent")
config_app = typer.Typer(help="Manage FRIDAY workspace configuration")


def version_callback(value: bool):
    if value:
        typer.echo(f"FRIDAY version: {__version__}")
        raise typer.Exit()


@app.callback(invoke_without_command=True)
def main_callback(
    ctx: typer.Context,
    prompt: Optional[str] = typer.Option(None, "--prompt", "-p", help="Single natural language instruction to execute"),
    yolo: bool = typer.Option(False, "--yolo", help="Run without permission confirmation prompts"),
    interactive: bool = typer.Option(False, "--interactive", "-i", help="Launch interactive REPL mode"),
    session_id: Optional[str] = typer.Option(None, "--session", "-s", help="Resume an existing session ID"),
    model: Optional[str] = typer.Option(None, "--model", "-m", help="LLM model identifier to use"),
    api_base: Optional[str] = typer.Option(None, "--api-base", help="Custom LLM API base URL (e.g. http://localhost:11434)"),
    profile: Optional[str] = typer.Option(
        None, "--profile", "--provider", help="LLM profile to use ('local', 'gemini-free', 'gemini-paid', 'groq', 'deepseek', 'claude')"
    ),
    telegram: Optional[bool] = typer.Option(
        None, "--telegram", "-t", help="Enable two-way Telegram notifications and interactive approval prompts"
    ),
    version: Optional[bool] = typer.Option(
        None, "--version", "-v", help="Show version and exit", callback=version_callback, is_eager=True
    ),
):
    if ctx.invoked_subcommand is None:
        _execute_runtime(
            target_dir=Path.cwd(),
            prompt=prompt,
            yolo=yolo,
            session_id=session_id,
            model=model,
            api_base=api_base,
            profile=profile,
            interactive=interactive,
            telegram=telegram,
        )


def setup_runtime(
    target_dir: Path,
    yolo: bool = False,
    session_id: Optional[str] = None,
    model: Optional[str] = None,
    api_base: Optional[str] = None,
    profile: Optional[str] = None,
    telegram: Optional[bool] = None,
) -> Dict[str, Any]:
    """Wire up full runtime: config, permissions, tools, verifier, LLM router, session, agent, and REPL."""
    config: FridayConfig = load_config(target_dir)

    # Sync environment keys from .env and config
    sync_env_keys(target_dir, config)

    # Resolve active profile and model overrides
    cli_profile = profile.strip().lower() if profile else None
    if cli_profile:
        config.active_profile = cli_profile
        if not model and cli_profile in PROFILE_MODELS:
            config.model = PROFILE_MODELS[cli_profile]

    if model:
        config.model = model
    if api_base:
        config.api_base = api_base
    effective_yolo = yolo or config.yolo_mode

    # Active profile selection
    if config.active_profile and config.active_profile in SUPPORTED_PROFILES:
        active_profile = config.active_profile
    elif config.model.startswith("ollama/"):
        active_profile = "local"
    elif "claude" in config.model:
        active_profile = "claude"
    elif "groq" in config.model:
        active_profile = "groq"
    elif "deepseek" in config.model:
        active_profile = "deepseek"
    elif "gemini-2.5-pro" in config.model or "gemini-pro" in config.model:
        active_profile = "gemini-paid"
    else:
        active_profile = "gemini-free"

    guard = WorkspaceGuard(target_dir=target_dir)
    bus = EventBus()
    renderer = UIRenderer(bus=bus)

    # Telegram bridge and prompter
    from friday.telegram.bridge import TelegramBridge
    from friday.telegram.prompter import TelegramPrompter, HybridPrompter

    tg_bridge: Optional[TelegramBridge] = None
    use_telegram = telegram if telegram is not None else (config.telegram_enabled or os.getenv("FRIDAY_TELEGRAM") == "1")
    if use_telegram:
        tg_bridge = TelegramBridge(
            bot_token=config.telegram_bot_token,
            chat_id=config.telegram_chat_id,
        )

    prompter = None
    if not effective_yolo:
        term_prompter = TerminalPrompter()
        if tg_bridge:
            tg_prompter = TelegramPrompter(bridge=tg_bridge)
            prompter = HybridPrompter(terminal_prompter=term_prompter, telegram_prompter=tg_prompter)
        else:
            prompter = term_prompter

    perms = PermissionController(yolo_mode=effective_yolo, prompter=prompter)

    cmd_tool = RunCommandTool(workspace=guard, permissions=perms)
    tools = [
        ViewFileTool(workspace=guard, permissions=perms),
        WriteFileTool(workspace=guard, permissions=perms),
        EditFileTool(workspace=guard, permissions=perms),
        ListFilesTool(workspace=guard, permissions=perms),
        PrintTreeTool(workspace=guard, permissions=perms),
        cmd_tool,
        SearchCodeTool(workspace=guard, permissions=perms),
        GitStatusTool(workspace=guard, permissions=perms),
        GitDiffTool(workspace=guard, permissions=perms),
        GitCommitTool(workspace=guard, permissions=perms),
    ]

    # Persistent Agency Memory
    from friday.core.memory import AgencyMemory
    from friday.tools.memory import RememberTool, RecallTool
    memory = AgencyMemory()
    try:
        memory.seed_defaults()
    except Exception:
        pass

    tools.extend([
        RememberTool(memory=memory, workspace=guard, permissions=perms),
        RecallTool(memory=memory, workspace=guard, permissions=perms),
    ])

    verifier = VerificationRunner(
        workspace=guard,
        command_runner=cmd_tool,
        max_retries=config.max_repair_retries,
        verification_command=config.verification_command,
    )

    # MultiLLMRouter as the runtime's LLM provider
    llm = MultiLLMRouter(
        bus=bus,
        active_profile=active_profile,
        api_base=config.api_base,
    )

    # Sync active provider config (model, temperature, api_base)
    if active_profile in llm.list_profiles():
        active_p = llm.get_provider(active_profile)
        if hasattr(active_p, "config"):
            if model:
                active_p.config.model = model
            active_p.config.temperature = config.temperature
            if config.api_base:
                active_p.config.api_base = config.api_base
    elif config.model:
        if config.model.startswith("ollama/"):
            custom_p = OllamaProvider(model=config.model, api_base=config.api_base or "http://localhost:11434")
        else:
            custom_p = LiteLLMProvider(
                config=LLMConfig(
                    model=config.model,
                    temperature=config.temperature,
                    api_base=config.api_base,
                )
            )
        llm.register_provider(active_profile, custom_p)
        llm.set_active_profile(active_profile)

    context_mgr = ContextManager(config=ContextConfig(max_context_tokens=config.max_context_tokens))

    pool = SubagentPool(bus=bus, workspace=guard)
    subagent_tool = DelegateSubagentTool(
        workspace=guard,
        permissions=perms,
        pool=pool,
        llm=llm,
        bus=bus,
        subagent_tools=tools,
    )
    tools.append(subagent_tool)

    jarvis_tool = DelegateJarvisTool(
        workspace=guard,
        permissions=perms,
        router=llm,
    )
    tools.append(jarvis_tool)

    # Automatically ensure JARVIS specialist worker background daemon is running
    try:
        from friday.core.jarvis_daemon import ensure_jarvis_worker
        ensure_jarvis_worker()
    except Exception as d_err:
        pass

    # Automatically ensure FRIDAY Telegram command listener background daemon is running
    try:
        from friday.telegram.daemon import start_telegram_daemon
        start_telegram_daemon(target_dir=target_dir)
    except Exception:
        pass

    agent = LeadAgent(
        bus=bus,
        workspace=guard,
        verifier=verifier,
        llm=llm,
        tools=tools,
        max_steps=config.max_steps,
        max_repair_retries=config.max_repair_retries,
        context_manager=context_mgr,
        memory=memory,
    )

    session_mgr = SessionManager()
    if session_id:
        session_file = target_dir / ".friday" / "sessions" / f"{session_id}.json"
        if session_file.exists():
            session = session_mgr.load_session(session_file)
        else:
            session = session_mgr.create_session(workspace_path=target_dir)
    else:
        session = session_mgr.create_session(workspace_path=target_dir)

    repl = FridayREPL(
        agent=agent,
        workspace=guard,
        bus=bus,
        perms=perms,
        renderer=renderer,
        session=session,
        session_manager=session_mgr,
        subagent_pool=pool,
    )

    return {
        "config": config,
        "guard": guard,
        "bus": bus,
        "renderer": renderer,
        "perms": perms,
        "tools": tools,
        "verifier": verifier,
        "llm": llm,
        "context_mgr": context_mgr,
        "agent": agent,
        "session_mgr": session_mgr,
        "session": session,
        "repl": repl,
        "subagent_pool": pool,
        "jarvis_tool": jarvis_tool,
        "tg_bridge": tg_bridge,
        "pixel_bridge": PixelAgentsBridge(bus=bus, workspace_path=str(target_dir)),
    }


def _execute_runtime(
    target_dir: Path,
    prompt: Optional[str] = None,
    yolo: bool = False,
    session_id: Optional[str] = None,
    model: Optional[str] = None,
    api_base: Optional[str] = None,
    profile: Optional[str] = None,
    interactive: bool = False,
    telegram: Optional[bool] = None,
) -> None:
    target_dir = target_dir.resolve()
    typer.echo(f"Initializing FRIDAY on workspace: {target_dir}")

    runtime = setup_runtime(
        target_dir=target_dir,
        yolo=yolo,
        session_id=session_id,
        model=model,
        api_base=api_base,
        profile=profile,
        telegram=telegram,
    )
    agent = runtime["agent"]
    repl = runtime["repl"]
    session_mgr = runtime["session_mgr"]
    session = runtime["session"]
    tg_bridge = runtime.get("tg_bridge")

    typer.echo("FRIDAY initialized and ready.")

    if prompt:
        typer.echo(f"Executing instruction: '{prompt}'")
        try:
            status = asyncio.run(agent.run_turn(prompt, session=session))
            status_str = str(status.value) if hasattr(status, "value") else (str(status) if status else "DONE")
            session_mgr.record_turn(
                session=session,
                prompt=prompt,
                thoughts=[],
                tool_calls=[],
                status=status_str,
            )
            session_mgr.save_session(session, target_dir=target_dir)

            if tg_bridge:
                if status_str in ("DONE", "TurnStatus.DONE", "success"):
                    asyncio.run(
                        tg_bridge.send_notification(
                            message=f"Görev başarıyla tamamlandı:\n<code>{prompt}</code>",
                            title="✅ FRIDAY Görevi Bitirdi",
                            event="bitirdim",
                        )
                    )
                else:
                    asyncio.run(
                        tg_bridge.send_notification(
                            message=f"Görev engellendi ({status_str}):\n<code>{prompt}</code>",
                            title="⚠️ FRIDAY Görev Uyarısı",
                            event="hata",
                        )
                    )
        except Exception as exc:
            if tg_bridge:
                asyncio.run(
                    tg_bridge.send_notification(
                        message=f"Görev yürütülürken hata oluştu:\n<code>{exc}</code>",
                        title="❌ FRIDAY Hatası",
                        event="hata",
                    )
                )
            raise
    elif interactive or (sys.stdin and sys.stdin.isatty()):
        asyncio.run(repl.run())


@app.command()
def run(
    target_path: Optional[str] = typer.Argument(None, help="Target project workspace directory"),
    yolo: bool = typer.Option(False, "--yolo", help="Run without permission confirmation prompts"),
    prompt: Optional[str] = typer.Option(None, "--prompt", "-p", help="Single natural language instruction to execute"),
    interactive: bool = typer.Option(False, "--interactive", "-i", help="Launch interactive REPL mode"),
    session_id: Optional[str] = typer.Option(None, "--session", "-s", help="Resume an existing session ID"),
    model: Optional[str] = typer.Option(None, "--model", "-m", help="LLM model identifier to use"),
    api_base: Optional[str] = typer.Option(None, "--api-base", help="Custom LLM API base URL (e.g. http://localhost:11434)"),
    profile: Optional[str] = typer.Option(
        None, "--profile", "--provider", help="LLM profile to use ('local', 'gemini-free', 'gemini-paid', 'groq', 'deepseek', 'claude')"
    ),
    telegram: Optional[bool] = typer.Option(
        None, "--telegram", "-t", help="Enable two-way Telegram notifications and interactive approval prompts"
    ),
):
    target_dir = Path(target_path).resolve() if target_path else Path.cwd()
    _execute_runtime(
        target_dir=target_dir,
        prompt=prompt,
        yolo=yolo,
        session_id=session_id,
        model=model,
        api_base=api_base,
        profile=profile,
        interactive=interactive,
        telegram=telegram,
    )


@app.command()
def use(
    profile: str = typer.Argument(
        ...,
        help="LLM profile to use ('local', 'gemini-free', 'gemini-paid', 'groq', 'deepseek', 'claude')",
    ),
    workspace: Optional[Path] = typer.Option(None, "--workspace", "-w", help="Target workspace directory"),
):
    """Switch active LLM profile and persist selection in workspace config."""
    target_dir = (workspace or Path.cwd()).resolve()
    p = profile.strip().lower()
    if p not in SUPPORTED_PROFILES:
        typer.secho(
            f"Error: Unsupported profile '{profile}'. Supported profiles: {', '.join(SUPPORTED_PROFILES)}",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=1)

    config = load_config(target_dir)
    config.active_profile = p
    config.model = PROFILE_MODELS[p]
    save_config(target_dir, config)

    typer.echo(f"Active profile set to '{p}'.")
    typer.echo(f"Active model: '{config.model}'")
    typer.echo(f"Configuration saved to {target_dir / '.friday' / 'config.yaml'}")


@config_app.command("set-key")
def config_set_key(
    key_name: str = typer.Argument(..., help="API key name (e.g. GEMINI_API_KEY, GROQ_API_KEY)"),
    value: str = typer.Argument(..., help="API key secret value"),
    workspace: Optional[Path] = typer.Option(None, "--workspace", "-w", help="Target workspace directory"),
):
    """Set API key into workspace .env and configuration."""
    target_dir = (workspace or Path.cwd()).resolve()
    key = key_name.strip()
    val = value.strip()

    # 1. Save to .env
    save_env_key(target_dir, key, val)

    # 2. Save to .friday/config.yaml
    config = load_config(target_dir)
    config.api_keys[key] = val
    save_config(target_dir, config)

    # 3. Set into current environment
    os.environ[key] = val

    masked = f"{val[:3]}...{val[-3:]}" if len(val) >= 8 else "***"
    typer.echo(f"API key '{key}' set successfully ({masked}).")
    typer.echo(f"Saved to .env and {target_dir / '.friday' / 'config.yaml'}")


@config_app.command("show")
def config_show(
    workspace: Optional[Path] = typer.Option(None, "--workspace", "-w", help="Target workspace directory"),
):
    """Display current workspace configuration."""
    target_dir = (workspace or Path.cwd()).resolve()
    config = load_config(target_dir)
    active_profile = config.active_profile or "gemini-free"

    typer.echo(f"FRIDAY Workspace Configuration ({target_dir}):")
    typer.echo(f"  Active Profile:       {active_profile}")
    typer.echo(f"  Model:                {config.model}")
    typer.echo(f"  Temperature:          {config.temperature}")
    typer.echo(f"  Max Context Tokens:   {config.max_context_tokens}")
    typer.echo(f"  YOLO Mode:            {config.yolo_mode}")
    typer.echo(f"  Verification Command: {config.verification_command}")
    typer.echo(f"  Max Repair Retries:   {config.max_repair_retries}")
    typer.echo(f"  Max Steps:            {config.max_steps}")
    typer.echo(f"  API Base:             {config.api_base}")
    if config.api_keys:
        typer.echo("  Configured API Keys:")
        for k in sorted(config.api_keys.keys()):
            typer.echo(f"    - {k}")


app.add_typer(config_app, name="config")

jarvis_app = typer.Typer(help="Manage JARVIS specialist worker background daemon")


@jarvis_app.command("status")
def jarvis_status_cmd(
    shared_root: Optional[Path] = typer.Option(None, "--shared-root", help="Path to Shared directory"),
):
    """Check if JARVIS specialist worker background daemon is running."""
    from friday.core.jarvis_daemon import is_jarvis_worker_running, resolve_daemon_paths
    s_root, l_root = resolve_daemon_paths(shared_root)
    running, pid = is_jarvis_worker_running(s_root)
    if running and pid:
        typer.echo(f"JARVIS Worker Daemon: [ONLINE] (PID: {pid})")
        typer.echo(f"  Shared Directory : {s_root}")
        typer.echo(f"  Logs Directory   : {l_root}")
        typer.echo(f"  Log File         : {l_root / 'jarvis.log'}")
    else:
        typer.echo("JARVIS Worker Daemon: [OFFLINE]")
        typer.echo("Run 'friday jarvis start' or launch FRIDAY to start it automatically.")


@jarvis_app.command("start")
def jarvis_start_cmd(
    shared_root: Optional[Path] = typer.Option(None, "--shared-root", help="Path to Shared directory"),
    logs_root: Optional[Path] = typer.Option(None, "--logs-root", help="Path to Logs directory"),
):
    """Start JARVIS worker as a silent background daemon."""
    from friday.core.jarvis_daemon import start_jarvis_worker, is_jarvis_worker_running
    running, pid = is_jarvis_worker_running(shared_root)
    if running and pid:
        typer.echo(f"JARVIS worker is already running (PID: {pid}).")
        return

    new_pid = start_jarvis_worker(shared_root, logs_root)
    if new_pid:
        typer.echo(f"JARVIS specialist worker started successfully in background (PID: {new_pid}).")
    else:
        typer.echo("Failed to start JARVIS worker daemon.", err=True)


@jarvis_app.command("stop")
def jarvis_stop_cmd(
    shared_root: Optional[Path] = typer.Option(None, "--shared-root", help="Path to Shared directory"),
):
    """Stop the running JARVIS worker background daemon."""
    from friday.core.jarvis_daemon import stop_jarvis_worker
    stopped = stop_jarvis_worker(shared_root)
    if stopped:
        typer.echo("JARVIS specialist worker daemon stopped successfully.")
    else:
        typer.echo("JARVIS worker was not running.")


@jarvis_app.command("restart")
def jarvis_restart_cmd(
    shared_root: Optional[Path] = typer.Option(None, "--shared-root", help="Path to Shared directory"),
    logs_root: Optional[Path] = typer.Option(None, "--logs-root", help="Path to Logs directory"),
):
    """Restart JARVIS worker background daemon."""
    from friday.core.jarvis_daemon import stop_jarvis_worker, start_jarvis_worker
    stop_jarvis_worker(shared_root)
    new_pid = start_jarvis_worker(shared_root, logs_root)
    if new_pid:
        typer.echo(f"JARVIS worker daemon restarted successfully (PID: {new_pid}).")
    else:
        typer.echo("Failed to restart JARVIS worker daemon.", err=True)


app.add_typer(jarvis_app, name="jarvis")

telegram_app = typer.Typer(help="Manage Telegram notifications and remote control")


@telegram_app.command("status")
def telegram_status_cmd():
    """Show configured Telegram connection status and asset paths."""
    from friday.telegram.bridge import TelegramBridge, EVENT_IMAGES, resolve_event_image
    from friday.telegram.daemon import is_telegram_daemon_running
    bridge = TelegramBridge()
    running, pid = is_telegram_daemon_running()
    daemon_badge = f"[ONLINE] (PID: {pid})" if running else "[OFFLINE]"
    token_masked = f"{bridge.bot_token[:8]}...{bridge.bot_token[-4:]}" if len(bridge.bot_token) > 12 else bridge.bot_token
    typer.echo("Telegram Entegrasyon Durumu:")
    typer.echo(f"  Arka Plan Dinleyicisi : {daemon_badge}")
    typer.echo(f"  Bot Token             : {token_masked}")
    typer.echo(f"  Chat ID               : {bridge.chat_id}")
    typer.echo("  Görsel Eşleştirmeleri:")
    for ev in ("izin", "bitirdim", "hata"):
        res = resolve_event_image(ev)
        typer.echo(f"    • {ev}: {'[MEVCUT] ' + res if res else '[BULUNAMADI]'}")
    if not running:
        typer.echo("\nİpucu: Telefondan komut dinlemek için 'friday telegram start' çalıştırabilirsiniz.")


@telegram_app.command("start")
def telegram_start_cmd(
    target_path: Optional[str] = typer.Argument(None, help="Target project workspace directory"),
):
    """Start FRIDAY Telegram command listener as a silent background daemon."""
    from friday.telegram.daemon import start_telegram_daemon, is_telegram_daemon_running
    running, pid = is_telegram_daemon_running()
    if running and pid:
        typer.echo(f"Telegram dinleyici servisi zaten çalışıyor (PID: {pid}).")
        return
    new_pid = start_telegram_daemon(target_dir=target_path)
    if new_pid:
        typer.echo(f"✅ FRIDAY Telegram dinleyicisi arka planda başlatıldı (PID: {new_pid}).")
        typer.echo("Artık telefonunuzdan Telegram'a mesaj atarak FRIDAY'i yönetebilirsiniz!")
    else:
        typer.echo("Telegram dinleyicisi başlatılamadı.", err=True)


@telegram_app.command("stop")
def telegram_stop_cmd():
    """Stop the running FRIDAY Telegram background daemon."""
    from friday.telegram.daemon import stop_telegram_daemon
    stopped = stop_telegram_daemon()
    if stopped:
        typer.echo("FRIDAY Telegram dinleyici servisi durduruldu.")
    else:
        typer.echo("Telegram dinleyicisi zaten çalışmıyor.")


@telegram_app.command("restart")
def telegram_restart_cmd(
    target_path: Optional[str] = typer.Argument(None, help="Target project workspace directory"),
):
    """Restart FRIDAY Telegram background daemon."""
    from friday.telegram.daemon import stop_telegram_daemon, start_telegram_daemon
    stop_telegram_daemon()
    new_pid = start_telegram_daemon(target_dir=target_path)
    if new_pid:
        typer.echo(f"FRIDAY Telegram dinleyicisi yeniden başlatıldı (PID: {new_pid}).")
    else:
        typer.echo("Telegram dinleyicisi yeniden başlatılamadı.", err=True)


@telegram_app.command("test")
def telegram_test_cmd(
    message: str = typer.Option("FRIDAY iki yönlü Telegram bağlantı testi.", "--message", "-m", help="Message to send"),
):
    """Send a test notification to Telegram to verify credentials and connectivity."""
    from friday.telegram.bridge import TelegramBridge
    bridge = TelegramBridge()
    ok = asyncio.run(bridge.send_notification(message=message, title="🔔 FRIDAY Test Bildirimi", event="bitirdim"))
    if ok:
        typer.echo("✅ Telegram test bildirimi başarıyla gönderildi.")
    else:
        typer.secho("❌ Telegram bildirimi gönderilemedi. Token veya ağ bağlantısını kontrol edin.", fg=typer.colors.RED)
        raise typer.Exit(code=1)


@telegram_app.command("notify")
def telegram_notify_cmd(
    message: str = typer.Argument(..., help="Notification message text"),
    title: str = typer.Option("🔔 FRIDAY Bildirimi", "--title", "-t", help="Notification title"),
    event: Optional[str] = typer.Option(None, "--event", "-e", help="Event name (izin, bitirdim, hata)"),
    image: Optional[str] = typer.Option(None, "--image", "-i", help="Custom image path"),
    web: Optional[str] = typer.Option(None, "--web", "-w", help="Localhost URL for UI screenshot"),
    mobile: bool = typer.Option(False, "--mobile", help="Capture mobile emulator screen via adb"),
):
    """Send ad-hoc message or alert with event images and UI screenshots."""
    from friday.telegram.bridge import TelegramBridge
    bridge = TelegramBridge()
    ok = asyncio.run(bridge.send_notification(message=message, title=title, event=event, image_path=image, web_url=web, mobile=mobile))
    if ok:
        typer.echo("Bildirim gönderildi.")
    else:
        typer.secho("Bildirim gönderilemedi.", fg=typer.colors.RED)
        raise typer.Exit(code=1)


@telegram_app.command("enable")
def telegram_enable_cmd(
    target_path: Optional[str] = typer.Argument(None, help="Target project workspace directory"),
):
    """Enable automatic Telegram notifications and interactive prompter for target workspace."""
    target_dir = Path(target_path).resolve() if target_path else Path.cwd()
    config = load_config(target_dir)
    config.telegram_enabled = True
    save_config(target_dir, config)
    typer.echo(f"✅ Telegram bildirimleri bu çalışma alanında etkinleştirildi: {target_dir}")


@telegram_app.command("disable")
def telegram_disable_cmd(
    target_path: Optional[str] = typer.Argument(None, help="Target project workspace directory"),
):
    """Disable automatic Telegram notifications for target workspace."""
    target_dir = Path(target_path).resolve() if target_path else Path.cwd()
    config = load_config(target_dir)
    config.telegram_enabled = False
    save_config(target_dir, config)
    typer.echo(f"🔒 Telegram bildirimleri bu çalışma alanında devre dışı bırakıldı: {target_dir}")


@telegram_app.command("listen")
def telegram_listen_cmd(
    target_path: Optional[str] = typer.Argument(None, help="Target project workspace directory"),
):
    """Start interactive Telegram remote command listener (/status, /run, approval prompts)."""
    target_dir = Path(target_path).resolve() if target_path else Path.cwd()
    from friday.telegram.listener import TelegramCommandListener
    listener = TelegramCommandListener(target_dir=target_dir)
    typer.echo("📱 FRIDAY Telegram Dinleyicisi Başlatıldı.")
    typer.echo(f"  Çalışma Alanı : {target_dir}")
    typer.echo(f"  Yetkili Chat  : {listener.bridge.chat_id}")
    typer.echo("Telefondan komutlar bekleniyor... Çıkış için Ctrl+C tuşlarına basın.")
    try:
        asyncio.run(listener.start())
    except KeyboardInterrupt:
        typer.echo("\nDinleyici durduruldu.")


app.add_typer(telegram_app, name="telegram")

office_app = typer.Typer(help="Manage Pixel Agents 2D visual office")


def get_pixel_pid_file() -> Path:
    return Path.home() / ".pixel-agents" / "pixel_office.pid"


@office_app.command("status")
def office_status_cmd():
    """Check live status of the Pixel Agents visual office server."""
    cfg_path = Path.home() / ".pixel-agents" / "server.json"
    if not cfg_path.is_file():
        typer.echo("Pixel Agents is offline (server.json not found).")
        typer.echo("Run 'friday office start' to launch the visual office.")
        return

    try:
        data = json.loads(cfg_path.read_text(encoding="utf-8"))
        port = data.get("port")
        token = data.get("token")
    except Exception as e:
        typer.echo(f"Pixel Agents config unreadable: {e}")
        return

    try:
        import httpx
        resp = httpx.get(f"http://127.0.0.1:{port}/api/health", timeout=1.5)
        if resp.status_code == 200:
            typer.echo(f"Pixel Agents is ONLINE (running on http://127.0.0.1:{port}).")
            typer.echo(f"Token: {token}")
            return
    except Exception:
        pass

    typer.echo(f"Pixel Agents config found (port {port}), but server is not responding (offline).")


@office_app.command("start")
def office_start_cmd(
    port: int = typer.Option(3100, "--port", "-p", help="Port to run Pixel Agents on"),
    host: str = typer.Option("127.0.0.1", "--host", help="Host to bind Pixel Agents"),
    browser: bool = typer.Option(True, "--browser/--no-browser", help="Open office in default browser"),
):
    """Start Pixel Agents standalone server in background and open browser."""
    import subprocess
    import webbrowser
    import time

    # Ensure Pixel Agents config accepts all sessions and hooks
    cfg_file = Path.home() / ".pixel-agents" / "config.json"
    try:
        cfg_file.parent.mkdir(parents=True, exist_ok=True)
        cur_cfg = {}
        if cfg_file.is_file():
            try:
                cur_cfg = json.loads(cfg_file.read_text(encoding="utf-8"))
            except Exception:
                cur_cfg = {}
        standalone_cfg = cur_cfg.setdefault("standalone", {})
        standalone_cfg["watchAllSessions"] = True
        standalone_cfg["alwaysShowLabels"] = True
        standalone_cfg["hooksInfoShown"] = True
        vscode_cfg = cur_cfg.setdefault("vscode", {})
        vscode_cfg["watchAllSessions"] = True
        vscode_cfg["alwaysShowLabels"] = True
        cur_cfg.setdefault("hooksConsent", {})["claude"] = "granted"
        cur_cfg.setdefault("hooksEnabled", {})["claude"] = True
        cfg_file.write_text(json.dumps(cur_cfg, indent=2), encoding="utf-8")
    except Exception:
        pass

    typer.echo(f"Starting Pixel Agents office on http://{host}:{port}...")

    cmd = ["npx.cmd" if sys.platform == "win32" else "npx", "pixel-agents", "--port", str(port), "--host", host]

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0,
    )

    pid_file = get_pixel_pid_file()
    pid_file.parent.mkdir(parents=True, exist_ok=True)
    pid_file.write_text(str(proc.pid))

    typer.echo(f"Pixel Agents process started (PID {proc.pid}).")

    # Give the server a brief moment to boot and stage agents
    time.sleep(1.2)
    _stage_office_agents(host=host, port=port)

    if browser:
        webbrowser.open(f"http://{host}:{port}")


def _stage_office_agents(host: str = "127.0.0.1", port: Optional[int] = None) -> bool:
    """Sends presence events so FRIDAY and JARVIS appear seated in the pixel office."""
    cfg_path = Path.home() / ".pixel-agents" / "server.json"
    if not cfg_path.is_file():
        return False
    try:
        data = json.loads(cfg_path.read_text(encoding="utf-8"))
        s_port = port or data.get("port", 3100)
        s_tok = data.get("token", "")
        if not s_tok:
            return False

        import httpx
        h = {"Authorization": f"Bearer {s_tok}", "Content-Type": "application/json"}
        cwd = str(Path.cwd())

        # 1. FRIDAY (Lead Orchestrator)
        httpx.post(
            f"http://{host}:{s_port}/api/hooks/claude",
            json={"session_id": "friday-lead-1", "hook_event_name": "SessionStart", "source": "startup", "cwd": cwd},
            headers=h,
            timeout=2.0,
        )
        httpx.post(
            f"http://{host}:{s_port}/api/hooks/claude",
            json={"session_id": "friday-lead-1", "hook_event_name": "Notification", "notification_type": "idle_prompt"},
            headers=h,
            timeout=2.0,
        )

        # 2. JARVIS (Code Specialist)
        httpx.post(
            f"http://{host}:{s_port}/api/hooks/claude",
            json={"session_id": "jarvis-worker-1", "hook_event_name": "SessionStart", "source": "startup", "cwd": cwd},
            headers=h,
            timeout=2.0,
        )
        httpx.post(
            f"http://{host}:{s_port}/api/hooks/claude",
            json={"session_id": "jarvis-worker-1", "hook_event_name": "Notification", "notification_type": "idle_prompt"},
            headers=h,
            timeout=2.0,
        )
        return True
    except Exception:
        return False


@office_app.command("sync")
def office_sync_cmd():
    """Sync and spawn FRIDAY & JARVIS characters into the active visual office."""
    ok = _stage_office_agents()
    if ok:
        typer.echo("✅ FRIDAY ve JARVIS karakterleri piksel ofisine başarıyla ışınlandı!")
    else:
        typer.echo("❌ Piksel ofisi sunucusuna erişilemedi. 'friday office start' çalıştırın.", err=True)


@office_app.command("stop")
def office_stop_cmd():
    """Stop the managed Pixel Agents background process."""
    pid_file = get_pixel_pid_file()
    if not pid_file.is_file():
        typer.echo("No running Pixel Agents office process found.")
        return

    try:
        pid = int(pid_file.read_text().strip())
        import os
        import signal
        import subprocess
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            os.kill(pid, signal.SIGTERM)
        typer.echo(f"Pixel Agents office process (PID {pid}) stopped.")
    except Exception as e:
        typer.echo(f"Error stopping process: {e}")
    finally:
        try:
            pid_file.unlink(missing_ok=True)
        except Exception:
            pass


app.add_typer(office_app, name="office")

dashboard_app = typer.Typer(help="Manage FRIDAY & JARVIS Web Observability Dashboard")


def get_dashboard_pid_file() -> Path:
    return Path.home() / ".friday" / "dashboard.pid"


def get_dashboard_info_file() -> Path:
    return Path.home() / ".friday" / "dashboard.json"


@dashboard_app.command("status")
def dashboard_status_cmd():
    """Check live status of the Web Observability Dashboard."""
    pid_file = get_dashboard_pid_file()
    if not pid_file.is_file():
        typer.echo("FRIDAY Dashboard is offline (no pid file found).")
        typer.echo("Run 'friday dashboard start' to launch.")
        return

    try:
        pid = int(pid_file.read_text().strip())
    except Exception:
        typer.echo("FRIDAY Dashboard is offline (invalid pid file).")
        return

    info_file = get_dashboard_info_file()
    port = 8000
    host = "127.0.0.1"
    if info_file.is_file():
        try:
            info = json.loads(info_file.read_text(encoding="utf-8"))
            port = info.get("port", port)
            host = info.get("host", host)
        except Exception:
            pass

    import httpx
    try:
        resp = httpx.get(f"http://{host}:{port}/api/status", timeout=1.5)
        if resp.status_code == 200:
            typer.echo(f"FRIDAY Dashboard is ONLINE on http://{host}:{port} (PID {pid}).")
            return
    except Exception:
        pass

    typer.echo(f"FRIDAY Dashboard is offline (PID {pid} not responding on http://{host}:{port}).")


@dashboard_app.command("start")
def dashboard_start_cmd(
    port: int = typer.Option(8000, "--port", "-p", help="Port to run Dashboard on"),
    host: str = typer.Option("127.0.0.1", "--host", help="Host to bind Dashboard to"),
    workspace: Path = typer.Option(Path("."), "--workspace", "-w", help="Workspace to observe"),
    browser: bool = typer.Option(True, "--browser/--no-browser", help="Open Dashboard in default browser"),
):
    """Start FRIDAY & JARVIS Web Observability Dashboard in background."""
    import subprocess
    import webbrowser
    import time

    pid_file = get_dashboard_pid_file()
    if pid_file.is_file():
        try:
            pid = int(pid_file.read_text().strip())
            import httpx
            resp = httpx.get(f"http://{host}:{port}/api/status", timeout=1.5)
            if resp.status_code == 200:
                typer.echo(f"FRIDAY Dashboard is already running on http://{host}:{port} (PID {pid}).")
                if browser:
                    webbrowser.open(f"http://{host}:{port}")
                return
        except Exception:
            pass

    typer.echo(f"Starting FRIDAY Dashboard on http://{host}:{port}...")

    cmd = [
        sys.executable,
        "-m",
        "friday.dashboard.runner",
        "--host",
        host,
        "--port",
        str(port),
        "--workspace",
        str(workspace.resolve()),
    ]

    log_file_path = Path.home() / ".friday" / "dashboard.log"
    log_file_path.parent.mkdir(parents=True, exist_ok=True)
    log_file = log_file_path.open("a", encoding="utf-8")

    proc = subprocess.Popen(
        cmd,
        stdout=log_file,
        stderr=log_file,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0,
    )

    pid_file.parent.mkdir(parents=True, exist_ok=True)
    pid_file.write_text(str(proc.pid))

    info_file = get_dashboard_info_file()
    info_file.write_text(json.dumps({"pid": proc.pid, "host": host, "port": port, "workspace": str(workspace.resolve())}))

    typer.echo(f"FRIDAY Dashboard started (PID {proc.pid}).")
    typer.echo(f"URL: http://{host}:{port}")

    if browser:
        time.sleep(0.5)
        webbrowser.open(f"http://{host}:{port}")


@dashboard_app.command("stop")
def dashboard_stop_cmd():
    """Stop the running FRIDAY & JARVIS Web Observability Dashboard."""
    pid_file = get_dashboard_pid_file()
    if not pid_file.is_file():
        typer.echo("No running dashboard process found.")
        return

    try:
        pid = int(pid_file.read_text().strip())
        import os
        import signal
        import subprocess
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            os.kill(pid, signal.SIGTERM)
        typer.echo(f"FRIDAY Dashboard process (PID {pid}) stopped.")
    except Exception as e:
        typer.echo(f"Error stopping dashboard: {e}")
    finally:
        try:
            pid_file.unlink(missing_ok=True)
            get_dashboard_info_file().unlink(missing_ok=True)
        except Exception:
            pass


app.add_typer(dashboard_app, name="dashboard")

memory_app = typer.Typer(help="Manage FRIDAY persistent long-term memory")


@memory_app.command("list")
def memory_list_cmd(category: Optional[str] = typer.Option(None, "--category", "-c", help="Filter by category")):
    """List stored agency memories."""
    from friday.core.memory import AgencyMemory
    mem = AgencyMemory()
    items = mem.list_all(category=category)
    if not items:
        typer.echo("No memories stored yet.")
        return
    typer.echo(f"Stored Memories ({len(items)}):")
    for it in items:
        typer.echo(f"  #{it.id} [{it.category}] {it.key}: {it.content} (hits: {it.access_count})")


@memory_app.command("add")
def memory_add_cmd(
    category: str = typer.Argument(..., help="Category (e.g. error_fix, user_preference, architecture)"),
    key: str = typer.Argument(..., help="Descriptive identifier key"),
    content: str = typer.Argument(..., help="Memory content to store"),
):
    """Add a new memory item."""
    from friday.core.memory import AgencyMemory
    mem = AgencyMemory()
    m_id = mem.remember(category=category, key=key, content=content)
    typer.echo(f"Memory stored successfully (ID #{m_id}).")


@memory_app.command("search")
def memory_search_cmd(query: str = typer.Argument(..., help="Search query")):
    """Search agency memories using full-text search."""
    from friday.core.memory import AgencyMemory
    mem = AgencyMemory()
    results = mem.recall(query)
    if not results:
        typer.echo(f"No memories matched '{query}'.")
        return
    typer.echo(f"Found {len(results)} matches for '{query}':")
    for it in results:
        typer.echo(f"  #{it.id} [{it.category}] {it.key}: {it.content}")


app.add_typer(memory_app, name="memory")


def main():
    app()


if __name__ == "__main__":
    main()


