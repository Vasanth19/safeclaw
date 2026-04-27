#!/usr/bin/env bash
# push-images.sh — push all SafeClaw images to GHCR.
#
# Requires:
#   GH_TOKEN env var (a GitHub PAT with write:packages scope)
#   GH_USERNAME env var (defaults to vasanth19)
#
# Usage:
#   GH_TOKEN=ghp_xxx ./scripts/push-images.sh [VERSION]
#
# Default VERSION = 1.0.

set -euo pipefail

VERSION="${1:-1.0}"
REGISTRY="ghcr.io/vasanth19"
GH_USERNAME="${GH_USERNAME:-vasanth19}"

if [ -z "${GH_TOKEN:-}" ]; then
    echo "push-images.sh: GH_TOKEN env var is required" >&2
    echo "  Generate one at https://github.com/settings/tokens with write:packages scope." >&2
    exit 1
fi

if ! command -v docker >/dev/null 2>&1; then
    echo "push-images.sh: docker not found in PATH" >&2
    exit 1
fi

log() {
    printf '\n\033[1;36m==> %s\033[0m\n' "$*"
}

# ─── Login to GHCR ──────────────────────────────────────────────────────────
log "Logging in to ghcr.io as ${GH_USERNAME}"
echo "${GH_TOKEN}" | docker login ghcr.io --username "${GH_USERNAME}" --password-stdin

# ─── Push each image (both :VERSION and :latest tags) ──────────────────────
push_image() {
    local name="$1"

    for tag in "${VERSION}" "latest"; do
        local image="${REGISTRY}/safeclaw-${name}:${tag}"

        if ! docker image inspect "${image}" >/dev/null 2>&1; then
            echo "push-images.sh: ${image} not found locally — run build-images.sh first" >&2
            exit 1
        fi

        log "Pushing ${image}"
        docker push "${image}"
    done
}

push_image "hermes"
push_image "embedder"
push_image "brain-api"
push_image "tasks-api"

log "Push complete. Images now available at ${REGISTRY}/safeclaw-*:${VERSION}"
