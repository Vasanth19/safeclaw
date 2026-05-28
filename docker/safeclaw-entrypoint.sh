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
# When the container starts as root (default), fix volume ownership so the
# hermes user (uid 10000) can write cron/jobs.json, sessions, logs, etc.
# In rootless Podman this may silently fail — that's okay because the mapped
# host UID already owns the volume.
if [ "$(id -u)" = "0" ]; then
    chown -R hermes:hermes "${HERMES_HOME}" 2>/dev/null || \
        log "Warning: chown of ${HERMES_HOME} failed (rootless container?) — continuing anyway"
fi

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
    # Chown to hermes:hermes so upstream entrypoint (which runs as hermes
    # user after the privilege drop) can re-chmod / re-chown without
    # "Operation not permitted". Only attempt if we're root.
    if [ "$(id -u)" = "0" ]; then
        chown hermes:hermes "${TARGET_CONFIG}" 2>/dev/null || true
    fi
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

# ─── Step 5: Bootstrap data dir + launch the gateway directly ───────────────
# The upstream hermes-agent moved to an s6-overlay runtime: docker/entrypoint.sh
# is now a deprecated shim that runs the cont-init hook (stage2-hook.sh, which
# calls `s6-setuidgid` — NOT installed in this debian + gosu/tini image) and
# does NOT exec the CMD. Handing off to it crash-loops the container (exit 127).
# So we replicate the essential parts of stage2-hook.sh here (seed the data-dir
# structure + sync bundled skills, all owned by the hermes user via gosu) and
# exec the gateway directly. Works regardless of whether the upstream entrypoint
# is the pre-s6 or s6 variant. See HOOVER-DEPLOYMENT-GUIDE.md for the diagnosis.
export HERMES_HOME
HERMES_USER="hermes"
GOSU="$(command -v gosu || echo /usr/local/bin/gosu)"
HERMES_BIN="${INSTALL_DIR}/.venv/bin/hermes"
PYTHON_BIN="${INSTALL_DIR}/.venv/bin/python"
SKILLS_SYNC="${INSTALL_DIR}/tools/skills_sync.py"

if [ ! -x "${HERMES_BIN}" ]; then
    echo "safeclaw-entrypoint: hermes binary not found/executable at ${HERMES_BIN}" >&2
    exit 1
fi

if [ "$(id -u)" = "0" ] && [ -x "${GOSU}" ]; then
    # Seed the data-dir structure owned by the hermes user.
    "${GOSU}" "${HERMES_USER}" mkdir -p \
        "${HERMES_HOME}/cron"     "${HERMES_HOME}/sessions" "${HERMES_HOME}/logs" \
        "${HERMES_HOME}/hooks"    "${HERMES_HOME}/memories" "${HERMES_HOME}/skills" \
        "${HERMES_HOME}/skins"    "${HERMES_HOME}/plans"    "${HERMES_HOME}/workspace" \
        "${HERMES_HOME}/home" 2>/dev/null || true
    printf 'docker\n' | "${GOSU}" "${HERMES_USER}" tee "${HERMES_HOME}/.install_method" >/dev/null 2>&1 || true
    if [ -f "${SKILLS_SYNC}" ] && [ -x "${PYTHON_BIN}" ]; then
        "${GOSU}" "${HERMES_USER}" "${PYTHON_BIN}" "${SKILLS_SYNC}" || log "skills_sync.py failed; continuing"
    fi
    log "bootstrap complete — launching as ${HERMES_USER}: $*"
    # CMD form varies per service: reader passes hermes subcommands
    # ("gateway run …") so we prepend the hermes binary; actor passes a full
    # wrapper ("sh -c 'exec …'") or an absolute path, which we run as-is.
    case "${1:-}" in
        sh|bash|/*) exec "${GOSU}" "${HERMES_USER}" "$@" ;;
        *)          exec "${GOSU}" "${HERMES_USER}" "${HERMES_BIN}" "$@" ;;
    esac
else
    # Already non-root (rootless) — seed + launch directly without gosu.
    mkdir -p \
        "${HERMES_HOME}/cron"     "${HERMES_HOME}/sessions" "${HERMES_HOME}/logs" \
        "${HERMES_HOME}/hooks"    "${HERMES_HOME}/memories" "${HERMES_HOME}/skills" \
        "${HERMES_HOME}/skins"    "${HERMES_HOME}/plans"    "${HERMES_HOME}/workspace" \
        "${HERMES_HOME}/home" 2>/dev/null || true
    [ -f "${SKILLS_SYNC}" ] && "${PYTHON_BIN}" "${SKILLS_SYNC}" 2>/dev/null || true
    log "bootstrap complete — launching: $*"
    case "${1:-}" in
        sh|bash|/*) exec "$@" ;;
        *)          exec "${HERMES_BIN}" "$@" ;;
    esac
fi
