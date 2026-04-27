#!/usr/bin/env bash
# safeclaw-entrypoint.sh — wraps the upstream Hermes entrypoint with three fixes:
#   1. Copy operator config from /safeclaw/config-template/config.yaml into
#      /opt/data/config.yaml (writable). This fixes the bind-mount rename
#      failure ("Device or resource busy") seen when /sethome / `hermes config
#      set` tries to atomic-rename a bind-mounted file.
#   2. If TELEGRAM_HOME_CHAT_ID is set, write TELEGRAM_HOME_CHANNEL into
#      config.yaml on first boot so /sethome is not required manually.
#   3. Auto-pick the inference provider from env vars:
#        OLLAMA_API_KEY  → ollama-cloud
#        ANTHROPIC_API_KEY → anthropic
#        OPENAI_API_KEY  → openrouter (treated as openai-compatible)
#      The provider is patched into config.yaml only if the operator left
#      provider == "auto".
#
# After these steps, exec the upstream entrypoint which handles privilege
# drop + skill sync + final hermes start.

set -euo pipefail

HERMES_HOME="${HERMES_HOME:-/opt/data}"
INSTALL_DIR="/opt/hermes"
TEMPLATE_DIR="/safeclaw/config-template"
TEMPLATE_FILE="${TEMPLATE_DIR}/config.yaml"
DEFAULT_TEMPLATE="${INSTALL_DIR}/safeclaw-default-config.yaml"
TARGET_CONFIG="${HERMES_HOME}/config.yaml"
UPSTREAM_ENTRYPOINT="${INSTALL_DIR}/docker/entrypoint.sh"

log() {
    printf '[safeclaw-entrypoint] %s\n' "$*"
}

# ─── Step 1: Ensure HERMES_HOME exists and is writable ──────────────────────
mkdir -p "${HERMES_HOME}"

# ─── Step 2: Seed config.yaml from template ─────────────────────────────────
# Resolve which template to use:
#   Operator-mounted /safeclaw/config-template/config.yaml takes precedence.
#   Otherwise fall back to the image-baked default.
SOURCE_TEMPLATE=""
if [ -f "${TEMPLATE_FILE}" ]; then
    SOURCE_TEMPLATE="${TEMPLATE_FILE}"
    log "operator config template detected at ${TEMPLATE_FILE}"
elif [ -f "${DEFAULT_TEMPLATE}" ]; then
    SOURCE_TEMPLATE="${DEFAULT_TEMPLATE}"
    log "no operator template; using baked default ${DEFAULT_TEMPLATE}"
fi

if [ -n "${SOURCE_TEMPLATE}" ]; then
    # COPY (not bind-mount) into /opt/data. This is the key fix for the
    # /sethome rename failure: atomic_yaml_write does temp-file + os.replace,
    # which fails on a bind-mounted regular file. A plain copy into the named
    # volume avoids the bind entirely.
    if [ -f "${TARGET_CONFIG}" ]; then
        # If the target is already a regular file in the volume AND it's
        # byte-identical to the template, leave it alone (preserves runtime
        # writes like /sethome from previous boots).
        if cmp -s "${SOURCE_TEMPLATE}" "${TARGET_CONFIG}"; then
            log "config.yaml already in sync with template — leaving as-is"
        else
            log "refreshing config.yaml from ${SOURCE_TEMPLATE}"
            # Write atomically: temp file in the same dir, then rename.
            tmp="${TARGET_CONFIG}.tmp.$$"
            cp "${SOURCE_TEMPLATE}" "${tmp}"
            mv "${tmp}" "${TARGET_CONFIG}"
        fi
    else
        log "writing initial config.yaml from ${SOURCE_TEMPLATE}"
        tmp="${TARGET_CONFIG}.tmp.$$"
        cp "${SOURCE_TEMPLATE}" "${tmp}"
        mv "${tmp}" "${TARGET_CONFIG}"
    fi
    chmod 640 "${TARGET_CONFIG}" || true
else
    log "WARNING: no config template found — Hermes upstream will seed defaults"
fi

# ─── Step 3: Inject TELEGRAM_HOME_CHAT_ID if provided ───────────────────────
# Hermes' /sethome stores the home chat under the env_key
# "<PLATFORM>_HOME_CHANNEL" inside config.yaml as a top-level key.
# We replicate that on first boot if the operator set TELEGRAM_HOME_CHAT_ID.
if [ -n "${TELEGRAM_HOME_CHAT_ID:-}" ] && [ -f "${TARGET_CONFIG}" ]; then
    log "injecting TELEGRAM_HOME_CHANNEL=${TELEGRAM_HOME_CHAT_ID} into ${TARGET_CONFIG}"
    python3 - "$TARGET_CONFIG" "$TELEGRAM_HOME_CHAT_ID" <<'PYEOF'
import os
import sys
import tempfile

target = sys.argv[1]
chat_id = sys.argv[2]

try:
    import yaml
except ImportError:
    # PyYAML may not be importable from the system python3; the upstream
    # entrypoint runs hermes from its own venv where yaml is guaranteed.
    # Fall back to naive line-based patch which still works for top-level
    # scalar keys.
    yaml = None

# Try to coerce to int (Hermes stores Telegram chat IDs as ints).
try:
    chat_value = int(chat_id)
except ValueError:
    chat_value = chat_id

if yaml is not None:
    with open(target, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    if not isinstance(cfg, dict):
        sys.stderr.write("safeclaw: config.yaml is not a mapping; skipping inject\n")
        sys.exit(0)
    existing = cfg.get("TELEGRAM_HOME_CHANNEL")
    if existing == chat_value:
        sys.exit(0)
    cfg["TELEGRAM_HOME_CHANNEL"] = chat_value
    fd, tmp = tempfile.mkstemp(prefix=".config_", suffix=".yaml", dir=os.path.dirname(target))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            yaml.safe_dump(cfg, out, sort_keys=False)
        os.replace(tmp, target)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    sys.exit(0)

# yaml unavailable — naive append (still safe because it's a top-level key).
with open(target, "r", encoding="utf-8") as f:
    body = f.read()
needle = "TELEGRAM_HOME_CHANNEL:"
lines = []
patched = False
for line in body.splitlines():
    if line.startswith(needle):
        lines.append(f"TELEGRAM_HOME_CHANNEL: {chat_value}")
        patched = True
    else:
        lines.append(line)
if not patched:
    lines.append(f"TELEGRAM_HOME_CHANNEL: {chat_value}")
with open(target, "w", encoding="utf-8") as f:
    f.write("\n".join(lines) + "\n")
PYEOF

    # Also export for in-process consumers (gateway run.py reads os.environ).
    export TELEGRAM_HOME_CHANNEL="${TELEGRAM_HOME_CHAT_ID}"
fi

# ─── Step 4: Auto-pick inference provider from env vars ─────────────────────
# Only patches if model.provider is currently "auto" (or unset). Operator
# overrides in the mounted template always win.
if [ -f "${TARGET_CONFIG}" ]; then
    PICKED_PROVIDER=""
    PICKED_KEY_NAME=""
    if [ -n "${OLLAMA_API_KEY:-}" ]; then
        PICKED_PROVIDER="ollama-cloud"
        PICKED_KEY_NAME="OLLAMA_API_KEY"
    elif [ -n "${ANTHROPIC_API_KEY:-}" ]; then
        PICKED_PROVIDER="anthropic"
        PICKED_KEY_NAME="ANTHROPIC_API_KEY"
    elif [ -n "${OPENAI_API_KEY:-}" ]; then
        PICKED_PROVIDER="openrouter"
        PICKED_KEY_NAME="OPENAI_API_KEY"
    fi

    if [ -n "${PICKED_PROVIDER}" ]; then
        log "detected ${PICKED_KEY_NAME} — provider preference: ${PICKED_PROVIDER}"
        python3 - "$TARGET_CONFIG" "$PICKED_PROVIDER" <<'PYEOF'
import os
import sys
import tempfile

target = sys.argv[1]
picked = sys.argv[2]

try:
    import yaml
except ImportError:
    sys.exit(0)

with open(target, "r", encoding="utf-8") as f:
    cfg = yaml.safe_load(f) or {}
if not isinstance(cfg, dict):
    sys.exit(0)

model_block = cfg.get("model")
if not isinstance(model_block, dict):
    sys.exit(0)

current = model_block.get("provider", "auto")
if current not in ("auto", None, ""):
    # Operator pinned a specific provider — respect it.
    sys.exit(0)

model_block["provider"] = picked
cfg["model"] = model_block

fd, tmp = tempfile.mkstemp(prefix=".config_", suffix=".yaml", dir=os.path.dirname(target))
try:
    with os.fdopen(fd, "w", encoding="utf-8") as out:
        yaml.safe_dump(cfg, out, sort_keys=False)
    os.replace(tmp, target)
except Exception:
    try:
        os.unlink(tmp)
    except OSError:
        pass
    raise
PYEOF
    fi
fi

# ─── Step 5: Hand off to the upstream entrypoint ────────────────────────────
if [ ! -x "${UPSTREAM_ENTRYPOINT}" ]; then
    echo "safeclaw-entrypoint: missing upstream entrypoint at ${UPSTREAM_ENTRYPOINT}" >&2
    exit 1
fi

log "handing off to upstream entrypoint: ${UPSTREAM_ENTRYPOINT} $*"
exec "${UPSTREAM_ENTRYPOINT}" "$@"
