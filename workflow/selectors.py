"""Selection functions for workflow routing."""
from workflow.models import CombinedValidationResult


def select_action(combined: CombinedValidationResult, target_ids: list[str]) -> list[str]:
    """Select next action based on validation and test results."""
    keep_task_id, remove_task_id = target_ids
    return [keep_task_id] if combined.should_keep else [remove_task_id]


def select_loop_action(combined: CombinedValidationResult, target_ids: list[str]) -> list[str]:
    """Select whether to retry generation or complete workflow."""
    retry_generation_id, complete_workflow_id = target_ids
    return [retry_generation_id] if combined.should_retry else [complete_workflow_id]
