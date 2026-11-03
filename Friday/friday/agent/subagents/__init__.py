"""FRIDAY Subagents: Worker isolation, specialized subagents, and pool management."""

from friday.agent.subagents.base import SubagentResult, BaseSubagent
from friday.agent.subagents.pool import SubagentPool
from friday.agent.subagents.researcher import ResearcherSubagent
from friday.agent.subagents.coder import CoderSubagent
from friday.agent.subagents.tester import TesterSubagent

__all__ = [
    "SubagentResult",
    "BaseSubagent",
    "SubagentPool",
    "ResearcherSubagent",
    "CoderSubagent",
    "TesterSubagent",
]
