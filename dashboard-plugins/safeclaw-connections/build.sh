#!/usr/bin/env bash
# Build the safeclaw-connections dashboard bundle.
#
# The UI is "pure-SDK" — it imports nothing from npm (React comes from
# window.__HERMES_PLUGIN_SDK__), so the bundle IS the source. `dist/` is
# gitignored, so a fresh clone has no bundle until this runs. Deploy/provision
# must invoke this once (and after any src/index.js edit) so the dashboard's
# manifest `entry: dist/index.js` resolves.
#
# If esbuild is available we minify; otherwise we copy verbatim — both produce a
# valid bundle.
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
src="$here/src/index.js"
out="$here/dashboard/dist/index.js"
mkdir -p "$(dirname "$out")"

if command -v esbuild >/dev/null 2>&1; then
  esbuild "$src" --bundle --format=iife --minify --outfile="$out"
  echo "built (esbuild --minify) → $out"
else
  cp "$src" "$out"
  echo "built (verbatim copy; esbuild not found) → $out"
fi

node --check "$out"
echo "ok: $(wc -c < "$out") bytes"
