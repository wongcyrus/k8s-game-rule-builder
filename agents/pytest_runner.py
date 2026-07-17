"""PyTest runner - pure Python test execution without LLM.

Runs pytest commands and returns structured results based on exit codes.
No LLM needed - just deterministic command execution.
"""
import json
import logging
import subprocess
import re
import shlex
import os
from typing import Any
from .config import PATHS


def _result(is_valid: bool, reason: str, details: list[Any] | None = None) -> dict[str, Any]:
    return {"is_valid": is_valid, "reason": reason, "details": details or []}


def _normalize_pytest_command(command: str) -> str:
    """Ensure pytest command includes '-s' unless capture is explicitly disabled another way."""
    tokens = shlex.split(command)
    if not tokens or tokens[0] != "pytest":
        return command

    if "-s" not in tokens and "--capture=no" not in tokens:
        tokens.insert(1, "-s")
    return shlex.join(tokens)


def _extract_task_dir(command: str) -> str | None:
    """Extract tests/<game>/<task> directory segment from pytest command."""
    match = re.search(r"(tests/[^/]+/[^/]+)/", command)
    if match:
        return match.group(1)
    return None


def _save_test_output(command: str, combined_output: str, skip_answer: bool) -> None:
    """Persist pytest output in the generated task directory."""
    task_dir_segment = _extract_task_dir(command)
    if task_dir_segment is None:
        return

    task_dir = PATHS.pytest_rootdir / task_dir_segment
    task_dir.mkdir(parents=True, exist_ok=True)

    filename = "no_answer_test_result.txt" if skip_answer else "test_result.txt"
    test_result_file = task_dir / filename
    with open(test_result_file, "w", encoding="utf-8") as f:
        f.write(combined_output)
    logging.info(f"💾 Saved test output to: {test_result_file}")


def run_pytest_command(command: str) -> dict[str, Any]:
    """Run the provided pytest command and return structured result.
    
    Args:
        command: The exact pytest command to run, e.g. 
                'pytest --import-mode=importlib --rootdir=. tests/game02/002_create_namespace/'
    
    Returns:
        Dict with 'is_valid' (bool), 'reason' (str), and 'details' (list)
    """
    test_project_path = str(PATHS.pytest_rootdir)
    logging.info(f"Running pytest command: {command}")
    logging.info(f"Working directory: {test_project_path}")
    
    # Check if SKIP_ANSWER_TESTS is set
    skip_answer = os.environ.get("SKIP_ANSWER_TESTS") == "True"
    
    try:
        normalized_command = _normalize_pytest_command(command)
    except ValueError as exc:
        return _result(False, f"Invalid pytest command: {exc}")
    if normalized_command != command:
        logging.info(f"Added -s flag to show print statements: {normalized_command}")

    try:
        cmd_list = shlex.split(normalized_command)
    except ValueError as exc:
        return _result(False, f"Invalid pytest command: {exc}")

    result = subprocess.run(
        cmd_list,
        capture_output=True,
        text=True,
        check=False,  # Don't raise exception, check exit code manually
        cwd=test_project_path,
    )
    
    combined_output = result.stdout + "\n" + result.stderr
    
    try:
        _save_test_output(normalized_command, combined_output, skip_answer)
    except OSError as exc:
        return _result(False, f"Failed to save test output: {exc}", details=[combined_output])
    
    # Pytest exit codes:
    # 0 = all tests passed
    # 1 = tests were collected and run but some failed
    # 2 = test execution was interrupted
    # 3 = internal error
    # 4 = pytest command line usage error
    # 5 = no tests collected
    
    if result.returncode == 0:
        logging.info(combined_output)
        return _result(True, "All tests passed", details=[combined_output])
    elif result.returncode == 5:
        logging.warning(combined_output)
        return _result(False, "No tests collected", details=[combined_output])
    else:
        logging.error(combined_output)
        return _result(False, f"Tests failed (exit code {result.returncode})", details=[combined_output])


def get_pytest_runner():
    """Get a pytest runner wrapper for backward compatibility.
    
    Returns a simple wrapper that calls run_pytest_command directly.
    No LLM needed - just runs pytest and checks exit codes.
    """
    class PytestWrapper:
        """Simple wrapper to maintain backward compatibility."""
        
        async def run(self, prompt: str) -> Any:
            """Extract pytest command from prompt and run it."""
            # Extract pytest command from prompt
            # Look for pytest command pattern
            match = re.search(r'pytest[^\n]*', prompt)
            if match:
                command = match.group(0).strip()
            else:
                # Fallback: assume the prompt is the command
                command = prompt.strip()
            
            logging.info(f"Running pytest: {command}")
            result = run_pytest_command(command)
            
            # Return a simple object with text attribute for compatibility
            class Result:
                def __init__(self, data):
                    self.text = json.dumps(data, indent=2)
                    self.data = data
            
            return Result(result)
    
    return PytestWrapper()


# Alias for backward compatibility
get_pytest_agent = get_pytest_runner


if __name__ == "__main__":
    def main():
        """Test pytest runner directly without LLM."""
        logging.info("\n=== Testing PyTest Runner (No LLM) ===")
        
        test_command = f"pytest --import-mode=importlib --rootdir=. tests/{PATHS.game_name}/002_create_namespace/"
        logging.info(f"Command: {test_command}")
        
        result = run_pytest_command(test_command)
        
        logging.info("\n=== PyTest Result ===")
        logging.info(json.dumps(result, indent=2))
        
        if result["is_valid"]:
            logging.info("\n✅ Tests PASSED")
        else:
            logging.info("\n❌ Tests FAILED")
            logging.info(f"Reason: {result['reason']}")
    
    main()
