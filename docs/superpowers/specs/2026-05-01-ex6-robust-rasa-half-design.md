# Ex6 Robust Rasa Structured Half — Design Spec

**Date:** 2026-05-01
**Scope:** `starter/rasa_half/`, `rasa_project/`
**Goal:** Fix bugs, add missing validation rules, make the validator dynamic, and add the `resume_from_loop` flow to earn all 20 grading points while producing production-quality code.

---

## Problem Statement

The prefilled Ex6 code has several issues:

1. **Mock server commented out** — `spawn_mock_rasa` in `structured_half.py` is commented out, but `run.py` imports it. Tier 1 (`make ex6`) crashes with `ImportError`.
2. **Deposit key mismatch** — The validator only recognizes the `deposit` key. The `calculate_cost` tool (Ex5) returns `deposit_required_gbp`, and the Rasa action uses `deposit_gbp`. When data flows from Ex5/Ex7, the deposit silently becomes 0, bypassing the 300 cap. Demonstrated: a 500 deposit submitted as `deposit_required_gbp` passes validation.
3. **Hardcoded dates** — `_normalise_date` maps `"today"` to `"2026-04-25"` literally. Not dynamic.
4. **Missing `resume_from_loop` flow** — The grading rubric awards 4 points for this flow. It was dropped during development.
5. **Missing `minimum_party_size` check** — `catering.json` defines `minimum_party_size: 4` but neither the validator nor the action enforces it.

---

## Design Decisions

### D1: Deposit key aliasing — strict with explicit alias map

An explicit, ordered set of recognized aliases:

```python
_DEPOSIT_ALIASES = ("deposit", "deposit_gbp", "deposit_required_gbp")
```

Checked in priority order. If a non-canonical alias is used, it is accepted but could be logged for observability. If no alias is found, deposit defaults to 0 (valid — some venues require no deposit). Any unrecognized key is ignored.

**Rationale:** Handles all known upstream producers (run.py uses `deposit`, calculate_cost uses `deposit_required_gbp`, Rasa action uses `deposit_gbp`) without silently swallowing unknown garbage.

### D2: Dynamic dates via `reference_date` parameter

`normalise_booking_payload` gains an optional `reference_date: datetime.date | None` parameter. When `None` (default), uses `datetime.date.today()`. The `"today"` and `"tomorrow"` keywords resolve relative to this reference.

ISO strings (`YYYY-MM-DD`) pass through unchanged and never touch the reference date.

**Rationale:** Fully testable and deterministic when needed (tests/grader pass a fixed date), dynamic by default in production. No hidden env vars.

### D3: Constants in action, not file I/O

`ActionValidateBooking` keeps hardcoded constants:

```python
MIN_PARTY_SIZE_FOR_BOOKING = 4
MAX_PARTY_SIZE_FOR_AUTO_BOOKING = 8
MAX_DEPOSIT_FOR_AUTO_BOOKING_GBP = 300
```

**Rationale:** The action server is a separate process. Adding file I/O makes it fragile (path resolution across processes). These are policy rules, not data. Document that they must stay in sync with `catering.json`.

### D4: Add `resume_from_loop`, skip `request_research`

Add `resume_from_loop` as a Rasa flow. Skip `request_research` — the rubric doesn't score it, and reverse handoff belongs in the Python bridge (Ex7).

**Rationale:** 4 rubric points. `resume_from_loop` is a legitimate dialog concern (re-entering validation with fresh data after a loop-side handoff).

---

## Component Changes

### 1. `starter/rasa_half/validator.py`

**Deposit aliasing:**
- Define `_DEPOSIT_ALIASES = ("deposit", "deposit_gbp", "deposit_required_gbp")`
- Replace the single `raw.get("deposit")` check with a loop over aliases, using the first match
- Default to 0 if no alias found

**Dynamic dates:**
- Add `reference_date: datetime.date | None = None` parameter to `normalise_booking_payload`
- Replace hardcoded `"2026-04-25"` / `"2026-04-26"` with computation from `reference_date or datetime.date.today()`
- Add `datetime.timedelta(days=1)` for "tomorrow"

**Additional date formats:**
- `DD/MM/YYYY` (e.g., `25/04/2026`)
- `Month DD, YYYY` (e.g., `April 25, 2026`)
- Keep existing `DD Month YYYY` and ISO `YYYY-MM-DD`

### 2. `rasa_project/data/flows.yml`

**New flow — `resume_from_loop`:**

```yaml
resume_from_loop:
  description: >
    Re-enter booking validation after a loop-side handoff.
    Triggered by /resume_from_loop with fresh booking metadata.
  steps:
    - id: reset_slots
      action: action_validate_booking
      next:
        - if: "slots.validation_error is not null"
          then: rejected
        - else: confirmed
    - id: rejected
      action: utter_booking_rejected
      next: END
    - id: confirmed
      action: utter_booking_confirmed
      next: END
```

Structurally identical to `confirm_booking` — the action does all the heavy lifting. The separate flow exists so Rasa's command generator can distinguish between a first attempt and a re-entry, and so the rubric's test can trigger it by name.

### 3. `rasa_project/actions/actions.py`

**New constant:** `MIN_PARTY_SIZE_FOR_BOOKING = 4`

**New validation rule** inserted after numeric casting, before the existing party size check:

```python
if party_int < MIN_PARTY_SIZE_FOR_BOOKING:
    return slot_events + [SlotSet("validation_error", "party_too_small")]
```

**Rule execution order:**
1. Missing required fields -> `"missing_{field}"`
2. Invalid numeric fields -> `"invalid_party_size"` / `"invalid_deposit"`
3. `party_size < 4` -> `"party_too_small"`
4. `party_size > 8` -> `"party_too_large"`
5. `deposit_gbp > 300` -> `"deposit_too_high"`
6. All pass -> generate booking reference

### 4. `starter/rasa_half/structured_half.py`

**Mock server:** Already uncommented (done during analysis). Add `party_too_small` rule to `_MockRasaHandler` to keep mock and real action in sync.

### 5. `rasa_project/domain.yml`

No structural changes. Existing slots and responses cover both flows. `utter_booking_rejected` uses `{validation_error}` which naturally includes new reason strings.

### 6. `starter/rasa_half/run.py`

Update `spawn_mock_rasa` import (already fixed). No other changes needed — the sample booking in `run.py` uses valid data that passes all rules.

---

## Testing Strategy

- All existing public tests in `tests/public/test_ex6_scaffold.py` continue to pass
- `make ex6` (tier 1 mock) passes end-to-end for the sample booking
- The deposit key bug demo (deposit via `deposit_required_gbp`) now correctly produces 500 in the normalized output
- Edge cases to verify manually:
  - Party=3 -> rejected with `party_too_small`
  - Party=12 -> rejected with `party_too_large`
  - Deposit=500 via any alias key -> rejected with `deposit_too_high`
  - `"today"` date -> resolves to actual today's date
  - `"April 25, 2026"` -> `"2026-04-25"`

---

## Grading Alignment

| Rubric check | Points | Addressed by |
|---|---|---|
| `ex6_structured_half_accepts_valid_booking` | 4 | Mock server uncommented, validator fixed |
| `ex6_rejects_oversize_party` | 3 | Existing action rule (party > 8) |
| `ex6_rejects_high_deposit` | 3 | Deposit key aliasing ensures deposit is read correctly |
| `confirm_booking` flow commits valid booking | 4 | Existing flow, unchanged |
| `resume_from_loop` re-enters correctly | 4 | New flow added |
| Validator normalises >= 3 of 5 fields | 2 | All 5 normalised |
| **Total** | **20** | |

---

## Files Modified

| File | Change |
|---|---|
| `starter/rasa_half/validator.py` | Deposit aliasing, dynamic dates, extra date formats, `reference_date` param |
| `starter/rasa_half/structured_half.py` | Mock server uncommented (done), add `party_too_small` to mock |
| `rasa_project/data/flows.yml` | Add `resume_from_loop` flow |
| `rasa_project/actions/actions.py` | Add `MIN_PARTY_SIZE_FOR_BOOKING`, `party_too_small` rule |
| `rasa_project/domain.yml` | No changes needed |
| `starter/rasa_half/run.py` | No changes needed |
