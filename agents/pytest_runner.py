"""PyTest runner - pure Python test execution without LLM.

Runs pytest commands and returns structured results based on exit codes.
No LLM needed - just deterministic command execution.
"""
import json
import logging
import subprocess
import re
from typing import Any
from .config import PATHS

logging.basicConfig(level=logging.INFO)


def _result(is_valid: bool, reason: str, details: list[Any] | None = None) -> dict[str, Any]:
    return {"is_valid": is_valid, "reason": reason, "details": details or []}


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
    
    # Add -s flag to show print statements if not already present
    if '-s' not in command and '--capture=no' not in command:
        # Insert -s after pytest command
        command = command.replace('pytest ', 'pytest -s ', 1)
        logging.info(f"Added -s flag to show print statements: {command}")
    
    cmd_list = command.split()
    result = subprocess.run(
        cmd_list,
        capture_output=True,
        text=True,
        check=False,  # Don't raise exception, check exit code manually
        cwd=test_project_path,
    )
    
    combined_output = result.stdout + "\n" + result.stderr
    
    # Save test output directly in the task folder as test_result.txt
    # Extract task directory from command
    import re
    task_match = re.search(r'(tests/[^/]+/[^/]+)/', command)
    if task_match:
        task_dir = PATHS.pytest_rootdir / task_match.group(1)
        test_result_file = task_dir / "test_result.txt"
        try:
            with open(test_result_file, 'w') as f:
                f.write(combined_output)
            logging.info(f"💾 Saved test output to: {test_result_file}")
        except Exception as e:
            logging.warning(f"Failed to save test output: {e}")
    
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
