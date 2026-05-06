# E2E Pipeline Runner Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire up an end-to-end runner: ex5 research → ex7 bridge → ex6 Rasa validation → ex8 voice/text manager conversation, with scripted and real LLM modes.

**Architecture:** A new `run_e2e.py` chains the bridge pipeline with the voice loop. The bridge's confirmed booking is formatted as the first "user" utterance and injected into the manager conversation via a new `initial_utterance` parameter on `run_text_mode`/`run_voice_mode`. The manager persona then continues the conversation normally.

**Tech Stack:** Python 3.12, sovereign-agent framework, FakeLLMClient (scripted mode), Nebius/Llama-3.3-70B (real mode), Speechmatics (voice mode), mock Rasa server (scripted) / real Rasa (real mode).

---

### Task 1: Add `initial_utterance` parameter to voice loop functions

Extend `run_text_mode` and `run_voice_mode` to accept an optional first utterance that skips stdin/mic capture on turn 0. Backward-compatible — defaults to `None`.

**Files:**
- Modify: `starter/voice_pipeline/voice_loop.py`
- Test: `tests/public/test_ex8_e2e.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/public/test_ex8_e2e.py`:

```python
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

    await run_text_mode(
        session, persona, max_turns=4, initial_utterance="Book Haymarket Tap for 6"
    )

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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m pytest tests/public/test_ex8_e2e.py -v`
Expected: FAIL — `run_text_mode` does not accept `initial_utterance` parameter yet.

- [ ] **Step 3: Implement `initial_utterance` in `run_text_mode`**

In `starter/voice_pipeline/voice_loop.py`, change the `run_text_mode` signature and add logic for turn 0:

```python
async def run_text_mode(
    session: Session,
    persona: ManagerPersona,
    max_turns: int = 6,
    initial_utterance: str | None = None,
) -> None:
    """Conversation via stdin/stdout. Same trace-event shape as voice mode."""
    print("Text mode. Type a message to Alasdair (pub manager); blank line to quit.")
    print(f"Session: {session.session_id}")
    print("-" * 60)

    for turn_idx in range(max_turns):
        if turn_idx == 0 and initial_utterance is not None:
            user_text = initial_utterance
            print(f"you> {user_text}")
        else:
            try:
                user_text = input("you> ").strip()
            except EOFError:
                break
            if not user_text:
                break

        session.append_trace_event(
            {
                "event_type": "voice.utterance_in",
                "actor": "user",
                "timestamp": now_utc().isoformat(),
                "payload": {"text": user_text, "turn": turn_idx, "mode": "text"},
            }
        )

        manager_text = await persona.respond(user_text)
        print(f"alasdair> {manager_text}")

        session.append_trace_event(
            {
                "event_type": "voice.utterance_out",
                "actor": "manager",
                "timestamp": now_utc().isoformat(),
                "payload": {"text": manager_text, "turn": turn_idx, "mode": "text"},
            }
        )

    print("-" * 60)
    print(f"Conversation ended. Trace: {session.trace_path}")
```

- [ ] **Step 4: Implement `initial_utterance` in `run_voice_mode`**

In `starter/voice_pipeline/voice_loop.py`, change the `run_voice_mode` signature. Pass `initial_utterance` through to the text-mode fallback, and handle it in voice mode by speaking it via TTS on turn 0:

```python
async def run_voice_mode(
    session: Session,
    persona: ManagerPersona,
    max_turns: int = 6,
    initial_utterance: str | None = None,
) -> None:
    """Voice mode. Real mic capture -> Speechmatics STT -> manager -> Speechmatics TTS."""

    # -- preflight: keys + deps --
    speechmatics_key = os.environ.get("SPEECHMATICS_API_KEY", "").strip()

    if not speechmatics_key:
        print(
            "⚠  SPEECHMATICS_API_KEY not set — falling back to text mode.\n"
            "   Add to .env and re-run for real voice.",
            file=sys.stderr,
        )
        await run_text_mode(session, persona, max_turns=max_turns, initial_utterance=initial_utterance)
        return

    try:
        import sounddevice as sd  # type: ignore[import-not-found]
        from speechmatics.rt import AsyncClient as RtAsyncClient  # noqa: F401
    except ImportError as e:
        print(
            f"⚠  Missing voice dep: {e.name}. Run 'make setup' with voice extra:\n"
            "     uv sync --extra voice\n"
            "   Falling back to text mode.",
            file=sys.stderr,
        )
        await run_text_mode(session, persona, max_turns=max_turns, initial_utterance=initial_utterance)
        return

    print(f"\U0001f399️  Voice mode. Session: {session.session_id}")
    print(f"    Speak when prompted. Silence for {SILENCE_TIMEOUT_S}s ends a turn.")
    print(f"    Max utterance: {MAX_UTTERANCE_S}s. Say 'goodbye' to end.")
    print("-" * 60)

    for turn_idx in range(max_turns):
        if turn_idx == 0 and initial_utterance is not None:
            user_text = initial_utterance
            print(f"   you> {user_text}")
            try:
                await _speak_speechmatics(user_text, speechmatics_key, sd)
            except Exception as e:  # noqa: BLE001
                print(f"   ⚠ TTS playback of initial utterance failed: {e}", file=sys.stderr)
        else:
            print(f"\n[turn {turn_idx + 1}] \U0001f3a4 listening...")

            try:
                audio_bytes = _record_until_silence(sd, session, turn_idx)
            except Exception as e:  # noqa: BLE001
                print(f"✗ mic capture failed: {e}", file=sys.stderr)
                print(
                    "   macOS? Check System Settings → Privacy & Security → Microphone\n"
                    "   and grant your terminal app access, then restart the terminal.",
                    file=sys.stderr,
                )
                return

            if not audio_bytes:
                print("   (silence detected; ending conversation)")
                break

            try:
                user_text = await _transcribe_speechmatics(audio_bytes, speechmatics_key)
            except Exception as e:  # noqa: BLE001
                print(f"✗ STT failed: {e}", file=sys.stderr)
                print(
                    "   Check SPEECHMATICS_API_KEY (make educator-diagnostics).\n"
                    "   Free-tier has a monthly cap; 403 usually means exhausted.",
                    file=sys.stderr,
                )
                return

            user_text = user_text.strip()
            if not user_text:
                print("   (no transcript; ending conversation)")
                break

            print(f"   you> {user_text}")

        session.append_trace_event(
            {
                "event_type": "voice.utterance_in",
                "actor": "user",
                "timestamp": now_utc().isoformat(),
                "payload": {"text": user_text, "turn": turn_idx, "mode": "voice"},
            }
        )

        if user_text.lower().strip(".!?") in ("goodbye", "bye", "cheerio"):
            break

        manager_text = await persona.respond(user_text)
        print(f"   alasdair> {manager_text}")

        session.append_trace_event(
            {
                "event_type": "voice.utterance_out",
                "actor": "manager",
                "timestamp": now_utc().isoformat(),
                "payload": {"text": manager_text, "turn": turn_idx, "mode": "voice"},
            }
        )

        try:
            await _speak_speechmatics(manager_text, speechmatics_key, sd)
        except Exception as e:  # noqa: BLE001
            print(f"   ⚠ TTS playback failed: {e} (continuing)", file=sys.stderr)

    print("-" * 60)
    print(f"Conversation ended. Trace: {session.trace_path}")
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run python -m pytest tests/public/test_ex8_e2e.py tests/public/test_ex8_scaffold.py -v`
Expected: All tests PASS. Existing ex8 tests still pass (backward-compatible change).

- [ ] **Step 6: Commit**

```bash
git add starter/voice_pipeline/voice_loop.py tests/public/test_ex8_e2e.py
git commit -m "feat(ex8): add initial_utterance parameter to text/voice mode"
```

---

### Task 2: Create `format_booking_utterance` helper

Extracts confirmed booking details from a `BridgeResult` and formats them as a natural first-turn message.

**Files:**
- Create: `starter/voice_pipeline/run_e2e.py` (start with just the helper)
- Test: `tests/public/test_ex8_e2e.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `tests/public/test_ex8_e2e.py`:

```python
def test_format_booking_utterance_includes_all_fields() -> None:
    """format_booking_utterance should include venue, party, date, time, deposit."""
    from starter.handoff_bridge.bridge import BridgeResult
    from sovereign_agent.halves import HalfResult

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
    from starter.handoff_bridge.bridge import BridgeResult
    from sovereign_agent.halves import HalfResult

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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m pytest tests/public/test_ex8_e2e.py::test_format_booking_utterance_includes_all_fields -v`
Expected: FAIL — `run_e2e` module does not exist yet.

- [ ] **Step 3: Implement `format_booking_utterance`**

Create `starter/voice_pipeline/run_e2e.py`:

```python
"""Ex8 — end-to-end pipeline runner.

Chains: ex5 research (loop half) -> ex7 handoff bridge -> ex6 Rasa
validation -> ex8 voice/text manager conversation.

Modes:
  default:  scripted FakeLLMClient + mock Rasa + text mode
  --real:   live Nebius LLM + real Rasa + text mode
  --voice:  scripted + Speechmatics STT/TTS
  --real --voice: full live pipeline
"""

from __future__ import annotations

from starter.handoff_bridge.bridge import BridgeResult

_VENUE_DISPLAY_NAMES: dict[str, str] = {
    "haymarket_tap": "Haymarket Tap",
    "royal_oak": "The Royal Oak",
    "sheep_heid": "The Sheep Heid Inn",
    "bennets_bar": "Bennet's Bar",
    "cafe_royal": "Cafe Royal",
}


def format_booking_utterance(bridge_result: BridgeResult) -> str:
    """Format confirmed booking details as a natural first-turn utterance."""
    output = bridge_result.final_half_result.output or {}
    booking = output.get("booking", {})

    venue_id = booking.get("venue_id", "the venue")
    venue_name = _VENUE_DISPLAY_NAMES.get(venue_id, venue_id)
    party_size = booking.get("party_size", "?")
    date = booking.get("date", "?")
    time = booking.get("time", "?")
    deposit = booking.get("deposit_gbp") or booking.get("deposit_required_gbp", 0)

    return (
        f"Hi, I'd like to book {venue_name} for {party_size} people "
        f"on {date} at {time}. "
        f"We'd put down a £{deposit} deposit."
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run python -m pytest tests/public/test_ex8_e2e.py::test_format_booking_utterance_includes_all_fields tests/public/test_ex8_e2e.py::test_format_booking_utterance_handles_deposit_required_gbp_alias -v`
Expected: Both PASS.

- [ ] **Step 5: Commit**

```bash
git add starter/voice_pipeline/run_e2e.py tests/public/test_ex8_e2e.py
git commit -m "feat(ex8): add format_booking_utterance helper"
```

---

### Task 3: Build scripted FakeLLMClient and wire up e2e runner

Single-round success: venue_search → calculate_cost → handoff_to_structured → mock Rasa confirms → format utterance → manager conversation.

**Files:**
- Modify: `starter/voice_pipeline/run_e2e.py`
- Test: `tests/public/test_ex8_e2e.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `tests/public/test_ex8_e2e.py`:

```python
@pytest.mark.asyncio
async def test_e2e_scripted_bridge_completes_and_voice_trace_exists(tmp_path, monkeypatch) -> None:
    """Full e2e scripted pipeline: bridge confirms, then voice trace has events."""
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()

    # stdin for the manager conversation (after the injected first turn)
    monkeypatch.setattr("sys.stdin", io.StringIO("sounds good\n\n"))

    from starter.voice_pipeline.run_e2e import run_e2e

    rc = await run_e2e(voice=False, real=False, sessions_dir=sessions_dir)
    assert rc == 0

    # Find the session trace
    session_dirs = list(sessions_dir.iterdir())
    assert len(session_dirs) == 1
    trace_path = session_dirs[0] / "trace.jsonl"
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m pytest tests/public/test_ex8_e2e.py::test_e2e_scripted_bridge_completes_and_voice_trace_exists -v`
Expected: FAIL — `run_e2e` function does not exist yet.

- [ ] **Step 3: Implement the scripted client builder**

Add to `starter/voice_pipeline/run_e2e.py`:

```python
import json

from sovereign_agent._internal.llm_client import (
    FakeLLMClient,
    ScriptedResponse,
    ToolCall,
)


def _build_scripted_client() -> FakeLLMClient:
    """Single-round success matching the README scenario.

    Party of 6, Haymarket, 19:30, bar_snacks. calculate_cost returns
    deposit_required_gbp=111 (under £300 cap). Mock Rasa confirms.
    """
    plan = json.dumps(
        [
            {
                "id": "sg_1",
                "description": "find venue near Haymarket for 6, compute cost, hand off",
                "success_criterion": "booking handed to structured half",
                "estimated_tool_calls": 3,
                "depends_on": [],
                "assigned_half": "loop",
            }
        ]
    )

    return FakeLLMClient(
        [
            ScriptedResponse(content=plan),
            ScriptedResponse(
                tool_calls=[
                    ToolCall(
                        id="c1",
                        name="venue_search",
                        arguments={
                            "near": "Haymarket",
                            "party_size": 6,
                            "budget_max_gbp": 2000,
                        },
                    )
                ]
            ),
            ScriptedResponse(
                tool_calls=[
                    ToolCall(
                        id="c2",
                        name="calculate_cost",
                        arguments={
                            "venue_id": "haymarket_tap",
                            "party_size": 6,
                            "duration_hours": 3,
                            "catering_tier": "bar_snacks",
                        },
                    )
                ]
            ),
            ScriptedResponse(
                tool_calls=[
                    ToolCall(
                        id="c3",
                        name="handoff_to_structured",
                        arguments={
                            "reason": "venue found and costed; handing to structured for confirmation",
                            "context": "party of 6 near Haymarket on 2026-04-25 at 19:30",
                            "data": {
                                "action": "confirm_booking",
                                "venue_id": "Haymarket Tap",
                                "date": "2026-04-25",
                                "time": "19:30",
                                "party_size": "6",
                                "deposit_required_gbp": 111,
                            },
                        },
                    )
                ]
            ),
        ]
    )
```

- [ ] **Step 4: Implement the `run_e2e` function**

Add to `starter/voice_pipeline/run_e2e.py`:

```python
import asyncio
import os
import sys
from pathlib import Path

from sovereign_agent._internal.llm_client import OpenAICompatibleClient
from sovereign_agent._internal.paths import user_data_dir
from sovereign_agent.executor import DefaultExecutor
from sovereign_agent.halves.loop import LoopHalf
from sovereign_agent.planner import DefaultPlanner
from sovereign_agent.session.directory import create_session

from starter._trace_stream import enable_trace_streaming
from starter.edinburgh_research.tools import build_tool_registry
from starter.handoff_bridge.bridge import HandoffBridge
from starter.rasa_half.structured_half import RasaStructuredHalf, spawn_mock_rasa
from starter.voice_pipeline.manager_persona import ManagerPersona
from starter.voice_pipeline.voice_loop import run_text_mode, run_voice_mode


_EXECUTOR_SYSTEM_PROMPT = (
    "You are the EXECUTOR of a booking research agent. Your job is to "
    "find a venue and hand it off for confirmation.\n\n"
    "WORKFLOW:\n"
    "1. Use venue_search to find a venue that fits the requirements.\n"
    "2. Use calculate_cost to compute the total and deposit.\n"
    "3. Call handoff_to_structured with ALL booking data in the 'data' "
    "dict: venue_id, date, time, party_size, and deposit "
    "(use deposit_required_gbp from calculate_cost).\n\n"
    "IMPORTANT: Do NOT call complete_task — the structured half "
    "confirms bookings, not you. Always hand off via "
    "handoff_to_structured when you have a venue."
)


async def run_e2e(
    voice: bool = False,
    real: bool = False,
    sessions_dir: Path | None = None,
) -> int:
    """Run the full pipeline: research -> bridge -> voice conversation."""
    if sessions_dir is None:
        sessions_dir = user_data_dir() / "homework" / "ex8-e2e"
    sessions_dir.mkdir(parents=True, exist_ok=True)

    task = "Book a venue for 6 people near Haymarket, Friday 2026-04-25 at 19:30."
    session = create_session(
        scenario="ex8-e2e-pipeline",
        task=task,
        sessions_dir=sessions_dir,
    )
    print(f"Session {session.session_id}")
    print(f"  dir: {session.directory}")
    enable_trace_streaming(session)

    # -- Stage 1: Research + Rasa validation via bridge --
    mock_server = None
    if real:
        from sovereign_agent.config import Config

        cfg = Config.from_env()
        print(f"  LLM: {cfg.llm_base_url} (live)")
        client = OpenAICompatibleClient(
            base_url=cfg.llm_base_url,
            api_key_env=cfg.llm_api_key_env,
        )
        planner_model = cfg.llm_planner_model
        executor_model = cfg.llm_executor_model
        rasa_half = RasaStructuredHalf()
    else:
        client = _build_scripted_client()
        planner_model = executor_model = "fake"
        mock_server, _thread, mock_url = spawn_mock_rasa(
            port=5907, max_party_size=8, max_deposit_gbp=300
        )
        rasa_half = RasaStructuredHalf(rasa_url=mock_url)

    tools = build_tool_registry(session)
    loop_half = LoopHalf(
        planner=DefaultPlanner(model=planner_model, client=client),
        executor=DefaultExecutor(
            model=executor_model,
            client=client,
            tools=tools,
            system_prompt=_EXECUTOR_SYSTEM_PROMPT,
        ),
    )
    bridge = HandoffBridge(
        loop_half=loop_half,
        structured_half=rasa_half,
        max_rounds=3,
    )

    try:
        bridge_result = await bridge.run(session, {"task": task})
    finally:
        if mock_server is not None:
            mock_server.shutdown()

    print(f"\nBridge outcome: {bridge_result.outcome}")
    print(f"  rounds: {bridge_result.rounds}")
    print(f"  summary: {bridge_result.summary}")

    if bridge_result.outcome != "completed":
        print("Bridge did not confirm booking — skipping voice stage.", file=sys.stderr)
        return 1

    # -- Stage 2: Voice/text conversation with pub manager --
    if not os.environ.get("NEBIUS_KEY"):
        print("✗ NEBIUS_KEY not set. Run 'make verify' first.", file=sys.stderr)
        return 1

    persona = ManagerPersona.from_env()
    first_utterance = format_booking_utterance(bridge_result)
    print(f"\n--- Manager conversation (first utterance from research agent) ---")
    print(f"  \"{first_utterance}\"")

    if voice:
        await run_voice_mode(session, persona, initial_utterance=first_utterance)
    else:
        await run_text_mode(session, persona, initial_utterance=first_utterance)

    return 0


def main() -> None:
    """Entry point. Parses --voice and --real flags from sys.argv."""
    voice = "--voice" in sys.argv
    real = "--real" in sys.argv
    sys.exit(asyncio.run(run_e2e(voice=voice, real=real)))


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run python -m pytest tests/public/test_ex8_e2e.py -v`
Expected: All tests PASS.

- [ ] **Step 6: Run all ex8 tests to check for regressions**

Run: `uv run python -m pytest tests/public/test_ex8_scaffold.py tests/public/test_ex8_e2e.py -v`
Expected: All tests PASS.

- [ ] **Step 7: Commit**

```bash
git add starter/voice_pipeline/run_e2e.py tests/public/test_ex8_e2e.py
git commit -m "feat(ex8): e2e pipeline runner with scripted and real modes"
```

---

### Task 4: Add Makefile targets

**Files:**
- Modify: `Makefile`

- [ ] **Step 1: Add e2e make targets**

Add these targets near the existing ex8 targets in the Makefile:

```makefile
.PHONY: ex8-e2e
ex8-e2e: ## Run Ex8 e2e pipeline (scripted research + text mode)
	@$(UV) run python -m starter.voice_pipeline.run_e2e

.PHONY: ex8-e2e-real
ex8-e2e-real: ## Run Ex8 e2e pipeline (real LLM + real Rasa + text mode)
	@$(UV) run python -m starter.voice_pipeline.run_e2e --real

.PHONY: ex8-e2e-voice
ex8-e2e-voice: ## Run Ex8 e2e pipeline (scripted research + voice mode)
	@$(UV) run python -m starter.voice_pipeline.run_e2e --voice

.PHONY: ex8-e2e-full
ex8-e2e-full: ## Run Ex8 full live pipeline (real LLM + real Rasa + voice)
	@$(UV) run python -m starter.voice_pipeline.run_e2e --real --voice
```

- [ ] **Step 2: Verify the target runs**

Run: `make ex8-e2e` (will need NEBIUS_KEY in .env — if not set, should exit with clear error).

- [ ] **Step 3: Update help text**

Add the e2e targets to the help text section of the Makefile, near the existing ex8 entries:

```
@echo '      ${CYAN}make ex8-e2e${RESET}             scripted research -> text manager conversation'
@echo '      ${CYAN}make ex8-e2e-real${RESET}         real LLM + Rasa -> text manager conversation'
@echo '      ${CYAN}make ex8-e2e-voice${RESET}        scripted research -> voice manager conversation'
@echo '      ${CYAN}make ex8-e2e-full${RESET}         full live pipeline (real LLM + Rasa + voice)'
```

- [ ] **Step 4: Commit**

```bash
git add Makefile
git commit -m "feat(ex8): add e2e pipeline Makefile targets"
```

---

### Task 5: Documentation

**Files:**
- Modify: `docs/superpowers/specs/2026-05-06-e2e-pipeline-runner-design.md` (update to reflect final implementation)

- [ ] **Step 1: Update spec with final implementation details**

Update the spec to note:
- `voice_loop.py` was modified (added `initial_utterance` parameter)
- The exact Makefile targets added
- Test file created at `tests/public/test_ex8_e2e.py`

- [ ] **Step 2: Commit**

```bash
git add docs/superpowers/specs/2026-05-06-e2e-pipeline-runner-design.md
git commit -m "docs: update e2e pipeline spec with final implementation details"
```

---

### Task 6: Full regression test

- [ ] **Step 1: Run all tests**

Run: `uv run python -m pytest tests/public/ -v`
Expected: All existing tests PASS, no regressions.
