# SafeClaw on orgo.ai — template deployment runbook

> # ⛔ DEPRECATED — do NOT deploy from this document
>
> This is the **legacy Docker-era plan** (docker compose, ghcr.io brain image,
> local Ollama embeddings). It was superseded by the **native, no-Docker stack**
> proven on mark-agent and elise-losasso. Following this doc produces a box where
> gbrain is installed but **never initialized** and **no embedding provider is
> configured** — the Console shows zero brain pages and semantic search is dead.
>
> **Deploy from these instead:**
> - **`ORGO-CLIENT-TEMPLATE.md`** — the full runbook (Step 2 = `gbrain init
>   --pglite --embedding-model openrouter:…` — REQUIRED, never skip)
> - **`INSTALL-CHECKLIST.md`** — the tick-box mirror
>
> Kept only as historical reference for the Docker approach.

Going-forward client deploys as **template duplication**: build one golden
snapshot, then "duplicate a workspace + configure" per customer. Each client =
one orgo **workspace** (`client-<name>`) + one **computer** cloned from the
snapshot. Suffolk stays on its VPS — this track is for NEW clients.

> 🔐 Rotate the orgo key first. The `sk_live_…` shared in chat is compromised.
> Mint a fresh key, then `export ORGO_API_KEY=sk_live_…`. Never commit it.

## What runs on each client computer

```
Hermes (native): gateway (Telegram poll + Slack socket) + web dashboard :9119 (loopback)
  plugins:  safeclaw-memory · safeclaw-personas · safeclaw-connections
  agents:   reader (read-only) · actor (draft-only)        ← trust split via personas
  skills:   slack-to-gdrive · …                            ← skills/ library
docker compose (orgo/docker-compose.brain.yml):
  gbrain :3131 (loopback) + postgres-brain (pgvector)
embeddings: host Ollama nomic-embed-text (small). LLM is hosted (off-box).
```

Pure egress — no public ports. Telegram polls, Slack uses socket mode, Composio
is outbound. The dashboard is loopback-only (reach it via the orgo desktop).

## One-time: build the golden snapshot

1. Create a scratch orgo computer (Ubuntu, ≥2 vCPU / 8 GB).
2. On it:
   ```bash
   sudo apt-get update && sudo apt-get install -y docker.io docker-compose-plugin git python3-pip
   pip3 install requests pyyaml
   git clone https://github.com/Vasanth19/safeclaw /opt/safeclaw
   cd /opt/safeclaw
   # install Hermes (Nous) + pull the brain image so first client boot is fast
   curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash    # see Hermes docs
   docker pull ghcr.io/vasanth19/safeclaw-brain:0.37.11.0
   docker pull pgvector/pgvector:pg16
   # host Ollama for embeddings
   curl -fsSL https://ollama.com/install.sh | sh && ollama pull nomic-embed-text
   ```
3. Leave config as placeholders (no secrets baked in).
4. **Snapshot the computer** in orgo → note the snapshot id. That id is the
   `--snapshot-id` every client deploy clones from.

## Per client: duplicate → configure → go

```bash
cd /opt/safeclaw        # or your local clone with orgo/ + ORGO_API_KEY set
cp orgo/client.env.example orgo/client.env
$EDITOR orgo/client.env         # fill __FILL_IN__ (Composio, Slack, Telegram, LLM keys)

export ORGO_API_KEY=sk_live_…   # the ROTATED key
python3 orgo/provision-client.py --name acme --snapshot-id <golden-snapshot-id>
```

`provision-client.py` then: creates workspace `client-acme` → clones a computer
from the snapshot → pushes `client.env` → brings up the brain → mints brain
tokens → renders agent configs from the connections registry → starts Hermes
(dashboard + gateway) → backfills the brain.

### Client-side prerequisites (manual, documented for the customer)

- Connect Gmail/Slack in **Composio**, create the read + draft MCPs, paste URLs
  into `client.env`.
- Create a Telegram bot via **@BotFather**, paste the token.
- These are the only OAuth steps; no DNS, TLS, or webhooks.

## Public URL + client self-serve setup

orgo can't expose app ports publicly, so each client gets a stable URL via a
**cloudflared named tunnel → authenticated Caddy → loopback dashboard**. See
`orgo/access/README.md` for the one-time tunnel + DNS + bcrypt-auth setup. The
client opens `https://safeclaw-<name>.<domain>`, logs in, and uses the **Setup**
and **Connections** tabs. The dashboard never leaves loopback — only the
authenticated Caddy is reachable.

## Auto-config from uploaded tokens (`orgo/setup/apply.py`)

The "upload your Gmail/Google/Slack/Telegram tokens and everything wires itself
up" pipeline — the orgo counterpart of the current SafeClaw onboarding, reusing
its validators (`onboarding/lib/validator.py`) and atomic env writer
(`onboarding/lib/env_writer.py`):

```bash
# creds.json = the setup form payload (same field names as the onboarding form)
python3 orgo/setup/apply.py --creds creds.json --install-dir . --restart
```

It runs, fail-fast, in order: validate creds against the real upstream APIs →
provision the Composio Reader/Actor Gmail MCP servers → write the Google
service-account JSON to `/opt/config/drive_credentials.json` (0600) → write
`client.env` atomically → register connections in the registry → render the
agent configs (`scripts/render-hermes-config.py`) → restart Hermes.

## Configure connections (the dashboard)

In the **Connections** tab (public URL or orgo desktop → `127.0.0.1:9119`):

- Add Gmail (one or several accounts), Slack, Telegram, Google Drive.
- Each connection is bound to **Reader** (read-only) or **Actor** (draft-only);
  scope is locked — you cannot grant a send tool.
- After adding/removing connections, re-render and restart Hermes (or just run
  `orgo/setup/apply.py` which does it for you):
  ```bash
  python3 scripts/render-hermes-config.py --agent actor \
      --base config/actor-hermes.yaml --out ~/.hermes/actor-config.yaml \
      --connections-dir ~/.hermes/connections --env-out orgo/client.env
  # (repeat --agent reader), then restart the Hermes gateway
  ```

## Security defaults (client-facing — keep them)

- `AUTO_SEND_ENABLED=false` — **draft-only**. The Actor drafts; a human sends.
  Flip per client only after an explicit, logged decision.
- Trust split enforced by the personas + connections plugins: a persona/
  connection can never grant itself a send/exfil tool (HTTP 422).

## Verify

```bash
bash scripts/smoke-brain.sh                 # brain /health + gbrain stats
# dashboard → Connections shows the accounts; scope badges read "read"/"draft"
# Telegram-DM the bot a memory question → confirms GBrain recall
# Send the test inbox a "reply with wiring details" email → expect a DRAFT, never a send
```

## Open items (see plan + tasks)

- Verify orgo workspace + snapshot/clone endpoint names against
  `docs.orgo.ai/llms-full.txt` (the `VERIFY` markers in `provision-client.py`).
- Optional: hosted embeddings (drop host Ollama) — only after confirming the
  GBrain image accepts an API-keyed OpenAI-compatible embeddings endpoint.
- Connections frontend bundle is pure-SDK (no npm imports). `dist/` is
  gitignored, so run `dashboard-plugins/safeclaw-connections/build.sh` once at
  provision time (it copies src→dist, or esbuild-minifies if available) so the
  plugin manifest's `entry: dist/index.js` resolves. Re-run after any src edit.
- In-dashboard Composio OAuth onboarding (Connections tab → "Connect with
  OAuth") needs `COMPOSIO_API_KEY` + `COMPOSIO_USER_ID` in the dashboard process
  env. The key stays server-side; clients only get the provider redirect_url.
  This replaces the standalone Netlify connect page — onboarding stays on-box.
