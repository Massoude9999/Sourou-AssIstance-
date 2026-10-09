"""Historique des conversations (SQLite, fichier data/alpha.db)."""

from __future__ import annotations

import sqlite3
import threading
import time
import uuid
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role TEXT NOT NULL,            -- 'user' ou 'agent'
    agent_id TEXT,
    phase TEXT,
    mode TEXT,
    content TEXT NOT NULL,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_conv ON messages(conversation_id, id);
"""


class Storage:
    def __init__(self, path: Path) -> None:
        self._lock = threading.Lock()
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA foreign_keys = ON")
        self._db.executescript(SCHEMA)

    def create_conversation(self, title: str = "Nouvelle réunion") -> dict:
        now = time.time()
        conv = {"id": uuid.uuid4().hex[:12], "title": title, "created_at": now, "updated_at": now}
        with self._lock, self._db:
            self._db.execute(
                "INSERT INTO conversations VALUES (:id, :title, :created_at, :updated_at)", conv)
        return conv

    def get_conversation(self, conv_id: str) -> dict | None:
        with self._lock:
            row = self._db.execute("SELECT * FROM conversations WHERE id = ?",
                                   (conv_id,)).fetchone()
        return dict(row) if row else None

    def list_conversations(self) -> list[dict]:
        with self._lock:
            rows = self._db.execute(
                "SELECT * FROM conversations ORDER BY updated_at DESC").fetchall()
        return [dict(r) for r in rows]

    def delete_conversation(self, conv_id: str) -> None:
        with self._lock, self._db:
            self._db.execute("DELETE FROM conversations WHERE id = ?", (conv_id,))

    def add_message(self, conv_id: str, role: str, content: str, agent_id: str | None = None,
                    phase: str | None = None, mode: str | None = None) -> None:
        now = time.time()
        with self._lock, self._db:
            self._db.execute(
                "INSERT INTO messages (conversation_id, role, agent_id, phase, mode, content,"
                " created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (conv_id, role, agent_id, phase, mode, content, now))
            # La première question donne son titre à la conversation.
            if role == "user":
                self._db.execute(
                    "UPDATE conversations SET title = ? WHERE id = ? AND title = ?",
                    (content.strip().splitlines()[0][:60] or "Réunion", conv_id,
                     "Nouvelle réunion"))
            self._db.execute("UPDATE conversations SET updated_at = ? WHERE id = ?",
                             (now, conv_id))

    def messages(self, conv_id: str) -> list[dict]:
        with self._lock:
            rows = self._db.execute(
                "SELECT role, agent_id, phase, mode, content, created_at FROM messages"
                " WHERE conversation_id = ? ORDER BY id", (conv_id,)).fetchall()
        return [dict(r) for r in rows]

    def history(self, conv_id: str, limit: int, coordinator_id: str) -> list[dict]:
        """Résumé des échanges passés : questions de l'utilisateur et décisions
        finales de l'orchestrateur (pas tout le débat, pour économiser le contexte)."""
        with self._lock:
            rows = self._db.execute(
                "SELECT role, agent_id, content FROM messages WHERE conversation_id = ?"
                " AND (role = 'user' OR (agent_id = ? AND phase IN ('synthese', 'direct')))"
                " ORDER BY id DESC LIMIT ?", (conv_id, coordinator_id, limit)).fetchall()
        return [{"who": "Utilisateur" if r["role"] == "user" else "Décision de l'équipe",
                 "content": r["content"]} for r in reversed(rows)]
