from workflow.models import (
    CombinedValidationResult,
    TestResult as WorkflowTestResult,
    ValidationResult,
)
from workflow.selectors import select_action, select_loop_action, select_skip_answer_action


def _combined(
    *,
    validation_ok: bool,
    test_ok: bool,
    retry_count: int = 0,
    max_retries: int = 3,
) -> CombinedValidationResult:
    return CombinedValidationResult(
        validation=ValidationResult(
            is_valid=validation_ok,
            reason="v",
            task_id="t1",
            task_directory="/tmp/t1",
        ),
        test=WorkflowTestResult(
            is_valid=test_ok,
            reason="t",
            task_id="t1",
            task_directory="/tmp/t1",
        ),
        retry_count=retry_count,
        max_retries=max_retries,
    )


def test_should_keep_true_when_validation_and_test_pass():
    combined = _combined(validation_ok=True, test_ok=True)
    assert combined.should_keep is True


def test_should_keep_false_when_one_fails():
    combined = _combined(validation_ok=True, test_ok=False)
    assert combined.should_keep is False


def test_should_retry_true_before_max_retries_when_failed():
    combined = _combined(validation_ok=False, test_ok=True, retry_count=1, max_retries=3)
    assert combined.should_retry is True


def test_should_retry_false_at_max_retries_when_failed():
    combined = _combined(validation_ok=False, test_ok=True, retry_count=3, max_retries=3)
    assert combined.should_retry is False


def test_select_action_routes_keep_when_should_keep():
    combined = _combined(validation_ok=True, test_ok=True)
    assert select_action(combined, ["keep", "remove"]) == ["keep"]


def test_select_action_routes_remove_when_not_keep():
    combined = _combined(validation_ok=True, test_ok=False)
    assert select_action(combined, ["keep", "remove"]) == ["remove"]


def test_select_skip_answer_action_completes_when_keep():
    combined = _combined(validation_ok=True, test_ok=True)
    assert select_skip_answer_action(combined, ["check_loop", "complete"]) == ["complete"]


def test_select_skip_answer_action_loops_when_failed():
    combined = _combined(validation_ok=False, test_ok=True)
    assert select_skip_answer_action(combined, ["check_loop", "complete"]) == ["check_loop"]


def test_select_loop_action_retries_when_should_retry():
    combined = _combined(validation_ok=False, test_ok=False, retry_count=0, max_retries=3)
    assert select_loop_action(combined, ["retry", "complete"]) == ["retry"]


def test_select_loop_action_completes_when_no_retry():
    combined = _combined(validation_ok=False, test_ok=False, retry_count=3, max_retries=3)
    assert select_loop_action(combined, ["retry", "complete"]) == ["complete"]
