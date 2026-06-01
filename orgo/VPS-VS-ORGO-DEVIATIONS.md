# VPS SafeClaw vs orgo-native SafeClaw — Deviations, Trade-offs, and Migration Plan

> **What this is.** A strategic engineering record answering the owner's question:
> *"How have we deviated from the original SafeClaw we install on the VPS? We've
> greatly simplified it. If I make the orgo installation my MAIN deployment and use
> Hermes profiles, what needs to change — including in the GitHub repo
> (`Vasanth19/safeclaw`)?"*
>
> **Framing correction baked in (2026-06-01).** The original VPS SafeClaw was **not**
> headless. It shipped its own onboarding/setup flow (`onboarding/` Flask installer +
> `CUSTOMER-ONBOARDING.md`) and a dashboard surface, and its **Slack setup is _better_**
> than what orgo-native currently has. That Slack stack (custom `mcp-tools/slack-api`
> MCP with a **source-level `SLACK_MCP_MODE` reader/actor tool-allowlist split**, plus a
> real Slack-app `manifest.json` and a 10-step customer walkthrough) is being **ported
> INTO** the orgo template, not discarded. The comparison below reflects this
> feature-by-feature.
>
> **Slack reality check (verified against `mcp-tools/slack-api/src/index.ts`, 226 lines).**
> The MCP is a **stdio request/response REST wrapper** over `@slack/web-api`. It reads
> **only `SLACK_BOT_TOKEN`** (throws if missing) and branches its tool allowlist on
> `SLACK_MCP_MODE` (`reader` vs `actor`). It contains **no Socket Mode code**, does **not**
> depend on `@slack/socket-mode` or `@slack/bolt`, and **never references
> `SLACK_MCP_BOT_TOKEN`**. The only `socket_mode_enabled: true` in the tree is in the
> Slack-app `manifest.json` (app config) — it is **not** implemented in the MCP. So
> "only the actor opens Socket Mode / second-poller avoidance / `SLACK_MCP_BOT_TOKEN`
> routing" is **not** an existing VPS strength; if we want Socket Mode it is **net-new
> work** (see PR 2). The verified, real strength is the `SLACK_MCP_MODE` tool-split.
>
> **No secrets.** All credentials are placeholders: `<ORGO_API_KEY>`, `<OLLAMA_API_KEY>`,
> `<COMPOSIO_API_KEY>`, `<TELEGRAM_BOT_TOKEN>`, `<UI_PASSWORD>`, `<SLACK_BOT_TOKEN>`.

---

## 0. TL;DR

- The orgo-native deployment is the **same product** (Hermes reader/actor trust split + GBrain brain) with a **radically simpler runtime**: no Docker, no Compose, no host-Ollama embeddings daemon, no Caddy/nginx, no Postgres+pgvector. It runs as five tmux sessions behind one Cloudflare named tunnel on an always-on orgo box.
- The trust split moves from **two-Composio-MCP-servers + container isolation** to **two Hermes profiles** (separate `HERMES_HOME`, separate tool allowlists, separate `.env`). This is still architecturally enforced, but it is **config-level isolation, not container-level** — the single most important security delta to acknowledge.
- The VPS build has **two strengths the orgo template currently lacks**: (1) the custom Slack MCP with a baked-in `SLACK_MCP_MODE` reader/actor **tool-allowlist split** (verified in source; **no** Socket Mode — that part is net-new work, not an existing strength), and (2) a hardened onboarding installer. **Both are being ported back into the orgo template** — orgo simplifies the runtime, it does not have to mean a weaker Slack or a worse setup UX.
- Making orgo the MAIN deployment is mostly a **repo-hygiene and documentation** exercise: commit the five untracked dirs, promote `orgo/ORGO-CLIENT-TEMPLATE.md` to canonical, demote the Docker docs to a legacy folder (kept maintained for Suffolk/Hoover), and flip `main` to orgo-first **without re-pointing Suffolk's VPS checkout** (it tracks `feat/safeclaw-brain-gbrain` and must not break).

---

## 1. Side-by-side architecture comparison

Two real, deployed shapes:

- **VPS SafeClaw** — as running on **Suffolk** (`/opt/safeclaw`, Docker Compose, tracks `feat/safeclaw-brain-gbrain`). Source of truth: `ARCHITECTURE.md`, `docker-compose.yml`, `mcp-tools/slack-api/`, `onboarding/`.
- **orgo-native SafeClaw** — as proven on the **mark-agent** reference box in Jake's paid orgo workspace. Source of truth: `orgo/ORGO-CLIENT-TEMPLATE.md`, `safeclaw-ui/app.py`.

| Component | VPS SafeClaw (Suffolk) | orgo-native SafeClaw (mark-agent) | Net change |
|---|---|---|---|
| **Trust-split enforcement point** | Two **separate Composio MCP servers** (Reader URL = read-only toolkit allowlist, e.g. `GMAIL_FETCH_EMAILS`; Actor URL = draft/send allowlist, e.g. `GMAIL_CREATE_DRAFT`, `GMAIL_SEND_EMAIL`, `TELEGRAM_SEND_MESSAGE` — slugs per `ARCHITECTURE.md` §4.4/§5.2; illustrative, the canonical allowlist lives in the Composio dashboard). Allowlist lives in the Composio dashboard per server, bound at **container boot**. Plus the Slack MCP's own `SLACK_MCP_MODE` source-level tool-allowlist split. | Two **Hermes profiles** (`/root/.hermes/profiles/reader` and `/root/.hermes/profiles/actor`), each a distinct `HERMES_HOME` with its own `config.yaml` tool list and its own `.env`. Reader profile gets read-only Composio Gmail tools; actor gets draft tools (no SEND). Default profile (dashboard `--tui` gateway) has **no Telegram token**. | **Same boundary, weaker isolation.** Still two allowlists the model can't cross, but enforced by **process/config separation on one box**, not by two containers on a Docker bridge. See §2. |
| **Brain (GBrain)** | `safeclaw-brain` container, `gbrain serve --http` on internal `:3131`, **Postgres + pgvector** (`postgres-brain` container), Bearer-token HTTP MCP, **embeddings via host Ollama** (`nomic-embed-text`). Per-holder auth tokens (reader/actor). | `gbrain init --pglite --no-embedding`, **stdio MCP (87 tools)**, wired into both profiles via `hermes mcp add gbrain --command gbrain --args serve`. **No embeddings at all** by default (PGLite, no-embedding). | **Big simplification + a capability gap.** Drops a Postgres container, a pgvector DB, and the host-Ollama embeddings daemon. But **no embeddings = no semantic search and `gbrain dream` can't run its embed phase** (see §2 + the dream cron gap). |
| **Runtime / process model** | **Docker Compose** (`docker-compose.yml`, ~20 KB): agent tier (`hermes-reader`, `hermes-actor`), platform tier (`safeclaw-brain`, `postgrest`, `tasks-api`, `reflector` weekly cron), data tier (`postgres-brain`, `postgres-tasks`) on one `safeclaw_net` bridge. Restart policies + healthchecks managed by Docker. | **Five tmux sessions** — `cf` (cloudflared), `wd` (watchdog), `sui` (Console), `hd` (Hermes dashboard `--tui`), `gw` (actor Telegram gateway). **No systemd, no cron, no Docker.** A `while true; sleep 30` watchdog supervisor curl-checks 8899/9119/cloudflared/gateway, relaunches dead ones, and re-syncs the clock. | **Reproducibility down, footprint way down.** Compose was a one-file, declarative, restart-policy'd topology; tmux+watchdog is imperative and bespoke. orgo's `/bash` **reaps nohup/setsid** — only tmux survives — so the watchdog is mandatory, not optional. |
| **LLM (inference)** | Ollama Cloud, **glm-4.7** (proven default; clean tool-calls, non-reasoning). Credential pool at `/opt/data/auth.json` (multi-key, rotates on clean 429s). | Ollama Cloud, **kimi-k2.5** per the template — **note:** knowledge says glm-4.7 is the proven model that survives the 78-tool agentic loop; kimi-k2.5 reasons ~3.7 min/step and is a known failure for ingest. **This should be normalized to glm-4.7 in the template.** | **Same provider, off-box.** Both keep inference off the box (local Ollama OOM-kills small boxes). Model-choice drift to fix during migration. |
| **Ingest** | Hermes agentic ingest into the brain; cron-driven (`0 */2 * * *`), `compression.enabled: true`, `max_turns: 25`, `api_max_retries: 2`. Docker cron / `reflector` container handles cadence. | Same Hermes ingest, but **no systemd/cron on orgo** → ingest cadence must become a **Hermes cron job** (built-in scheduler) inside the actor/reader profile, not an OS cron. | **Scheduler moves into Hermes.** Same token-economy config applies; the cron *host* changes. |
| **UI / setup / dashboard** | **Two surfaces:** (a) `onboarding/` Flask installer on `:8080` behind Caddy — the actual customer setup wizard (`CUSTOMER-ONBOARDING.md`), with tests under `onboarding/tests/`; (b) Hermes' own dashboard. | **Two surfaces:** (a) **SafeClaw Console** (`safeclaw-ui/app.py`, no-build Flask, `127.0.0.1:8899`, before_request basic-auth, panels: Dashboard / Chat / Slack / Telegram / Gmail / GoogleDrive / Zapier-MCP; Chat → `hermes chat -q -Q`); (b) Hermes dashboard `--tui` on `:9119` (the `--tui` flag is what exposes the Chat tab). | **Both had a setup UI** — this is the corrected framing. orgo's Console is a richer, always-on ops panel; the VPS onboarding installer is a hardened **first-run wizard** with tests. The onboarding wizard's hardening is being **ported into the Console flow** (§3). |
| **Slack** | **Stronger tool-split (verified).** Custom `mcp-tools/slack-api` — **TypeScript stdio MCP baked into the Hermes image**, run by *both* agents, switching its **tool allowlist** on `SLACK_MCP_MODE` (`reader`/`actor`). Reader mode → `slack_list_channels`, `slack_get_channel_history`, `slack_get_user_info`, `slack_download_file`. Actor mode → `slack_download_file`, `slack_send_message`, `slack_upload_file`. It is a **stdio REST request/response wrapper over `@slack/web-api`** — it reads **only `SLACK_BOT_TOKEN`** and contains **no Socket Mode**. Real `manifest.json` with exact OAuth scopes (the `socket_mode_enabled: true` there is **app config only**, not implemented in the MCP); `docs/SLACK-APP-WALKTHROUGH.md` is a 10-step customer guide producing `xoxb-`/`xapp-`/`T…`/`U…`. | **Currently weaker.** The Console "Slack" panel **only saves tokens** — there is no mode-split MCP and no walkthrough integrated. | **VPS wins on the tool-split today; being PORTED into orgo.** The `mcp-tools/slack-api` `SLACK_MCP_MODE` reader/actor allowlist + the walkthrough is the canonical port-in target. **Socket Mode is NOT being ported (it doesn't exist) — if real-time presence is wanted, PR 2 BUILDS it** (net-new). Because the MCP uses `@slack/web-api` REST (request/response, no long-lived poller), the "second poller / single live presence" framing does not apply. **Gotcha to carry over:** the stdio Slack MCP child goes silent (`ClosedResourceError`, empty error string) after **~8h** — the orgo watchdog must add a periodic Slack-MCP/gateway restart. **Fix on the way in:** `orgo/client.env.example` ships a `SLACK_MCP_BOT_TOKEN` var the code ignores — drop it (the MCP reads only `SLACK_BOT_TOKEN`). |
| **Telegram** | Actor-only token in the actor's environment; reader never holds it. | **Same discipline:** `TELEGRAM_BOT_TOKEN` + `TELEGRAM_ALLOWED_USERS` in the **actor profile `.env` only**; default+reader `.env` carry no token. Gateway runs in tmux `gw`. **One getUpdates consumer per bot** — dedicated @BotFather bot per box; never run `--tui` with a token on the default profile (second poller). | **Equivalent.** Profile `.env` cleanly expresses "token lives only with the actor," which was previously a container-env fact. |
| **Tunneling / exposure** | **nginx/Caddy + host ports.** Suffolk specifically: SafeClaw isolated on **`:8443`** (nginx IP-allow-list admin listener reusing the Brookhaven cert); onboarding behind Caddy on `:8080`. Brookhaven owns 80/443. | **One Cloudflare named tunnel**, two hostnames: `safeclaw-<CLIENT>` → Console `:8899`, `hermes-<CLIENT>` → Hermes dash `:9119`. Hermes ingress **must** set `originRequest.httpHostHeader: localhost` (else 400 Invalid Host). `--protocol http2` to avoid QUIC orphans. | **No reverse proxy, no host TLS, no open ports.** Cloudflare terminates TLS off-box; nothing is published on the box's public interface. Simpler and arguably safer (no listener surface), but adds a Cloudflare dependency + named-tunnel setup. |
| **Secrets handling** | `suffolk.env` (gitignored) on the box; container env injection via Compose; Composio holds OAuth tokens off-box. | `/root/.hermes/.env` written at **`0600`** by the Console; per-profile `.env` files; Composio still holds OAuth off-box; UI basic-auth pass in `/opt/safeclaw-ui/.uipass`. Composio Gmail entry (url + `x-api-key` header) written **directly into each profile's `config.yaml`** (because `hermes mcp add --url` can't attach headers). | **Equivalent secrecy posture**, different mechanics. Both keep OAuth at Composio. orgo spreads secrets across profile `.env`s + `config.yaml`; file perms (`0600`) matter more without container boundaries. |
| **Ops / monitoring** | Docker restart policies + healthchecks; `docker compose restart hermes-reader` to recycle the stale stdio MCP (~8h); daily 4 AM restart cron recommended; verify Brookhaven `/health` after every change (**PRIME DIRECTIVE**). | tmux watchdog (30s loop) curl-checks + relaunches; **clock re-sync from the Cloudflare `Date` header** (suspend/resume drift breaks TLS); `pkill -x cloudflared` (never `-f`, it kills your own `/bash` command). | **Self-healing moves from Docker to a bespoke supervisor.** orgo gains clock-drift correction (a real orgo-specific need); loses Docker's declarative health/restart semantics. |

---

## 2. What was simplified — the honest cost/benefit ledger

### What the orgo path GAINS

- **No Docker / no Compose overhead.** A 4 GB box can't fit Docker + the full stack; native is the only thing that fits the old box, and even on the 16 GB `mark-agent` it stays leaner (no daemon, no images, no bridge networking).
- **Faster deploys.** `git clone`, `pip install flask pyyaml requests`, a Node 20 tarball, `gbrain init`, a few `hermes` commands, five tmux sessions, one tunnel. No image builds, no `TARGETARCH` cross-compile traps, no golden-snapshot dance.
- **Profiles-based trust split is legible.** "The actor profile is the only one with the Telegram token / the draft tools" is a one-line config fact, easy to audit, easy to reason about. No need to read a 20 KB compose file to see the boundary.
- **Always-on, no host-Ollama embeddings daemon to babysit.** PGLite no-embedding removes the whole `172.17.0.1:11434` host-Ollama bind + systemd drop-in.
- **"Dreaming" becomes possible as a Hermes cron** (built-in scheduler) — once an embedding key is wired — giving nightly 11-phase brain maintenance the VPS box never actually ran either. (Net-new capability, not a regression, *if* we add the embedding key.)
- **No public listener surface on the box.** Cloudflare named tunnel means no nginx/Caddy, no `:8443`/`:8080` ports, nothing bound to the public interface.

### What the orgo path DROPS (and the cost)

- **Container-level isolation of the trust split.** ⚠️ **This is the security-relevant delta.** On the VPS, reader and actor are **separate containers** on a Docker bridge; a compromise of the reader process cannot trivially read the actor's filesystem/env. On orgo, both profiles are **processes under the same `root` user on one box** — the boundary is `HERMES_HOME` + allowlist config, not a kernel/cgroup namespace. The *tool* boundary (reader literally has no send tool) still holds — that is the core defense and it is intact — but **lateral movement after an RCE is easier** on orgo because there's no container wall. Mitigations to note: run profiles under separate unix users if/when orgo allows it; keep per-profile `.env` at `0600`; never put the actor's send tokens where the reader process can read them.
- **Compose reproducibility / declarative topology.** The compose file *was* the spec — one artifact described every service, network, port, and restart policy. orgo replaces it with imperative `/bash` steps + a bespoke watchdog. Drift between "what the runbook says" and "what's actually running in tmux" is now a real risk; the `ORGO-CLIENT-TEMPLATE.md` runbook is the only spec.
- **Postgres + pgvector + embeddings.** PGLite no-embedding means **no semantic/vector search** and **`gbrain dream`'s embed phase can't run** without bolting on an external embedding key (Ollama Cloud has **no** `/v1/embeddings` — must use OpenRouter/OpenAI). Recall quality is reduced to non-embedding retrieval until that's fixed.
- **`postgrest` / `tasks-api` / `reflector`** platform-tier services. If any client workflow depended on the task queue or the weekly reflector cron, those have no orgo-native equivalent yet.

### Where the trust split is genuinely WEAKER on orgo

State it plainly for the decision record: **profiles are config-level isolation, not container-level isolation.** The injection defense ("the agent that reads untrusted email has no tool that can send") is preserved — that's the EchoLeak-class defense and it does not regress. What regresses is **defense-in-depth against post-compromise lateral movement**: two containers > two profiles under one user. For a single-tenant, single-user box behind a Cloudflare tunnel with no public ports, this is an acceptable trade — but it is a real reduction and the owner is signing off on it.

### VPS-only strengths being PORTED BACK into orgo (not lost)

- **The Slack MCP** (`mcp-tools/slack-api`, `SLACK_MCP_MODE` reader/actor **tool-allowlist** split, the real `manifest.json` scopes, and `docs/SLACK-APP-WALKTHROUGH.md`) → ported into the orgo template, replacing the Console's token-only Slack panel. **Note:** the MCP is REST-only (`@slack/web-api`, reads only `SLACK_BOT_TOKEN`); there is **no Socket Mode to port**. If real-time Slack presence is wanted, PR 2 builds it as net-new work.
- **The onboarding installer** (`onboarding/` Flask wizard + `CUSTOMER-ONBOARDING.md` + its test suite) → its hardening and customer-walkthrough logic folded into the SafeClaw Console flow.

So "simplified" is accurate for the **runtime**, but the **feature surface** is being kept at parity (Slack, setup UX) by porting — not by dropping.

---

## 3. Migration plan — make orgo-native + Hermes profiles the MAIN deployment

Goal: `Vasanth19/safeclaw` `main` becomes **orgo-first**; the Docker/VPS path becomes a maintained-but-legacy track for the existing Suffolk/Hoover clients; nothing breaks Suffolk's in-flight checkout.

### 3.1 Repo state today (verified `git status --porcelain -uall`)

Actual untracked tree (verbatim, 2026-06-01) — these MUST be committed for orgo to be a real, reproducible deployment:

```
?? .claude/knowledge/decisions/gemma-on-suffolk-vps-not-viable.md
?? .claude/knowledge/decisions/safeclaw-ingest-working-config.md
?? .claude/knowledge/gotchas/hermes-compression-off-causes-quadratic-tokens.md
?? .claude/knowledge/gotchas/ollama-cloud-models-and-limits.md
?? .claude/knowledge/gotchas/openclaw-ollama-concurrency-conflict.md
?? .claude/knowledge/gotchas/slack-native-mcp-goes-stale-after-8h.md
?? .claude/knowledge/patterns/hermes-credential-pool-multi-key.md
?? .claude/scheduled_tasks.lock                              # do NOT commit (transient lock — gitignore it)
?? dashboard-plugins/safeclaw-connections/README.md
?? dashboard-plugins/safeclaw-connections/dashboard/manifest.json
?? dashboard-plugins/safeclaw-connections/dashboard/plugin_api.py
?? dashboard-plugins/safeclaw-connections/src/index.js
?? orgo/INSTALL-CHECKLIST.md
?? orgo/ORGO-CLIENT-TEMPLATE.md
?? orgo/ORGO-DEPLOY.md
?? orgo/VPS-VS-ORGO-DEVIATIONS.md                            # this doc
?? orgo/access/Caddyfile.example
?? orgo/access/README.md
?? orgo/access/cloudflared-config.yml.example
?? orgo/client.env.example
?? orgo/docker-compose.brain.yml
?? orgo/provision-client.py
?? orgo/setup/apply.py
?? safeclaw-ui/app.py
?? safeclaw-ui/requirements.txt
?? safeclaw-ui/templates/index.html
?? scripts/render-hermes-config.py
?? skills/README.md
?? skills/slack-to-gdrive/SKILL.md
```

**Note on two files commonly mislabelled "legacy":**

- `scripts/render-hermes-config.py` is **not** a docker-compose renderer and is **not** Docker-specific. Per its own docstring it is a **connections-registry → Hermes agent-config renderer**: it reads the connections registry owned by the `safeclaw-connections` dashboard plugin and inserts the generated MCP-server entries into a Hermes `config.yaml` as TEXT (preserving comments + the `&composio_headers` anchor), writing to `/opt/data/config.yaml`. It mirrors `dashboard-plugins/safeclaw-connections/dashboard/plugin_api.py::_mcp_snippet`. It is **deployment-agnostic, used at provision time** — the orgo profiles *also* need MCP entries written into `config.yaml`, so this may be directly reusable by the orgo path.
- `dashboard-plugins/safeclaw-connections/` is the **connections-registry + Hermes-config renderer** plugin (same provision-time role), not a "legacy Docker provisioning path."

**Decide before filing either as legacy:** confirm whether `orgo/ORGO-CLIENT-TEMPLATE.md` / `orgo/setup/apply.py` reuse `render-hermes-config.py`. If they do (likely — orgo still needs Composio MCP entries in `config.yaml`), it stays canonical and is **not** moved to `docs/vps-legacy/` in PR 3.

### 3.2 Docs: canonical vs legacy

**Become canonical (orgo-first):**
- `orgo/ORGO-CLIENT-TEMPLATE.md` — the single source of truth for new deploys (already declares it supersedes the Docker path).
- `safeclaw-ui/` Console docs.
- `ARCHITECTURE.md` — **keep, but update** §3 "Container topology" to add an orgo-native topology section (tmux sessions, profiles, tunnel) alongside the Docker one, and update §2.3 to note the profile-based enforcement + the container-vs-profile isolation caveat from §2 here.
- `docs/SLACK-APP-WALKTHROUGH.md` — stays canonical (it's deployment-agnostic OAuth setup; referenced by the Slack port-in).

**Move to `docs/vps-legacy/` (kept for Suffolk/Hoover, clearly marked legacy):**
- `INSTALL.md`, `DEPLOY-RUNBOOK.md`, `HOSTINGER-DEPLOY.md`, `FIRST-RUN.md`
- `docker-compose.yml` and the `docker/` build context, `orgo/docker-compose.brain.yml`, `orgo/ORGO-DEPLOY.md`, `orgo/provision-client.py`
- `CUSTOMER-ONBOARDING.md` (until/unless its content is fully folded into the Console flow — then it becomes a Console doc)

Keep `SUFFOLK-DEPLOYMENT-GUIDE.md`, `SUFFOLK-DEPLOY-PLAN.md`, `HOOVER-DEPLOYMENT-GUIDE.md`, and `CLIENT-DEPLOYMENT-PLAYBOOK.md` where they are — they are live client runbooks. Add a one-line banner to each: *"VPS/Docker track — for orgo deploys see `orgo/ORGO-CLIENT-TEMPLATE.md`."*

### 3.3 What `README.md` and `CLAUDE.md` should say after the switch

**`README.md`:**
- One-line product statement (unchanged): SafeClaw = Hermes reader/actor trust split + GBrain.
- **"Deploy" section reordered:** orgo-native is the **default/recommended** path → link `orgo/ORGO-CLIENT-TEMPLATE.md`. A second "Legacy: self-hosted Docker (VPS)" subsection → link `docs/vps-legacy/`.
- A short "Two runtimes, one product" note explaining the trust split is the same; runtime differs (Docker vs tmux), and the isolation caveat from §2.
- Update the architecture diagram/links to point at both topologies in `ARCHITECTURE.md`.

**`CLAUDE.md`:**
- Replace the "Active work — Suffolk deployment" lead with a **"Default deployment = orgo-native (`orgo/ORGO-CLIENT-TEMPLATE.md`)"** lead.
- Keep the **PRIME DIRECTIVE / Suffolk** block (Brookhaven coexistence) — but file it under a "Legacy VPS clients (Suffolk, Hoover)" heading.
- Keep the **branch caveat** (below) verbatim — it's load-bearing.
- Quality checks: keep the Docker compose validation for the legacy path, add the orgo native checks (`python3 -m py_compile safeclaw-ui/app.py`, `bash -n` for shell, `bash scripts/smoke-brain.sh`).

### 3.4 Branch strategy (the Suffolk exception is sacred)

- `main` becomes **orgo-first** (canonical orgo runbook + Console + committed dirs).
- **`feat/safeclaw-brain-gbrain` stays open and is NOT deleted.** Suffolk's `/opt/safeclaw` tracks this branch. **Do NOT re-point Suffolk to `main`.** Restructuring docs on `main` must not force Suffolk to pull doc moves that would confuse its in-place checkout — keep the Suffolk-relevant runbooks reachable on the branch it tracks (cherry-pick/merge only the fixes Suffolk needs, never the wholesale doc relocation, until Suffolk is intentionally migrated).
- Hoover tracks `main` already (fresh box). When `main` flips orgo-first, **Hoover's VPS/Docker instance must keep working** — that's exactly why the Docker docs stay maintained under `docs/vps-legacy/` rather than deleted, and why `docker-compose.yml` is moved-not-removed.
- After any future squash-merge to `main`, follow the repo's squash-merge hygiene (delete merged feature branches with `-D` + remote delete) — **except** `feat/safeclaw-brain-gbrain`, which is deliberately retained for Suffolk.
- **Cross-doc cleanup (non-blocking):** `SUFFOLK-DEPLOYMENT-GUIDE.md` line ~109 still says PR #1 is "not merged," which contradicts `CLAUDE.md` + `CLIENT-DEPLOYMENT-PLAYBOOK.md` (merged to `main` 2026-05-26) — the premise this migration plan relies on. The Suffolk exception itself is correct; only that one stale line should be fixed in the Suffolk guide so it stops contradicting the merged-to-main state.

### 3.5 What stays maintained for legacy VPS clients

- `docker-compose.yml` + `docker/` build + `INSTALL.md`/`DEPLOY-RUNBOOK.md`/`HOSTINGER-DEPLOY.md`/`FIRST-RUN.md` (relocated under `docs/vps-legacy/`, still working).
- The `~8h stale stdio MCP` restart pattern (`docker compose restart hermes-reader` + 4 AM cron) for Suffolk; the **same gotcha applies to orgo** but via the watchdog.
- Suffolk's `:8443` nginx admin-listener teardown notes and the **never run stock `provision-vps.sh` on Suffolk** warning (it installs Caddy on 80/443 + `ufw --force reset` — would nuke Brookhaven).

### 3.6 Concrete ordered PR plan

| PR | Title | Contents | Risk / gate |
|---|---|---|---|
| **PR 1** | `chore: commit orgo-native deployment artifacts` | Commit the full untracked set (see §3.1): **`orgo/`** — all of `ORGO-CLIENT-TEMPLATE.md`, `ORGO-DEPLOY.md`, `INSTALL-CHECKLIST.md`, `VPS-VS-ORGO-DEVIATIONS.md`, `access/` (Caddyfile.example, cloudflared-config.yml.example, README.md), `setup/apply.py`, `client.env.example`, `docker-compose.brain.yml`, `provision-client.py`; **`safeclaw-ui/`** (app.py, requirements.txt, templates/); **`skills/`** (README.md, slack-to-gdrive/SKILL.md); **`dashboard-plugins/safeclaw-connections/`**; **`scripts/render-hermes-config.py`**; and the **7 `.claude/knowledge/{decisions,gotchas,patterns}` files** (committed as knowledge artifacts). Add `.claude/scheduled_tasks.lock` to `.gitignore` (confirmed **not** yet ignored — `git check-ignore` exit 1). **No doc moves yet** — PR 3's later relocations (`orgo/ORGO-DEPLOY.md`, `orgo/provision-client.py`, `orgo/docker-compose.brain.yml`) operate on files this PR commits, so they must land here first. | Pure addition; nothing existing breaks. Verify `python3 -m py_compile` on `safeclaw-ui/app.py`, `scripts/render-hermes-config.py`, `orgo/setup/apply.py`, `orgo/provision-client.py` (all confirmed clean) + `bash -n` on shell scripts. **Confirm no secrets** committed — scan found placeholders only (`__FILL_IN__`, `xoxb-…`); `orgo/client.env.example` ends in `.example` so it is **not** caught by the `*.env` ignore and commits correctly. |
| **PR 2** | `port: Slack mode-split MCP + onboarding hardening into orgo template` | Wire `mcp-tools/slack-api` (`SLACK_MCP_MODE` reader/actor **tool-allowlist** split — the verified, real strength) + `docs/SLACK-APP-WALKTHROUGH.md` into `orgo/ORGO-CLIENT-TEMPLATE.md` (replace Console token-only Slack panel). The MCP reads only `SLACK_BOT_TOKEN` (REST via `@slack/web-api`); **drop the unused `SLACK_MCP_BOT_TOKEN` from `orgo/client.env.example`**. Add watchdog step for the ~8h Slack-MCP restart. Fold onboarding-wizard hardening into the Console flow. **Socket Mode is net-new, not a port** — the existing MCP has none; if real-time presence is wanted, this PR (or a follow-up) must BUILD it (add `@slack/socket-mode`/Bolt, only the actor opening the connection). Treat that as additive scope, not parity restoration. | Feature parity restoration for the tool-split; net-new for Socket Mode (if pursued). Gate: a dry-run of the Slack walkthrough against a test workspace; confirm the reader profile's allowlist excludes `slack_send_message`/`slack_upload_file`. |
| **PR 3** | `docs: restructure to orgo-first; relocate Docker path to docs/vps-legacy/` | Move `INSTALL.md`, `DEPLOY-RUNBOOK.md`, `HOSTINGER-DEPLOY.md`, `FIRST-RUN.md`, `docker-compose.yml`, `docker/`, `orgo/ORGO-DEPLOY.md`, `orgo/provision-client.py`, `orgo/docker-compose.brain.yml` → `docs/vps-legacy/`. Add legacy banners to Suffolk/Hoover runbooks. **Do this on `main` only; do NOT propagate the relocation onto `feat/safeclaw-brain-gbrain`.** | Highest blast radius for tooling that hard-codes paths. Gate: grep the repo for references to moved files and fix links. Verify Suffolk/Hoover runbooks still resolve. |
| **PR 4** | `docs: orgo-first README + CLAUDE.md; ARCHITECTURE orgo topology` | Reorder `README.md` (orgo default, Docker legacy). Rewrite `CLAUDE.md` lead (orgo default; Suffolk under "legacy VPS clients"; keep PRIME DIRECTIVE + branch caveat). Add orgo-native topology + profile-isolation caveat to `ARCHITECTURE.md` §2.3/§3. | Doc-only. Gate: re-read CLAUDE.md branch caveat survives verbatim. |
| **PR 5** | `feat: orgo correctness fixes` | Normalize template model `kimi-k2.5` → **glm-4.7**; register `gbrain dream` as a Hermes cron (with an OpenRouter/OpenAI embedding key); register ingest as a Hermes cron with the working token-economy config; update Step 0 to stop narrating the free-account failure as current (target the 16 GB always-on `mark-agent`, not the old 4 GB Mark box). | Operational hardening. Gate: a full deploy of the template top-to-bottom against a fresh box in Jake's paid workspace, verified end-to-end. |

PRs 1–4 are sequential (each builds on the prior); PR 5 can land any time after PR 1.

---

## 4. Decision record

**Decision:** Approving this document means the owner is deciding that **orgo-native + Hermes profiles becomes the MAIN/default SafeClaw deployment**, the Docker/VPS path becomes a **maintained legacy track** for existing clients (Suffolk, Hoover), and the repo is restructured per §3.

**What is explicitly accepted by approving:**
1. **A weaker isolation tier for the trust split** — profiles (config/process isolation under one user) instead of containers (separate filesystems/namespaces on a Docker bridge). The injection defense (reader has no send tool) is preserved; defense-in-depth against post-RCE lateral movement is reduced. (§2)
2. **No embeddings by default** on orgo (PGLite no-embedding) until an external embedding key is wired — reducing recall quality and blocking `gbrain dream`'s embed phase until PR 5. (§2, §3.6)
3. **A dependency on Cloudflare** (named tunnel) and on **orgo's always-on paid workspace** (auto_stop=0) — a free/Hacker account silently breaks everything (15-min suspend, clock drift, dead tunnels).
4. **A bespoke watchdog** as the reliability substrate in place of Docker restart policies, and the operational gotchas that come with orgo `/bash` (job reaping, `pkill -x`, QUIC orphans, clock drift).
5. **The Suffolk exception holds:** its VPS keeps tracking `feat/safeclaw-brain-gbrain`; the doc relocation does **not** propagate to that branch; Brookhaven is never disturbed.

**Reversibility:** **High.** Nothing is deleted — the Docker path is *relocated and kept maintained*, not removed, so reverting to "Docker is canonical" is a doc/README reorder, not a rebuild. Suffolk and Hoover continue running on Docker untouched throughout. The only one-way-ish item is the Slack-MCP/onboarding *port-in* (PR 2), which is purely additive (orgo gains the VPS's better Slack); it can be left in place even if the canonical path were reverted. The single hard-to-reverse risk is **operational lock-in to orgo's paid workspace** — but that is a billing decision (Jake already owns the Scale workspace), not a code decision.

**Recommendation:** Proceed. The runtime simplification is real and justified for single-tenant single-user boxes; the two genuine regressions (container isolation, embeddings) are bounded and documented; and the two VPS strengths (Slack, onboarding) are preserved by porting rather than dropped. Land PR 1 immediately (it's pure, secret-free addition), then PRs 2–5 in order.
