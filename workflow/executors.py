"""Workflow executors for K8s task generation."""
import logging
import re
import shutil
from typing_extensions import Never

from agent_framework import (
    AgentExecutorRequest,
    AgentExecutorResponse,
    Message,
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

_MISSING = object()  # sentinel for get_state fallback detection


@executor(id="initialize_retry")
async def initialize_retry(message: str | AgentExecutorRequest | InitialWorkflowState, ctx: WorkflowContext[AgentExecutorRequest]) -> None:
    """Initialize or re-initialize shared state before generation."""
    logging.info("\n[STEP] Initializing/Re-initializing workflow state...")
    
    if isinstance(message, InitialWorkflowState):
        logging.info("First run - initializing shared state from InitialWorkflowState")
        ctx.set_state("task_id", message.task_id)
        ctx.set_state("target_topic", message.target_topic)
        ctx.set_state("concept_description", message.concept_description)
        ctx.set_state("difficulty", message.difficulty)
        ctx.set_state("objective", message.objective)
        ctx.set_state("retry_count", message.retry_count)
        ctx.set_state("max_retries", message.max_retries)
        logging.info(f"Set state: task_id={message.task_id}, topic={message.target_topic}")
        
        # Pre-create the task directory so the agent can write files immediately
        task_dir = PATHS.game_root / message.task_id
        task_dir.mkdir(parents=True, exist_ok=True)
        logging.info(f"Pre-created task directory: {task_dir}")
        
        request = AgentExecutorRequest(
            messages=[Message(role="user", contents=[message.prompt])],
            should_respond=True
        )
    else:
        task_id = ctx.get_state("task_id", _MISSING)
        target_topic = ctx.get_state("target_topic", _MISSING)
        if task_id is _MISSING or target_topic is _MISSING:
            raise KeyError(f"Missing required shared state: task_id={task_id}, target_topic={target_topic}")
        logging.info(f"Retry: State found: task_id={task_id}, topic={target_topic}")
        
        # Ensure directory exists on retries too
        task_dir = PATHS.game_root / task_id
        task_dir.mkdir(parents=True, exist_ok=True)
        
        if isinstance(message, str):
            request = AgentExecutorRequest(
                messages=[Message(role="user", contents=[message])],
                should_respond=True
            )
        else:
            request = message
    
    await ctx.send_message(request)


@executor(id="parse_generated_task")
async def parse_generated_task(response: AgentExecutorResponse, ctx: WorkflowContext[TaskInfo]) -> None:
    """Parse task generation response and extract task info."""
    logging.info("\n[STEP] Parsing generated task...")
    
    if ctx.get_state("retry_count", _MISSING) is _MISSING:
        ctx.set_state("retry_count", 0)
    
    if ctx.get_state("max_retries", _MISSING) is _MISSING:
        ctx.set_state("max_retries", 3)
    
    task_id = ctx.get_state("task_id", _MISSING)
    if task_id is _MISSING:
        text = response.agent_response.text
        # Try absolute path first, then relative, then bare ID
        task_id_match = re.search(rf'{re.escape(str(PATHS.game_root))}/(\d{{3}}_[a-z0-9_]+)', text)
        if not task_id_match:
            task_id_match = re.search(rf'{PATHS.game_name}/(\d{{3}}_[a-z0-9_]+)', text)
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
    
    ctx.set_state(f"validation_{validation.task_id}", validation)
    
    task_with_val = TaskWithValidation(
        task_id=validation.task_id,
        task_directory=validation.task_directory,
        validation=validation
    )
    
    await ctx.send_message(task_with_val)


@executor(id="run_pytest")
async def run_pytest(task_with_val: TaskWithValidation, ctx: WorkflowContext[TestResult]) -> None:
    """Run pytest directly without LLM - it's just command execution."""
    
    from agents.pytest_runner import run_pytest_command
    
    pytest_command = f"pytest --import-mode=importlib --rootdir=. {task_with_val.task_directory}/"
    result = run_pytest_command(pytest_command)
    
    raw_output = ""
    if result.get("details") and len(result["details"]) > 0:
        raw_output = result["details"][0]
        ctx.set_state(f"raw_output_{task_with_val.task_id}", raw_output)
        logging.debug(f"Saved raw output ({len(raw_output)} chars) for {task_with_val.task_id}")
    else:
        logging.warning(f"No raw output captured for {task_with_val.task_id}")

    test_result = TestResult(
        is_valid=result["is_valid"],
        reason=result["reason"],
        task_id=task_with_val.task_id,
        task_directory=task_with_val.task_directory,
        raw_output=raw_output
    )
    
    await ctx.send_message(test_result)


@executor(id="make_decision")
async def make_decision(test_result: TestResult, ctx: WorkflowContext[CombinedValidationResult]) -> None:
    """Make keep/remove decision based on validation and test results."""
    logging.info("\n[STEP] Making decision...")
    
    logging.info(f"Decision for {test_result.task_id}: valid={test_result.is_valid}, reason={test_result.reason}")
    
    validation = ctx.get_state(f"validation_{test_result.task_id}", _MISSING)
    if validation is _MISSING:
        validation = ValidationResult(
            is_valid=True,
            reason="Validation passed (assumed)",
            task_id=test_result.task_id,
            task_directory=test_result.task_directory
        )
    
    retry_count = ctx.get_state("retry_count", _MISSING)
    if retry_count is _MISSING:
        retry_count = 0
    
    max_retries = ctx.get_state("max_retries", _MISSING)
    if max_retries is _MISSING:
        max_retries = 3
    
    target_topic = ctx.get_state("target_topic", "")
    concept_description = ctx.get_state("concept_description", "")
    difficulty = ctx.get_state("difficulty", "")
    objective = ctx.get_state("objective", "")
    
    if target_topic:
        logging.info(f"Task context: topic={target_topic}, difficulty={difficulty}")
    
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
    """Record task failure - task stays in game folder for retry attempts."""
    logging.info(f"\n[STEP] ❌ Task failed: {combined.test.task_id}")
    reasons = []
    if not combined.validation.is_valid:
        reasons.append(f"Validation failed: {combined.validation.reason}")
    if not combined.test.is_valid:
        reasons.append(f"Tests failed: {combined.test.reason}")
    
    # Increment retry count
    retry_count = combined.retry_count + 1
    ctx.set_state("retry_count", retry_count)
    
    # Store failure info in shared state for potential final move
    ctx.set_state(f"failure_reasons_{combined.test.task_id}", reasons)
    
    await ctx.yield_output(
        f"❌ Task {combined.test.task_id} failed checks (attempt {combined.retry_count + 1}/{combined.max_retries}). Reasons: {'; '.join(reasons)}"
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
    
    ctx.set_state("task_id", task_id)
    ctx.set_state("target_topic", target_topic)
    ctx.set_state("concept_description", concept_description)
    ctx.set_state("difficulty", difficulty)
    ctx.set_state("objective", objective)
    
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
        f"\n\n✅ Directory already exists: {PATHS.game_root}/{task_id}/"
        f"\nWrite all files directly into this directory. Do NOT call create_directory."
        f"\n\nTask Details:"
        f"\n- Concept: {target_topic}"
        f"\n- Description: {concept_description}"
        f"\n- Difficulty: {difficulty}"
        f"\n- Objective: {objective}"
        f"\n\nCreate ALL required files including __init__.py, instruction.md, concept.md, session.json, "
        f"setup.template.yaml, answer.template.yaml, and all test files (test_01_setup.py, "
        f"test_02_ready.py, test_03_answer.py, test_05_check.py, test_06_cleanup.py). "
        f"Include test_04_challenge.py only if the task requires pre-validation actions like load generation. "
        f"test_02_ready.py must test that resources from setup.template.yaml are ready. "
        f"Use proper Jinja template variables and follow all established patterns. "
        f"Make sure all files are syntactically correct and tests will pass."
    )
    
    await ctx.send_message(
        AgentExecutorRequest(
            messages=[Message(role="user", contents=[generation_prompt])],
            should_respond=True
        )
    )


@executor(id="fix_task")
async def fix_task(combined: CombinedValidationResult, ctx: WorkflowContext[AgentExecutorRequest]) -> None:
    """Fix the failed task instead of regenerating from scratch."""
    logging.info(f"\n[STEP] 🔧 Fixing failed task: {combined.test.task_id} (attempt {combined.retry_count + 1}/{combined.max_retries})")
    
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
    
    ctx.set_state("task_id", task_id)
    ctx.set_state("target_topic", target_topic)
    ctx.set_state("concept_description", concept_description)
    ctx.set_state("difficulty", difficulty)
    ctx.set_state("objective", objective)
    
    failure_reasons = []
    if not combined.validation.is_valid:
        failure_reasons.append(f"Validation: {combined.validation.reason}")
    if not combined.test.is_valid:
        failure_reasons.append(f"Tests: {combined.test.reason}")
    
    # Get raw test output if available
    raw_test_output = ""
    val = ctx.get_state(f"raw_output_{task_id}", _MISSING)
    if val is not _MISSING:
        raw_test_output = val
    elif combined.test.raw_output:
        raw_test_output = combined.test.raw_output
    
    if not raw_test_output:
        logging.warning(f"No raw test output available for {task_id}")
    
    fix_prompt = (
        f"Fix the failed Kubernetes task '{task_id}' located in '{PATHS.game_root}/{task_id}/'."
        f"\n\nThis is fix attempt {combined.retry_count + 1} of {combined.max_retries}."
        f"\n\n⚠️  TASK FAILED WITH THESE ERRORS:"
        f"\n{chr(10).join([f'  - {reason}' for reason in failure_reasons])}"
    )
    
    if raw_test_output:
        fix_prompt += (
            f"\n\n📋 FULL TEST OUTPUT:"
            f"\n```\n{raw_test_output}\n```"
        )
    
    fix_prompt += (
        f"\n\n🔍 YOUR TASK:"
        f"\n1. READ all files from '{PATHS.game_root}/{task_id}/' to understand the task"
        f"\n2. READ session.json to see available variables"
        f"\n3. READ setup.template.yaml to see what resources are deployed"
        f"\n4. READ answer.template.yaml to understand the solution"
        f"\n5. ANALYZE the specific errors and identify which files are broken"
        f"\n6. Make TARGETED FIXES to ONLY the broken files"
        f"\n7. WRITE ONLY the fixed files back to '{PATHS.game_root}/{task_id}/'"
        f"\n\n⚠️  CRITICAL: DO NOT rewrite all files! Only fix the broken ones!"
        f"\n\n⚠️  FILE WRITING RULES:"
        f"\n- Use ABSOLUTE paths for all file operations — e.g. {PATHS.game_root}/{task_id}/file.py"
        f"\n- Task stays in '{PATHS.game_root}/{task_id}/' during retry attempts"
        f"\n- Read files from '{PATHS.game_root}/{task_id}/'"
        f"\n- Identify which specific files are broken from error messages"
        f"\n- Write ONLY the fixed files back to '{PATHS.game_root}/{task_id}/'"
        f"\n- DO NOT write files that are working correctly"
        f"\n- Example: If only test_02_ready.py is broken, write only test_02_ready.py"
        f"\n- Example: If test_02_ready.py and session.json are broken, write only those 2 files"
        f"\n\n📝 Required Files (for reference - only fix what's broken):"
        f"\n  1. __init__.py (empty file)"
        f"\n  2. instruction.md (challenge description)"
        f"\n  3. concept.md (learning material - NO solution code)"
        f"\n  4. session.json (plain JSON with variables)"
        f"\n  5. setup.template.yaml (Jinja template)"
        f"\n  6. answer.template.yaml (Jinja template)"
        f"\n  7. test_01_setup.py (deploy setup)"
        f"\n  8. test_02_ready.py (wait for resources)"
        f"\n  9. test_03_answer.py (deploy answer)"
        f"\n  10. test_05_check.py (validate solution)"
        f"\n  11. test_06_cleanup.py (cleanup)"
        f"\n  12. test_04_challenge.py (optional - only if needed)"
        f"\n- If a file is missing → create it"
        f"\n- If a file is broken → fix and write only that file"
        f"\n- If a file is working → DO NOT write it"
        f"\n\n📝 Task Context:"
        f"\n- Task ID: {task_id}"
        f"\n- Concept: {target_topic}"
        f"\n- Description: {concept_description}"
        f"\n- Difficulty: {difficulty}"
        f"\n- Objective: {objective}"
        f"\n\n✅ QUALITY CHECKLIST:"
        f"\n- Fix ONLY the broken parts, preserve working code"
        f"\n- Write ONLY the files you fixed"
        f"\n- session.json must be plain JSON (NOT Jinja template)"
        f"\n- YAML templates must use proper Jinja2 syntax: {{{{ variable }}}}"
        f"\n- test_02_ready.py must check resources from setup.template.yaml (NOT answer.template.yaml!)"
        f"\n  → DEBUGGING: Read session.json + setup.template.yaml to find correct variable names"
        f"\n  → DON'T just increase timeout - fix the root cause (wrong resource, wrong variable, wrong file)"
        f"\n  → Test flow: test_01_setup.py deploys setup → test_02_ready.py waits for setup resources"
        f"\n  → Then: test_03_answer.py deploys answer → test_05_check.py validates answer resources"
        f"\n- All tests must use try/except and .get() for safe JSON access"
        f"\n- Ensure proper Python indentation and syntax"
        f"\n- Ensure proper YAML indentation (2 spaces)"
    )
    
    await ctx.send_message(
        AgentExecutorRequest(
            messages=[Message(role="user", contents=[fix_prompt])],
            should_respond=True
        )
    )


@executor(id="run_pytest_skip_answer")
async def run_pytest_skip_answer(combined: CombinedValidationResult, ctx: WorkflowContext[CombinedValidationResult]) -> None:
    """Run pytest with SKIP_ANSWER_TESTS=True to validate test_05_check.py fails."""
    logging.info(f"\n[STEP] Running pytest with SKIP_ANSWER_TESTS=True for: {combined.test.task_id}")
    
    from agents.pytest_runner import run_pytest_command
    import os
    
    # Set environment variable
    original_env = os.environ.get("SKIP_ANSWER_TESTS")
    os.environ["SKIP_ANSWER_TESTS"] = "True"
    
    try:
        pytest_command = f"pytest --import-mode=importlib --rootdir=. {combined.test.task_directory}/"
        result = run_pytest_command(pytest_command)
        
        # Parse the output to check if test_05_check.py failed
        raw_output = result.get("details", [""])[0] if result.get("details") else ""
        
        # Check if test_05_check.py failed (which is expected)
        test_05_failed = "test_05_check.py" in raw_output and ("FAILED" in raw_output or "failed" in raw_output.lower())
        
        # Check if test_03_answer.py was skipped (which is expected)
        test_03_skipped = "test_03_answer.py" in raw_output and ("SKIPPED" in raw_output or "skipped" in raw_output.lower())
        
        logging.info(f"test_03_answer.py skipped: {test_03_skipped}")
        logging.info(f"test_05_check.py failed: {test_05_failed}")
        
        # Validation passes if test_05_check.py failed (as expected when answer is not deployed)
        if test_05_failed:
            logging.info("✅ Validation passed: test_05_check.py failed as expected when answer is skipped")
            await ctx.send_message(combined)
        else:
            logging.error("❌ Validation failed: test_05_check.py should fail when SKIP_ANSWER_TESTS=True")
            
            # Create new test result with failure
            new_test_result = TestResult(
                is_valid=False,
                reason="test_05_check.py did not fail when answer was skipped (SKIP_ANSWER_TESTS=True)",
                task_id=combined.test.task_id,
                task_directory=combined.test.task_directory,
                raw_output=raw_output
            )
            
            # Increment retry count
            retry_count = combined.retry_count + 1
            ctx.set_state("retry_count", retry_count)
            
            # Store failure info
            failure_reasons = [f"Skip answer test validation failed: {new_test_result.reason}"]
            ctx.set_state(f"failure_reasons_{combined.test.task_id}", failure_reasons)
            
            updated_combined = CombinedValidationResult(
                validation=combined.validation,
                test=new_test_result,
                retry_count=retry_count,
                max_retries=combined.max_retries,
                target_topic=combined.target_topic,
                concept_description=combined.concept_description,
                difficulty=combined.difficulty,
                objective=combined.objective,
            )
            
            await ctx.send_message(updated_combined)
    
    finally:
        # Restore original environment variable
        if original_env is None:
            os.environ.pop("SKIP_ANSWER_TESTS", None)
        else:
            os.environ["SKIP_ANSWER_TESTS"] = original_env


@executor(id="complete_workflow")
async def complete_workflow(combined: CombinedValidationResult, ctx: WorkflowContext[Never, str]) -> None:
    """Complete the workflow - either success or max retries reached."""
    logging.info("\n[STEP] 🏁 Completing workflow...")
    if combined.should_keep:
        await ctx.yield_output(f"🏁 Workflow complete: Task {combined.test.task_id} successfully generated")
    else:
        # Move task to unsuccessful folder only after all retries exhausted
        logging.info(f"\n[STEP] ❌ Moving task to unsuccessful folder after {combined.retry_count} failed attempts: {combined.test.task_id}")
        
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
            
            # Get failure reasons from shared state
            reasons = ctx.get_state(f"failure_reasons_{combined.test.task_id}", _MISSING)
            if reasons is _MISSING:
                reasons = []
                if not combined.validation.is_valid:
                    reasons.append(f"Validation failed: {combined.validation.reason}")
                if not combined.test.is_valid:
                    reasons.append(f"Tests failed: {combined.test.reason}")
            
            failure_report_path = unsuccessful_task_path / "FAILURE_REPORT.txt"
            
            # Get raw test output if available
            raw_test_output = ""
            val = ctx.get_state(f"raw_output_{combined.test.task_id}", _MISSING)
            if val is not _MISSING:
                raw_test_output = val
            elif combined.test.raw_output:
                raw_test_output = combined.test.raw_output
            
            # Read session.json if it exists
            session_json_content = ""
            session_json_path = unsuccessful_task_path / "session.json"
            if session_json_path.exists():
                try:
                    with open(session_json_path, 'r') as sf:
                        session_json_content = sf.read()
                    logging.info(f"✅ Read session.json: {len(session_json_content)} chars")
                except Exception as e:
                    logging.warning(f"⚠️  Could not read session.json: {e}")
            
            with open(failure_report_path, 'w') as f:
                f.write(f"Task ID: {combined.test.task_id}\n")
                f.write(f"Total Retry Attempts: {combined.retry_count}\n")
                f.write(f"Final Failure Reasons:\n")
                for reason in reasons:
                    f.write(f"  - {reason}\n")
                f.write(f"\nValidation Details:\n")
                f.write(f"  Valid: {combined.validation.is_valid}\n")
                f.write(f"  Reason: {combined.validation.reason}\n")
                f.write(f"\nTest Details:\n")
                f.write(f"  Valid: {combined.test.is_valid}\n")
                f.write(f"  Reason: {combined.test.reason}\n")
                
                # Add session.json content
                if session_json_content:
                    f.write(f"\n{'='*80}\n")
                    f.write(f"SESSION.JSON CONTENT:\n")
                    f.write(f"{'='*80}\n")
                    f.write(session_json_content)
                    f.write(f"\n{'='*80}\n")
                
                # Add raw test output
                if raw_test_output:
                    f.write(f"\n{'='*80}\n")
                    f.write(f"FULL TEST OUTPUT:\n")
                    f.write(f"{'='*80}\n")
                    f.write(raw_test_output)
                    f.write(f"\n{'='*80}\n")
                else:
                    f.write(f"\n{'='*80}\n")
                    f.write(f"Full test output saved in: test_result.txt\n")
                    f.write(f"{'='*80}\n")
            
            logging.info(f"Saved failure report to: {failure_report_path}")
        
        await ctx.yield_output(f"🏁 Workflow complete: Failed to generate valid task after {combined.retry_count} retries. Task moved to unsuccessful folder.")
