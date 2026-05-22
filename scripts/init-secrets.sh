#!/usr/bin/env bash
# SafeClaw — generate per-install secrets in-place inside .env
#
# Walks the .env file, replaces every line whose value is exactly `__GENERATE__`
# with a fresh random value, and writes the file back atomically. Idempotent:
# already-populated secrets are preserved on re-runs.
#
# Generated values:
#   BRAIN_DB_PASSWORD,    POSTGRES_TASKS_PASSWORD,
#   TASKS_AGENT_PASSWORD, TASKS_HUMAN_PASSWORD      -> openssl rand -hex 16
#   JWT_SECRET                                       -> openssl rand -hex 32
#   TASKS_AGENT_JWT                                  -> HS256 over {"role":"tasks_agent"}
#                                                       signed with JWT_SECRET
#
# NOT generated here: SAFECLAW_BRAIN_READER_TOKEN / SAFECLAW_BRAIN_ACTOR_TOKEN
# (left as __MINTED__) — those are minted from the running safeclaw-brain by
# the onboarding provisioner, not by this script.
#
# Usage:
#   bash scripts/init-secrets.sh        # fill any remaining __GENERATE__ lines
#   bash scripts/init-secrets.sh --help # print this comment block

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
ENV_FILE="${REPO_ROOT}/.env"
TMP_FILE="${ENV_FILE}.tmp.$$"

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  sed -n '2,18p' "${BASH_SOURCE[0]}"
  exit 0
fi

# ── Sanity checks ─────────────────────────────────────────────────────────
for cmd in openssl node; do
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "ERROR: required tool '$cmd' not found in PATH." >&2
    exit 1
  fi
done

if [[ ! -f "${ENV_FILE}" ]]; then
  echo "ERROR: ${ENV_FILE} not found. Copy .env.example to .env first:" >&2
  echo "       cp .env.example .env" >&2
  exit 1
fi

trap 'rm -f "${TMP_FILE}"' EXIT

# ── Helpers ───────────────────────────────────────────────────────────────
gen_password() { openssl rand -hex 16; }
gen_jwt_secret() { openssl rand -hex 32; }

# Sign an HS256 JWT with the given secret. Uses Node + node:crypto so we don't
# need any external dependencies. Payload is the literal {"role":"tasks_agent"}
# plus an `iat` claim for auditability.
sign_tasks_agent_jwt() {
  local secret="$1"
  JWT_SECRET="${secret}" node -e '
    const crypto = require("crypto");
    const secret = process.env.JWT_SECRET;
    const b64url = (buf) =>
      Buffer.from(buf).toString("base64")
        .replace(/=/g, "").replace(/\+/g, "-").replace(/\//g, "_");
    const header  = b64url(JSON.stringify({ alg: "HS256", typ: "JWT" }));
    const payload = b64url(JSON.stringify({
      role: "tasks_agent",
      iat: Math.floor(Date.now() / 1000),
    }));
    const sig = crypto
      .createHmac("sha256", secret)
      .update(header + "." + payload)
      .digest();
    const sigB64 = b64url(sig);
    process.stdout.write(header + "." + payload + "." + sigB64);
  '
}

# ── Pass 1 — fill plain __GENERATE__ values, capture JWT_SECRET if we made it.
# (Plain space-separated lists instead of associative arrays so this script
# works on bash 3.2, which is what ships on macOS.)
REPLACED_KEYS=""
DEFERRED_JWT=0
JWT_SECRET_VALUE=""

while IFS= read -r line; do
  if [[ "$line" =~ ^([A-Z_][A-Z0-9_]*)=__GENERATE__$ ]]; then
    key="${BASH_REMATCH[1]}"
    case "$key" in
      JWT_SECRET)
        value="$(gen_jwt_secret)"
        JWT_SECRET_VALUE="$value"
        ;;
      TASKS_AGENT_JWT)
        # Defer until we know JWT_SECRET. Emit placeholder for now; pass 2
        # rewrites it.
        echo "$line"
        DEFERRED_JWT=1
        continue
        ;;
      BRAIN_DB_PASSWORD|POSTGRES_TASKS_PASSWORD|TASKS_AGENT_PASSWORD|TASKS_HUMAN_PASSWORD)
        value="$(gen_password)"
        ;;
      *)
        # Unknown __GENERATE__ key — generate a 32-byte hex token and warn.
        value="$(openssl rand -hex 32)"
        echo "WARN: ${key}=__GENERATE__ — no specific rule, used 32-byte hex." >&2
        ;;
    esac
    echo "${key}=${value}"
    REPLACED_KEYS="${REPLACED_KEYS} ${key}"
  else
    echo "$line"
  fi
done < "${ENV_FILE}" > "${TMP_FILE}"

# If we generated a fresh JWT_SECRET in pass 1, use it. Otherwise read the
# existing one out of .env so TASKS_AGENT_JWT stays valid.
if [[ -z "${JWT_SECRET_VALUE}" ]]; then
  JWT_SECRET_VALUE="$(grep -E '^JWT_SECRET=' "${TMP_FILE}" | head -1 | cut -d= -f2- || true)"
fi

# ── Pass 2 — fill TASKS_AGENT_JWT now that we know JWT_SECRET.
if [[ "${DEFERRED_JWT}" -eq 1 ]]; then
  if [[ -z "${JWT_SECRET_VALUE}" || "${JWT_SECRET_VALUE}" == "__GENERATE__" ]]; then
    echo "ERROR: cannot sign TASKS_AGENT_JWT — JWT_SECRET is empty or unset." >&2
    exit 1
  fi
  jwt="$(sign_tasks_agent_jwt "${JWT_SECRET_VALUE}")"
  TMP2="${TMP_FILE}.2"
  awk -v jwt="$jwt" '
    /^TASKS_AGENT_JWT=__GENERATE__$/ { print "TASKS_AGENT_JWT=" jwt; next }
    { print }
  ' "${TMP_FILE}" > "${TMP2}"
  mv "${TMP2}" "${TMP_FILE}"
  REPLACED_KEYS="${REPLACED_KEYS} TASKS_AGENT_JWT"
fi

# ── Atomic write back, lock down permissions.
mv "${TMP_FILE}" "${ENV_FILE}"
chmod 600 "${ENV_FILE}"
trap - EXIT

# ── Report (no values printed) ────────────────────────────────────────────
# Trim leading whitespace and compute a count.
REPLACED_KEYS="$(echo "${REPLACED_KEYS}" | sed -e 's/^ *//')"
if [[ -z "${REPLACED_KEYS}" ]]; then
  echo "init-secrets: nothing to do — no __GENERATE__ placeholders remain in .env."
else
  count="$(echo "${REPLACED_KEYS}" | wc -w | tr -d ' ')"
  echo "init-secrets: filled ${count} placeholder(s):"
  for key in ${REPLACED_KEYS}; do
    echo "  - ${key}"
  done
fi
echo "init-secrets: .env permissions are now 600."
