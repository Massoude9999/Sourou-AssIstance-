#!/usr/bin/env bash
# Arrête et retire le démarrage automatique (les données dans data/ sont conservées).
set -euo pipefail
PLIST="$HOME/Library/LaunchAgents/com.equipe-alpha.server.plist"
launchctl unload "$PLIST" 2>/dev/null || true
rm -f "$PLIST"
echo "Service Équipe Alpha retiré. Ollama reste installé (brew services stop ollama pour l'arrêter)."
