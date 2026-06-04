#!/usr/bin/env bash
# Build the safeclaw-settings dashboard bundle.
#
# Pure-SDK UI (no npm imports — React comes from window.__HERMES_PLUGIN_SDK__),
# so the bundle IS the source. `dist/` is gitignored; a fresh clone has no
# bundle until this runs. Deploy/provision must invoke it once (and after any
# src/index.js edit) so the manifest's `entry: dist/index.js` resolves.
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
