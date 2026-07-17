# K8s Task Generation Workflow

This package contains the refactored workflow for generating Kubernetes learning tasks with validation and testing.

## Structure

```
workflow/
├── __init__.py          # Package exports
├── models.py            # Data models (Pydantic & dataclasses)
├── executors.py         # Workflow executors (step implementations)
├── selectors.py         # Selection functions for conditional routing
├── builder.py           # Workflow builder
├── runner.py            # Main workflow runner
└── README.md            # This file

unit_tests/
└── test_workflow_*.py   # Builder workflow unit tests
```

## Components

### models.py
Contains all data models used throughout the workflow:
- `ValidationResult`: Validation results from task validator
- `TestResult`: Test results from pytest runner
- `CombinedValidationResult`: Combined validation + test results with retry logic
- `TaskInfo`: Basic task information
- `TaskWithValidation`: Task info with validation results
- `InitialWorkflowState`: Initial state for workflow execution

### executors.py
Contains all workflow executors (steps):
- `initialize_retry`: Initialize/re-initialize workflow state
- `parse_generated_task`: Parse task generation response
- `run_validation`: Run validation checks
- `run_pytest`: Run pytest tests
- `make_decision`: Make keep/remove decision
- `keep_task`: Keep successful task and continue to skip-answer validation
- `remove_task`: Record failure and increment retry count
- `run_pytest_skip_answer`: Validate `test_05_check.py` fails when answer is skipped
- `check_loop`: Check if should retry with fixer or complete
- `fix_task`: Build targeted fix prompt with failure context
- `complete_workflow`: Complete workflow or move to unsuccessful folder after max retries

### selectors.py
Contains selection functions for conditional routing:
- `select_action`: Choose between keep_task and remove_task
- `select_skip_answer_action`: Choose between check_loop and complete_workflow
- `select_loop_action`: Choose between fix_task and complete_workflow

### builder.py
Contains the workflow builder:
- `build_workflow`: Builds the complete workflow graph

### runner.py
Contains the main workflow runner:
- `run_workflow`: Main async function that orchestrates the entire workflow
- `main`: Entry point

## Related Components

### workflow/idea_generator.py
Contains task idea generation logic:
- `generate_task_idea`: Generate unique task ideas using the idea agent

## Workflow Flow

```
initialize_retry
    ↓
generator_agent
    ↓
parse_generated_task
    ↓
run_validation
    ↓
run_pytest
    ↓
make_decision
    ↓
[keep_task OR remove_task]
    ↓
[run_pytest_skip_answer OR check_loop]
    ↓
[fix_task OR complete_workflow]
    ↓
(fix_task routes to fixer_agent, then back to parse_generated_task)
```

## Usage

Run the workflow from the project root:

```bash
python workflow.py
```

Run builder unit tests:

```bash
pytest
```

Or import and use programmatically:

```python
from workflow.runner import run_workflow
import asyncio

asyncio.run(run_workflow())
```

## Key Features

- **Retry Logic**: Automatically retries failed tasks up to max_retries (default: 3)
- **Validation**: Validates task structure and file syntax
- **Testing**: Runs pytest tests to ensure task correctness
- **Conditional Routing**: Uses selection functions for dynamic workflow paths
- **State Management**: Uses shared state to pass data between executors
- **Failure Tracking**: Moves failed tasks to unsuccessful folder with detailed reports
- **Skip-Answer Validation**: Verifies `test_05_check.py` fails when `SKIP_ANSWER_TESTS=True`
