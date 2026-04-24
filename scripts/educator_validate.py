"""educator_validate.py — validate the homework end-to-end before cohort release.

Workflow:
  1. Back up starter/ and answers/ to .educator_backup/ (idempotent)
  2. Apply solution/ over starter/ and answers/
  3. Run every scenario (Ex5-Ex8)
  4. Run the grader
  5. Report whether the homework is ready to ship
  6. Restore starter/ and answers/ from backup

The backup/restore is NOT optional — this script mutates the working
tree temporarily. If anything goes wrong mid-run, `make educator-reset`
will clean up.

Exit codes:
  0 — homework passes validation (46+/76 achievable locally)
  1 — validation found problems
  2 — script itself failed to run
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
BACKUP = REPO / ".educator_backup"
SOLUTION = REPO / "solution"

# Load .env into os.environ so every subprocess we spawn inherits
# RASA_PRO_LICENSE, NEBIUS_KEY, SPEECHMATICS_KEY, etc. Without this
# the harness's scenarios see the shell env but not the file.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _dotenv import load_dotenv_into_environ  # noqa: E402

load_dotenv_into_environ(REPO / ".env")


def _cache_dir() -> Path:
    """XDG-standard cache path for educator logs. Used by diagnostics."""
    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Caches"
    elif sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    else:
        base = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache")
    p = base / "sovereign-agent" / "homework-pub-booking"
    p.mkdir(parents=True, exist_ok=True)
    return p


class _Tee:
    """Duplicate writes to multiple streams. Used for educator-validate's
    split output: interactive terminal + cached log file for diagnostics."""

    def __init__(self, *streams):
        self.streams = streams

    def write(self, data):
        for s in self.streams:
            try:
                s.write(data)
                s.flush()
            except Exception:
                pass

    def flush(self):
        for s in self.streams:
            try:
                s.flush()
            except Exception:
                pass


class _C:
    _on = sys.stdout.isatty()

    @classmethod
    def _w(cls, code: str, s: str) -> str:
        return f"\033[{code}m{s}\033[0m" if cls._on else s

    @classmethod
    def g(cls, s: str) -> str:  # green
        return cls._w("32", s)

    @classmethod
    def r(cls, s: str) -> str:  # red
        return cls._w("31", s)

    @classmethod
    def y(cls, s: str) -> str:  # yellow
        return cls._w("33", s)

    @classmethod
    def d(cls, s: str) -> str:  # dim
        return cls._w("2", s)

    @classmethod
    def b(cls, s: str) -> str:  # bold
        return cls._w("1", s)


def _run(cmd: list[str], cwd: Path | None = None, timeout: int = 120) -> tuple[int, str, str]:
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=cwd or REPO,
            timeout=timeout,
        )
        return proc.returncode, proc.stdout, proc.stderr
    except subprocess.TimeoutExpired as e:
        # Return what we have so diagnostics can see the hang point
        partial_stdout = (e.stdout or b"").decode("utf-8", errors="replace") if e.stdout else ""
        partial_stderr = (e.stderr or b"").decode("utf-8", errors="replace") if e.stderr else ""
        return 124, partial_stdout, f"TIMEOUT after {timeout}s\n{partial_stderr}"


def backup_starter() -> None:
    """Idempotent snapshot. Captures starter/, answers/, rasa_project/."""
    if BACKUP.exists():
        shutil.rmtree(BACKUP)
    BACKUP.mkdir()
    shutil.copytree(REPO / "starter", BACKUP / "starter")
    shutil.copytree(REPO / "answers", BACKUP / "answers")
    if (REPO / "rasa_project").exists():
        shutil.copytree(REPO / "rasa_project", BACKUP / "rasa_project")


def restore_starter() -> None:
    """Reverse of backup_starter. Idempotent."""
    if not BACKUP.exists():
        return
    for name in ("starter", "answers", "rasa_project"):
        target = REPO / name
        if target.exists():
            shutil.rmtree(target)
        backup_path = BACKUP / name
        if backup_path.exists():
            shutil.copytree(backup_path, target)


def apply_solution() -> int:
    """Run the apply_solution.sh shell script.

    We pass --force because the harness manages Rasa's lifecycle itself
    (spawns + kills processes as part of running ex6-real in tier 3).
    Without --force, apply_solution.sh refuses when it detects running
    rasa/action-server processes — which is correct for humans running
    it manually, but wrong for the harness.
    """
    rc, _out, err = _run(["bash", str(SOLUTION / "apply_solution.sh"), "--force"])
    if rc != 0:
        print(_C.r("✗") + " apply_solution.sh failed")
        print(err)
    return rc


def _find_latest_session_dir(scenario_hint: str) -> Path | None:
    """Find the most recent session dir for a scenario. Looks in both
    repo-local sessions/ and the platform user-data dir."""
    candidates: list[Path] = []
    if (REPO / "sessions").exists():
        candidates.extend((REPO / "sessions").glob(f"*{scenario_hint}*"))
        candidates.extend((REPO / "sessions").glob("sess_*"))

    # platform dir
    if sys.platform == "darwin":
        data_root = Path.home() / "Library" / "Application Support" / "sovereign-agent"
    elif sys.platform == "win32":
        root = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        data_root = Path(root) / "sovereign-agent"
    else:
        data_root = (
            Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
            / "sovereign-agent"
        )
    if data_root.exists():
        for ex_dir in data_root.glob(f"examples/*{scenario_hint}*"):
            candidates.extend(ex_dir.glob("sess_*"))

    candidates = [c for c in candidates if c.is_dir()]
    if not candidates:
        return None
    candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0]


def _scan_trace_for_failures(session_dir: Path) -> list[str]:
    """Return list of human-readable tool-failure descriptions from trace.jsonl."""
    import json as _json

    trace = session_dir / "logs" / "trace.jsonl"
    if not trace.exists():
        return []
    failures: list[str] = []
    for line in trace.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            e = _json.loads(line)
        except _json.JSONDecodeError:
            continue
        if e.get("event_type") == "executor.tool_called":
            p = e.get("payload") or {}
            if not p.get("success", True):
                summary = (p.get("summary") or "").replace("\n", " ")[:140]
                failures.append(f"{p.get('tool', '?')}: {summary}")
    return failures


def run_scenario(name: str, module: str, extra_args: list[str] | None = None) -> tuple[bool, str]:
    """Run one scenario module. Return (passed, summary).

    "Passing" requires BOTH exit 0 AND no failed tool calls in the
    session's trace.jsonl. A scenario can exit 0 even when an internal
    tool call failed (e.g. handoff succeeded with degraded data but
    the bridge still completed), so we scan for it.
    """
    extra_args = extra_args or []
    cmd = ["uv", "run", "python", "-m", module, *extra_args]
    timeout = 600 if "--real" in extra_args else 120
    rc, out, err = _run(cmd, timeout=timeout)

    if rc != 0:
        tail = (out + err).strip().splitlines()[-5:]
        return False, f"{name}: exit {rc} — " + " | ".join(tail)

    # Exit 0 — now check for failed tool calls in the latest session.
    # Module name like 'starter.edinburgh_research.run' → 'edinburgh-research'
    scenario_hint = module.split(".")[1].replace("_", "-") if "." in module else module
    session_dir = _find_latest_session_dir(scenario_hint)
    if session_dir is None:
        return True, f"{name}: ran cleanly (no session found to audit)"

    failures = _scan_trace_for_failures(session_dir)
    if failures:
        preview = " · ".join(failures[:2])
        return False, f"{name}: tool failures in session — {preview}"
    return True, f"{name}: ran cleanly"


def run_grader() -> tuple[int, int, str]:
    """Run the grader. Returns (earned, possible_local, raw_output)."""
    rc, out, err = _run(["uv", "run", "python", "-m", "grader.check_submit"])
    combined = out + err
    # Parse the "Raw score:" line
    earned = possible = 0
    for line in combined.splitlines():
        if "Raw score:" in line:
            # e.g.  "**Raw score:** 46.0 / 46"
            import re

            m = re.search(r"(\d+(?:\.\d+)?)\s*/\s*(\d+)", line)
            if m:
                earned = int(float(m.group(1)))
                possible = int(m.group(2))
                break
    return earned, possible, combined


def print_section(title: str) -> None:
    print()
    print(_C.b(f"  {title}"))
    print(_C.d("  " + "─" * 66))


def main() -> int:
    # Tee stdout+stderr to a log file so `make educator-diagnostics` can
    # read the last run without manual copy-paste.
    log_path = _cache_dir() / "educator_validate.log"
    log_file = log_path.open("w", encoding="utf-8")
    original_stdout = sys.stdout
    original_stderr = sys.stderr
    sys.stdout = _Tee(original_stdout, log_file)
    sys.stderr = _Tee(original_stderr, log_file)

    try:
        return _main_impl()
    finally:
        sys.stdout = original_stdout
        sys.stderr = original_stderr
        log_file.close()
        print(_C.d(f"  (full log cached at {log_path})"))


def _main_impl() -> int:
    real = "--real" in sys.argv

    print()
    print(_C.y("━" * 72))
    print(_C.b("  homework-pub-booking") + _C.d("  ·  ") + _C.b("educator validation harness"))
    print(_C.d(f"  repo: {REPO}"))
    print(
        _C.d(
            f"  mode: {'REAL (live services, costs tokens + starts Docker)' if real else 'offline (mocks, fakes, stubs)'}"
        )
    )
    print(_C.y("━" * 72))

    if not SOLUTION.exists():
        print(
            _C.r("✗") + " solution/ directory not found. This harness needs the reference solution."
        )
        print(_C.d("  The educator should keep solution/ in a private sibling repo; copy"))
        print(_C.d("  it into ./solution/ before running `make educator-validate`."))
        return 2

    # ── Phase 1 — back up ────────────────────────────────────────────
    print_section("Phase 1 — backing up starter/ and answers/")
    backup_starter()
    print(f"  {_C.g('✓')} backed up to {BACKUP.relative_to(REPO)}/")

    # ── Phase 2 — apply solution ─────────────────────────────────────
    print_section("Phase 2 — applying solution/")
    try:
        rc = apply_solution()
        if rc != 0:
            print(f"  {_C.r('✗')} apply_solution.sh exit {rc}")
            restore_starter()
            return 1
        print(f"  {_C.g('✓')} solution applied")

        # ── Phase 3 — run each scenario ─────────────────────────────
        print_section(
            "Phase 3 — running scenarios"
            + (" (REAL mode — live services)" if real else " (offline mode)")
        )
        if real:
            scenarios = [
                ("ex5 (real Nebius)", "starter.edinburgh_research.run", ["--real"]),
                ("ex6 (real Rasa)", "starter.rasa_half.run", ["--real"]),
                ("ex7 (real Nebius)", "starter.handoff_bridge.run", ["--real"]),
            ]
        else:
            scenarios = [
                ("ex5", "starter.edinburgh_research.run", []),
                ("ex6", "starter.rasa_half.run", []),
                ("ex7", "starter.handoff_bridge.run", []),
            ]
        all_pass = True
        scenario_results: list[tuple[str, bool, str]] = []
        for name, module, args in scenarios:
            ok, summary = run_scenario(name, module, args)
            mark = _C.g("✓") if ok else (_C.y("⚠") if real else _C.r("✗"))
            print(f"  {mark} {summary}")
            scenario_results.append((name, ok, summary))
            if not ok:
                all_pass = False

        # Ex8 heuristic check
        voice_loop = (REPO / "starter/voice_pipeline/voice_loop.py").read_text()
        voice_impl = "raise NotImplementedError" not in voice_loop
        mark = _C.g("✓") if voice_impl else _C.r("✗")
        print(f"  {mark} ex8: voice_loop.run_voice_mode implemented (heuristic)")
        if not voice_impl:
            all_pass = False

        # ── Phase 4 — run grader ─────────────────────────────────────
        print_section("Phase 4 — running grader against solution-applied tree")
        earned, possible, _output = run_grader()
        local_max = 46
        print(f"  local grader score: {earned} / {local_max} (excluding 30pt Reasoning layer)")

        # ── Verdict ──────────────────────────────────────────────────
        # OFFLINE mode: strict pass/fail. Deterministic, must be green before ship.
        # REAL mode:    DIAGNOSTIC. Real LLMs spiral, real services glitch — that's
        #               data, not a build failure. Always exits 0 so the educator
        #               can review the full report.
        print()
        print(_C.y("━" * 72))

        if real:
            # Diagnostic mode — always green-exit
            n_pass = sum(1 for _, ok, _ in scenario_results if ok) + (1 if voice_impl else 0)
            n_total = len(scenario_results) + 1
            print(_C.b(f"  🔬 REAL-mode diagnostic: {n_pass}/{n_total} scenarios clean"))
            print()
            print(_C.d("     This is a DIAGNOSTIC run, not a pass/fail check. Real LLMs and"))
            print(_C.d("     services behave nondeterministically — Qwen spirals, Rasa caches"))
            print(_C.d("     stale code, voice SDKs glitch. These are teaching moments for"))
            print(_C.d("     students, not bugs to suppress."))
            print()
            failures = [(name, summary) for name, ok, summary in scenario_results if not ok]
            if failures:
                print(_C.b("     Failures this run:"))
                for fname, fsummary in failures:
                    short = fsummary.split(" — ", 1)[-1][:90]
                    print(f"       {_C.y('•')} {fname}: {short}")
                print()
                print(_C.d("     For every known real-mode failure mode, see:"))
                print(_C.d("       docs/real-mode-failures.md"))
            else:
                print(
                    _C.g(
                        "     All real scenarios completed this run. (Run again; results may vary.)"
                    )
                )
            verdict_rc = 0  # always succeed in diagnostic mode
        else:
            # Offline mode — strict
            if earned >= local_max - 2 and all_pass:
                verdict = _C.g("✓ homework ready to ship")
                verdict_rc = 0
            elif earned >= local_max - 6:
                verdict = _C.y("⚠ homework mostly working; investigate gaps")
                verdict_rc = 0
            else:
                verdict = _C.r("✗ homework has real problems — investigate before cohort release")
                verdict_rc = 1
            print(f"  {verdict}")
            if not all_pass:
                verdict_rc = 1

        print(_C.y("━" * 72))

    finally:
        # ── Phase 5 — restore ────────────────────────────────────────
        print_section("Phase 5 — restoring pristine starter/ and answers/")
        restore_starter()
        print(f"  {_C.g('✓')} restored")

    print()
    return verdict_rc


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # noqa: BLE001
        import traceback

        print(_C.r("✗") + f" harness crashed: {e}")
        traceback.print_exc()
        try:
            restore_starter()
        except Exception:  # noqa: BLE001
            pass
        sys.exit(2)
