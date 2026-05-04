"""Tests for bridge zero-result handoff validation."""

from __future__ import annotations

import tempfile
from pathlib import Path

from sovereign_agent.halves import HalfResult
from sovereign_agent.session.directory import create_session

from starter.handoff_bridge.bridge import (
    build_forward_handoff,
    validate_forward_handoff,
)


def _make_session():
    td = tempfile.mkdtemp()
    sessions_dir = Path(td) / "sessions"
    sessions_dir.mkdir()
    return create_session(scenario="test", sessions_dir=sessions_dir)


class TestValidateForwardHandoff:
    def test_rejects_missing_venue_id(self) -> None:
        session = _make_session()
        loop_result = HalfResult(
            success=True,
            output={"search_results": []},
            summary="no venue found",
            next_action="handoff_to_structured",
            handoff_payload={
                "data": {
                    "action": "confirm_booking",
                    "near": "Haymarket",
                    "party_size": 12,
                    "search_results": [],
                }
            },
        )
        handoff = build_forward_handoff(session, loop_result)
        ok, reason = validate_forward_handoff(handoff)
        assert not ok
        assert "venue_id" in reason.lower()

    def test_repair_extracts_venue_id_from_loop_output(self) -> None:
        """If loop output has venue_id but handoff payload doesn't, repair."""
        from starter.handoff_bridge.bridge import _try_repair_handoff

        session = _make_session()
        loop_result = HalfResult(
            success=True,
            output={"venue_id": "royal_oak", "area": "Old Town"},
            summary="found royal_oak",
            next_action="handoff_to_structured",
            handoff_payload={"data": {"action": "confirm_booking"}},
        )
        handoff = build_forward_handoff(session, loop_result)
        repaired = _try_repair_handoff(handoff, loop_result)
        ok, _ = validate_forward_handoff(repaired)
        assert ok
        assert repaired.data["venue_id"] == "royal_oak"

    def test_accepts_valid_handoff(self) -> None:
        session = _make_session()
        loop_result = HalfResult(
            success=True,
            output={"venue": "haymarket_tap"},
            summary="found venue",
            next_action="handoff_to_structured",
            handoff_payload={
                "data": {
                    "action": "confirm_booking",
                    "venue_id": "haymarket_tap",
                    "date": "2026-04-25",
                    "time": "19:30",
                    "party_size": 6,
                    "deposit": "£0",
                }
            },
        )
        handoff = build_forward_handoff(session, loop_result)
        ok, reason = validate_forward_handoff(handoff)
        assert ok
        assert reason == ""

    def test_rejects_empty_venue_id(self) -> None:
        session = _make_session()
        loop_result = HalfResult(
            success=True,
            output={},
            summary="",
            next_action="handoff_to_structured",
            handoff_payload={
                "data": {
                    "venue_id": "",
                    "date": "2026-04-25",
                    "time": "19:30",
                    "party_size": 6,
                }
            },
        )
        handoff = build_forward_handoff(session, loop_result)
        ok, reason = validate_forward_handoff(handoff)
        assert not ok

    def test_rejects_none_data(self) -> None:
        session = _make_session()
        loop_result = HalfResult(
            success=True,
            output={},
            summary="",
            next_action="handoff_to_structured",
            handoff_payload={"reason": "no results"},
        )
        handoff = build_forward_handoff(session, loop_result)
        ok, reason = validate_forward_handoff(handoff)
        assert not ok

    def test_repair_extracts_from_complete_task_tool_calls(self) -> None:
        """When the LLM calls complete_task, venue data is in tool call args."""
        from starter.handoff_bridge.bridge import _try_repair_handoff

        session = _make_session()
        loop_result = HalfResult(
            success=True,
            output={
                "final_answer": "Booked The Royal Oak",
                "executor_results": [
                    {
                        "subgoal_id": "sg_1",
                        "success": True,
                        "final_answer": "",
                        "turns_used": 3,
                        "tool_calls_made": [
                            {
                                "name": "venue_search",
                                "arguments": {"near": "Old Town", "party_size": 12},
                                "success": True,
                                "summary": "1 result(s)",
                            },
                            {
                                "name": "complete_task",
                                "arguments": {
                                    "result": {
                                        "venue_id": "The Royal Oak",
                                        "date": "2026-04-25",
                                        "time": "19:30",
                                        "party_size": 12,
                                    }
                                },
                                "success": True,
                                "summary": "session marked complete",
                            },
                        ],
                    }
                ],
            },
            summary="found royal_oak",
            next_action="handoff_to_structured",
            handoff_payload={"data": {"final_answer": "Booked The Royal Oak"}},
        )
        handoff = build_forward_handoff(session, loop_result)
        repaired = _try_repair_handoff(handoff, loop_result)
        ok, _ = validate_forward_handoff(repaired)
        assert ok
        assert repaired.data["venue_id"] == "The Royal Oak"
        assert repaired.data["party_size"] == 12
