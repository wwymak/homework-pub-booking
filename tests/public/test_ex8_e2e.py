"""Tests for the e2e pipeline runner and initial_utterance injection."""

from __future__ import annotations

import io

import pytest
from sovereign_agent.session.directory import create_session

from starter.voice_pipeline.manager_persona import ManagerTurn


class StubPersona:
    """Deterministic stub that echoes input. No LLM call."""

    def __init__(self) -> None:
        self.history: list[ManagerTurn] = []

    async def respond(self, utterance: str) -> str:
        r = f"(echo) {utterance}"
        self.history.append(ManagerTurn(user_utterance=utterance, manager_response=r))
        return r


@pytest.mark.asyncio
async def test_text_mode_initial_utterance_injected(tmp_path, monkeypatch) -> None:
    """When initial_utterance is set, turn 0 uses it instead of stdin."""
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    session = create_session(scenario="test", sessions_dir=sessions_dir)
    persona = StubPersona()

    # stdin has one follow-up, then EOF
    monkeypatch.setattr("sys.stdin", io.StringIO("follow up\n\n"))

    from starter.voice_pipeline.voice_loop import run_text_mode

    await run_text_mode(session, persona, max_turns=4, initial_utterance="Book Haymarket Tap for 6")

    # Turn 0 should be the injected utterance, not from stdin
    assert len(persona.history) >= 1
    assert persona.history[0].user_utterance == "Book Haymarket Tap for 6"

    # Turn 1 should be from stdin
    if len(persona.history) >= 2:
        assert persona.history[1].user_utterance == "follow up"

    # Trace should have both turns
    trace = session.trace_path.read_text(encoding="utf-8")
    assert "Book Haymarket Tap for 6" in trace
    assert "voice.utterance_in" in trace


@pytest.mark.asyncio
async def test_text_mode_without_initial_utterance_unchanged(tmp_path, monkeypatch) -> None:
    """Without initial_utterance, text mode still reads from stdin as before."""
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    session = create_session(scenario="test", sessions_dir=sessions_dir)
    persona = StubPersona()

    monkeypatch.setattr("sys.stdin", io.StringIO("hello\n\n"))

    from starter.voice_pipeline.voice_loop import run_text_mode

    await run_text_mode(session, persona, max_turns=4)

    assert len(persona.history) == 1
    assert persona.history[0].user_utterance == "hello"
