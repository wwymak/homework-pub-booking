# Ex9 — Reflection

## Q1 — Planner handoff decision

### Your answer

In session `sess_646758b6fc38` (Ex7 handoff-bridge), the planner makes
two separate structured-half assignments across two bridge rounds, each
triggered by a different signal.

**Round 1** — the planner's initial plan (ticket `tk_65e77d71`) assigns
`sg_2` directly to `"structured"`:

```json
{
  "id": "sg_2",
  "description": "Book the first available venue from the search results",
  "success_criterion": "Booking confirmation received with reservation details",
  "estimated_tool_calls": 1,
  "depends_on": ["sg_1"],
  "assigned_half": "structured",
  "status": "pending"
}
```

The signal here is the **transactional commit** nature of the subgoal:
"Book the first available venue" is a terminal action that changes
system state (creating a reservation), not an exploratory search. The
planner is prompted with the list of available halves and their
purposes; when a subgoal involves making a booking, confirmation, or
any other irreversible commit, it assigns `"structured"` because those
actions require the booking system's approval workflow.

The executor then searched venues, found Royal Oak (party of 12), calculated the cost (total
£1234, deposit £370), and called `handoff_to_structured`. The
structured half rejected it:

```
"rejection_reason": "sorry, we can't accept this booking. reason: party_too_large"
```

This rejection triggers **Round 2**, where the planner re-plans (ticket
`tk_8b497973`). The re-plan's `sg_3` is explicitly routed to structured:

```json
{
  "id": "sg_3",
  "description": "Hand off the corrected booking data to the structured half for approval.",
  "success_criterion": "Structured half accepts the handoff and processes the booking.",
  "estimated_tool_calls": 1,
  "depends_on": ["sg_2"],
  "assigned_half": "structured",
  "status": "pending"
}
```

The signal for this second assignment is the **rejection feedback**
itself. The re-plan's task preview (trace.jsonl line 12) reads:

> "The structured half rejected the previous proposal. Reason: sorry,
> we can't accept this booking. reason: party_too_large. The booking
> system only auto-approves parties of 8 or fewer. Reduce party_size"

The planner now models the structured half as a gatekeeper with
acceptance rules, so it explicitly names the handoff ("Hand off the
corrected booking data to the structured half for approval") and sets
the success criterion as the structured half accepting the handoff.
This time the loop found Haymarket Tap (party of 8, total £675,
deposit £135) and the structured half accepted, completing the session
in round 2.

### Citations

- `session_logs/examples/ex7-handoff-bridge/sess_646758b6fc38/logs/tickets/tk_65e77d71/raw_output.json` — Round 1 plan with `sg_2` assigned to `"structured"` (lines 11-22)
- `session_logs/examples/ex7-handoff-bridge/sess_646758b6fc38/logs/tickets/tk_8b497973/raw_output.json` — Round 2 re-plan with `sg_3` assigned to `"structured"` (lines 22-32)
- `session_logs/examples/ex7-handoff-bridge/sess_646758b6fc38/logs/trace.jsonl` — full session trace showing the rejection at line 10 and the re-plan trigger at line 12

---

## Q2 — Dataflow integrity catch

### Your answer

Session `sess_892993f94852` (Ex5 edinburgh-research) is a clear case
where `verify_dataflow` catches fabrications that manual inspection
would miss.

**What happened:** The executor successfully called `venue_search` and
got back Haymarket Tap, then called `get_weather` and got `cloudy, 12C`.
But when it called `calculate_cost`, it passed the literal placeholder
string `"<chosen pub's id>"` instead of the actual venue ID
`"haymarket_tap"`, so the tool returned `venue not found`
(trace.jsonl line 7):

```json
{"tool": "calculate_cost",
 "arguments": {"venue_id": "<chosen pub's id>", "party_size": 6, ...},
 "success": false,
 "summary": "calculate_cost(<chosen pub's id>): venue not found"}
```

Rather than retrying with the correct ID, the executor fabricated an
entire set of plausible-looking data and called `generate_flyer` with
it (trace.jsonl line 12). The resulting flyer
(`workspace/flyer.html`) contains:

| Flyer field       | Fabricated value          | Actual tool output              |
|-------------------|---------------------------|---------------------------------|
| `venue_name`      | "The Royal Edinburgh"     | "Haymarket Tap" (venue_search)  |
| `venue_address`   | "1 Castle Road, Edinburgh"| "12 Dalry Rd, Edinburgh EH11 2BG" |
| `condition`       | "Sunny"                   | "cloudy" (get_weather)          |
| `temperature`     | 18 C                      | 12 C                            |
| `total`           | £250                      | never computed (calculate_cost failed) |
| `deposit`         | £50                       | never computed                  |
| `date`            | 2023-04-20                | task specifies 2026-04-25       |
| `party_size`      | 8                         | task specifies 6                |

**Why manual inspection misses it:** Every fabricated value is
internally consistent and plausible. £250 for a party of 8 with a £50
deposit looks reasonable. "Sunny, 18 C" is believable Edinburgh spring
weather. "The Royal Edinburgh" sounds like a real pub. A human skimming
the flyer would likely approve it.

**Why `verify_dataflow` catches it:** The check
(in `starter/edinburgh_research/integrity.py`, lines 119-176)
extracts every concrete fact from the flyer — money amounts via
`extract_money_facts`, temperatures via `extract_temperature_facts`,
weather conditions via `extract_condition_facts`, and all
`data-testid` attribute values via `extract_testid_facts`. It then
checks each fact against `_TOOL_CALL_LOG` using `fact_appears_in_log`
(line 156), which recursively scans all tool call arguments and
outputs.

For this flyer, `£250` and `£50` never appear in any tool output
(because `calculate_cost` failed). `18` never appears as a temperature
(the tool returned `12`). `Sunny` never appears (the tool returned
`cloudy`). `The Royal Edinburgh` never appears anywhere in tool
outputs. The check would return:

```python
IntegrityResult(
    ok=False,
    unverified_facts=["£250", "£50", "18", "sunny",
                      "The Royal Edinburgh", "1 Castle Road, Edinburgh",
                      "2023-04-20"],
    summary="dataflow FAIL: 7 unverified fact(s): [...]"
)
```

Compare this to a correct session like `sess_3c28e30c4cd5`, where
`calculate_cost` succeeded (trace.jsonl line 5: `total £556, deposit
£111`), the flyer used those exact values, and `verify_dataflow` would
return `ok=True` with all facts verified.

The broader point: `verify_dataflow` compares against ground truth in
`_TOOL_CALL_LOG`, not against "does this look reasonable." It catches
fabrications precisely when they are most dangerous — when they look
plausible enough that a human would wave them through.

### Citations

- `session_logs/examples/ex5-edinburgh-research/sess_892993f94852/logs/trace.jsonl` — the full tool call sequence; line 7 shows `calculate_cost` failing with the placeholder venue ID, lines 11-12 show fabricated data being passed to `generate_flyer`
- `session_logs/examples/ex5-edinburgh-research/sess_892993f94852/workspace/flyer.html` — the produced flyer with fabricated values (lines 12-22)
- `starter/edinburgh_research/integrity.py` — `verify_dataflow` implementation (lines 119-176), fact extraction helpers (lines 65-97), `fact_appears_in_log` (lines 100-113)
- `session_logs/examples/ex5-edinburgh-research/sess_3c28e30c4cd5/logs/trace.jsonl` — correct session for comparison; line 5 shows `calculate_cost` succeeding with `total £556, deposit £111`
