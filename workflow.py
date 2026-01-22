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


@dataclass
class CombinedValidationResult:
    """Combined validation and test results for decision making."""
    validation: ValidationResult
    test: TestResult
    retry_count: int = 0  # Track number of retry attempts
    max_retries: int = 3  # Maximum retry attempts
    
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


# Executor: Parse task generation response
@executor(id="parse_generated_task")
async def parse_generated_task(response: AgentExecutorResponse, ctx: WorkflowContext[TaskInfo]) -> None:
    """Parse task generation response and extract task info."""
    logging.info("\n[EXECUTOR] parse_generated_task: Extracting task ID from generator response...")
    
    # Initialize shared state if not already set (for DevUI and other entry points)
    try:
        await ctx.get_shared_state("retry_count")
    except KeyError:
        await ctx.set_shared_state("retry_count", 0)
        logging.info("Initialized retry_count to 0")
    
    try:
        await ctx.get_shared_state("max_retries")
    except KeyError:
        await ctx.set_shared_state("max_retries", 3)
        logging.info("Initialized max_retries to 3")
    
    text = response.agent_response.text
    logging.info(f"Generator response (first 500 chars): {text[:500]}")
    
    # Try to get task_id from shared state first (set by main())
    try:
        task_id = await ctx.get_shared_state("task_id")
        logging.info(f"✅ Using task ID from shared state: {task_id}")
    except KeyError:
        # Fallback: Extract task ID from response text
        # Try multiple patterns since MCP server is scoped to tests/ root
        task_id_match = re.search(rf'{PATHS.game_name}/(\d{{3}}_[a-z0-9_]+)', text)
        if not task_id_match:
            task_id_match = re.search(rf'tests/{PATHS.game_name}/(\d{{3}}_[a-z0-9_]+)', text)
        if not task_id_match:
            task_id_match = re.search(r'(\d{3}_[a-z0-9_]+)', text)
        
        if task_id_match:
            task_id = task_id_match.group(1)
            logging.info(f"✅ Extracted task ID from response: {task_id}")
        else:
            logging.error("❌ Could not extract task ID from generation response")
            # Increment retry count
            try:
                retry_count = await ctx.get_shared_state("retry_count")
                retry_count += 1
            except KeyError:
                retry_count = 1
            await ctx.set_shared_state("retry_count", retry_count)
            raise ValueError("Failed to parse task ID from generation")
    
    task_info = TaskInfo(
        task_id=task_id,
        task_directory=f"tests/{PATHS.game_name}/{task_id}"
    )
    
    await ctx.send_message(task_info)


# Executor: Run validation directly (no LLM needed)
@executor(id="run_validation")
async def run_validation(task_info: TaskInfo, ctx: WorkflowContext[TaskWithValidation]) -> None:
    """Run validation directly without LLM - it's just file checks."""
    logging.info(f"\n[EXECUTOR] run_validation: Validating {task_info.task_id}...")
    
    from agents.k8s_task_validator import validate_task_directory
    
    # Run validation directly
    result = validate_task_directory(task_info.task_id)
    
    # Extract detailed failure reasons from results
    failure_reasons = []
    if not result["is_valid"] and result.get("details"):
        for detail in result["details"]:
            if isinstance(detail, dict) and not detail.get("is_valid", True):
                reason = detail.get("reason", "Unknown error")
                # Skip generic messages, only include specific errors
                if reason not in ["Validation completed", "Directory listing"]:
                    failure_reasons.append(reason)
    
    # Create a more informative reason
    if failure_reasons:
        detailed_reason = "; ".join(failure_reasons[:3])  # Show first 3 errors
        if len(failure_reasons) > 3:
            detailed_reason += f" (and {len(failure_reasons) - 3} more errors)"
    else:
        # If no specific failures found but validation failed, use generic message
        if not result["is_valid"]:
            detailed_reason = "Validation failed - check file structure and syntax"
        else:
            detailed_reason = "All validation checks passed"
    
    # Convert to ValidationResult
    validation = ValidationResult(
        is_valid=result["is_valid"],
        reason=detailed_reason,
        task_id=task_info.task_id,
        task_directory=task_info.task_directory
    )
    
    status = "✅ PASSED" if validation.is_valid else "❌ FAILED"
    logging.info(f"{status} Validation: {validation.reason}")
    
    # Store validation result in shared state for later retrieval
    await ctx.set_shared_state(f"validation_{validation.task_id}", validation)
    
    # Create TaskWithValidation
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
    logging.info(f"\n[EXECUTOR] run_pytest: Running tests for {task_with_val.task_id}...")
    
    from agents.pytest_runner import run_pytest_command
    
    # Build pytest command
    pytest_command = f"pytest --import-mode=importlib --rootdir=. {task_with_val.task_directory}/"
    
    # Run pytest directly
    result = run_pytest_command(pytest_command)
    
    # Convert to TestResult
    test_result = TestResult(
        is_valid=result["is_valid"],
        reason=result["reason"],
        task_id=task_with_val.task_id,
        task_directory=task_with_val.task_directory
    )
    
    status = "✅ PASSED" if test_result.is_valid else "❌ FAILED"
    logging.info(f"{status} Tests: {test_result.reason}")
    
    await ctx.send_message(test_result)


# Executor: Make decision based on test results
@executor(id="make_decision")
async def make_decision(test_result: TestResult, ctx: WorkflowContext[CombinedValidationResult]) -> None:
    """Make keep/remove decision based on validation and test results."""
    logging.info("\n[EXECUTOR] make_decision: Making decision based on test results...")
    
    # Retrieve validation result from shared state
    try:
        validation = await ctx.get_shared_state(f"validation_{test_result.task_id}")
    except KeyError:
        # Fallback: assume validation passed if we got to testing phase
        logging.warning(f"⚠️  Validation result not found for {test_result.task_id}, assuming passed")
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
    
    # Combine results for decision
    combined = CombinedValidationResult(
        validation=validation,
        test=test_result,
        retry_count=retry_count,
        max_retries=max_retries
    )
    
    decision = "KEEP" if combined.should_keep else "REMOVE"
    logging.info(f"\n🔀 DECISION: {decision} task {test_result.task_id}")
    logging.info(f"   Validation: {'✅ PASSED' if validation.is_valid else '❌ FAILED'} - {validation.reason}")
    logging.info(f"   Tests: {'✅ PASSED' if test_result.is_valid else '❌ FAILED'} - {test_result.reason}")
    logging.info(f"   Retry count: {retry_count}/{max_retries}")
    
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


# Selection function for loop routing
def select_loop_action(combined: CombinedValidationResult, target_ids: list[str]) -> list[str]:
    """Select whether to retry generation or complete workflow.
    
    Args:
        combined: Combined validation and test results
        target_ids: [retry_generation_id, complete_workflow_id]
    
    Returns:
        List containing the selected target ID
    """
    retry_generation_id, complete_workflow_id = target_ids
    
    if combined.should_retry:
        logging.info(f"🔄 Routing to RETRY_GENERATION (attempt {combined.retry_count + 1}/{combined.max_retries})")
        return [retry_generation_id]
    else:
        if combined.should_keep:
            logging.info(f"🏁 Routing to COMPLETE_WORKFLOW (task successful)")
        else:
            logging.info(f"🏁 Routing to COMPLETE_WORKFLOW (max retries reached: {combined.retry_count}/{combined.max_retries})")
        return [complete_workflow_id]


# Executor: Keep task (success path)
@executor(id="keep_task")
async def keep_task(combined: CombinedValidationResult, ctx: WorkflowContext[CombinedValidationResult]) -> None:
    """Keep the task - it passed all checks."""
    logging.info(f"\n✅ KEEPING TASK: {combined.test.task_id}")
    logging.info(f"   Validation: {combined.validation.reason}")
    logging.info(f"   Tests: {combined.test.reason}")
    logging.info(f"   Retry attempts: {combined.retry_count}")
    
    await ctx.yield_output(
        f"✅ Task {combined.test.task_id} passed all checks and has been kept."
    )
    
    # Send message to check_loop
    await ctx.send_message(combined)


# Executor: Remove task (failure path)
@executor(id="remove_task")
async def remove_task(combined: CombinedValidationResult, ctx: WorkflowContext[CombinedValidationResult]) -> None:
    """Remove the task - it failed validation or tests."""
    logging.info(f"\n❌ REMOVING TASK: {combined.test.task_id}")
    
    reasons = []
    if not combined.validation.is_valid:
        reasons.append(f"Validation failed: {combined.validation.reason}")
    if not combined.test.is_valid:
        reasons.append(f"Tests failed: {combined.test.reason}")
    
    logging.info(f"   Reasons: {'; '.join(reasons)}")
    logging.info(f"   Retry attempts: {combined.retry_count}/{combined.max_retries}")
    
    # Actually remove the directory - use absolute path
    task_path = PATHS.game_root / combined.test.task_id
    if task_path.exists():
        shutil.rmtree(task_path)
        logging.info(f"   🗑️  Deleted directory: {task_path}")
    else:
        logging.warning(f"   ⚠️  Directory not found: {task_path}")
    
    # Increment retry count for next attempt
    retry_count = combined.retry_count + 1
    await ctx.set_shared_state("retry_count", retry_count)
    
    await ctx.yield_output(
        f"❌ Task {combined.test.task_id} failed checks and has been removed. Reasons: {'; '.join(reasons)}"
    )
    
    # Create updated combined result with new retry count
    updated_combined = CombinedValidationResult(
        validation=combined.validation,
        test=combined.test,
        retry_count=retry_count,
        max_retries=combined.max_retries
    )
    
    # Send updated message to check_loop
    await ctx.send_message(updated_combined)


# Executor: Check if should loop back
@executor(id="check_loop")
async def check_loop(combined: CombinedValidationResult, ctx: WorkflowContext[CombinedValidationResult]) -> None:
    """Check if we should retry or complete the workflow."""
    logging.info(f"\n🔄 CHECK_LOOP: Retry count {combined.retry_count}/{combined.max_retries}")
    
    if combined.should_keep:
        logging.info(f"   → Task successful, will complete")
    elif combined.should_retry:
        logging.info(f"   → Will retry generation (attempt {combined.retry_count + 1})")
    else:
        logging.info(f"   → Max retries reached, will complete")
    
    # Always send message - routing will decide what to do
    await ctx.send_message(combined)


# Executor: Retry generation (loop back)
@executor(id="retry_generation")
async def retry_generation(combined: CombinedValidationResult, ctx: WorkflowContext[AgentExecutorRequest]) -> None:
    """Retry task generation after a failure.
    
    Note: Each retry creates a fresh request. The generator uses AzureOpenAIChatClient
    which manages conversation in-memory, so each iteration is independent.
    
    Supports two modes:
    1. Full workflow mode: Uses complete concept details from shared state
    2. DevUI/manual mode: Falls back to basic prompt if concept details missing
    """
    logging.info(f"\n🔄 RETRY: Attempt {combined.retry_count + 1}/{combined.max_retries}")
    
    # Try to get all concept details from shared state
    try:
        target_topic = await ctx.get_shared_state("target_topic")
        task_id = await ctx.get_shared_state("task_id")
        concept_description = await ctx.get_shared_state("concept_description")
        difficulty = await ctx.get_shared_state("difficulty")
        objective = await ctx.get_shared_state("objective")
        
        # Full workflow mode - all data available
        logging.info(f"   Mode: Full workflow (with concept details)")
        logging.info(f"   Task ID: {task_id}")
        logging.info(f"   Topic: {target_topic}")
        logging.info(f"   Difficulty: {difficulty}")
        
        generation_prompt = (
            f"Generate a complete Kubernetes learning task with ID '{task_id}' about '{target_topic}'. "
            f"This is retry attempt {combined.retry_count + 1} of {combined.max_retries}. "
            f"\n\nIMPORTANT: You MUST use the exact task ID '{task_id}' - do not generate a new ID."
            f"\n\nIMPORTANT: Create directory {PATHS.game_name}/{task_id}/ (NOT tests/{PATHS.game_name}/...)"
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
        
    except KeyError as e:
        # DevUI/manual mode - minimal data available
        logging.warning(f"   Mode: DevUI/manual (missing concept details: {e})")
        logging.warning("   Falling back to basic retry prompt")
        
        # Try to get at least task_id and topic
        try:
            task_id = await ctx.get_shared_state("task_id")
            target_topic = await ctx.get_shared_state("target_topic")
            
            logging.info(f"   Task ID: {task_id}")
            logging.info(f"   Topic: {target_topic}")
            
            generation_prompt = (
                f"Generate a complete Kubernetes learning task with ID '{task_id}' about '{target_topic}'. "
                f"This is retry attempt {combined.retry_count + 1} of {combined.max_retries}. "
                f"\n\nIMPORTANT: You MUST use the exact task ID '{task_id}' - do not generate a new ID."
                f"\n\nIMPORTANT: Create directory {PATHS.game_name}/{task_id}/ (NOT tests/{PATHS.game_name}/...)"
                f"\n\nCreate ALL required files including __init__.py, instruction.md, session.json, "
                f"setup.template.yaml, answer.template.yaml, and all test files (test_01_setup.py, "
                f"test_02_ready.py, test_03_answer.py, test_05_check.py, test_06_cleanup.py). "
                f"Include test_04_challenge.py only if the task requires pre-validation actions like load generation. "
                f"test_02_ready.py must test that resources from setup.template.yaml are ready. "
                f"Use proper Jinja template variables and follow all established patterns. "
                f"Make sure all files are syntactically correct and tests will pass."
            )
            
        except KeyError:
            # Absolute fallback - no task_id or topic
            logging.error("❌ RETRY FAILED: Missing both task_id and target_topic")
            logging.error("   Cannot retry without at least task ID and topic.")
            await ctx.yield_output(
                f"❌ Retry failed: Missing required information (task_id and target_topic). Workflow cannot continue."
            )
            return
    
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
    if combined.should_keep:
        logging.info(f"\n🏁 COMPLETE: Task {combined.test.task_id} successfully generated after {combined.retry_count} retries")
        await ctx.yield_output(f"🏁 Workflow complete: Task {combined.test.task_id} successfully generated")
    else:
        logging.info(f"\n🏁 COMPLETE: Failed to generate valid task after {combined.retry_count} retries")
        await ctx.yield_output(f"🏁 Workflow complete: Failed to generate valid task after {combined.retry_count} retries")


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
    
    # Create all MCP tools at workflow level to avoid nested context issues
    docs_mcp_tool = MCPStdioTool(
        name="filesystem_docs",
        command="npx",
        args=["-y", "@modelcontextprotocol/server-filesystem", str(PATHS.k8s_docs_root)],
        load_prompts=False
    )
    
    # MCP server root should be the parent of tests/ so agent can create tests/game02/XXX/
    tests_mcp_tool = MCPStdioTool(
        name="filesystem_tests",
        command="npx",
        args=["-y", "@modelcontextprotocol/server-filesystem", str(PATHS.tests_root.parent)],
        load_prompts=False
    )
    
    # Initialize all MCP tools in a single context
    async with docs_mcp_tool, tests_mcp_tool:
        # Create agents with MCP tools
        idea_agent, idea_memory = await create_idea_agent_with_mcp(docs_mcp_tool)
        generator_agent = await create_generator_agent_with_mcp(tests_mcp_tool)
        
        logging.info(f"✅ Idea agent initialized with {len(idea_memory.generated_ideas)} existing concepts")
        
        # Create agent executors
        generator_executor = AgentExecutor(generator_agent, id="generator_agent")
        
        # Build workflow with conditional logic and retry loop
        # Note: Validation and pytest are now direct executors (no LLM needed)
        workflow = (
            WorkflowBuilder()
            .set_start_executor(generator_executor)
            .add_edge(generator_executor, parse_generated_task)
            .add_edge(parse_generated_task, run_validation)
            .add_edge(run_validation, run_pytest)
            .add_edge(run_pytest, make_decision)
            .add_multi_selection_edge_group(
                make_decision,
                [keep_task, remove_task],
                selection_func=select_action,
            )
            # Add loop edges - both keep and remove go to check_loop
            .add_edge(keep_task, check_loop)
            .add_edge(remove_task, check_loop)
            # check_loop routes to either retry_generation or complete_workflow
            .add_multi_selection_edge_group(
                check_loop,
                [retry_generation, complete_workflow],
                selection_func=select_loop_action,
            )
            # retry_generation loops back to generator
            .add_edge(retry_generation, generator_executor)
            .build()
        )
        
        # Initialize workflow configuration
        logging.info("\n🔄 Workflow configured with retry loop")
        logging.info(f"   Max retries: 3")
        logging.info(f"   Loop structure:")
        logging.info(f"     keep_task → check_loop → complete_workflow (success)")
        logging.info(f"     remove_task → check_loop → [retry_generation OR complete_workflow]")
        logging.info(f"     retry_generation → generator_agent (loop back)")
        logging.info(f"     complete_workflow → END")
        
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
            png_file = viz.save_png("workflow_graph.png")
            logging.info(f"✅ PNG exported to: {png_file}")
        except Exception as e:
            logging.warning(f"⚠️  Could not export PNG: {e}")       
       
        
        logging.info("\n" + "="*80)
        
        # Step 1: Generate unique task idea using idea agent
        logging.info("\n[STEP 1] Generating unique task idea from K8s documentation...")
        logging.info("-"*80)
        
        from agents.k8s_task_idea_agent import K8sTaskConcept, get_last_saved_concept, clear_last_saved_concept
        
        # Clear any previous concept
        clear_last_saved_concept()
        
        idea_result = await idea_agent.run(
            "Based on the Kubernetes documentation, suggest ONE new and unique task idea "
            "for teaching Kubernetes concepts. Choose a concept that hasn't been covered yet. "
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
        
        # Get concept from tool call
        concept = get_last_saved_concept()
        
        if not concept:
            logging.error("❌ No concept saved via tool call")
            logging.error(f"   Agent response (first 500 chars): {idea_result.text[:500]}")
            return
        
        # Validate variations exist
        if not concept.variations or len(concept.variations) == 0:
            logging.error("❌ No task variations found in concept")
            logging.error(f"   Concept: {concept.concept}")
            logging.error(f"   Description: {concept.description}")
            logging.error(f"   Tags: {concept.tags}")
            logging.error("\n⚠️  The idea agent did not generate task variations properly.")
            logging.error("   This is an LLM execution issue - the agent should generate 3 variations.")
            logging.error("   Try running the workflow again, or check the idea agent instructions.")
            return
        
        # Don't save to memory yet - only save if task passes validation/tests
        logging.info(f"✅ Generated concept: {concept.concept}")
        logging.info(f"   Will save to memory only if task succeeds")
        
        # Use beginner variation
        beginner_task = concept.variations[0]
        
        target_topic = concept.concept
        task_id = beginner_task.task_id
        
        logging.info(f"\n[STEP 2] Running workflow to generate task files...")
        logging.info("-"*80)
        
        # Get list of existing task IDs to avoid duplication
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
            f"\n\nIMPORTANT: Create directory {PATHS.game_name}/{task_id}/ (NOT tests/{PATHS.game_name}/...)"
            f"\n\nCreate ALL required files including __init__.py, instruction.md, session.json, "
            f"setup.template.yaml, answer.template.yaml, and all test files (test_01_setup.py, "
            f"test_02_ready.py, test_03_answer.py, test_05_check.py, test_06_cleanup.py). "
            f"Include test_04_challenge.py only if the task requires pre-validation actions like load generation. "
            f"test_02_ready.py must test that resources from setup.template.yaml are ready. "
            f"Use proper Jinja template variables and follow all established patterns. "
            f"Make sure all files are syntactically correct and tests will pass."
        )
        
        logging.info(f"\n🚀 Starting workflow for: {target_topic}")
        logging.info(f"   Task ID: {task_id}")
        logging.info(f"   Existing tasks: {len(existing_tasks)}")
        
        # Track if workflow succeeded
        workflow_succeeded = False
        
        # Store all concept details in workflow context for retry attempts
        # Note: Don't store idea_memory object (not serializable) - we'll handle save differently
        async for event in workflow.run_stream(
            task_prompt, 
            initial_state={
                "target_topic": target_topic,
                "task_id": task_id,
                "concept_description": concept.description,
                "difficulty": beginner_task.difficulty,
                "objective": beginner_task.objective,
                "retry_count": 0,
                "max_retries": 3
            }
        ):
            if isinstance(event, WorkflowEvent):
                if event.data and isinstance(event.data, str) and event.data.strip():  # Only log non-empty string events
                    logging.info(f"\n📤 Workflow output: {event.data}")
                    # Check if workflow succeeded
                    if "successfully generated" in event.data:
                        workflow_succeeded = True
        
        # Save concept to memory only if workflow succeeded
        if workflow_succeeded:
            idea_memory.add_structured_concept(concept)
            logging.info(f"\n💾 Saved concept to memory: {concept.concept}")
        else:
            logging.info(f"\n⚠️  Concept not saved to memory (workflow did not succeed)")
        
        logging.info("\n" + "="*80)
        logging.info("WORKFLOW COMPLETE")
        logging.info("="*80)


if __name__ == "__main__":
    asyncio.run(main())
