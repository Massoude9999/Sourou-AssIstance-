"""Exécution des réunions en tâche de fond.

La réunion continue sur le Mac mini même si le téléphone se met en veille :
le téléphone peut se reconnecter et reprendre le flux là où il s'était arrêté
(paramètre `since`). Une seule réunion tourne à la fois pour ne pas saturer la
mémoire du Mac ; les suivantes attendent leur tour.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import AsyncIterator

from .config import Settings
from .llm import LLMClient
from .meeting import Meeting
from .storage import Storage

log = logging.getLogger("alpha")
KEEP_FINISHED_RUNS = 20


class Run:
    def __init__(self, conversation_id: str) -> None:
        self.id = uuid.uuid4().hex[:12]
        self.conversation_id = conversation_id
        self.events: list[dict] = []
        self.done = False
        self._cond = asyncio.Condition()

    async def add(self, event: dict) -> None:
        async with self._cond:
            event["seq"] = len(self.events)
            self.events.append(event)
            self._cond.notify_all()

    async def finish(self) -> None:
        async with self._cond:
            self.done = True
            self._cond.notify_all()

    async def follow(self, since: int = 0) -> AsyncIterator[dict]:
        i = max(0, since)
        while True:
            async with self._cond:
                while i >= len(self.events) and not self.done:
                    await self._cond.wait()
                batch = self.events[i:]
                i = len(self.events)
                finished = self.done
            for event in batch:
                yield event
            if finished and i >= len(self.events):
                return


class RunManager:
    def __init__(self, settings: Settings, llm: LLMClient, storage: Storage) -> None:
        self.s = settings
        self.storage = storage
        self.meeting = Meeting(settings, llm)
        self.runs: dict[str, Run] = {}
        self._gpu = asyncio.Lock()
        self._tasks: set[asyncio.Task] = set()

    def get(self, run_id: str) -> Run | None:
        return self.runs.get(run_id)

    def active_for(self, conv_id: str) -> Run | None:
        return next((r for r in self.runs.values()
                     if r.conversation_id == conv_id and not r.done), None)

    def start(self, conv_id: str, text: str, mode: str) -> Run:
        run = Run(conv_id)
        self.runs[run.id] = run
        self._prune()
        task = asyncio.create_task(self._execute(run, text, mode))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return run

    def _prune(self) -> None:
        finished = [rid for rid, r in self.runs.items() if r.done]
        for rid in finished[:-KEEP_FINISHED_RUNS]:
            del self.runs[rid]

    def _notes(self) -> str:
        path = self.s.memory_file
        return path.read_text(encoding="utf-8") if path.exists() else ""

    async def _execute(self, run: Run, text: str, mode: str) -> None:
        conv_id = run.conversation_id
        history = self.storage.history(conv_id, self.s.history_messages, self.s.coordinator.id)
        self.storage.add_message(conv_id, "user", text, mode=mode)

        async def emit(event: dict) -> None:
            if event["type"] == "agent_end":
                self.storage.add_message(conv_id, "agent", event["content"],
                                         agent_id=event["agent"], phase=event["phase"],
                                         mode=mode)
            await run.add(event)

        try:
            if self._gpu.locked():
                await run.add({"type": "queued"})
            async with self._gpu:
                await self.meeting.run(text, mode, history, self._notes(), emit)
            await run.add({"type": "done"})
        except Exception as exc:  # noqa: BLE001 - l'erreur est montrée sur le téléphone
            log.exception("Réunion %s en échec", run.id)
            await run.add({"type": "error", "message": str(exc)})
        finally:
            await run.finish()
