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
