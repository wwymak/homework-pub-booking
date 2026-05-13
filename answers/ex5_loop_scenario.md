# Ex5 — Edinburgh research loop scenario

## Your answer

The main challenge was information flow through the planner–executor
loop. Early sessions failed because `run.py` passed a 7-word summary to
the planner instead of the full task description from `SESSION.md`. The
planner then produced vague subgoals, and the executor — which only sees
subgoal descriptions — invented its own parameters. Sessions
[`sess_2168538e584a`](../session_logs/examples/ex5-edinburgh-research/sess_2168538e584a/) and [`sess_a2d815bb8d0f`](../session_logs/examples/ex5-edinburgh-research/sess_a2d815bb8d0f/) never found a venue because
the executor searched "Edinburgh" or "Edinburgh City Center" instead of
"Haymarket". Session [`sess_892993f94852`](../session_logs/examples/ex5-edinburgh-research/sess_892993f94852/) found the venue but passed the
literal placeholder `"<chosen pub's id>"` to `calculate_cost`, then
fabricated data for the flyer.

Three changes fixed this: (1) passing the full task description and
tool summaries into the planner context, (2) a custom planner system
prompt requiring exact parameters be copied into subgoal descriptions
and dependent tools grouped into 1–2 subgoals rather than 5, and (3) a
custom executor prompt forbidding invented arguments. After these
changes, sessions [`sess_3c28e30c4cd5`](../session_logs/examples/ex5-edinburgh-research/sess_3c28e30c4cd5/) and [`sess_8ab3df4bad7f`](../session_logs/examples/ex5-edinburgh-research/sess_8ab3df4bad7f/) both
completed successfully with correct data.

The integrity checker (`verify_dataflow`) also needed extending — it
originally only verified numeric facts (£ amounts, °C temperatures),
so fabricated venue names and addresses passed silently. Adding
`data-testid` attribute extraction and HTML entity decoding closed
that gap. One subtle catch: a "no deposit required" template originally
included the £300 policy threshold in the flyer text, which
`verify_dataflow` correctly flagged as ungrounded — that value came
from a business rule, not a tool call.

## Citations
Links to successful sessions are mentioned above, but to make it clearer the exact files, these 2 are the
trace/flyer links for one of the sucessful sessions:

- session_logs/examples/ex5-edinburgh-research/sess_8ab3df4bad7f/logs/trace.jsonl — tool call sequence
- session_logs/examples/ex5-edinburgh-research/sess_8ab3df4bad7f/workspace/flyer.html — the produced flyer
