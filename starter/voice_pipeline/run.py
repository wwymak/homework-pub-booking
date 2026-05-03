"""Ex8 — voice pipeline runner."""

from __future__ import annotations

import asyncio
import os
import sys

from sovereign_agent._internal.paths import user_data_dir
from sovereign_agent.session.directory import create_session

from starter._trace_stream import enable_trace_streaming
from starter.voice_pipeline.manager_persona import ManagerPersona
from starter.voice_pipeline.voice_loop import run_text_mode, run_voice_mode


async def main_async(voice: bool) -> int:
    sessions_root = user_data_dir() / "homework" / "ex8"
    sessions_root.mkdir(parents=True, exist_ok=True)

    session = create_session(
        scenario="ex8-voice-pipeline",
        task="Converse with Alasdair MacLeod (pub manager) to arrange a booking.",
        sessions_dir=sessions_root,
    )
    print(f"Session {session.session_id}")
    print(f"  dir: {session.directory}")
    enable_trace_streaming(session)

    if not os.environ.get("NEBIUS_KEY"):
        print("✗ NEBIUS_KEY not set. Run 'make verify' first.", file=sys.stderr)
        return 1

    persona = ManagerPersona.from_env()

    if voice:
        await run_voice_mode(session, persona)
    else:
        await run_text_mode(session, persona)

    return 0


def main() -> None:
    voice = "--voice" in sys.argv
    # --text is the default and can also be passed explicitly
    sys.exit(asyncio.run(main_async(voice=voice)))


if __name__ == "__main__":
    main()
