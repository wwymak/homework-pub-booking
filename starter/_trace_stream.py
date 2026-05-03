"""Trace event streaming — prints session trace events to stderr in real time.

Call ``enable_trace_streaming(session)`` after creating a session to get
live console output from planner, executor, and bridge events. Works with
any exercise (ex5–ex8).
"""

from __future__ import annotations

import json
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sovereign_agent.session.directory import Session

_COLOURS = {
    "bridge": "\033[36m",
    "planner": "\033[33m",
    "executor": "\033[32m",
    "session": "\033[35m",
    "reset": "\033[0m",
}


def _colour(tag: str, text: str) -> str:
    """Wrap *text* in ANSI colour based on *tag*."""
    c = _COLOURS.get(tag, "")
    return f"{c}{text}{_COLOURS['reset']}" if c else text


def format_trace_event(event: dict) -> str:
    """Format a single trace event dict into a human-readable line."""
    etype = event.get("event_type", "unknown")
    payload = event.get("payload") or {}

    if etype == "bridge.round_start":
        half = payload.get("half", "?")
        rnd = payload.get("round", "?")
        return _colour("bridge", f"[bridge] round {rnd} starting (half={half})")

    if etype == "planner.called":
        preview = payload.get("task_preview", "")[:80]
        return _colour("planner", f"[planner] planning: {preview}")

    if etype == "planner.produced_subgoals":
        n = payload.get("num_subgoals", "?")
        return _colour("planner", f"[planner] produced {n} subgoal(s)")

    if etype == "bridge.implicit_handoff":
        reason = payload.get("reason", "?")
        return _colour("bridge", f"[bridge] implicit handoff: {reason}")

    if etype == "bridge.handoff_rejected":
        reason = payload.get("reason", "?")
        rnd = payload.get("round", "?")
        return _colour("bridge", f"[bridge] handoff rejected in round {rnd}: {reason}")

    if etype == "executor.tool_called":
        ok = payload.get("success", False)
        summary = payload.get("summary", "")
        marker = "ok" if ok else "FAIL"
        return _colour("executor", f"[executor] {summary} [{marker}]")

    if etype == "session.state_changed":
        src = payload.get("from", "?")
        dst = payload.get("to", "?")
        rnd = payload.get("round", "")
        reason = payload.get("rejection_reason", "")
        parts = [f"[session] {src} -> {dst}"]
        if rnd:
            parts.append(f"round {rnd}")
        if reason:
            parts.append(f"rejected: {reason}")
        return _colour("session", " | ".join(parts))

    return f"[{etype}] {json.dumps(payload, default=str)[:120]}"


def enable_trace_streaming(session: Session) -> None:
    """Monkey-patch *session.append_trace_event* to also print to stderr."""
    original = session.append_trace_event

    def _streaming_append(event: dict) -> None:
        original(event)
        try:
            line = format_trace_event(event)
            print(line, file=sys.stderr, flush=True)
        except Exception:
            pass

    session.append_trace_event = _streaming_append  # type: ignore[method-assign]


__all__ = ["enable_trace_streaming", "format_trace_event"]
