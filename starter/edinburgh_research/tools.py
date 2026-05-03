"""Ex5 tools. Four tools the agent uses to research an Edinburgh booking.

Each tool:
  1. Reads its fixture from sample_data/ (DO NOT modify the fixtures).
  2. Logs its arguments and output into _TOOL_CALL_LOG (see integrity.py).
  3. Returns a ToolResult with success=True/False, output=dict, summary=str.

The grader checks for:
  * Correct parallel_safe flags (reads True, generate_flyer False).
  * Every tool's results appear in _TOOL_CALL_LOG.
  * Tools fail gracefully on missing fixtures or bad inputs (ToolError,
    not RuntimeError).
"""

from __future__ import annotations

import json
from pathlib import Path

from sovereign_agent.errors import ToolError
from sovereign_agent.session.directory import Session
from sovereign_agent.tools.registry import ToolRegistry, ToolResult, _RegisteredTool

from starter.edinburgh_research.integrity import record_tool_call

_SAMPLE_DATA = Path(__file__).parent / "sample_data"


# ---------------------------------------------------------------------------
# TODO 1 — venue_search
# ---------------------------------------------------------------------------
def venue_search(near: str, party_size: int, budget_max_gbp: int = 1000) -> ToolResult:
    """Search for Edinburgh venues near <near> that can seat the party.

    Reads sample_data/venues.json. Filters by:
      * open_now == True
      * area contains <near> (case-insensitive substring match)
      * seats_available_evening >= party_size
      * hire_fee_gbp + min_spend_gbp <= budget_max_gbp

    Returns a ToolResult with:
      output: {"near": ..., "party_size": ..., "results": [<venue dicts>], "count": int}
      summary: "venue_search(<near>, party=<N>): <count> result(s)"

    MUST call record_tool_call(...) before returning so the integrity
    check can see what data was produced.
    """
    # TODO 1a: load venues.json. Raise ToolError(SA_TOOL_DEPENDENCY_MISSING)
    #          if the file is absent.
    if not (_SAMPLE_DATA / "venues.json").exists():
        raise ToolError(code="SA_TOOL_DEPENDENCY_MISSING", message="venue data unavailable")

    try:
        with open(_SAMPLE_DATA / "venues.json") as f:
            venues = json.load(f)
        valid_venues = [
            v
            for v in venues
            if v["open_now"]
            and near.lower() in v["area"].lower()
            and v["seats_available_evening"] >= party_size
            and v["hire_fee_gbp"] + v["min_spend_gbp"] <= budget_max_gbp
        ]
        input_args = {
            "near": near,
            "party_size": party_size,
            "budget_max_gbp": budget_max_gbp,
        }
        output: dict = {
            **input_args,
            "results": valid_venues,
            "count": len(valid_venues),
        }

        if len(valid_venues) == 0:
            all_areas = sorted({v["area"] for v in venues if v["open_now"]})
            area_matched = [
                v for v in venues if v["open_now"] and near.lower() in v["area"].lower()
            ]
            if not area_matched:
                output["hint"] = (
                    f"No venues found in area '{near}'. "
                    f"Valid areas are: {', '.join(all_areas)}. "
                    "Try one of these exact area names."
                )
            else:
                max_seats = max(v["seats_available_evening"] for v in area_matched)
                output["hint"] = (
                    f"Venues exist in '{near}' but none seat {party_size}. "
                    f"Largest capacity in this area: {max_seats}. "
                    "Try a different area first, keeping the same party_size. "
                    f"Valid areas: {', '.join(all_areas)}. "
                    "Do NOT hand off without a venue_id."
                )

        record_tool_call("venue_search", input_args, output)
        return ToolResult(
            success=True,
            output=output,
            summary=f"venue_search({near}, party={party_size}): {len(valid_venues)} result(s)",
        )
    except Exception as e:
        raise ToolError(code="SA_TOOL_EXECUTION_FAILED", message=f"venue search error: {e}") from e


# ---------------------------------------------------------------------------
# TODO 2 — get_weather
# ---------------------------------------------------------------------------
def get_weather(city: str, date: str) -> ToolResult:
    """Look up the scripted weather for <city> on <date> (YYYY-MM-DD).

    Reads sample_data/weather.json. Returns:
      output: {"city": str, "date": str, "condition": str, "temperature_c": int, ...}
      summary: "get_weather(<city>, <date>): <condition>, <temp>C"

    If the city or date is not in the fixture, return success=False with
    a clear ToolError (SA_TOOL_INVALID_INPUT). Do NOT raise.

    MUST call record_tool_call(...) before returning.
    """
    if not (_SAMPLE_DATA / "weather.json").exists():
        raise ToolError(code="SA_TOOL_DEPENDENCY_MISSING", message="weather data unavailable")
    try:
        with open(_SAMPLE_DATA / "weather.json") as f:
            weather = json.load(f)
        input_args = {"city": city, "date": date}
        city_key = city.lower()
        city_data = {k.lower(): v for k, v in weather.items()}.get(city_key)
        if city_data is None:
            output = {"error": "city not found", **input_args}
            record_tool_call("get_weather", input_args, output)
            return ToolResult(
                success=False,
                output=output,
                summary=f"get_weather({city}, {date}): city not found",
                error=ToolError(code="SA_TOOL_INVALID_INPUT", message="city not found"),
            )
        if date not in city_data:
            output = {"error": "date not found", **input_args}
            record_tool_call("get_weather", input_args, output)
            return ToolResult(
                success=False,
                output=output,
                summary=f"get_weather({city}, {date}): date not found",
                error=ToolError(code="SA_TOOL_INVALID_INPUT", message="date not found"),
            )
        day = city_data[date]
        output = {**input_args, **day}
        record_tool_call("get_weather", input_args, output)
        return ToolResult(
            success=True,
            output=output,
            summary=f"get_weather({city}, {date}): {day['condition']}, {day['temperature_c']}C",
        )
    except Exception as e:
        raise ToolError(code="SA_TOOL_EXECUTION_FAILED", message=f"get_weather error: {e}") from e


# ---------------------------------------------------------------------------
# TODO 3 — calculate_cost
# ---------------------------------------------------------------------------
def calculate_cost(
    venue_id: str,
    party_size: int,
    duration_hours: int,
    catering_tier: str = "bar_snacks",
) -> ToolResult:
    """Compute the total cost for a booking.

    Formula:
      base_per_head = base_rates_gbp_per_head[catering_tier]
      venue_mult    = venue_modifiers[venue_id]
      subtotal      = base_per_head * venue_mult * party_size * max(1, duration_hours)
      service       = subtotal * service_charge_percent / 100
      total         = subtotal + service + <venue's hire_fee_gbp + min_spend_gbp>
      deposit_rule  = per deposit_policy thresholds

    Returns:
      output: {
        "venue_id": str,
        "party_size": int,
        "duration_hours": int,
        "catering_tier": str,
        "subtotal_gbp": int,
        "service_gbp": int,
        "total_gbp": int,
        "deposit_required_gbp": int,
      }
      summary: "calculate_cost(<venue>, <party>): total £<N>, deposit £<M>"

    MUST call record_tool_call(...) before returning.
    """
    if not (_SAMPLE_DATA / "catering.json").is_file():
        raise ToolError(code="SA_TOOL_DEPENDENCY_MISSING", message="catering data unavailable")
    if not (_SAMPLE_DATA / "venues.json").exists():
        raise ToolError(code="SA_TOOL_DEPENDENCY_MISSING", message="venues data unavailable")

    try:
        with open(_SAMPLE_DATA / "catering.json") as f:
            catering = json.load(f)
        with open(_SAMPLE_DATA / "venues.json") as f:
            venues = json.load(f)
        input_args = {
            "venue_id": venue_id,
            "party_size": party_size,
            "duration_hours": duration_hours,
            "catering_tier": catering_tier,
        }

        venues_by_id = {v["id"]: v for v in venues}
        venue = venues_by_id.get(venue_id)
        if venue is None:
            output = {**input_args, "error": "venue not found"}
            record_tool_call("calculate_cost", input_args, output)
            return ToolResult(
                success=False,
                output=output,
                summary=f"calculate_cost({venue_id}): venue not found",
                error=ToolError(code="SA_TOOL_INVALID_INPUT", message="venue not found"),
            )

        base_per_head = catering["base_rates_gbp_per_head"].get(catering_tier)
        if base_per_head is None:
            output = {**input_args, "error": "unknown catering tier"}
            record_tool_call("calculate_cost", input_args, output)
            return ToolResult(
                success=False,
                output=output,
                summary=f"calculate_cost({venue_id}): unknown catering tier '{catering_tier}'",
                error=ToolError(code="SA_TOOL_INVALID_INPUT", message="unknown catering tier"),
            )

        venue_mult = catering["venue_modifiers"].get(venue_id, 1)
        subtotal = base_per_head * venue_mult * party_size * max(1, duration_hours)
        service = subtotal * catering["service_charge_percent"] / 100
        total = subtotal + service + venue["hire_fee_gbp"] + venue["min_spend_gbp"]

        if total < 300:
            deposit = 0
        elif total <= 1000:
            deposit = total * 0.20
        else:
            deposit = total * 0.30

        subtotal = int(subtotal)
        service = int(service)
        total = int(total)
        deposit = int(deposit)

        output = {
            **input_args,
            "subtotal_gbp": subtotal,
            "service_gbp": service,
            "total_gbp": total,
            "deposit_required_gbp": deposit,
        }
        record_tool_call("calculate_cost", input_args, output)
        return ToolResult(
            success=True,
            output=output,
            summary=f"calculate_cost({venue_id}, {party_size}): total £{total}, deposit £{deposit}",
        )
    except Exception as e:
        raise ToolError(
            code="SA_TOOL_EXECUTION_FAILED", message=f"calculate_cost error: {e}"
        ) from e


# ---------------------------------------------------------------------------
# TODO 4 — generate_flyer
# ---------------------------------------------------------------------------
def generate_flyer(session: Session, event_details: dict) -> ToolResult:
    """Produce an HTML flyer and write it to workspace/flyer.html.

    event_details is expected to contain at least:
      venue_name, venue_address, date, time, party_size, condition,
      temperature_c, total_gbp, deposit_required_gbp

    Write a self-contained HTML flyer (inline CSS, no external assets). Tag every key fact with data-testid="<n>" so the integrity check can parse it.

    Write a formatted HTML flyer with an H1 title, the event
    facts, a weather summary, and the cost breakdown.

    Returns:
      output: {"path": "workspace/flyer.html", "bytes_written": int}
      summary: "generate_flyer: wrote <path> (<N> chars)"

    MUST call record_tool_call(...) before returning — the integrity
    check compares the flyer's contents against earlier tool outputs.

    IMPORTANT: this tool MUST be registered with parallel_safe=False
    because it writes a file.
    """
    required_keys = [
        "venue_name",
        "venue_address",
        "date",
        "time",
        "party_size",
        "condition",
        "temperature_c",
        "total_gbp",
        "deposit_required_gbp",
    ]
    missing = [k for k in required_keys if k not in event_details]
    if missing:
        raise ToolError(
            code="SA_TOOL_INVALID_INPUT",
            message=f"missing event_details keys: {missing}",
        )

    d = event_details
    html = f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"><title>Event Flyer</title>
<style>
  body {{ font-family: Arial, sans-serif; max-width: 600px; margin: 2em auto; padding: 1em; }}
  h1 {{ color: #2c3e50; }}
  dl {{ display: grid; grid-template-columns: auto 1fr; gap: 0.3em 1em; }}
  dt {{ font-weight: bold; }}
</style>
</head>
<body>
<h1 data-testid="title">{d["venue_name"]} — Event Flyer</h1>
<dl>
  <dt>Venue</dt><dd data-testid="venue_name">{d["venue_name"]}</dd>
  <dt>Address</dt><dd data-testid="venue_address">{d["venue_address"]}</dd>
  <dt>Date</dt><dd data-testid="date">{d["date"]}</dd>
  <dt>Time</dt><dd data-testid="time">{d["time"]}</dd>
  <dt>Party size</dt><dd data-testid="party_size">{d["party_size"]}</dd>
  <dt>Weather</dt><dd data-testid="condition">{d["condition"]}</dd>
  <dt>Temperature</dt><dd data-testid="temperature">{d["temperature_c"]}°C</dd>
  <dt>Total cost</dt><dd data-testid="total">&pound;{d["total_gbp"]}</dd>
  <dt>Deposit required</dt><dd data-testid="deposit">&pound;{d["deposit_required_gbp"]}</dd>
</dl>
</body>
</html>"""

    flyer_path = session.workspace_dir / "flyer.html"
    flyer_path.parent.mkdir(parents=True, exist_ok=True)
    flyer_path.write_text(html, encoding="utf-8")
    bytes_written = flyer_path.stat().st_size

    input_args = {"event_details": event_details}
    output = {"path": "workspace/flyer.html", "bytes_written": bytes_written}
    record_tool_call("generate_flyer", input_args, output)
    return ToolResult(
        success=True,
        output=output,
        summary=f"generate_flyer: wrote workspace/flyer.html ({len(html)} chars)",
    )


# ---------------------------------------------------------------------------
# Registry builder — DO NOT MODIFY the name, signature, or registration calls.
# The grader imports and calls this to pick up your tools.
# ---------------------------------------------------------------------------
def build_tool_registry(session: Session) -> ToolRegistry:
    """Build a session-scoped tool registry with all four Ex5 tools plus
    the sovereign-agent builtins (read_file, write_file, list_files,
    handoff_to_structured, complete_task).

    DO NOT change the tool names — the tests and grader call them by name.
    """
    from sovereign_agent.tools.builtin import make_builtin_registry

    reg = make_builtin_registry(session)

    # venue_search
    reg.register(
        _RegisteredTool(
            name="venue_search",
            description="Search Edinburgh venues by area, party size, and max budget.",
            fn=venue_search,
            parameters_schema={
                "type": "object",
                "properties": {
                    "near": {"type": "string"},
                    "party_size": {"type": "integer"},
                    "budget_max_gbp": {"type": "integer", "default": 1000},
                },
                "required": ["near", "party_size"],
            },
            returns_schema={"type": "object"},
            is_async=False,
            parallel_safe=True,  # read-only
            examples=[
                {
                    "input": {"near": "Haymarket", "party_size": 6, "budget_max_gbp": 800},
                    "output": {"count": 1, "results": [{"id": "haymarket_tap"}]},
                }
            ],
        )
    )

    # get_weather
    reg.register(
        _RegisteredTool(
            name="get_weather",
            description="Get scripted weather for a city on a YYYY-MM-DD date.",
            fn=get_weather,
            parameters_schema={
                "type": "object",
                "properties": {
                    "city": {"type": "string"},
                    "date": {"type": "string"},
                },
                "required": ["city", "date"],
            },
            returns_schema={"type": "object"},
            is_async=False,
            parallel_safe=True,  # read-only
            examples=[
                {
                    "input": {"city": "Edinburgh", "date": "2026-04-25"},
                    "output": {"condition": "cloudy", "temperature_c": 12},
                }
            ],
        )
    )

    # calculate_cost
    reg.register(
        _RegisteredTool(
            name="calculate_cost",
            description="Compute total cost and deposit for a booking.",
            fn=calculate_cost,
            parameters_schema={
                "type": "object",
                "properties": {
                    "venue_id": {"type": "string"},
                    "party_size": {"type": "integer"},
                    "duration_hours": {"type": "integer"},
                    "catering_tier": {
                        "type": "string",
                        "enum": ["drinks_only", "bar_snacks", "sit_down_meal", "three_course_meal"],
                        "default": "bar_snacks",
                    },
                },
                "required": ["venue_id", "party_size", "duration_hours"],
            },
            returns_schema={"type": "object"},
            is_async=False,
            parallel_safe=True,  # pure compute, no shared state
            examples=[
                {
                    "input": {
                        "venue_id": "haymarket_tap",
                        "party_size": 6,
                        "duration_hours": 3,
                    },
                    "output": {"total_gbp": 540, "deposit_required_gbp": 0},
                }
            ],
        )
    )

    # generate_flyer — parallel_safe=False because it writes a file
    def _flyer_adapter(event_details: dict) -> ToolResult:
        return generate_flyer(session, event_details)

    reg.register(
        _RegisteredTool(
            name="generate_flyer",
            description="Write an HTML flyer for the event to workspace/flyer.html.",
            fn=_flyer_adapter,
            parameters_schema={
                "type": "object",
                "properties": {"event_details": {"type": "object"}},
                "required": ["event_details"],
            },
            returns_schema={"type": "object"},
            is_async=False,
            parallel_safe=False,  # writes a file — MUST be False
            examples=[
                {
                    "input": {
                        "event_details": {
                            "venue_name": "Haymarket Tap",
                            "date": "2026-04-25",
                            "party_size": 6,
                        }
                    },
                    "output": {"path": "workspace/flyer.html"},
                }
            ],
        )
    )

    return reg


__all__ = [
    "build_tool_registry",
    "venue_search",
    "get_weather",
    "calculate_cost",
    "generate_flyer",
]
