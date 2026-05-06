"""Ex8 -- end-to-end pipeline runner.

Chains: ex5 research (loop half) -> ex7 handoff bridge -> ex6 Rasa
validation -> ex8 voice/text manager conversation.

Modes:
  default:  scripted FakeLLMClient + mock Rasa + text mode
  --real:   live Nebius LLM + real Rasa + text mode
  --voice:  scripted + Speechmatics STT/TTS
  --real --voice: full live pipeline
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

from sovereign_agent._internal.llm_client import (
    ChatMessage,
    FakeLLMClient,
    LLMClient,
    OpenAICompatibleClient,
    ScriptedResponse,
    ToolCall,
)
from sovereign_agent._internal.paths import user_data_dir
from sovereign_agent.executor import DefaultExecutor
from sovereign_agent.halves.loop import LoopHalf
from sovereign_agent.planner import DefaultPlanner
from sovereign_agent.session.directory import Session, create_session

from starter._trace_stream import enable_trace_streaming
from starter.edinburgh_research.tools import build_tool_registry
from starter.handoff_bridge.bridge import BridgeResult, HandoffBridge
from starter.rasa_half.structured_half import RasaStructuredHalf, spawn_mock_rasa
from starter.voice_pipeline.manager_persona import ManagerPersona

_VENUE_DISPLAY_NAMES: dict[str, str] = {
    "haymarket_tap": "Haymarket Tap",
    "royal_oak": "The Royal Oak",
    "sheep_heid": "The Sheep Heid Inn",
    "bennets_bar": "Bennet's Bar",
    "cafe_royal": "Cafe Royal",
}


def format_booking_utterance(bridge_result: BridgeResult) -> str:
    """Format confirmed booking details as a natural first-turn utterance."""
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
        f"Hi, I'd like to book {venue_name} for {party_size} people "
        f"on {date} at {time}. "
        f"We'd put down a £{deposit} deposit."
    )


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
            async with AsyncClient(api_key=speechmatics_key) as tts_client:
                response = await tts_client.generate(
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

    mode = "voice" if voice else "text"
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
                "payload": {"text": researcher_text, "turn": turn_idx, "mode": mode},
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
                "payload": {"text": manager_text, "turn": turn_idx, "mode": mode},
            }
        )

        # Check if manager said goodbye
        if _is_goodbye(manager_text):
            print("   (manager ended the conversation)")
            break

        # Last turn — don't generate a researcher response
        if turn_idx >= max_turns - 1:
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
            # Let the researcher's goodbye be the next turn's utterance
            continue

    print("-" * 60)
    print(f"Conversation ended. Trace: {session.trace_path}")


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


def _build_scripted_client() -> FakeLLMClient:
    """Single-round success matching the README scenario.

    Party of 6, Haymarket, 19:30, bar_snacks. calculate_cost returns
    deposit_required_gbp=111 (under 300 cap). Mock Rasa confirms.
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


def _build_researcher_client() -> tuple[OpenAICompatibleClient, str]:
    """Build the LLM client for the research agent."""
    client = OpenAICompatibleClient(
        base_url="https://api.tokenfactory.nebius.com/v1/",
        api_key_env="NEBIUS_KEY",
    )
    return client, "meta-llama/Llama-3.3-70B-Instruct"


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


def main() -> None:
    """Entry point. Parses --voice and --real flags from sys.argv."""
    voice = "--voice" in sys.argv
    real = "--real" in sys.argv
    sys.exit(asyncio.run(run_e2e(voice=voice, real=real)))


if __name__ == "__main__":
    main()
