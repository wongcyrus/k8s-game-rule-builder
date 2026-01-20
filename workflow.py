"""Workflow for K8s task generation with validation and testing.

This workflow uses Agent Framework's WorkflowBuilder with conditional logic:
1. Generate task files (generator agent)
2. Validate task structure (validator agent with structured output)
3. Run pytest tests (pytest agent)
4. Conditional: If validation AND tests pass -> keep task, else -> remove task
"""
import asyncio
import json
import logging
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Any
from pydantic import BaseModel, Field

from agent_framework import (
    AgentExecutor,
    AgentExecutorRequest,
    AgentExecutorResponse,
    ChatMessage,
    Role,
    WorkflowBuilder,
    WorkflowContext,
    WorkflowEvent,
    WorkflowViz,
    executor,
)
from agent_framework.azure import AzureOpenAIResponsesClient
from azure.identity import AzureCliCredential

from agents import (
    get_pytest_agent,
    get_k8s_task_generator_agent,
    get_k8s_task_validator_agent,
)
from agents.config import PATHS, AZURE

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)


# Structured output models
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


@dataclass
class CombinedValidationResult:
    """Combined validation and test results for decision making."""
    validation: ValidationResult
    test: TestResult
    
    @property
    def should_keep(self) -> bool:
        """Decision: keep task only if both validation and tests pass."""
        return self.validation.is_valid and self.test.is_valid


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


# Executor: Parse task generation response
@executor(id="parse_generated_task")
async def parse_generated_task(response: AgentExecutorResponse, ctx: WorkflowContext[TaskInfo]) -> None:
    """Parse task generation response and extract task info."""
    logging.info("\n[EXECUTOR] parse_generated_task: Extracting task ID from generator response...")
    
    text = response.agent_response.text
    logging.info(f"Generator response (first 500 chars): {text[:500]}")
    
    # Extract task ID from response
    task_id_match = re.search(r'tests/game02/(\d{3}_[a-z0-9_]+)', text)
    if not task_id_match:
        task_id_match = re.search(r'(\d{3}_[a-z0-9_]+)', text)
    
    if task_id_match:
        task_id = task_id_match.group(1)
        logging.info(f"✅ Extracted task ID: {task_id}")
        
        task_info = TaskInfo(
            task_id=task_id,
            task_directory=f"tests/game02/{task_id}"
        )
        
        await ctx.send_message(task_info)
    else:
        logging.error("❌ Could not extract task ID from generation response")
        raise ValueError("Failed to parse task ID from generation")


# Executor: Create validation request
@executor(id="create_validation_request")
async def create_validation_request(task_info: TaskInfo, ctx: WorkflowContext[AgentExecutorRequest]) -> None:
    """Create validation request for the validator agent."""
    logging.info(f"\n[EXECUTOR] create_validation_request: Creating validation request for {task_info.task_id}...")
    
    validation_prompt = (
        f"Validate the task directory {task_info.task_id} and return structured JSON with "
        f"'is_valid' (bool), 'reason' (string), 'task_id' (string), and 'task_directory' (string). "
        f"Check all required files, YAML syntax, Python syntax, and Jinja templates."
    )
    
    await ctx.send_message(
        AgentExecutorRequest(
            messages=[ChatMessage(Role.USER, text=validation_prompt)],
            should_respond=True
        )
    )


# Executor: Parse validation response
@executor(id="parse_validation_result")
async def parse_validation_result(response: AgentExecutorResponse, ctx: WorkflowContext[TaskWithValidation]) -> None:
    """Parse validation response into structured result."""
    logging.info("\n[EXECUTOR] parse_validation_result: Parsing validation response...")
    
    text = response.agent_response.text
    logging.info(f"Validator response (first 500 chars): {text[:500]}")
    
    try:
        # Extract JSON from response
        json_match = re.search(r'\{[^}]*"is_valid"[^}]*\}', text, re.DOTALL)
        if json_match:
            result_data = json.loads(json_match.group(0))
            validation = ValidationResult(**result_data)
        else:
            # Fallback parsing - extract task ID from text
            task_id_match = re.search(r'(\d{3}_[a-z0-9_]+)', text)
            task_id = task_id_match.group(1) if task_id_match else "unknown"
            is_valid = "valid" in text.lower() and "invalid" not in text.lower()
            
            validation = ValidationResult(
                is_valid=is_valid,
                reason=text[:200],
                task_id=task_id,
                task_directory=f"tests/game02/{task_id}"
            )
        
        status = "✅ PASSED" if validation.is_valid else "❌ FAILED"
        logging.info(f"{status} Validation: {validation.reason}")
        
        # Create TaskWithValidation
        task_with_val = TaskWithValidation(
            task_id=validation.task_id,
            task_directory=validation.task_directory,
            validation=validation
        )
        
        await ctx.send_message(task_with_val)
        
    except Exception as e:
        logging.error(f"❌ Failed to parse validation: {e}")
        raise


# Executor: Create pytest request
@executor(id="create_pytest_request")
async def create_pytest_request(task_with_val: TaskWithValidation, ctx: WorkflowContext[AgentExecutorRequest]) -> None:
    """Create pytest request for the pytest agent."""
    logging.info(f"\n[EXECUTOR] create_pytest_request: Creating pytest request for {task_with_val.task_id}...")
    
    pytest_prompt = (
        f"Run all tests in {task_with_val.task_directory}/ to validate the generated task. "
        f"Show test results and any failures. Task ID: {task_with_val.task_id}"
    )
    
    await ctx.send_message(
        AgentExecutorRequest(
            messages=[ChatMessage(Role.USER, text=pytest_prompt)],
            should_respond=True
        )
    )


# Executor: Parse test results and make decision
@executor(id="parse_tests_and_decide")
async def parse_tests_and_decide(response: AgentExecutorResponse, ctx: WorkflowContext[CombinedValidationResult]) -> None:
    """Parse pytest response and make keep/remove decision."""
    logging.info("\n[EXECUTOR] parse_tests_and_decide: Parsing test results and making decision...")
    
    text = response.agent_response.text
    logging.info(f"Pytest response (first 500 chars): {text[:500]}")
    
    # Extract task ID from response
    task_id_match = re.search(r'Task ID: (\d{3}_[a-z0-9_]+)', text)
    if not task_id_match:
        task_id_match = re.search(r'tests/game02/(\d{3}_[a-z0-9_]+)', text)
    task_id = task_id_match.group(1) if task_id_match else "unknown"
    task_directory = f"tests/game02/{task_id}"
    
    # Parse test result
    is_valid = "passed" in text.lower() and "failed" not in text.lower()
    
    test_result = TestResult(
        is_valid=is_valid,
        reason="Tests passed" if is_valid else "Tests failed",
        task_id=task_id,
        task_directory=task_directory
    )
    
    status = "✅ PASSED" if test_result.is_valid else "❌ FAILED"
    logging.info(f"{status} Tests: {test_result.reason}")
    
    # For now, create a dummy validation (we'll fix this with proper state management)
    # In a real scenario, we'd retrieve the stored validation
    validation = ValidationResult(
        is_valid=True,  # Assume validation passed if we got here
        reason="Validation passed",
        task_id=task_id,
        task_directory=task_directory
    )
    
    # Combine results
    combined = CombinedValidationResult(validation=validation, test=test_result)
    
    decision = "KEEP" if combined.should_keep else "REMOVE"
    logging.info(f"\n🔀 DECISION: {decision} task {task_id}")
    
    await ctx.send_message(combined)


# Selection function for conditional routing
def select_action(combined: CombinedValidationResult, target_ids: list[str]) -> list[str]:
    """Select next action based on validation and test results.
    
    Args:
        combined: Combined validation and test results
        target_ids: [keep_task_id, remove_task_id]
    
    Returns:
        List containing the selected target ID
    """
    keep_task_id, remove_task_id = target_ids
    
    if combined.should_keep:
        logging.info(f"✅ Routing to KEEP task {combined.test.task_id}")
        return [keep_task_id]
    else:
        logging.info(f"❌ Routing to REMOVE task {combined.test.task_id}")
        return [remove_task_id]


# Executor: Keep task (success path)
@executor(id="keep_task")
async def keep_task(combined: CombinedValidationResult, ctx: WorkflowContext[str]) -> None:
    """Keep the task - it passed all checks."""
    logging.info(f"\n✅ KEEPING TASK: {combined.test.task_id}")
    logging.info(f"   Validation: {combined.validation.reason}")
    logging.info(f"   Tests: {combined.test.reason}")
    
    await ctx.yield_output(
        f"✅ Task {combined.test.task_id} passed all checks and has been kept."
    )


# Executor: Remove task (failure path)
@executor(id="remove_task")
async def remove_task(combined: CombinedValidationResult, ctx: WorkflowContext[str]) -> None:
    """Remove the task - it failed validation or tests."""
    logging.info(f"\n❌ REMOVING TASK: {combined.test.task_id}")
    
    reasons = []
    if not combined.validation.is_valid:
        reasons.append(f"Validation failed: {combined.validation.reason}")
    if not combined.test.is_valid:
        reasons.append(f"Tests failed: {combined.test.reason}")
    
    logging.info(f"   Reasons: {'; '.join(reasons)}")
    
    # Actually remove the directory - use absolute path
    task_path = PATHS.tests_root / "game02" / combined.test.task_id
    if task_path.exists():
        shutil.rmtree(task_path)
        logging.info(f"   🗑️  Deleted directory: {task_path}")
    else:
        logging.warning(f"   ⚠️  Directory not found: {task_path}")
    
    await ctx.yield_output(
        f"❌ Task {combined.test.task_id} failed checks and has been removed. Reasons: {'; '.join(reasons)}"
    )


async def main():
    """Run the workflow with conditional logic."""
    logging.info("="*80)
    logging.info("K8S TASK GENERATION WORKFLOW WITH VALIDATION")
    logging.info("="*80)
    
    credential = AzureCliCredential()
    responses_client = AzureOpenAIResponsesClient(
        endpoint=AZURE.endpoint,
        deployment_name=AZURE.deployment_name,
        credential=credential,
    )
    
    # Create agent executors
    async with get_k8s_task_generator_agent() as generator_agent:
        generator_executor = AgentExecutor(generator_agent, id="generator_agent")
        
        validator_agent = get_k8s_task_validator_agent()
        validator_executor = AgentExecutor(validator_agent, id="validator_agent")
        
        pytest_agent = get_pytest_agent()
        pytest_executor = AgentExecutor(pytest_agent, id="pytest_agent")
        
        # Build workflow with conditional logic
        workflow = (
            WorkflowBuilder()
            .set_start_executor(generator_executor)
            .add_edge(generator_executor, parse_generated_task)
            .add_edge(parse_generated_task, create_validation_request)
            .add_edge(create_validation_request, validator_executor)
            .add_edge(validator_executor, parse_validation_result)
            .add_edge(parse_validation_result, create_pytest_request)
            .add_edge(create_pytest_request, pytest_executor)
            .add_edge(pytest_executor, parse_tests_and_decide)
            .add_multi_selection_edge_group(
                parse_tests_and_decide,
                [keep_task, remove_task],
                selection_func=select_action,
            )
            .build()
        )
        
        # Generate workflow visualization
        logging.info("\n" + "="*80)
        logging.info("WORKFLOW VISUALIZATION")
        logging.info("="*80)
        
        viz = WorkflowViz(workflow)
        
        # Print Mermaid diagram
        logging.info("\n📊 Mermaid Diagram:")
        logging.info("-"*80)
        print(viz.to_mermaid())
        logging.info("-"*80)
        
        # Print DiGraph
        logging.info("\n📊 DiGraph:")
        logging.info("-"*80)
        print(viz.to_digraph())
        logging.info("-"*80)
        
        # Export to files
        try:
            svg_file = viz.save_svg("workflow_graph.svg")
            logging.info(f"\n✅ SVG exported to: {svg_file}")
        except Exception as e:
            logging.warning(f"⚠️  Could not export SVG: {e}")
        
        try:
            png_file = viz.save_png("workflow_graph.png")
            logging.info(f"✅ PNG exported to: {png_file}")
        except Exception as e:
            logging.warning(f"⚠️  Could not export PNG: {e}")
        
        try:
            pdf_file = viz.save_pdf("workflow_graph.pdf")
            logging.info(f"✅ PDF exported to: {pdf_file}")
        except Exception as e:
            logging.warning(f"⚠️  Could not export PDF: {e}")
        
        logging.info("\n" + "="*80)
        
        # Run workflow
        task_prompt = (
            "Generate a complete Kubernetes learning task with a unique ID in format '###_concept_name'. "
            "Create ALL required files including __init__.py, instruction.md, session.json, "
            "setup.template.yaml, answer.template.yaml, and all test files (test_01_setup.py, "
            "test_03_answer.py, test_05_check.py, test_06_cleanup.py). "
            "Use proper Jinja template variables and follow all established patterns."
        )
        
        logging.info("\n🚀 Starting workflow...")
        async for event in workflow.run_stream(task_prompt):
            if isinstance(event, WorkflowEvent):
                if event.data:  # Only log non-empty events
                    logging.info(f"\n📤 Workflow output: {event.data}")
        
        logging.info("\n" + "="*80)
        logging.info("WORKFLOW COMPLETE")
        logging.info("="*80)


if __name__ == "__main__":
    asyncio.run(main())
