# End-to-End Pipeline Runner (Ex8 E2E)

## Purpose

Wire up the full booking pipeline: ex5 research (loop half) -> ex7 handoff bridge -> ex6 Rasa validation -> ex8 voice/text conversation with the pub manager. The confirmed booking details from the bridge become the first "user" utterance in the manager conversation.

## Architecture

### New file: `starter/voice_pipeline/run_e2e.py`

Single entry point with two flags:
- `--real`: use live Nebius LLM for the research loop half (default: scripted `FakeLLMClient`)
- `--voice`: use Speechmatics STT/TTS for the manager conversation (default: text mode via stdin/stdout)

Both flags are combinable. The manager persona always uses a real LLM (Nebius) regardless of `--real`.

### Pipeline stages

```
Stage 1: Research + Validation
  LoopHalf (ex5 tools: venue_search, calculate_cost)
      |
  HandoffBridge (ex7)
      |
  RasaStructuredHalf (ex6, mock or real Rasa)
      |
  BridgeResult { outcome="completed", booking data + booking_reference }

Stage 2: Voice/Text Conversation
  format_booking_utterance(bridge_result) -> first utterance string
      |
  [voice mode only] Speak the utterance via Speechmatics TTS
      |
  ManagerPersona.respond(utterance) -> manager reply
      |
  Continue with run_text_mode or run_voice_mode for remaining turns
```

### Data flow detail

The bridge result contains a `final_half_result.output` dict with:
- `booking.venue_id` (e.g., "haymarket_tap")
- `booking.date` (e.g., "2026-04-25")
- `booking.time` (e.g., "19:30")
- `booking.party_size` (e.g., 6)
- `booking.deposit_gbp` (e.g., 111 — from `calculate_cost` for haymarket_tap, party=6, 3hrs, bar_snacks)
- `booking_reference` (e.g., "BK-A1B2C3D4")

`format_booking_utterance()` converts this into a natural sentence, e.g.:
> "Hi, I'd like to book Haymarket Tap for 6 people on 2026-04-25 at 19:30. We'd put down a £111 deposit."

This string is the first "user" turn in the manager conversation. In voice mode it is also spoken aloud via Speechmatics TTS before being sent to the persona. The manager then responds, and remaining turns proceed normally through the existing `run_text_mode` / `run_voice_mode` loop.

### Scripted mode (default, no `--real`)

Matches the README scenario: party of 6, near Haymarket, 19:30, deposit under £300. Single-round bridge success.

Scripted LLM responses:
1. Planner: one subgoal — "find venue near Haymarket for 6"
2. Executor turn 1: `venue_search(near="Haymarket", party_size=6, budget_max_gbp=2000)`
3. Executor turn 2: `calculate_cost(venue_id="haymarket_tap", party_size=6, duration_hours=3)`
4. Executor turn 3: `handoff_to_structured` with venue_id, date, time, party_size, deposit from calculate_cost output

Mock Rasa server: `max_party_size=8`, `max_deposit_gbp=300` (defaults). Confirms and returns booking reference.

### Real mode (`--real`)

Uses `OpenAICompatibleClient` with Nebius for the loop half planner and executor. Same `Config.from_env()` pattern as ex7's `run.py`. Manager persona always uses real LLM.

### Voice mode (`--voice`)

In voice mode, the first utterance (research agent's booking request) is spoken via `_speak_speechmatics` before the persona responds. This ensures the full conversation is audible. Subsequent turns use the existing `run_voice_mode` loop. Falls back to text mode if `SPEECHMATICS_API_KEY` is missing (existing graceful degradation).

### Session

Single session with scenario `ex8-e2e-pipeline`. All trace events from the bridge (ex7 `bridge.round_start`, `session.state_changed`) and voice loop (`voice.utterance_in`, `voice.utterance_out`) land in the same trace file.

## Key function signatures

```python
def format_booking_utterance(bridge_result: BridgeResult) -> str:
    """Format confirmed booking details as a natural first-turn utterance."""

async def run_e2e(voice: bool, real: bool) -> int:
    """Run the full pipeline: research -> bridge -> voice conversation."""

def main() -> None:
    """Entry point. Parses --voice and --real flags from sys.argv."""
```

## Integration with existing code

- Imports `build_tool_registry` from `starter.edinburgh_research.tools`
- Imports `HandoffBridge` from `starter.handoff_bridge.bridge`
- Imports `RasaStructuredHalf`, `spawn_mock_rasa` from `starter.rasa_half.structured_half`
- Imports `ManagerPersona` from `starter.voice_pipeline.manager_persona`
- Imports `run_text_mode`, `run_voice_mode` from `starter.voice_pipeline.voice_loop`
- Imports `_speak_speechmatics` from `starter.voice_pipeline.voice_loop` (for speaking first utterance in voice mode)

### Changes to existing files

- `starter/voice_pipeline/manager_persona.py`: updated system prompt to add conversation flow (ask for deposit before confirming)
- `starter/voice_pipeline/voice_loop.py`: added `initial_utterance: str | None = None` parameter to `run_text_mode` and `run_voice_mode` (backward-compatible)
- `Makefile`: added `ex8-e2e`, `ex8-e2e-real`, `ex8-e2e-voice`, `ex8-e2e-full` targets

### New files

- `starter/voice_pipeline/run_e2e.py`: the e2e runner
- `tests/public/test_ex8_e2e.py`: 5 tests covering initial_utterance injection, format_booking_utterance, and full e2e scripted pipeline

## Rasa server behaviour

- **Default (scripted) mode**: spawns a mock Rasa server via `spawn_mock_rasa` — no license needed
- **`--real` mode**: uses the real Rasa server at `localhost:5005` (assumes `rasa serve` + action server are running, or uses `RasaHostLifecycle`). Requires `RASA_PRO_LICENSE` and related keys in `.env`.

This matches ex7's runner pattern.

## What this does NOT include

- No changes to ex5/ex6/ex7 code
