#!/usr/bin/env bash
# Native menu + Python core. No pip or third-party menu host required.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
[[ "$(uname -s)" == Darwin ]] || { echo "PadPilot requires macOS 14 or later."; exit 1; }
[[ "${1:-}" == "" || "${1:-}" == "--yes" || "${1:-}" == "-y" ]] || { echo "Usage: $0 [--yes]"; exit 1; }
PYTHON_BIN="$(command -v python3)" || { echo "Install Python 3.10+ with Tk support first."; exit 1; }
"$PYTHON_BIN" -c 'import sys; assert sys.version_info >= (3, 10), "Python 3.10+ required"; import tkinter'
xcrun --find swiftc >/dev/null 2>&1 || { echo "Install Apple Command Line Tools: xcode-select --install"; exit 1; }

if [[ ! -d /Applications/BetterDisplay.app && ! -d "$HOME/Applications/BetterDisplay.app" ]]; then
    INSTALL_CHOICE=n
    if command -v brew >/dev/null 2>&1; then
        if [[ "${1:-}" == "--yes" || "${1:-}" == "-y" ]]; then
            INSTALL_CHOICE=y
        else
            read -r -p "Install BetterDisplay with Homebrew? (y/N): " INSTALL_CHOICE
        fi
        if [[ "$INSTALL_CHOICE" =~ ^[Yy]$ ]]; then
            brew install --cask betterdisplay
        fi
    fi
    [[ -d /Applications/BetterDisplay.app || -d "$HOME/Applications/BetterDisplay.app" ]] || {
        echo "Install BetterDisplay, then rerun this installer."; exit 1;
    }
fi
exec "$PYTHON_BIN" "$SCRIPT_DIR/manage_app.py"
