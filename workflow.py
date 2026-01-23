"""Workflow for K8s task generation with validation and testing.

This workflow uses Agent Framework's WorkflowBuilder with conditional logic:
1. Generate task files (generator agent)
2. Validate task structure (validator agent with structured output)
3. Run pytest tests (pytest agent)
4. Conditional: If validation AND tests pass -> keep task, else -> remove task

This is the main entry point. The workflow logic has been refactored into:
- workflow/models.py: Data models
- workflow/executors.py: Workflow executors
- workflow/selectors.py: Selection functions for routing
- workflow/builder.py: Workflow builder
- workflow/idea_generator.py: Task idea generation
- workflow/runner.py: Main workflow runner
"""
from workflow.runner import main

if __name__ == "__main__":
    main()
