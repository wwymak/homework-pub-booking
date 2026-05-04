# Ex7 Handoff Bridge -- Changes and Decisions

## Overview

Ex7 builds the `HandoffBridge` -- an orchestrator that routes between the
research agent (loop half) and Rasa CALM (structured half) for pub booking
confirmation. The bridge mediates round-trips: the loop half proposes a venue,
the structured half validates it against business rules, and if rejected, the
bridge sends the loop half back to try again with guidance about what went wrong.

The prefilled code had several issues: the bridge crashed on zero-result
searches, the loop half could bypass Rasa entirely, constraint relaxation was
too aggressive, and the LLM received no feedback about why proposals were
rejected. Additionally, there was no real-time visibility into what the agent
was doing, and the ex7 scenario conflicted with ex6's Rasa party size rules.

## Bugs Found and Fixed

### 1. Zero-result handoff crash

**The bug:** When `venue_search` returned zero results, the LLM would call
`handoff_to_structured` without a `venue_id`. The structured half's
`normalise_booking_payload` raised "missing venue_id", crashing the run.

**Fix:** Added `validate_forward_handoff(handoff)` in the bridge. Before
routing to the structured half, the bridge checks that `handoff.data` is a dict
containing a non-empty `venue_id`. If validation fails, the bridge skips the
structured half and sends the loop back to retry with a constraint relaxation
task.

Also added `_try_repair_handoff(handoff, loop_result)` as a second layer of
defence. If the handoff payload is missing `venue_id` but the loop result's
output contains it (common when the LLM puts data in the wrong place), the
bridge repairs the handoff by extracting venue data from the loop output.

### 2. Loop half bypassing Rasa (calling complete_task directly)

**The bug:** When the loop half found a venue, it sometimes called
`complete_task` instead of `handoff_to_structured`. The bridge accepted
`next_action="complete"` and returned immediately, meaning Rasa's business rules
(party size limits, deposit caps) were never checked.

**Fix:** The bridge now treats `next_action="complete"` from the loop half as an
implicit forward handoff. It synthesises a `HalfResult` with
`next_action="handoff_to_structured"` and routes through the structured half for
confirmation. The bridge logs this as a `bridge.implicit_handoff` trace event.

**Decision -- why intercept at the bridge, not fix the executor:** The executor
system prompt now tells the LLM to use `handoff_to_structured` instead of
`complete_task`, but LLMs don't always follow instructions. The bridge-level
intercept is a safety net that guarantees Rasa validation regardless of LLM
behaviour.

### 3. LLM searching invalid areas

**The bug:** The venue database only contains venues in specific Edinburgh
areas (Haymarket, Old Town, Duddingston, Tollcross, New Town). The LLM would
search for "Edinburgh" as an area, which matched nothing, then spiral through
other invalid area names.

**Fix:** Updated `venue_search` in `starter/edinburgh_research/tools.py` to
include exact valid area names in the zero-result hint. The hint now
differentiates between "area not found" (suggests valid area names) and "area
found but party too large" (reports the largest capacity in that area).

### 4. LLM relaxing all constraints at once

**The bug:** When retrying after a failed search, the LLM would drop party size
from 12 to 2 and change the area simultaneously. This defeated the purpose of
constraint relaxation.

**Fix:** Added `_build_constraint_relaxation_task()` in the bridge with explicit
guidance: "Relax ONE constraint at a time. Keep the original party_size and try
different areas first. Only reduce party_size as a LAST RESORT." The task also
lists the exact valid area names.

### 5. LLM stuck retrying party_size=12 after rejection

**The bug:** `build_reverse_task()` only said "Produce an alternative" without
explaining why the structured half rejected the proposal. The LLM would
re-propose the same party size and get rejected in a loop.

**Fix:** `build_reverse_task()` now parses the rejection reason and includes
specific guidance:
- `party_too_large` -- "The booking system rejected the party size as too large.
  Reduce party_size in your next proposal."
- `deposit_too_high` -- "The booking system rejects deposits over £300."
- `party_too_small` -- "The booking system requires a minimum party size of 4."

### 6. Task hardcoded in bridge.run()

**The bug:** The booking task string was hardcoded inside `bridge.run()`,
meaning the bridge could only ever run one scenario.

**Fix:** Moved the task to `create_session(task=...)` as user input. The bridge
receives the task via `initial_task` parameter. Workflow guidance (use
venue_search, then calculate_cost, then handoff_to_structured) was moved to the
executor system prompt, where it belongs.

### 7. Ex7 vs ex6 Rasa max party size conflict

**The bug:** Ex6 enforces `MAX_PARTY_SIZE_FOR_AUTO_BOOKING = 8`, but ex7's
scenario involves a party of 12. Running ex7 against real Rasa would always
reject, since the action server enforced the ex6 limit.

**Fix:** Made the max party size configurable at three levels:
- **Mock server:** `spawn_mock_rasa()` now accepts a `max_party_size` keyword
  argument (default 8). `_MockRasaHandler` reads it from the server instance
  via `getattr(self.server, "max_party_size", 8)`.
- **Real Rasa action server:** `rasa_project/actions/actions.py` reads
  `MAX_PARTY_SIZE_FOR_AUTO_BOOKING` from `os.environ.get("MAX_PARTY_SIZE", "8")`.
  Defaults to 8 (ex6 behaviour) when unset.
- **Makefile:** Added `make rasa-actions-ex7` target that starts the action
  server with `MAX_PARTY_SIZE=16`. The `ex7-real` target also sets the env var
  for the bridge process. **Important:** the env var must be set on the *action
  server* process, not just the bridge -- the action server is a separate
  process (Terminal 1) that validates bookings. For real-mode ex7, use
  `make rasa-actions-ex7` instead of `make rasa-actions`.
- **Ex7 run.py:** Passes `max_party_size=16` to `spawn_mock_rasa()` for offline
  mode.

`build_reverse_task()` was also updated to remove the hardcoded "reduce to 8 or
fewer" guidance, replaced with a generic "rejected the party size as too large"
message that works regardless of the configured limit.

## New Features

### 8. Real-time trace streaming (`starter/_trace_stream.py`)

**What:** A reusable utility that prints formatted trace events to stderr as
they happen, giving real-time visibility into the agent's behaviour.

**Why:** Without streaming, the only way to see what happened was to read the
trace file after the run completed. During development, this made it impossible
to see where the agent was going wrong until it finished (or crashed).

**Design:** `enable_trace_streaming(session)` monkey-patches
`session.append_trace_event` to print each event after writing it to the trace
file. `format_trace_event(event)` renders different event types with colour
codes:
- `bridge.round_start` -- round number and which half is running
- `bridge.implicit_handoff` -- loop tried to complete, rerouted to structured
- `bridge.handoff_rejected` -- handoff validation failed (e.g. missing venue_id)
- `executor.tool_called` -- tool name and result summary
- `planner.called` / `planner.produced_subgoals` -- planning activity
- `session.state_changed` -- transitions between halves, with rejection reasons

**Scope:** Wired into all exercises (ex5 through ex8), not just ex7.

### 9. Handoff validation and repair

**What:** Two new functions in the bridge:
- `validate_forward_handoff(handoff)` -- returns `(bool, reason)` checking for
  valid `venue_id`
- `_try_repair_handoff(handoff, loop_result)` -- extracts venue data from loop
  output if the handoff payload is empty

**Why:** LLMs frequently put booking data in the wrong place (in the output dict
instead of the handoff payload) or omit fields entirely. Rather than crashing,
the bridge attempts repair first, then validates, and only retries if repair
also fails.

## Files Modified

| File | Changes |
|---|---|
| `starter/handoff_bridge/bridge.py` | Core bridge logic: implicit handoff intercept, handoff validation/repair, constraint relaxation task, reverse task with rejection guidance, generic party size message |
| `starter/handoff_bridge/run.py` | Task moved to `create_session`, executor system prompt with workflow guidance, `max_party_size=16` for mock, `enable_trace_streaming` |
| `starter/_trace_stream.py` | New file: `format_trace_event`, `enable_trace_streaming` |
| `starter/edinburgh_research/tools.py` | Zero-result hints with valid area names, area-vs-capacity differentiation |
| `starter/edinburgh_research/run.py` | Added `enable_trace_streaming(session)` |
| `starter/rasa_half/structured_half.py` | `_MockRasaHandler` reads `max_party_size` from server; `spawn_mock_rasa` accepts `max_party_size` kwarg |
| `starter/rasa_half/run.py` | Added `enable_trace_streaming(session)` |
| `starter/voice_pipeline/run.py` | Added `enable_trace_streaming(session)` |
| `rasa_project/actions/actions.py` | `MAX_PARTY_SIZE_FOR_AUTO_BOOKING` reads from `MAX_PARTY_SIZE` env var |
| `Makefile` | `ex7-real` target sets `MAX_PARTY_SIZE=16`; new `rasa-actions-ex7` target for action server with higher limit |

## Tests Added

| File | Tests |
|---|---|
| `tests/public/test_bridge_zero_results.py` | 5 tests: validates `validate_forward_handoff` rejects missing/empty venue_id, accepts valid handoff, and `_try_repair_handoff` extracts venue_id from loop output |
| `tests/public/test_trace_stream.py` | 7 tests: `format_trace_event` for each event type, `enable_trace_streaming` prints events and still writes to file |

## Test Results

- 45/45 public tests pass, 0 skipped
- Offline `make ex7` completes in 1 round (mock accepts party_size=12 with limit=16)

## Design Decisions

### Bridge as safety net, not just router

The bridge enforces invariants that the LLM can't be trusted to maintain:
- Every proposal goes through Rasa (no `complete_task` bypass)
- Every handoff carries a valid `venue_id` (no crash on empty data)
- Constraint relaxation is one-at-a-time (no dropping party from 12 to 2)

This makes the system resilient to LLM prompt-following failures without
requiring perfect prompt engineering.

### Configurable limits via env var

Using `MAX_PARTY_SIZE` as an env var rather than a command-line flag keeps the
Rasa action server interface unchanged. The Makefile sets it per-exercise, and
the mock server accepts it as a constructor parameter. This means:
- Ex6 (`make ex6-real`): uses default of 8
- Ex7 (`make ex7-real`): sets 16
- Students can override for experimentation

### Trace streaming as monkey-patch

Monkey-patching `session.append_trace_event` is unconventional but has two
advantages: it requires zero changes to the sovereign-agent library, and it
guarantees that every trace event (including ones from library internals) is
streamed. A callback or observer pattern would have been cleaner but would
require modifying the Session class upstream.
