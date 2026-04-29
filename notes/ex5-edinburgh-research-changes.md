# Ex5 Edinburgh Research -- Changes and Issues Found

## Overview

Ex5 implements four tools for an Edinburgh venue booking scenario, wired into
the sovereign-agent `LoopHalf` (planner + executor). The tools search venues,
look up weather, calculate costs, and generate an HTML flyer. The integrity
checker (`verify_dataflow`) validates that every fact in the flyer was produced
by a tool call, catching LLM hallucinations.

## Changes to `starter/edinburgh_research/tools.py`

### Tool 1: `venue_search`

- **Bug:** `.contains()` does not exist on Python strings. Replaced with the
  `in` operator for case-insensitive substring matching
  (`near.lower() in v["area"].lower()`).
- **Bug:** Output dict used `"venues"` as the key but the docstring specifies
  `"results"`. Renamed to match the contract.
- **Fix:** `ToolError` was being called positionally (`ToolError("SA_TOOL_DEPENDENCY_MISSING")`).
  Changed to keyword arguments (`code=`, `message=`) to match the dataclass
  constructor.
- **Fix:** Moved `json.load` inside the `try` block so JSON parse errors are
  also caught by the `SA_TOOL_EXECUTION_FAILED` handler.

### Tool 2: `get_weather`

- **Bug:** Weather fixture uses lowercase keys (`"edinburgh"`, `"glasgow"`)
  but the task passes `"Edinburgh"`. Added case-insensitive city lookup
  via `{k.lower(): v for k, v in weather.items()}`.
- **Bug:** Error cases constructed an intermediate dict with a nested
  `"output"` key inside `output`, then unpacked it into `ToolResult(**output)`.
  This produced a ToolResult with `output={"output": {...}}` -- double-nested.
  Replaced with direct `ToolResult(success=False, output=..., summary=..., error=...)`
  construction for each branch.
- **Fix:** `ToolError` called positionally; changed to keyword arguments.
- **Docstring compliance:** The docstring says "return success=False ... Do NOT
  raise" for invalid city/date. The error cases now return a ToolResult with
  `success=False` and a `ToolError` in the `error` field, rather than raising.

### Tool 3: `calculate_cost`

- **Bug:** `venues.json` is a list of venue dicts, not a dict keyed by ID.
  `venue_id in venues` always returned False. Built a lookup dict:
  `venues_by_id = {v["id"]: v for v in venues}`.
- **Bug:** `required_catering_info_keys not in catering.keys()` compared a
  Python list against dict_keys using `not in`, which checks membership of
  the list object itself, not its elements. Replaced with individual
  validation: check `venue` is found, check `base_per_head` is not None.
- **Bug:** Deposit calculation was entirely missing (commented stub).
  Implemented using `deposit_policy` thresholds from `catering.json`:
  under 300 = no deposit, 300-1000 = 20%, over 1000 = 30%.
- **Bug:** `output` dict was empty in the success path -- never populated with
  the required fields. Now includes `subtotal_gbp`, `service_gbp`,
  `total_gbp`, `deposit_required_gbp`.
- **Bug:** `ToolResult(output)` passed a dict as the positional `success`
  argument. Changed to keyword arguments.
- **Bug:** Summary string had hardcoded `deposit £<M>` placeholder.

### Tool 4: `generate_flyer` (new implementation)

- Validates all required keys are present in `event_details`, raises
  `ToolError(SA_TOOL_INVALID_INPUT)` listing missing keys.
- Generates self-contained HTML with inline CSS.
- Tags every fact with `data-testid` attributes for the integrity checker.
- Writes to `session.workspace_dir / "flyer.html"` using the Session API.
- Records the tool call with full `event_details` as arguments so
  `verify_dataflow` can trace every flyer fact back to tool input.

## Changes to `starter/edinburgh_research/run.py`

### Problem: Information not reaching the LLMs

The `create_session()` call writes a detailed task description to `SESSION.md`
with exact tool call arguments. However, `half.run()` was called with a
7-word summary string:

```python
half.run(session, {"task": "research Edinburgh venue and write flyer"})
```

The planner received only this summary -- not the full task with exact
parameters. The planner then produced vague subgoal descriptions. The executor
only sees subgoal descriptions, so it had no idea what arguments to use and
invented its own (wrong areas, wrong party sizes).

### Fix 1: Pass the full task and tool discovery to the planner

```python
task_description = session.session_md_path.read_text(encoding="utf-8")
tools_summary = "\n".join(f"- {t.name}: {t.description}" for t in tools.list())
result = await half.run(session, {
    "task": task_description,
    "context": {"tools_summary": tools_summary},
})
```

The planner's `_build_planner_user_prompt` already checks
`context.get("tools_summary")` -- it was just never populated.

### Fix 2: Custom planner system prompt

The planner must produce subgoal descriptions that carry enough detail for
the executor. Key instructions:

- **Group dependent tool calls into the same subgoal.** When tool B needs
  tool A's output, they must be in one subgoal so the executor sees both
  results in its conversation context. The original 5-subgoal plan broke the
  data chain: the executor for `calculate_cost` didn't know the `venue_id`
  from `venue_search`.
- **Copy exact tool arguments into subgoal descriptions.** The executor cannot
  see the original task -- it only sees the subgoal's `description` field.
- **Don't copy placeholder text** like `<chosen pub's id>`. Instead write
  "use the venue_id returned by venue_search".
- **Prefer 1-2 large subgoals** over many small ones for dependent sequences.

### Fix 3: Custom executor system prompt

- Follow exact tool arguments from the subgoal description.
- Do not invent arguments or change parameter values.
- If a tool returns 0 results, re-read the subgoal before retrying.
- Must call `generate_flyer` before `complete_task`.

## Changes to `starter/edinburgh_research/integrity.py`

### Problem: `verify_dataflow` only checked numeric facts

The original implementation extracted three types of facts:
- Money amounts (`£N` via regex)
- Temperatures (`N°C` via regex)
- Weather condition keywords (`sunny`, `cloudy`, etc.)

This meant a flyer with a fabricated venue name, address, date, time, or
party size would pass the integrity check -- those string facts were never
verified against the tool call log.

### Fix: Extract and verify `data-testid` facts

`verify_dataflow` now calls `extract_testid_facts()` and adds the values to
the facts-to-check list (skipping `"title"` which is a composite string, and
deduplicating against already-extracted numeric facts).

This catches hallucinations in:
- `venue_name`, `venue_address` (string facts)
- `date`, `time` (string facts)
- `party_size` (numeric but not currency/temperature)

### Fix: HTML entity decoding

`extract_testid_facts` now decodes HTML entities via `html.unescape()` so
`&pound;556` becomes `£556`. Without this, `&pound;` values weren't matched
against `£` values from the regex extractors, causing false negatives on
legitimate flyers.

### Fix: Ruff B005 lint violation

Replaced `.strip("£°CcC")` (multi-character strip is misleading -- it strips
any character in the set, not the substring) with explicit `re.sub()` calls
for prefix/suffix removal.

## Observed LLM behaviour issues (Qwen3 on Nebius)

These are not code bugs but observations relevant to tuning:

- **Qwen3-32B (executor)** does not reliably follow prescriptive tool-call
  instructions. It "freelances" -- inventing its own search parameters even
  when exact values are given in the prompt.
- **Qwen3-Next-80B (planner)** tends to over-decompose into many small
  subgoals, breaking data flow between dependent tool calls.
- Grouping all dependent calls into 1-2 subgoals and feeding the full task
  description (not a summary) to the planner resolved the issue for the
  `ex5-real` scenario.
