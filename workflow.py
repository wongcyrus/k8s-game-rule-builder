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
from typing_extensions import Never
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
    MCPStdioTool,
)
from agent_framework.azure import AzureOpenAIResponsesClient
from azure.identity import AzureCliCredential

from agents import (
    get_pytest_agent,
)
from agents.k8s_task_generator_agent import create_generator_agent_with_mcp
from agents.k8s_task_idea_agent import create_idea_agent_with_mcp
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
    raw_output: str = Field(default="", description="Raw pytest output for debugging")


@dataclass
class CombinedValidationResult:
    """Combined validation and test results for decision making."""
    validation: ValidationResult
    test: TestResult
    retry_count: int = 0  # Track number of retry attempts
    max_retries: int = 3  # Maximum retry attempts
    # Store task metadata for retry loop (so it doesn't depend on shared state)
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


# Dataclass for initial workflow state
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


# Executor: Initialize retry (entry point for loops)
@executor(id="initialize_retry")
async def initialize_retry(message: str | AgentExecutorRequest | InitialWorkflowState, ctx: WorkflowContext[AgentExecutorRequest]) -> None:
    """Initialize or re-initialize shared state before generation.
    
    This is the entry point for both first run and retries.
    On first run, receives InitialWorkflowState with all initial values.
    On retry, receives AgentExecutorRequest and shared state is already set.
    
    Args:
        message: InitialWorkflowState (first run), AgentExecutorRequest (retry), or string (fallback)
    """
    logging.info("\n[STEP] Initializing/Re-initializing workflow state...")
    
    # Handle first run with InitialWorkflowState
    if isinstance(message, InitialWorkflowState):
        logging.info("First run - initializing shared state from InitialWorkflowState")
        await ctx.set_shared_state("task_id", message.task_id)
        await ctx.set_shared_state("target_topic", message.target_topic)
        await ctx.set_shared_state("concept_description", message.concept_description)
        await ctx.set_shared_state("difficulty", message.difficulty)
        await ctx.set_shared_state("objective", message.objective)
        await ctx.set_shared_state("retry_count", message.retry_count)
        await ctx.set_shared_state("max_retries", message.max_retries)
        logging.info(f"Set state: task_id={message.task_id}, topic={message.target_topic}")
        
        # Create request from prompt
        request = AgentExecutorRequest(
            messages=[ChatMessage(Role.USER, text=message.prompt)],
            should_respond=True
        )
    else:
        # Retry case - shared state should already exist
        try:
            task_id = await ctx.get_shared_state("task_id")
            target_topic = await ctx.get_shared_state("target_topic")
            logging.info(f"Retry: State found: task_id={task_id}, topic={target_topic}")
        except KeyError as e:
            logging.error(f"Missing required shared state: {e}")
            raise
        
        # Convert string to AgentExecutorRequest if needed
        if isinstance(message, str):
            request = AgentExecutorRequest(
                messages=[ChatMessage(Role.USER, text=message)],
                should_respond=True
            )
        else:
            request = message
    
    # Forward the request to generator
    await ctx.send_message(request)


# Executor: Parse task generation response
@executor(id="parse_generated_task")
async def parse_generated_task(response: AgentExecutorResponse, ctx: WorkflowContext[TaskInfo]) -> None:
    """Parse task generation response and extract task info.
    
    Waits for essential files to be created before proceeding to validation.
    """
    logging.info("\n[STEP] Parsing generated task...")
    
    # Initialize shared state if not already set (for retry loop)
    try:
        await ctx.get_shared_state("retry_count")
    except KeyError:
        await ctx.set_shared_state("retry_count", 0)
    
    try:
        await ctx.get_shared_state("max_retries")
    except KeyError:
        await ctx.set_shared_state("max_retries", 3)
    
    # Try to get task_id from shared state first (set by main() or parse_user_input)
    try:
        task_id = await ctx.get_shared_state("task_id")
    except KeyError:
        # Fallback: Extract task ID from response text (for first run)
        text = response.agent_response.text
        task_id_match = re.search(rf'{PATHS.game_name}/(\d{{3}}_[a-z0-9_]+)', text)
        if not task_id_match:
            task_id_match = re.search(rf'tests/{PATHS.game_name}/(\d{{3}}_[a-z0-9_]+)', text)
        if not task_id_match:
            task_id_match = re.search(r'(\d{3}_[a-z0-9_]+)', text)
        
        if task_id_match:
            task_id = task_id_match.group(1)
        else:
            raise ValueError("Failed to parse task ID from generation and not found in shared state")
    
    task_info = TaskInfo(
        task_id=task_id,
        task_directory=f"tests/{PATHS.game_name}/{task_id}"
    )
    
    await ctx.send_message(task_info)


# Executor: Run validation directly (no LLM needed)
@executor(id="run_validation")
async def run_validation(task_info: TaskInfo, ctx: WorkflowContext[TaskWithValidation]) -> None:
    """Run validation directly without LLM - it's just file checks."""
    logging.info(f"\n[STEP] Validating task: {task_info.task_id}")
    from agents.k8s_task_validator import validate_task_directory
    
    result = validate_task_directory(task_info.task_id)
    
    # Extract detailed failure reasons
    failure_reasons = []
    if not result["is_valid"] and result.get("details"):
        for detail in result["details"]:
            if isinstance(detail, dict) and not detail.get("is_valid", True):
                reason = detail.get("reason", "Unknown error")
                if reason not in ["Validation completed", "Directory listing"]:
                    failure_reasons.append(reason)
    
    # Create informative reason
    if failure_reasons:
        detailed_reason = "; ".join(failure_reasons[:3])
        if len(failure_reasons) > 3:
            detailed_reason += f" (and {len(failure_reasons) - 3} more errors)"
    else:
        if not result["is_valid"]:
            detailed_reason = "Validation failed - check file structure and syntax"
        else:
            detailed_reason = "All validation checks passed"
    
    validation = ValidationResult(
        is_valid=result["is_valid"],
        reason=detailed_reason,
        task_id=task_info.task_id,
        task_directory=task_info.task_directory
    )
    
    await ctx.set_shared_state(f"validation_{validation.task_id}", validation)
    
    task_with_val = TaskWithValidation(
        task_id=validation.task_id,
        task_directory=validation.task_directory,
        validation=validation
    )
    
    await ctx.send_message(task_with_val)


# Executor: Run pytest directly (no LLM needed)
@executor(id="run_pytest")
async def run_pytest(task_with_val: TaskWithValidation, ctx: WorkflowContext[TestResult]) -> None:
    """Run pytest directly without LLM - it's just command execution."""
    logging.info(f"\n[STEP] Running tests for: {task_with_val.task_id}")
    logging.info("="*80)
    logging.info("🔍 NEW CODE VERSION - CHECKING RAW OUTPUT CAPTURE")
    logging.info("="*80)
    
    from agents.pytest_runner import run_pytest_command
    
    pytest_command = f"pytest --import-mode=importlib --rootdir=. {task_with_val.task_directory}/"
    result = run_pytest_command(pytest_command)
    
    logging.info(f"🔍 DEBUG: pytest result keys: {result.keys()}")
    logging.info(f"🔍 DEBUG: pytest result['details'] exists: {'details' in result}")
    if 'details' in result:
        logging.info(f"🔍 DEBUG: pytest result['details'] length: {len(result['details'])}")
        if len(result['details']) > 0:
            logging.info(f"🔍 DEBUG: pytest result['details'][0] length: {len(result['details'][0])} chars")
    
    # Extract raw output from details
    raw_output = ""
    if result.get("details") and len(result["details"]) > 0:
        raw_output = result["details"][0]
        logging.info(f"✅ ✅ ✅ Captured raw output length: {len(raw_output)} chars")
        
        # WORKAROUND: Save raw output to shared state since Pydantic might be dropping it
        await ctx.set_shared_state(f"raw_output_{task_with_val.task_id}", raw_output)
        logging.info(f"✅ ✅ ✅ Saved raw output to shared state for {task_with_val.task_id}")
    else:
        logging.error(f"❌ ❌ ❌ No raw output captured. Result keys: {result.keys()}")
        logging.error(f"❌ ❌ ❌ Details: {result.get('details')}")

    test_result = TestResult(
        is_valid=result["is_valid"],
        reason=result["reason"],
        task_id=task_with_val.task_id,
        task_directory=task_with_val.task_directory,
        raw_output=raw_output
    )
    
    logging.info(f"🔍 DEBUG: Created TestResult with raw_output length: {len(test_result.raw_output)} chars")
    
    await ctx.send_message(test_result)


# Executor: Make decision based on test results
@executor(id="make_decision")
async def make_decision(test_result: TestResult, ctx: WorkflowContext[CombinedValidationResult]) -> None:
    """Make keep/remove decision based on validation and test results."""
    logging.info("\n[STEP] Making decision...")
    
    # DEBUG: Check test_result
    logging.info(f"DEBUG make_decision: test_result type: {type(test_result)}")
    logging.info(f"DEBUG make_decision: test_result fields: {test_result.model_dump() if hasattr(test_result, 'model_dump') else vars(test_result)}")
    logging.info(f"DEBUG make_decision: raw_output length: {len(test_result.raw_output)} chars")
    
    # Retrieve validation result from shared state
    try:
        validation = await ctx.get_shared_state(f"validation_{test_result.task_id}")
    except KeyError:
        # Fallback: assume validation passed if we got to testing phase
        validation = ValidationResult(
            is_valid=True,
            reason="Validation passed (assumed)",
            task_id=test_result.task_id,
            task_directory=test_result.task_directory
        )
    
    # Get retry count
    try:
        retry_count = await ctx.get_shared_state("retry_count")
    except KeyError:
        retry_count = 0
    
    # Get max retries configuration
    try:
        max_retries = await ctx.get_shared_state("max_retries")
    except KeyError:
        max_retries = 3
    
    # Get task metadata from shared state
    target_topic = ""
    concept_description = ""
    difficulty = ""
    objective = ""
    
    try:
        target_topic = await ctx.get_shared_state("target_topic")
        logging.info(f"✓ Got target_topic: {target_topic}")
    except KeyError:
        logging.warning("✗ target_topic not in shared state")
    
    try:
        concept_description = await ctx.get_shared_state("concept_description")
        logging.info(f"✓ Got concept_description: {concept_description[:50]}...")
    except KeyError:
        logging.warning("✗ concept_description not in shared state")
    
    try:
        difficulty = await ctx.get_shared_state("difficulty")
        logging.info(f"✓ Got difficulty: {difficulty}")
    except KeyError:
        logging.warning("✗ difficulty not in shared state")
    
    try:
        objective = await ctx.get_shared_state("objective")
        logging.info(f"✓ Got objective: {objective[:50]}...")
    except KeyError:
        logging.warning("✗ objective not in shared state")
    
    combined = CombinedValidationResult(
        validation=validation,
        test=test_result,
        retry_count=retry_count,
        max_retries=max_retries,
        target_topic=target_topic,
        concept_description=concept_description,
        difficulty=difficulty,
        objective=objective,
    )
    
    await ctx.send_message(combined)


# Selection function for conditional routing
def select_action(combined: CombinedValidationResult, target_ids: list[str]) -> list[str]:
    """Select next action based on validation and test results."""
    keep_task_id, remove_task_id = target_ids
    return [keep_task_id] if combined.should_keep else [remove_task_id]


# Selection function for loop routing
def select_loop_action(combined: CombinedValidationResult, target_ids: list[str]) -> list[str]:
    """Select whether to retry generation or complete workflow."""
    retry_generation_id, complete_workflow_id = target_ids
    return [retry_generation_id] if combined.should_retry else [complete_workflow_id]


# Executor: Keep task (success path)
@executor(id="keep_task")
async def keep_task(combined: CombinedValidationResult, ctx: WorkflowContext[CombinedValidationResult]) -> None:
    """Keep the task - it passed all checks."""
    logging.info(f"\n[STEP] ✅ Keeping task: {combined.test.task_id}")
    await ctx.yield_output(
        f"✅ Task {combined.test.task_id} passed all checks and has been kept."
    )
    await ctx.send_message(combined)


# Executor: Remove task (failure path)
@executor(id="remove_task")
async def remove_task(combined: CombinedValidationResult, ctx: WorkflowContext[CombinedValidationResult]) -> None:
    """Move the task to unsuccessful folder - it failed validation or tests."""
    logging.info(f"\n[STEP] ❌ Moving task to unsuccessful folder: {combined.test.task_id}")
    reasons = []
    if not combined.validation.is_valid:
        reasons.append(f"Validation failed: {combined.validation.reason}")
    if not combined.test.is_valid:
        reasons.append(f"Tests failed: {combined.test.reason}")
    
    # Prepare unsuccessful directory
    unsuccessful_dir = PATHS.unsuccessful_game_root
    unsuccessful_dir.mkdir(parents=True, exist_ok=True)
    
    # Source and destination paths
    task_path = PATHS.game_root / combined.test.task_id
    unsuccessful_task_path = unsuccessful_dir / combined.test.task_id
    
    # If task exists, move it to unsuccessful folder
    if task_path.exists():
        # If destination already exists, remove it first (or add timestamp)
        if unsuccessful_task_path.exists():
            import time
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            unsuccessful_task_path = unsuccessful_dir / f"{combined.test.task_id}_{timestamp}"
        
        shutil.move(str(task_path), str(unsuccessful_task_path))
        logging.info(f"Moved task to: {unsuccessful_task_path}")
        
        # Save failure report
        failure_report_path = unsuccessful_task_path / "FAILURE_REPORT.txt"
        
        with open(failure_report_path, 'w') as f:
            f.write(f"Task ID: {combined.test.task_id}\n")
            f.write(f"Retry Attempt: {combined.retry_count}\n")
            f.write(f"Failure Reasons:\n")
            for reason in reasons:
                f.write(f"  - {reason}\n")
            f.write(f"\nValidation Details:\n")
            f.write(f"  Valid: {combined.validation.is_valid}\n")
            f.write(f"  Reason: {combined.validation.reason}\n")
            f.write(f"\nTest Details:\n")
            f.write(f"  Valid: {combined.test.is_valid}\n")
            f.write(f"  Reason: {combined.test.reason}\n")
            f.write(f"\n{'='*80}\n")
            f.write(f"Full test output saved in: test_result.txt\n")
            f.write(f"{'='*80}\n")
        
        logging.info(f"Saved failure report to: {failure_report_path}")
    
    # Increment retry count
    retry_count = combined.retry_count + 1
    await ctx.set_shared_state("retry_count", retry_count)
    
    await ctx.yield_output(
        f"❌ Task {combined.test.task_id} failed checks and has been moved to unsuccessful folder. Reasons: {'; '.join(reasons)}"
    )
    
    # Create updated combined result with new retry count
    # Preserve task metadata for retry loop
    updated_combined = CombinedValidationResult(
        validation=combined.validation,
        test=combined.test,
        retry_count=retry_count,
        max_retries=combined.max_retries,
        target_topic=combined.target_topic,
        concept_description=combined.concept_description,
        difficulty=combined.difficulty,
        objective=combined.objective,
    )
    
    await ctx.send_message(updated_combined)


# Executor: Check if should loop back
@executor(id="check_loop")
async def check_loop(combined: CombinedValidationResult, ctx: WorkflowContext[CombinedValidationResult]) -> None:
    """Check if we should retry or complete the workflow."""
    logging.info(f"\n[STEP] Checking retry status: {combined.retry_count}/{combined.max_retries}")
    await ctx.send_message(combined)


# Executor: Retry generation (loop back)
@executor(id="retry_generation")
async def retry_generation(combined: CombinedValidationResult, ctx: WorkflowContext[AgentExecutorRequest]) -> None:
    """Retry task generation after a failure.
    
    Uses task metadata stored in CombinedValidationResult (passed through the workflow).
    Re-sets shared state before looping back to ensure it persists.
    """
    logging.info(f"\n[STEP] 🔄 Retrying generation: attempt {combined.retry_count + 1}/{combined.max_retries}")
    
    # Extract all data from combined result (no dependency on shared state)
    task_id = combined.test.task_id
    target_topic = combined.target_topic
    concept_description = combined.concept_description
    difficulty = combined.difficulty
    objective = combined.objective
    
    # Validate we have the required data
    if not target_topic or not concept_description:
        raise ValueError(
            f"Missing task metadata in CombinedValidationResult. "
            f"target_topic='{target_topic}', concept_description='{concept_description}'. "
            f"This indicates the metadata was not properly passed through the workflow."
        )
    
    # Re-set shared state for the next loop iteration
    # This ensures the metadata is available when we loop back
    await ctx.set_shared_state("task_id", task_id)
    await ctx.set_shared_state("target_topic", target_topic)
    await ctx.set_shared_state("concept_description", concept_description)
    await ctx.set_shared_state("difficulty", difficulty)
    await ctx.set_shared_state("objective", objective)
    
    # Get failure reasons to help agent fix issues
    failure_reasons = []
    if not combined.validation.is_valid:
        failure_reasons.append(f"Validation: {combined.validation.reason}")
    if not combined.test.is_valid:
        failure_reasons.append(f"Tests: {combined.test.reason}")
    
    generation_prompt = (
        f"Generate a complete Kubernetes learning task with ID '{task_id}' about '{target_topic}'. "
        f"This is retry attempt {combined.retry_count + 1} of {combined.max_retries}. "
        f"\n\n⚠️  PREVIOUS ATTEMPT FAILED:"
        f"\n{chr(10).join([f'  - {reason}' for reason in failure_reasons])}"
        f"\n\nIMPORTANT: You MUST use the exact task ID '{task_id}' - do not generate a new ID."
        f"\n\n✅ Create directory: {PATHS.game_name}/{task_id}/"
        f"\n\nTask Details:"
        f"\n- Concept: {target_topic}"
        f"\n- Description: {concept_description}"
        f"\n- Difficulty: {difficulty}"
        f"\n- Objective: {objective}"
        f"\n\nCreate ALL required files including __init__.py, instruction.md, session.json, "
        f"setup.template.yaml, answer.template.yaml, and all test files (test_01_setup.py, "
        f"test_02_ready.py, test_03_answer.py, test_05_check.py, test_06_cleanup.py). "
        f"Include test_04_challenge.py only if the task requires pre-validation actions like load generation. "
        f"test_02_ready.py must test that resources from setup.template.yaml are ready. "
        f"Use proper Jinja template variables and follow all established patterns. "
        f"Make sure all files are syntactically correct and tests will pass."
    )
    
    await ctx.send_message(
        AgentExecutorRequest(
            messages=[ChatMessage(Role.USER, text=generation_prompt)],
            should_respond=True
        )
    )


# Executor: Complete workflow (end loop)
@executor(id="complete_workflow")
async def complete_workflow(combined: CombinedValidationResult, ctx: WorkflowContext[Never, str]) -> None:
    """Complete the workflow - either success or max retries reached."""
    logging.info("\n[STEP] 🏁 Completing workflow...")
    if combined.should_keep:
        await ctx.yield_output(f"🏁 Workflow complete: Task {combined.test.task_id} successfully generated")
    else:
        await ctx.yield_output(f"🏁 Workflow complete: Failed to generate valid task after {combined.retry_count} retries")


async def main():
    """Run the workflow with conditional logic."""
    # Force reload to pick up code changes
    import importlib
    import sys
    if 'agents.pytest_runner' in sys.modules:
        importlib.reload(sys.modules['agents.pytest_runner'])
    
    logging.info("="*80)
    logging.info("K8S TASK GENERATION WORKFLOW")
    logging.info("="*80)
    
    credential = AzureCliCredential()
    responses_client = AzureOpenAIResponsesClient(
        endpoint=AZURE.endpoint,
        deployment_name=AZURE.deployment_name,
        credential=credential,
    )
    
    # Create MCP tools
    docs_mcp_tool = MCPStdioTool(
        name="filesystem_docs",
        command="npx",
        args=["-y", "@modelcontextprotocol/server-filesystem", str(PATHS.k8s_docs_root)],
        load_prompts=False
    )
    
    tests_mcp_tool = MCPStdioTool(
        name="filesystem_tests",
        command="npx",
        args=["-y", "@modelcontextprotocol/server-filesystem", str(PATHS.tests_root.parent)],
        load_prompts=False
    )
    
    async with docs_mcp_tool, tests_mcp_tool:
        # Create agents
        idea_agent, idea_memory = await create_idea_agent_with_mcp(docs_mcp_tool)
        generator_agent = await create_generator_agent_with_mcp(tests_mcp_tool)
        generator_executor = AgentExecutor(generator_agent, id="generator_agent")
        
        # Build workflow
        workflow = (
            WorkflowBuilder()
            .set_start_executor(initialize_retry)  # Start with initialization
            .add_edge(initialize_retry, generator_executor)
            .add_edge(generator_executor, parse_generated_task)
            .add_edge(parse_generated_task, run_validation)
            .add_edge(run_validation, run_pytest)
            .add_edge(run_pytest, make_decision)
            .add_multi_selection_edge_group(
                make_decision,
                [keep_task, remove_task],
                selection_func=select_action,
            )
            .add_edge(keep_task, check_loop)
            .add_edge(remove_task, check_loop)
            .add_multi_selection_edge_group(
                check_loop,
                [retry_generation, complete_workflow],
                selection_func=select_loop_action,
            )
            .add_edge(retry_generation, initialize_retry)  # Loop back to initialization
            .build()
        )
        
        # Generate workflow visualization
        viz = WorkflowViz(workflow)
        print(viz.to_mermaid())
        print(viz.to_digraph())
        
        try:
            viz.save_png("workflow_graph.png")
        except Exception:
            pass
        
        # Step 1: Generate unique task idea
        logging.info("\n[STEP 1] Generating unique task idea...")
        from agents.k8s_task_idea_agent import K8sTaskConcept, get_last_saved_concept, clear_last_saved_concept
        
        clear_last_saved_concept()
        
        # Build list of existing concepts
        existing_concepts = []
        if idea_memory.generated_ideas:
            existing_concepts = [idea['concept'] for idea in idea_memory.generated_ideas.values()]
        
        idea_prompt = (
            "Based on the Kubernetes documentation, suggest ONE new and unique task idea "
            "for teaching Kubernetes concepts. Choose a concept that hasn't been covered yet. "
        )
        
        if existing_concepts:
            idea_prompt += (
                f"\n\n⚠️  IMPORTANT: Do NOT suggest these previously covered concepts:\n"
                f"{chr(10).join([f'  - {c}' for c in existing_concepts])}\n"
                f"\nGenerate a DIFFERENT concept that is NOT in the list above."
            )
        
        idea_prompt += (
            "\n\nYou MUST generate exactly 3 task variations (BEGINNER, INTERMEDIATE, ADVANCED)."
            "\n\nFor the BEGINNER variation, use a task_id in format '###_concept_name' (e.g., '050_secrets_management')."
            "\nFor INTERMEDIATE and ADVANCED, you can use sequential IDs or descriptive suffixes."
            "\n\nEach variation must include:"
            "\n- task_id: string (e.g., '050_secrets_management')"
            "\n- difficulty: string - must be exactly 'BEGINNER', 'INTERMEDIATE', or 'ADVANCED'"
            "\n- title: string - descriptive title"
            "\n- objective: string - what students will learn"
            "\n- key_skills: list of strings - skills students will acquire"
            "\n- estimated_time: integer - completion time in minutes"
            "\n\nAlso provide:"
            "\n- concept: string - core concept name"
            "\n- description: string - general description of the concept"
            "\n- tags: list of strings - relevant tags (e.g., ['security', 'storage'])"
            "\n\nCall save_k8s_task_concept with ALL parameters: concept, tags, description, and variations (list of 3 dicts)."
        )
        
        idea_result = await idea_agent.run(idea_prompt)
        concept = get_last_saved_concept()
        
        if not concept:
            logging.error("❌ No concept saved via tool call")
            return
        
        if not concept.variations or len(concept.variations) == 0:
            logging.error("❌ No task variations found in concept")
            return
        
        beginner_task = concept.variations[0]
        target_topic = concept.concept
        task_id = beginner_task.task_id
        
        logging.info(f"✅ Generated concept: {concept.concept} (ID: {task_id})")
        
        # Step 2: Run workflow
        logging.info("\n[STEP 2] Running workflow to generate task files...")
        
        # Get existing tasks
        game_dir = PATHS.game_root
        existing_tasks = []
        if game_dir.exists():
            existing_tasks = [d.name for d in game_dir.iterdir() if d.is_dir() and d.name[0].isdigit()]
        
        task_prompt = (
            f"Generate a complete Kubernetes learning task with ID '{task_id}' about '{target_topic}'. "
            f"\n\nTask Details:"
            f"\n- Concept: {concept.concept}"
            f"\n- Description: {concept.description}"
            f"\n- Difficulty: {beginner_task.difficulty}"
            f"\n- Objective: {beginner_task.objective}"
            f"\n\nEXISTING TASKS (avoid these IDs): {', '.join(existing_tasks) if existing_tasks else 'None'}"
            f"\n\nPREVIOUSLY COVERED CONCEPTS (this is a new concept): {', '.join(existing_concepts) if existing_concepts else 'None'}"
            f"\n\n✅ Create directory: {PATHS.game_name}/{task_id}/"
            f"\n\nCreate ALL required files including __init__.py, instruction.md, session.json, "
            f"setup.template.yaml, answer.template.yaml, and all test files (test_01_setup.py, "
            f"test_02_ready.py, test_03_answer.py, test_05_check.py, test_06_cleanup.py). "
            f"Include test_04_challenge.py only if the task requires pre-validation actions like load generation. "
            f"test_02_ready.py must test that resources from setup.template.yaml are ready. "
            f"Use proper Jinja template variables and follow all established patterns. "
            f"Make sure all files are syntactically correct and tests will pass."
        )
        
        # Create initial state object
        initial_state = InitialWorkflowState(
            prompt=task_prompt,
            target_topic=target_topic,
            task_id=task_id,
            concept_description=concept.description,
            difficulty=beginner_task.difficulty,
            objective=beginner_task.objective,
            retry_count=0,
            max_retries=3
        )
        
        workflow_succeeded = False
        
        async for event in workflow.run_stream(initial_state):
            if isinstance(event, WorkflowEvent):
                if event.data and isinstance(event.data, str) and event.data.strip():
                    if "successfully generated" in event.data:
                        workflow_succeeded = True
        
        # Save concept to memory only if workflow succeeded
        if workflow_succeeded:
            idea_memory.add_structured_concept(concept)
            logging.info(f"\n💾 Saved concept to memory: {concept.concept}")
        
        logging.info("\n" + "="*80)
        logging.info("WORKFLOW COMPLETE")
        logging.info("="*80)


if __name__ == "__main__":
    asyncio.run(main())
