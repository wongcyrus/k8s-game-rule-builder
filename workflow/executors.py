"""Workflow executors for K8s task generation."""
import logging
import re
import shutil
from typing_extensions import Never

from agent_framework import (
    AgentExecutorRequest,
    AgentExecutorResponse,
    ChatMessage,
    Role,
    WorkflowContext,
    executor,
)

from agents.config import PATHS
from workflow.models import (
    InitialWorkflowState,
    TaskInfo,
    TaskWithValidation,
    ValidationResult,
    TestResult,
    CombinedValidationResult,
)


@executor(id="initialize_retry")
async def initialize_retry(message: str | AgentExecutorRequest | InitialWorkflowState, ctx: WorkflowContext[AgentExecutorRequest]) -> None:
    """Initialize or re-initialize shared state before generation."""
    logging.info("\n[STEP] Initializing/Re-initializing workflow state...")
    
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
        
        request = AgentExecutorRequest(
            messages=[ChatMessage(Role.USER, text=message.prompt)],
            should_respond=True
        )
    else:
        try:
            task_id = await ctx.get_shared_state("task_id")
            target_topic = await ctx.get_shared_state("target_topic")
            logging.info(f"Retry: State found: task_id={task_id}, topic={target_topic}")
        except KeyError as e:
            logging.error(f"Missing required shared state: {e}")
            raise
        
        if isinstance(message, str):
            request = AgentExecutorRequest(
                messages=[ChatMessage(Role.USER, text=message)],
                should_respond=True
            )
        else:
            request = message
    
    await ctx.send_message(request)


@executor(id="parse_generated_task")
async def parse_generated_task(response: AgentExecutorResponse, ctx: WorkflowContext[TaskInfo]) -> None:
    """Parse task generation response and extract task info."""
    logging.info("\n[STEP] Parsing generated task...")
    
    try:
        await ctx.get_shared_state("retry_count")
    except KeyError:
        await ctx.set_shared_state("retry_count", 0)
    
    try:
        await ctx.get_shared_state("max_retries")
    except KeyError:
        await ctx.set_shared_state("max_retries", 3)
    
    try:
        task_id = await ctx.get_shared_state("task_id")
    except KeyError:
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


@executor(id="run_validation")
async def run_validation(task_info: TaskInfo, ctx: WorkflowContext[TaskWithValidation]) -> None:
    """Run validation directly without LLM - it's just file checks."""
    logging.info(f"\n[STEP] Validating task: {task_info.task_id}")
    from agents.k8s_task_validator import validate_task_directory
    
    result = validate_task_directory(task_info.task_id)
    
    failure_reasons = []
    if not result["is_valid"] and result.get("details"):
        for detail in result["details"]:
            if isinstance(detail, dict) and not detail.get("is_valid", True):
                reason = detail.get("reason", "Unknown error")
                if reason not in ["Validation completed", "Directory listing"]:
                    failure_reasons.append(reason)
    
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
    
    raw_output = ""
    if result.get("details") and len(result["details"]) > 0:
        raw_output = result["details"][0]
        logging.info(f"✅ ✅ ✅ Captured raw output length: {len(raw_output)} chars")
        
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


@executor(id="make_decision")
async def make_decision(test_result: TestResult, ctx: WorkflowContext[CombinedValidationResult]) -> None:
    """Make keep/remove decision based on validation and test results."""
    logging.info("\n[STEP] Making decision...")
    
    logging.info(f"DEBUG make_decision: test_result type: {type(test_result)}")
    logging.info(f"DEBUG make_decision: test_result fields: {test_result.model_dump() if hasattr(test_result, 'model_dump') else vars(test_result)}")
    logging.info(f"DEBUG make_decision: raw_output length: {len(test_result.raw_output)} chars")
    
    try:
        validation = await ctx.get_shared_state(f"validation_{test_result.task_id}")
    except KeyError:
        validation = ValidationResult(
            is_valid=True,
            reason="Validation passed (assumed)",
            task_id=test_result.task_id,
            task_directory=test_result.task_directory
        )
    
    try:
        retry_count = await ctx.get_shared_state("retry_count")
    except KeyError:
        retry_count = 0
    
    try:
        max_retries = await ctx.get_shared_state("max_retries")
    except KeyError:
        max_retries = 3
    
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


@executor(id="keep_task")
async def keep_task(combined: CombinedValidationResult, ctx: WorkflowContext[CombinedValidationResult]) -> None:
    """Keep the task - it passed all checks."""
    logging.info(f"\n[STEP] ✅ Keeping task: {combined.test.task_id}")
    await ctx.yield_output(
        f"✅ Task {combined.test.task_id} passed all checks and has been kept."
    )
    await ctx.send_message(combined)


@executor(id="remove_task")
async def remove_task(combined: CombinedValidationResult, ctx: WorkflowContext[CombinedValidationResult]) -> None:
    """Move the task to unsuccessful folder - it failed validation or tests."""
    logging.info(f"\n[STEP] ❌ Moving task to unsuccessful folder: {combined.test.task_id}")
    reasons = []
    if not combined.validation.is_valid:
        reasons.append(f"Validation failed: {combined.validation.reason}")
    if not combined.test.is_valid:
        reasons.append(f"Tests failed: {combined.test.reason}")
    
    unsuccessful_dir = PATHS.unsuccessful_game_root
    unsuccessful_dir.mkdir(parents=True, exist_ok=True)
    
    task_path = PATHS.game_root / combined.test.task_id
    unsuccessful_task_path = unsuccessful_dir / combined.test.task_id
    
    if task_path.exists():
        if unsuccessful_task_path.exists():
            import time
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            unsuccessful_task_path = unsuccessful_dir / f"{combined.test.task_id}_{timestamp}"
        
        shutil.move(str(task_path), str(unsuccessful_task_path))
        logging.info(f"Moved task to: {unsuccessful_task_path}")
        
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
    
    retry_count = combined.retry_count + 1
    await ctx.set_shared_state("retry_count", retry_count)
    
    await ctx.yield_output(
        f"❌ Task {combined.test.task_id} failed checks and has been moved to unsuccessful folder. Reasons: {'; '.join(reasons)}"
    )
    
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


@executor(id="check_loop")
async def check_loop(combined: CombinedValidationResult, ctx: WorkflowContext[CombinedValidationResult]) -> None:
    """Check if we should retry or complete the workflow."""
    logging.info(f"\n[STEP] Checking retry status: {combined.retry_count}/{combined.max_retries}")
    await ctx.send_message(combined)


@executor(id="retry_generation")
async def retry_generation(combined: CombinedValidationResult, ctx: WorkflowContext[AgentExecutorRequest]) -> None:
    """Retry task generation after a failure."""
    logging.info(f"\n[STEP] 🔄 Retrying generation: attempt {combined.retry_count + 1}/{combined.max_retries}")
    
    task_id = combined.test.task_id
    target_topic = combined.target_topic
    concept_description = combined.concept_description
    difficulty = combined.difficulty
    objective = combined.objective
    
    if not target_topic or not concept_description:
        raise ValueError(
            f"Missing task metadata in CombinedValidationResult. "
            f"target_topic='{target_topic}', concept_description='{concept_description}'. "
            f"This indicates the metadata was not properly passed through the workflow."
        )
    
    await ctx.set_shared_state("task_id", task_id)
    await ctx.set_shared_state("target_topic", target_topic)
    await ctx.set_shared_state("concept_description", concept_description)
    await ctx.set_shared_state("difficulty", difficulty)
    await ctx.set_shared_state("objective", objective)
    
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


@executor(id="complete_workflow")
async def complete_workflow(combined: CombinedValidationResult, ctx: WorkflowContext[Never, str]) -> None:
    """Complete the workflow - either success or max retries reached."""
    logging.info("\n[STEP] 🏁 Completing workflow...")
    if combined.should_keep:
        await ctx.yield_output(f"🏁 Workflow complete: Task {combined.test.task_id} successfully generated")
    else:
        await ctx.yield_output(f"🏁 Workflow complete: Failed to generate valid task after {combined.retry_count} retries")
