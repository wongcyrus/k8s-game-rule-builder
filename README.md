# K8s Game Rule Builder

A Python project for building Kubernetes learning game rules using AI agents powered by the Model Context Protocol (MCP).

## Features

- **AI-Powered Task Generation**: Uses Azure OpenAI agents to generate Kubernetes learning tasks
- **MCP Integration**: Leverages the official [Model Context Protocol filesystem server](https://github.com/modelcontextprotocol/servers/tree/main/src/filesystem) for file operations
- **Automated Test Creation**: Generates complete test suites with setup, validation, and cleanup
- **Template-Based System**: Uses Jinja2 templates with dynamic variable substitution

## Setup

### Quick Start

Run the setup script to create a virtual environment and install dependencies:

```bash
bash setup.sh
```

The setup script will:
- Create a Python virtual environment
- Install all required dependencies including agent-framework
- Set up Jupyter kernel support

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

# Install IPython kernel
python -m ipykernel install --user --name=k8s-game-rule-builder
```

## Usage

### Running the Agents

The project includes several AI agents for different purposes:

```bash
# Activate virtual environment
source .venv/bin/activate

# Run the main agent pipeline
python main.py

# Run individual agents
python -m agents.filesystem_agent
python -m agents.k8s_task_generator_agent
python -m agents.k8s_task_idea_agent
```

### Agent Overview

- **FileSystem Agent**: Reads and writes files using the MCP filesystem server
- **Kubernetes Agent**: Interacts with Kubernetes clusters
- **PyTest Agent**: Runs and validates test suites
- **K8s Task Generator Agent**: Creates complete Kubernetes learning tasks
- **K8s Task Idea Agent**: Generates unique task ideas from Kubernetes documentation

### Agent Logic Documentation

See [docs/agent_logic.md](docs/agent_logic.md) for a detailed explanation of the Kubernetes task generator agent, its required file outputs, and how validation tests are structured.

### Jupyter Support

## Project Structure

```
k8s-game-rule-builder/
├── .venv/                  # Virtual environment (created by setup.sh)
├── agents/                 # AI agent modules
│   ├── __init__.py
│   ├── filesystem_agent.py         # MCP filesystem operations
│   ├── k8s_task_generator_agent.py # Task generation
│   ├── k8s_task_idea_agent.py      # Idea generation
│   ├── kubernetes_agent.py         # K8s cluster interaction
│   ├── pytest_agent.py             # Test execution
│   └── logging_middleware.py       # Agent logging
├── docs/                   # Documentation
│   └── agent_logic.md     # Agent architecture and logic
├── main.py                # Main entry point
├── setup.sh               # Setup script
├── requirements.txt       # Python dependencies
└── README.md              # This file
```

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
