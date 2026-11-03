import asyncio
import uuid
from typing import Any, Callable, Coroutine, Dict
from friday.core.bus import EventBus, SubagentProgressEvent
from friday.core.workspace import WorkspaceGuard
from friday.agent.subagents.base import SubagentResult, BaseSubagent

WorkerRunner = Callable[[str], Coroutine[Any, Any, SubagentResult]]


class SubagentPool:
    def __init__(self, bus: EventBus, workspace: WorkspaceGuard) -> None:
        self.bus = bus
        self.workspace = workspace
        self.active_tasks: Dict[str, asyncio.Task[SubagentResult]] = {}

    async def spawn(self, role: str, prompt: str, runner: WorkerRunner) -> str:
        task_id = f"subagent-{role}-{uuid.uuid4().hex[:6]}"

        async def _wrapper() -> SubagentResult:
            await self.bus.publish(
                SubagentProgressEvent(
                    subagent_id=task_id, role=role, message=f"Starting: {prompt[:60]}"
                )
            )
            try:
                res = await runner(prompt)
            except Exception as e:
                res = SubagentResult(success=False, summary="", error=str(e))

            await self.bus.publish(
                SubagentProgressEvent(
                    subagent_id=task_id,
                    role=role,
                    message="Completed" if res.success else "Failed",
                )
            )
            return res

        task = asyncio.create_task(_wrapper())
        self.active_tasks[task_id] = task
        return task_id

    async def spawn_worker(self, worker: BaseSubagent, prompt: str) -> str:
        """Spawn a typed BaseSubagent worker in the pool."""
        return await self.spawn(role=worker.role, prompt=prompt, runner=worker.run)

    async def wait_for(self, task_id: str) -> SubagentResult:
        task = self.active_tasks.get(task_id)
        if not task:
            return SubagentResult(success=False, summary="", error="Task not found")

        try:
            return await task
        finally:
            self.active_tasks.pop(task_id, None)
