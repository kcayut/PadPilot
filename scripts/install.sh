#!/usr/bin/env bash
# PadPilot Non-Intrusive Installation and Setup Script
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PYTHON_BIN="$(which python3)"

AUTO_INSTALL=false
if [[ "$1" == "--yes" || "$1" == "-y" ]]; then
    AUTO_INSTALL=true
fi

echo "=================================================="
echo "          🚀 PadPilot Installation Setup"
echo "=================================================="
echo "Project Location: $PROJECT_ROOT"
echo "Python Binary:    $PYTHON_BIN"
echo ""

# 1. Dependency Detection
MISSING_DEPS=()

echo "Checking dependencies..."

if [[ -d "/Applications/BetterDisplay.app" ]]; then
    echo "  [✓] BetterDisplay.app found"
else
    echo "  [✗] BetterDisplay.app NOT found"
    MISSING_DEPS+=("betterdisplay")
fi

if which betterdisplaycli >/dev/null 2>&1 || [[ -x "/Applications/BetterDisplay.app/Contents/MacOS/BetterDisplay" ]] || [[ -x "/opt/homebrew/bin/betterdisplaycli" ]]; then
    echo "  [✓] BetterDisplay CLI capability found"
else
    echo "  [✗] betterdisplaycli NOT found"
    MISSING_DEPS+=("betterdisplaycli")
fi

if [[ -d "/Applications/SwiftBar.app" ]]; then
    echo "  [✓] SwiftBar.app found"
else
    echo "  [✗] SwiftBar.app NOT found"
    MISSING_DEPS+=("swiftbar")
fi

echo ""

if [[ ${#MISSING_DEPS[@]} -gt 0 ]]; then
    echo "Missing dependencies detected: ${MISSING_DEPS[*]}"
    if which brew >/dev/null 2>&1; then
        if [ "$AUTO_INSTALL" = true ]; then
            INSTALL_CHOICE="y"
        else
            read -p "Would you like to install missing dependencies via Homebrew? (y/N): " INSTALL_CHOICE
        fi

        if [[ "$INSTALL_CHOICE" =~ ^[Yy]$ ]]; then
            for dep in "${MISSING_DEPS[@]}"; do
                if [[ "$dep" == "betterdisplay" ]]; then
                    echo "Installing BetterDisplay..."
                    brew install --cask betterdisplay
                elif [[ "$dep" == "swiftbar" ]]; then
                    echo "Installing SwiftBar..."
                    brew install --cask swiftbar
                fi
            done
        else
            echo "Skipping automatic installation. Please install missing dependencies manually."
        fi
    else
        echo "Homebrew is not installed. Please install BetterDisplay and SwiftBar manually."
    fi
fi

# 2. Directory Creation
echo ""
echo "Setting up directories..."
mkdir -p "$HOME/Library/Application Support/PadPilot/runtime"
mkdir -p "$HOME/Library/Logs/PadPilot"
mkdir -p "$HOME/Library/LaunchAgents"

# 3. SwiftBar Plugin Setup
echo "Configuring SwiftBar Plugin..."
SWIFTBAR_PLUGINS_DIR="$HOME/Library/Application Support/SwiftBar/plugins"
mkdir -p "$SWIFTBAR_PLUGINS_DIR"
ln -sf "$PROJECT_ROOT/swiftbar/padpilot.30s.py" "$SWIFTBAR_PLUGINS_DIR/padpilot.30s.py"
echo "  [✓] Linked padpilot.30s.py into $SWIFTBAR_PLUGINS_DIR"

# 4. LaunchAgent Setup
echo "Configuring LaunchAgent..."
PLIST_SRC="$PROJECT_ROOT/launchd/com.padpilot.daemon.plist.in"
PLIST_DEST="$HOME/Library/LaunchAgents/com.padpilot.daemon.plist"
LOG_DIR="$HOME/Library/Logs/PadPilot"
mkdir -p "$LOG_DIR"

"$PYTHON_BIN" -c "
import sys
from pathlib import Path
src, dest, py, root, logs = sys.argv[1:6]
template = Path(src).read_text(encoding='utf-8')
output = (template
    .replace('__PYTHON_BIN__', py)
    .replace('__PROJECT_ROOT__', root)
    .replace('__LOG_DIR__', logs))
Path(dest).write_text(output, encoding='utf-8')
" "$PLIST_SRC" "$PLIST_DEST" "$PYTHON_BIN" "$PROJECT_ROOT" "$LOG_DIR"

# Unload previous instance if loaded
launchctl unload "$PLIST_DEST" 2>/dev/null || true
launchctl load "$PLIST_DEST"
echo "  [✓] Loaded LaunchAgent com.padpilot.daemon"

# 5. CLI convenience link
if [[ -d "$HOME/bin" ]]; then
    ln -sf "$PROJECT_ROOT/bin/padpilot-cli" "$HOME/bin/padpilot-cli"
    echo "  [✓] Linked padpilot-cli into $HOME/bin"
fi

echo ""
echo "=================================================="
echo "          🎉 Installation Completed!"
echo "=================================================="
echo "You can now:"
echo "  1. Pair your iPad:       $PROJECT_ROOT/bin/padpilot-cli pair --interactive"
echo "  2. Check status:         $PROJECT_ROOT/bin/padpilot-cli status"
echo "  3. Open SwiftBar:        open -a SwiftBar"
echo "  4. View logs:            $PROJECT_ROOT/bin/padpilot-cli open-log"
echo "=================================================="
