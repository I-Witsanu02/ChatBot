#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
ollama create UPH_ChatBot -f deployment/ollama/Modelfile.UPH_ChatBot.typhoon
