"""Déroulé d'une réunion de l'Équipe Alpha.

Mode « reunion » : cadrage (orchestrateur) → tour de table → débat → synthèse.
Mode « direct »  : l'orchestrateur répond seul, plus rapide.

Chaque étape émet des événements (phase, agent_start, token, agent_end) que le
serveur relaie au téléphone en temps réel et enregistre dans la base.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Awaitable, Callable

from .config import Agent, Settings
from .llm import LLMClient

Emit = Callable[[dict], Awaitable[None]]

COMMON_RULES = """Règles communes à toute l'équipe :
- Réponds toujours en français, de façon concrète, chiffrée quand c'est possible, et actionnable.
- {length}
- Ne promets jamais de gains garantis.
- Refuse toute demande illégale, dangereuse ou contraire à l'éthique, et propose une alternative.
- Parle uniquement en ton nom : n'invente pas les répliques des autres experts.
- Favorise un MVP rapide et peu coûteux, puis une version long terme."""

PHASES = {
    "cadrage": "🎯 Cadrage",
    "tour_de_table": "🧠 Tour de table",
    "debat": "⚔️ Débat",
    "synthese": "✅ Synthèse et décision",
    "direct": "💬 Réponse directe",
}

# Taille max (caractères) d'une intervention recopiée dans le contexte des suivants.
TRANSCRIPT_CLIP = 1500
HISTORY_CLIP = 800


@dataclass
class Turn:
    agent: Agent
    phase: str
    text: str


def clip(text: str, limit: int) -> str:
    text = text.strip()
    return text if len(text) <= limit else text[:limit].rstrip() + " […]"


def parse_experts(text: str, experts: list[Agent], max_n: int) -> list[Agent]:
    """Lit la ligne « EXPERTS: id1, id2 » écrite par l'orchestrateur.
    Accepte les identifiants ou les noms, ignore ce qui est inconnu."""
    matches = re.findall(r"EXPERTS?\s*:\s*(.+)", text, flags=re.IGNORECASE)
    if not matches:
        return []
    chosen: list[Agent] = []
    for token in re.split(r"[,;/|]", matches[-1]):
        token = token.strip().strip("*`[]()").lower()
        if not token:
            continue
        for agent in experts:
            if agent in chosen:
                continue
            if token == agent.id or token == agent.name.lower() or agent.id in token \
                    or agent.name.lower() in token:
                chosen.append(agent)
                break
        if len(chosen) >= max_n:
            break
    return chosen


class Meeting:
    def __init__(self, settings: Settings, llm: LLMClient) -> None:
        self.s = settings
        self.llm = llm

    # ---------- construction des prompts ----------

    def _system(self, agent: Agent, max_words: int | None) -> str:
        length = (f"Sois bref : {max_words} mots maximum." if max_words
                  else "Sois complet mais va à l'essentiel.")
        return f"{agent.system}\n\n{COMMON_RULES.format(length=length)}"

    def _context(self, question: str, transcript: list[Turn], history: list[dict],
                 notes: str) -> str:
        parts: list[str] = []
        if notes.strip():
            parts.append("## Carnet de bord (mémoire permanente de l'utilisateur)\n"
                         + clip(notes, 3000))
        if history:
            lines = [f"- {h['who']} : {clip(h['content'], HISTORY_CLIP)}" for h in history]
            parts.append("## Échanges précédents de cette conversation\n" + "\n".join(lines))
        parts.append("## Demande actuelle de l'utilisateur\n" + question.strip())
        if transcript:
            lines = [f"**{t.agent.name}** ({PHASES[t.phase]}) : {clip(t.text, TRANSCRIPT_CLIP)}"
                     for t in transcript]
            parts.append("## Réunion en cours\n" + "\n\n".join(lines))
        return "\n\n".join(parts)

    async def _speak(self, agent: Agent, phase: str, task: str, context: str,
                     emit: Emit, max_words: int | None) -> str:
        await emit({"type": "agent_start", "agent": agent.id, "phase": phase})
        messages = [
            {"role": "system", "content": self._system(agent, max_words)},
            {"role": "user", "content": f"{context}\n\n## Ta tâche\n{task}"},
        ]
        parts: list[str] = []
        async for chunk in self.llm.stream_chat(self.s.model_for(agent), messages,
                                                self.s.temperature):
            parts.append(chunk)
            await emit({"type": "token", "agent": agent.id, "text": chunk})
        text = "".join(parts).strip()
        await emit({"type": "agent_end", "agent": agent.id, "phase": phase, "content": text})
        return text

    # ---------- déroulé ----------

    async def run(self, question: str, mode: str, history: list[dict], notes: str,
                  emit: Emit) -> None:
        if mode == "direct":
            await self._direct(question, history, notes, emit)
        else:
            await self._meeting(question, history, notes, emit)

    async def _direct(self, question: str, history: list[dict], notes: str,
                      emit: Emit) -> None:
        await emit({"type": "phase", "phase": "direct", "label": PHASES["direct"]})
        ctx = self._context(question, [], history, notes)
        await self._speak(self.s.coordinator, "direct",
                          "Réponds directement à l'utilisateur, de façon utile et concrète.",
                          ctx, emit, max_words=None)

    async def _meeting(self, question: str, history: list[dict], notes: str,
                       emit: Emit) -> None:
        coord = self.s.coordinator
        transcript: list[Turn] = []

        async def turn(agent: Agent, phase: str, task: str, max_words: int | None) -> str:
            ctx = self._context(question, transcript, history, notes)
            text = await self._speak(agent, phase, task, ctx, emit, max_words)
            transcript.append(Turn(agent, phase, text))
            return text

        # 1. Cadrage : reformulation + choix des experts
        await emit({"type": "phase", "phase": "cadrage", "label": PHASES["cadrage"]})
        roster = "\n".join(f"- {a.id} : {a.name} ({a.role})" for a in self.s.experts)
        framing = await turn(coord, "cadrage", (
            "Reformule clairement la demande et l'objectif en 2 à 3 phrases. "
            "Signale au plus 3 informations manquantes importantes, s'il y en a. "
            f"Puis choisis les {self.s.max_experts} experts les plus utiles parmi :\n{roster}\n"
            "Termine OBLIGATOIREMENT par une dernière ligne au format exact :\n"
            "EXPERTS: id1, id2, id3"
        ), max_words=self.s.max_words)

        experts = parse_experts(framing, self.s.experts, self.s.max_experts)
        if not experts:
            experts = [a for i in self.s.default_experts if (a := self.s.expert(i))]
            experts = experts[: self.s.max_experts] or self.s.experts[: self.s.max_experts]
        await emit({"type": "experts", "agents": [a.id for a in experts]})

        # 2. Tour de table
        await emit({"type": "phase", "phase": "tour_de_table", "label": PHASES["tour_de_table"]})
        for agent in experts:
            await turn(agent, "tour_de_table", (
                "Donne ton analyse d'expert : idées, recommandations concrètes et alertes "
                "dans ton domaine. Appuie-toi sur ce qui a déjà été dit sans le répéter."
            ), max_words=self.s.max_words)

        # 3. Débat
        for r in range(self.s.debate_rounds):
            label = PHASES["debat"] + (f" (tour {r + 1})" if self.s.debate_rounds > 1 else "")
            await emit({"type": "phase", "phase": "debat", "label": label})
            for agent in experts:
                await turn(agent, "debat", (
                    "Phase de débat : challenge les propositions des autres experts. "
                    "Cite l'expert visé, signale le risque ou l'objection principale, "
                    "propose une alternative et dis sur quoi tu es d'accord."
                ), max_words=max(80, self.s.max_words // 2))

        # 4. Synthèse et décision
        await emit({"type": "phase", "phase": "synthese", "label": PHASES["synthese"]})
        await turn(coord, "synthese", (
            "Arbitre le débat et rédige la réponse finale à l'utilisateur, avec ces sections :\n"
            "✅ Décision\n🗺️ Plan d'action (étapes, délais, budget, outils)\n"
            "📦 Livrables concrets\n📈 KPIs\n⚠️ Risques et parades\n"
            "➡️ Prochaines étapes immédiates (ce que l'utilisateur fait maintenant)"
        ), max_words=self.s.max_words * 3)
