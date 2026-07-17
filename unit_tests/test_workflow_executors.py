import asyncio
from pathlib import Path
from types import SimpleNamespace

import workflow.executors as executors
from workflow.models import (
    CombinedValidationResult,
    TestResult as WorkflowTestResult,
    ValidationResult,
)


class _FakeCtx:
    def __init__(self):
        self.state = {}
        self.sent = []
        self.outputs = []

    def set_state(self, key, value):
        self.state[key] = value

    def get_state(self, key, default=None):
        return self.state.get(key, default)

    async def send_message(self, message):
        self.sent.append(message)

    async def yield_output(self, text):
        self.outputs.append(text)


def _combined(task_id: str = "050_demo", retry_count: int = 0, max_retries: int = 3) -> CombinedValidationResult:
    return CombinedValidationResult(
        validation=ValidationResult(
            is_valid=False,
            reason="validation failed",
            task_id=task_id,
            task_directory=f"tests/game02/{task_id}",
        ),
        test=WorkflowTestResult(
            is_valid=False,
            reason="tests failed",
            task_id=task_id,
            task_directory=f"tests/game02/{task_id}",
            raw_output="raw output",
        ),
        retry_count=retry_count,
        max_retries=max_retries,
        target_topic="ConfigMaps",
        concept_description="desc",
        difficulty="BEGINNER",
        objective="obj",
    )


def _call_executor(fn, *args):
    return asyncio.run(fn._original_func(*args))


def test_initialize_retry_with_initial_state_creates_task_dir_and_sends_request(monkeypatch, tmp_path: Path):
    fake_paths = SimpleNamespace(game_root=tmp_path / "tests/game02")
    monkeypatch.setattr(executors, "PATHS", fake_paths)

    message = executors.InitialWorkflowState(
        prompt="generate task",
        target_topic="ConfigMaps",
        task_id="050_demo",
        concept_description="desc",
        difficulty="BEGINNER",
        objective="obj",
    )
    ctx = _FakeCtx()

    _call_executor(executors.initialize_retry, message, ctx)

    assert (fake_paths.game_root / "050_demo").exists()
    assert ctx.state["task_id"] == "050_demo"
    assert len(ctx.sent) == 1


def test_parse_generated_task_uses_state_task_id(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(executors, "PATHS", SimpleNamespace(game_root=tmp_path, game_name="game02"))
    ctx = _FakeCtx()
    ctx.set_state("task_id", "051_demo")
    response = SimpleNamespace(agent_response=SimpleNamespace(text="ignored"))

    _call_executor(executors.parse_generated_task, response, ctx)

    sent = ctx.sent[0]
    assert sent.task_id == "051_demo"
    assert sent.task_directory == "tests/game02/051_demo"


def test_make_decision_uses_default_validation_when_missing():
    ctx = _FakeCtx()
    test_result = WorkflowTestResult(
        is_valid=True,
        reason="ok",
        task_id="052_demo",
        task_directory="tests/game02/052_demo",
    )

    _call_executor(executors.make_decision, test_result, ctx)

    combined = ctx.sent[0]
    assert combined.validation.is_valid is True
    assert combined.test.task_id == "052_demo"


def test_remove_task_increments_retry_and_sets_failure_reasons():
    ctx = _FakeCtx()
    combined = _combined(task_id="053_demo", retry_count=1, max_retries=3)

    _call_executor(executors.remove_task, combined, ctx)

    assert ctx.state["retry_count"] == 2
    assert "failure_reasons_053_demo" in ctx.state
    assert "attempt 2/3" in ctx.outputs[0]
    assert ctx.sent[0].retry_count == 2


def test_run_pytest_skip_answer_marks_failure_when_check_does_not_fail(monkeypatch):
    ctx = _FakeCtx()
    combined = _combined(task_id="054_demo", retry_count=0, max_retries=2)

    import agents.pytest_runner as pytest_runner

    def fake_run(command: str):
        return {
            "is_valid": True,
            "reason": "all passed",
            "details": ["test_03_answer.py SKIPPED\nbut no check failure"],
        }

    monkeypatch.setattr(pytest_runner, "run_pytest_command", fake_run)

    _call_executor(executors.run_pytest_skip_answer, combined, ctx)

    updated = ctx.sent[0]
    assert updated.test.is_valid is False
    assert updated.retry_count == 1
    assert "failure_reasons_054_demo" in ctx.state


def test_complete_workflow_failure_moves_task_and_writes_report(monkeypatch, tmp_path: Path):
    game_root = tmp_path / "tests/game02"
    unsuccessful_root = tmp_path / "unsuccessful/game02"
    task_id = "055_demo"
    task_dir = game_root / task_id
    task_dir.mkdir(parents=True, exist_ok=True)
    (task_dir / "session.json").write_text('{"namespace":"x"}', encoding="utf-8")

    monkeypatch.setattr(
        executors,
        "PATHS",
        SimpleNamespace(game_root=game_root, unsuccessful_game_root=unsuccessful_root),
    )

    ctx = _FakeCtx()
    ctx.set_state("failure_reasons_055_demo", ["Validation failed: bad yaml"])
    ctx.set_state("raw_output_055_demo", "pytest output")
    combined = _combined(task_id=task_id, retry_count=3, max_retries=3)

    _call_executor(executors.complete_workflow, combined, ctx)

    moved_dir = unsuccessful_root / task_id
    assert moved_dir.exists()
    report = (moved_dir / "FAILURE_REPORT.txt").read_text(encoding="utf-8")
    assert "Task ID: 055_demo" in report
    assert "pytest output" in report
    assert "Workflow complete: Failed to generate valid task" in ctx.outputs[0]


def test_initialize_retry_parses_plain_input_dict(monkeypatch, tmp_path: Path):
    fake_paths = SimpleNamespace(game_root=tmp_path / "tests/game02")
    monkeypatch.setattr(executors, "PATHS", fake_paths)
    ctx = _FakeCtx()

    payload = {"input": "Generate task 060_demo_task about 'Pods'"}
    _call_executor(executors.initialize_retry, payload, ctx)

    assert ctx.state["task_id"] == "060_demo_task"
    assert ctx.state["target_topic"] == "Pods"
    assert len(ctx.sent) == 1


def test_parse_generated_task_extracts_id_from_response_text(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(executors, "PATHS", SimpleNamespace(game_root=tmp_path, game_name="game02"))
    ctx = _FakeCtx()
    response = SimpleNamespace(
        agent_response=SimpleNamespace(text=f"created at {tmp_path}/061_auto_task")
    )

    _call_executor(executors.parse_generated_task, response, ctx)
    assert ctx.sent[0].task_id == "061_auto_task"


def test_run_validation_collects_failure_reasons(monkeypatch):
    ctx = _FakeCtx()
    task_info = executors.TaskInfo(task_id="062_demo", task_directory="tests/game02/062_demo")

    import agents.k8s_task_validator as validator

    def fake_validate(_task_id):
        return {
            "is_valid": False,
            "details": [
                {"is_valid": False, "reason": "Missing files"},
                {"is_valid": False, "reason": "YAML invalid"},
                {"is_valid": True, "reason": "Validation completed"},
            ],
        }

    monkeypatch.setattr(validator, "validate_task_directory", fake_validate)
    _call_executor(executors.run_validation, task_info, ctx)

    sent = ctx.sent[0]
    assert sent.validation.is_valid is False
    assert "Missing files" in sent.validation.reason


def test_run_pytest_captures_raw_output(monkeypatch):
    ctx = _FakeCtx()
    task = executors.TaskWithValidation(
        task_id="063_demo",
        task_directory="tests/game02/063_demo",
        validation=ValidationResult(
            is_valid=True, reason="ok", task_id="063_demo", task_directory="tests/game02/063_demo"
        ),
    )

    import agents.pytest_runner as pytest_runner

    monkeypatch.setattr(
        pytest_runner,
        "run_pytest_command",
        lambda _cmd: {"is_valid": True, "reason": "ok", "details": ["RAW"]},
    )
    _call_executor(executors.run_pytest, task, ctx)

    assert ctx.state["raw_output_063_demo"] == "RAW"
    assert ctx.sent[0].raw_output == "RAW"


def test_retry_generation_requires_metadata():
    ctx = _FakeCtx()
    bad = CombinedValidationResult(
        validation=ValidationResult(is_valid=False, reason="bad", task_id="064_demo", task_directory="x"),
        test=WorkflowTestResult(is_valid=False, reason="bad", task_id="064_demo", task_directory="x"),
        retry_count=0,
        max_retries=1,
        target_topic="",
        concept_description="",
    )

    import pytest

    with pytest.raises(ValueError, match="Missing task metadata"):
        _call_executor(executors.retry_generation, bad, ctx)


def test_fix_task_requires_metadata():
    ctx = _FakeCtx()
    bad = CombinedValidationResult(
        validation=ValidationResult(is_valid=False, reason="bad", task_id="065_demo", task_directory="x"),
        test=WorkflowTestResult(is_valid=False, reason="bad", task_id="065_demo", task_directory="x"),
        retry_count=0,
        max_retries=1,
        target_topic="",
        concept_description="",
    )

    import pytest

    with pytest.raises(ValueError, match="Missing task metadata"):
        _call_executor(executors.fix_task, bad, ctx)


def test_run_pytest_skip_answer_success_path_restores_env(monkeypatch):
    import os
    import agents.pytest_runner as pytest_runner

    ctx = _FakeCtx()
    combined = _combined(task_id="066_demo")
    os.environ["SKIP_ANSWER_TESTS"] = "old"

    monkeypatch.setattr(
        pytest_runner,
        "run_pytest_command",
        lambda _cmd: {
            "is_valid": False,
            "reason": "expected",
            "details": ["test_03_answer.py SKIPPED\ntest_05_check.py FAILED"],
        },
    )
    _call_executor(executors.run_pytest_skip_answer, combined, ctx)

    assert ctx.sent[0].test.task_id == "066_demo"
    assert os.environ["SKIP_ANSWER_TESTS"] == "old"


def test_complete_workflow_success_branch():
    ctx = _FakeCtx()
    combined = CombinedValidationResult(
        validation=ValidationResult(is_valid=True, reason="ok", task_id="067_demo", task_directory="x"),
        test=WorkflowTestResult(is_valid=True, reason="ok", task_id="067_demo", task_directory="x"),
        retry_count=0,
        max_retries=1,
    )

    _call_executor(executors.complete_workflow, combined, ctx)
    assert "successfully generated" in ctx.outputs[0]


def test_initialize_retry_unknown_dict_and_existing_state(monkeypatch, tmp_path: Path):
    fake_paths = SimpleNamespace(game_root=tmp_path / "tests/game02")
    monkeypatch.setattr(executors, "PATHS", fake_paths)
    ctx = _FakeCtx()
    ctx.set_state("task_id", "068_demo")
    ctx.set_state("target_topic", "Pods")

    payload = {"unexpected": 1}
    _call_executor(executors.initialize_retry, payload, ctx)

    assert (fake_paths.game_root / "068_demo").exists()
    assert len(ctx.sent) == 1


def test_parse_generated_task_raises_when_no_id(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(executors, "PATHS", SimpleNamespace(game_root=tmp_path, game_name="game02"))
    ctx = _FakeCtx()
    response = SimpleNamespace(agent_response=SimpleNamespace(text="no task id here"))

    import pytest

    with pytest.raises(ValueError, match="Failed to parse task ID"):
        _call_executor(executors.parse_generated_task, response, ctx)


def test_run_validation_default_failure_reason_when_no_details(monkeypatch):
    ctx = _FakeCtx()
    task_info = executors.TaskInfo(task_id="069_demo", task_directory="tests/game02/069_demo")

    import agents.k8s_task_validator as validator

    monkeypatch.setattr(
        validator,
        "validate_task_directory",
        lambda _task_id: {"is_valid": False, "details": []},
    )
    _call_executor(executors.run_validation, task_info, ctx)
    assert "Validation failed - check file structure and syntax" in ctx.sent[0].validation.reason


def test_run_pytest_without_details_keeps_empty_raw_output(monkeypatch):
    ctx = _FakeCtx()
    task = executors.TaskWithValidation(
        task_id="070_demo",
        task_directory="tests/game02/070_demo",
        validation=ValidationResult(is_valid=True, reason="ok", task_id="070_demo", task_directory="x"),
    )
    import agents.pytest_runner as pytest_runner

    monkeypatch.setattr(pytest_runner, "run_pytest_command", lambda _cmd: {"is_valid": True, "reason": "ok", "details": []})
    _call_executor(executors.run_pytest, task, ctx)
    assert ctx.sent[0].raw_output == ""


def test_keep_task_and_check_loop_forward_combined():
    ctx = _FakeCtx()
    combined = _combined(task_id="071_demo")
    _call_executor(executors.keep_task, combined, ctx)
    _call_executor(executors.check_loop, combined, ctx)
    assert "passed all checks" in ctx.outputs[0]
    assert ctx.sent[-1].test.task_id == "071_demo"


def test_retry_generation_success_sets_state_and_sends_prompt(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(executors, "PATHS", SimpleNamespace(game_root=tmp_path / "tests/game02"))
    ctx = _FakeCtx()
    combined = _combined(task_id="072_demo", retry_count=1, max_retries=3)

    _call_executor(executors.retry_generation, combined, ctx)
    assert ctx.state["task_id"] == "072_demo"
    prompt = ctx.sent[0].messages[0].contents[0].text
    assert "retry attempt 2 of 3" in prompt


def test_fix_task_success_includes_raw_output_in_prompt(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(executors, "PATHS", SimpleNamespace(game_root=tmp_path / "tests/game02"))
    ctx = _FakeCtx()
    combined = _combined(task_id="073_demo", retry_count=0, max_retries=2)
    ctx.set_state("raw_output_073_demo", "RAW OUTPUT HERE")

    _call_executor(executors.fix_task, combined, ctx)
    sent_prompt = ctx.sent[0].messages[0].contents[0].text
    assert "FULL TEST OUTPUT" in sent_prompt
    assert "RAW OUTPUT HERE" in sent_prompt


def test_complete_workflow_uses_default_reasons_and_timestamp_on_collision(monkeypatch, tmp_path: Path):
    game_root = tmp_path / "tests/game02"
    unsuccessful_root = tmp_path / "unsuccessful/game02"
    task_id = "074_demo"
    task_dir = game_root / task_id
    task_dir.mkdir(parents=True, exist_ok=True)
    (task_dir / "session.json").write_text('{"namespace":"x"}', encoding="utf-8")
    (unsuccessful_root / task_id).mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(
        executors,
        "PATHS",
        SimpleNamespace(game_root=game_root, unsuccessful_game_root=unsuccessful_root),
    )

    import time
    monkeypatch.setattr(time, "strftime", lambda _fmt: "20260101_000000")

    ctx = _FakeCtx()
    combined = _combined(task_id=task_id, retry_count=3, max_retries=3)
    _call_executor(executors.complete_workflow, combined, ctx)

    moved_dir = unsuccessful_root / f"{task_id}_20260101_000000"
    assert moved_dir.exists()
