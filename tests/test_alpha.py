"""Tests de l'Équipe Alpha, sans Ollama (client simulé)."""

import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from alpha_team.config import load_settings
from alpha_team.llm import FakeClient, ThinkFilter
from alpha_team.meeting import Meeting, parse_experts
from alpha_team.server import create_app


@pytest.fixture
def settings(tmp_path, monkeypatch):
    monkeypatch.setenv("ALPHA_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ALPHA_TOKEN", "secret-test")
    return load_settings()


# ---------- ThinkFilter ----------

def test_think_filter_hides_reasoning_split_across_chunks():
    f = ThinkFilter()
    chunks = ["Bon", "jour <thi", "nk>je réfléchis", "…</th", "ink> le monde"]
    out = "".join(f.feed(c) for c in chunks) + f.flush()
    assert out == "Bonjour  le monde"


def test_think_filter_passes_plain_text():
    f = ThinkFilter()
    assert f.feed("a < b et c <") + f.flush() == "a < b et c <"


# ---------- Choix des experts ----------

def test_parse_experts_by_id_and_name(settings):
    text = "Reformulation...\nEXPERTS: strategie, Growth & Vente, inconnu, dev"
    ids = [a.id for a in parse_experts(text, settings.experts, 3)]
    assert ids == ["strategie", "growth", "dev"]


def test_parse_experts_missing_line(settings):
    assert parse_experts("pas de liste", settings.experts, 3) == []


# ---------- Déroulé d'une réunion ----------

def test_meeting_runs_all_phases(settings):
    events = []

    async def emit(ev):
        events.append(ev)

    llm = FakeClient()
    asyncio.run(Meeting(settings, llm).run("Lancer un SaaS", "reunion", [], "Budget 200 €", emit))

    phases = [e["phase"] for e in events if e["type"] == "phase"]
    assert phases == ["cadrage", "tour_de_table", "debat", "synthese"]
    speakers = [(e["agent"], e["phase"]) for e in events if e["type"] == "agent_end"]
    assert speakers == [
        ("coordinateur", "cadrage"),
        ("strategie", "tour_de_table"), ("produit", "tour_de_table"),
        ("strategie", "debat"), ("produit", "debat"),
        ("coordinateur", "synthese"),
    ]
    # Le carnet de bord et la réunion en cours sont transmis aux experts suivants.
    last_prompt = llm.calls[-1]["messages"][-1]["content"]
    assert "Budget 200 €" in last_prompt
    assert "Stratège business" in last_prompt


def test_direct_mode_single_answer(settings):
    events = []

    async def emit(ev):
        events.append(ev)

    asyncio.run(Meeting(settings, FakeClient()).run("Question", "direct", [], "", emit))
    assert [e["agent"] for e in events if e["type"] == "agent_end"] == ["coordinateur"]


# ---------- API ----------

def read_stream(client, run_id, headers):
    with client.stream("GET", f"/api/runs/{run_id}/stream", headers=headers) as r:
        assert r.status_code == 200
        return [json.loads(line) for line in r.iter_lines() if line]


def test_api_requires_token(settings):
    with TestClient(create_app(settings, FakeClient())) as client:
        assert client.get("/api/conversations").status_code == 401
        bad = {"Authorization": "Bearer nope"}
        assert client.get("/api/conversations", headers=bad).status_code == 401
        assert client.get("/api/health").status_code == 200


def test_api_full_meeting_is_stored(settings):
    headers = {"Authorization": "Bearer secret-test"}
    with TestClient(create_app(settings, FakeClient())) as client:
        conv = client.post("/api/conversations", json={}, headers=headers).json()
        r = client.post(f"/api/conversations/{conv['id']}/messages",
                        json={"text": "Créer une app de devis", "mode": "reunion"},
                        headers=headers)
        assert r.status_code == 200
        events = read_stream(client, r.json()["run_id"], headers)
        assert events[-1]["type"] == "done"
        assert [e["seq"] for e in events] == list(range(len(events)))

        data = client.get(f"/api/conversations/{conv['id']}", headers=headers).json()
        assert data["title"] == "Créer une app de devis"
        assert data["active_run"] is None
        roles = [(m["role"], m["agent_id"]) for m in data["messages"]]
        assert roles[0] == ("user", None)
        assert roles[-1] == ("agent", "coordinateur")
        assert len(roles) == 7

        # Reprise du flux après coupure : on ne reçoit que la suite.
        with client.stream("GET", f"/api/runs/{r.json()['run_id']}/stream?since=5",
                           headers=headers) as resp:
            again = [json.loads(line) for line in resp.iter_lines() if line]
        assert again[0]["seq"] == 5


def test_api_notes_roundtrip(settings):
    headers = {"Authorization": "Bearer secret-test"}
    with TestClient(create_app(settings, FakeClient())) as client:
        assert client.put("/api/notes", json={"content": "Objectif : 1000 €/mois"},
                          headers=headers).status_code == 200
        assert client.get("/api/notes", headers=headers).json()["content"] == \
            "Objectif : 1000 €/mois"


def test_index_served(settings):
    with TestClient(create_app(settings, FakeClient())) as client:
        r = client.get("/")
        assert r.status_code == 200 and "Équipe Alpha" in r.text
