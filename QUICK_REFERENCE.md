# Quick Reference

## Commands

```bash
# Setup
bash setup.sh

# Run workflow (generates 1 task with retry)
python workflow.py

# Launch DevUI
./launch_devui.sh

# Generate visualization
python visualize_workflow.py
```

## Configuration

```python
# In workflow.py main()
target_topic = "ConfigMaps and environment variables"
initial_state = {
    "target_topic": target_topic,
    "retry_count": 0,
    "max_retries": 3
}
```

## Workflow Logic

```
Generate → Validate → Test → Success?
  YES → Keep → Complete ✓
  NO  → Remove → Retry? (if < max_retries)
    YES → Loop back
    NO  → Complete ✗
```

## Key Files

| File | Purpose |
|------|---------|
| `workflow.py` | Main workflow implementation |
| `launch_devui_full.py` | DevUI launcher |
| `agents/k8s_task_generator_agent.py` | Task generator |
| `agents/k8s_task_validator.py` | Task validator (no LLM) |
| `agents/pytest_runner.py` | Test runner (no LLM) |

## Agents

1. **Generator** - Creates K8s tasks with MCP filesystem
2. **Validator** - Validates structure, YAML, Python, Jinja
3. **Pytest** - Runs test suites

## Executors

1. `parse_generated_task` - Extract task ID
2. `create_validation_request` - Request validation
3. `parse_validation_result` - Parse validation
4. `create_pytest_request` - Request tests
5. `parse_tests_and_decide` - Parse tests, decide
6. `keep_task` - Success path
7. `remove_task` - Failure path (increments retry)
8. `check_loop` - Check retry condition
9. `retry_generation` - Retry with fresh context
10. `complete_workflow` - End workflow

## Decision Points

### 1. Keep vs Remove
- **Logic**: `validation.is_valid AND test.is_valid`
- **Routes**: keep_task OR remove_task

### 2. Retry vs Complete
- **Logic**: `NOT success AND retry_count < max_retries`
- **Routes**: retry_generation OR complete_workflow

## Shared State

```python
{
    "target_topic": str,           # Topic to generate
    "retry_count": int,            # Current retry (0-based)
    "max_retries": int,            # Max retries allowed
    "validation_{task_id}": dict   # Validation results
}
```

## Success Criteria

Task is kept only if:
- ✅ Validation passes (all files, syntax correct)
- ✅ Tests pass (all pytest tests succeed)

## Termination

Workflow completes when:
- ✅ Task succeeds → Keep and complete
- ❌ Max retries reached → Complete without task

## Common Topics

```python
# Good (specific)
"ConfigMaps and environment variables"
"Persistent Volumes and Claims"
"Network Policies for pod isolation"
"Resource limits and requests"

# Bad (vague)
"Kubernetes basics"
"Advanced concepts"
```

## Retry Limits

| Complexity | max_retries |
|-----------|-------------|
| Simple | 2 |
| Medium | 3 (default) |
| Complex | 5 |

## Troubleshooting

### Tasks fail validation
- Check generator instructions
- Review validator rules
- Examine failed files

### Tests always fail
- Verify pytest config
- Check test helpers
- Review test patterns

### Tests marked as failed when they passed
- **Fixed in v2.0.1**
- Ensure you're running latest version
- Check CHANGELOG.md for details

### Duplicate IDs
- Verify existing_tasks list
- Check generator receives list
- Review ID extraction regex

### Max retries too low
- Increase max_retries
- Improve prompts
- Simplify topic

## Documentation

- [README.md](README.md) - Overview
- [WORKFLOW.md](WORKFLOW.md) - Architecture
- [CHANGELOG.md](CHANGELOG.md) - Changes
- [docs/RETRY_LOGIC.md](docs/RETRY_LOGIC.md) - Retry guide
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) - Technical details

## Version

Current: **v2.0.1** (Retry-based workflow with test parsing fix)
Previous: v2.0.0 (Retry-based workflow)
Previous: v1.0.0 (Multi-task generation)

See [CHANGELOG.md](CHANGELOG.md) for migration guide.
