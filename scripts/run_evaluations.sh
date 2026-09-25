#!/bin/bash



# Ensure we're running from the project root
cd "$(dirname "$0")/.."

# Activate virtual environment if it exists
if [ -d ".venv" ]; then
    source .venv/bin/activate
fi

python main.py "$@"
