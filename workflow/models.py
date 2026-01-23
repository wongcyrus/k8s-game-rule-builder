"""Data models for K8s task generation workflow."""
from dataclasses import dataclass
from pydantic import BaseModel, Field


class ValidationResult(BaseModel):
    """Structured validation result from validator agent."""
    is_valid: bool = Field(description="Whether the task passed validation")
    reason: str = Field(description="Reason for validation result")
    task_id: str = Field(description="Task ID being validated")
    task_directory: str = Field(description="Task directory path")


class TestResult(BaseModel):
    """Structured test result from pytest agent."""
    is_valid: bool = Field(description="Whether tests passed")
    reason: str = Field(description="Test execution summary")
    task_id: str = Field(description="Task ID being tested")
    task_directory: str = Field(description="Task directory path")
    raw_output: str = Field(default="", description="Raw pytest output for debugging")


@dataclass
class CombinedValidationResult:
    """Combined validation and test results for decision making."""
    validation: ValidationResult
    test: TestResult
    retry_count: int = 0
    max_retries: int = 3
    target_topic: str = ""
    concept_description: str = ""
    difficulty: str = ""
    objective: str = ""
    
    @property
    def should_keep(self) -> bool:
        """Decision: keep task only if both validation and tests pass."""
        return self.validation.is_valid and self.test.is_valid
    
    @property
    def should_retry(self) -> bool:
        """Decision: retry if task failed and haven't exceeded max retries."""
        return not self.should_keep and self.retry_count < self.max_retries


@dataclass
class TaskInfo:
    """Task information passed through workflow."""
    task_id: str
    task_directory: str


@dataclass
class TaskWithValidation:
    """Task info with validation result."""
    task_id: str
    task_directory: str
    validation: ValidationResult


@dataclass
class InitialWorkflowState:
    """Initial state for workflow execution."""
    prompt: str
    target_topic: str
    task_id: str
    concept_description: str
    difficulty: str
    objective: str
    retry_count: int = 0
    max_retries: int = 3
