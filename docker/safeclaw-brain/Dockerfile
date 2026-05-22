# syntax=docker/dockerfile:1
# ─── safeclaw-brain — GBrain engine, compiled to a static linux binary ───────
#
# Two stages:
#   1. builder  — oven/bun image; vendors a pinned git clone of the GBrain
#                 source and compiles it to a single static bun-linux-x64
#                 binary via `bun build --compile`.
#   2. runtime  — slim Debian; carries the compiled binary at
#                 /usr/local/bin/gbrain, plus `git` (GBrain repos are
#                 git-backed) and `curl` (healthcheck). entrypoint.sh handles
#                 idempotent init + apply-migrations + serve.
#
# GBRAIN_REF pins the exact source. Upstream (garrytan/gbrain) does NOT tag
# releases — the only tag is an eval baseline — so we pin the commit SHA that
# corresponds to package.json version 0.37.11.0 on the `master` branch.
# Pass --build-arg GBRAIN_REF=<sha-or-branch-or-tag> to override.

ARG BUN_VERSION=1.2
ARG GBRAIN_REF=fe3499e5a184c8e507a30f0bb6ad7f9c7f7c9551

# ─── Stage 1: builder ────────────────────────────────────────────────────────
FROM oven/bun:${BUN_VERSION} AS builder
ARG GBRAIN_REF

# git is needed to vendor the source; ca-certificates for the https clone.
RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /src

# Vendor a pinned clone of the GBrain source. We clone the default branch and
# `git checkout` the ref so this works whether GBRAIN_REF is a tag, a branch,
# or a bare commit SHA (a shallow --branch clone cannot resolve a raw SHA).
RUN git clone https://github.com/garrytan/gbrain.git . \
    && git fetch --depth 1 origin "${GBRAIN_REF}" 2>/dev/null \
       && git checkout FETCH_HEAD \
       || git checkout "${GBRAIN_REF}"

# Install dependencies, then compile the CLI to a single static linux binary.
RUN bun install --frozen-lockfile || bun install
RUN bun build --compile --target=bun-linux-x64 --outfile bin/gbrain-linux-x64 src/cli.ts

# ─── Stage 2: runtime ────────────────────────────────────────────────────────
FROM debian:bookworm-slim AS runtime

# git: GBrain repos are git-backed (the brain home is a git working tree).
# curl: container healthcheck against /health.
# ca-certificates: outbound https (Ollama proxy, etc.).
RUN apt-get update \
    && apt-get install -y --no-install-recommends git curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /src/bin/gbrain-linux-x64 /usr/local/bin/gbrain
RUN chmod +x /usr/local/bin/gbrain

COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

# Brain home — backed by the safeclaw_brain_data volume in compose.
ENV GBRAIN_HOME=/data/safeclaw-brain
WORKDIR /data/safeclaw-brain

EXPOSE 3131

HEALTHCHECK --interval=15s --timeout=5s --retries=5 --start-period=30s \
  CMD curl -fsS http://localhost:3131/health || exit 1

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
