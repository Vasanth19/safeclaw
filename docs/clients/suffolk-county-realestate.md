# Suffolk County Real Estate — Client VPS

## Server Access

| Field | Value |
|-------|-------|
| SSH alias | `suffolk-vps` |
| Host | `76.13.188.248` |
| User | `root` |
| SSH key | `~/.ssh/id_ed25519` (after key-copy setup) |
| Credentials | MemPalace `wing_secrets/vps` |

> **Security note:** Password auth should be disabled. If `PasswordAuthentication`
> is still `yes` in `/etc/ssh/sshd_config`, switch to key-only and reload sshd.

## Project

- **Stack:** SafeClaw AI Assistant (`ai-assistant` repo, deployed as SafeClaw)
- **GitHub:** https://github.com/Vasanth19/safeclaw.git
- **Deploy path:** `/opt/safeclaw` (canonical — matches `INSTALL.md` / `CUSTOMER-ONBOARDING.md` / `HOSTINGER-DEPLOY.md`)
- **Compose project name:** `safeclaw` (hardcoded via `name:` field — directory moves preserve volume + network attachment)
- **Public ports:** Onboarding webapp on `0.0.0.0:8080` (this is a Suffolk-specific override of the default `127.0.0.1:8080` localhost-only binding — handled by direct edit of `docker-compose.yml` on the VPS, not via env var)

## First-time deploy

```bash
ssh suffolk-vps
cd /opt
git clone https://github.com/Vasanth19/safeclaw.git safeclaw
cd safeclaw
cp .env.example .env       # fill in real secrets — see CUSTOMER-ONBOARDING.md
bash scripts/init-secrets.sh
docker compose up -d
```

## Routine updates (after pushing to `main`)

The VPS is **not** a git working tree right now (deploy is rsync-based).
To update, rsync the changed files from the dev machine, then rebuild the
affected services. Two patterns:

### Pattern A — surgical rsync (preferred for small changes)

```bash
# Local: identify changed files (e.g. via `git diff --name-only HEAD~1`)
# Then rsync just those paths, preserving relative structure:
rsync -av --relative \
  <changed-file-1> \
  <changed-file-2> \
  ... \
  suffolk-vps:/opt/safeclaw/

# On VPS: rebuild only the services that changed
ssh suffolk-vps 'cd /opt/safeclaw && docker compose build <service> && \
  docker compose up -d --no-deps --force-recreate <service>'
```

**Important:** before rsyncing tracked files, verify the VPS hasn't
diverged. md5sum each target file and compare against `git show
HEAD~1:<path>` locally. If checksums match, rsync is safe; if they
differ, do a 3-way merge or surgical edit on the VPS.

### Pattern B — convert VPS to git working tree (one-time setup)

If you want `git pull`-based updates going forward:

```bash
ssh suffolk-vps
cd /opt/safeclaw
git init
git remote add origin https://github.com/Vasanth19/safeclaw.git
git fetch origin
# At this point your tracked files match the working tree exactly
# (because the rsync that put them here came from the same commit).
# Soft-reset to align HEAD with origin/main without touching files:
git reset --soft origin/main
# Then verify nothing is unexpectedly modified:
git status
```

After that, future updates: `cd /opt/safeclaw && git pull && docker compose build <svc> && docker compose up -d --no-deps <svc>`

## Critical local-only state (NEVER overwrite)

These files/directories live on the VPS and are NOT in git. They survive
`docker compose down` and any rsync that excludes them. If you do a
destructive `git reset --hard`, double-check these are untouched:

| Path | Contains |
|------|----------|
| `/opt/safeclaw/.env` | Suffolk's actual secrets (Composio API key, Postgres pw, JWTs, LLM keys) |
| `/opt/safeclaw/.env.local` | Per-install overrides |
| `/opt/safeclaw/brain/` | Suffolk's vectorized memory (~13MB grows over time) |
| `/opt/safeclaw/attachments/` | Slack/Gmail attachment staging + processed dirs |
| `/opt/safeclaw/config/drive_credentials.json` | Service account JSON (created by onboarding Step 5; mode 0600) |
| `/opt/safeclaw/config/rclone.conf/` | rclone state (this is a **directory**, not a file — different from `config/rclone.conf` in the repo template) |
| `/opt/safeclaw/.composio/` | Composio CLI scaffolding |
| Docker volume `safeclaw_obs_data` | Postgres database (vectors + observations) |

## Suffolk-specific divergence from `main`

The only persistent local edit on Suffolk's VPS:

- `docker-compose.yml` — onboarding port binding changed from
  `127.0.0.1:8080` → `0.0.0.0:8080` so the webapp is reachable from the
  internet (default install assumes a Caddy reverse proxy in front; Suffolk
  exposes 8080 directly).

When you rsync a new `docker-compose.yml`, you must preserve this edit.
Either:
1. Apply your change as a surgical `sed`/Python edit on the VPS file
   (preserves the port override automatically), OR
2. Maintain a local Suffolk-specific overlay that you apply post-rsync.

## Migration history

- **2026-05-05:** Migrated deploy path from `/root/ai-assistant` →
  `/opt/safeclaw` to match the canonical install path documented in
  `INSTALL.md` / `CUSTOMER-ONBOARDING.md`. Old path renamed to
  `/root/ai-assistant.deleteme.<stamp>` with 48-hour rollback window.
  See `/root/SAFECLAW-MIGRATION-NOTE.md` on the VPS for rollback steps.
- **2026-05-05:** Stale clone at `/opt/safeclaw` (April 28 commit, 10
  uncommitted edits, never used) renamed to
  `/opt/safeclaw.deleteme.<stamp>` before the new deploy was copied in.
  See `/root/SAFECLAW-CLEANUP-NOTE.md`.
- **2026-05-05:** `embedder` image rebuilt locally with
  `google-api-python-client` + `google-auth` for the Drive service-account
  refactor (commit `657ddb1`). Image still tagged `:1.0` — not pushed to
  registry. If the registry image is ever pulled fresh, this customization
  must be rebuilt or the registry image bumped to `:1.1` and pushed.

## Quick reference commands

```bash
# Full status
ssh suffolk-vps 'cd /opt/safeclaw && docker compose ps'

# Tail onboarding logs
ssh suffolk-vps 'cd /opt/safeclaw && docker compose logs -f onboarding'

# Bootstrap brain (after onboarding completes Step 5 + full stack is up)
ssh suffolk-vps 'cd /opt/safeclaw && bash scripts/bootstrap-brain.sh --dry-run'

# Smoke-test embedder Drive libs
ssh suffolk-vps 'cd /opt/safeclaw && docker compose exec -T embedder python -c \
  "from google.oauth2 import service_account; from googleapiclient.discovery import build; print(\"ok\")"'

# Check what's customized vs origin/main (when VPS becomes a git tree)
ssh suffolk-vps 'cd /opt/safeclaw && git status'
```

## Notes

- Onboarding UI exposed on port 8080 behind Caddy/HTTPS (or directly).
- See `DEPLOY-RUNBOOK.md` for full first-time setup guide.
- See `CUSTOMER-ONBOARDING.md` for the customer-facing setup wizard flow,
  including Step 5 (Google Drive service account JSON upload).
- Suffolk currently runs only `onboarding` + `embedder`. The remaining
  10 services in the compose file (`postgres-obs`, `postgres-tasks`,
  `postgrest`, `hermes-actor`, `hermes-reader`, `brain-api-mcp`,
  `tasks-api-mcp`, `slack-api-mcp`, `rclone-upload`, `reflector`) are
  defined but not yet started. They come up when the customer completes
  the onboarding wizard.
