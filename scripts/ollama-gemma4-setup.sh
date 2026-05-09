#!/bin/bash
# Permanent Gemma4 setup on port 11435
# Run once to pull the model into the isolated cache

set -e

export OLLAMA_HOST=localhost:11435
export OLLAMA_MODELS="$HOME/.ollama-gemma"

echo "Pulling gemma4 into ~/.ollama-gemma (port 11435)..."
ollama pull gemma4

echo "Done. Gemma4 is available at http://localhost:11435"
echo "Logs: ~/.ollama-gemma/gemma4.log"
