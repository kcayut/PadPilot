"""BetterDisplay CLI integration and Capability Probing for PadPilot."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from typing import Any, List, Optional, Tuple

from core.logger import get_logger

logger = get_logger("BetterDisplay")


@dataclass
class BetterDisplayCapabilities:
    cli_available: bool = False
    cli_path: Optional[str] = None
    sidecar_supported: bool = False
    virtual_creation_supported: bool = False
    details: str = ""


class BetterDisplayCLI:
    """Wrapper for BetterDisplay CLI with capability probing and safety fallbacks."""

    def __init__(self, custom_path: Optional[str] = None) -> None:
        self.cli_path = self._resolve_cli_path(custom_path)
        self.capabilities = self.probe_capabilities()

    def _resolve_cli_path(self, custom_path: Optional[str] = None) -> Optional[str]:
        if custom_path and os.path.isfile(custom_path) and os.access(custom_path, os.X_OK):
            return custom_path

        # Check PATH
        which_path = shutil.which("betterdisplaycli")
        if which_path:
            return which_path

        # Check inside BetterDisplay.app bundle
        app_bundle_bin = "/Applications/BetterDisplay.app/Contents/MacOS/BetterDisplay"
        if os.path.isfile(app_bundle_bin) and os.access(app_bundle_bin, os.X_OK):
            return app_bundle_bin

        # Common Homebrew paths
        for p in ["/opt/homebrew/bin/betterdisplaycli", "/usr/local/bin/betterdisplaycli"]:
            if os.path.isfile(p) and os.access(p, os.X_OK):
                return p

        return None

    def is_available(self) -> bool:
        return self.cli_path is not None and os.path.isfile(self.cli_path) and os.access(self.cli_path, os.X_OK)

    def run_cmd(self, args: List[str], timeout: float = 8.0) -> Tuple[int, str, str]:
        if not self.cli_path:
            return -1, "", "betterdisplaycli executable not found"
        cmd = [self.cli_path] + args
        try:
            res = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
            return res.returncode, res.stdout.strip(), res.stderr.strip()
        except subprocess.TimeoutExpired:
            logger.warning(f"Command timed out: {' '.join(cmd)}")
            return -1, "", "Command timed out"
        except Exception as e:
            logger.error(f"Error running {' '.join(cmd)}: {e}")
            return -1, "", str(e)

    def probe_capabilities(self) -> BetterDisplayCapabilities:
        caps = BetterDisplayCapabilities()
        if not self.cli_path:
            caps.details = "betterdisplaycli binary not found"
            return caps

        caps.cli_path = self.cli_path
        # Executable availability does not prove optional feature support.
        caps.cli_available = True

        code, stdout, stderr = self.run_cmd(["help"], timeout=15.0)
        if code != 0 and not stdout:
            caps.details = f"betterdisplaycli help unavailable ({stderr}); capabilities unverified. Commands may be retried."
            logger.warning(caps.details)
            return caps

        help_text = (stdout + " " + stderr).lower()

        caps.sidecar_supported = "sidecar" in help_text or "sidecarlist" in help_text
        caps.virtual_creation_supported = "virtualscreen" in help_text or "create" in help_text
        caps.details = (
            f"CLI ready. Sidecar support: {caps.sidecar_supported}, "
            f"Virtual creation support: {caps.virtual_creation_supported}"
        )
        logger.info(caps.details)
        return caps

    def get_sidecar_list(self) -> List[dict[str, str]]:
        """List available Sidecar targets. Returns list of {name, uuid}."""
        if not self.is_available():
            return []
        code, stdout, stderr = self.run_cmd(["get", "-sidecarList"], timeout=5.0)
        if code != 0:
            logger.warning(f"get -sidecarList failed: {stderr}")
            return []

        devices: List[dict[str, str]] = []
        for line in stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            # Output format can be:
            # "Cayut's iPad (UUID: 12345678-ABCD-...)" or "Name: ..., UUID: ..." or JSON
            uuid_match = re.search(r"([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})", line)
            uuid = uuid_match.group(1) if uuid_match else ""

            # Extract name before UUID or parenthesis
            name = line
            if uuid_match:
                name = line[: uuid_match.start()].strip(" (:-")
            if not name:
                name = "iPad"

            devices.append({"name": name, "uuid": uuid, "raw": line})
        return devices

    def connect_sidecar(self, specifier: str) -> bool:
        """Connect Sidecar display using name or UUID."""
        if not self.is_available():
            logger.error("Cannot connect Sidecar: BetterDisplay CLI not available")
            return False
        logger.info(f"Connecting Sidecar with specifier: {specifier}")
        code, out, err = self.run_cmd(["set", "-sidecarConnected=on", f"-specifier={specifier}"], timeout=10.0)
        if code == 0:
            logger.info("connect_sidecar command completed successfully")
            return True
        logger.warning(f"connect_sidecar failed (code {code}): {err or out}")
        return False

    def disconnect_sidecar(self, specifier: str) -> bool:
        """Disconnect Sidecar display using name or UUID."""
        if not self.is_available():
            logger.error("Cannot disconnect Sidecar: BetterDisplay CLI not available")
            return False
        logger.info(f"Disconnecting Sidecar with specifier: {specifier}")
        code, out, err = self.run_cmd(["set", "-sidecarConnected=off", f"-specifier={specifier}"], timeout=8.0)
        if code == 0:
            logger.info("disconnect_sidecar command completed successfully")
            return True
        logger.warning(f"disconnect_sidecar failed (code {code}): {err or out}")
        return False

    def set_main_display(self, specifier: str) -> bool:
        """Set a display as Main Display."""
        if not self.is_available():
            logger.error("Cannot set main display: BetterDisplay CLI not available")
            return False
        logger.info(f"Setting main display to: {specifier}")
        # Try -namelike first, or -uuid if it matches uuid pattern
        is_uuid = re.match(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$", specifier)
        arg = f"-uuid={specifier}" if is_uuid else f"-namelike={specifier}"
        code, out, err = self.run_cmd(["set", arg, "-main=on"], timeout=8.0)
        if code == 0:
            logger.info(f"Successfully set main display to {specifier}")
            return True
        logger.warning(f"set_main_display failed (code {code}): {err or out}")
        return False

    def connect_virtual_display(self, name: str) -> bool:
        """Connect an existing virtual display."""
        if not self.is_available():
            logger.error("Cannot connect virtual display: BetterDisplay CLI not available")
            return False
        logger.info(f"Connecting Virtual Screen: {name}")
        code, out, err = self.run_cmd(["set", f"-namelike={name}", "-connected=on"], timeout=8.0)
        if code == 0:
            logger.info(f"Virtual Screen '{name}' connected successfully")
            return True
        logger.warning(f"connect_virtual_display failed (code {code}): {err or out}")
        return False

    def disconnect_virtual_display(self, name: str) -> bool:
        """Disconnect a virtual display."""
        if not self.is_available():
            logger.error("Cannot disconnect virtual display: BetterDisplay CLI not available")
            return False
        logger.info(f"Disconnecting Virtual Screen: {name}")
        code, out, err = self.run_cmd(["set", f"-namelike={name}", "-connected=off"], timeout=8.0)
        if code == 0:
            logger.info(f"Virtual Screen '{name}' disconnected successfully")
            return True
        logger.warning(f"disconnect_virtual_display failed (code {code}): {err or out}")
        return False

    def get_display_identifiers(self) -> List[dict[str, Any]]:
        """Fetch display identifiers from BetterDisplay CLI."""
        if not self.is_available():
            return []
        code, out, err = self.run_cmd(["get", "-identifiers"], timeout=5.0)
        if code != 0 or not out:
            return []
        try:
            return json.loads("[" + out + "]")
        except Exception:
            return []

    def check_virtual_display(self, name: str) -> Tuple[bool, bool]:
        """Check if virtual display exists and if it is connected.
        
        Returns:
            (virtual_display_exists, virtual_display_connected)
        """
        identifiers = self.get_display_identifiers()
        if not identifiers:
            return False, False

        exists = False
        connected = False
        for item in identifiers:
            item_name = item.get("name", "")
            dev_type = item.get("deviceType", "")
            if name and name.casefold() == item_name.casefold():
                exists = True
                disp_id = str(item.get("displayID", "0"))
                if disp_id.isdecimal() and int(disp_id) > 0:
                    connected = True
        return exists, connected

    def ensure_virtual_display(self, name: str) -> Tuple[bool, str]:
        """Ensure virtual display exists.
        
        Capability probing per requirements:
        1. Check if pre-existing virtual display exists.
        2. If missing, probe if CLI can create it.
        3. If CLI supports creation, attempt create.
        4. If not supported, inform user to create it once in BetterDisplay UI.
        """
        exists, connected = self.check_virtual_display(name)
        if exists:
            return True, f"Virtual display '{name}' exists (connected: {connected})"

        if not self.capabilities.virtual_creation_supported:
            msg = (
                f"Virtual display '{name}' not found and CLI creation not supported in this version. "
                "Please open BetterDisplay Settings and create a Virtual Screen named '{name}' once."
            )
            logger.warning(msg)
            return False, msg

        logger.info(f"Attempting to create Virtual Screen '{name}' via CLI...")
        code, out, err = self.run_cmd(
            ["create", "-devicetype=virtualscreen", f"-virtualscreenname={name}", "-aspectWidth=16", "-aspectHeight=10"],
            timeout=10.0,
        )
        if code == 0:
            logger.info(f"Virtual Screen '{name}' created successfully")
            return True, f"Virtual Screen '{name}' created successfully"

        msg = f"Failed to create Virtual Screen '{name}' via CLI: {err or out}. Please create it manually in BetterDisplay."
        logger.warning(msg)
        return False, msg
