"""educator_diagnostics.py — comprehensive diagnostics for educator iteration.

When make educator-validate fails, running this produces a single
copy-pasteable report with:

  - Platform + Python + uv + Docker versions
  - Every env var the exercises depend on (values masked)
  - Service availability checks (Docker daemon, Rasa license, Nebius auth,
    Speechmatics auth, Rime.ai auth) — tells you what's missing
  - Exact rasa-pro package version
  - Last ci-real or validate log excerpt if available
  - Git state (branch, HEAD, dirty?) if git is available

Usage:
  make educator-diagnostics            # full report
  make educator-diagnostics --quick    # skip network checks

Design principle: NEVER fail this script. Catch every exception, report
what we found and what we couldn't. The output is the input for the
next debugging iteration.
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
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
    def r(cls, s: str) -> str:
        return cls._w("31", s)

    @classmethod
    def y(cls, s: str) -> str:
        return cls._w("33", s)

    @classmethod
    def d(cls, s: str) -> str:
        return cls._w("2", s)

    @classmethod
    def b(cls, s: str) -> str:
        return cls._w("1", s)


@dataclass
class Check:
    name: str
    ok: bool | None  # None = couldn't determine
    detail: str = ""
    raw: str = ""  # raw output for unknown-error diagnostics


@dataclass
class Section:
    title: str
    checks: list[Check] = field(default_factory=list)


def _run(cmd: list[str], timeout: int = 15) -> tuple[int, str, str]:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return proc.returncode, proc.stdout or "", proc.stderr or ""
    except FileNotFoundError:
        return 127, "", f"command not found: {cmd[0]}"
    except subprocess.TimeoutExpired:
        return 124, "", f"timeout after {timeout}s: {' '.join(cmd)}"
    except Exception as e:  # noqa: BLE001
        return 1, "", f"{type(e).__name__}: {e}"


def _mask(value: str) -> str:
    if not value:
        return "(empty)"
    if len(value) <= 8:
        return "***"
    return f"{value[:4]}...{value[-4:]}"


def _read_env_file_vars() -> dict[str, str]:
    env = {}
    env_file = REPO / ".env"
    if not env_file.exists():
        return env
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[7:]
        k, _, v = line.partition("=")
        k, v = k.strip(), v.strip().strip('"').strip("'")
        if v:
            env[k] = v
    return env


def section_platform() -> Section:
    s = Section("Platform")

    s.checks.append(
        Check(
            "Python",
            ok=sys.version_info >= (3, 12),
            detail=f"{sys.version.split()[0]} on {platform.platform()}",
        )
    )

    rc, out, _ = _run(["uv", "--version"])
    s.checks.append(
        Check(
            "uv",
            ok=(rc == 0),
            detail=out.strip() if rc == 0 else "not installed",
        )
    )

    rc, out, err = _run(["docker", "--version"])
    s.checks.append(
        Check("docker CLI", ok=(rc == 0), detail=out.strip() if rc == 0 else "not installed")
    )

    rc, out, err = _run(["docker", "info", "--format", "{{.ServerVersion}}"], timeout=10)
    if rc == 0 and out.strip():
        s.checks.append(Check("docker daemon", ok=True, detail=f"server {out.strip()}"))
    else:
        # Why? Daemon not running is the most common "Docker installed but unusable" case.
        err_summary = (err or "unreachable").splitlines()[0] if err else "unreachable"
        s.checks.append(
            Check(
                "docker daemon",
                ok=False,
                detail=f"daemon not reachable: {err_summary}",
                raw=err,
            )
        )

    rc, out, _ = _run(["docker", "compose", "version"], timeout=10)
    s.checks.append(
        Check(
            "docker compose",
            ok=(rc == 0),
            detail=out.strip() if rc == 0 else "not available (needed for Ex6 Rasa)",
        )
    )

    return s


def section_env_vars() -> Section:
    s = Section("Environment variables (loaded from .env + shell)")
    env_file_vars = _read_env_file_vars()

    # Merge: shell env wins over .env (matches dotenv's override=False default)
    all_env = {**env_file_vars, **os.environ}

    # Required for all homework
    important = [
        ("NEBIUS_KEY", "Ex5, Ex7, Ex8 (Llama persona)"),
        ("SOVEREIGN_AGENT_LLM_BASE_URL", "Ex5, Ex7 (defaults to Nebius)"),
        ("SOVEREIGN_AGENT_LLM_PLANNER_MODEL", "Ex5, Ex7 (defaults fine)"),
        ("SOVEREIGN_AGENT_LLM_EXECUTOR_MODEL", "Ex5, Ex7 (defaults fine)"),
        ("RASA_PRO_LICENSE", "Ex6 (Rasa Pro container)"),
        ("SPEECHMATICS_KEY", "Ex8 voice"),
        ("RIME_API_KEY", "Ex8 voice TTS"),
    ]
    for var, purpose in important:
        val = all_env.get(var, "")
        src = (
            "(.env)"
            if var in env_file_vars and var not in os.environ
            else ("(shell)" if val else "")
        )
        if val:
            s.checks.append(Check(var, ok=True, detail=f"{_mask(val)} {src} — {purpose}"))
        else:
            s.checks.append(Check(var, ok=False, detail=f"(not set) — needed for: {purpose}"))

    return s


def section_python_deps() -> Section:
    s = Section("Python packages")

    for pkg in ("sovereign_agent", "openai", "typer", "pyyaml"):
        try:
            import importlib
            import importlib.metadata

            # Import probe
            mod_name = pkg if pkg != "pyyaml" else "yaml"
            importlib.import_module(mod_name)
            version = importlib.metadata.version(pkg)
            s.checks.append(Check(pkg, ok=True, detail=f"v{version}"))
        except Exception as e:  # noqa: BLE001
            s.checks.append(Check(pkg, ok=False, detail=f"{type(e).__name__}: {e}"))

    # Optional packages — fine to be missing
    for pkg in ("rasa_pro", "speechmatics", "httpx"):
        try:
            import importlib
            import importlib.metadata

            # speechmatics may be 'speechmatics-python'
            pkg_dist = pkg.replace("_", "-")
            if pkg == "speechmatics":
                pkg_dist = "speechmatics-python"
            try:
                version = importlib.metadata.version(pkg_dist)
                s.checks.append(Check(pkg, ok=True, detail=f"v{version} (optional)"))
            except importlib.metadata.PackageNotFoundError:
                s.checks.append(
                    Check(pkg, ok=None, detail="not installed (only needed for specific exercises)")
                )
        except Exception as e:  # noqa: BLE001
            s.checks.append(Check(pkg, ok=None, detail=f"probe error: {e}"))

    return s


def section_service_auth(quick: bool) -> Section:
    s = Section("Service authentication (skipped with --quick)")
    if quick:
        s.checks.append(Check("skipped", ok=None, detail="use without --quick to probe services"))
        return s

    env_vars = {**_read_env_file_vars(), **os.environ}

    # Nebius auth probe
    nebius_key = env_vars.get("NEBIUS_KEY", "")
    if not nebius_key:
        s.checks.append(Check("Nebius auth", ok=False, detail="NEBIUS_KEY not set"))
    else:
        try:
            import asyncio

            from openai import AsyncOpenAI

            async def probe():
                client = AsyncOpenAI(
                    api_key=nebius_key,
                    base_url=env_vars.get(
                        "SOVEREIGN_AGENT_LLM_BASE_URL",
                        "https://api.tokenfactory.nebius.com/v1/",
                    ),
                )
                return await asyncio.wait_for(
                    client.chat.completions.create(
                        model=env_vars.get("NEBIUS_SMOKE_MODEL", "google/gemma-2-2b-it"),
                        messages=[{"role": "user", "content": "ok"}],
                        max_tokens=3,
                    ),
                    timeout=15.0,
                )

            resp = asyncio.run(probe())
            s.checks.append(
                Check(
                    "Nebius auth",
                    ok=True,
                    detail=f"200 OK, model {resp.model}",
                )
            )
        except Exception as e:  # noqa: BLE001
            err_str = str(e)
            hint = ""
            if "401" in err_str or "Unauthorized" in err_str:
                hint = " (invalid key)"
            elif "404" in err_str:
                hint = " (endpoint/model wrong)"
            elif "timeout" in err_str.lower():
                hint = " (network or rate limit)"
            s.checks.append(
                Check(
                    "Nebius auth",
                    ok=False,
                    detail=f"{type(e).__name__}: {err_str[:100]}{hint}",
                    raw=err_str,
                )
            )

    # Speechmatics — check by importing and making an auth probe
    spx_key = env_vars.get("SPEECHMATICS_KEY", "")
    if not spx_key:
        s.checks.append(
            Check(
                "Speechmatics auth",
                ok=None,
                detail="SPEECHMATICS_KEY not set (only needed for Ex8 voice)",
            )
        )
    else:
        try:
            import urllib.request

            req = urllib.request.Request(
                "https://asr.api.speechmatics.com/v2/jobs",
                headers={"Authorization": f"Bearer {spx_key}"},
                method="GET",
            )
            try:
                with urllib.request.urlopen(req, timeout=10) as resp:
                    status = resp.status
                s.checks.append(Check("Speechmatics auth", ok=True, detail=f"HTTP {status}"))
            except urllib.error.HTTPError as he:
                # 401 means key bad; any other HTTP error is a success in terms of reachability
                ok = he.code != 401
                s.checks.append(
                    Check(
                        "Speechmatics auth",
                        ok=ok,
                        detail=f"HTTP {he.code}"
                        + (" (key invalid)" if he.code == 401 else " (reachable)"),
                    )
                )
        except Exception as e:  # noqa: BLE001
            s.checks.append(Check("Speechmatics auth", ok=False, detail=f"{type(e).__name__}: {e}"))

    # Rime.ai — probe auth via their API
    rime_key = env_vars.get("RIME_API_KEY", "")
    if not rime_key:
        s.checks.append(
            Check(
                "Rime.ai auth",
                ok=None,
                detail="RIME_API_KEY not set (only needed for Ex8 voice TTS)",
            )
        )
    else:
        try:
            import urllib.request

            # Rime.ai TTS endpoint — a bare GET to /v1/rime-tts returns auth error or method not allowed
            # depending on path. We just want to confirm the key is recognised.
            req = urllib.request.Request(
                "https://users.rime.ai/v1/user",
                headers={"Authorization": f"Bearer {rime_key}"},
                method="GET",
            )
            try:
                with urllib.request.urlopen(req, timeout=10) as resp:
                    s.checks.append(Check("Rime.ai auth", ok=True, detail=f"HTTP {resp.status}"))
            except urllib.error.HTTPError as he:
                ok = he.code != 401 and he.code != 403
                s.checks.append(
                    Check(
                        "Rime.ai auth",
                        ok=ok,
                        detail=f"HTTP {he.code}"
                        + (" (key invalid)" if he.code in (401, 403) else " (reachable)"),
                    )
                )
        except Exception as e:  # noqa: BLE001
            s.checks.append(Check("Rime.ai auth", ok=False, detail=f"{type(e).__name__}: {e}"))

    return s


def section_project_state() -> Section:
    s = Section("Project state")

    # Git state
    if shutil.which("git") and (REPO / ".git").exists():
        rc, branch, _ = _run(["git", "-C", str(REPO), "rev-parse", "--abbrev-ref", "HEAD"])
        rc2, sha, _ = _run(["git", "-C", str(REPO), "rev-parse", "--short", "HEAD"])
        rc3, status, _ = _run(["git", "-C", str(REPO), "status", "--porcelain"])
        dirty = bool(status.strip()) if rc3 == 0 else None
        if rc == 0 and rc2 == 0:
            detail = f"branch {branch.strip()} @ {sha.strip()}"
            if dirty:
                detail += " (dirty)"
            s.checks.append(Check("git", ok=True, detail=detail))
        else:
            s.checks.append(Check("git", ok=None, detail="git repo but couldn't read HEAD"))
    else:
        s.checks.append(Check("git", ok=None, detail="not a git repo"))

    # solution/ present?
    solution_dir = REPO / "solution"
    if solution_dir.exists():
        ex_count = len(
            [p for p in solution_dir.iterdir() if p.is_dir() and p.name.startswith("ex")]
        )
        s.checks.append(Check("solution/", ok=True, detail=f"present, {ex_count} exercise dirs"))
    else:
        s.checks.append(
            Check(
                "solution/",
                ok=None,
                detail="not present (expected on student checkouts; needed for educator-validate)",
            )
        )

    # .educator_backup/ present?
    backup_dir = REPO / ".educator_backup"
    if backup_dir.exists():
        s.checks.append(
            Check(".educator_backup/", ok=True, detail="present (last validate ran successfully)")
        )
    else:
        s.checks.append(
            Check(".educator_backup/", ok=None, detail="not present (validate hasn't run yet)")
        )

    # Pristine state check: are TODOs still present?
    todos_present = []
    todos_absent = []
    for name, path in [
        ("ex5 tools", "starter/edinburgh_research/tools.py"),
        ("ex5 integrity", "starter/edinburgh_research/integrity.py"),
        ("ex6 validator", "starter/rasa_half/validator.py"),
        ("ex6 half", "starter/rasa_half/structured_half.py"),
        ("ex7 bridge", "starter/handoff_bridge/bridge.py"),
        ("ex8 voice", "starter/voice_pipeline/voice_loop.py"),
    ]:
        p = REPO / path
        if p.exists() and "raise NotImplementedError" in p.read_text(encoding="utf-8"):
            todos_present.append(name)
        else:
            todos_absent.append(name)
    if todos_present and todos_absent:
        s.checks.append(
            Check(
                "starter state",
                ok=None,
                detail=f"mixed: {len(todos_present)} TODO / {len(todos_absent)} implemented",
            )
        )
    elif todos_present:
        s.checks.append(Check("starter state", ok=True, detail="pristine (all TODOs present)"))
    elif todos_absent:
        s.checks.append(Check("starter state", ok=True, detail="implemented (or solution applied)"))

    return s


def section_last_validate_log() -> Section:
    s = Section("Last validation run log (tail)")
    cache = Path.home() / "Library" / "Caches" / "sovereign-agent" / "homework-pub-booking"
    if not cache.exists():
        cache = Path.home() / ".cache" / "sovereign-agent" / "homework-pub-booking"
    log = cache / "educator_validate.log"
    if log.exists():
        tail = log.read_text(encoding="utf-8").splitlines()[-30:]
        s.checks.append(Check("last validate log", ok=True, detail=f"{log}"))
        s.checks.append(Check("  tail", ok=None, detail="\n        " + "\n        ".join(tail)))
    else:
        s.checks.append(
            Check(
                "last validate log",
                ok=None,
                detail=(
                    f"no log at {log} — run `make educator-validate` first, then rerun diagnostics"
                ),
            )
        )
    return s


def _print_section(s: Section) -> None:
    print()
    print(_C.b(f"  {s.title}"))
    print(_C.d("  " + "─" * 66))
    for c in s.checks:
        if c.ok is True:
            mark = _C.g("✓")
        elif c.ok is False:
            mark = _C.r("✗")
        else:
            mark = _C.y("⚠")
        print(f"  {mark} {c.name:<26} {c.detail}")


def main() -> int:
    quick = "--quick" in sys.argv

    print()
    print(_C.y("━" * 72))
    print(_C.b("  homework-pub-booking") + _C.d("  ·  ") + _C.b("educator diagnostics"))
    print(_C.d(f"  repo: {REPO}"))
    print(_C.d(f"  mode: {'quick (no network)' if quick else 'full (probes services)'}"))
    print(_C.y("━" * 72))

    sections = [
        section_platform(),
        section_env_vars(),
        section_python_deps(),
        section_service_auth(quick),
        section_project_state(),
        section_last_validate_log(),
    ]

    for s in sections:
        _print_section(s)

    # Summary
    all_checks = [c for s in sections for c in s.checks]
    n_fail = sum(1 for c in all_checks if c.ok is False)
    n_warn = sum(1 for c in all_checks if c.ok is None)
    n_ok = sum(1 for c in all_checks if c.ok is True)

    print()
    print(_C.y("━" * 72))
    print(f"  {n_ok} ok · {n_warn} warn/unknown · {n_fail} fail")
    if n_fail == 0:
        print(_C.g("  ✓ educator environment looks ready"))
    else:
        print(
            _C.r(f"  ✗ {n_fail} check(s) failing — fix those before running make educator-validate")
        )
    print(_C.y("━" * 72))
    print()
    print(_C.d("  Copy this whole output into the issue / chat when asking for help."))
    print()

    return 0 if n_fail == 0 else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # noqa: BLE001
        import traceback

        print(_C.r(f"✗ diagnostics itself crashed: {e}"))
        traceback.print_exc()
        sys.exit(2)
