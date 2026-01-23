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

agents/
└── idea_generator.py    # Task idea generation logic (moved from workflow/)
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
- `keep_task`: Keep successful task
- `remove_task`: Move failed task to unsuccessful folder
- `check_loop`: Check if should retry
- `retry_generation`: Retry task generation
- `complete_workflow`: Complete workflow

### selectors.py
Contains selection functions for conditional routing:
- `select_action`: Choose between keep_task and remove_task
- `select_loop_action`: Choose between retry_generation and complete_workflow

### builder.py
Contains the workflow builder:
- `build_workflow`: Builds the complete workflow graph

### runner.py
Contains the main workflow runner:
- `run_workflow`: Main async function that orchestrates the entire workflow
- `main`: Entry point

## Related Components

### agents/idea_generator.py
Contains task idea generation logic (moved from workflow/):
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
check_loop
    ↓
[retry_generation OR complete_workflow]
    ↓
(retry loops back to initialize_retry)
```

## Usage

Run the workflow from the project root:

```bash
python workflow.py
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
