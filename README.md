# 🧭 Équipe Alpha : ton équipe d'IA locales

Une équipe de 12 IA spécialisées (stratège, product manager, dev, designer, growth,
finance, juridique…) qui **se réunit, débat et tranche** pour t'aider à lancer des
projets et à gagner du temps.
Elle tourne **100 % en local sur ton Mac mini** (aucun abonnement IA, tes données restent
chez toi) et tu lui parles **depuis ton téléphone**, où que tu sois.

```
 📱 Téléphone ──(Tailscale, chiffré)──▶ 🖥️ Mac mini
                                         ├─ Serveur Équipe Alpha (FastAPI, port 8000)
                                         │    ├─ 🧭 Orchestrateur : cadre et choisit les experts
                                         │    ├─ 🧠 Tour de table : chaque expert donne son avis
                                         │    ├─ ⚔️ Débat : les experts se challengent
                                         │    └─ ✅ Synthèse : décision + plan d'action
                                         ├─ Ollama (modèles d'IA locaux)
                                         └─ data/ : historique (SQLite) + carnet de bord
```

## Fonctionnalités

- **Mode « Réunion d'équipe »** : l'orchestrateur reformule ta demande et choisit
  les 3 experts les plus utiles. Chacun donne son avis, puis ils débattent, et
  l'orchestrateur rend la décision (plan d'action, KPIs, risques, prochaines étapes).
- **Mode « Réponse rapide »** : l'orchestrateur répond seul, en quelques secondes.
- **Réponses en direct** : tu vois chaque expert écrire en temps réel.
- **Robuste sur mobile** : la réunion continue sur le Mac si ton téléphone se met en
  veille, et l'affichage reprend où il s'était arrêté.
- **Mémoire** : historique des conversations, plus un **carnet de bord** (objectifs,
  budget, contraintes) relu par l'équipe à chaque réunion.
- **Un modèle par expert, au choix** : par exemple un modèle de code pour le dev
  (`model:` dans `config.yaml`).
- **App installable** sur l'écran d'accueil (iPhone et Android), avec thème clair ou sombre.
- **Sécurisé** : accès par jeton et réseau privé Tailscale, sans aucun port ouvert sur internet.

## Installation sur le Mac mini (environ 15 minutes)

```bash
git clone https://github.com/Massoude9999/Sourou-AssIstance-.git
cd Sourou-AssIstance-
./scripts/install_mac.sh            # choisit le modèle selon ta RAM
# ou forcer un modèle : ./scripts/install_mac.sh qwen2.5:14b
```

Le script installe Homebrew, Ollama, le modèle d'IA, Python et Tailscale. Il crée le
jeton d'accès et lance le serveur **automatiquement à chaque démarrage du Mac**.

### Accès depuis le téléphone

1. Sur le Mac : ouvre **Tailscale** et connecte-toi (compte gratuit).
2. Sur le téléphone : installe l'app **Tailscale** et connecte-toi avec le même compte.
3. Ouvre `http://<nom-du-mac>:8000` ou l'adresse `100.x.x.x` du Mac affichée dans Tailscale.
4. Colle le **jeton** (affiché à la fin de l'installation, ou dans `data/token.txt`).
5. iPhone : *Partager → Sur l'écran d'accueil*. Android : *⋮ → Installer l'application*.

> ⚠️ N'ouvre **jamais** le port 8000 sur ta box : Tailscale suffit et reste privé.
> 💤 Empêche la mise en veille du Mac : *Réglages Système → Énergie*.

## Quel modèle pour mon Mac mini ?

| RAM du Mac mini | Modèle conseillé | Durée d'une réunion complète* |
|---|---|---|
| 8 Go  | `qwen2.5:3b` (qualité limitée) | environ 1 à 2 min |
| 16 Go | `qwen2.5:7b` | environ 2 à 4 min |
| 24-32 Go | `qwen2.5:14b` | environ 4 à 7 min |
| 48-64 Go | `qwen2.5:32b` | environ 8 à 12 min |

\*Ordre de grandeur pour 3 experts et 1 tour de débat (8 interventions) : à mesurer
sur ta machine. Pour aller plus vite, baisse `max_experts`, mets `debate_rounds: 0`
ou utilise le mode « Réponse rapide ».
Tu peux essayer d'autres modèles d'Ollama (`llama3.1:8b`, `mistral-small`, `qwen3`…) :
`ollama pull <modèle>`, puis modifie `default_model` dans `config.yaml`.

## Personnaliser l'équipe

Tout se règle dans [`config.yaml`](config.yaml) :
- modifier le prompt (`system`) ou le rôle d'un expert, en ajouter ou en retirer ;
- donner un modèle différent à un expert (`model: "qwen2.5-coder:7b"` pour le dev) ;
- régler le nombre d'experts par réunion, les tours de débat et la longueur des réponses.

Après une modification : `launchctl kickstart -k gui/$(id -u)/com.equipe-alpha.server`.

## Commandes utiles

```bash
./scripts/start.sh            # lancement manuel (si le service est arrêté)
./scripts/start.sh --fake     # tester l'interface sans Ollama (réponses simulées)
tail -f data/server.log       # journal du serveur
./scripts/uninstall_mac.sh    # retirer le démarrage automatique
```

## Développement

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt -r requirements-dev.txt
.venv/bin/python -m pytest -q
```

| Fichier | Rôle |
|---|---|
| `alpha_team/meeting.py` | Déroulé de la réunion : cadrage, tour de table, débat, synthèse |
| `alpha_team/llm.py` | Client Ollama en streaming (masque les balises `<think>`) et client simulé |
| `alpha_team/runs.py` | Réunions en tâche de fond, reprise du flux, file d'attente |
| `alpha_team/server.py` | API web + authentification par jeton |
| `alpha_team/storage.py` | Historique SQLite |
| `alpha_team/static/` | Application mobile (HTML/JS sans dépendance) |

## Feuille de route

- **V1 (cette version)** : réunion multi-agents, accès mobile, mémoire, carnet de bord.
- **V2** : 🎙️ messages vocaux (Whisper local), 🔔 notification de fin de réunion,
  export du plan d'action en Markdown/PDF.
- **V3** : outils pour les agents (recherche web, lecture de fichiers, exécution de code),
  automatisations (n8n), tâches et rappels planifiés.
