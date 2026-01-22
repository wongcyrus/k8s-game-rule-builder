# MCP Filesystem Path Fix

## Problem
The MCP filesystem server was failing with `create_directory` errors because of a path mismatch:

- **MCP Server Scope**: `/home/developer/Documents/data-disk/k8s-game-rule/tests`
- **Agent Instructions**: Told agent to create `tests/game02/XXX_task_name/`
- **Result**: Agent tried to create `/tests/tests/game02/XXX_task_name/` (double `tests/`)

## Root Cause
The MCP filesystem server is initialized with a root directory (`PATHS.tests_root`). All paths passed to the MCP server must be **relative to this root**. The agent instructions incorrectly included the `tests/` prefix, causing the path to be duplicated.

## Solution Applied

### 1. Updated Agent Instructions (`agents/k8s_task_generator_agent.py`)
```python
# BEFORE (incorrect):
f"For each task, create directory tests/{PATHS.game_name}/XXX_descriptive_name/"

# AFTER (correct):
f"For each task, create directory {PATHS.game_name}/XXX_descriptive_name/"
```

Added clear documentation:
```python
"\n\n=== IMPORTANT: PATH STRUCTURE ===\n"
f"The filesystem tools are scoped to {PATHS.tests_root}.\n"
f"All paths you use must be RELATIVE to this root.\n"
f"To create a task, use path: {PATHS.game_name}/XXX_descriptive_name/ (NOT tests/{PATHS.game_name}/...)\n"
```

### 2. Updated Workflow Prompts (`workflow.py`)
Updated all three locations where task generation prompts are created:
- `main()` function initial prompt
- `retry_generation()` full workflow mode
- `retry_generation()` DevUI/manual mode

All now include:
```python
f"\n\nIMPORTANT: Create directory {PATHS.game_name}/{task_id}/ (NOT tests/{PATHS.game_name}/...)"
```

### 3. Updated Path Parsing (`workflow.py`)
Enhanced `parse_generated_task()` to handle both path formats:
```python
# Try multiple patterns since MCP server is scoped to tests/ root
task_id_match = re.search(rf'{PATHS.game_name}/(\d{{3}}_[a-z0-9_]+)', text)
if not task_id_match:
    task_id_match = re.search(rf'tests/{PATHS.game_name}/(\d{{3}}_[a-z0-9_]+)', text)
if not task_id_match:
    task_id_match = re.search(r'(\d{3}_[a-z0-9_]+)', text)
```

## Expected Behavior Now

When the agent receives a prompt to create task `287_ephemeral_containers_basic`:

1. **Agent creates**: `game02/287_ephemeral_containers_basic/`
2. **MCP server resolves to**: `/home/developer/Documents/data-disk/k8s-game-rule/tests/game02/287_ephemeral_containers_basic/`
3. **Result**: ✅ Correct path, no errors

## Testing
Run the workflow to verify:
```bash
python workflow.py
```

The MCP filesystem server should now successfully create directories and files without errors.
