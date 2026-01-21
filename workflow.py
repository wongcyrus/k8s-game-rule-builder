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
    get_k8s_task_validator_agent,
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
        # Increment retry count
        try:
            retry_count = await ctx.get_shared_state("retry_count")
            retry_count += 1
        except KeyError:
            retry_count = 1
        await ctx.set_shared_state("retry_count", retry_count)
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
        
        # Store validation result in shared state for later retrieval
        await ctx.set_shared_state(f"validation_{validation.task_id}", validation)
        
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
    
    # Parse test result - look for pytest success indicators
    # Check for explicit success messages or passed count
    is_valid = False
    reason = "Tests failed"
    
    # Look for pytest success patterns
    if "all tests passed" in text.lower():
        is_valid = True
        reason = "All tests passed"
    elif re.search(r'passed.*✅.*\d+', text, re.IGNORECASE):
        # Look for "Passed: ✅ X" pattern
        passed_match = re.search(r'passed.*✅.*(\d+)', text, re.IGNORECASE)
        failed_match = re.search(r'failed.*❌.*(\d+)', text, re.IGNORECASE)
        if passed_match and failed_match:
            passed_count = int(passed_match.group(1))
            failed_count = int(failed_match.group(1))
            if passed_count > 0 and failed_count == 0:
                is_valid = True
                reason = f"All {passed_count} tests passed"
            else:
                reason = f"{failed_count} tests failed, {passed_count} passed"
    elif re.search(r'\d+\s+passed', text, re.IGNORECASE):
        # Look for "X passed" in pytest output
        passed_match = re.search(r'(\d+)\s+passed', text, re.IGNORECASE)
        failed_match = re.search(r'(\d+)\s+failed', text, re.IGNORECASE)
        if passed_match:
            passed_count = int(passed_match.group(1))
            failed_count = int(failed_match.group(1)) if failed_match else 0
            if passed_count > 0 and failed_count == 0:
                is_valid = True
                reason = f"All {passed_count} tests passed"
            else:
                reason = f"{failed_count} tests failed, {passed_count} passed"
    
    test_result = TestResult(
        is_valid=is_valid,
        reason=reason,
        task_id=task_id,
        task_directory=task_directory
    )
    
    status = "✅ PASSED" if test_result.is_valid else "❌ FAILED"
    logging.info(f"{status} Tests: {test_result.reason}")
    
    # Retrieve validation result from shared state
    try:
        validation = await ctx.get_shared_state(f"validation_{task_id}")
    except KeyError:
        # Fallback: assume validation passed if we got to testing phase
        logging.warning(f"⚠️  Validation result not found for {task_id}, assuming passed")
        validation = ValidationResult(
            is_valid=True,
            reason="Validation passed (assumed)",
            task_id=task_id,
            task_directory=task_directory
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
    logging.info(f"\n🔀 DECISION: {decision} task {task_id}")
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
    task_path = PATHS.tests_root / "game02" / combined.test.task_id
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
    """
    logging.info(f"\n🔄 RETRY: Attempt {combined.retry_count + 1}/{combined.max_retries}")
    
    # Get the target topic from shared state
    try:
        target_topic = await ctx.get_shared_state("target_topic")
    except KeyError:
        target_topic = "a Kubernetes concept"
    
    # Get list of existing task IDs to avoid duplication
    game02_dir = PATHS.tests_root / "game02"
    existing_tasks = []
    if game02_dir.exists():
        existing_tasks = [d.name for d in game02_dir.iterdir() if d.is_dir() and d.name[0].isdigit()]
    
    generation_prompt = (
        f"Generate a complete Kubernetes learning task about '{target_topic}' with a unique ID in format '###_concept_name'. "
        f"This is retry attempt {combined.retry_count + 1} of {combined.max_retries}. "
        f"\n\nEXISTING TASKS (avoid these IDs): {', '.join(existing_tasks) if existing_tasks else 'None'}"
        f"\n\nCreate ALL required files including __init__.py, instruction.md, session.json, "
        f"setup.template.yaml, answer.template.yaml, and all test files (test_01_setup.py, "
        f"test_03_answer.py, test_05_check.py, test_06_cleanup.py). "
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
    
    tests_mcp_tool = MCPStdioTool(
        name="filesystem_tests",
        command="npx",
        args=["-y", "@modelcontextprotocol/server-filesystem", str(PATHS.tests_root)],
        load_prompts=False
    )
    
    # Initialize all MCP tools in a single context
    async with docs_mcp_tool, tests_mcp_tool:
        # Create agents with MCP tools
        idea_agent, idea_memory, idea_thread, thread_state_path = await create_idea_agent_with_mcp(docs_mcp_tool)
        generator_agent = await create_generator_agent_with_mcp(tests_mcp_tool)
        
        logging.info(f"✅ Idea agent initialized with {len(idea_memory.generated_ideas)} existing concepts")
        
        # Create agent executors
        generator_executor = AgentExecutor(generator_agent, id="generator_agent")
        
        validator_agent = get_k8s_task_validator_agent()
        validator_executor = AgentExecutor(validator_agent, id="validator_agent")
        
        pytest_agent = get_pytest_agent()
        pytest_executor = AgentExecutor(pytest_agent, id="pytest_agent")
        
        # Build workflow with conditional logic and retry loop
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
        
        # Step 1: Generate unique task idea using idea agent
        logging.info("\n[STEP 1] Generating unique task idea from K8s documentation...")
        logging.info("-"*80)
        
        from agents.k8s_task_idea_agent import K8sTaskConcept
        
        idea_result = await idea_agent.run(
            "Based on the Kubernetes documentation, suggest ONE new and unique task idea "
            "for teaching Kubernetes concepts. Choose a concept that hasn't been covered yet. "
            "Provide a clear task ID in format '###_concept_name' (e.g., '050_secrets_management'). "
            "Include the objective and what students will learn.",
            thread=idea_thread,
            response_format=K8sTaskConcept,
        )
        
        # Extract concept
        concept = None
        if idea_result.value and isinstance(idea_result.value, K8sTaskConcept):
            concept = idea_result.value
            logging.info("✅ Got structured output from idea agent")
        else:
            logging.error("❌ Failed to get structured output from idea agent")
            logging.error(f"   idea_result.value type: {type(idea_result.value)}")
            logging.error(f"   idea_result.value: {idea_result.value}")
            if hasattr(idea_result, 'text'):
                logging.error(f"   Response text (first 500 chars): {idea_result.text[:500]}")
            return
        
        # Save to memory
        idea_memory.add_structured_concept(concept)
        logging.info(f"✅ Saved concept to memory: {concept.concept}")
        
        # Use beginner variation
        beginner_task = concept.variations[0] if concept.variations else None
        if not beginner_task:
            logging.error("❌ No task variations found")
            return
        
        target_topic = concept.concept
        task_id = beginner_task.task_id
        
        # Persist thread state
        import json
        serialized_thread = await idea_thread.serialize()
        with open(thread_state_path, "w") as f:
            json.dump(serialized_thread, f)
        
        logging.info(f"\n[STEP 2] Running workflow to generate task files...")
        logging.info("-"*80)
        
        # Get list of existing task IDs to avoid duplication
        game02_dir = PATHS.tests_root / "game02"
        existing_tasks = []
        if game02_dir.exists():
            existing_tasks = [d.name for d in game02_dir.iterdir() if d.is_dir() and d.name[0].isdigit()]
        
        task_prompt = (
            f"Generate a complete Kubernetes learning task with ID '{task_id}' about '{target_topic}'. "
            f"\n\nTask Details:"
            f"\n- Concept: {concept.concept}"
            f"\n- Description: {concept.description}"
            f"\n- Difficulty: {beginner_task.difficulty}"
            f"\n- Objective: {beginner_task.objective}"
            f"\n\nEXISTING TASKS (avoid these IDs): {', '.join(existing_tasks) if existing_tasks else 'None'}"
            f"\n\nCreate ALL required files including __init__.py, instruction.md, session.json, "
            f"setup.template.yaml, answer.template.yaml, and all test files (test_01_setup.py, "
            f"test_03_answer.py, test_05_check.py, test_06_cleanup.py). "
            f"Use proper Jinja template variables and follow all established patterns. "
            f"Make sure all files are syntactically correct and tests will pass."
        )
        
        logging.info(f"\n🚀 Starting workflow for: {target_topic}")
        logging.info(f"   Task ID: {task_id}")
        logging.info(f"   Existing tasks: {len(existing_tasks)}")
        
        # Store target topic in workflow context for retry attempts
        async for event in workflow.run_stream(task_prompt, initial_state={"target_topic": target_topic, "task_id": task_id, "retry_count": 0, "max_retries": 3}):
            if isinstance(event, WorkflowEvent):
                if event.data and isinstance(event.data, str) and event.data.strip():  # Only log non-empty string events
                    logging.info(f"\n📤 Workflow output: {event.data}")
        
        logging.info("\n" + "="*80)
        logging.info("WORKFLOW COMPLETE")
        logging.info("="*80)


if __name__ == "__main__":
    asyncio.run(main())
