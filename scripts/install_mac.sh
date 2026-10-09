#!/usr/bin/env bash
# Installation de l'Équipe Alpha sur un Mac mini (Apple Silicon recommandé).
# Usage : ./scripts/install_mac.sh [modele]     ex. ./scripts/install_mac.sh qwen2.5:14b
set -euo pipefail

cd "$(dirname "$0")/.."
ROOT="$(pwd)"
MODEL="${1:-}"

say() { printf "\n\033[1;34m▶ %s\033[0m\n" "$*"; }

# 1. Homebrew
if ! command -v brew >/dev/null 2>&1; then
  say "Installation de Homebrew"
  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
  eval "$(/opt/homebrew/bin/brew shellenv)"
fi

# 2. Ollama (les modèles d'IA locaux)
if ! command -v ollama >/dev/null 2>&1; then
  say "Installation d'Ollama"
  brew install ollama
fi
say "Démarrage d'Ollama en service (relancé automatiquement au démarrage du Mac)"
brew services start ollama || true
for _ in $(seq 1 30); do curl -fsS http://127.0.0.1:11434/api/tags >/dev/null 2>&1 && break; sleep 1; done

# 3. Choix du modèle selon la RAM
if [ -z "$MODEL" ]; then
  RAM_GB=$(( $(sysctl -n hw.memsize) / 1073741824 ))
  if   [ "$RAM_GB" -ge 48 ]; then MODEL="qwen2.5:32b"
  elif [ "$RAM_GB" -ge 24 ]; then MODEL="qwen2.5:14b"
  else                            MODEL="qwen2.5:7b"
  fi
  say "RAM détectée : ${RAM_GB} Go → modèle choisi : $MODEL"
fi
say "Téléchargement du modèle $MODEL (peut prendre plusieurs minutes)"
ollama pull "$MODEL"
# Écrit le modèle choisi dans config.yaml
sed -i '' "s|^default_model:.*|default_model: \"$MODEL\"|" config.yaml

# 4. Python + dépendances
PY=python3
command -v "$PY" >/dev/null 2>&1 || { say "Installation de Python"; brew install python; }
say "Création de l'environnement Python"
"$PY" -m venv .venv
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -r requirements.txt

# 5. Jeton d'accès (créé au premier chargement de la config)
mkdir -p data
TOKEN=$(.venv/bin/python -c "from alpha_team.config import load_settings; print(load_settings().token)")

# 6. Démarrage automatique (launchd)
PLIST="$HOME/Library/LaunchAgents/com.equipe-alpha.server.plist"
say "Installation du service de démarrage automatique"
mkdir -p "$HOME/Library/LaunchAgents"
cat > "$PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.equipe-alpha.server</string>
  <key>ProgramArguments</key>
  <array>
    <string>$ROOT/.venv/bin/python</string><string>-m</string><string>alpha_team</string>
  </array>
  <key>WorkingDirectory</key><string>$ROOT</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>$ROOT/data/server.log</string>
  <key>StandardErrorPath</key><string>$ROOT/data/server.log</string>
</dict>
</plist>
PLIST
launchctl unload "$PLIST" 2>/dev/null || true
launchctl load "$PLIST"

# 7. Tailscale (accès sécurisé depuis le téléphone)
if [ ! -d "/Applications/Tailscale.app" ] && ! command -v tailscale >/dev/null 2>&1; then
  say "Installation de Tailscale"
  brew install --cask tailscale || true
fi

HOST=$(scutil --get LocalHostName 2>/dev/null || hostname -s)
cat <<MSG

✅ Équipe Alpha installée et démarrée.

  Sur ce Mac        : http://localhost:8000
  Jeton d'accès     : $TOKEN   (aussi dans data/token.txt)
  Journal           : data/server.log

📱 Pour y accéder depuis ton téléphone :
  1. Ouvre Tailscale sur ce Mac et connecte-toi (compte gratuit).
  2. Installe l'app Tailscale sur ton téléphone, même compte.
  3. Sur le téléphone, ouvre : http://$(echo "$HOST" | tr '[:upper:]' '[:lower:]'):8000
     (ou l'adresse 100.x.x.x du Mac affichée dans Tailscale)
  4. Colle le jeton, puis « Partager → Sur l'écran d'accueil ».

⚠️ N'ouvre jamais le port 8000 sur ta box internet : passe uniquement par Tailscale.
💤 Pense à empêcher la mise en veille : Réglages Système → Énergie →
   « Empêcher la suspension automatique lorsque l'écran est éteint ».
MSG
