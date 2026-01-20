# K8s Game Rule Builder

A Python project with Jupyter Notebook support for building game rules.

## Setup

### Quick Start

Run the setup script to create a virtual environment and install dependencies:

```bash
bash setup.sh
```

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

### Agent Logic Documentation

See [docs/agent_logic.md](docs/agent_logic.md) for a detailed explanation of the Kubernetes task generator agent, its required file outputs, and how validation tests are structured.

### Activate Virtual Environment

```bash
source .venv/bin/activate
```

### Start Jupyter Notebook

```bash
jupyter notebook
```

### Start JupyterLab

```bash
jupyter lab
```

### Deactivate Virtual Environment

```bash
deactivate
```

## Project Structure

```
k8s-game-rule-builder/
├── .venv/              # Virtual environment (created by setup.sh)
├── .gitignore          # Git ignore file
├── setup.sh            # Setup script
├── requirements.txt    # Python dependencies
└── README.md           # This file
```

## Dependencies

See [requirements.txt](requirements.txt) for the full list of dependencies.
