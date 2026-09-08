#!/usr/bin/env bash
# PadPilot Safe Uninstallation Script
set -e

PLIST_DEST="$HOME/Library/LaunchAgents/com.padpilot.daemon.plist"
SWIFTBAR_PLUGIN="$HOME/Library/Application Support/SwiftBar/plugins/padpilot.30s.py"
APP_SUPPORT="$HOME/Library/Application Support/PadPilot"
LOG_DIR="$HOME/Library/Logs/PadPilot"

PURGE=false
if [[ "$1" == "--purge" ]]; then
    PURGE=true
fi

echo "=================================================="
echo "          🛑 PadPilot Uninstaller"
echo "=================================================="

# 1. Unload and remove LaunchAgent & stop daemon process
if [[ -f "$PLIST_DEST" ]]; then
    echo "Unloading LaunchAgent..."
    launchctl unload "$PLIST_DEST" 2>/dev/null || true
    rm -f "$PLIST_DEST"
    echo "  [✓] Removed LaunchAgent plist"
fi

# Ensure all background daemon processes are terminated
pkill -f "bin/padpilotd" 2>/dev/null || true
pkill -f "padpilotd" 2>/dev/null || true
echo "  [✓] Ensured background daemon processes are terminated"

# 2. Remove SwiftBar plugin symlink & refresh
if [[ -L "$SWIFTBAR_PLUGIN" || -f "$SWIFTBAR_PLUGIN" ]]; then
    rm -f "$SWIFTBAR_PLUGIN"
    echo "  [✓] Removed SwiftBar plugin link"
fi

if pgrep -x "SwiftBar" >/dev/null 2>&1 || pgrep -f "SwiftBar.app" >/dev/null 2>&1; then
    open -g "swiftbar://refreshallplugins" 2>/dev/null || true
    echo "  [✓] Refreshed SwiftBar menu bar"
fi

# 3. Handle runtime files
if [[ -d "$APP_SUPPORT/runtime" ]]; then
    rm -rf "$APP_SUPPORT/runtime"
    echo "  [✓] Cleaned up runtime files"
fi

if [[ -S "$APP_SUPPORT/padpilot.sock" ]]; then
    rm -f "$APP_SUPPORT/padpilot.sock"
fi

# 4. Handle Purge
if [ "$PURGE" = true ]; then
    echo "Purging configuration and logs (--purge specified)..."
    rm -rf "$APP_SUPPORT"
    rm -rf "$LOG_DIR"
    echo "  [✓] Purged configuration and logs"
else
    echo ""
    echo "Notice: Configuration, logs, and CLI binary were preserved at:"
    echo "  - $APP_SUPPORT/config.json"
    echo "  - $LOG_DIR"
    echo "  - $HOME/bin/padpilot-cli (if linked)"
    echo "BetterDisplay, SwiftBar, and PadPilotVirtual were also preserved."
    echo "(To completely delete configurations and logs, re-run with: ./uninstall.sh --purge)"
fi

echo ""
echo "PadPilot has been safely uninstalled."
