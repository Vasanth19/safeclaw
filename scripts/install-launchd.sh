#!/usr/bin/env bash
# install-launchd.sh — register and start the Hermes launchd daemons.
# Run once after install-local-hermes.sh.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
AGENTS_DIR="$HOME/Library/LaunchAgents"
READER_PLIST="$REPO/launchd/com.safeclaw.hermes-reader.plist"
ACTOR_PLIST="$REPO/launchd/com.safeclaw.hermes-actor.plist"

mkdir -p "$AGENTS_DIR"

for LABEL in com.safeclaw.hermes-reader com.safeclaw.hermes-actor; do
  if launchctl list | grep -q "$LABEL"; then
    echo "==> Unloading existing $LABEL"
    launchctl unload "$AGENTS_DIR/$LABEL.plist" 2>/dev/null || true
  fi
done

echo "==> Copying plists to $AGENTS_DIR"
cp "$READER_PLIST" "$AGENTS_DIR/"
cp "$ACTOR_PLIST"  "$AGENTS_DIR/"

echo "==> Loading reader"
launchctl load -w "$AGENTS_DIR/com.safeclaw.hermes-reader.plist"

echo "==> Loading actor"
launchctl load -w "$AGENTS_DIR/com.safeclaw.hermes-actor.plist"

echo ""
echo "Daemons registered. Check status with:"
echo "  launchctl list | grep safeclaw"
echo ""
echo "Tail logs:"
echo "  tail -f ~/.safeclaw/reader-home/logs/stdout.log"
echo "  tail -f ~/.safeclaw/actor-home/logs/stdout.log"
echo ""
echo "Stop Docker versions:"
echo "  docker compose stop hermes-reader hermes-actor"
echo ""
echo "Update hermes-chat alias in ~/.zshrc:"
echo "  alias hermes-chat='HERMES_HOME=~/.safeclaw/actor-home ~/.safeclaw/hermes-venv/bin/hermes chat'"
