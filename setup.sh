#!/bin/bash

# setup.sh - Setup Python virtual environment with Jupyter notebook support
# Usage: bash setup.sh

set -e  # Exit on error

echo "🚀 Setting up Python virtual environment..."

# Check if Python 3 is installed
if ! command -v python3 &> /dev/null; then
    echo "❌ Error: Python 3 is not installed. Please install Python 3 first."
    exit 1
fi

# Display Python version
PYTHON_VERSION=$(python3 --version)
echo "✓ Found $PYTHON_VERSION"

# Create virtual environment
if [ -d ".venv" ]; then
    echo "⚠️  .venv directory already exists. Do you want to recreate it? (y/n)"
    read -r response
    if [[ "$response" =~ ^[Yy]$ ]]; then
        echo "🗑️  Removing existing .venv..."
        rm -rf .venv
    else
        echo "ℹ️  Using existing .venv"
    fi
fi

if [ ! -d ".venv" ]; then
    echo "📦 Creating virtual environment..."
    python3 -m venv .venv
    echo "✓ Virtual environment created"
fi

# Activate virtual environment
echo "🔌 Activating virtual environment..."
source .venv/bin/activate

# Upgrade pip
echo "⬆️  Upgrading pip..."
pip install --upgrade pip

# Install Jupyter and common packages
echo "📚 Installing Jupyter and common packages..."
pip install jupyter jupyterlab notebook ipykernel

# Install the kernel
echo "🔧 Installing IPython kernel..."
python -m ipykernel install --user --name=k8s-game-rule-builder --display-name="Python (k8s-game-rule-builder)"

# Install requirements if requirements.txt exists
if [ -f "requirements.txt" ]; then
    echo "📋 Installing packages from requirements.txt..."
    pip install -r requirements.txt
else
    echo "ℹ️  No requirements.txt found, skipping..."
fi

echo ""
echo "✅ Setup complete!"
echo ""
echo "To activate the virtual environment, run:"
echo "  source .venv/bin/activate"
echo ""
