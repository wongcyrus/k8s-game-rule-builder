"""Selection functions for workflow routing."""
from workflow.models import CombinedValidationResult


def select_action(combined: CombinedValidationResult, target_ids: list[str]) -> list[str]:
    """Select next action based on validation and test results."""
    keep_task_id, remove_task_id = target_ids
    return [keep_task_id] if combined.should_keep else [remove_task_id]


def select_skip_answer_action(combined: CombinedValidationResult, target_ids: list[str]) -> list[str]:
    """Select next action after skip answer test - either retry or complete."""
    check_loop_id, complete_workflow_id = target_ids
    # If validation passed (should_keep is True), complete workflow
    # If validation failed, go to check_loop to decide retry or final failure
    return [complete_workflow_id] if combined.should_keep else [check_loop_id]


def select_loop_action(combined: CombinedValidationResult, target_ids: list[str]) -> list[str]:
    """Select whether to retry generation or complete workflow."""
    retry_generation_id, complete_workflow_id = target_ids
    return [retry_generation_id] if combined.should_retry else [complete_workflow_id]
