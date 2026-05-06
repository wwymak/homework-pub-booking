"""Ex8 — voice loop (reference solution).

Two modes:
  * text mode: stdin → manager → stdout. Free, no mic needed.
  * voice mode: mic → Speechmatics realtime STT → manager →
    Speechmatics TTS → speakers.

Both modes write identical trace events so downstream grading
doesn't care which ran.

Voice mode degrades gracefully:
  - No SPEECHMATICS_API_KEY    → text mode with warning
  - speechmatics-rt missing    → text mode with install hint
  - No mic / no playback       → attempted run; errors surface clearly
"""

from __future__ import annotations

import os
import sys
import wave

from sovereign_agent.session.directory import Session
from sovereign_agent.session.state import now_utc

from starter.voice_pipeline.manager_persona import ManagerPersona

# Audio config — matches Speechmatics' default expectations
SAMPLE_RATE = 16000
CHANNELS = 1
SAMPLE_WIDTH = 2  # 16-bit PCM
MAX_UTTERANCE_S = 15.0  # cap per-turn recording
SILENCE_TIMEOUT_S = 2.0  # consecutive silence to end an utterance


# ---------------------------------------------------------------------------
# Text mode — reference implementation (read this first)
# ---------------------------------------------------------------------------
async def run_text_mode(
    session: Session,
    persona: ManagerPersona,
    max_turns: int = 6,
    initial_utterance: str | None = None,
) -> None:
    """Conversation via stdin/stdout. Same trace-event shape as voice mode.

    When *initial_utterance* is provided, turn 0 uses that string instead
    of reading from stdin. Subsequent turns read from stdin as normal.
    """
    print("Text mode. Type a message to Alasdair (pub manager); blank line to quit.")
    print(f"Session: {session.session_id}")
    print("-" * 60)

    for turn_idx in range(max_turns):
        # On turn 0, use the injected utterance if provided.
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


# ---------------------------------------------------------------------------
# Voice mode — Speechmatics STT + Speechmatics TTS
# ---------------------------------------------------------------------------
async def run_voice_mode(
    session: Session,
    persona: ManagerPersona,
    max_turns: int = 6,
    initial_utterance: str | None = None,
) -> None:
    """Voice mode. Real mic capture -> Speechmatics STT -> manager -> Speechmatics TTS.

    When *initial_utterance* is provided, turn 0 uses that string instead
    of capturing from the mic. The utterance is also spoken via TTS before
    being sent to the persona.
    """

    # ── preflight: keys + deps ─────────────────────────────────────
    speechmatics_key = os.environ.get("SPEECHMATICS_API_KEY", "").strip()

    if not speechmatics_key:
        print(
            "⚠  SPEECHMATICS_API_KEY not set — falling back to text mode.\n"
            "   Add to .env and re-run for real voice.",
            file=sys.stderr,
        )
        await run_text_mode(
            session, persona, max_turns=max_turns, initial_utterance=initial_utterance
        )
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
        await run_text_mode(
            session, persona, max_turns=max_turns, initial_utterance=initial_utterance
        )
        return

    print(f"🎙️  Voice mode. Session: {session.session_id}")
    print(f"    Speak when prompted. Silence for {SILENCE_TIMEOUT_S}s ends a turn.")
    print(f"    Max utterance: {MAX_UTTERANCE_S}s. Say 'goodbye' to end.")
    print("-" * 60)

    for turn_idx in range(max_turns):
        # ── turn 0 with injected utterance: skip mic + STT ─────────
        if turn_idx == 0 and initial_utterance is not None:
            user_text = initial_utterance
            print(f"\n[turn {turn_idx + 1}] (injected) you> {user_text}")

            # Speak the injected utterance via TTS so the user hears it.
            try:
                await _speak_speechmatics(user_text, speechmatics_key, sd)
            except Exception as e:  # noqa: BLE001
                print(f"   ⚠ TTS for initial utterance failed: {e} (continuing)", file=sys.stderr)
        else:
            print(f"\n[turn {turn_idx + 1}] 🎤 listening...")

            # ── capture audio ──────────────────────────────────────────
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

            # ── transcribe via Speechmatics ────────────────────────────
            try:
                user_text = await _transcribe_speechmatics(
                    audio_bytes,
                    speechmatics_key,
                )
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

        # ── get manager reply ──────────────────────────────────────
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

        # ── speak reply via Speechmatics TTS ──────────────────────
        try:
            await _speak_speechmatics(manager_text, speechmatics_key, sd)
        except Exception as e:  # noqa: BLE001
            print(f"   ⚠ TTS playback failed: {e} (continuing)", file=sys.stderr)

    print("-" * 60)
    print(f"Conversation ended. Trace: {session.trace_path}")


# ---------------------------------------------------------------------------
# Audio capture
# ---------------------------------------------------------------------------
def _record_until_silence(sd, session: Session, turn: int) -> bytes:
    """Record from the default mic until SILENCE_TIMEOUT_S of silence or
    MAX_UTTERANCE_S hit. Returns raw 16-bit PCM @ SAMPLE_RATE mono.

    Uses a simple RMS threshold — fine for quiet rooms, may need bumping
    in noisy ones. Writes the captured audio to session/workspace/turn_<N>.wav
    for debugging.
    """
    import numpy as np

    threshold = 500  # int16 RMS amplitude below which we call it silence
    chunk_ms = 100
    chunk_samples = int(SAMPLE_RATE * chunk_ms / 1000)
    silence_chunks_needed = int(SILENCE_TIMEOUT_S * 1000 / chunk_ms)

    captured: list[bytes] = []
    silence_chunks = 0
    total_ms = 0
    speech_started = False

    with sd.InputStream(samplerate=SAMPLE_RATE, channels=CHANNELS, dtype="int16") as stream:
        while True:
            data, _overflow = stream.read(chunk_samples)
            if hasattr(data, "tobytes"):
                raw = data.tobytes()
            else:
                raw = bytes(data)
            captured.append(raw)
            total_ms += chunk_ms

            # RMS amplitude (crude VAD)
            arr = np.frombuffer(raw, dtype=np.int16)
            if arr.size == 0:
                rms = 0
            else:
                rms = int(np.sqrt(np.mean(arr.astype(np.float64) ** 2)))

            if rms >= threshold:
                speech_started = True
                silence_chunks = 0
            else:
                silence_chunks += 1

            # End conditions
            if speech_started and silence_chunks >= silence_chunks_needed:
                break
            if total_ms >= MAX_UTTERANCE_S * 1000:
                break
            # Grace: if no speech in first 3s, exit with empty
            if not speech_started and total_ms >= 3000:
                return b""

    audio_bytes = b"".join(captured)

    # Save for debugging
    wav_path = session.workspace_dir / f"turn_{turn}_input.wav"
    wav_path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(wav_path), "wb") as wf:
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(SAMPLE_WIDTH)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(audio_bytes)

    return audio_bytes


# ---------------------------------------------------------------------------
# Speechmatics realtime STT (speechmatics-rt SDK)
# ---------------------------------------------------------------------------
async def _transcribe_speechmatics(
    audio_bytes: bytes,
    api_key: str,
) -> str:
    """Send PCM bytes to Speechmatics RT API, collect final transcripts."""
    import io

    from speechmatics.rt import (
        AsyncClient,
        AudioEncoding,
        AudioFormat,
        ServerMessageType,
        TranscriptionConfig,
        TranscriptResult,
    )

    transcripts: list[str] = []

    audio_format = AudioFormat(
        encoding=AudioEncoding.PCM_S16LE,
        sample_rate=SAMPLE_RATE,
    )
    trans_config = TranscriptionConfig(
        language="en",
        enable_partials=False,
        max_delay=1.5,
    )

    async with AsyncClient(api_key=api_key) as client:

        @client.on(ServerMessageType.ADD_TRANSCRIPT)
        def _on_final(message: dict) -> None:
            result = TranscriptResult.from_message(message)
            transcripts.append(result.metadata.transcript)

        stream = io.BytesIO(audio_bytes)
        await client.transcribe(
            stream,
            transcription_config=trans_config,
            audio_format=audio_format,
        )

    return " ".join(transcripts).strip()


# ---------------------------------------------------------------------------
# Speechmatics TTS + playback
# ---------------------------------------------------------------------------
async def _speak_speechmatics(text: str, api_key: str, sd) -> None:
    """Generate speech via Speechmatics TTS and play raw PCM through speakers."""
    import numpy as np
    from speechmatics.tts import AsyncClient, OutputFormat, Voice

    async with AsyncClient(api_key=api_key) as client:
        response = await client.generate(
            text=text,
            voice=Voice.THEO,
            output_format=OutputFormat.RAW_PCM_16000,
        )
        pcm_bytes = await response.read()

    samples = np.frombuffer(pcm_bytes, dtype=np.int16)
    sd.play(samples, samplerate=SAMPLE_RATE)
    sd.wait()


__all__ = ["run_text_mode", "run_voice_mode"]
