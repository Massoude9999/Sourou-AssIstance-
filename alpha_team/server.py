"""API web + interface mobile de l'Équipe Alpha."""

from __future__ import annotations

import json
import os
import secrets
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .config import Settings, load_settings
from .llm import FakeClient, LLMClient, OllamaClient
from .runs import RunManager
from .storage import Storage

STATIC_DIR = Path(__file__).parent / "static"


class NewConversation(BaseModel):
    title: str = "Nouvelle réunion"


class NewMessage(BaseModel):
    text: str = Field(min_length=1, max_length=8000)
    mode: str = Field(default="reunion", pattern="^(reunion|direct)$")


class Notes(BaseModel):
    content: str = Field(max_length=20000)


def create_app(settings: Settings | None = None, llm: LLMClient | None = None) -> FastAPI:
    settings = settings or load_settings()
    if llm is None:
        llm = (FakeClient(delay=0.03) if os.environ.get("ALPHA_FAKE_LLM")
               else OllamaClient(settings.ollama_url, settings.num_ctx, settings.think))
    storage = Storage(settings.data_dir / "alpha.db")
    runs = RunManager(settings, llm, storage)

    app = FastAPI(title="Équipe Alpha", docs_url=None, redoc_url=None)

    def auth(request: Request) -> None:
        header = request.headers.get("authorization", "")
        token = header.removeprefix("Bearer ").strip()
        if not secrets.compare_digest(token.encode(), settings.token.encode()):
            raise HTTPException(status_code=401, detail="Jeton invalide")

    def conversation_or_404(conv_id: str) -> dict:
        conv = storage.get_conversation(conv_id)
        if not conv:
            raise HTTPException(status_code=404, detail="Conversation introuvable")
        return conv

    # ---------- pages ----------

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    # ---------- API ----------

    @app.get("/api/health")
    async def health() -> dict:
        """Sans authentification : n'expose que l'état d'Ollama."""
        return {"server": True, "ollama": await llm.health(),
                "default_model": settings.default_model}

    @app.get("/api/agents", dependencies=[Depends(auth)])
    def agents() -> dict:
        return {
            "coordinator": settings.coordinator.public(),
            "experts": [a.public() for a in settings.experts],
            "default_model": settings.default_model,
        }

    @app.get("/api/conversations", dependencies=[Depends(auth)])
    def list_conversations() -> list[dict]:
        return storage.list_conversations()

    @app.post("/api/conversations", dependencies=[Depends(auth)])
    def create_conversation(body: NewConversation) -> dict:
        return storage.create_conversation(body.title)

    @app.get("/api/conversations/{conv_id}", dependencies=[Depends(auth)])
    def get_conversation(conv_id: str) -> dict:
        conv = conversation_or_404(conv_id)
        active = runs.active_for(conv_id)
        return {**conv, "messages": storage.messages(conv_id),
                "active_run": active.id if active else None}

    @app.delete("/api/conversations/{conv_id}", dependencies=[Depends(auth)])
    def delete_conversation(conv_id: str) -> dict:
        conversation_or_404(conv_id)
        if runs.active_for(conv_id):
            raise HTTPException(status_code=409, detail="Une réunion est en cours")
        storage.delete_conversation(conv_id)
        return {"ok": True}

    @app.post("/api/conversations/{conv_id}/messages", dependencies=[Depends(auth)])
    async def post_message(conv_id: str, body: NewMessage) -> dict:
        conversation_or_404(conv_id)
        if runs.active_for(conv_id):
            raise HTTPException(status_code=409, detail="Une réunion est déjà en cours ici")
        run = runs.start(conv_id, body.text, body.mode)
        return {"run_id": run.id}

    @app.get("/api/runs/{run_id}/stream", dependencies=[Depends(auth)])
    async def stream_run(run_id: str, since: int = 0) -> StreamingResponse:
        run = runs.get(run_id)
        if not run:
            raise HTTPException(status_code=404, detail="Réunion introuvable ou terminée")

        async def body():
            async for event in run.follow(since):
                yield json.dumps(event, ensure_ascii=False) + "\n"

        return StreamingResponse(body(), media_type="application/x-ndjson",
                                 headers={"Cache-Control": "no-cache",
                                          "X-Accel-Buffering": "no"})

    @app.get("/api/notes", dependencies=[Depends(auth)])
    def get_notes() -> dict:
        path = settings.memory_file
        return {"content": path.read_text(encoding="utf-8") if path.exists() else ""}

    @app.put("/api/notes", dependencies=[Depends(auth)])
    def put_notes(body: Notes) -> dict:
        settings.memory_file.write_text(body.content, encoding="utf-8")
        return {"ok": True}

    return app
