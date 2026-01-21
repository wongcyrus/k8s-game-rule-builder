# K8s Game Rule Builder

A Python project for building Kubernetes learning game rules using AI agents powered by Azure OpenAI and the Model Context Protocol (MCP).

## Features

- **AI-Powered Task Generation**: Uses Azure OpenAI agents to generate progressive Kubernetes learning tasks (Beginner → Intermediate → Advanced)
- **Intelligent Memory System**: Prevents duplicate content generation across sessions
- **MCP Integration**: Leverages the official [Model Context Protocol filesystem server](https://github.com/modelcontextprotocol/servers/tree/main/src/filesystem) for file operations  
- **Automated Test Creation**: Generates complete test suites with setup, validation, and cleanup
- **Template-Based System**: Uses Jinja2 templates with dynamic variable substitution
- **Comprehensive Logging**: Built-in middleware for debugging and monitoring

## Setup

### Quick Start

Run the setup script to create a virtual environment and install dependencies:

```bash
bash setup.sh
```

The setup script will:
- Create a Python virtual environment
- Install all required dependencies including agent-framework

**Note**: The MCP filesystem server is automatically managed via npx and doesn't require manual installation.

### Manual Setup

If you prefer to set up manually:

```bash
# Create virtual environment
python3 -m venv .venv

# Activate virtual environment
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

## Usage

### Running the Agents

The project includes several AI agents for different purposes:

```bash
# Activate virtual environment
source .venv/bin/activate

# Option 1: Launch DevUI (Interactive UI)
devui entities
# Open browser to http://localhost:8000

# Option 2: Run the main agent pipeline (sequential)
python main.py

# Option 3: Run the workflow (conditional with validation, single task)
python workflow.py

# Option 4: Run the workflow loop (multiple tasks with statistics)
python workflow_loop.py

# Generate workflow visualization
python visualize_workflow.py

# Run individual agents
python -m agents.filesystem_agent
python -m agents.k8s_task_generator_agent
python -m agents.k8s_task_idea_agent
```

### Agent Overview

The project includes several specialized AI agents that work together:

1. **K8s Task Idea Agent** - Generates unique Kubernetes concepts with progressive difficulty (Beginner/Intermediate/Advanced)
2. **K8s Task Generator Agent** - Creates complete task scaffolding with templates, tests, and validation
3. **K8s Task Validator Agent** - Validates task structure, YAML syntax, Python syntax, and Jinja templates
4. **PyTest Agent** - Runs and validates test suites
5. **Filesystem Agent** - Handles file operations via MCP filesystem server
6. **Kubernetes Agent** - Executes kubectl commands against K8s clusters

### Workflows

The project supports multiple execution modes:

1. **main.py** - Sequential pipeline (idea → generate → test)
2. **workflow.py** - Conditional workflow with validation (single task)
3. **workflow_loop.py** - Workflow loop for multiple tasks with statistics

See [WORKFLOW.md](WORKFLOW.md) for detailed workflow documentation including:
- Workflow architecture and visualization
- Conditional logic and decision making
- Structured output models
- Executor naming conventions

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for detailed technical documentation on agent logic, workflows, and system design.

## Project Structure

```
k8s-game-rule-builder/
├── .venv/                  # Virtual environment (created by setup.sh)
├── agents/                 # AI agent modules
│   ├── __init__.py
│   ├── filesystem_agent.py         # MCP filesystem operations
│   ├── k8s_task_generator_agent.py # Task generation
│   ├── k8s_task_idea_agent.py      # Idea generation with memory
│   ├── k8s_task_validator_agent.py # Task validation
│   ├── kubernetes_agent.py         # K8s cluster interaction
│   ├── pytest_agent.py             # Test execution
│   └── logging_middleware.py       # Agent logging
├── entities/               # DevUI entities (agents & workflows)
│   ├── .env               # Shared environment variables
│   ├── k8s_task_workflow/ # Complete workflow
│   ├── k8s_generator_agent/
│   ├── k8s_validator_agent/
│   └── k8s_pytest_agent/
├── docs/                   # Documentation
│   └── ARCHITECTURE.md    # Technical architecture & design
├── main.py                # Main entry point (sequential)
├── workflow.py            # Workflow entry point (conditional)
├── visualize_workflow.py  # Workflow visualization
├── setup.sh               # Setup script
├── requirements.txt       # Python dependencies
├── README.md              # This file
└── WORKFLOW.md            # Workflow documentation
```

## Quick Start

1. **Setup environment:**
   ```bash
   bash setup.sh
   ```

2. **Run the sequential pipeline:**
   ```bash
   source .venv/bin/activate
   python main.py
   ```

3. **Run the conditional workflow (single task):**
   ```bash
   source .venv/bin/activate
   python workflow.py
   ```

4. **Run the workflow loop (multiple tasks):**
   ```bash
   source .venv/bin/activate
   python workflow_loop.py
   ```

5. **Launch DevUI (Interactive UI):**
   ```bash
   source .venv/bin/activate
   devui entities
   # Open browser to http://localhost:8000
   ```

6. **Generate workflow visualization:**
   ```bash
   source .venv/bin/activate
   python visualize_workflow.py
   # Creates: workflow_graph.svg, workflow_graph.png, workflow_graph.pdf
   ```

7. **Generate task ideas:**
   ```bash
   python -m agents.k8s_task_idea_agent
   ```

## Documentation

- **README.md** (this file) - Quick start and overview
- **[WORKFLOW.md](WORKFLOW.md)** - Workflow documentation:
  - Conditional workflow architecture
  - Workflow visualization (Mermaid, SVG, PNG, PDF)
  - Structured output models
  - Executor naming conventions
- **[entities/README.md](entities/README.md)** - DevUI entities:
  - Quick start guide
  - Available entities
  - Usage examples
- **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)** - Technical documentation:
  - Agent architecture and workflows
  - Template system and validation patterns
  - MCP integration details
  - Memory management

## Requirements

- Python 3.x
- Azure OpenAI API access
- Node.js (for npx to run MCP server)
- kubectl (for Kubernetes interaction)
- DevUI (optional): `pip install agent-framework[devui]`

## License

See LICENSE file for details.

## MCP Integration

This project uses the [Model Context Protocol (MCP)](https://modelcontextprotocol.io/) to enable AI agents to interact with external tools:

- **MCP Filesystem Server**: Official [@modelcontextprotocol/server-filesystem](https://github.com/modelcontextprotocol/servers/tree/main/src/filesystem) package
- **Automatic Execution**: Launched via `npx` when agents start (no manual installation required)
- **Sandboxed Access**: File operations restricted to specified directories for security
- **Rich Capabilities**: Supports read/write files, directory operations, search, and more

### How It Works

1. Agents use `MCPStdioTool` to connect to the MCP server via stdio
2. The server is launched with `npx -y @modelcontextprotocol/server-filesystem [allowed_directories]`
3. Agents can then call filesystem tools within the allowed directories
4. Server automatically shuts down when the agent context closes

## Dependencies

See [requirements.txt](requirements.txt) for the full list of dependencies.
