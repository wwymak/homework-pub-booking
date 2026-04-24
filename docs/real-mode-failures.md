# Real-mode failures — a catalogue

This is the reference for every failure mode we've seen when running the
homework against LIVE services (Nebius LLMs, Rasa Pro, Speechmatics, Rime).
They're not bugs to suppress — they're the teaching moments. Students
WILL hit at least one of these, and learning to diagnose them is
Decision 7 (**observability as a first-class primitive**) in action.

The educator harness (`make educator-validate-real`) is DIAGNOSTIC:
it reports what happened and always exits 0. Pass/fail is the offline
`make educator-validate`.

---

## Ex5 — Qwen3-32B spiral on `venue_search`

### What it looks like

`make ex5-real` never writes `workspace/flyer.html`. The terminal shows:

```
Tool-call histogram (8 total):
  venue_search        ████████ ← SPIRAL?
  
  ★ NEVER CALLED: get_weather, calculate_cost, generate_flyer
```

Or a trace with 5-10 consecutive `venue_search` calls, each with
increasingly different args (party=30, 40, 50; area=Old Town, New Town,
City Centre).

### Why

Qwen3-32B is an instruct model — not a reasoning model. When the first
`venue_search` returns 0 results (because the fixture has specific
matches), Qwen doesn't reason "OK, there's no match, let me report
that"; it pattern-matches "search failed → try different params."
And because the task prompt provides wiggle room, it keeps expanding.

### Fix (short-term)

Our task prompt now includes HARD RULES:

```
Do NOT call venue_search more than once.
Do NOT change party_size from 6.
```

Qwen complies ~70% of the time. The other 30% is teaching material.

### Fix (what the STUDENT should write)

The student's `venue_search` implementation should detect the LLM
spiralling and return a `ToolResult` with `success=False` and a
clear `summary` telling the LLM to stop:

```python
from starter.edinburgh_research.integrity import _TOOL_CALL_LOG

def venue_search(near, party_size, budget_max_gbp=1000):
    # ... do the actual search ...

    # Spiral detection — after 3+ calls, force a stop
    search_count = sum(1 for r in _TOOL_CALL_LOG if r.tool_name == "venue_search")
    if search_count >= 3:
        return ToolResult(
            success=False,
            output={"error": "too_many_searches", "count": search_count},
            summary="STOP calling venue_search; use the results you already have.",
        )

    return ToolResult(success=True, ...)
```

This is defense-in-depth: the task prompt is the first line (LLM
compliance), and the tool itself is the second (brute-force cap).

### Why it matters pedagogically

This is **exactly** what a production agent encounters. LLMs will
try variations until something works or they hit a limit. Real
systems need to enforce budgets at the tool level because the model
won't do it voluntarily.

---

## Ex6 — `action_validate_booking` returns internal_error

### What it looks like

```
Structured half outcome: escalate
  summary: rasa returned unexpected output
  output: {'rasa_response': [
    {'text': 'Sorry, I am having trouble with that. Please try again.'},
    {'text': 'Okay, stopping confirm_booking.'},
  ]}
```

Those messages come from Rasa's default `pattern_internal_error` +
`pattern_cancel_flow` — i.e., your `ActionValidateBooking.run()` raised
a Python exception inside the action server.

### Why — TWO CAUSES

**Cause A — Action server cache.** Rasa caches Python modules in
memory at startup. When you edit `actions.py` or run
`make educator-apply-solution`, the file on disk updates but the
running action server keeps its OLD bytecode. The traceback you see
points at SOLUTION code (the new file), but the exception came from
the STUB.

This is the #1 reason students reach "my code looks right but still
fails."

### Fix — Restart the action server

After ANY change to `rasa_project/actions/*.py`:

```bash
# In Terminal 1 (rasa-actions): press Ctrl-C
# Then restart:
make rasa-actions
```

**Same for `rasa-serve` after changes to `flows.yml`, `domain.yml`,
or `config.yml`.** Rasa also caches the trained model — if you
changed flows, run `make rasa-clean` first to force retraining.

**Cause B — Metadata vs slots mismatch.** Students reading tutorials
often write `party_size = tracker.get_slot("party_size")` — but CALM
doesn't automatically pour message metadata into slots when the
trigger is programmatic (`/confirm_booking`). Your action needs to
read metadata explicitly:

```python
latest = tracker.latest_message or {}
booking = (latest.get("metadata") or {}).get("booking") or {}
party_size = booking.get("party_size")  # or fall back to slot
```

---

## Ex6 — Embeddings 401 "Incorrect API key"

### What it looks like

```
litellm.AuthenticationError: Incorrect API key provided: v1.CmMKH...
```

OpenAI-formatted error with YOUR Nebius key. You'd think Rasa called
OpenAI by mistake.

### Why

`config.yml` puts the embeddings reference outside `flow_retrieval:`.
Rasa silently falls back to the default OpenAI embeddings provider,
tries your Nebius key against `api.openai.com`, gets a 401.

### Fix

Inside `rasa_project/config.yml`:

```yaml
pipeline:
  - name: CompactLLMCommandGenerator
    llm:
      model_group: nebius_llm
    flow_retrieval:              # ← embeddings must be nested here
      embeddings:
        model_group: nebius_embeddings
```

NOT:

```yaml
    llm:
      model_group: nebius_llm
    embeddings:                  # ← WRONG (sibling to llm)
      model_group: nebius_embeddings
```

---

## Ex7 — Loop half uses FakeLLMClient even in `--real`

### What it looks like

The educator harness reports `ex7 (real Nebius): ran cleanly` but the
session shows only scripted behavior — no real LLM decisions.

### Why

Ex7's `run.py` in the current solution hard-codes `FakeLLMClient` for
the loop half, regardless of `--real`. Only the structured half is
"real" (host-process Rasa). This is deliberate: the Ex7 lesson is
"can the bridge round-trip?", which is best exercised deterministically.

### Workaround (if you want to exercise real LLM recovery)

Edit `starter/handoff_bridge/run.py` line ~130 (the `if real:` block)
to pass an `OpenAICompatibleClient` instead. Expect Qwen to
occasionally spiral here too.

---

## Ex7 — FakeLLMClient ran out of scripted responses

### What it looks like

```
ExternalError: [SA_EXT_UNEXPECTED_RESPONSE] FakeLLMClient ran out of
scripted responses
```

### Why

The scripted trajectory in `_build_fake_client_two_rounds()` assumes
a particular sequence of planner/executor calls. If the framework
version changes (sovereign-agent 0.2.1 adds a new chat call between
plan and execute, for example), the script is too short.

### Fix

Open `starter/handoff_bridge/run.py`, find `_build_fake_client_two_rounds`,
add more `ScriptedResponse` entries at the end (safe: unused extras
don't hurt). Or check the sovereign-agent CHANGELOG for version drift.

---

## Ex8 — Speechmatics 401 / 403

### What it looks like

```
speechmatics.models.AuthError: 401 Unauthorized
```

Usually when `run_voice_mode` opens a real-time session.

### Fix

Your `SPEECHMATICS_KEY` is wrong, expired, or on the wrong tier.
Check:

```bash
make educator-diagnostics    # shows auth status for Speechmatics
curl -H "Authorization: Bearer $SPEECHMATICS_KEY" \
     https://asr.api.speechmatics.com/v2/jobs
```

If that returns 200, the key works. If 401, regenerate at
https://portal.speechmatics.com → API Keys.

Free-tier keys work for realtime STT but have a 2-hour audio/month
cap. If you exceeded it you'll get 403.

---

## Ex8 — Rime TTS 400 "invalid voice"

### What it looks like

```
httpx.HTTPStatusError: 400 Bad Request — {"error": "invalid voice name"}
```

### Why

Rime.ai renames their voices. The voice we wire to by default
(`luna`, `abbie`, `amelia`, etc.) may have been replaced.

### Fix

Open `starter/voice_pipeline/voice_loop.py`, find `_call_rime_tts`,
check the `voice_name` field. Get the current voice list:

```bash
curl -H "Authorization: Bearer $RIME_API_KEY" \
     https://users.rime.ai/data/voices/all | python -m json.tool
```

Pick an Arcana voice (the natural-sounding line) and update the code.

---

## Ex8 — Mic or audio playback fails on macOS

### What it looks like

```
sounddevice.PortAudioError: Error querying device -1
```

Or the audio plays but nothing is recorded (STT returns empty).

### Fix

macOS needs Terminal (or iTerm, whichever you're running uv from)
to have microphone access. System Settings → Privacy & Security →
Microphone → toggle your terminal app on.

If you use Ghostty / Warp / a newer terminal, restart it fully after
granting permission.

---

## General — "my code works offline, breaks in real mode"

This is the defining experience of production agent systems. Offline,
you control every response. Real mode, the LLM surprises you.

**Start with the trace.** Every session writes `logs/trace.jsonl`.
Two commands to learn:

```bash
# Human-readable replay
make narrate-latest

# Raw events for filtering
cat $(make logs)/logs/trace.jsonl | jq 'select(.event_type == "executor.tool_called")'
```

If the trace shows a pattern (looping, wrong args, skipped step),
that's a task-prompt issue. If it shows errors mid-turn, that's a
code bug. If it shows normal flow but ends wrong, read the final
`session.state_changed` events.

**Keep offline deterministic.** Your `make ex5` must ALWAYS pass.
That's the contract. Real mode is the adversarial test.

**Diagnostic-driven development.** When a real-mode failure occurs,
add the failure signature + diagnosis to THIS doc. Every cohort
should leave the doc slightly better than they found it.
