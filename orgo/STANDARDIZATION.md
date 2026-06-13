# Orgo box standardization baseline

> The canonical runtime every orgo client box should match, plus an audit of the
> live fleet as of 2026-06-13. Use this to bring a drifted box back in line and as
> the spec for the clean template.

## Canonical baseline

| Dimension | Standard |
|-----------|----------|
| Brain engine | Postgres + pgvector, supervised by `postgres-brain` (never PGlite) |
| Embeddings | OpenRouter `openai/text-embedding-3-small` (1536 dim) |
| Brain role | `CREATE ROLE brain LOGIN SUPERUSER BYPASSRLS` (BYPASSRLS is required) |
| Gateway | one supervised `hermes-gateway-actor`; reader profile kept for ingestion only |
| Reader profile MCP | **Gmail + gbrain only** (lean, to avoid cold start aborts) |
| Actor cron timeout | `cron.script_timeout_seconds: 1800` in the actor config |
| Email ingest | `email-ingest.sh` registered hourly (`15 * * * *`) |
| Calendar ingest | `calendar-sync.sh` registered daily (`30 5 * * *`) where Calendar is connected |
| Admin bootstrap | durable `GBRAIN_ADMIN_BOOTSTRAP_TOKEN` in `/opt/brain/.env` |

## Fleet audit, 2026-06-13

Aligned across Travis / Matt / Elise: Postgres engine, `hermes-gateway-actor` +
`postgres-brain` supervised, cron timeout 1800, email-ingest hourly, calendar-sync
daily.

Drift still to resolve (needs a decision before acting):

1. **gbrain version is not pinned.** Travis `0.42.36.0`, Matt `0.42.26.0`, Elise
   `0.42.42.0`. Matt is the furthest behind. Pin the fleet to one version. Upgrading
   gbrain is **not** safe to automate blindly (schema migrations, fragile brains);
   it should be done per box with a verified backup, which is the motivation for the
   controlled update scheduler (see the meeting roadmap).
2. **Reader profile is inconsistent.** Travis and Matt carry GHL in the reader
   (`gbrain + gmail + ghl`); Elise is clean (`gbrain + gmail`). GHL is a local stdio
   MCP so it does not cause the remote cold start problem, but the reader should be
   standardized one way. Recommend: keep the reader to Gmail + gbrain and put GHL in
   the actor only.
3. **Brain serving topology differs.** Elise serves the brain via a supervised
   `safeclaw-brain` program plus the full `safeclaw-console` / `safeclaw-tunnel`
   stack; Travis and Matt do not run `safeclaw-brain` and instead expose portal
   helpers (`portal-brief`, `portal-tasks-sync`, `ghl-mcp`). Decide which topology is
   canonical and converge.

## Bringing a box back to baseline

1. Engine: confirm `engine: postgres` in `/opt/brain/.gbrain/config.json`; if PGlite,
   migrate (role with BYPASSRLS, `gbrain init --url ... --embedding-model ...`).
2. Reader profile: trim `/root/.hermes/profiles/reader/config.yaml` to Gmail + gbrain.
3. Actor config: ensure `cron.script_timeout_seconds: 1800`.
4. Crons: `email-ingest` hourly, `calendar-sync` daily; remove ad hoc one offs unless
   intentionally per box.
5. Supervisor: `postgres-brain` and `hermes-gateway-actor` present and running.
