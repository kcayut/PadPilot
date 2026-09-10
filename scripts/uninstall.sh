#!/usr/bin/env bash
# Remove only this checkout's integrations; recoverable removals use Trash.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
[[ "${1:-}" == "" || "${1:-}" == "--purge" ]] || { echo "Usage: $0 [--purge]"; exit 1; }
if [[ "${1:-}" == "--purge" ]]; then
    exec python3 "$SCRIPT_DIR/manage_app.py" --uninstall --purge
else
    exec python3 "$SCRIPT_DIR/manage_app.py" --uninstall
fi
