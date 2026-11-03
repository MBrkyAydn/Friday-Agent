from pathlib import Path
import pytest
from friday.core.memory import AgencyMemory, MemoryItem
from friday.tools.memory import RememberTool, RecallTool


def test_memory_crud_and_fts(tmp_path: Path):
    db_file = tmp_path / "memory" / "test_memory.db"
    mem = AgencyMemory(db_path=db_file)

    # 1. Remember items
    m1_id = mem.remember(
        category="error_fix",
        key="powershell_statement_separator",
        content="In PowerShell, use ';' instead of '&&' to separate multiple commands.",
        metadata={"os": "windows"}
    )
    assert m1_id > 0

    m2_id = mem.remember(
        category="user_preference",
        key="groq_model_preference",
        content="User preferred Groq model is groq/openai/gpt-oss-120b.",
        metadata={"source": "user"}
    )
    assert m2_id > 0

    # 2. List all
    all_items = mem.list_all()
    assert len(all_items) == 2

    # 3. List by category
    fixes = mem.list_all(category="error_fix")
    assert len(fixes) == 1
    assert fixes[0].key == "powershell_statement_separator"

    # 4. Recall by query (FTS)
    results = mem.recall("PowerShell separator")
    assert len(results) >= 1
    assert results[0].id == m1_id
    assert "PowerShell" in results[0].content

    # Check access count incremented
    item = mem.get(m1_id)
    assert item is not None
    assert item.access_count >= 1

    # 5. Recall Groq preference
    groq_results = mem.recall("Groq model")
    assert len(groq_results) >= 1
    assert groq_results[0].id == m2_id

    # 6. Forget
    assert mem.forget(m1_id) is True
    assert len(mem.list_all()) == 1
    assert mem.get(m1_id) is None


@pytest.mark.asyncio
async def test_memory_tools(tmp_path: Path):
    db_file = tmp_path / "tools_mem.db"
    mem = AgencyMemory(db_path=db_file)

    remember_tool = RememberTool(memory=mem)
    recall_tool = RecallTool(memory=mem)

    # Execute RememberTool
    rem_res = await remember_tool.execute(
        category="architecture",
        key="mailbox_ipc",
        content="FRIDAY and JARVIS communicate via Shared/mailboxes inbox files."
    )
    assert rem_res.success is True
    assert "Remembered" in rem_res.output

    # Execute RecallTool
    rec_res = await recall_tool.execute(query="mailbox communication")
    assert rec_res.success is True
    assert "Shared/mailboxes" in rec_res.output
