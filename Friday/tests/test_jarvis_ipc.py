import asyncio
import pytest
from pathlib import Path

from friday.core.workspace import WorkspaceGuard
from friday.core.permissions import PermissionController, PermissionTier
from friday.core.shared_bus import SharedBusProtocol
from friday.tools.jarvis_ipc import DelegateJarvisTool
from friday.cli import setup_runtime
from jarvis.worker import JarvisWorker


@pytest.fixture
def env_paths(tmp_path: Path):
    ws_dir = tmp_path / "Friday"
    shared_root = tmp_path / "Shared"
    logs_root = tmp_path / "Logs"
    ws_dir.mkdir(parents=True, exist_ok=True)
    shared_root.mkdir(parents=True, exist_ok=True)
    logs_root.mkdir(parents=True, exist_ok=True)
    return ws_dir, shared_root, logs_root


def test_delegate_jarvis_tool_metadata(env_paths):
    ws_dir, shared_root, logs_root = env_paths
    guard = WorkspaceGuard(target_dir=ws_dir)
    perms = PermissionController(yolo_mode=True)
    tool = DelegateJarvisTool(
        workspace=guard,
        permissions=perms,
        shared_root=shared_root,
        logs_root=logs_root,
    )

    assert tool.name == "delegate_jarvis"
    assert tool.tier == PermissionTier.TIER_0_SAFE
    schema = tool.to_schema()
    assert schema["type"] == "function"
    assert schema["function"]["name"] == "delegate_jarvis"
    assert "task" in schema["function"]["parameters"]["properties"]


@pytest.mark.asyncio
async def test_delegate_jarvis_empty_task_rejected(env_paths):
    ws_dir, shared_root, logs_root = env_paths
    guard = WorkspaceGuard(target_dir=ws_dir)
    perms = PermissionController(yolo_mode=True)
    tool = DelegateJarvisTool(
        workspace=guard,
        permissions=perms,
        shared_root=shared_root,
        logs_root=logs_root,
    )

    result = await tool.execute(task="")
    assert result.success is False
    assert "cannot be empty" in result.error


@pytest.mark.asyncio
async def test_delegate_jarvis_timeout_handling(env_paths):
    ws_dir, shared_root, logs_root = env_paths
    guard = WorkspaceGuard(target_dir=ws_dir)
    perms = PermissionController(yolo_mode=True)
    tool = DelegateJarvisTool(
        workspace=guard,
        permissions=perms,
        shared_root=shared_root,
        logs_root=logs_root,
        default_timeout=0.1,
        poll_interval=0.02,
    )

    result = await tool.execute(task="Task that nobody will answer", timeout=0.1)
    assert result.success is False
    assert "Timeout: JARVIS did not respond" in result.error


@pytest.mark.asyncio
async def test_delegate_jarvis_success_flow(env_paths):
    ws_dir, shared_root, logs_root = env_paths
    guard = WorkspaceGuard(target_dir=ws_dir)
    perms = PermissionController(yolo_mode=True)
    tool = DelegateJarvisTool(
        workspace=guard,
        permissions=perms,
        shared_root=shared_root,
        logs_root=logs_root,
        poll_interval=0.02,
    )

    jarvis_bus = SharedBusProtocol(shared_root=shared_root, logs_root=logs_root, agent_name="Jarvis")

    async def jarvis_simulated_responder():
        # Wait until message arrives in Jarvis inbox
        for _ in range(50):
            messages = jarvis_bus.read_inbox()
            if messages:
                msg = messages[0]
                jarvis_bus.send_message(
                    recipient="Friday",
                    action="task_completed",
                    payload={
                        "in_reply_to": msg["message_id"],
                        "result": "Refactored payment gateway successfully",
                        "success": True,
                    },
                )
                return
            await asyncio.sleep(0.02)

    responder_task = asyncio.create_task(jarvis_simulated_responder())
    result = await tool.execute(task="Refactor payment gateway", timeout=2.0)
    await responder_task

    assert result.success is True
    assert "Refactored payment gateway successfully" in result.output
    assert result.error is None


@pytest.mark.asyncio
async def test_delegate_jarvis_failed_flow(env_paths):
    ws_dir, shared_root, logs_root = env_paths
    guard = WorkspaceGuard(target_dir=ws_dir)
    perms = PermissionController(yolo_mode=True)
    tool = DelegateJarvisTool(
        workspace=guard,
        permissions=perms,
        shared_root=shared_root,
        logs_root=logs_root,
        poll_interval=0.02,
    )

    jarvis_bus = SharedBusProtocol(shared_root=shared_root, logs_root=logs_root, agent_name="Jarvis")

    async def jarvis_simulated_failure():
        for _ in range(50):
            messages = jarvis_bus.read_inbox()
            if messages:
                msg = messages[0]
                jarvis_bus.send_message(
                    recipient="Friday",
                    action="task_failed",
                    payload={
                        "in_reply_to": msg["message_id"],
                        "error": "SyntaxError in generated code",
                        "success": False,
                    },
                )
                return
            await asyncio.sleep(0.02)

    responder_task = asyncio.create_task(jarvis_simulated_failure())
    result = await tool.execute(task="Write buggy code", timeout=2.0)
    await responder_task

    assert result.success is False
    assert "SyntaxError in generated code" in result.error


@pytest.mark.asyncio
async def test_delegate_jarvis_e2e_with_actual_worker(env_paths):
    ws_dir, shared_root, logs_root = env_paths
    guard = WorkspaceGuard(target_dir=ws_dir)
    perms = PermissionController(yolo_mode=True)
    tool = DelegateJarvisTool(
        workspace=guard,
        permissions=perms,
        shared_root=shared_root,
        logs_root=logs_root,
        poll_interval=0.02,
    )

    worker = JarvisWorker(
        shared_root=shared_root,
        logs_root=logs_root,
        workspace_root=ws_dir,
        enable_coder=False,
    )

    async def worker_loop():
        for _ in range(50):
            processed = worker.process_next_task()
            if processed:
                return
            await asyncio.sleep(0.02)

    worker_task = asyncio.create_task(worker_loop())
    result = await tool.execute(task="Create report and verify", timeout=2.0)
    await worker_task

    assert result.success is True
    assert "Task completed and verified by JARVIS" in result.output


def test_cli_wires_delegate_jarvis_tool(tmp_path: Path):
    runtime = setup_runtime(target_dir=tmp_path, yolo=True)

    # Tool registered in runtime tools
    tool_names = [t.name for t in runtime["tools"]]
    assert "delegate_jarvis" in tool_names

    # Tool registered on LeadAgent
    agent_tool_names = [t.name for t in runtime["agent"].tools]
    assert "delegate_jarvis" in agent_tool_names

    # Tool exposed in runtime dict
    assert "jarvis_tool" in runtime
    assert isinstance(runtime["jarvis_tool"], DelegateJarvisTool)
