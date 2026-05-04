"""Ex7 — handoff bridge.

Routes between the loop half and the Rasa-backed structured half,
supporting REVERSE handoffs (structured → loop) when the structured
half rejects.

The base sovereign-agent LoopHalf only knows how to request a handoff
FORWARD. The bridge you're building here is the thing that decides
what to do when the structured half says "no, go back and try again".
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal

from sovereign_agent.halves import HalfResult
from sovereign_agent.halves.loop import LoopHalf
from sovereign_agent.halves.structured import StructuredHalf
from sovereign_agent.handoff import Handoff
from sovereign_agent.session.directory import Session
from sovereign_agent.session.state import now_utc

log = logging.getLogger(__name__)

BridgeOutcome = Literal["completed", "failed", "max_rounds_exceeded"]


@dataclass
class BridgeResult:
    outcome: BridgeOutcome
    rounds: int
    final_half_result: HalfResult | None
    summary: str


class HandoffBridge:
    """Orchestrates round-trips between LoopHalf and a StructuredHalf.

    Not a sovereign-agent Half itself — it lives one level up, deciding
    which half should run next.
    """

    def __init__(
        self,
        *,
        loop_half: LoopHalf,
        structured_half: StructuredHalf,
        max_rounds: int = 3,
    ) -> None:
        self.loop_half = loop_half
        self.structured_half = structured_half
        self.max_rounds = max_rounds

    # ------------------------------------------------------------------
    # TODO — the main run method
    # ------------------------------------------------------------------
    async def run(self, session: Session, initial_task: dict) -> BridgeResult:
        """Run the bridge until the session completes, fails, or hits max_rounds."""
        from sovereign_agent.handoff import write_handoff

        rounds = 0
        current_input: dict = initial_task
        last_loop = last_struct = None

        while rounds < self.max_rounds:
            rounds += 1
            session.append_trace_event(
                {
                    "event_type": "bridge.round_start",
                    "actor": "bridge",
                    "payload": {"round": rounds, "half": "loop"},
                }
            )
            loop_result = await self.loop_half.run(session, current_input)
            last_loop = loop_result

            if loop_result.next_action == "complete":
                # The loop thinks it's done, but in bridge mode the
                # structured half (Rasa) must confirm before we accept.
                # Treat this as an implicit forward handoff.
                log.info(
                    "bridge: loop returned 'complete' — treating as "
                    "implicit handoff to structured half for confirmation"
                )
                session.append_trace_event(
                    {
                        "event_type": "bridge.implicit_handoff",
                        "actor": "bridge",
                        "payload": {
                            "round": rounds,
                            "reason": "loop returned complete; "
                            "routing to structured half for confirmation",
                        },
                    }
                )
                # Synthesise a handoff_payload from the loop output.
                # When the LLM calls complete_task, structured booking
                # data is buried in tool call history, not at the top
                # level — extract it so the handoff carries real data.
                extracted = _extract_booking_from_tool_calls(loop_result.output or {})
                handoff_data = extracted if extracted.get("venue_id") else loop_result.output
                loop_result = HalfResult(
                    success=loop_result.success,
                    output=loop_result.output,
                    summary=loop_result.summary,
                    next_action="handoff_to_structured",
                    handoff_payload={"data": handoff_data},
                )

            if loop_result.next_action not in (
                "handoff_to_structured",
                "escalate",
            ):
                session.mark_failed(f"unexpected loop outcome: {loop_result.next_action}")
                return BridgeResult(
                    outcome="failed",
                    rounds=rounds,
                    final_half_result=loop_result,
                    summary=f"unexpected loop outcome: {loop_result.next_action}",
                )

            if loop_result.next_action == "escalate":
                session.mark_failed(f"loop half escalated: {loop_result.summary}")
                return BridgeResult(
                    outcome="failed",
                    rounds=rounds,
                    final_half_result=loop_result,
                    summary=f"loop half escalated: {loop_result.summary}",
                )

            handoff = build_forward_handoff(session, loop_result)
            handoff = _try_repair_handoff(handoff, loop_result)

            valid, rejection = validate_forward_handoff(handoff)
            if not valid:
                log.info("bridge: skipping structured half — %s", rejection)
                session.append_trace_event(
                    {
                        "event_type": "bridge.handoff_rejected",
                        "actor": "bridge",
                        "payload": {
                            "round": rounds,
                            "reason": rejection,
                        },
                    }
                )
                current_input = _build_constraint_relaxation_task(loop_result, rejection)
                session.append_trace_event(
                    {
                        "event_type": "session.state_changed",
                        "actor": "bridge",
                        "payload": {
                            "from": "loop",
                            "to": "loop",
                            "round": rounds,
                            "rejection_reason": rejection,
                        },
                    }
                )
                continue

            write_handoff(session, "structured", handoff)
            session.append_trace_event(
                {
                    "event_type": "session.state_changed",
                    "actor": "bridge",
                    "payload": {"from": "loop", "to": "structured", "round": rounds},
                }
            )

            struct_result = await self.structured_half.run(session, {"data": handoff.data})
            last_struct = struct_result

            if struct_result.next_action == "complete":
                session.mark_complete(struct_result.output)
                session.append_trace_event(
                    {
                        "event_type": "session.state_changed",
                        "actor": "bridge",
                        "payload": {"from": "structured", "to": "complete", "round": rounds},
                    }
                )
                return BridgeResult(
                    outcome="completed",
                    rounds=rounds,
                    final_half_result=struct_result,
                    summary=f"structured confirmed in round {rounds}",
                )

            if struct_result.next_action == "escalate":
                current_input = build_reverse_task(loop_result, struct_result)
                session.append_trace_event(
                    {
                        "event_type": "session.state_changed",
                        "actor": "bridge",
                        "payload": {
                            "from": "structured",
                            "to": "loop",
                            "round": rounds,
                            "rejection_reason": (struct_result.output or {}).get("reason")
                            or struct_result.summary,
                        },
                    }
                )
                forward_file = session.ipc_input_dir / "handoff_to_structured.json"
                if forward_file.exists():
                    archive = session.handoffs_audit_dir / f"round_{rounds}_forward.json"
                    archive.parent.mkdir(parents=True, exist_ok=True)
                    forward_file.rename(archive)
                continue

            session.mark_failed(
                {"reason": f"unexpected struct outcome: {struct_result.next_action}"}
            )
            return BridgeResult(
                outcome="failed",
                rounds=rounds,
                final_half_result=struct_result,
                summary=f"unexpected struct outcome: {struct_result.next_action}",
            )

        session.mark_failed({"reason": f"max_rounds={self.max_rounds} exceeded"})
        final = last_struct or last_loop
        return BridgeResult(
            outcome="max_rounds_exceeded",
            rounds=rounds,
            final_half_result=final,
            summary=f"bridge exhausted {self.max_rounds} rounds without resolution",
        )


# ---------------------------------------------------------------------------
# Helper constructors — you may use these or write your own
# ---------------------------------------------------------------------------
def build_forward_handoff(session: Session, loop_result: HalfResult) -> Handoff:
    """Package a loop result into a forward-handoff payload for structured."""
    return Handoff(
        from_half="loop",
        to_half="structured",
        written_at=now_utc(),
        session_id=session.session_id,
        reason="loop-half requested confirmation",
        context=loop_result.summary,
        data=(loop_result.handoff_payload or {}).get("data") or loop_result.output,
        return_instructions=(
            "If you cannot confirm (party too large, deposit too high, etc.), "
            "respond with next_action=escalate and include a human-readable "
            "'reason' in output so the loop half can adapt."
        ),
    )


def _extract_booking_from_tool_calls(output: dict) -> dict:
    """Extract structured booking data from executor tool call history.

    When the LLM calls ``complete_task`` instead of ``handoff_to_structured``,
    the venue data ends up buried inside ``executor_results[*].tool_calls_made``
    rather than at the top level of ``output``.
    """
    booking: dict = {}
    for er in output.get("executor_results") or []:
        for tc in er.get("tool_calls_made") or []:
            args = tc.get("arguments") or {}
            name = tc.get("name", "")

            if name == "complete_task":
                result = args.get("result") or args
                if isinstance(result, dict):
                    for k in (
                        "venue_id",
                        "date",
                        "time",
                        "party_size",
                        "deposit",
                        "deposit_required_gbp",
                        "area",
                        "name",
                    ):
                        if k in result and k not in booking:
                            booking[k] = result[k]

            elif name == "handoff_to_structured":
                data = args.get("data") or {}
                if isinstance(data, dict):
                    for k in (
                        "venue_id",
                        "date",
                        "time",
                        "party_size",
                        "deposit",
                        "deposit_required_gbp",
                        "area",
                        "name",
                    ):
                        if k in data and k not in booking:
                            booking[k] = data[k]

            elif name == "calculate_cost":
                for k in ("venue_id", "deposit_required_gbp", "total_cost_gbp"):
                    if k in args and k not in booking:
                        booking[k] = args[k]

    return booking


def _try_repair_handoff(handoff: Handoff, loop_result: HalfResult) -> Handoff:
    """If the handoff data is missing venue_id but loop_result has it, repair."""
    data = handoff.data
    if isinstance(data, dict) and data.get("venue_id"):
        return handoff

    output = loop_result.output or {}

    # First try top-level output keys
    venue_id = output.get("venue_id")
    source_data = output

    # If not at top level, dig into executor tool call history
    if not venue_id:
        source_data = _extract_booking_from_tool_calls(output)
        venue_id = source_data.get("venue_id")

    if not venue_id:
        return handoff

    log.info("bridge: repairing handoff — injecting venue_id=%s from loop output", venue_id)
    repaired_data = dict(data) if isinstance(data, dict) else {}
    repaired_data["venue_id"] = venue_id
    for key in ("date", "time", "party_size", "deposit", "deposit_required_gbp", "area", "name"):
        if key in source_data and key not in repaired_data:
            repaired_data[key] = source_data[key]

    handoff.data = repaired_data
    return handoff


def validate_forward_handoff(handoff: Handoff) -> tuple[bool, str]:
    """Check that a forward handoff carries enough data for the structured half.

    Returns ``(True, "")`` when valid, ``(False, reason)`` otherwise.
    """
    data = handoff.data
    if not isinstance(data, dict):
        return False, "handoff data is not a dict"
    venue_id = data.get("venue_id")
    if not venue_id or (isinstance(venue_id, str) and not venue_id.strip()):
        return False, (
            "missing venue_id in handoff data. You MUST include the "
            "venue_id from your search results in the handoff data dict. "
            "If no venues were found, try a different area or relax "
            "party_size — but only one constraint at a time."
        )
    return True, ""


def _build_constraint_relaxation_task(loop_result: HalfResult, rejection: str) -> dict:
    """Build a task dict that tells the loop half to retry with relaxed constraints."""
    return {
        "task": (
            f"The previous search returned no usable venue. {rejection}\n\n"
            "RULES FOR RETRYING:\n"
            "1. Relax ONE constraint at a time. Keep the original party_size "
            "and try different areas first.\n"
            "2. Valid venue areas: Haymarket, Old Town, Duddingston, Tollcross, "
            "New Town. Use these EXACT names — 'Edinburgh' is NOT a valid area.\n"
            "3. Only reduce party_size as a LAST RESORT after trying all areas.\n"
            "4. When you find a venue, call calculate_cost to get the deposit, "
            "then call handoff_to_structured with the venue data INCLUDING "
            "venue_id, date, time, party_size, and deposit in the 'data' dict.\n"
            "5. Do NOT call complete_task — the structured half confirms."
        ),
        "context": {
            "prior_result": loop_result.output,
            "rejection_reason": rejection,
            "retry": True,
            "valid_areas": ["Haymarket", "Old Town", "Duddingston", "Tollcross", "New Town"],
        },
    }


def build_reverse_task(loop_result: HalfResult, struct_result: HalfResult) -> dict:
    """Build the task dict to pass back to the loop half after a reject."""
    reason = struct_result.output.get("reason") or struct_result.summary
    reason_lower = reason.lower()

    guidance = ""
    if "party_too_large" in reason_lower:
        guidance = (
            "\nThe booking system rejected the party size as too large. "
            "Reduce party_size in your next proposal."
        )
    elif "deposit_too_high" in reason_lower:
        guidance = (
            "\nThe booking system rejects deposits over £300. "
            "Find a cheaper venue or reduce duration/catering tier."
        )
    elif "party_too_small" in reason_lower:
        guidance = "\nThe booking system requires a minimum party size of 4."

    return {
        "task": (
            "The structured half rejected the previous proposal. "
            f"Reason: {reason}.{guidance}\n\n"
            "Produce an alternative. Use venue_search, then calculate_cost, "
            "then handoff_to_structured with the corrected data. "
            "Do NOT call complete_task."
        ),
        "context": {
            "prior_result": loop_result.output,
            "rejection_reason": reason,
            "retry": True,
        },
    }


__all__ = [
    "BridgeOutcome",
    "BridgeResult",
    "HandoffBridge",
    "build_forward_handoff",
    "build_reverse_task",
    "validate_forward_handoff",
]
