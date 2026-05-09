#!/usr/bin/env bash
# build-images.sh — build all SafeClaw container images locally.
#
# Tags both :<VERSION> and :latest for every image. Does NOT push.
# Use scripts/push-images.sh to push to GHCR after verifying.
#
# Usage:
#   ./scripts/build-images.sh [VERSION]
#
# Default VERSION = 1.0.

set -euo pipefail

VERSION="${1:-1.0}"
REGISTRY="ghcr.io/vasanth19"

# Resolve repo root from this script's location so the script can be invoked
# from any cwd without breaking COPY paths.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." >/dev/null 2>&1 && pwd)"

cd "${REPO_ROOT}"

log() {
    printf '\n\033[1;36m==> %s\033[0m\n' "$*"
}

build_image() {
    local name="$1"
    local context="$2"
    local dockerfile="$3"

    log "Building ${REGISTRY}/safeclaw-${name}:${VERSION}"
    docker build \
        --tag "${REGISTRY}/safeclaw-${name}:${VERSION}" \
        --tag "${REGISTRY}/safeclaw-${name}:latest" \
        --tag "safeclaw/${name}:${VERSION}" \
        --tag "safeclaw/${name}:latest" \
        --file "${dockerfile}" \
        "${context}"
}

# ─── Pre-flight checks ──────────────────────────────────────────────────────
if ! command -v docker >/dev/null 2>&1; then
    echo "build-images.sh: docker not found in PATH" >&2
    exit 1
fi

if [ ! -d "vendor/hermes-agent" ]; then
    echo "build-images.sh: vendor/hermes-agent missing — git submodule update?" >&2
    exit 1
fi

# ─── 1. SafeClaw Hermes ─────────────────────────────────────────────────────
# Build context = repo root (Dockerfile reaches into vendor/hermes-agent/ AND
# docker/ from a single context).
build_image "hermes" "." "docker/Dockerfile.safeclaw-hermes"

# ─── 2. Embedder ────────────────────────────────────────────────────────────
build_image "embedder" "services/embedder" "services/embedder/Dockerfile"

# ─── 3. Brain API MCP ───────────────────────────────────────────────────────
build_image "brain-api" "mcp-tools/brain-api" "mcp-tools/brain-api/Dockerfile"

# ─── 4. Tasks API MCP ───────────────────────────────────────────────────────
build_image "tasks-api" "mcp-tools/tasks-api" "mcp-tools/tasks-api/Dockerfile"

# ─── 5. Slack API MCP ───────────────────────────────────────────────────────
build_image "slack-api" "mcp-tools/slack-api" "mcp-tools/slack-api/Dockerfile"

# ─── Summary ────────────────────────────────────────────────────────────────
log "Build complete. Images:"
docker images \
    --format '  {{.Repository}}:{{.Tag}}\t{{.Size}}\t{{.CreatedSince}}' \
    | grep -E '(safeclaw|safeclaw-)' \
    | sort -u
