"""Tests for trace event streaming utility."""

from __future__ import annotations

import tempfile
from pathlib import Path

from sovereign_agent.session.directory import create_session

from starter._trace_stream import enable_trace_streaming, format_trace_event


def _make_session() -> tuple[object, Path]:
    td = tempfile.mkdtemp()
    sessions_dir = Path(td) / "sessions"
    sessions_dir.mkdir()
    session = create_session(scenario="test", sessions_dir=sessions_dir)
    return session, Path(td)


def test_format_bridge_round_start() -> None:
    event = {
        "event_type": "bridge.round_start",
        "actor": "bridge",
        "payload": {"round": 1, "half": "loop"},
    }
    line = format_trace_event(event)
    assert "round 1" in line.lower()
    assert "loop" in line.lower()


def test_format_executor_tool_called() -> None:
    event = {
        "event_type": "executor.tool_called",
        "actor": "default",
        "payload": {
            "tool": "venue_search",
            "arguments": {"near": "Haymarket", "party_size": 12},
            "success": True,
            "summary": "venue_search(Haymarket, party=12): 0 result(s)",
        },
    }
    line = format_trace_event(event)
    assert "venue_search" in line
    assert "0 result(s)" in line


def test_format_planner_called() -> None:
    event = {
        "event_type": "planner.called",
        "actor": "default",
        "payload": {"task_preview": "book for party of 12"},
    }
    line = format_trace_event(event)
    assert "planner" in line.lower() or "plan" in line.lower()


def test_format_session_state_changed() -> None:
    event = {
        "event_type": "session.state_changed",
        "actor": "bridge",
        "payload": {
            "from": "structured",
            "to": "loop",
            "round": 1,
            "rejection_reason": "party_too_large",
        },
    }
    line = format_trace_event(event)
    assert "structured" in line
    assert "loop" in line


def test_format_unknown_event() -> None:
    event = {"event_type": "custom.something", "payload": {"x": 1}}
    line = format_trace_event(event)
    assert "custom.something" in line


def test_enable_trace_streaming_prints_events() -> None:
    session, _ = _make_session()
    enable_trace_streaming(session)

    session.append_trace_event(
        {
            "event_type": "executor.tool_called",
            "actor": "default",
            "payload": {
                "tool": "venue_search",
                "arguments": {},
                "success": True,
                "summary": "found 2",
            },
        }
    )

    assert session.trace_path.exists()
    trace_lines = session.trace_path.read_text().strip().splitlines()
    assert len(trace_lines) == 1


def test_enable_trace_streaming_still_writes_to_file() -> None:
    session, _ = _make_session()
    enable_trace_streaming(session)

    session.append_trace_event({"event_type": "test.event", "payload": {}})
    session.append_trace_event({"event_type": "test.event2", "payload": {}})

    trace_lines = session.trace_path.read_text().strip().splitlines()
    assert len(trace_lines) == 2
