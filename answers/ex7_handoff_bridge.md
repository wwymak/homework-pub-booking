# Ex7 — Handoff bridge

## Your answer
I spent quite a bit of time with this bit to make sure it works correctly (there were initially a lot of silent failures)
There were various bridge fixes that were needed, in addition to tweaking the rasa setup from ex6 to meet with requirements of
ex7's scenarios

The most common early failure was the loop half calling `complete_task`
instead of `handoff_to_structured`, bypassing Rasa entirely
([`sess_042bada6c108`](../session_logs/examples/ex7-handoff-bridge/sess_042bada6c108/),
[`sess_dbafac2da909`](../session_logs/examples/ex7-handoff-bridge/sess_dbafac2da909/)).
The bridge now intercepts `next_action="complete"` and reroutes it as
an implicit forward handoff, extracting venue data from the tool call
history since the sovereign-agent framework buries it inside
`executor_results[*].tool_calls_made[*].arguments` rather than at the
top level. A `validate_forward_handoff` check prevents crashes when
`venue_id` is missing, and `_try_repair_handoff` extracts it from the
loop output as a fallback.

The second pattern was the LLM ignoring rejection feedback.
[`sess_f62506e9d207`](../session_logs/examples/ex7-handoff-bridge/sess_f62506e9d207/)
kept proposing party_size=12 after "party_too_large" rejections because
`build_reverse_task()` only said "produce an alternative" without
explaining why. Adding rejection-specific guidance (e.g. "reduce
party_size") and constraint relaxation rules ("relax ONE constraint at
a time") improved retry behaviour. The later successful sessions
([`sess_6f3a0e0f9d5c`](../session_logs/examples/ex7-handoff-bridge/sess_6f3a0e0f9d5c/),
[`sess_760ddfa45244`](../session_logs/examples/ex7-handoff-bridge/sess_760ddfa45244/))
completed in a single bridge round with correct parameters.

A practical conflict: ex6 enforces `MAX_PARTY_SIZE=8` but ex7's
scenario involves 12. I made the limit configurable via environment
variable on the Rasa action server and as a `spawn_mock_rasa()` kwarg
for offline mode, so each exercise sets its own policy without code
changes.

## Citations

- starter/handoff_bridge/bridge.py — HandoffBridge.run, implicit handoff intercept, handoff validation/repair
- starter/handoff_bridge/run.py — task passed via create_session, executor system prompt with workflow guidance
- starter/edinburgh_research/tools.py — zero-result hints with valid area names
