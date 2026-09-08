#!/usr/bin/env python3
"""<xbar.title>PadPilot Menu Bar Controller</xbar.title>
<xbar.version>v1.0</xbar.version>
<xbar.author>PadPilot</xbar.author>
<xbar.desc>Automated display manager for Mac mini M4 + iPad via USB-C Sidecar</xbar.desc>
<xbar.dependencies>python3,BetterDisplay</xbar.dependencies>
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# Paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent
CLI_PATH = PROJECT_ROOT / "bin" / "padpilot-cli"
STATUS_FILE_PRIMARY = Path.home() / "Library" / "Application Support" / "PadPilot" / "runtime" / "status.json"
STATUS_FILE_FALLBACK = Path("/tmp/PadPilot/runtime/status.json")
PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / "com.padpilot.daemon.plist"


def load_status() -> dict:
    target_file = None
    if STATUS_FILE_PRIMARY.exists():
        target_file = STATUS_FILE_PRIMARY
    elif STATUS_FILE_FALLBACK.exists():
        target_file = STATUS_FILE_FALLBACK

    if not target_file:
        return {}
    try:
        with open(target_file, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def main() -> None:
    cli_str = str(CLI_PATH)
    status = load_status()
    autostart_enabled = PLIST_PATH.is_file()
    a_mark = "✓ " if autostart_enabled else "   "

    if not status:
        print("⏸️ PadPilot")
        print("---")
        print("Status: Daemon Not Running | color=orange")
        print(f"Start PadPilot Daemon | bash='{cli_str}' param1=start terminal=false refresh=true")
        print("---")
        print(f"{a_mark}Run Daemon at Login | bash='{cli_str}' param1=autostart param2=toggle terminal=false refresh=true")
        print(f"Refresh | bash='{cli_str}' param1=action param2=refresh terminal=false refresh=true")
        print(f"Open Log | bash='{cli_str}' param1=open-log terminal=false")
        print("---")
        print("Quit SwiftBar | bash='osascript' param1='-e' param2='tell application \"SwiftBar\" to quit' terminal=false")
        return

    icon = status.get("icon", "📱")
    mode = status.get("mode", "automatic")
    details = status.get("status_details", {})
    actual = status.get("actual", {})
    desired = status.get("desired", {})
    runtime = status.get("runtime", {})
    configured_ipad = status.get("configured_ipad", {})

    # Top Bar Display
    print(f"{icon} PadPilot")
    print("---")

    # Status Section
    print("Status | font=bold")
    print(f"Physical Display:     {details.get('physical_display', 'None')}")
    print(f"USB iPad:             {details.get('usb_ipad', 'Not Connected')}")
    print(f"Sidecar:              {details.get('sidecar', 'Disconnected')}")
    print(f"Current Main:         {details.get('current_main', 'None')}")
    v_exists = actual.get("virtual_display_exists", False)
    v_conn = actual.get("virtual_display_connected", False)
    v_desc = "Connected" if v_conn else ("Configured" if v_exists else "Missing")
    print(f"Virtual Fallback:     {v_desc}")
    print("---")

    # Desired vs Actual Section
    print("Desired vs Actual | font=bold")
    print(f"Desired State:        {details.get('desired_role', 'None')}")
    sat_text = details.get("actual_role_satisfied", "")
    sat_color = "green" if "Satisfied" in sat_text else "orange"
    print(f"Actual State:         {sat_text} | color={sat_color}")
    print("---")

    # Reason Section
    print("Reason | font=bold")
    reason_text = details.get("reason", "None")
    # Wrap long reason text into multiple lines for clean menu appearance
    words = reason_text.split(" ")
    lines, current_line = [], []
    for w in words:
        current_line.append(w)
        if len(" ".join(current_line)) > 36:
            lines.append(" ".join(current_line))
            current_line = []
    if current_line:
        lines.append(" ".join(current_line))

    for line in lines:
        print(f"{line} | color=#888888")
    print("---")

    # Mode Section
    print("Mode | font=bold")
    m_auto = "✓ " if mode == "automatic" else "   "
    m_manual = "✓ " if mode == "manual_only" else "   "
    m_prefer = "✓ " if mode == "prefer_ipad" else "   "
    print(f"{m_auto}Automatic | bash='{cli_str}' param1=set-mode param2=automatic terminal=false refresh=true")
    print(f"{m_manual}Manual Only | bash='{cli_str}' param1=set-mode param2=manual_only terminal=false refresh=true")
    print(f"{m_prefer}Prefer iPad | bash='{cli_str}' param1=set-mode param2=prefer_ipad terminal=false refresh=true")
    print("---")

    # Actions Section
    print("Actions | font=bold")
    print(f"Use iPad as Secondary | bash='{cli_str}' param1=action param2=use_ipad_secondary terminal=false refresh=true")
    print(f"Use iPad as Main | bash='{cli_str}' param1=action param2=use_ipad_main terminal=false refresh=true")
    print(f"Disconnect iPad | bash='{cli_str}' param1=action param2=disconnect_ipad terminal=false refresh=true")
    print(f"Reconnect Sidecar | bash='{cli_str}' param1=action param2=reconnect_sidecar terminal=false refresh=true")
    print("---")

    # Utilities
    print(f"Refresh Display State | bash='{cli_str}' param1=action param2=refresh terminal=false refresh=true")
    print(f"Reset Display Automation | bash='{cli_str}' param1=action param2=reset terminal=false refresh=true")
    print("Open BetterDisplay | bash='open' param1='-a' param2='BetterDisplay' terminal=false")
    print(f"Preferences... | bash='{cli_str}' param1=prefs terminal=false")
    print(f"Open Log | bash='{cli_str}' param1=open-log terminal=false")
    print("---")

    # Management & Exit
    print(f"{a_mark}Run Daemon at Login | bash='{cli_str}' param1=autostart param2=toggle terminal=false refresh=true")
    print(f"Stop PadPilot Daemon | bash='{cli_str}' param1=stop terminal=false refresh=true")
    print("Quit SwiftBar | bash='osascript' param1='-e' param2='tell application \"SwiftBar\" to quit' terminal=false")


if __name__ == "__main__":
    main()
