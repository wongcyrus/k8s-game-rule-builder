import asyncio
from pathlib import Path
from types import SimpleNamespace

import agents.pytest_runner as pytest_runner


class _SubprocessResult:
    def __init__(self, returncode: int, stdout: str = "", stderr: str = ""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def test_normalize_pytest_command_adds_s_flag():
    command = "pytest --import-mode=importlib tests/game02/001_task/"
    normalized = pytest_runner._normalize_pytest_command(command)
    assert normalized.startswith("pytest -s ")


def test_normalize_pytest_command_keeps_capture_no():
    command = "pytest --capture=no tests/game02/001_task/"
    normalized = pytest_runner._normalize_pytest_command(command)
    assert normalized == command


def test_normalize_pytest_command_non_pytest_passthrough():
    command = "python -m pytest tests/game02/001_task/"
    assert pytest_runner._normalize_pytest_command(command) == command


def test_extract_task_dir_returns_none_for_non_matching_command():
    assert pytest_runner._extract_task_dir("pytest tests/just_one_segment/") is None


def test_run_pytest_command_success_saves_result_file(monkeypatch, tmp_path: Path):
    captured = {}

    def fake_run(cmd_list, capture_output, text, check, cwd):
        captured["cmd_list"] = cmd_list
        captured["cwd"] = cwd
        return _SubprocessResult(returncode=0, stdout="PASS", stderr="")

    monkeypatch.setattr(pytest_runner, "PATHS", SimpleNamespace(pytest_rootdir=tmp_path))
    monkeypatch.setattr(pytest_runner.subprocess, "run", fake_run)

    result = pytest_runner.run_pytest_command(
        "pytest --import-mode=importlib --rootdir=. tests/game02/002_create_namespace/"
    )

    assert result["is_valid"] is True
    assert result["reason"] == "All tests passed"
    assert "-s" in captured["cmd_list"]
    assert captured["cwd"] == str(tmp_path)

    output_file = tmp_path / "tests/game02/002_create_namespace/test_result.txt"
    assert output_file.exists()
    assert "PASS" in output_file.read_text(encoding="utf-8")


def test_run_pytest_command_skip_answer_uses_no_answer_filename(monkeypatch, tmp_path: Path):
    def fake_run(*args, **kwargs):
        return _SubprocessResult(returncode=0, stdout="PASS", stderr="")

    monkeypatch.setattr(pytest_runner, "PATHS", SimpleNamespace(pytest_rootdir=tmp_path))
    monkeypatch.setattr(pytest_runner.subprocess, "run", fake_run)
    monkeypatch.setenv("SKIP_ANSWER_TESTS", "True")

    result = pytest_runner.run_pytest_command(
        "pytest --import-mode=importlib tests/game02/003_task/"
    )

    assert result["is_valid"] is True
    output_file = tmp_path / "tests/game02/003_task/no_answer_test_result.txt"
    assert output_file.exists()


def test_run_pytest_command_no_tests_collected(monkeypatch, tmp_path: Path):
    def fake_run(*args, **kwargs):
        return _SubprocessResult(returncode=5, stdout="", stderr="no tests collected")

    monkeypatch.setattr(pytest_runner, "PATHS", SimpleNamespace(pytest_rootdir=tmp_path))
    monkeypatch.setattr(pytest_runner.subprocess, "run", fake_run)

    result = pytest_runner.run_pytest_command("pytest tests/game02/004_task/")

    assert result["is_valid"] is False
    assert result["reason"] == "No tests collected"


def test_run_pytest_command_returns_failed_for_nonzero_exit(monkeypatch, tmp_path: Path):
    def fake_run(*args, **kwargs):
        return _SubprocessResult(returncode=1, stdout="", stderr="failed")

    monkeypatch.setattr(pytest_runner, "PATHS", SimpleNamespace(pytest_rootdir=tmp_path))
    monkeypatch.setattr(pytest_runner.subprocess, "run", fake_run)

    result = pytest_runner.run_pytest_command("pytest tests/game02/004_task/")
    assert result["is_valid"] is False
    assert result["reason"] == "Tests failed (exit code 1)"


def test_run_pytest_command_invalid_shell_syntax(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(pytest_runner, "PATHS", SimpleNamespace(pytest_rootdir=tmp_path))
    result = pytest_runner.run_pytest_command("pytest \"unterminated")
    assert result["is_valid"] is False
    assert "Invalid pytest command" in result["reason"]


def test_run_pytest_command_handles_save_output_oserror(monkeypatch, tmp_path: Path):
    def fake_run(*args, **kwargs):
        return _SubprocessResult(returncode=0, stdout="ok", stderr="")

    def fake_save(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(pytest_runner, "PATHS", SimpleNamespace(pytest_rootdir=tmp_path))
    monkeypatch.setattr(pytest_runner.subprocess, "run", fake_run)
    monkeypatch.setattr(pytest_runner, "_save_test_output", fake_save)

    result = pytest_runner.run_pytest_command("pytest tests/game02/005_task/")
    assert result["is_valid"] is False
    assert "Failed to save test output" in result["reason"]


def test_get_pytest_runner_extracts_pytest_command(monkeypatch):
    captured = {}

    def fake_run(command: str):
        captured["command"] = command
        return {"is_valid": True, "reason": "ok", "details": []}

    monkeypatch.setattr(pytest_runner, "run_pytest_command", fake_run)
    runner = pytest_runner.get_pytest_runner()

    prompt = "Please execute this:\npytest tests/game02/001_task/ -q\nthanks"
    result = asyncio.run(runner.run(prompt))

    assert captured["command"] == "pytest tests/game02/001_task/ -q"
    assert '"is_valid": true' in result.text
