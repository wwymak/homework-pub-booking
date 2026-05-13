# Research Agent Persona Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the stdin/mic loop in e2e mode with a second LLM persona (research agent) that responds to the pub manager automatically, producing a natural multi-turn conversation.

**Architecture:** Add `build_research_agent_prompt()` and `run_automated_conversation()` to `run_e2e.py`. The research agent uses the same Nebius Llama-3.3-70B model as the manager but with its own system prompt and conversation history. In voice mode, the research agent speaks with Speechmatics `Voice.SARAH` while the manager uses `Voice.THEO`.

**Tech Stack:** Python 3.12, sovereign-agent LLMClient/ChatMessage, Speechmatics TTS (SARAH + THEO), Nebius Llama-3.3-70B.

---

### File structure

All changes in one file:
- Modify: `starter/voice_pipeline/run_e2e.py` — add `build_research_agent_prompt`, `_is_goodbye`, `run_automated_conversation`; update `run_e2e` to call the new function
- Test: `tests/public/test_ex8_e2e.py` — add tests for prompt builder, goodbye detection, and automated conversation

No new files. No changes to `voice_loop.py`, `manager_persona.py`, or any other existing file.

---

### Task 1: Add `build_research_agent_prompt` and `_is_goodbye`

**Files:**
- Modify: `starter/voice_pipeline/run_e2e.py`
- Modify: `tests/public/test_ex8_e2e.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/public/test_ex8_e2e.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run python -m pytest tests/public/test_ex8_e2e.py::test_build_research_agent_prompt_includes_booking_details tests/public/test_ex8_e2e.py::test_is_goodbye_detects_farewell_keywords -v`
Expected: FAIL — `build_research_agent_prompt` and `_is_goodbye` don't exist yet.

- [ ] **Step 3: Implement both functions**

Add to `starter/voice_pipeline/run_e2e.py`, after the existing `format_booking_utterance` function:

```python
_GOODBYE_WORDS = frozenset({"goodbye", "bye", "cheerio", "cheers"})


def _is_goodbye(text: str) -> bool:
    """Return True if the text contains a farewell keyword."""
    words = set(text.lower().replace(",", " ").replace(".", " ").replace("!", " ").split())
    return bool(words & _GOODBYE_WORDS)


def build_research_agent_prompt(bridge_result: BridgeResult) -> str:
    """Build the research agent's system prompt from confirmed booking details."""
    half = bridge_result.final_half_result
    output = (half.output if half is not None else None) or {}
    booking = output.get("booking", {})

    venue_id = booking.get("venue_id", "the venue")
    venue_name = _VENUE_DISPLAY_NAMES.get(venue_id, venue_id)
    party_size = booking.get("party_size", "?")
    date = booking.get("date", "?")
    time = booking.get("time", "?")
    deposit = booking.get("deposit_gbp") or booking.get("deposit_required_gbp", 0)

    return (
        "You are a researcher booking a pub for your team outing. You are "
        "friendly and efficient. Keep responses short (under 30 words).\n\n"
        "You already know these details:\n"
        f"  - Venue: {venue_name}\n"
        f"  - Date: {date}\n"
        f"  - Time: {time}\n"
        f"  - Party size: {party_size}\n"
        f"  - Deposit: £{deposit}\n"
        "  - Your contact number: 12345678\n\n"
        "Answer the manager's questions using these details. When the manager "
        "confirms the booking is done, thank them and say goodbye.\n"
        "Do not invent information beyond what is listed above."
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run python -m pytest tests/public/test_ex8_e2e.py::test_build_research_agent_prompt_includes_booking_details tests/public/test_ex8_e2e.py::test_is_goodbye_detects_farewell_keywords -v`
Expected: Both PASS.

- [ ] **Step 5: Commit**

```bash
git add starter/voice_pipeline/run_e2e.py tests/public/test_ex8_e2e.py
git commit -m "feat(ex8): add research agent prompt builder and goodbye detection"
```

---

### Task 2: Add `run_automated_conversation`

**Files:**
- Modify: `starter/voice_pipeline/run_e2e.py`
- Modify: `tests/public/test_ex8_e2e.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/public/test_ex8_e2e.py`:

```python
@pytest.mark.asyncio
async def test_run_automated_conversation_produces_multi_turn_trace(tmp_path) -> None:
    """Automated conversation should produce multiple utterance_in/out pairs."""
    import json

    from sovereign_agent._internal.llm_client import ChatMessage, OpenAICompatibleClient
    from sovereign_agent.session.directory import create_session

    from starter.voice_pipeline.manager_persona import ManagerPersona, ManagerTurn

    # Stub both personas to avoid real LLM calls.
    class StubManagerPersona:
        history: list[ManagerTurn] = []
        _turn = 0

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

    # Turn 0: researcher's booking request -> manager reply
    # Turn 1: researcher's "12345678" -> manager's "Cheerio!"
    # Conversation ends because manager said "Cheerio" (goodbye)
    assert len(utterance_ins) >= 2
    assert len(utterance_outs) >= 2

    # First utterance should be the booking request
    assert "Haymarket Tap" in utterance_ins[0]["payload"]["text"]

    # Conversation should have ended naturally (not hit max_turns=6)
    assert len(utterance_ins) <= 3
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m pytest tests/public/test_ex8_e2e.py::test_run_automated_conversation_produces_multi_turn_trace -v`
Expected: FAIL — `run_automated_conversation` doesn't exist yet.

- [ ] **Step 3: Implement `run_automated_conversation`**

Add the following import at the top of `run_e2e.py` (add `ChatMessage` to the existing sovereign_agent import, and add `Session` from session.directory — it's already imported via `create_session` but we need the type):

Add `ChatMessage` to the existing import:
```python
from sovereign_agent._internal.llm_client import (
    ChatMessage,
    FakeLLMClient,
    ...
)
```

Add `Session` to the existing import:
```python
from sovereign_agent.session.directory import Session, create_session
```

Then add the function after `build_research_agent_prompt`:

```python
async def run_automated_conversation(
    *,
    session: Session,
    manager: ManagerPersona,
    researcher_client,
    researcher_model: str,
    bridge_result: BridgeResult,
    voice: bool = False,
    max_turns: int = 6,
) -> None:
    """Run a fully automated conversation between the research agent and the manager."""
    from sovereign_agent.session.state import now_utc

    researcher_prompt = build_research_agent_prompt(bridge_result)
    researcher_history: list[ChatMessage] = [
        ChatMessage(role="system", content=researcher_prompt),
    ]

    first_utterance = format_booking_utterance(bridge_result)

    # Voice mode setup
    speechmatics_key = ""
    sd = None
    if voice:
        speechmatics_key = os.environ.get("SPEECHMATICS_API_KEY", "").strip()
        if speechmatics_key:
            try:
                import sounddevice as _sd
                sd = _sd
            except ImportError:
                pass

    async def _speak(text: str, voice_name: str) -> None:
        """Speak text via TTS if in voice mode."""
        if not voice or not speechmatics_key or sd is None:
            return
        try:
            import numpy as np
            from speechmatics.tts import AsyncClient, OutputFormat, Voice

            voice_enum = Voice.SARAH if voice_name == "researcher" else Voice.THEO
            async with AsyncClient(api_key=speechmatics_key) as client:
                response = await client.generate(
                    text=text,
                    voice=voice_enum,
                    output_format=OutputFormat.RAW_PCM_16000,
                )
                pcm_bytes = await response.read()
            samples = np.frombuffer(pcm_bytes, dtype=np.int16)
            sd.play(samples, samplerate=16000)
            sd.wait()
        except Exception as e:  # noqa: BLE001
            print(f"   ⚠ TTS failed: {e} (continuing)", file=sys.stderr)

    print("\n--- Automated conversation ---")

    researcher_text = first_utterance
    for turn_idx in range(max_turns):
        # -- Research agent speaks --
        label = "(injected)" if turn_idx == 0 else "(agent)"
        print(f"\n[turn {turn_idx + 1}] researcher {label}> {researcher_text}")
        await _speak(researcher_text, "researcher")

        session.append_trace_event(
            {
                "event_type": "voice.utterance_in",
                "actor": "user",
                "timestamp": now_utc().isoformat(),
                "payload": {
                    "text": researcher_text,
                    "turn": turn_idx,
                    "mode": "voice" if voice else "text",
                },
            }
        )

        # -- Manager responds --
        manager_text = await manager.respond(researcher_text)
        print(f"   alasdair> {manager_text}")
        await _speak(manager_text, "manager")

        session.append_trace_event(
            {
                "event_type": "voice.utterance_out",
                "actor": "manager",
                "timestamp": now_utc().isoformat(),
                "payload": {
                    "text": manager_text,
                    "turn": turn_idx,
                    "mode": "voice" if voice else "text",
                },
            }
        )

        # Check if manager said goodbye
        if _is_goodbye(manager_text):
            print("   (manager ended the conversation)")
            break

        # -- Research agent formulates next response via LLM --
        researcher_history.append(ChatMessage(role="user", content=manager_text))
        resp = await researcher_client.chat(
            model=researcher_model,
            messages=researcher_history,
            temperature=0.0,
            max_tokens=200,
        )
        researcher_text = (resp.content or "").strip()
        researcher_history.append(ChatMessage(role="assistant", content=researcher_text))

        # Check if researcher said goodbye
        if _is_goodbye(researcher_text):
            # Let the researcher say goodbye, then end
            print(f"\n[turn {turn_idx + 2}] researcher (agent)> {researcher_text}")
            await _speak(researcher_text, "researcher")
            session.append_trace_event(
                {
                    "event_type": "voice.utterance_in",
                    "actor": "user",
                    "timestamp": now_utc().isoformat(),
                    "payload": {
                        "text": researcher_text,
                        "turn": turn_idx + 1,
                        "mode": "voice" if voice else "text",
                    },
                }
            )
            print("   (researcher ended the conversation)")
            break

    print("-" * 60)
    print(f"Conversation ended. Trace: {session.trace_path}")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run python -m pytest tests/public/test_ex8_e2e.py -v`
Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add starter/voice_pipeline/run_e2e.py tests/public/test_ex8_e2e.py
git commit -m "feat(ex8): add run_automated_conversation for two-agent e2e"
```

---

### Task 3: Wire `run_automated_conversation` into `run_e2e`

**Files:**
- Modify: `starter/voice_pipeline/run_e2e.py`
- Modify: `tests/public/test_ex8_e2e.py`

- [ ] **Step 1: Update the existing e2e integration test**

The existing `test_e2e_scripted_bridge_completes_and_voice_trace_exists` test monkeypatches `ManagerPersona.from_env` and uses stdin. Now that `run_e2e` uses the automated conversation loop, the test needs to also provide a stub researcher client. Update the test:

Replace the existing test with:

```python
@pytest.mark.asyncio
async def test_e2e_scripted_bridge_completes_and_voice_trace_exists(tmp_path, monkeypatch) -> None:
    """Full e2e scripted pipeline: bridge confirms, then automated conversation produces trace."""
    import json

    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()

    # Stub manager persona
    from starter.voice_pipeline.manager_persona import ManagerTurn

    class StubManager:
        history: list[ManagerTurn] = []
        _turn = 0

        async def respond(self, utterance: str) -> str:
            self._turn += 1
            if self._turn == 1:
                r = "Aye, what's the number?"
            else:
                r = "All sorted. Cheerio!"
            self.history.append(ManagerTurn(user_utterance=utterance, manager_response=r))
            return r

    monkeypatch.setenv("NEBIUS_KEY", "fake-key-for-test")
    monkeypatch.setattr(
        "starter.voice_pipeline.manager_persona.ManagerPersona.from_env",
        classmethod(lambda cls: StubManager()),
    )

    # Stub research agent LLM client
    from sovereign_agent._internal.llm_client import ChatMessage

    class StubResearcherClient:
        async def chat(self, *, model, messages, temperature=0.0, max_tokens=200):
            return ChatMessage(role="assistant", content="It's 12345678. Cheers!")

    monkeypatch.setattr(
        "starter.voice_pipeline.run_e2e._build_researcher_client",
        lambda: (StubResearcherClient(), "fake"),
    )

    from starter.voice_pipeline.run_e2e import run_e2e

    rc = await run_e2e(voice=False, real=False, sessions_dir=sessions_dir)
    assert rc == 0

    session_dirs = list(sessions_dir.iterdir())
    assert len(session_dirs) == 1
    trace_path = session_dirs[0] / "logs" / "trace.jsonl"
    assert trace_path.exists()

    trace_text = trace_path.read_text(encoding="utf-8")

    assert "bridge.round_start" in trace_text
    assert "voice.utterance_in" in trace_text
    assert "voice.utterance_out" in trace_text

    events = [json.loads(line) for line in trace_text.strip().splitlines()]
    utterance_ins = [e for e in events if e.get("event_type") == "voice.utterance_in"]
    assert len(utterance_ins) >= 1
    assert "Haymarket Tap" in utterance_ins[0]["payload"]["text"]
```

- [ ] **Step 2: Replace Stage 2 in `run_e2e`**

In `starter/voice_pipeline/run_e2e.py`, add a helper to build the researcher client:

```python
def _build_researcher_client() -> tuple:
    """Build the LLM client for the research agent. Returns (client, model)."""
    client = OpenAICompatibleClient(
        base_url="https://api.tokenfactory.nebius.com/v1/",
        api_key_env="NEBIUS_KEY",
    )
    return client, "meta-llama/Llama-3.3-70B-Instruct"
```

Then replace Stage 2 in `run_e2e` (lines 229-242, the section starting with `# -- Stage 2:`) with:

```python
    # -- Stage 2: Automated conversation with pub manager --
    if not os.environ.get("NEBIUS_KEY"):
        print("✗ NEBIUS_KEY not set. Run 'make verify' first.", file=sys.stderr)
        return 1

    persona = ManagerPersona.from_env()
    researcher_client, researcher_model = _build_researcher_client()

    await run_automated_conversation(
        session=session,
        manager=persona,
        researcher_client=researcher_client,
        researcher_model=researcher_model,
        bridge_result=bridge_result,
        voice=voice,
        max_turns=6,
    )

    return 0
```

Also remove the now-unused imports `run_text_mode` and `run_voice_mode` from the import block (they're no longer called in this file).

- [ ] **Step 3: Run all tests**

Run: `uv run python -m pytest tests/public/test_ex8_e2e.py tests/public/test_ex8_scaffold.py -v`
Expected: All tests PASS.

- [ ] **Step 4: Commit**

```bash
git add starter/voice_pipeline/run_e2e.py tests/public/test_ex8_e2e.py
git commit -m "feat(ex8): wire automated conversation into e2e runner"
```

---

### Task 4: Full regression test and documentation

**Files:**
- Modify: `docs/superpowers/specs/2026-05-06-research-agent-persona-design.md`

- [ ] **Step 1: Run full test suite**

Run: `uv run python -m pytest tests/public/ -v`
Expected: All tests PASS, no regressions.

- [ ] **Step 2: Update spec with final details**

Update the spec to note:
- Voice uses `Voice.SARAH` (not ARIA — ARIA doesn't exist in this Speechmatics version)
- The `_build_researcher_client` helper is monkeypatchable for tests
- `run_text_mode`/`run_voice_mode` imports removed from `run_e2e.py` (no longer used there)

- [ ] **Step 3: Commit**

```bash
git add docs/superpowers/specs/2026-05-06-research-agent-persona-design.md
git commit -m "docs: update research agent spec with final implementation details"
```
