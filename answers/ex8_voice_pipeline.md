# Ex8 — Voice pipeline

## Your answer

The main deliverable for ex8 was `run_e2e.py`, which chains all prior
exercises into a single pipeline: the loop half (ex5) searches venues
and calculates costs, the handoff bridge (ex7) routes to the Rasa
structured half (ex6) for booking validation, and on confirmation the
booking details seed an automated voice/text conversation with the pub
manager. For the 'best' experience, you can use `make ex8-e2e-full`, which
the research agent does research, speaks to the pub manager, who replies back
using the Speechmatics TTS/STT sdks.

The key design problem was bridging the structured output of the bridge
into natural conversation. `format_booking_utterance()` converts the
bridge result (venue_id, date, time, party_size, deposit) into a
first-turn sentence like "Hi, I'd like to book Haymarket Tap for 6
people on 2026-04-25 at 19:30. We'd put down a £111 deposit." This
becomes the opening of `run_automated_conversation()`, which drives a
two-agent dialogue: a research agent (LLM-backed, with a system prompt
containing the confirmed booking details) responds to the manager's
questions, while the `ManagerPersona` (Llama-3.3-70B) plays the pub
manager. The conversation terminates on a goodbye keyword from either
side, capped at 6 turns.

In scripted mode (no `--real`), a `FakeLLMClient` with hard-coded tool
call responses ensures the research stage is deterministic — the planner
produces one subgoal, the executor calls `venue_search`, `calculate_cost`,
and `handoff_to_structured` in sequence, and the mock Rasa server
confirms. All three e2e sessions
([`sess_c369e526b7e7`](../session_logs/homework/ex8-e2e/sess_c369e526b7e7/),
[`sess_708a72248756`](../session_logs/homework/ex8-e2e/sess_708a72248756/),
[`sess_cdbacd69eaab`](../session_logs/homework/ex8-e2e/sess_cdbacd69eaab/))
completed successfully with identical bookings (BK-7D401E9E). The
fullest was `sess_cdbacd69eaab` (voice mode, 3 turns: booking request,
contact number, goodbye).

The voice pipeline itself uses Speechmatics for STT/TTS with graceful
degradation — if `SPEECHMATICS_API_KEY` is missing it falls back to text
mode. Both modes emit the same `voice.utterance_in`/`voice.utterance_out`
trace events, so downstream analysis is identical regardless of
transport.

## Citations

- starter/voice_pipeline/run_e2e.py — e2e pipeline runner, format_booking_utterance, run_automated_conversation
- starter/voice_pipeline/manager_persona.py — LLM-backed pub manager persona
- starter/voice_pipeline/voice_loop.py — run_voice_mode, run_text_mode, Speechmatics integration
