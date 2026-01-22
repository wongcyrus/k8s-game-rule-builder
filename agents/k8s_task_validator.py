"""Kubernetes task validator - pure Python validation without LLM.

Provides functions to validate generated game tasks by checking required files,
YAML syntax, Python code parsing, and Jinja template syntax.

No LLM needed - just deterministic file validation.
"""
import ast
import json
import logging
import sys
import re
from pathlib import Path
from typing import Any

import yaml
from jinja2 import Environment, TemplateSyntaxError
from agents.config import VALIDATION

# Ensure the project root is on sys.path when executed directly
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(level=logging.INFO)

def _resolve_path(path_str: str) -> Path:
    """Resolve a path relative to the task root if not absolute."""
    path = Path(path_str)
    return path if path.is_absolute() else VALIDATION.base_task_root / path


def _load_text(path: Path) -> str:
    """Load file contents, raising FileNotFoundError if missing."""
    logging.info(f"Reading file: {path}")
    return path.read_text(encoding="utf-8")


def _sanitize_jinja_placeholders(text: str) -> str:
    """Replace Jinja expressions with placeholders to allow YAML parsing."""
    text = re.sub(r"{{[^}]+}}", "JINJA_VALUE", text)
    text = re.sub(r"{%-?[^%]+%-?}", "# JINJA_BLOCK", text)
    return text


def _result(is_valid: bool, reason: str, details: list[Any] | None = None) -> dict[str, Any]:
    """Standardize validation output structure."""
    return {"is_valid": is_valid, "reason": reason, "details": details or []}


def _validate_yaml(path: Path) -> str:
    """Validate YAML syntax for a file, supporting multi-document YAML, tolerating Jinja."""
    data = _load_text(path)
    sanitized = _sanitize_jinja_placeholders(data)
    list(yaml.safe_load_all(sanitized))
    return f"✅ YAML valid: {path}"


def _validate_python_ast(path: Path) -> str:
    """Validate Python code by parsing the AST to catch syntax errors."""
    source = _load_text(path)
    ast.parse(source, filename=str(path))
    return f"✅ Python syntax valid: {path}"


def _validate_jinja_template(path: Path) -> str:
    """Validate Jinja template syntax without rendering."""
    source = _load_text(path)
    env = Environment()
    env.parse(source)
    return f"✅ Template syntax valid: {path}"


def _validate_json(path: Path) -> str:
    """Validate JSON structure for session files."""
    data = _load_text(path)
    json.loads(data)
    return f"✅ JSON valid: {path}"


def _list_task_files(task_dir: Path) -> list[str]:
    """List files in the task directory (non-recursive)."""
    return sorted([p.name for p in task_dir.iterdir() if p.is_file()])


def check_required_files(task_dir: str) -> dict[str, Any]:
    """Check that the standard task files exist.
    
    Note: test_04_challenge.py is optional and not checked here.
    """
    resolved_dir = _resolve_path(task_dir)
    missing = [name for name in VALIDATION.required_files if not (resolved_dir / name).exists()]
    if missing:
        return _result(False, f"Missing files: {', '.join(missing)}", details=["Missing files"] + missing)
    return _result(True, f"All required files present in {resolved_dir}")


def validate_yaml_file(file_path: str) -> dict[str, Any]:
    """Validate YAML syntax for a single file."""
    path = _resolve_path(file_path)
    if not path.exists():
        return _result(False, f"File not found: {path}")
    try:
        _validate_yaml(path)
        return _result(True, f"YAML valid: {path}")
    except yaml.YAMLError as exc:
        return _result(False, f"YAML invalid in {path}: {exc}")


def validate_python_file(file_path: str) -> dict[str, Any]:
    """Validate Python syntax using AST parsing."""
    path = _resolve_path(file_path)
    if not path.exists():
        return _result(False, f"File not found: {path}")
    try:
        _validate_python_ast(path)
        return _result(True, f"Python syntax valid: {path}")
    except SyntaxError as exc:
        return _result(False, f"Python syntax error in {path}: {exc}")


def validate_template_file(file_path: str) -> dict[str, Any]:
    """Validate Jinja template syntax without rendering."""
    path = _resolve_path(file_path)
    if not path.exists():
        return _result(False, f"File not found: {path}")
    try:
        _validate_jinja_template(path)
        return _result(True, f"Template syntax valid: {path}")
    except TemplateSyntaxError as exc:
        return _result(False, f"Template syntax error in {path}: {exc}")


def validate_task_directory(task_dir: str) -> dict[str, Any]:
    """Validate required files, YAML, Python, templates, and JSON within a task directory.
    
    This is the main validation function - call this directly instead of using an LLM agent.
    """
    resolved_dir = _resolve_path(task_dir)
    if not resolved_dir.exists():
        return _result(False, f"Task directory not found: {resolved_dir}")

    results: list[dict[str, Any]] = []

    # List files first for transparency
    try:
        listed = _list_task_files(resolved_dir)
        results.append(_result(True, "Directory listing", details=listed))
    except Exception as exc:
        results.append(_result(False, f"Unable to list files in {resolved_dir}: {exc}"))

    # Required files check first
    results.append(check_required_files(task_dir))

    # Validate every file we find according to type
    try:
        for filename in listed:
            file_path = resolved_dir / filename
            if filename in VALIDATION.yaml_files:
                try:
                    results.append(validate_yaml_file(str(file_path)))
                    results.append(validate_template_file(str(file_path)))
                except Exception as exc:
                    results.append(_result(False, f"Validation failed for {file_path}: {exc}"))
            elif filename in VALIDATION.py_files:
                try:
                    results.append(validate_python_file(str(file_path)))
                except Exception as exc:
                    results.append(_result(False, f"Validation failed for {file_path}: {exc}"))
            elif filename in VALIDATION.json_files:
                if file_path.exists():
                    try:
                        results.append(_result(True, _validate_json(file_path)))
                    except Exception as exc:
                        results.append(_result(False, f"JSON validation failed for {file_path}: {exc}"))
            else:
                # Not a validated type; note it for transparency
                results.append(_result(True, f"Skipped non-validated file: {file_path}"))
    except Exception as exc:
        results.append(_result(False, f"Unexpected error during per-file validation: {exc}"))

    overall_valid = all(item.get("is_valid", False) for item in results)
    return _result(overall_valid, "Validation completed", details=results)


# Legacy function for backward compatibility
def get_k8s_task_validator():
    """Legacy function for backward compatibility.
    
    Returns a simple wrapper that calls validate_task_directory directly.
    No LLM needed - validation is deterministic.
    """
    class ValidatorWrapper:
        """Simple wrapper to maintain backward compatibility."""
        
        async def run(self, prompt: str) -> Any:
            """Extract task directory from prompt and validate."""
            # Extract task directory from prompt
            import re
            match = re.search(r'(\d{3}_[a-z0-9_]+)', prompt)
            if not match:
                # Try to find any path-like string
                match = re.search(r'tests/[^/]+/(\d{3}_[a-z0-9_]+)', prompt)
            
            if match:
                task_dir = match.group(1)
            else:
                # Fallback: assume the prompt contains the task directory
                task_dir = prompt.strip()
            
            logging.info(f"Validating task directory: {task_dir}")
            result = validate_task_directory(task_dir)
            
            # Return a simple object with text attribute for compatibility
            class Result:
                def __init__(self, data):
                    self.text = json.dumps(data, indent=2)
                    self.data = data
            
            return Result(result)
    
    return ValidatorWrapper()


# Alias for backward compatibility
get_k8s_task_validator_agent = get_k8s_task_validator


if __name__ == "__main__":
    def main():
        """Test validation directly without LLM."""
        sample_task = "642_workload_identity_federation"
        logging.info(f"\n=== Testing K8s Task Validator (No LLM) ===")
        logging.info(f"Validating: {sample_task}")
        
        result = validate_task_directory(sample_task)
        
        logging.info("\n=== Validation Result ===")
        logging.info(json.dumps(result, indent=2))
        
        if result["is_valid"]:
            logging.info("\n✅ Task validation PASSED")
        else:
            logging.info("\n❌ Task validation FAILED")
            logging.info(f"Reason: {result['reason']}")

    main()
