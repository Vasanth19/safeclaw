# SafeClaw → Suffolk VPS Deployment Plan

**Target:** `ssh suffolk-vps` (IP `187.77.30.131`, hostname `srv1687869`, public name `srv1687869.hstgr.cloud`)
**Status of this doc:** assessment + install plan. NOTHING has been changed on the VPS — every command below is to be run by the operator with the explicit go-aheads flagged.
**Central problem solved here:** the stock `provision-vps.sh` installs **Caddy bound to 80/443**, which would collide head-on with the live Brookhaven nginx. This plan REPLACES the Caddy step with an nginx subdomain server block that coexists with Brookhaven.

---

## 0. Read-only assessment results (gathered live, no changes made)

| Check | Finding | Verdict |
|---|---|---|
| OS / kernel | Ubuntu, kernel `6.8.0-111-generic`, x86_64 | OK |
| Docker | `29.5.1` (Engine + client), Community | OK — install step can be skipped |
| Docker Compose | `v5.1.3` plugin | OK |
| CPU | 2 vCPU | Adequate (tight — see notes) |
| RAM | 7.8 GiB total, **6.7 GiB available**, 1.1 GiB used, **0 B swap** | Adequate; no swap is a risk under load |
| Disk `/` | 96 G total, **92 G free** (5% used) | Ample |
| Ports 80 / 443 | `nginx` (pids 12597/17472/17473) on `0.0.0.0:80` and `0.0.0.0:443` | **OWNED by Brookhaven nginx — DO NOT bind Caddy here** |
| Port 8001 | `uvicorn` on `127.0.0.1:8001` (Brookhaven API) | Reserved — leave alone |
| Port 5432 | host `postgres` on `127.0.0.1:5432` (Brookhaven Postgres 16) | Reserved — SafeClaw's Postgres are containerized, no host port, NO conflict |
| Port 8080 | free | SafeClaw onboarding will bind `127.0.0.1:8080` — no conflict |
| Port 3001 | free | PostgREST binds `127.0.0.1:3001` — no conflict |
| Port 9119 | free | hermes-actor Mission Control binds `127.0.0.1:9119` — no conflict |
| Ollama | **NOT installed**; nothing on `:11434` or `:11435` | Must install (flagged below) |
| nginx layout | `sites-enabled/brookhaven` → `sites-available/brookhaven`; also `sites-available/default` | Add a NEW `safeclaw` site alongside |
| nginx version | `nginx/1.24.0 (Ubuntu)` | OK |
| certbot | `/usr/bin/certbot` present; renewal `srv1687869.hstgr.cloud.conf` exists | Reuse for the new subdomain |
| Let's Encrypt certs | `live/srv1687869.hstgr.cloud/` (Brookhaven only) | New cert needed for SafeClaw subdomain |
| Brookhaven health | `http://127.0.0.1:8001/health` → `{"status":"ok"}`; `https://srv1687869.hstgr.cloud/health` → `{"status":"ok"}` | **Baseline captured — protect this** |

### Readiness verdict: READY (no hard blockers)
- Docker/Compose already present → install step skippable.
- Resources sufficient for ~6–8 containers + 148 MB brain image + Ollama, but **2 vCPU / 8 GiB / no swap is the tight constraint**. The 148 MB is just the brain image; the *Ollama embedding model* (`nomic-embed-text`, ~275 MB on disk) plus embedding inference runs on CPU on the host. Embeddings are bursty (bootstrap indexes 90 days of email). Recommend adding swap before the run (see Pre-flight).
- One real blocker to *automation*, not to feasibility: **the stock Caddy step must not run** (port collision). This plan substitutes nginx.

### Two discrepancies found in the repo that affect Suffolk (flagged, not changed):
1. **Ollama port mismatch.** `docker-compose.yml` points `safeclaw-brain` at `host.docker.internal:11434` but both Hermes containers at `host.docker.internal:11435`. `provision-vps.sh` installs Ollama on the default **:11434** only and `ollama pull`s there. So the **brain's embeddings will work** (11434) but **Hermes' `ollama-cloud` provider will fail** unless either (a) the customer uses an Anthropic/OpenAI LLM key instead of local Ollama (recommended for Suffolk — the brain only needs local Ollama for *embeddings*, Hermes can use a hosted LLM), or (b) you run a second Ollama listener / socket on 11435. **Decide at pre-flight (see step P6).**
2. The compose `image:` tags pull from `ghcr.io/vasanth19/safeclaw-*`; `provision-vps.sh` clones from `github.com/Vasanth19/safeclaw.git`. Confirm both the GHCR images and the repo are published/public before the run, or build locally.

---

## 1. Pre-flight checklist (operator + customer)

### P1. DNS — CUSTOMER/OPERATOR ACTION REQUIRED (do this first, allow propagation)
Create an **A record** for a new subdomain pointing at `187.77.30.131`, e.g.:
```
safeclaw.srv1687869.hstgr.cloud   A   187.77.30.131
```
(Or a customer-branded apex/subdomain on a domain they own that resolves to this IP.) **No CNAME** — certbot needs to validate the A record directly. Do not proceed to the nginx/certbot step until `dig +short safeclaw.srv1687869.hstgr.cloud` returns `187.77.30.131`.

### P2. Credentials the CUSTOMER must supply (entered in the onboarding wizard, Step 2)
- **LLM access** — ONE of:
  - Ollama Cloud key (if using `ollama-cloud` provider — but see discrepancy #1 re: port 11435), or
  - **Anthropic API key** (recommended for Suffolk — avoids the 11435 issue), or OpenAI API key.
- **Composio**: `COMPOSIO_API_KEY` + `COMPOSIO_USER_ID`. The wizard auto-provisions the reader/actor MCP servers from these (`validator.provision_composio_mcps`), so the customer does **not** need to paste the two MCP URLs manually — but if pre-provisioned, have `COMPOSIO_READER_MCP_URL` + `COMPOSIO_ACTOR_MCP_URL` ready as a fallback. Customer must have already connected Gmail/Drive/Slack to their Composio account.
- **Telegram**: `TELEGRAM_BOT_TOKEN` + `TELEGRAM_ALLOWED_USERS` (the boss's numeric Telegram user id). Actor owns the user-facing chat.
- **Slack (optional)**: `SLACK_BOT_TOKEN`, `SLACK_APP_TOKEN`, `SLACK_HOME_CHANNEL`, `SLACK_INGEST_CHANNELS`. If omitted, the welcome DM is skipped (soft-fail) — install still completes.
- **Firecrawl (optional)**: `FIRECRAWL_API_KEY` for the actor's `web_search`/`web_extract`.
- **Google Drive (optional)**: service-account JSON for organized Drive uploads.

### P3. NOT brought by the customer (auto-generated/minted on box)
- `BRAIN_DB_PASSWORD`, `POSTGRES_TASKS_PASSWORD`, `TASKS_AGENT_PASSWORD`, `TASKS_HUMAN_PASSWORD`, `JWT_SECRET`, `TASKS_AGENT_JWT` → `init-secrets.sh`.
- `SAFECLAW_BRAIN_READER_TOKEN`, `SAFECLAW_BRAIN_ACTOR_TOKEN` → minted post-boot via `gbrain auth create` (provisioner phase `mint_tokens`).

### P4. Confirm artifacts are reachable — OPERATOR ACTION
- GHCR images public: `ghcr.io/vasanth19/safeclaw-hermes:1.2`, `ghcr.io/vasanth19/safeclaw-brain:0.37.11.0` (or build brain locally from `docker/safeclaw-brain/`).
- Repo public: `github.com/Vasanth19/safeclaw.git`.

### P5. Capture the Brookhaven baseline (so we can prove non-interference later) — read-only
```bash
curl -s https://srv1687869.hstgr.cloud/health        # expect {"status":"ok"}
curl -s http://127.0.0.1:8001/health                 # expect {"status":"ok"}
ss -tlnp | grep -E ':80|:443|:8001|:5432'            # record the owning pids
```

### P6. DECIDE the LLM path (resolves discrepancy #1) — OPERATOR + CUSTOMER
- **Recommended:** customer supplies an **Anthropic (or OpenAI) LLM key**; the wizard's `LLM_PRESETS` repoints Hermes off Ollama. Local Ollama is then needed **only** for brain embeddings on :11434 (which the provision script already handles). This sidesteps the :11435 mismatch entirely.
- If the customer insists on Ollama Cloud for the LLM: you must also expose Ollama (or a proxy) on **:11435** for the Hermes containers, OR patch the two Hermes `OLLAMA_BASE_URL` values in `docker-compose.yml` to `:11434`. Flag as a change requiring go-ahead.

### P7. (Recommended) add swap — DESTRUCTIVE-ish, REQUIRES GO-AHEAD
No swap is configured. Under bootstrap (90-day email embed) the 2 vCPU / 8 GiB box can spike. Adding a 4 GiB swapfile is low-risk and reversible:
```bash
# REQUIRES OPERATOR GO-AHEAD — modifies host
fallocate -l 4G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
echo '/swapfile none swap sw 0 0' >> /etc/fstab
```

---

## 2. nginx-coexistence adaptation (REPLACES the Caddy step)

> **DO NOT install or run Caddy.** Caddy binds 80/443 and would knock out Brookhaven. Instead add an nginx server block for the SafeClaw subdomain proxying to `127.0.0.1:8080`, mirroring the existing Brookhaven block, and let the existing `certbot` issue its cert.

### 2a. Write the SafeClaw nginx site — REQUIRES GO-AHEAD (writes to /etc/nginx)
Create `/etc/nginx/sites-available/safeclaw` (HTTP-only first; certbot adds the TLS lines):
```nginx
# /etc/nginx/sites-available/safeclaw
# SafeClaw onboarding + app. Proxies to the localhost-only onboarding container
# (and the app it boots). Coexists with the Brookhaven block — separate server_name.
server {
    listen 80;
    listen [::]:80;
    server_name safeclaw.srv1687869.hstgr.cloud;

    # Onboarding webapp + SSE install stream. The container publishes 127.0.0.1:8080.
    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # SSE: the onboarding install stream is long-lived — disable buffering.
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 3600s;
        proxy_set_header Connection '';
        chunked_transfer_encoding off;
    }
}
```
Enable it (does NOT touch the Brookhaven symlink):
```bash
ln -s /etc/nginx/sites-available/safeclaw /etc/nginx/sites-enabled/safeclaw
nginx -t                 # validate BOTH blocks parse — abort if not OK
systemctl reload nginx   # reload (not restart) — zero downtime for Brookhaven
```

### 2b. Issue the cert with the existing certbot — REQUIRES GO-AHEAD (network + writes /etc/letsencrypt)
Use the nginx installer plugin so certbot edits the `safeclaw` block in place and leaves Brookhaven untouched. `-d` is scoped to ONLY the new subdomain:
```bash
certbot --nginx -d safeclaw.srv1687869.hstgr.cloud \
  --non-interactive --agree-tos -m <ADMIN_EMAIL> \
  --redirect
```
This adds `listen 443 ssl;` + the cert paths + an 80→443 redirect to the `safeclaw` server block only. Verify Brookhaven's block is unchanged afterward (`git diff`-style review of `sites-available/brookhaven` — it should be byte-identical). Re-run `nginx -t && systemctl reload nginx`.

> Net effect: nginx now serves BOTH `srv1687869.hstgr.cloud` (Brookhaven) and `safeclaw.srv1687869.hstgr.cloud` (SafeClaw) on the same 80/443 listeners via `server_name` virtual hosting. No port contention.

---

## 3. Step-by-step install sequence (Caddy step REMOVED)

This adapts `scripts/provision-vps.sh` but **skips its steps 1-base-pkgs/Caddy, 3-ufw-reset, and 6-Caddyfile**. Run as root.

> **DO NOT run `provision-vps.sh` as-is** — its step 6 writes a Caddyfile and reloads Caddy on 80/443, and its step 3 does `ufw --force reset` (which could disrupt Brookhaven's firewall posture). Run the steps below manually instead.

### S1. Firewall — INSPECT FIRST, do NOT blindly reset — REQUIRES GO-AHEAD if changing
The script's `ufw --force reset` is destructive to existing rules. Instead:
```bash
ufw status verbose      # read-only: see what's there
# Only if ufw is active and 80/443/22 are NOT already allowed, add them WITHOUT reset:
# ufw allow 22/tcp; ufw allow 80/tcp; ufw allow 443/tcp
```
SafeClaw publishes no new public ports (onboarding is 127.0.0.1-only; nginx already owns 80/443), so likely **no firewall change is needed**.

### S2. Docker — SKIP (already 29.5.1 + Compose v5.1.3). 
Only verify: `docker compose version`.

### S3. Clone the repo to /opt/safeclaw — REQUIRES GO-AHEAD (writes /opt)
```bash
mkdir -p /opt
git clone https://github.com/Vasanth19/safeclaw.git /opt/safeclaw
cd /opt/safeclaw
```
(Idempotent re-run: `git -C /opt/safeclaw fetch && git -C /opt/safeclaw reset --hard origin/main`.)

### S4. Install Ollama on the host (embeddings) — REQUIRES GO-AHEAD (installs a service)
```bash
curl -fsSL https://ollama.com/install.sh | sh
systemctl enable --now ollama
curl -fsS http://localhost:11434/api/tags        # expect JSON
ollama pull nomic-embed-text                      # ~275 MB; brain embeddings model
```
> Ollama binds `127.0.0.1:11434` by default — no conflict with Brookhaven. The `safeclaw-brain` container reaches it via `host.docker.internal:11434` (mapped to host-gateway in compose). **If you chose the Ollama-Cloud LLM path in P6, also resolve :11435 here.**

### S5. Pull / build images — REQUIRES GO-AHEAD (network, disk)
```bash
cd /opt/safeclaw
docker compose pull          # pulls hermes:1.2 + brain:0.37.11.0 + postgres/postgrest/etc.
# If the brain image isn't on GHCR, build it (148 MB target):
# docker compose build safeclaw-brain
```

### S6. Boot ONLY the onboarding webapp — REQUIRES GO-AHEAD (starts a container)
```bash
docker compose up -d onboarding
# wait for health:
until curl -fsS http://localhost:8080/health >/dev/null 2>&1; do sleep 3; done
```
The onboarding container binds `127.0.0.1:8080` (+ `[::1]:8080`) only. nginx (step 2) fronts it at `https://safeclaw.srv1687869.hstgr.cloud`.

### S7. Run the wizard — CUSTOMER ACTION
Send the customer: `https://safeclaw.srv1687869.hstgr.cloud/setup`
They fill Step 2 with the P2 credentials and click Submit. The provisioner (`onboarding/lib/provisioner.py`) then runs ALL of the following automatically as an SSE-streamed pipeline — **steps S8–S12 below are what it does**; you do not run them by hand unless the wizard fails and you're recovering.

### S8. (auto) Write .env + secrets
`_phase_env` writes `.env` from the form (+ Composio MCP auto-provision); `_phase_secrets` runs `init-secrets.sh` to fill `__GENERATE__` passwords/JWT.

### S9. (auto) Boot the brain layer first
`docker compose up -d safeclaw-brain` → brings up `postgres-brain` (transitively) + `safeclaw-brain`. Entrypoint runs `gbrain init --embedding-model ollama:nomic-embed-text --embedding-dimensions 768` (first boot only) then `gbrain apply-migrations --yes`, then `gbrain serve --http --port 3131`.

### S10. (auto) Wait for brain health, then mint tokens
`_phase_brain_health` waits on `/health`; `_phase_mint_brain_tokens` runs `docker compose exec -T safeclaw-brain gbrain auth create reader` and `... actor`, parses the `gbrain_<64hex>` tokens, writes them into `.env` as `SAFECLAW_BRAIN_READER_TOKEN` / `SAFECLAW_BRAIN_ACTOR_TOKEN`.

### S11. (auto) Full compose up
`_phase_compose_up_rest` runs `docker compose up -d` — (re)creates hermes-reader, hermes-actor, postgres-tasks, postgrest, rclone-upload, reflector with the freshly-minted brain tokens in `.env`.

### S12. (auto) Wait for health, then bootstrap
`_phase_health` waits on `postgres-brain`, `safeclaw-brain`, `postgres-tasks`. `_phase_bootstrap` runs `scripts/bootstrap-brain.sh` — pulls 90 days of Gmail via the Composio Reader MCP and seeds the brain (people/companies pages, `extract_facts`, style samples, `identity/soul`). Then `_phase_welcome` DMs the boss (Slack, soft-fail if absent), and `done`.

---

## 4. Brain-specific call-outs

- **postgres-brain is containerized with NO host port** (`docker-compose.yml`: no `ports:` on the service). Brookhaven's host Postgres on `127.0.0.1:5432` is **completely independent** — different cluster, different process, no port overlap. SafeClaw's two Postgres (brain + tasks) talk only over `safeclaw_net`.
- **GBrain token minting** happens post-boot, not in `init-secrets.sh`. The tokens stay `__MINTED__` in `.env` until the brain is healthy, then `gbrain auth create` mints them. Legacy bearer tokens grandfather to `read+write+admin` (over-privileged but acceptable for v1 — the real boundary is the Composio reader/actor split).
- **Local Ollama embeddings:** `nomic-embed-text` (768-dim) on host `:11434`, reached via `host.docker.internal:11434/v1`. Zero egress for embeddings, no key. **Must `ollama pull nomic-embed-text` (step S4) before S9** or the brain init/embedding fails.
- **GBRAIN_VERSION pinning:** `.env` pins `GBRAIN_VERSION=0.37.11.0`; the image build arg `GBRAIN_REF=fe3499e5a184c8e507a30f0bb6ad7f9c7f7c9551` pins the exact upstream source SHA (upstream doesn't tag releases). Upgrades = bump both, `docker compose pull safeclaw-brain && docker compose up -d safeclaw-brain` — entrypoint re-runs `apply-migrations` idempotently; the `safeclaw_brain_data` + `safeclaw_brain_db` volumes persist data across upgrades.

---

## 5. Verification

### 5a. SafeClaw stack healthy
```bash
cd /opt/safeclaw
docker compose ps                       # all services Up/healthy
# brain reachable from inside the network + identity:
docker compose exec -T safeclaw-brain curl -fsS http://localhost:3131/health
docker compose exec -T safeclaw-brain gbrain stats         # pages/people/companies seeded
docker compose exec -T safeclaw-brain gbrain list-pages | grep -i soul   # identity/soul present
docker compose logs --tail=50 hermes-actor                 # actor up, no provider errors
curl -s https://safeclaw.srv1687869.hstgr.cloud/health     # onboarding/app 200 via nginx
```
- **Token scopes:** a brain request with a minted token succeeds for read+write; an unauthenticated request is rejected.
- **Reader path:** feed a test email → reader writes an observation page visible via `gbrain query`.
- **Actor path:** ask the actor about a known contact via Telegram → it queries the brain first (check logs), drafts in the soul/style voice, posts an approval.

### 5b. Brookhaven NON-INTERFERENCE check (must all still pass)
```bash
curl -s https://srv1687869.hstgr.cloud/health        # STILL {"status":"ok"}
curl -s http://127.0.0.1:8001/health                 # STILL {"status":"ok"}
ss -tlnp | grep -E ':80|:443'                         # STILL owned by nginx (same pids family)
ss -tlnp | grep ':8001'                               # STILL uvicorn, untouched
ss -tlnp | grep ':5432'                               # STILL host postgres, untouched
systemctl status nginx --no-pager                     # active (running), serving both vhosts
diff <(cat /etc/nginx/sites-available/brookhaven) <BASELINE_COPY>   # brookhaven block unchanged
```
If ANY of these regress, STOP and roll back (section 6).

---

## 6. Rollback (remove SafeClaw without touching Brookhaven)

```bash
# 1. Tear down SafeClaw containers + network (keeps volumes by default):
cd /opt/safeclaw && docker compose down

# 2. Full removal incl. data volumes (DESTRUCTIVE to SafeClaw data only):
docker compose down -v                 # removes safeclaw_brain_db, safeclaw_brain_data, tasks_data, etc.

# 3. Remove the nginx site (Brookhaven block is a SEPARATE file — untouched):
rm -f /etc/nginx/sites-enabled/safeclaw
# optional: rm /etc/nginx/sites-available/safeclaw
nginx -t && systemctl reload nginx

# 4. Remove the SafeClaw cert (Brookhaven cert lives in a separate live/ dir):
certbot delete --cert-name safeclaw.srv1687869.hstgr.cloud

# 5. (optional) Stop/remove Ollama if it was installed only for SafeClaw:
systemctl disable --now ollama         # leave installed if unsure; harmless on :11434

# 6. (optional) Remove the repo + swapfile:
rm -rf /opt/safeclaw
# swapoff /swapfile && sed -i '/\/swapfile/d' /etc/fstab && rm /swapfile
```
Brookhaven (`uvicorn :8001`, host Postgres `:5432`, its nginx vhost, its cert) is never referenced by any of the above.

---

## 7. Steps requiring explicit operator go-ahead / customer action (summary)

| Step | Type | Owner |
|---|---|---|
| P1 — create DNS A record for `safeclaw.*` | CUSTOMER/OPERATOR (external) | customer |
| P2 — supply LLM/Composio/Telegram/Slack creds | CUSTOMER | customer |
| P6 — decide LLM path (resolve :11435 mismatch) | DECISION | operator+customer |
| P7 — add 4 GiB swap | DESTRUCTIVE-ish (host change) | operator go-ahead |
| 2a — write+enable `/etc/nginx/sites-available/safeclaw` | WRITE to /etc/nginx | operator go-ahead |
| 2b — `certbot --nginx -d safeclaw.*` | WRITE /etc/letsencrypt, network | operator go-ahead |
| S1 — any ufw change | host firewall | operator go-ahead (likely none needed) |
| S3 — clone repo to /opt/safeclaw | WRITE /opt | operator go-ahead |
| S4 — install Ollama + pull model | install service, network | operator go-ahead |
| S5 — docker compose pull/build | network, disk | operator go-ahead |
| S6 — boot onboarding container | starts container | operator go-ahead |
| S7 — run wizard | CUSTOMER (browser) | customer |

**Never run:** `provision-vps.sh` unmodified (Caddy + `ufw --force reset`), anything that binds 80/443/8001/5432 on the host, anything that restarts/reloads Brookhaven's uvicorn or host Postgres, `apt` operations that could pull in Caddy.
