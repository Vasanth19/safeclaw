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
| `POSTGRES_OBS_USER` | Yes | Any string. Default: `obs_user` |
| `POSTGRES_OBS_PASSWORD` | Yes | `openssl rand -base64 24` |
| `POSTGRES_OBS_DB` | Yes | Any string. Default: `safeclaw_obs` |
| `POSTGRES_TASKS_USER` | Yes | Any string. Default: `tasks_super` |
| `POSTGRES_TASKS_PASSWORD` | Yes | `openssl rand -base64 24` |
| `POSTGRES_TASKS_DB` | Yes | Any string. Default: `safeclaw_tasks` |
| `TASKS_AGENT_PASSWORD` | Yes | `openssl rand -base64 24` — for the DB user created by 002_task_schema.sql |
| `TASKS_HUMAN_PASSWORD` | Yes | `openssl rand -base64 24` — for the human DB user |
| `NANGO_ENCRYPTION_KEY` | Yes | `openssl rand -hex 32` — must be exactly 32 bytes hex |
| `NANGO_SECRET_KEY` | Yes | Set any string now; update after first Nango login |
| `JWT_SECRET` | Yes | `openssl rand -hex 32` — used to sign/verify PostgREST JWTs |
| `TASKS_AGENT_JWT` | Yes | Sign a JWT: see §Generating TASKS_AGENT_JWT below |
| `GOOGLE_CLIENT_ID` | Yes | Google Cloud Console → APIs & Services → Credentials → OAuth 2.0 Client |
| `GOOGLE_CLIENT_SECRET` | Yes | Same as above |
| `RCLONE_DRIVE_FOLDER_ID` | Yes | Google Drive folder URL → extract the long ID after `/folders/` |
| `SLACK_BOT_TOKEN` | Phase 2 | Slack App Dashboard → OAuth & Permissions → Bot User OAuth Token (xoxb-...) |
| `SLACK_APP_TOKEN` | Phase 2 | Slack App Dashboard → Basic Information → App-Level Tokens (xapp-...) |
| `SLACK_REVIEW_CHANNEL_ID` | Phase 2 | Slack channel URL or right-click → Copy Link → extract C... ID |
| `HERMES_LLM_API_KEY` | Yes | Your LLM provider API key (OpenAI or compatible) |
| `HERMES_LLM_BASE_URL` | Yes | e.g. `https://api.openai.com/v1` |
| `HERMES_MODEL` | Yes | e.g. `NousResearch/Hermes-3-Llama-3.1-8B` |
| `ACTOR_ENABLED` | Yes | Default: `false`. Set `true` in Phase 2. |
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

```bash
docker compose up -d
```

Check service status:
```bash
docker compose ps
```

Wait for all services to be `healthy` (Postgres, PostgREST, Nango) or `running`
(hermes-reader, rclone-sync). Allow up to 60 seconds for Postgres initialization.

Run foundation verification:
```bash
bash scripts/verify-stack.sh --phase 0
```

---

## 4. OAuth Setup

After the stack is healthy, authorize all OAuth connections through Nango.

```bash
bash scripts/setup-oauth.sh
```

The script walks through each integration step-by-step. You will need:
- Google Cloud OAuth credentials (Client ID + Secret) already in `.env`
- Access to all three Jake McKinney Gmail accounts
- Slack workspace admin access

**Nango dashboard:** http://localhost:3003

### OAuth integration summary

| Integration ID | Provider | Scopes | Used by |
|---------------|----------|--------|---------|
| `gmail-readonly` | Google | `gmail.readonly`, `gmail.labels` | hermes-reader |
| `gmail-draft` | Google | `gmail.compose` | hermes-actor |
| `google-drive-file` | Google | `drive.file` | hermes-actor |
| `slack-bot` | Slack | `channels:read`, `channels:history`, `chat:write`, `chat:write.public` | both |

---

## 5. Database Initialization

Run migrations after OAuth setup (or anytime after Postgres is healthy):

```bash
# Observation DB
docker compose exec postgres-obs psql \
  -U "$POSTGRES_OBS_USER" \
  -d "$POSTGRES_OBS_DB" \
  -f /migrations/001_obs_schema.sql

# Task DB
docker compose exec postgres-tasks psql \
  -U "$POSTGRES_TASKS_USER" \
  -d "$POSTGRES_TASKS_DB" \
  -f /migrations/002_task_schema.sql
```

Verify tables were created:
```bash
docker compose exec postgres-obs psql -U "$POSTGRES_OBS_USER" -d "$POSTGRES_OBS_DB" \
  -c "\dt"

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

### Querying the observation DB

```bash
# Most recent observations
docker compose exec postgres-obs psql \
  -U "$POSTGRES_OBS_USER" -d "$POSTGRES_OBS_DB" \
  -c "SELECT inbox, subject, is_critical, processed_at FROM observations ORDER BY processed_at DESC LIMIT 20;"

# Critical alerts awaiting acknowledgment
docker compose exec postgres-obs psql \
  -U "$POSTGRES_OBS_USER" -d "$POSTGRES_OBS_DB" \
  -c "SELECT * FROM critical_alerts WHERE acknowledged_at IS NULL ORDER BY alerted_at DESC;"

# Review queue (pending approvals)
docker compose exec postgres-obs psql \
  -U "$POSTGRES_OBS_USER" -d "$POSTGRES_OBS_DB" \
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
| Nango shows "Token expired" for a Gmail connection | OAuth refresh token has been revoked or expired | Re-authorize the connection in Nango dashboard: Connections → select connection → Re-authorize |
| hermes-reader logs "watch expired" for Gmail Pub/Sub | Gmail watch() expires after 7 days | Trigger the `gmail_rearm` schedule manually: `docker compose exec hermes-actor hermes-agent trigger gmail_rearm` |
| PostgREST returns 403 on all requests | JWT secret mismatch between `.env` and PostgREST config | Verify `JWT_SECRET` in `.env` matches the value PostgREST was started with. Restart postgrest after any change. |
| hermes-actor tool call returns "Tool not available: gmail_send" | Actor is correctly refusing a send operation | Expected behavior. If this appears outside of a send attempt, check for prompt injection in the observation being processed. |
| Observation rows not appearing after email arrives | Gmail Pub/Sub subscription has expired, or hermes-reader is down | (1) Check `docker compose ps` for hermes-reader status. (2) Verify Pub/Sub subscription is active in Google Cloud Console. (3) Trigger `gmail_rearm`. |
| Drive mirror is empty | rclone-sync is failing or `RCLONE_DRIVE_FOLDER_ID` is wrong | Check logs: `docker compose logs rclone-sync`. Verify the folder ID in `.env` by opening the Drive folder and copying the ID from the URL. |
| hermes-actor exits with "ACTOR_ENABLED=false" | Expected Phase 1 behavior | Set `ACTOR_ENABLED=true` in `.env` and run `docker compose up -d hermes-actor` to start Phase 2. |
| PostgREST returns 401 for agent requests | `TASKS_AGENT_JWT` is malformed or signed with wrong secret | Re-generate the JWT (see §Generating TASKS_AGENT_JWT) and update `.env`. Restart hermes-actor. |
| No morning briefing card in Slack | `SLACK_REVIEW_CHANNEL_ID` wrong, or bot not invited to channel | Verify channel ID in `.env`. Confirm @SafeClaw is a member of #safeclaw-review. |
