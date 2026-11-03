import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from jarvis.coder import CoderResult, JarvisCoder


def test_parse_files_from_response_multiple():
    coder = JarvisCoder()
    sample_response = """
Here are the files:

FILE: main.py
```python
from fastapi import FastAPI
app = FastAPI()

@app.get("/add")
def add(a: int, b: int):
    return {"result": a + b}
```

FILE: tests/test_main.py
```python
def test_addition():
    assert 1 + 1 == 2
```
"""
    files = coder._parse_files_from_response(sample_response)
    assert len(files) == 2
    assert files[0][0] == "main.py"
    assert "FastAPI" in files[0][1]
    assert files[1][0] == "tests/test_main.py"
    assert "test_addition" in files[1][1]


def test_write_files_safe_and_traversal_prevention(tmp_path: Path):
    coder = JarvisCoder()
    files = [
        ("api/app.py", "x = 42\n"),
        ("../escaped.py", "malicious = True\n"),
    ]

    written = coder._write_files(tmp_path, files)
    assert written == ["api/app.py"]
    assert (tmp_path / "api" / "app.py").exists()
    assert (tmp_path / "api" / "app.py").read_text(encoding="utf-8") == "x = 42\n"
    assert not (tmp_path.parent / "escaped.py").exists()


def test_verify_workspace_valid_syntax(tmp_path: Path):
    coder = JarvisCoder()
    test_file = tmp_path / "script.py"
    test_file.write_text("def foo():\n    return 100\n", encoding="utf-8")

    ok, msg = coder._verify_workspace(tmp_path)
    assert ok is True
    assert "Syntax check passed" in msg


def test_verify_workspace_syntax_error(tmp_path: Path):
    coder = JarvisCoder()
    test_file = tmp_path / "bad.py"
    test_file.write_text("def broken(\n", encoding="utf-8")

    ok, msg = coder._verify_workspace(tmp_path)
    assert ok is False
    assert "Syntax verification failed" in msg


def test_execute_task_end_to_end_mocked(tmp_path: Path):
    coder = JarvisCoder()
    mock_llm_response = """
FILE: main.py
```python
def add(a: int, b: int) -> int:
    return a + b
```

FILE: test_calc.py
```python
def test_calc():
    from main import add
    assert add(2, 3) == 5
```
"""

    with patch.object(coder, "_call_llm", return_value=mock_llm_response):
        result = coder.execute_task(
            task="Write an addition function and test",
            workspace_dir=tmp_path,
        )

        assert result.success is True
        assert "main.py" in result.files_created
        assert "test_calc.py" in result.files_created
        assert (tmp_path / "main.py").exists()
        assert (tmp_path / "test_calc.py").exists()
        assert "Created files" in result.output
