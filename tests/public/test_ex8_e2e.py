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


def test_format_booking_utterance_includes_all_fields() -> None:
    """format_booking_utterance should include venue, party, date, time, deposit."""
    from sovereign_agent.halves import HalfResult

    from starter.handoff_bridge.bridge import BridgeResult

    bridge_result = BridgeResult(
        outcome="completed",
        rounds=1,
        final_half_result=HalfResult(
            success=True,
            output={
                "committed": True,
                "booking": {
                    "venue_id": "haymarket_tap",
                    "date": "2026-04-25",
                    "time": "19:30",
                    "party_size": 6,
                    "deposit_gbp": 111,
                },
                "booking_reference": "BK-A1B2C3D4",
            },
            summary="confirmed",
            next_action="complete",
        ),
        summary="structured confirmed in round 1",
    )

    from starter.voice_pipeline.run_e2e import format_booking_utterance

    utterance = format_booking_utterance(bridge_result)

    assert "Haymarket Tap" in utterance or "haymarket_tap" in utterance.lower()
    assert "6" in utterance
    assert "2026-04-25" in utterance or "25" in utterance
    assert "19:30" in utterance
    assert "111" in utterance


def test_format_booking_utterance_handles_deposit_required_gbp_alias() -> None:
    """The bridge may pass deposit as deposit_required_gbp instead of deposit_gbp."""
    from sovereign_agent.halves import HalfResult

    from starter.handoff_bridge.bridge import BridgeResult

    bridge_result = BridgeResult(
        outcome="completed",
        rounds=1,
        final_half_result=HalfResult(
            success=True,
            output={
                "committed": True,
                "booking": {
                    "venue_id": "royal_oak",
                    "date": "2026-04-25",
                    "time": "19:30",
                    "party_size": 6,
                    "deposit_required_gbp": 200,
                },
                "booking_reference": "BK-XXXX",
            },
            summary="confirmed",
            next_action="complete",
        ),
        summary="confirmed",
    )

    from starter.voice_pipeline.run_e2e import format_booking_utterance

    utterance = format_booking_utterance(bridge_result)
    assert "200" in utterance
