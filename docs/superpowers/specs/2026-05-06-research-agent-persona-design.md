# Research Agent Persona for E2E Conversation

## Purpose

Replace the mic/stdin loop in e2e mode with a second LLM persona (the "research agent") that responds to the pub manager automatically, creating a fully automated two-agent conversation. The research agent has a distinct TTS voice (Sarah) from the manager (Theo).

## Architecture

### New class: `ResearchAgentPersona`

Lives in `starter/voice_pipeline/run_e2e.py` (same file as the runner — it's small and only used here).

Same pattern as `ManagerPersona`: wraps the Nebius LLM client with a system prompt and conversation history. The system prompt is dynamically built from the bridge result's booking details.

System prompt template:
```
You are a researcher booking a pub for your team outing. You are
friendly and efficient. Keep responses short (under 30 words).

You already know these details:
  - Venue: {venue_name}
  - Date: {date}
  - Time: {time}
  - Party size: {party_size}
  - Deposit: £{deposit}
  - Your contact number: 12345678

Answer the manager's questions using these details. When the manager
confirms the booking is done, thank them and say goodbye.
Do not invent information beyond what is listed above.
```

### Conversation loop in `run_e2e.py`

A new function `run_automated_conversation()` replaces the `run_text_mode`/`run_voice_mode` call in `run_e2e()`. It runs a back-and-forth loop:

```
turn 0: research agent speaks first utterance (format_booking_utterance)
        manager responds
turn 1: research agent responds to manager (LLM call)
        manager responds
...
until: goodbye detected in either response, or max_turns (6) reached
```

Each turn appends `voice.utterance_in` (research agent) and `voice.utterance_out` (manager) trace events, matching the existing trace schema.

### Voice mode

- Research agent: `Voice.SARAH` via Speechmatics TTS
- Manager: `Voice.THEO` via Speechmatics TTS (existing)
- In text mode, both agents print to stdout with labels (`researcher>`, `alasdair>`)

### Goodbye detection

After each response (from either side), check if the text contains any of: "goodbye", "bye", "cheerio", "cheers". Case-insensitive. If detected, the conversation ends naturally.

### Existing code impact

- `run_text_mode` / `run_voice_mode` with `initial_utterance` remain unchanged — still used for standalone/manual mode via `make ex8-text`, `make ex8-voice`
- `run_e2e()` stops calling `run_text_mode`/`run_voice_mode` and instead calls the new `run_automated_conversation()`
- `format_booking_utterance()` still used for the first utterance

## Key function signatures

```python
def build_research_agent_prompt(bridge_result: BridgeResult) -> str:
    """Build the research agent's system prompt from confirmed booking details."""

async def run_automated_conversation(
    *,
    session: Session,
    manager: ManagerPersona,
    researcher_client: LLMClient,
    researcher_model: str,
    bridge_result: BridgeResult,
    voice: bool = False,
    max_turns: int = 6,
) -> None:
    """Run a fully automated conversation between the research agent and the manager."""

def _build_researcher_client() -> tuple[OpenAICompatibleClient, str]:
    """Build the LLM client for the research agent."""
```

> **Note**: `_build_researcher_client` is monkeypatchable for tests, allowing test fixtures to substitute a fake LLM client without requiring real API credentials.

## What this does NOT include

- No changes to `voice_loop.py`, `manager_persona.py`, or any ex5/ex6/ex7 code
- No new files — everything goes in `run_e2e.py`
- The standalone modes (`make ex8-text`, `make ex8-voice`) are unaffected
