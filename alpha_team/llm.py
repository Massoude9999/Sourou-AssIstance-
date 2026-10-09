"""Clients LLM : Ollama (local) et un faux client pour les tests / la démo."""

from __future__ import annotations

import asyncio
import json
from typing import AsyncIterator, Protocol

import httpx


class LLMError(RuntimeError):
    pass


class LLMClient(Protocol):
    def stream_chat(
        self, model: str, messages: list[dict], temperature: float
    ) -> AsyncIterator[str]: ...

    async def health(self) -> dict: ...


class ThinkFilter:
    """Masque les blocs <think>...</think> des modèles « qui réfléchissent »,
    même quand les balises arrivent découpées entre plusieurs morceaux du flux."""

    OPEN, CLOSE = "<think>", "</think>"

    def __init__(self) -> None:
        self.buf = ""
        self.inside = False

    def feed(self, text: str) -> str:
        self.buf += text
        out: list[str] = []
        while True:
            tag = self.CLOSE if self.inside else self.OPEN
            i = self.buf.find(tag)
            if i >= 0:
                if not self.inside:
                    out.append(self.buf[:i])
                self.buf = self.buf[i + len(tag):]
                self.inside = not self.inside
                continue
            # Garde en réserve un début de balise éventuel en fin de tampon.
            keep = self._partial_suffix(self.buf, tag)
            if not self.inside:
                out.append(self.buf[: len(self.buf) - keep])
            self.buf = self.buf[len(self.buf) - keep:]
            return "".join(out)

    def flush(self) -> str:
        out = "" if self.inside else self.buf
        self.buf = ""
        return out

    @staticmethod
    def _partial_suffix(s: str, tag: str) -> int:
        for k in range(min(len(tag) - 1, len(s)), 0, -1):
            if s.endswith(tag[:k]):
                return k
        return 0


class OllamaClient:
    def __init__(self, base_url: str, num_ctx: int = 8192, think: bool | None = None,
                 timeout: float = 600.0, keep_alive: str = "30m") -> None:
        self.base_url = base_url.rstrip("/")
        self.num_ctx = num_ctx
        self.keep_alive = keep_alive
        self.think = think
        self.timeout = timeout

    async def stream_chat(self, model: str, messages: list[dict],
                          temperature: float) -> AsyncIterator[str]:
        payload: dict = {
            "model": model,
            "messages": messages,
            "stream": True,
            "keep_alive": self.keep_alive,
            "options": {"num_ctx": self.num_ctx, "temperature": temperature},
        }
        if self.think is not None:
            payload["think"] = self.think

        timeout = httpx.Timeout(self.timeout, connect=10.0)
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                async with client.stream("POST", f"{self.base_url}/api/chat", json=payload) as r:
                    if r.status_code != 200:
                        body = (await r.aread()).decode(errors="replace")
                        raise LLMError(f"Ollama {r.status_code} : {body[:300]}")
                    filt = ThinkFilter()
                    async for line in r.aiter_lines():
                        if not line.strip():
                            continue
                        data = json.loads(line)
                        if "error" in data:
                            raise LLMError(f"Ollama : {data['error']}")
                        chunk = filt.feed(data.get("message", {}).get("content", ""))
                        if chunk:
                            yield chunk
                        if data.get("done"):
                            break
                    tail = filt.flush()
                    if tail:
                        yield tail
        except httpx.ConnectError as exc:
            raise LLMError(
                f"Impossible de joindre Ollama sur {self.base_url}. "
                "Lance-le avec : brew services start ollama"
            ) from exc

    async def health(self) -> dict:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                r = await client.get(f"{self.base_url}/api/tags")
                r.raise_for_status()
                models = [m["name"] for m in r.json().get("models", [])]
                return {"ok": True, "models": models}
        except Exception as exc:  # noqa: BLE001 - on remonte l'erreur à l'UI
            return {"ok": False, "error": str(exc), "models": []}


class FakeClient:
    """Réponses simulées : pour tester l'interface sans Ollama (ALPHA_FAKE_LLM=1)."""

    def __init__(self, delay: float = 0.0) -> None:
        self.delay = delay
        self.calls: list[dict] = []

    async def stream_chat(self, model: str, messages: list[dict],
                          temperature: float) -> AsyncIterator[str]:
        self.calls.append({"model": model, "messages": messages})
        prompt = messages[-1]["content"]
        text = f"Réponse simulée ({model}). Point clé : tester vite et à petit coût."
        if "EXPERTS:" in prompt.split("## Ta tâche")[-1]:
            text += "\nEXPERTS: strategie, produit"
        for word in text.split(" "):
            if self.delay:
                await asyncio.sleep(self.delay)
            yield word + " "

    async def health(self) -> dict:
        return {"ok": True, "models": ["fake"]}
