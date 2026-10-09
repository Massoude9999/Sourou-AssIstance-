"""Chargement de la configuration (config.yaml + variables d'environnement)."""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path

import yaml

ROOT_DIR = Path(__file__).resolve().parent.parent


@dataclass
class Agent:
    id: str
    name: str
    emoji: str
    color: str
    role: str
    system: str
    model: str | None = None

    def public(self) -> dict:
        """Infos affichables côté téléphone (sans le prompt système)."""
        return {
            "id": self.id,
            "name": self.name,
            "emoji": self.emoji,
            "color": self.color,
            "role": self.role,
            "model": self.model,
        }


@dataclass
class Settings:
    coordinator: Agent
    experts: list[Agent]
    ollama_url: str = "http://127.0.0.1:11434"
    default_model: str = "qwen2.5:7b"
    num_ctx: int = 8192
    temperature: float = 0.6
    think: bool | None = None
    max_experts: int = 3
    debate_rounds: int = 1
    max_words: int = 180
    history_messages: int = 6
    host: str = "0.0.0.0"
    port: int = 8000
    data_dir: Path = field(default_factory=lambda: ROOT_DIR / "data")
    default_experts: list[str] = field(default_factory=list)
    token: str = ""

    def model_for(self, agent: Agent) -> str:
        return agent.model or self.default_model

    def expert(self, agent_id: str) -> Agent | None:
        return next((a for a in self.experts if a.id == agent_id), None)

    @property
    def memory_file(self) -> Path:
        """Carnet de bord permanent, modifiable à la main ou depuis le téléphone."""
        return self.data_dir / "carnet.md"


def _agent(raw: dict) -> Agent:
    return Agent(
        id=str(raw["id"]),
        name=str(raw.get("name", raw["id"])),
        emoji=str(raw.get("emoji", "🤖")),
        color=str(raw.get("color", "#6366f1")),
        role=str(raw.get("role", "")),
        system=str(raw.get("system", "")).strip(),
        model=raw.get("model"),
    )


def _load_token(data_dir: Path) -> str:
    """Jeton d'accès : variable ALPHA_TOKEN, sinon data/token.txt (créé au besoin)."""
    env = os.environ.get("ALPHA_TOKEN", "").strip()
    if env:
        return env
    path = data_dir / "token.txt"
    if path.exists():
        return path.read_text().strip()
    token = secrets.token_urlsafe(24)
    path.write_text(token + "\n")
    path.chmod(0o600)
    return token


def load_settings(path: str | Path | None = None) -> Settings:
    path = Path(path or os.environ.get("ALPHA_CONFIG") or ROOT_DIR / "config.yaml")
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}

    data_dir = Path(os.environ.get("ALPHA_DATA_DIR") or raw.get("data_dir", "data"))
    if not data_dir.is_absolute():
        data_dir = ROOT_DIR / data_dir
    data_dir.mkdir(parents=True, exist_ok=True)

    experts = [_agent(e) for e in raw.get("experts", [])]
    if not experts:
        raise ValueError("config.yaml doit définir au moins un expert")

    return Settings(
        coordinator=_agent(raw["coordinator"]),
        experts=experts,
        ollama_url=os.environ.get("OLLAMA_URL") or raw.get("ollama_url", "http://127.0.0.1:11434"),
        default_model=os.environ.get("ALPHA_MODEL") or raw.get("default_model", "qwen2.5:7b"),
        num_ctx=int(raw.get("num_ctx", 8192)),
        temperature=float(raw.get("temperature", 0.6)),
        think=raw.get("think"),
        max_experts=int(raw.get("max_experts", 3)),
        debate_rounds=int(raw.get("debate_rounds", 1)),
        max_words=int(raw.get("max_words", 180)),
        history_messages=int(raw.get("history_messages", 6)),
        host=os.environ.get("ALPHA_HOST") or raw.get("host", "0.0.0.0"),
        port=int(os.environ.get("ALPHA_PORT") or raw.get("port", 8000)),
        data_dir=data_dir,
        default_experts=list(raw.get("default_experts", [])),
        token=_load_token(data_dir),
    )
