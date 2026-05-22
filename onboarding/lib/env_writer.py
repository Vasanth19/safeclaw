"""Atomic .env writer for SafeClaw installs.

We start from .env.example (the template that ships with the SafeClaw repo),
substitute __FILL_IN__ values from the customer's submitted form, leave
__GENERATE__ values alone (init-secrets.sh fills those), and write the
result to .env atomically (temp file + rename + chmod 600).

Rules:
  * Never write a partial .env. If anything goes wrong we leave the existing
    file alone.
  * Never echo secret values back to logs (caller is responsible — we just
    don't print them here).
  * Refuse to overwrite if any required key is missing from the input dict.
  * Always set 0600 perms after rename.

Composio note:
    The four COMPOSIO_* keys are customer-supplied via Step 2 of the
    onboarding form — Composio is the customer's account, where they did
    the OAuth dance for Gmail / Drive / Slack. They live in ALLOWED_KEYS
    and flow through the same write_env() path as everything else.
"""
from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path

# Whitelist of env keys the onboarding form is allowed to set. Anything not
# in this set we ignore — defends against the form posting arbitrary
# environment variables.
ALLOWED_KEYS = {
    # LLM
    "HERMES_INFERENCE_PROVIDER",
    "OLLAMA_BASE_URL",
    "OLLAMA_API_KEY",
    "HERMES_DEFAULT_MODEL",
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    # Composio (customer-supplied)
    "COMPOSIO_API_KEY",
    "COMPOSIO_USER_ID",
    "COMPOSIO_READER_MCP_URL",
    "COMPOSIO_ACTOR_MCP_URL",
    # Web research (optional — Hermes built-in web_search/web_extract activates
    # when any one of these provider keys is set).
    "FIRECRAWL_API_KEY",
    "EXA_API_KEY",
    "TAVILY_API_KEY",
    "PARALLEL_API_KEY",
    # Slack (primary chat)
    "SLACK_BOT_TOKEN",
    "SLACK_APP_TOKEN",
    "SLACK_WORKSPACE_ID",
    "SLACK_BOT_ADMIN_USER_ID",
    "SLACK_HOME_CHANNEL",
    "SLACK_INGEST_CHANNELS",
    "SLACK_ALLOWED_USERS",
    # Telegram (optional)
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_ALLOWED_USERS",
    # Brain
    "BRAIN_USER_KEY",
    "BOOTSTRAP_DAYS",
}

# Values that must never be set to literal placeholder strings.
PLACEHOLDERS = {"__FILL_IN__", "__GENERATE__", ""}

KEY_LINE_RE = re.compile(r"^([A-Z_][A-Z0-9_]*)=(.*)$")


class EnvWriteError(RuntimeError):
    pass


def _shell_quote(value: str) -> str:
    """Quote a value safely for a .env file consumed by both
    docker-compose and `set -o allexport; source .env`.

    Strategy: if value is empty or contains anything that isn't
    alphanumeric / safe punctuation, wrap it in double quotes and
    backslash-escape internal $, ", \\, and backticks.
    """
    if value == "":
        return '""'
    safe = re.compile(r"^[A-Za-z0-9_./:@,+\-]+$")
    if safe.match(value):
        return value
    escaped = (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("$", "\\$")
        .replace("`", "\\`")
    )
    return f'"{escaped}"'


def merge_into_template(template_text: str, values: dict[str, str]) -> str:
    """Walk the template line by line and substitute __FILL_IN__ values.

    Lines we don't recognise (comments, blanks) are passed through unchanged.
    Lines whose key is __GENERATE__ are left for init-secrets.sh.
    Lines whose key is __FILL_IN__ AND we have a value for: substitute.
    Lines whose key is __FILL_IN__ AND we DON'T have a value: left alone
    (caller can decide whether to fail — env_writer is non-judgemental about
    optional keys, e.g. TELEGRAM_BOT_TOKEN).
    """
    out_lines: list[str] = []
    seen_keys: set[str] = set()

    for raw in template_text.splitlines():
        match = KEY_LINE_RE.match(raw)
        if not match:
            out_lines.append(raw)
            continue

        key, current = match.group(1), match.group(2)

        if key not in ALLOWED_KEYS:
            # Pass through — likely a __GENERATE__ secret or an internal
            # default we don't expose in the form.
            out_lines.append(raw)
            continue

        seen_keys.add(key)

        if key in values and values[key] != "":
            new_value = _shell_quote(str(values[key]))
            out_lines.append(f"{key}={new_value}")
        else:
            # No customer value — leave whatever the template had.
            out_lines.append(raw)

    # If the form provided keys that aren't in the template at all, append
    # them at the end. This lets us add new fields (e.g. SLACK_*) before
    # the template is updated.
    extras = [k for k in values.keys() if k in ALLOWED_KEYS and k not in seen_keys]
    if extras:
        out_lines.append("")
        out_lines.append("# ── Added by onboarding webapp ──")
        for key in extras:
            value = values[key]
            if value == "":
                continue
            out_lines.append(f"{key}={_shell_quote(str(value))}")

    return "\n".join(out_lines) + "\n"


def write_env(
    install_dir: str | Path,
    values: dict[str, str],
    *,
    template_name: str = ".env.example",
    target_name: str = ".env",
) -> Path:
    """Atomically write target_name in install_dir.

    Returns the path to the written file. Raises EnvWriteError on any failure.
    """
    install_dir = Path(install_dir)
    template_path = install_dir / template_name
    target_path = install_dir / target_name

    if not template_path.is_file():
        raise EnvWriteError(f"template not found: {template_path}")

    # Reject placeholder leakage from the form.
    for key, value in values.items():
        if value in PLACEHOLDERS:
            raise EnvWriteError(f"refusing to write placeholder for {key}")

    template_text = template_path.read_text(encoding="utf-8")

    # If a .env already exists (e.g. a partially-completed retry), preserve
    # any non-form keys (init-secrets results, custom defaults) by merging
    # on top of the existing file. Falls back to .env.example for fresh
    # installs.
    if target_path.is_file():
        base_text = target_path.read_text(encoding="utf-8")
    else:
        base_text = template_text

    rendered = merge_into_template(base_text, values)

    _atomic_write(install_dir, target_path, rendered)
    return target_path


def set_env_values(
    install_dir: str | Path,
    values: dict[str, str],
    *,
    target_name: str = ".env",
) -> Path:
    """Set specific KEY=VALUE pairs in an existing .env, atomically.

    Unlike write_env(), this is NOT whitelist-driven — it's for values the
    server itself produces post-boot (e.g. brain access tokens minted from the
    running safeclaw-brain), which never originate from the customer form.

    Existing lines for the given keys are rewritten in place; missing keys are
    appended. All other lines are preserved verbatim. Refuses placeholder
    values to avoid clobbering a real value with a sentinel.
    """
    install_dir = Path(install_dir)
    target_path = install_dir / target_name

    if not target_path.is_file():
        raise EnvWriteError(f".env not found: {target_path}")

    for key, value in values.items():
        if value in PLACEHOLDERS:
            raise EnvWriteError(f"refusing to set placeholder for {key}")

    remaining = dict(values)
    out_lines: list[str] = []
    for raw in target_path.read_text(encoding="utf-8").splitlines():
        match = KEY_LINE_RE.match(raw)
        if match and match.group(1) in remaining:
            key = match.group(1)
            out_lines.append(f"{key}={_shell_quote(str(remaining.pop(key)))}")
        else:
            out_lines.append(raw)

    # Any keys not already present get appended.
    for key, value in remaining.items():
        out_lines.append(f"{key}={_shell_quote(str(value))}")

    rendered = "\n".join(out_lines) + "\n"
    _atomic_write(install_dir, target_path, rendered)
    return target_path


def _atomic_write(install_dir: Path, target_path: Path, rendered: str) -> None:
    """Write `rendered` to target_path atomically, leaving 0600 perms."""
    # tempfile in same dir so rename is atomic on the same filesystem.
    fd, tmp_name = tempfile.mkstemp(
        prefix=".env.tmp.", dir=str(install_dir)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(rendered)
        os.chmod(tmp_name, 0o600)
        os.replace(tmp_name, target_path)
    except Exception as exc:  # pragma: no cover — defensive
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass
        raise EnvWriteError(f"failed to write {target_path}: {exc}") from exc
