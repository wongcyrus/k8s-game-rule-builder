# Project Summary

## K8s Game Rule Builder

AI-powered Kubernetes learning task generation with validation and testing workflows.

## Quick Commands

```bash
# Setup
bash setup.sh

# Run workflows
python main.py              # Sequential pipeline
python workflow.py          # Conditional workflow with validation
python visualize_workflow.py # Generate workflow visualization

# Launch DevUI
./launch_devui.sh          # Interactive web UI
# or
devui entities             # Direct command
```

## Documentation

| File | Purpose |
|------|---------|
| [README.md](README.md) | Quick start and overview |
| [WORKFLOW.md](WORKFLOW.md) | Workflow architecture and visualization |
| [entities/README.md](entities/README.md) | DevUI entities guide |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Technical deep dive |

## Project Structure

```
k8s-game-rule-builder/
├── agents/                 # AI agent modules
├── entities/              # DevUI entities
│   ├── k8s_task_workflow/
│   ├── k8s_validator_agent/
│   └── k8s_pytest_agent/
├── docs/                  # Documentation
├── main.py               # Sequential pipeline
├── workflow.py           # Conditional workflow
└── visualize_workflow.py # Visualization generator
```

## Key Features

- **AI-Powered Generation**: Azure OpenAI agents create K8s learning tasks
- **Conditional Workflow**: Validates and tests tasks, removes failures automatically
- **Interactive DevUI**: Web interface for agents and workflows
- **Visualization**: Mermaid, SVG, PNG, PDF workflow diagrams
- **MCP Integration**: Filesystem operations via Model Context Protocol

## Agents

1. **Generator** - Creates complete K8s tasks
2. **Validator** - Validates structure and syntax
3. **PyTest** - Runs test suites

## Workflows

### Sequential (main.py)
```
Idea → Generate → Test
```

### Conditional (workflow.py)
```
Generate → Validate → Test → [Keep or Remove]
```

## DevUI Entities

- ✅ **k8s_validator_agent** - Validate tasks
- ✅ **k8s_pytest_agent** - Run tests
- ✅ **k8s_task_workflow** - Simplified workflow (validation + testing)
- ⚠️ **k8s_generator_agent** - Placeholder (use `python workflow.py`)

## Requirements

- Python 3.12+
- Azure OpenAI access
- Node.js (for MCP)
- kubectl (for K8s)
- DevUI: `pip install agent-framework[devui]`

## Status

✅ All systems operational
- Workflow tested and working
- DevUI entities loading correctly
- Documentation consolidated
- Visualization generating properly
