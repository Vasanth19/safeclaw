---
date: 2026-05-22
tags: [gbrain, docker, deployment, gotchas]
related-services: [safeclaw-brain]
source: session
---

# GBrain (v0.37.11.0) deployment gotchas

## Context
Found while containerizing GBrain as the `safeclaw-brain` service and smoke-testing it locally.

## Details

1. **`gbrain auth create <name>` arg-parse BUG.** With no `--takes-holders` flag, `takesIdx = -1`, so `rest[takesIdx+1]` resolves to `rest[0]` (the name), which the positional-finder then *excludes* → empty name → exits with usage, no token. **Workaround: always pass `--takes-holders world,garry,brain`.** (src/commands/auth.ts:393)

2. **Compile must match image arch.** The Dockerfile must NOT hardcode `--target=bun-linux-x64`. On arm64 hosts the x86 binary fails at runtime with `Could not open '/lib64/ld-linux-x86-64.so.2'`. Use buildkit's `ARG TARGETARCH` → `amd64`→`bun-linux-x64`, `arm64`→`bun-linux-arm64`.

3. **`gbrain init` defaults to PGLite even with DATABASE_URL set.** To use Postgres (required for static bearer tokens — the `access_tokens` table is Postgres-only), init with `--supabase --non-interactive --url "$DATABASE_URL"`. (`--supabase` selects the Postgres engine; works against any plain Postgres, not just Supabase.)

4. **Pin a PUBLISHED commit, not a local one.** Upstream `garrytan/gbrain` doesn't tag releases. The local checkout HEAD `fe3499e` was an unpushed local merge — cloning it in Docker fails with `reference is not a tree`. The published v0.37.11.0 is `d0d0e2a` on origin/master. Verify with `git branch -r --contains <sha>`.

5. **query/search vs get_page visibility.** `query`/`search` filter results by the token's `takes_holder` allow-list; a page written via `put_page` may not be visible to a reading token even though it's embedded (stats showed 1/1/1). `get_page` by slug always works. OPEN: determine GBrain's holder model so the actor's semantic search returns written pages. (auth help: "MCP-bound calls to takes_list / takes_search / query filter by this")

6. **OrbStack `StorageFull`.** OrbStack's VM crashes to "Stopped" with btrfs/`No space left on device` when the *Mac host* disk is full (was 98%). Fix = free host space; OrbStack's own data dir is tiny.

## Example
Postgres init in the entrypoint:
```bash
gbrain init --supabase --non-interactive --url "${DATABASE_URL}" \
  --embedding-model ollama:nomic-embed-text --embedding-dimensions 768
# token mint (note the required --takes-holders):
gbrain auth create reader --takes-holders world,garry,brain
```
