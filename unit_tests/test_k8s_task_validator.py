import asyncio
from pathlib import Path
from types import SimpleNamespace

import agents.k8s_task_validator as validator


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_sanitize_jinja_placeholders_replaces_expressions_and_blocks():
    text = "name: {{ namespace }}\n{%- if x -%}\nvalue: 1\n{%- endif -%}\n"
    out = validator._sanitize_jinja_placeholders(text)
    assert "JINJA_VALUE" in out
    assert "# JINJA_BLOCK" in out


def test_validate_yaml_file_with_jinja_is_valid(monkeypatch, tmp_path: Path):
    base = tmp_path / "tasks"
    _write(base / "001_demo/setup.template.yaml", "metadata:\n  name: {{namespace}}\n")
    monkeypatch.setattr(
        validator,
        "VALIDATION",
        SimpleNamespace(base_task_root=base, required_files=(), yaml_files=(), py_files=(), json_files=()),
    )

    result = validator.validate_yaml_file("001_demo/setup.template.yaml")
    assert result["is_valid"] is True


def test_validate_python_file_returns_error_on_syntax_issue(monkeypatch, tmp_path: Path):
    base = tmp_path / "tasks"
    _write(base / "001_demo/test_01_setup.py", "def broken(:\n    pass\n")
    monkeypatch.setattr(
        validator,
        "VALIDATION",
        SimpleNamespace(base_task_root=base, required_files=(), yaml_files=(), py_files=(), json_files=()),
    )

    result = validator.validate_python_file("001_demo/test_01_setup.py")
    assert result["is_valid"] is False
    assert "syntax error" in result["reason"].lower()


def test_validate_task_directory_end_to_end(monkeypatch, tmp_path: Path):
    base = tmp_path / "tasks"
    task_id = "001_demo"
    task_dir = base / task_id

    required_files = (
        "__init__.py",
        "instruction.md",
        "concept.md",
        "session.json",
        "setup.template.yaml",
        "answer.template.yaml",
        "test_01_setup.py",
        "test_02_ready.py",
        "test_03_answer.py",
        "test_05_check.py",
        "test_06_cleanup.py",
    )

    for filename in required_files:
        if filename.endswith(".json"):
            _write(task_dir / filename, '{"namespace":"demo"}')
        elif filename.endswith(".yaml"):
            _write(task_dir / filename, "apiVersion: v1\nkind: Namespace\nmetadata:\n  name: {{namespace}}\n")
        elif filename.endswith(".py"):
            _write(task_dir / filename, "def test_ok():\n    assert True\n")
        else:
            _write(task_dir / filename, "ok\n")

    monkeypatch.setattr(
        validator,
        "VALIDATION",
        SimpleNamespace(
            base_task_root=base,
            required_files=required_files,
            yaml_files=("setup.template.yaml", "answer.template.yaml"),
            py_files=(
                "test_01_setup.py",
                "test_02_ready.py",
                "test_03_answer.py",
                "test_04_challenge.py",
                "test_05_check.py",
                "test_06_cleanup.py",
            ),
            json_files=("session.json",),
        ),
    )

    result = validator.validate_task_directory(task_id)
    assert result["is_valid"] is True
    assert result["reason"] == "Validation completed"


def test_get_k8s_task_validator_extracts_task_id(monkeypatch):
    captured = {}

    def fake_validate(task_dir: str):
        captured["task_dir"] = task_dir
        return {"is_valid": True, "reason": "ok", "details": []}

    monkeypatch.setattr(validator, "validate_task_directory", fake_validate)
    wrapper = validator.get_k8s_task_validator()

    result = asyncio.run(wrapper.run("please validate tests/game02/123_demo_task now"))
    assert captured["task_dir"] == "123_demo_task"
    assert '"is_valid": true' in result.text


def test_check_required_files_returns_missing(monkeypatch, tmp_path: Path):
    base = tmp_path / "tasks"
    task_dir = base / "001_demo"
    task_dir.mkdir(parents=True, exist_ok=True)
    _write(task_dir / "__init__.py", "")
    monkeypatch.setattr(
        validator,
        "VALIDATION",
        SimpleNamespace(base_task_root=base, required_files=("__init__.py", "instruction.md"), yaml_files=(), py_files=(), json_files=()),
    )

    result = validator.check_required_files("001_demo")
    assert result["is_valid"] is False
    assert "Missing files" in result["reason"]


def test_validate_yaml_template_python_not_found(monkeypatch, tmp_path: Path):
    base = tmp_path / "tasks"
    monkeypatch.setattr(
        validator,
        "VALIDATION",
        SimpleNamespace(base_task_root=base, required_files=(), yaml_files=(), py_files=(), json_files=()),
    )
    assert validator.validate_yaml_file("001/no.yaml")["is_valid"] is False
    assert validator.validate_template_file("001/no.tmpl")["is_valid"] is False
    assert validator.validate_python_file("001/no.py")["is_valid"] is False


def test_validate_template_file_reports_syntax_error(monkeypatch, tmp_path: Path):
    base = tmp_path / "tasks"
    _write(base / "001_demo/setup.template.yaml", "{% if x %}\nname: demo\n")
    monkeypatch.setattr(
        validator,
        "VALIDATION",
        SimpleNamespace(base_task_root=base, required_files=(), yaml_files=(), py_files=(), json_files=()),
    )

    result = validator.validate_template_file("001_demo/setup.template.yaml")
    assert result["is_valid"] is False
    assert "Template syntax error" in result["reason"]


def test_validate_task_directory_not_found(monkeypatch, tmp_path: Path):
    base = tmp_path / "tasks"
    monkeypatch.setattr(
        validator,
        "VALIDATION",
        SimpleNamespace(base_task_root=base, required_files=(), yaml_files=(), py_files=(), json_files=()),
    )
    result = validator.validate_task_directory("001_missing")
    assert result["is_valid"] is False
    assert "Task directory not found" in result["reason"]


def test_validate_task_directory_handles_listing_and_loop_exceptions(monkeypatch, tmp_path: Path):
    base = tmp_path / "tasks"
    task_dir = base / "001_demo"
    task_dir.mkdir(parents=True, exist_ok=True)
    _write(task_dir / "setup.template.yaml", "name: {{namespace}}")

    monkeypatch.setattr(
        validator,
        "VALIDATION",
        SimpleNamespace(
            base_task_root=base,
            required_files=(),
            yaml_files=("setup.template.yaml",),
            py_files=(),
            json_files=(),
        ),
    )
    monkeypatch.setattr(validator, "_list_task_files", lambda _p: (_ for _ in ()).throw(RuntimeError("boom")))
    result = validator.validate_task_directory("001_demo")
    assert result["is_valid"] is False
    reasons = [d["reason"] for d in result["details"] if isinstance(d, dict)]
    assert any("Unable to list files" in r for r in reasons)
    assert any("Unexpected error during per-file validation" in r for r in reasons)


def test_get_k8s_task_validator_raises_without_task_id(monkeypatch):
    captured = {}

    def fake_validate(task_dir: str):
        captured["task_dir"] = task_dir
        return {"is_valid": True, "reason": "ok", "details": []}

    monkeypatch.setattr(validator, "validate_task_directory", fake_validate)
    wrapper = validator.get_k8s_task_validator()

    import pytest
    with pytest.raises(ValueError, match="Could not extract task directory"):
        asyncio.run(wrapper.run("raw_task_name_without_id"))
