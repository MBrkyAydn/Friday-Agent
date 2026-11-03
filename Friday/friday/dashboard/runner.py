import argparse
import logging
from pathlib import Path
import uvicorn

from friday.cli import setup_runtime
from friday.dashboard.server import create_dashboard_app

logger = logging.getLogger("friday.dashboard.runner")


def main():
    parser = argparse.ArgumentParser(description="FRIDAY & JARVIS Observability Dashboard Runner")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind")
    parser.add_argument("--port", type=int, default=8000, help="Port to bind")
    parser.add_argument("--workspace", default=".", help="Workspace path to observe")
    args = parser.parse_args()

    workspace_path = Path(args.workspace).resolve()

    # Boot full FRIDAY runtime so dashboard can execute real tasks
    bus = None
    lead_agent = None
    router = None
    memory = None
    try:
        runtime = setup_runtime(target_dir=workspace_path, yolo=True)
        bus = runtime.get("bus")
        lead_agent = runtime.get("agent")
        router = runtime.get("llm")
        memory = getattr(lead_agent, "memory", None)
    except Exception as e:
        logger.warning(f"Could not initialize full FRIDAY agent runtime in dashboard: {e}")

    app = create_dashboard_app(
        workspace_path=workspace_path,
        bus=bus,
        lead_agent=lead_agent,
        router=router,
        memory=memory,
    )
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
