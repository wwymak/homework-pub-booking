"""Custom Rasa actions for the homework.

This file runs inside the Rasa action-server container. It imports
from rasa_sdk which is only available inside that environment — do
NOT try to run this file from your homework venv.

ActionValidateBooking is the one you need to implement.
"""

from __future__ import annotations

from typing import Any

# rasa_sdk is provided by the Rasa container, not the homework venv.
# Your IDE may complain about these imports outside the container.
from rasa_sdk import Action, Tracker  # type: ignore[import-not-found]
from rasa_sdk.events import SlotSet  # type: ignore[import-not-found]
from rasa_sdk.executor import CollectingDispatcher  # type: ignore[import-not-found]


# Rules — see ASSIGNMENT.md §Ex6 and sample_data/catering.json.
MAX_PARTY_SIZE_FOR_AUTO_BOOKING = 8
MAX_DEPOSIT_FOR_AUTO_BOOKING_GBP = 300


class ActionValidateBooking(Action):
    """Validate the proposed booking. Returns one of:

    * Success: SlotSet("validation_error", None), plus a booking_reference.
    * Rejection: SlotSet("validation_error", "<reason>").

    The reason string is the one propagated to the user AND back to
    RasaStructuredHalf via the response message.

    Rules (for convenience):
      * party_size > 8            → reject with "party_too_large"
      * deposit_gbp > 300         → reject with "deposit_too_high"
      * missing required field    → reject with "missing_<field>"
      * otherwise                 → success

    IMPORTANT — read booking data from metadata, not slots:

        latest = tracker.latest_message or {}
        meta = latest.get("metadata") or {}
        booking = meta.get("booking") or {}
        venue_id = booking.get("venue_id")
        ...

    CALM's LLM command generator starts the flow from /confirm_booking
    but does NOT automatically read metadata into slots. That's your
    job. Set the slots yourself at the end so downstream responses
    can interpolate {venue_id}, {booking_reference}, etc.
    """

    def name(self) -> str:
        return "action_validate_booking"

    def run(
        self,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: dict[str, Any],
    ) -> list[dict[str, Any]]:
        # Slots are pulled from the tracker. See domain.yml for the schema.
        party_size = tracker.get_slot("party_size")
        deposit_gbp = tracker.get_slot("deposit_gbp")
        venue_id = tracker.get_slot("venue_id")
        date = tracker.get_slot("date")
        time = tracker.get_slot("time")

        # TODO: validate each field per the rules above and set the
        # validation_error slot accordingly.
        #
        # Use SlotSet("validation_error", "<reason>") for a rejection,
        # or SlotSet("validation_error", None) + SlotSet("booking_reference", "BK-...")
        # for a success.
        #
        # Example happy path:
        #   import hashlib
        #   ref = "BK-" + hashlib.sha1(
        #       f"{venue_id}|{date}|{time}|{party_size}".encode()
        #   ).hexdigest()[:8].upper()
        #   return [
        #       SlotSet("validation_error", None),
        #       SlotSet("booking_reference", ref),
        #   ]

        raise NotImplementedError(
            "TODO Ex6: implement ActionValidateBooking.run per the rules in "
            "the class docstring and in ASSIGNMENT.md §Ex6."
        )
