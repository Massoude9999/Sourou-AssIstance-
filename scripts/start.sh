#!/usr/bin/env bash
# Lancement manuel (sans service launchd). Ajoute --fake pour tester sans Ollama.
set -euo pipefail
cd "$(dirname "$0")/.."
[ "${1:-}" = "--fake" ] && export ALPHA_FAKE_LLM=1
exec .venv/bin/python -m alpha_team
