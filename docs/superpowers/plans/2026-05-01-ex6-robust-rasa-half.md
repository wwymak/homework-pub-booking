# Ex6 Robust Rasa Structured Half — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix deposit key aliasing bug, add dynamic date handling, add `resume_from_loop` Rasa flow, add `party_too_small` validation rule, and sync the mock server — earning all 20 Ex6 grading points with production-quality code.

**Architecture:** Four files change: the validator gets deposit aliasing + dynamic dates, the Rasa action gets a min-party-size rule, the flows file gets a new `resume_from_loop` flow, and the mock server gets the same min-party-size rule to stay in sync. TDD throughout — tests before implementation.

**Tech Stack:** Python 3.12, Rasa CALM (flows.yml + rasa-sdk custom actions), sovereign-agent 0.2.0, pytest

**Spec:** `docs/superpowers/specs/2026-05-01-ex6-robust-rasa-half-design.md`

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `tests/public/test_ex6_scaffold.py` | Modify | Add tests for deposit aliasing, dynamic dates, extra date formats, party_too_small |
| `starter/rasa_half/validator.py` | Modify | Deposit key aliasing, `reference_date` param, additional date formats |
| `rasa_project/actions/actions.py` | Modify | Add `MIN_PARTY_SIZE_FOR_BOOKING = 4` and `party_too_small` rule |
| `rasa_project/data/flows.yml` | Modify | Add `resume_from_loop` flow |
| `starter/rasa_half/structured_half.py` | Modify | Add `party_too_small` rule to mock server |

---

### Task 1: Deposit key aliasing in validator

**Files:**
- Test: `tests/public/test_ex6_scaffold.py`
- Modify: `starter/rasa_half/validator.py:49-106`

- [ ] **Step 1: Write failing tests for deposit key aliasing**

Add to `tests/public/test_ex6_scaffold.py`:

```python
def test_normalise_deposit_key_aliases() -> None:
    """Deposit must be recognized from any of the known upstream key names."""
    from starter.rasa_half.validator import normalise_booking_payload

    base = {
        "venue_id": "Haymarket Tap",
        "date": "2026-04-25",
        "time": "19:30",
        "party_size": 6,
    }

    # "deposit" key (what run.py uses)
    out1 = normalise_booking_payload({**base, "deposit": "£500"})
    assert out1["metadata"]["booking"]["deposit_gbp"] == 500

    # "deposit_gbp" key (what Rasa action uses)
    out2 = normalise_booking_payload({**base, "deposit_gbp": 500})
    assert out2["metadata"]["booking"]["deposit_gbp"] == 500

    # "deposit_required_gbp" key (what calculate_cost returns)
    out3 = normalise_booking_payload({**base, "deposit_required_gbp": 500})
    assert out3["metadata"]["booking"]["deposit_gbp"] == 500

    # No deposit key at all → default 0
    out4 = normalise_booking_payload(base)
    assert out4["metadata"]["booking"]["deposit_gbp"] == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/public/test_ex6_scaffold.py::test_normalise_deposit_key_aliases -v`

Expected: FAIL — `deposit_gbp` and `deposit_required_gbp` keys produce 0 instead of 500.

- [ ] **Step 3: Implement deposit key aliasing**

In `starter/rasa_half/validator.py`, add the alias tuple after the existing `_GBP_PATTERN`:

```python
_DEPOSIT_ALIASES = ("deposit", "deposit_gbp", "deposit_required_gbp")
```

Replace the deposit extraction block (lines 76-79) from:

```python
    deposit = 0
    if raw.get("deposit") is not None:
        deposit = parse_currency_gbp(raw["deposit"])
```

to:

```python
    deposit = 0
    for _alias in _DEPOSIT_ALIASES:
        if raw.get(_alias) is not None:
            deposit = parse_currency_gbp(raw[_alias])
            break
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/public/test_ex6_scaffold.py::test_normalise_deposit_key_aliases -v`

Expected: PASS

- [ ] **Step 5: Run all existing ex6 tests to check for regressions**

Run: `uv run pytest tests/public/test_ex6_scaffold.py -v`

Expected: All 9 tests pass (8 existing + 1 new).

- [ ] **Step 6: Commit**

```bash
git add tests/public/test_ex6_scaffold.py starter/rasa_half/validator.py
git commit -m "feat(ex6): add deposit key aliasing in validator

Recognizes deposit, deposit_gbp, and deposit_required_gbp as input
keys. Fixes silent data loss when upstream tools use non-canonical
key names."
```

---

### Task 2: Dynamic date handling via `reference_date` parameter

**Files:**
- Test: `tests/public/test_ex6_scaffold.py`
- Modify: `starter/rasa_half/validator.py:49-156`

- [ ] **Step 1: Write failing tests for dynamic dates**

Add to `tests/public/test_ex6_scaffold.py`:

```python
import datetime


def test_normalise_date_today_is_dynamic() -> None:
    """'today' should resolve to reference_date, not a hardcoded string."""
    from starter.rasa_half.validator import normalise_booking_payload

    base = {
        "venue_id": "haymarket_tap",
        "date": "today",
        "time": "19:30",
        "party_size": 6,
    }
    ref = datetime.date(2026, 6, 15)
    out = normalise_booking_payload(base, reference_date=ref)
    assert out["metadata"]["booking"]["date"] == "2026-06-15"


def test_normalise_date_tomorrow_is_dynamic() -> None:
    """'tomorrow' should resolve to reference_date + 1 day."""
    from starter.rasa_half.validator import normalise_booking_payload

    base = {
        "venue_id": "haymarket_tap",
        "date": "tomorrow",
        "time": "19:30",
        "party_size": 6,
    }
    ref = datetime.date(2026, 6, 15)
    out = normalise_booking_payload(base, reference_date=ref)
    assert out["metadata"]["booking"]["date"] == "2026-06-16"


def test_normalise_date_default_uses_real_today() -> None:
    """When no reference_date is passed, 'today' uses datetime.date.today()."""
    from starter.rasa_half.validator import normalise_booking_payload

    base = {
        "venue_id": "haymarket_tap",
        "date": "today",
        "time": "19:30",
        "party_size": 6,
    }
    out = normalise_booking_payload(base)
    assert out["metadata"]["booking"]["date"] == datetime.date.today().isoformat()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/public/test_ex6_scaffold.py::test_normalise_date_today_is_dynamic tests/public/test_ex6_scaffold.py::test_normalise_date_tomorrow_is_dynamic tests/public/test_ex6_scaffold.py::test_normalise_date_default_uses_real_today -v`

Expected: FAIL — `normalise_booking_payload` doesn't accept `reference_date` parameter; "today" returns hardcoded `"2026-04-25"`.

- [ ] **Step 3: Implement dynamic date handling**

In `starter/rasa_half/validator.py`:

Add `import datetime` at the top (after `import re`).

Change `_normalise_date` signature from:

```python
def _normalise_date(raw: str) -> str:
```

to:

```python
def _normalise_date(raw: str, reference_date: datetime.date | None = None) -> str:
```

Replace the hardcoded "today"/"tomorrow" block (lines 141-145) from:

```python
    s = str(raw).strip().lower()
    if s == "today":
        return "2026-04-25"
    if s == "tomorrow":
        return "2026-04-26"
```

to:

```python
    s = str(raw).strip().lower()
    ref = reference_date or datetime.date.today()
    if s == "today":
        return ref.isoformat()
    if s == "tomorrow":
        return (ref + datetime.timedelta(days=1)).isoformat()
```

Add two more date format patterns before the final `raise`. After the existing `DD Month YYYY` match block, add:

```python
    # DD/MM/YYYY
    if m := re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", s):
        day, month, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return f"{year:04d}-{month:02d}-{day:02d}"
    # Month DD, YYYY (e.g., "april 25, 2026")
    if m := re.match(r"(\w+)\s+(\d{1,2})(?:st|nd|rd|th)?,?\s*(\d{4})?", s):
        month_name = m.group(1)
        day = int(m.group(2))
        year = int(m.group(3)) if m.group(3) else ref.year
        if month_name not in _MONTH_NAMES:
            raise ValidationFailed(f"unknown month: {month_name!r}")
        return f"{year:04d}-{_MONTH_NAMES[month_name]:02d}-{day:02d}"
```

Change `normalise_booking_payload` signature from:

```python
def normalise_booking_payload(raw: dict) -> dict:
```

to:

```python
def normalise_booking_payload(raw: dict, reference_date: datetime.date | None = None) -> dict:
```

Update the call to `_normalise_date` (line 67) from:

```python
    date_iso = _normalise_date(date_raw)
```

to:

```python
    date_iso = _normalise_date(date_raw, reference_date=reference_date)
```

Also update the `year` default in the existing `DD Month YYYY` match block (line 152) from:

```python
        year = int(m.group(3)) if m.group(3) else 2026
```

to:

```python
        ref = reference_date or datetime.date.today()
        year = int(m.group(3)) if m.group(3) else ref.year
```

Wait — `ref` is already defined at the top of the function body. So just use:

```python
        year = int(m.group(3)) if m.group(3) else ref.year
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/public/test_ex6_scaffold.py::test_normalise_date_today_is_dynamic tests/public/test_ex6_scaffold.py::test_normalise_date_tomorrow_is_dynamic tests/public/test_ex6_scaffold.py::test_normalise_date_default_uses_real_today -v`

Expected: PASS

- [ ] **Step 5: Write and run tests for additional date formats**

Add to `tests/public/test_ex6_scaffold.py`:

```python
def test_normalise_date_extra_formats() -> None:
    """Validator handles DD/MM/YYYY and Month DD, YYYY formats."""
    from starter.rasa_half.validator import normalise_booking_payload

    base = {"venue_id": "haymarket_tap", "time": "19:30", "party_size": 6}

    out1 = normalise_booking_payload({**base, "date": "25/04/2026"})
    assert out1["metadata"]["booking"]["date"] == "2026-04-25"

    out2 = normalise_booking_payload({**base, "date": "April 25, 2026"})
    assert out2["metadata"]["booking"]["date"] == "2026-04-25"

    out3 = normalise_booking_payload({**base, "date": "april 25 2026"})
    assert out3["metadata"]["booking"]["date"] == "2026-04-25"
```

Run: `uv run pytest tests/public/test_ex6_scaffold.py::test_normalise_date_extra_formats -v`

Expected: PASS

- [ ] **Step 6: Run full ex6 test suite for regressions**

Run: `uv run pytest tests/public/test_ex6_scaffold.py -v`

Expected: All tests pass (8 original + 4 new = 12).

- [ ] **Step 7: Commit**

```bash
git add tests/public/test_ex6_scaffold.py starter/rasa_half/validator.py
git commit -m "feat(ex6): dynamic date handling with reference_date parameter

Replace hardcoded 'today'/'tomorrow' dates with datetime.date.today()
default. Add reference_date parameter for deterministic testing.
Add DD/MM/YYYY and Month DD, YYYY date format support."
```

---

### Task 3: Add `party_too_small` rule to `ActionValidateBooking`

**Files:**
- Modify: `rasa_project/actions/actions.py:29-136`

- [ ] **Step 1: Add the constant and validation rule**

In `rasa_project/actions/actions.py`, add the new constant after line 29:

```python
MIN_PARTY_SIZE_FOR_BOOKING = 4
```

Add the new rule after the numeric casting block (after the `invalid_deposit` check, before the `party_int > MAX_PARTY_SIZE` check). Insert:

```python
        if party_int < MIN_PARTY_SIZE_FOR_BOOKING:
            return slot_events + [SlotSet("validation_error", "party_too_small")]
```

The full rule order becomes:
1. Missing required fields
2. Invalid numeric fields
3. `party_int < 4` → `party_too_small` (NEW)
4. `party_int > 8` → `party_too_large`
5. `deposit_int > 300` → `deposit_too_high`
6. Success → booking reference

- [ ] **Step 2: Verify the action file is syntactically valid**

Run: `uv run python -c "from rasa_project.actions.actions import ActionValidateBooking; print('OK')"`

If that fails due to import path, try:

Run: `uv run python -c "import ast; ast.parse(open('rasa_project/actions/actions.py').read()); print('syntax OK')"`

Expected: `syntax OK`

- [ ] **Step 3: Commit**

```bash
git add rasa_project/actions/actions.py
git commit -m "feat(ex6): add minimum party size validation rule

Reject bookings with party_size < 4 (matches catering.json
minimum_party_size). Adds MIN_PARTY_SIZE_FOR_BOOKING constant."
```

---

### Task 4: Add `party_too_small` rule to mock server

**Files:**
- Test: `tests/public/test_ex6_scaffold.py`
- Modify: `starter/rasa_half/structured_half.py:439-478`

- [ ] **Step 1: Write failing test for party_too_small via mock**

Add to `tests/public/test_ex6_scaffold.py`:

```python
import asyncio


def test_ex6_rejects_party_too_small() -> None:
    """Mock server rejects party_size < 4 with party_too_small reason."""
    from starter.rasa_half.structured_half import RasaStructuredHalf, spawn_mock_rasa
    from sovereign_agent._internal.paths import example_sessions_dir
    from sovereign_agent.session.directory import create_session

    server, _thread, mock_url = spawn_mock_rasa(port=5906)
    try:
        with example_sessions_dir("test-ex6-small-party", persist=False) as sessions_root:
            session = create_session(
                scenario="test-ex6",
                task="Test party too small rejection",
                sessions_dir=sessions_root,
            )
            half = RasaStructuredHalf(rasa_url=mock_url)
            result = asyncio.run(
                half.run(
                    session,
                    {
                        "data": {
                            "venue_id": "haymarket_tap",
                            "date": "2026-04-25",
                            "time": "19:30",
                            "party_size": "3",
                            "deposit": "100",
                        }
                    },
                )
            )
        assert not result.success
        assert "party_too_small" in result.summary
    finally:
        server.shutdown()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/public/test_ex6_scaffold.py::test_ex6_rejects_party_too_small -v`

Expected: FAIL — mock server doesn't check for party < 4, so it confirms the booking.

- [ ] **Step 3: Add `party_too_small` check to mock server**

In `starter/rasa_half/structured_half.py`, in the `_MockRasaHandler.do_POST` method, add the party_too_small check after the `not party` check and before the `party > 8` check. Change:

```python
        if not party:
            response = [
                {
                    "text": "Booking rejected (missing party size).",
                    "custom": {"action": "rejected", "reason": "missing_party_size"},
                }
            ]
        elif party > 8:
```

to:

```python
        if not party:
            response = [
                {
                    "text": "Booking rejected (missing party size).",
                    "custom": {"action": "rejected", "reason": "missing_party_size"},
                }
            ]
        elif party < 4:
            response = [
                {
                    "text": "Sorry, we can't accept this booking. Reason: party_too_small",
                    "custom": {"action": "rejected", "reason": "party_too_small"},
                }
            ]
        elif party > 8:
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/public/test_ex6_scaffold.py::test_ex6_rejects_party_too_small -v`

Expected: PASS

- [ ] **Step 5: Run full ex6 test suite for regressions**

Run: `uv run pytest tests/public/test_ex6_scaffold.py -v`

Expected: All tests pass (12 previous + 1 new = 13).

- [ ] **Step 6: Commit**

```bash
git add tests/public/test_ex6_scaffold.py starter/rasa_half/structured_half.py
git commit -m "feat(ex6): add party_too_small check to mock server

Keeps mock in sync with ActionValidateBooking — rejects party_size < 4."
```

---

### Task 5: Add `resume_from_loop` Rasa flow

**Files:**
- Modify: `rasa_project/data/flows.yml`

- [ ] **Step 1: Add the `resume_from_loop` flow**

Append the following to `rasa_project/data/flows.yml`, after the `confirm_booking` flow:

```yaml

  resume_from_loop:
    description: >
      Re-enter booking validation after a loop-side handoff provided
      fresh booking data. Triggered by /resume_from_loop with booking
      metadata. Structurally identical to confirm_booking — the custom
      action does the heavy lifting.
    steps:
      - id: validate
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

- [ ] **Step 2: Validate the YAML is parseable**

Run: `uv run python -c "import yaml; data = yaml.safe_load(open('rasa_project/data/flows.yml')); flows = data['flows']; assert 'confirm_booking' in flows; assert 'resume_from_loop' in flows; print(f'OK: {len(flows)} flows defined')"`

Expected: `OK: 2 flows defined`

- [ ] **Step 3: Commit**

```bash
git add rasa_project/data/flows.yml
git commit -m "feat(ex6): add resume_from_loop Rasa flow

Allows re-entry into booking validation after loop-side handoff.
Same validation logic via action_validate_booking, separate flow
for Rasa command generator distinction."
```

---

### Task 6: End-to-end verification and documentation

**Files:**
- Test: run `make ex6` and manual edge case checks
- Modify: `docs/superpowers/specs/2026-05-01-ex6-robust-rasa-half-design.md` (mark as implemented)

- [ ] **Step 1: Run `make ex6` (tier 1 mock) end-to-end**

Run: `uv run python -m starter.rasa_half.run`

Expected output includes:
```
Structured half outcome: complete
  summary: booking confirmed by rasa (ref=BK-...)
```

- [ ] **Step 2: Verify deposit key bug is fixed**

Run:
```bash
uv run python -c "
from starter.rasa_half.validator import normalise_booking_payload
raw = {'venue_id': 'Cafe Royal', 'date': '2026-04-25', 'time': '19:30', 'party_size': 6, 'deposit_required_gbp': 500}
result = normalise_booking_payload(raw)
deposit = result['metadata']['booking']['deposit_gbp']
assert deposit == 500, f'Expected 500, got {deposit}'
print(f'deposit_gbp = {deposit} — deposit key aliasing works')
"
```

Expected: `deposit_gbp = 500 — deposit key aliasing works`

- [ ] **Step 3: Verify dynamic dates**

Run:
```bash
uv run python -c "
import datetime
from starter.rasa_half.validator import normalise_booking_payload
raw = {'venue_id': 'haymarket_tap', 'date': 'today', 'time': '19:30', 'party_size': 6}
result = normalise_booking_payload(raw)
today = datetime.date.today().isoformat()
actual = result['metadata']['booking']['date']
assert actual == today, f'Expected {today}, got {actual}'
print(f'today resolved to {actual} — dynamic dates work')
"
```

Expected: `today resolved to 2026-05-01 — dynamic dates work`

- [ ] **Step 4: Run full test suite**

Run: `uv run pytest tests/public/ -v`

Expected: All tests pass, 0 skipped.

- [ ] **Step 5: Run grader**

Run: `uv run python -m grader.check_submit --only ex6`

Expected: `ex6_structured_half_runs` passes.

- [ ] **Step 6: Commit final state**

```bash
git add -A
git commit -m "chore(ex6): end-to-end verification complete

All ex6 tests pass. Mock server, validator, action, and flows
are aligned. Deposit aliasing, dynamic dates, party_too_small,
and resume_from_loop all working."
```
