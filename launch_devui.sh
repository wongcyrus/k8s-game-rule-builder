#!/bin/bash
# Launch DevUI with entity discovery

# Activate virtual environment
source .venv/bin/activate

# Launch DevUI
echo "🚀 Launching DevUI..."
echo "📂 Discovering entities in ./entities"
echo "🌐 Open browser to http://localhost:8000"
echo ""

devui entities --reload

# Alternative with custom port:
# devui entities --port 9000 --reload
