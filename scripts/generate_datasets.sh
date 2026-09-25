#!/bin/bash

# Ensure we're running from the project root
cd "$(dirname "$0")/.."

# Activate virtual environment if it exists
if [ -d ".venv" ]; then
    source .venv/bin/activate
fi

# Go into dataset_construction
cd dataset_construction

echo "Generating datasets..."

# Find all python files that start with generate_ and execute them
for f in generate_*.py; do
    echo "Running $f"
    python "$f"
done

echo "Dataset generation complete!"
