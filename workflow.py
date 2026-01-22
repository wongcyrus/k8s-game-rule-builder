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
    level=logging.WARNING,
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
    logging.info("\n[STEP] Parsing generated task...")
    
    # Initialize shared state if not already set
    try:
        await ctx.get_shared_state("retry_count")
    except KeyError:
        await ctx.set_shared_state("retry_count", 0)
    
    try:
        await ctx.get_shared_state("max_retries")
    except KeyError:
        await ctx.set_shared_state("max_retries", 3)
    
    text = response.agent_response.text
    
    # Try to get task_id from shared state first (set by main())
    try:
        task_id = await ctx.get_shared_state("task_id")
    except KeyError:
        # Fallback: Extract task ID from response text
        task_id_match = re.search(rf'{PATHS.game_name}/(\d{{3}}_[a-z0-9_]+)', text)
        if not task_id_match:
            task_id_match = re.search(rf'tests/{PATHS.game_name}/(\d{{3}}_[a-z0-9_]+)', text)
        if not task_id_match:
            task_id_match = re.search(r'(\d{3}_[a-z0-9_]+)', text)
        
        if task_id_match:
            task_id = task_id_match.group(1)
        else:
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
    from agents.pytest_runner import run_pytest_command
    
    pytest_command = f"pytest --import-mode=importlib --rootdir=. {task_with_val.task_directory}/"
    result = run_pytest_command(pytest_command)
    
    test_result = TestResult(
        is_valid=result["is_valid"],
        reason=result["reason"],
        task_id=task_with_val.task_id,
        task_directory=task_with_val.task_directory
    )
    
    await ctx.send_message(test_result)


# Executor: Make decision based on test results
@executor(id="make_decision")
async def make_decision(test_result: TestResult, ctx: WorkflowContext[CombinedValidationResult]) -> None:
    """Make keep/remove decision based on validation and test results."""
    logging.info("\n[STEP] Making decision...")
    
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
    
    combined = CombinedValidationResult(
        validation=validation,
        test=test_result,
        retry_count=retry_count,
        max_retries=max_retries
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
    """Remove the task - it failed validation or tests."""
    logging.info(f"\n[STEP] ❌ Removing task: {combined.test.task_id}")
    reasons = []
    if not combined.validation.is_valid:
        reasons.append(f"Validation failed: {combined.validation.reason}")
    if not combined.test.is_valid:
        reasons.append(f"Tests failed: {combined.test.reason}")
    
    # Remove the directory
    task_path = PATHS.game_root / combined.test.task_id
    if task_path.exists():
        shutil.rmtree(task_path)
    
    # Increment retry count
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
    
    Supports full workflow mode (with concept details) and DevUI/manual mode (basic prompt).
    """
    logging.info(f"\n[STEP] 🔄 Retrying generation: attempt {combined.retry_count + 1}/{combined.max_retries}")
    # Try to get concept details from shared state
    try:
        target_topic = await ctx.get_shared_state("target_topic")
        task_id = await ctx.get_shared_state("task_id")
        concept_description = await ctx.get_shared_state("concept_description")
        difficulty = await ctx.get_shared_state("difficulty")
        objective = await ctx.get_shared_state("objective")
        
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
        
    except KeyError:
        # DevUI/manual mode - minimal data available
        try:
            task_id = await ctx.get_shared_state("task_id")
            target_topic = await ctx.get_shared_state("target_topic")
            
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
    logging.info("\n[STEP] 🏁 Completing workflow...")
    if combined.should_keep:
        await ctx.yield_output(f"🏁 Workflow complete: Task {combined.test.task_id} successfully generated")
    else:
        await ctx.yield_output(f"🏁 Workflow complete: Failed to generate valid task after {combined.retry_count} retries")


async def main():
    """Run the workflow with conditional logic."""
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
            .add_edge(keep_task, check_loop)
            .add_edge(remove_task, check_loop)
            .add_multi_selection_edge_group(
                check_loop,
                [retry_generation, complete_workflow],
                selection_func=select_loop_action,
            )
            .add_edge(retry_generation, generator_executor)
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
            f"\n\nIMPORTANT: Create directory {PATHS.game_name}/{task_id}/ (NOT tests/{PATHS.game_name}/...)"
            f"\n\nCreate ALL required files including __init__.py, instruction.md, session.json, "
            f"setup.template.yaml, answer.template.yaml, and all test files (test_01_setup.py, "
            f"test_02_ready.py, test_03_answer.py, test_05_check.py, test_06_cleanup.py). "
            f"Include test_04_challenge.py only if the task requires pre-validation actions like load generation. "
            f"test_02_ready.py must test that resources from setup.template.yaml are ready. "
            f"Use proper Jinja template variables and follow all established patterns. "
            f"Make sure all files are syntactically correct and tests will pass."
        )
        
        workflow_succeeded = False
        
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
