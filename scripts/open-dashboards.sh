#!/usr/bin/env bash
# SafeClaw — open control surfaces in the default browser
#
# Usage:
#   bash scripts/open-dashboards.sh
#
# Opens:
#   http://localhost:8080/dashboard  (SafeClaw Dashboard)
#   http://localhost:9119            (Hermes Mission Control)

set -euo pipefail

open_url() {
    local url="$1"
    case "$(uname -s)" in
        Darwin)
            open "$url"
            ;;
        Linux)
            if command -v xdg-open >/dev/null 2>&1; then
                xdg-open "$url"
            else
                echo "Cannot auto-open browser on this Linux system."
                echo "  Please open manually: $url"
            fi
            ;;
        *)
            echo "Unknown OS. Please open manually: $url"
            ;;
    esac
}

echo "Opening SafeClaw control surfaces..."
sleep 1

open_url "http://localhost:8080/dashboard"
open_url "http://localhost:9119"

echo "Done. If these don't load, make sure 'docker compose up -d' is running."
