import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional
from fastapi import FastAPI, HTTPException, Query, Response, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, PlainTextResponse

from friday.core.bus import EventBus
from friday.core.permissions import PermissionDecision
from friday.dashboard.bus_bridge import ConnectionManager, DashboardBusBridge
from friday.dashboard.prompter import DashboardPrompter

logger = logging.getLogger("friday.dashboard.server")
SHARED_ROOT = Path("D:/AI-Agents/Shared")
SUPPORTED_PROFILES = ("local", "gemini-free", "gemini-paid", "groq", "deepseek", "claude")


def create_dashboard_app(
    workspace_path: Path,
    bus: Optional[EventBus] = None,
    static_html_path: Optional[Path] = None,
    lead_agent: Optional[Any] = None,
    router: Optional[Any] = None,
    prompter: Optional[DashboardPrompter] = None,
    memory: Optional[Any] = None,
) -> FastAPI:
    app = FastAPI(title="FRIDAY & JARVIS Observability Dashboard", version="1.0.0")
    manager = ConnectionManager()
    workspace_path = Path(workspace_path).resolve()

    # Automatically ensure runtime exists if not provided
    if lead_agent is None:
        try:
            from friday.cli import setup_runtime
            runtime = setup_runtime(target_dir=workspace_path, yolo=True)
            if bus is None:
                bus = runtime.get("bus")
            lead_agent = runtime.get("agent")
            if router is None:
                router = runtime.get("llm")
            if memory is None:
                memory = getattr(lead_agent, "memory", None)
        except Exception as e:
            logger.warning(f"Could not initialize FRIDAY runtime in dashboard app: {e}")

    if bus is None:
        bus = EventBus()

    bridge = DashboardBusBridge(bus=bus, manager=manager)

    if prompter is None:
        prompter = DashboardPrompter(manager=manager)
    elif prompter.manager is None:
        prompter.manager = manager

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/api/status")
    async def get_status() -> Dict[str, Any]:
        from friday.core.config import load_config
        active_prof = "groq"
        try:
            cfg = load_config(workspace_path)
            if cfg.active_profile:
                active_prof = cfg.active_profile
        except Exception:
            pass

        if router and hasattr(router, "get_active_profile"):
            active_prof = router.get_active_profile()

        return {
            "status": "ok",
            "workspace": str(workspace_path),
            "friday_state": getattr(lead_agent, "state", "IDLE") if lead_agent else "IDLE",
            "jarvis_state": "IDLE",
            "active_profile": active_prof,
        }

    @app.post("/api/profile")
    async def set_profile(payload: Dict[str, Any]) -> Dict[str, Any]:
        profile = payload.get("profile")
        if not profile or profile not in SUPPORTED_PROFILES:
            raise HTTPException(status_code=400, detail=f"Invalid profile. Must be one of {SUPPORTED_PROFILES}")

        from friday.core.config import load_config, save_config
        try:
            cfg = load_config(workspace_path)
            cfg.active_profile = profile
            save_config(workspace_path, cfg)
        except Exception as e:
            logger.warning(f"Could not persist config in {workspace_path}: {e}")

        if router and hasattr(router, "set_active_profile"):
            router.set_active_profile(profile)

        await manager.broadcast({
            "type": "profile_changed",
            "profile": profile,
        })
        return {"status": "ok", "active_profile": profile}

    @app.post("/api/task")
    async def run_task(payload: Dict[str, Any]) -> Dict[str, Any]:
        prompt = payload.get("prompt", "").strip()
        if not prompt:
            raise HTTPException(status_code=400, detail="prompt cannot be empty")

        import asyncio

        async def execute():
            try:
                # Immediate visual feedback
                if bus:
                    from friday.core.bus import AgentThoughtEvent
                    await bus.publish(AgentThoughtEvent(thought=f"Task received: '{prompt}'"))
                await manager.broadcast({
                    "type": "agent_state",
                    "state": "RUNNING",
                    "prompt": prompt,
                })

                if lead_agent and hasattr(lead_agent, "run_turn"):
                    status = await lead_agent.run_turn(prompt)
                    from friday.core.verifier import TaskStatus
                    if status == TaskStatus.DONE:
                        await manager.broadcast({
                            "type": "task_done",
                            "task_id": "turn",
                            "summary": f"Completed: {prompt}",
                        })
                    else:
                        await manager.broadcast({
                            "type": "task_blocked",
                            "task_id": "turn",
                            "reason": f"Execution completed with status: {status}",
                        })
                elif bus:
                    from friday.core.bus import AgentThoughtEvent, TaskDoneEvent
                    await bus.publish(AgentThoughtEvent(thought=f"Executing dashboard task: '{prompt}'"))
                    await asyncio.sleep(0.3)
                    await bus.publish(TaskDoneEvent(task_id="dashboard-task", summary=f"Completed '{prompt}'", evidence="ok"))
                else:
                    await manager.broadcast({
                        "type": "task_blocked",
                        "task_id": "dashboard-task",
                        "reason": "Agent runtime is not initialized",
                    })
            except Exception as e:
                logger.error(f"Task execution failed: {e}", exc_info=True)
                await manager.broadcast({
                    "type": "task_blocked",
                    "task_id": "dashboard-task",
                    "reason": f"Task error: {e}",
                    "diagnostics": str(e),
                })
            finally:
                await manager.broadcast({
                    "type": "agent_state",
                    "state": "IDLE",
                })

        asyncio.create_task(execute())
        return {"status": "started", "task": prompt}

    @app.get("/api/permission/pending")
    async def get_pending_permissions() -> List[Dict[str, Any]]:
        return [
            {"request_id": rid, "details": details}
            for rid, details in prompter.pending_details.items()
        ]

    @app.post("/api/permission")
    async def resolve_permission(payload: Dict[str, Any]) -> Dict[str, Any]:
        req_id = payload.get("request_id")
        raw_decision = payload.get("decision", "deny")
        if not req_id:
            raise HTTPException(status_code=400, detail="request_id required")

        try:
            decision = PermissionDecision(raw_decision)
        except Exception:
            decision = PermissionDecision.DENY

        ok = prompter.resolve(req_id, decision)
        if not ok:
            raise HTTPException(status_code=404, detail="Pending permission request not found")

        await manager.broadcast({
            "type": "permission_resolved",
            "request_id": req_id,
            "decision": decision.value,
        })
        return {"status": "ok", "request_id": req_id, "decision": decision.value}

    @app.get("/api/memory")
    async def get_memories(category: Optional[str] = Query(None)) -> List[Dict[str, Any]]:
        from friday.core.memory import AgencyMemory
        mem = memory or AgencyMemory()
        items = mem.list_all(category=category)
        return [
            {
                "id": it.id,
                "category": it.category,
                "key": it.key,
                "content": it.content,
                "metadata": it.metadata,
                "created_at": it.created_at,
                "access_count": it.access_count,
            }
            for it in items
        ]

    @app.post("/api/memory")
    async def add_memory(payload: Dict[str, Any]) -> Dict[str, Any]:
        category = payload.get("category", "convention")
        key = payload.get("key", "").strip()
        content = payload.get("content", "").strip()
        if not key or not content:
            raise HTTPException(status_code=400, detail="key and content required")
        from friday.core.memory import AgencyMemory
        mem = memory or AgencyMemory()
        m_id = mem.remember(
            category=category,
            key=key,
            content=content,
            metadata=payload.get("metadata", {}),
        )
        return {"status": "ok", "id": m_id, "key": key}

    @app.get("/api/mailbox")
    async def get_mailbox() -> List[Dict[str, Any]]:
        messages: List[Dict[str, Any]] = []
        mailboxes_dir = SHARED_ROOT / "mailboxes"
        if not mailboxes_dir.is_dir():
            return messages

        for box in ["friday_inbox", "jarvis_inbox"]:
            box_dir = mailboxes_dir / box
            if not box_dir.is_dir():
                continue
            for msg_file in sorted(box_dir.glob("*.json")):
                try:
                    data = json.loads(msg_file.read_text(encoding="utf-8"))
                    data["_file"] = msg_file.name
                    data["_box"] = box
                    messages.append(data)
                except Exception as e:
                    logger.debug(f"Failed to read mailbox message {msg_file}: {e}")

        return messages

    @app.get("/api/files")
    async def list_files() -> List[Dict[str, Any]]:
        items = []
        if not workspace_path.is_dir():
            return items

        skip_dirs = {".git", ".pytest_cache", "__pycache__", ".venv", ".superpowers"}
        for p in workspace_path.iterdir():
            if p.name in skip_dirs:
                continue
            items.append({
                "name": p.name,
                "path": str(p.relative_to(workspace_path)),
                "is_dir": p.is_dir(),
                "size": p.stat().st_size if p.is_file() else 0,
            })
        return items

    @app.get("/api/files/content", response_class=PlainTextResponse)
    async def get_file_content(path: str = Query(...)) -> str:
        target = (workspace_path / path).resolve()
        # Security check: must remain inside workspace
        if not str(target).startswith(str(workspace_path)):
            raise HTTPException(status_code=403, detail="Access denied")
        if not target.is_file():
            raise HTTPException(status_code=404, detail="File not found")
        try:
            return target.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @app.get("/", response_class=HTMLResponse)
    async def get_index() -> Response:
        html_file = static_html_path or (Path(__file__).parent / "static" / "index.html")
        if html_file.is_file():
            return HTMLResponse(content=html_file.read_text(encoding="utf-8"))
        return HTMLResponse(content="<h1>FRIDAY & JARVIS Observability Dashboard</h1>")

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket):
        await manager.connect(websocket)
        try:
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            manager.disconnect(websocket)
        except Exception:
            manager.disconnect(websocket)

    return app
