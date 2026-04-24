"""Ex8 — voice loop.

Text mode runs stdin → manager → stdout (already implemented).
Voice mode runs mic → Speechmatics STT → manager → Rime Arcana TTS → speakers (YOUR TODO).

The trace records EVERY utterance (both directions) as
'voice.utterance_in' (user) and 'voice.utterance_out' (manager).
Both modes MUST emit identical event shapes so the grader doesn't
care which one ran.
"""

from __future__ import annotations

# These imports will be used in your run_voice_mode implementation.
# noqa: F401 silences "unused" until you implement.
import os  # noqa: F401
import sys  # noqa: F401

from sovereign_agent.session.directory import Session
from sovereign_agent.session.state import now_utc

from starter.voice_pipeline.manager_persona import ManagerPersona


# ---------------------------------------------------------------------------
# Text mode — implemented; read first to learn the trace-event shape
# ---------------------------------------------------------------------------
async def run_text_mode(session: Session, persona: ManagerPersona, max_turns: int = 6) -> None:
    """Run the conversation via stdin/stdout.

    This implementation is COMPLETE (no TODO) so you can see the
    expected trace event shape. Read it, then port the same shape to
    run_voice_mode().
    """
    print("Text mode. Type a message to Alasdair (pub manager); blank line to quit.")
    print(f"Session: {session.session_id}")
    print("-" * 60)

    for turn_idx in range(max_turns):
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


# ---------------------------------------------------------------------------
# Voice mode — TODO for Ex8
# ---------------------------------------------------------------------------
async def run_voice_mode(session: Session, persona: ManagerPersona, max_turns: int = 6) -> None:
    """Real voice mode: mic → Speechmatics STT → manager → Rime Arcana TTS → speakers.

    Before you start:
      1. Run: make setup-voice
         (installs speechmatics-python, sounddevice, pydub, numpy)
      2. Check SPEECHMATICS_KEY and RIME_API_KEY are in your .env
      3. macOS only: System Settings → Privacy & Security → Microphone
         → grant your terminal app access
      4. Run: make ex8-voice

    Architecture for each turn:
        mic capture (sounddevice) ─▶ WAV bytes
                                        │
                         Speechmatics realtime STT (websocket)
                                        │
                                        ▼
                                 user_text (transcript)
                                        │
                           (emit 'voice.utterance_in' trace event)
                                        │
                            persona.respond(user_text)
                                        │
                                        ▼
                                manager_text (LLM reply)
                                        │
                          (emit 'voice.utterance_out' trace event)
                                        │
                             Rime.ai Arcana TTS (REST → mp3)
                                        │
                      pydub decode → sounddevice playback

    Degrade gracefully. In order of preference:
      * No SPEECHMATICS_KEY          → fall back to run_text_mode with warning
      * speechmatics-python missing  → same, suggest `make setup-voice`
      * No RIME_API_KEY              → STT works, manager replies printed (no audio)
      * Mic permission denied        → clear error pointing at system settings

    Key libraries (installed via `make setup-voice`):
      - speechmatics.models, speechmatics.client — STT websocket
      - sounddevice — mic capture + audio playback
      - pydub — MP3 decode (Rime returns MP3; stdlib only does WAV)
      - numpy — sample arrays

    Trace events MUST match text mode's shape exactly:
        'voice.utterance_in'  with payload {text, turn, mode: 'voice'}
        'voice.utterance_out' with payload {text, turn, mode: 'voice'}

    Step-by-step implementation order:
      1. Preflight — check env vars and deps, fall back to text if missing
      2. Wire STT only first. Print the transcript, call persona.respond,
         print the reply. Skip TTS. Confirm trace events fire.
      3. Add Rime TTS last. Decode MP3 → play audio.

    Common failures are documented in docs/real-mode-failures.md.
    """
    raise NotImplementedError(
        "TODO Ex8: implement run_voice_mode. See docstring above for the "
        "architecture. Start with preflight, wire STT first (print transcripts), "
        "add Rime TTS last."
    )


__all__ = ["run_text_mode", "run_voice_mode"]
