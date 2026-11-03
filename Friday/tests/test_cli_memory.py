from pathlib import Path
from typer.testing import CliRunner
from friday.cli import app
from friday.core.memory import AgencyMemory

runner = CliRunner()


def test_cli_memory_commands(tmp_path: Path, monkeypatch):
    test_db = tmp_path / "agency_mem.db"
    mem = AgencyMemory(db_path=test_db)
    mem.seed_defaults()

    # Monkeypatch default db path in AgencyMemory
    monkeypatch.setattr("friday.core.memory.DEFAULT_MEMORY_DB", test_db)

    # 1. friday memory list
    res = runner.invoke(app, ["memory", "list"])
    assert res.exit_code == 0
    assert "Stored Memories" in res.stdout
    assert "groq_model_preference" in res.stdout

    # 2. friday memory search
    res_search = runner.invoke(app, ["memory", "search", "PowerShell"])
    assert res_search.exit_code == 0
    assert "powershell_statement_separator" in res_search.stdout

    # 3. friday memory add
    res_add = runner.invoke(
        app,
        ["memory", "add", "convention", "doc_rule", "Write concise docstrings in code."],
    )
    assert res_add.exit_code == 0
    assert "Memory stored successfully" in res_add.stdout

    # Verify search finds added item
    res_search2 = runner.invoke(app, ["memory", "search", "concise"])
    assert res_search2.exit_code == 0
    assert "doc_rule" in res_search2.stdout
