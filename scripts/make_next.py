"""make_next — inspect repo state, print the exact next command.

Answers the question: "I ran make, now what do I actually do?"

Walks a decision tree:
  1. Is .venv set up?           → suggest `make setup`
  2. Is .env populated?         → suggest editing it
  3. Has `make verify` passed?  → suggest running it
  4. Are tests green?           → progress based on what's implemented
  5. Which exercise is next?    → tools.py → integrity.py → Ex6 etc.

Outputs one SPECIFIC next step plus context. Not a tutorial.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


class _C:
    _on = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None

    @classmethod
    def _w(cls, code: str, s: str) -> str:
        return f"\033[{code}m{s}\033[0m" if cls._on else s

    @classmethod
    def g(cls, s: str) -> str:
        return cls._w("32", s)

    @classmethod
    def y(cls, s: str) -> str:
        return cls._w("33", s)

    @classmethod
    def b(cls, s: str) -> str:
        return cls._w("1", s)

    @classmethod
    def c(cls, s: str) -> str:
        return cls._w("36", s)

    @classmethod
    def d(cls, s: str) -> str:
        return cls._w("2", s)

    @classmethod
    def r(cls, s: str) -> str:
        return cls._w("31", s)


def _file_has_todo(path: Path, marker: str = "raise NotImplementedError") -> bool:
    """True if the file still has TODO stubs."""
    if not path.exists():
        return True
    return marker in path.read_text(encoding="utf-8")


def _env_has_nebius_key() -> bool:
    env_path = REPO / ".env"
    if not env_path.exists():
        return False
    text = env_path.read_text(encoding="utf-8")
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        if k.strip() == "NEBIUS_KEY" and v.strip().strip('"').strip("'"):
            return True
    return False


def _verify_log_fresh() -> bool:
    """Has verify ever been run and produced green output?"""
    # Heuristic: check if .venv exists and sovereign-agent imports
    venv = REPO / ".venv"
    if not venv.exists():
        return False
    return True


def _tool_counts() -> tuple[int, int]:
    """Return (implemented, total) for the student's TODOs across the homework."""
    todo_files = [
        REPO / "starter" / "edinburgh_research" / "tools.py",
        REPO / "starter" / "edinburgh_research" / "integrity.py",
        REPO / "starter" / "rasa_half" / "validator.py",
        REPO / "starter" / "rasa_half" / "structured_half.py",
        REPO / "starter" / "handoff_bridge" / "bridge.py",
        REPO / "starter" / "voice_pipeline" / "voice_loop.py",
        REPO / "rasa_project" / "actions" / "actions.py",
    ]
    total = len(todo_files)
    implemented = sum(1 for p in todo_files if not _file_has_todo(p))
    return implemented, total


def _banner(title: str, emoji: str) -> None:
    print()
    print(_C.b(_C.y(f"{emoji} {title}")))
    print(_C.d("─" * 60))


def _step(n: int | None, cmd: str, detail: str) -> None:
    num = f"{n}." if n is not None else " "
    print(f"  {_C.g(num)} {_C.c(cmd):<30} {_C.d(detail)}")


def main() -> int:
    # Test — do nothing, just check they're in the right dir
    if not (REPO / "Makefile").exists():
        print(_C.r("✗") + " This doesn't look like a homework-pub-booking repo.")
        print(f"  (No Makefile in {REPO})")
        return 1

    # ── 1. setup? ────────────────────────────────────────────────────
    venv_ok = (REPO / ".venv").exists() or (REPO / "uv.lock").exists()
    env_exists = (REPO / ".env").exists()
    env_populated = _env_has_nebius_key()

    if not venv_ok:
        _banner("You haven't run setup yet.", "🚀")
        _step(1, "make setup", "creates .venv, installs deps, creates .env")
        print()
        print(_C.d("  After this, run `make next` again for the next step."))
        return 0

    if not env_exists:
        _banner(".env is missing (setup probably failed partway).", "⚠")
        _step(1, "make env-bootstrap", "regenerate .env.example from fallback")
        _step(2, "make setup", "re-run setup")
        return 0

    if not env_populated:
        _banner("Your .env doesn't have NEBIUS_KEY yet.", "🔑")
        _step(None, "$EDITOR .env", "set NEBIUS_KEY=<your-key>")
        print()
        print(_C.d("  Get a free key at https://tokenfactory.nebius.com"))
        print(_C.d("  Then: make verify"))
        return 0

    # ── 2. verify? ───────────────────────────────────────────────────
    # We can't tell for sure if verify passed, but if sovereign_agent imports
    # we assume the env is usable.
    try:
        subprocess.run(
            [sys.executable, "-c", "import sovereign_agent"],
            check=True,
            capture_output=True,
            timeout=5,
        )
        sa_ok = True
    except Exception:
        sa_ok = False

    if not sa_ok:
        _banner("sovereign-agent can't be imported.", "⚠")
        _step(1, "make setup", "re-run the install (it's idempotent)")
        _step(2, "make verify", "confirms the env works end-to-end")
        return 0

    # ── 3. which exercise? ───────────────────────────────────────────
    implemented, total = _tool_counts()

    if implemented == 0:
        _banner("Env is ready. Time to start Ex5.", "📚")
        print(f"  {_C.d('Implemented:')} {_C.r(f'{implemented}/{total}')} files")
        print()
        print("  Next step:")
        _step(1, "make ex5", "run the offline scenario (currently prints TODO message)")
        print()
        print(f"  {_C.d('Then open these files and implement the TODOs:')}")
        print(f"    {_C.c('starter/edinburgh_research/tools.py')}")
        print(f"    {_C.c('starter/edinburgh_research/integrity.py')}")
        print()
        print(f"  {_C.d('Use')} {_C.c('make test')} {_C.d('between changes.')}")
        print(f"  {_C.d('When skipped tests turn to passes, you are on track.')}")
        return 0

    # ── 4. which file next? ──────────────────────────────────────────
    todo_order = [
        ("Ex5 — tools", REPO / "starter/edinburgh_research/tools.py"),
        ("Ex5 — integrity", REPO / "starter/edinburgh_research/integrity.py"),
        ("Ex6 — validator", REPO / "starter/rasa_half/validator.py"),
        ("Ex6 — structured_half", REPO / "starter/rasa_half/structured_half.py"),
        ("Ex6 — rasa action", REPO / "rasa_project/actions/actions.py"),
        ("Ex7 — bridge", REPO / "starter/handoff_bridge/bridge.py"),
        ("Ex8 — voice loop", REPO / "starter/voice_pipeline/voice_loop.py"),
    ]
    for label, path in todo_order:
        if _file_has_todo(path):
            _banner(f"Working on: {label}", "🎯")
            print(f"  {_C.d('Progress:')} {_C.g(f'{implemented}/{total}')} files implemented\n")
            print(f"  Next file: {_C.c(str(path.relative_to(REPO)))}")
            print()
            if "tools" in str(path):
                _step(1, "make test", "see which tool tests skip → implement those")
                _step(2, "make ex5", "run scenario offline once tools.py is done")
            elif "integrity" in str(path):
                _step(1, "make ex5", "see if dataflow check triggers on your flyer")
            elif "rasa" in str(path).lower() or "validator" in str(path):
                _step(1, "make setup-rasa", "one-time rasa-pro install (~2 min)")
                _step(2, "make ex6", "mock-server mode first (no rasa setup needed)")
                _step(3, "make ex6-help", "the three-terminal recipe")
            elif "bridge" in str(path):
                _step(1, "make ex7", "offline scripted round-trip")
                _step(2, "make ex7-real", "once offline is green")
            elif "voice" in str(path):
                _step(1, "make setup-voice", "speechmatics + sounddevice")
                _step(2, "make ex8-text", "text mode first — no mic needed")
            return 0

    # ── 5. all TODOs done — graduate to final checks ─────────────────
    _banner("All TODOs implemented. Time to lock in the grade.", "🎉")
    print(f"  {_C.d('Progress:')} {_C.g(f'{implemented}/{total}')} files implemented\n")
    _step(1, "make test", "all skips should be passes")
    _step(2, "make check-submit", "local grader (Mechanical + Behavioural)")
    _step(3, "$EDITOR answers/ex9_reflection.md", "the Reasoning layer (30pts)")
    print()
    print(_C.d("  For a final sanity run:"))
    _step(None, "make ci", "lint + format + test + collect")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # noqa: BLE001
        print(_C.r(f"✗ make_next crashed: {e}"))
        sys.exit(1)
