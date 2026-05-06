"""Tests for the e2e pipeline runner and initial_utterance injection."""

from __future__ import annotations

import io
import json

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


@pytest.mark.asyncio
async def test_e2e_scripted_bridge_completes_and_voice_trace_exists(tmp_path, monkeypatch) -> None:
    """Full e2e scripted pipeline: bridge confirms, then voice trace has events."""
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()

    # stdin for the manager conversation (after the injected first turn)
    monkeypatch.setattr("sys.stdin", io.StringIO("sounds good\n\n"))

    # Avoid needing a real NEBIUS_KEY by setting a fake one and
    # monkeypatching ManagerPersona.from_env to return a StubPersona.
    monkeypatch.setenv("NEBIUS_KEY", "fake-key-for-test")
    monkeypatch.setattr(
        "starter.voice_pipeline.run_e2e.ManagerPersona.from_env",
        staticmethod(lambda: StubPersona()),
    )

    from starter.voice_pipeline.run_e2e import run_e2e

    rc = await run_e2e(voice=False, real=False, sessions_dir=sessions_dir)
    assert rc == 0

    # Find the session trace
    session_dirs = list(sessions_dir.iterdir())
    assert len(session_dirs) == 1
    trace_path = session_dirs[0] / "logs" / "trace.jsonl"
    assert trace_path.exists()

    trace_text = trace_path.read_text(encoding="utf-8")

    # Bridge events should be present
    assert "bridge.round_start" in trace_text

    # Voice events should be present (from the manager conversation)
    assert "voice.utterance_in" in trace_text
    assert "voice.utterance_out" in trace_text

    # The injected first utterance should mention Haymarket Tap
    events = [json.loads(line) for line in trace_text.strip().splitlines()]
    utterance_ins = [e for e in events if e.get("event_type") == "voice.utterance_in"]
    assert len(utterance_ins) >= 1
    assert "Haymarket Tap" in utterance_ins[0]["payload"]["text"]


def test_build_research_agent_prompt_includes_booking_details() -> None:
    """Research agent prompt should contain venue, date, time, party size, deposit."""
    from sovereign_agent.halves import HalfResult

    from starter.handoff_bridge.bridge import BridgeResult
    from starter.voice_pipeline.run_e2e import build_research_agent_prompt

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
        summary="confirmed",
    )

    prompt = build_research_agent_prompt(bridge_result)

    assert "Haymarket Tap" in prompt
    assert "2026-04-25" in prompt
    assert "19:30" in prompt
    assert "6" in prompt
    assert "111" in prompt
    assert "12345678" in prompt


def test_is_goodbye_detects_farewell_keywords() -> None:
    """_is_goodbye should catch common farewell words."""
    from starter.voice_pipeline.run_e2e import _is_goodbye

    assert _is_goodbye("Goodbye and thanks!")
    assert _is_goodbye("Right, bye then.")
    assert _is_goodbye("Cheerio!")
    assert _is_goodbye("Cheers, see you Friday.")
    assert not _is_goodbye("I'd like to book for 6 people.")
    assert not _is_goodbye("What time works?")


@pytest.mark.asyncio
async def test_run_automated_conversation_produces_multi_turn_trace(tmp_path) -> None:
    """Automated conversation should produce multiple utterance_in/out pairs."""
    from sovereign_agent._internal.llm_client import ChatMessage
    from sovereign_agent.session.directory import create_session

    from starter.voice_pipeline.manager_persona import ManagerTurn

    # Stub both personas to avoid real LLM calls.
    class StubManagerPersona:
        def __init__(self):
            self.history: list[ManagerTurn] = []
            self._turn = 0

        async def respond(self, utterance: str) -> str:
            self._turn += 1
            if self._turn == 1:
                r = "Aye, sounds good. What's the contact number?"
            elif self._turn == 2:
                r = "Right, you're all booked in. Cheerio!"
            else:
                r = "Goodbye."
            self.history.append(ManagerTurn(user_utterance=utterance, manager_response=r))
            return r

    class StubResearcherClient:
        async def chat(self, *, model, messages, temperature=0.0, max_tokens=200):
            return ChatMessage(role="assistant", content="It's 12345678. Thanks!")

    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    session = create_session(scenario="test", sessions_dir=sessions_dir)

    from sovereign_agent.halves import HalfResult

    from starter.handoff_bridge.bridge import BridgeResult
    from starter.voice_pipeline.run_e2e import run_automated_conversation

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
        summary="confirmed",
    )

    await run_automated_conversation(
        session=session,
        manager=StubManagerPersona(),
        researcher_client=StubResearcherClient(),
        researcher_model="fake",
        bridge_result=bridge_result,
        voice=False,
        max_turns=6,
    )

    trace_text = session.trace_path.read_text(encoding="utf-8")
    events = [json.loads(line) for line in trace_text.strip().splitlines()]

    utterance_ins = [e for e in events if e.get("event_type") == "voice.utterance_in"]
    utterance_outs = [e for e in events if e.get("event_type") == "voice.utterance_out"]

    # Turn 0: researcher's booking request -> manager asks for number
    # Turn 1: researcher's "12345678" -> manager's "Cheerio!"
    # Conversation ends because manager said "Cheerio" (goodbye)
    assert len(utterance_ins) >= 2
    assert len(utterance_outs) >= 2

    # First utterance should be the booking request
    assert "Haymarket Tap" in utterance_ins[0]["payload"]["text"]

    # Conversation should have ended naturally (not hit max_turns=6)
    assert len(utterance_ins) <= 3
