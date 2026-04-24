"""Regenerate .env.example from an embedded fallback.

Run via `make env-bootstrap` when the shipped `.env.example` is missing
from your checkout (usually because your tar extract dropped dotfiles).

The bundled content is kept intentionally minimal. The full version in
the repo has more comments and docs pointers; this script's job is to
unblock `make setup` and get you to `make verify`. Once you're up and
running, `git checkout .env.example` from the public repo will restore
the full-comment version.
"""

from __future__ import annotations

from pathlib import Path

FALLBACK_ENV_EXAMPLE = """\
# =====================================================================
# homework-pub-booking — minimal .env.example (bootstrap fallback)
# =====================================================================
# This is the RECOVERY version of .env.example — it's shorter than the
# one shipped in the repo because it's embedded in a Python script.
# After `make setup` works, you can fetch the full version with:
#     curl -O https://raw.githubusercontent.com/sovereignagents/\\
#            homework-pub-booking/main/.env.example
# or just `git checkout .env.example` if this is a git clone.

# --- REQUIRED ---------------------------------------------------------
# Your Nebius API key. Get one at https://tokenfactory.nebius.com
# See docs/nebius-signup.md for the 2-minute walkthrough.
NEBIUS_KEY=

# --- Sovereign-agent model selection ---------------------------------
# Grader runs against these defaults. Override only if you know why.
SOVEREIGN_AGENT_LLM_BASE_URL=https://api.tokenfactory.nebius.com/v1/
SOVEREIGN_AGENT_LLM_API_KEY_ENV=NEBIUS_KEY
SOVEREIGN_AGENT_LLM_PLANNER_MODEL=Qwen/Qwen3-Next-80B-A3B-Thinking
SOVEREIGN_AGENT_LLM_EXECUTOR_MODEL=Qwen/Qwen3-32B
SOVEREIGN_AGENT_LLM_MEMORY_MODEL=meta-llama/Llama-3.3-70B-Instruct

# --- OPTIONAL: Ex6 Rasa integration -----------------------------------
# Rasa Pro developer-edition JWT license. Required when running the
# real Rasa container (Ex6 solution). Without it, the stdlib mock
# server is used (enough to pass HTTP-contract tests).
# Sign up at https://rasa.com/rasa-pro-developer-edition/
RASA_PRO_LICENSE=

# --- OPTIONAL: Ex8 voice pipeline -------------------------------------
# Only needed if you run `make ex8-voice`. Text mode needs neither.
SPEECHMATICS_KEY=
# Rime.ai TTS — uses the Arcana model for voice output.
RIME_API_KEY=
"""


def main() -> None:
    target = Path(".env.example")
    if target.exists():
        print(f"✗ {target} already exists — refusing to overwrite.")
        print("  Delete it first if you really want to regenerate from the fallback:")
        print("    rm .env.example && make env-bootstrap")
        raise SystemExit(1)
    target.write_text(FALLBACK_ENV_EXAMPLE, encoding="utf-8")
    print(f"✓ Wrote {target} ({target.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
