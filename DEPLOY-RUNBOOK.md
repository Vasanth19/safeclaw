# SafeClaw Deploy Runbook

Step-by-step operator guide for installing, configuring, and maintaining the SafeClaw stack.

---

## 1. System Requirements

| Requirement | Minimum | Notes |
|-------------|---------|-------|
| OS | macOS 14+ or Ubuntu 22.04+ | macOS: egress iptables rules are best-effort. Full enforcement requires Linux. |
| OrbStack | 1.0+ | macOS only. Linux: Docker Engine 24+ is sufficient. OrbStack's Linux VM allows iptables egress rules on macOS — a key advantage over Docker Desktop. |
| `docker compose` | v2 (plugin) | Verify: `docker compose version`. Must show v2.x, not v1.x `docker-compose`. |
| RAM (free) | 4 GB | Hermes agents are memory-intensive with large context windows. |
| Disk | 20 GB | For Postgres data, Drive mirror, and Docker image cache. |
| CPU | 4 cores | Hermes inference is CPU-bound if not using a remote LLM endpoint. |

---

## 2. First-Time Setup

### Clone the repository

```bash
git clone <repo-url> safeclaw
cd safeclaw/ai-assistant
```

### Copy and fill the environment file

```bash
cp .env.example .env
```

Open `.env` and fill in every value. The table below describes each variable.

### Environment Variables

| Variable | Required | How to Generate / Where to Find |
|----------|----------|--------------------------------|
| `BRAIN_DB_USER` | Yes | Any string. Default: `safeclaw_brain`. Postgres user for the GBrain backend (`postgres-brain`). |
| `BRAIN_DB_PASSWORD` | Yes | `openssl rand -base64 24` — auto-set by `scripts/init-secrets.sh` |
| `BRAIN_DB_NAME` | Yes | Any string. Default: `safeclaw_brain` |
| `BRAIN_USER_KEY` | Yes | Single-user installs use `primary`. |
| `GBRAIN_VERSION` | Yes | GBrain image/build pin (e.g. `0.37.11.0`). Bump to upgrade the brain — see §11. |
| `SAFECLAW_BRAIN_HTTP_URL` | Yes | Internal HTTP endpoint of the brain. Default: `http://safeclaw-brain:3131`. Agents hit `${SAFECLAW_BRAIN_HTTP_URL}/mcp`. |
| `SAFECLAW_BRAIN_READER_TOKEN` | Yes | `__MINTED__` until you run `docker compose exec safeclaw-brain gbrain auth create reader` post-boot; paste the printed `gbrain_<hex>`. |
| `SAFECLAW_BRAIN_ACTOR_TOKEN` | Yes | `__MINTED__` until you run `docker compose exec safeclaw-brain gbrain auth create actor` post-boot; paste the printed `gbrain_<hex>`. |
| `POSTGRES_TASKS_USER` | Yes | Any string. Default: `tasks_super` |
| `POSTGRES_TASKS_PASSWORD` | Yes | `openssl rand -base64 24` |
| `POSTGRES_TASKS_DB` | Yes | Any string. Default: `safeclaw_tasks` |
| `TASKS_AGENT_PASSWORD` | Yes | `openssl rand -base64 24` — for the DB user created by 002_task_schema.sql |
| `TASKS_HUMAN_PASSWORD` | Yes | `openssl rand -hex 16` — auto-set by `scripts/init-secrets.sh` |
| `JWT_SECRET` | Yes | `openssl rand -hex 32` — auto-set by `scripts/init-secrets.sh` |
| `TASKS_AGENT_JWT` | Yes | Auto-signed by `scripts/init-secrets.sh` (HS256, payload `{"role":"tasks_agent"}`) |
| `COMPOSIO_API_KEY` | Yes | Composio dashboard → project API key (`ak_...`) |
| `COMPOSIO_USER_ID` | Yes | Composio dashboard → connection actor (`pg-test-...` or your real user_id) |
| `COMPOSIO_READER_MCP_URL` | Yes | Composio dashboard → Reader MCP server URL (read-only toolkit allowlist) |
| `COMPOSIO_ACTOR_MCP_URL` | Yes | Composio dashboard → Actor MCP server URL (draft/send toolkit allowlist) |
| `TELEGRAM_BOT_TOKEN` | Yes (v1) | `@BotFather` on Telegram → create bot → copy token |
| `TELEGRAM_ALLOWED_USERS` | Yes (v1) | Comma-separated numeric Telegram user IDs (`@userinfobot`) |
| `HERMES_INFERENCE_PROVIDER` | Yes | e.g. `ollama-cloud` |
| `OLLAMA_BASE_URL` | Yes | e.g. `http://host.docker.internal:11434/v1` |
| `OLLAMA_API_KEY` | Yes | `ollama-local` for the local daemon (cloud auth via `~/.ollama/id_ed25519`) |
| `HERMES_DEFAULT_MODEL` | Yes | e.g. `glm-5.1:cloud` |
| `ACTOR_ENABLED` | Yes | Default: `true` (v1 ships actor-on). |
| `AUTO_SEND_ENABLED` | Yes | Default: `false`. Set `true` only after Phase 4 sign-off. |

### Generating TASKS_AGENT_JWT

The JWT must be signed with `JWT_SECRET` and include `{"role": "tasks_agent"}` in the payload.

```bash
# Quick generation using Node.js (no expiry — rotate periodically):
node -e "
  const crypto = require('crypto');
  const secret = process.env.JWT_SECRET;
  const header = Buffer.from(JSON.stringify({alg:'HS256',typ:'JWT'})).toString('base64url');
  const payload = Buffer.from(JSON.stringify({role:'tasks_agent',iat:Math.floor(Date.now()/1000)})).toString('base64url');
  const sig = crypto.createHmac('sha256',secret).update(header+'.'+payload).digest('base64url');
  console.log(header+'.'+payload+'.'+sig);
"
```

Paste the output as `TASKS_AGENT_JWT` in `.env`.

---

## 3. Starting the Stack

Before the first `up`, pull the local embedding model on the host running the
Ollama daemon (the brain embeds locally via Ollama — no API key, no egress):

```bash
ollama pull nomic-embed-text
```

```bash
docker compose up -d
```

Check service status:
```bash
docker compose ps
```

Wait for all services to be `healthy` (`postgres-brain`, `postgres-tasks`,
`postgrest`, `safeclaw-brain`) or `running` (hermes-reader, hermes-actor,
rclone-sync). Allow up to 60 seconds for Postgres initialization on the first
`up`. On first boot, `safeclaw-brain` runs `gbrain init` +
`gbrain apply-migrations --yes` before its `/health` check goes green.

After the brain is healthy, mint the two agent bearer tokens and load them:

```bash
docker compose exec safeclaw-brain gbrain auth create reader   # → SAFECLAW_BRAIN_READER_TOKEN
docker compose exec safeclaw-brain gbrain auth create actor    # → SAFECLAW_BRAIN_ACTOR_TOKEN
# paste both gbrain_<hex> values into .env, then:
docker compose up -d hermes-reader hermes-actor
```

Run foundation verification:
```bash
bash scripts/verify-stack.sh --phase 0
```

---

## 4. OAuth Setup

OAuth + per-toolkit MCP is delegated to **Composio** (off-box). SafeClaw never
holds a refresh token on disk.

1. Sign in at https://app.composio.dev.
2. Connect the Gmail / Drive / Slack / etc. accounts the assistant should
   reach. Each connection is bound to your `COMPOSIO_USER_ID`.
3. Create **two MCP servers** for this install:
   - **Reader** — read-only toolkit allowlist (e.g. `GMAIL_FETCH_EMAILS`,
     `GMAIL_LIST_THREADS`). No draft / send / delete actions.
   - **Actor** — draft / send / move toolkit allowlist (e.g.
     `GMAIL_CREATE_DRAFT`, `GMAIL_SEND_EMAIL`, `TELEGRAM_SEND_MESSAGE`,
     `GOOGLEDRIVE_MOVE_FILE`). No raw inbox reads.
4. Copy the two MCP URLs and your project API key into `.env` as
   `COMPOSIO_READER_MCP_URL`, `COMPOSIO_ACTOR_MCP_URL`, and
   `COMPOSIO_API_KEY`.

The toolkit allowlist on each MCP server is the load-bearing trust boundary —
see ARCHITECTURE.md §5 for why.

### Suggested connection ID conventions (single-user install)

| Connection ID | Toolkit | Where it appears |
|---------------|---------|------------------|
| `primary-inbox` | Gmail | Reader + Actor |
| `secondary-inbox` | Gmail (optional) | Reader + Actor |
| `tertiary-inbox` | Gmail (optional) | Reader + Actor |
| `primary-drive` | Google Drive | Actor |
| `your-workspace` | Slack (v2 only) | Actor |

---

## 5. Database Initialization

**Brain DB:** no manual step. GBrain owns its own schema — the `safeclaw-brain`
entrypoint runs `gbrain init` (first boot) + `gbrain apply-migrations --yes`
(every boot, idempotent) against `postgres-brain` automatically. SafeClaw ships
no brain DDL.

**Task DB:** run the task migration after OAuth setup (or anytime after Postgres
is healthy):

```bash
# Task DB
docker compose exec postgres-tasks psql \
  -U "$POSTGRES_TASKS_USER" \
  -d "$POSTGRES_TASKS_DB" \
  -f /migrations/002_task_schema.sql
```

Verify tables were created:
```bash
# Brain (GBrain-managed) — page count + health
docker compose exec safeclaw-brain gbrain stats

docker compose exec postgres-tasks psql -U "$POSTGRES_TASKS_USER" -d "$POSTGRES_TASKS_DB" \
  -c "\dt"
```

---

## 6. Hermes Configuration

Config files are mounted read-only into each container:
- `./config/reader-hermes.yaml` → `/config/hermes.yaml` in `hermes-reader`
- `./config/actor-hermes.yaml` → `/config/hermes.yaml` in `hermes-actor`

To reload configuration without rebuilding:
```bash
docker compose restart hermes-reader
docker compose restart hermes-actor
```

To edit and reload the system prompt or tool allowlist:
1. Edit the relevant YAML file locally
2. Restart the container:
   ```bash
   docker compose restart hermes-reader  # or hermes-actor
   ```
3. Check logs to confirm the new config was loaded:
   ```bash
   docker compose logs --tail=20 hermes-reader
   ```

---

## 7. Monitoring

### Live log streaming

```bash
# Reader agent (primary monitoring target)
docker compose logs -f hermes-reader

# Actor agent
docker compose logs -f hermes-actor

# All services
docker compose logs -f
```

### Inspecting the brain (GBrain)

The brain has no host port and no raw SQL surface — use the `gbrain` CLI inside
the `safeclaw-brain` container. (Avoid querying `postgres-brain` directly; the
schema is GBrain-owned and may change between `GBRAIN_VERSION` bumps.)

```bash
# Brain health + page/stat summary
docker compose exec safeclaw-brain gbrain doctor
docker compose exec safeclaw-brain gbrain stats

# Recent pages (observations, People, Companies, style samples)
docker compose exec safeclaw-brain gbrain list_pages

# Read the Soul page the agent reads
docker compose exec safeclaw-brain gbrain get_page identity/soul

# Hybrid query the brain
docker compose exec safeclaw-brain gbrain query "recent emails from Alice"
```

### Querying the task DB

```bash
# Review queue (pending approvals)
docker compose exec postgres-tasks psql \
  -U "$POSTGRES_TASKS_USER" -d "$POSTGRES_TASKS_DB" \
  -c "SELECT action_type, proposed_at, approved_at, rejected_at FROM review_queue ORDER BY proposed_at DESC LIMIT 10;"
```

---

## 8. Stopping and Updating

### Graceful shutdown

```bash
# Stop all containers, preserve volumes:
docker compose down

# Stop and remove volumes (DATA LOSS — only for clean reinstall):
docker compose down -v
```

### Updating the Hermes version

1. Edit `docker-compose.yml` — update the image tag for `hermes-reader` and `hermes-actor`
2. Pull the new image:
   ```bash
   docker compose pull hermes-reader hermes-actor
   ```
3. Restart with the new image:
   ```bash
   docker compose up -d hermes-reader hermes-actor
   ```
4. Watch logs for any config format changes:
   ```bash
   docker compose logs -f hermes-reader
   ```

### Monthly maintenance

```bash
# Update all images
docker compose pull

# Restart with new images
docker compose up -d

# Run OSV scan on MCP tools
cd mcp-tools/tasks-api && npm audit

# Rotate TASKS_AGENT_JWT (generate new one, update .env, restart actor)
```

---

## 9. Egress Rules (Linux Production Only)

On a Linux host, apply iptables rules to enforce the domain-level egress allowlist.
This prevents hermes-reader from making HTTP calls to arbitrary external hosts even if
the system prompt is bypassed by a prompt injection attack.

```bash
#!/usr/bin/env bash
# Run as root after docker compose up

NETWORK=$(docker network inspect safeclaw_safeclaw_net --format '{{range .IPAM.Config}}{{.Subnet}}{{end}}')

# Allow DNS (required for domain resolution)
iptables -I FORWARD -s "$NETWORK" -p udp --dport 53 -j ACCEPT
iptables -I FORWARD -s "$NETWORK" -p tcp --dport 53 -j ACCEPT

# Allow *.googleapis.com (74.125.0.0/16, 142.250.0.0/15, 172.217.0.0/16)
for subnet in 74.125.0.0/16 142.250.0.0/15 172.217.0.0/16; do
  iptables -I FORWARD -s "$NETWORK" -d "$subnet" -j ACCEPT
done

# Allow *.slack.com (52.0.0.0/8 is a broad range — Slack uses AWS; consult Slack IP list)
iptables -I FORWARD -s "$NETWORK" -d 52.1.0.0/24 -j ACCEPT   # Example — update with real range

# Allow internal Docker network traffic
iptables -I FORWARD -s "$NETWORK" -d "$NETWORK" -j ACCEPT

# Drop all other forwarded traffic from safeclaw_net
iptables -A FORWARD -s "$NETWORK" -j DROP

echo "Egress rules applied for subnet: $NETWORK"
```

Note: IP ranges for googleapis.com and slack.com change over time. For production, use
a DNS-based allowlist (e.g., `squid` proxy with domain allowlist) rather than raw IP
ranges. The iptables approach above is a defense-in-depth layer, not a sole control.

---

## 10. Troubleshooting

| Symptom | Likely Cause | Fix |
|---------|-------------|-----|
| Composio MCP returns "auth required" or "invalid connection" | OAuth refresh token has been revoked or expired | Re-authorize the connection in the Composio dashboard: Connections → select connection → Re-authenticate |
| hermes-reader logs "watch expired" for Gmail Pub/Sub | Gmail watch() expires after 7 days | Trigger the `gmail_rearm` schedule manually: `docker compose exec hermes-actor hermes-agent trigger gmail_rearm` |
| PostgREST returns 403 on all requests | JWT secret mismatch between `.env` and PostgREST config | Verify `JWT_SECRET` in `.env` matches the value PostgREST was started with. Restart postgrest after any change. |
| hermes-actor tool call returns "Tool not available: gmail_send" | Actor is correctly refusing a send operation | Expected behavior. If this appears outside of a send attempt, check for prompt injection in the observation being processed. |
| Observation rows not appearing after email arrives | Gmail Pub/Sub subscription has expired, or hermes-reader is down | (1) Check `docker compose ps` for hermes-reader status. (2) Verify Pub/Sub subscription is active in Google Cloud Console. (3) Trigger `gmail_rearm`. |
| Drive mirror is empty | rclone-sync is failing or `RCLONE_DRIVE_FOLDER_ID` is wrong | Check logs: `docker compose logs rclone-sync`. Verify the folder ID in `.env` by opening the Drive folder and copying the ID from the URL. |
| hermes-actor exits with "ACTOR_ENABLED=false" | Expected Phase 1 behavior | Set `ACTOR_ENABLED=true` in `.env` and run `docker compose up -d hermes-actor` to start Phase 2. |
| PostgREST returns 401 for agent requests | `TASKS_AGENT_JWT` is malformed or signed with wrong secret | Re-generate the JWT (see §Generating TASKS_AGENT_JWT) and update `.env`. Restart hermes-actor. |
| No morning briefing card in Slack | `SLACK_REVIEW_CHANNEL_ID` wrong, or bot not invited to channel | Verify channel ID in `.env`. Confirm @SafeClaw is a member of #safeclaw-review. |
