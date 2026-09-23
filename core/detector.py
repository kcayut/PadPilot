"""Hardware and display topology detector for SidecarSwitch.

Uses CoreGraphics (ctypes) and IOKit (ioreg) for low-cost, high-speed detection.
Does not rely on high-frequency system_profiler polling.
"""

from __future__ import annotations

import ctypes
import re
import subprocess
import time
from ctypes import byref, c_uint32
from typing import Any, List, Optional, Set, Tuple

from core.betterdisplay import BetterDisplayCLI
from core.config import Config
from core.logger import get_logger
from core.models import ActualState, DisplayInfo, IpadConfig

logger = get_logger("Detector")


class DisplayDetector:
    """Detects physical displays, USB iPads, and Sidecar sessions."""

    def __init__(self, config: Config, bd_cli: BetterDisplayCLI) -> None:
        self.config = config
        self.bd_cli = bd_cli
        self._cg = self._init_coregraphics()
        self._sidecar_display_identity = None

    def _init_coregraphics(self) -> Optional[ctypes.CDLL]:
        try:
            return ctypes.cdll.LoadLibrary("/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics")
        except Exception as e:
            logger.error(f"Failed to load CoreGraphics: {e}")
            return None

    def get_online_displays(self) -> List[DisplayInfo]:
        """Fetch all online displays via CoreGraphics."""
        self.display_error = ""
        if not self._cg:
            self.display_error = "CoreGraphics unavailable"
            return []

        max_displays = 32
        display_ids = (c_uint32 * max_displays)()
        count = c_uint32()

        try:
            err = self._cg.CGGetOnlineDisplayList(max_displays, display_ids, byref(count))
            if err != 0:
                self.display_error = f"CoreGraphics query failed: {err}"
                logger.warning(f"CGGetOnlineDisplayList returned error: {err}")
                return []
        except Exception as e:
            self.display_error = str(e)
            logger.error(f"CGGetOnlineDisplayList exception: {e}")
            return []

        # BetterDisplay identifiers lookup
        bd_map = {}
        try:
            for item in self.bd_cli.get_display_identifiers():
                d_id = str(item.get("displayID", ""))
                if d_id:
                    bd_map[d_id] = item
        except Exception as error:
            self.bd_cli.identifiers_error = str(error)

        displays: List[DisplayInfo] = []
        for i in range(count.value):
            did = display_ids[i]
            is_active = bool(self._cg.CGDisplayIsActive(did))
            is_main = bool(self._cg.CGDisplayIsMain(did))
            is_builtin = bool(self._cg.CGDisplayIsBuiltin(did))
            w = int(self._cg.CGDisplayPixelsWide(did))
            h = int(self._cg.CGDisplayPixelsHigh(did))

            vendor = int(self._cg.CGDisplayVendorNumber(did))
            model = int(self._cg.CGDisplayModelNumber(did))

            # Filter out ghost / inactive / placeholder 0x0 or 1x1 displays
            # Apple Silicon creates dummy Display 1 (e.g. 0x0, 1x1, inactive) when booting headless
            if not is_active or w <= 1 or h <= 1:
                logger.debug(f"Ignoring inactive or placeholder display: did={did}, active={is_active}, {w}x{h}")
                continue

            # If vendor is 0 and model is 0 without a matching BetterDisplay item, it's a headless placeholder
            if vendor == 0 and model == 0 and str(did) not in bd_map:
                logger.debug(f"Ignoring headless placeholder display with vendor 0: did={did}")
                continue

            # Device identity comes from hardware metadata, never a user-editable name.
            is_sidecar = vendor == 0x6161706C or model == 0x69506164
            is_virtual = vendor == 2198

            # Check from BetterDisplay
            bd_item = bd_map.get(str(did))
            if bd_item:
                name = bd_item.get("name") or f"Display-{did}"
                if (
                    bd_item.get("deviceType") == "VirtualScreen"
                    or str(bd_item.get("vendor")) == "2198"
                ):
                    is_virtual = True
                # Sidecar in BetterDisplay has vendor 1633775724 / model 1766875492 or empty registryLocation
                if (
                    str(bd_item.get("vendor")) == "1633775724"
                    or str(bd_item.get("model")) == "1766875492"
                ):
                    is_sidecar = True
            else:
                # CoreGraphics fallback
                name = f"Display-{did}"
                if vendor == 0x0469:
                    name = f"ASUS Display ({w}x{h})"
                elif vendor == 0x6161706C or model == 0x69506164:
                    name = self.config.ipad.name or f"iPad ({w}x{h})"
                    is_sidecar = True
                elif vendor == 2198 or vendor == 0x0896:
                    name = self.config.virtual_display_name or "SidecarSwitchVirtual"
                    is_virtual = True
                elif vendor != 0:
                    name = f"Monitor 0x{vendor:x} ({w}x{h})"

            displays.append(
                DisplayInfo(
                    display_id=did,
                    name=name,
                    uuid=(bd_item.get("UUID") or bd_item.get("uuid")) if bd_item else None,
                    is_main=is_main,
                    is_builtin=is_builtin,
                    is_virtual=is_virtual,
                    is_sidecar=is_sidecar,
                    width=w,
                    height=h,
                )
            )

        return displays

    def parse_usb_devices(self) -> List[dict[str, Any]]:
        """Parse connected USB devices from IOKit USB tree."""
        self.usb_error = ""
        try:
            out = subprocess.check_output(
                ["ioreg", "-p", "IOUSB", "-w0", "-l"],
                text=True,
                timeout=3.0,
                stderr=subprocess.DEVNULL,
            )
        except Exception as e:
            self.usb_error = str(e)
            logger.warning(f"Failed to query ioreg for USB: {e}")
            return []

        devices: List[dict[str, Any]] = []
        blocks = out.split("+-o ")
        for b in blocks[1:]:
            name_match = re.match(r"([^@]+)@([0-9a-fA-F]+)", b)
            name = name_match.group(1).strip() if name_match else "Unknown"

            vendor_id_m = re.search(r'"idVendor"\s*=\s*(\d+)', b)
            product_id_m = re.search(r'"idProduct"\s*=\s*(\d+)', b)
            serial_m = re.search(r'"(?:kUSBSerialNumberString|USB Serial Number)"\s*=\s*"([^"]+)"', b)
            product_name_m = re.search(r'"(?:kUSBProductString|USB Product Name)"\s*=\s*"([^"]+)"', b)
            vendor_name_m = re.search(r'"(?:kUSBVendorString|USB Vendor Name)"\s*=\s*"([^"]+)"', b)

            if vendor_id_m:
                devices.append(
                    {
                        "name": name,
                        "vendor_id": int(vendor_id_m.group(1)),
                        "product_id": int(product_id_m.group(1)) if product_id_m else None,
                        "serial": serial_m.group(1) if serial_m else None,
                        "product_name": product_name_m.group(1) if product_name_m else None,
                        "vendor_name": vendor_name_m.group(1) if vendor_name_m else None,
                    }
                )

        return devices

    def is_display_ignored(self, d: DisplayInfo) -> bool:
        """Exclude system roles; per-display choices override name heuristics."""
        if d.is_virtual or d.is_sidecar:
            return True
        override = self.config.display_exclusions.get((d.uuid or '').upper())
        if override is not None:
            return override
        name_lower = d.name.strip().lower()
        # ponytail: known headless names are defaults; per-UUID choices correct collisions.
        if name_lower in {"generic", "generic display"}:
            return True
        if "dummy" in name_lower or "headless" in name_lower:
            return True
        # Virtual display check
        if (self.config.virtual_display_name and self.config.virtual_display_name.lower() in name_lower) or "virtual" in name_lower:
            return True
        # Ignore list check
        for pattern in self.config.ignore_list:
            if pattern and pattern.lower() in name_lower:
                return True
        return False

    def resolve_ipad(self, usb_devices, sidecar_list):
        """Prefer the explicit Sidecar identity; infer only without a usable pairing."""
        self.auto_detect_error = ""
        if not self.config.auto_detect_ipad or self.config.ipad.sidecar_uuid:
            return self.config.ipad
        errors = (getattr(self, "usb_error", ""), getattr(self.bd_cli, "sidecar_error", ""))
        if any(isinstance(error, str) and error for error in errors):
            self.auto_detect_error = "Device query incomplete; pausing automatic iPad selection."
            return IpadConfig()
        ipads = [u for u in usb_devices if u.get("vendor_id") == 1452 and
                 "ipad" in (u.get("product_name") or u.get("name") or "").casefold()]
        if len(ipads) != 1 or not ipads[0].get("serial"):
            self.auto_detect_error = "Auto-detection requires a single connected iPad with identifiable USB serial."
            return IpadConfig()
        usb = ipads[0]
        known = [p for p in [self.config.ipad, *self.config.paired_ipads]
                 if p.usb_serial == usb["serial"] and p.sidecar_uuid]
        uuids = {p.sidecar_uuid.casefold() for p in known}
        candidates = [d for d in sidecar_list if not uuids or d.get("uuid", "").casefold() in uuids]
        if len(uuids) > 1 or len(candidates) != 1 or not candidates[0].get("uuid") or not candidates[0].get("name"):
            self.auto_detect_error = "Sidecar candidate not present or not unique; wait or pair explicitly."
            return IpadConfig()
        candidate = candidates[0]
        # ponytail: unique candidates are a heuristic, not proof of USB/Sidecar identity.
        # Use explicit pairing when other nearby iPads can be discovered.
        return IpadConfig(candidate["name"], candidate["uuid"], usb["serial"])

    def observe(self, current_generation: int = 0) -> Tuple[ActualState, Tuple[Any, ...]]:
        """Observe the current hardware state and calculate deterministic signature.
        
        Returns:
            (ActualState, deterministic_signature_tuple)
        """
        t0 = time.time()
        all_displays = self.get_online_displays()
        identifiers_error = getattr(self.bd_cli, 'identifiers_error', '')
        usb_devices = self.parse_usb_devices()

        # Check virtual display
        v_exists, v_conn = self.bd_cli.check_virtual_display(self.config.virtual_display_name)

        # Check Sidecar
        sidecar_list = self.bd_cli.get_sidecar_list()
        sidecar_available = len(sidecar_list) > 0
        sidecar_connected = False
        sidecar_display_online = False

        # Configured iPad matching
        target = self.resolve_ipad(usb_devices, sidecar_list)
        target_sidecar_uuid = target.sidecar_uuid
        target_usb_serial = target.usb_serial
        target_name = target.name
        # Saved names are user labels. Resolve the current name through the session UUID.
        targets = [d for d in sidecar_list if target_sidecar_uuid and
                   d.get("uuid", "").casefold() == target_sidecar_uuid.casefold()]
        if len(targets) == 1 and targets[0].get("name"):
            target_name = targets[0]["name"]
        session_connected = (self.bd_cli.get_sidecar_connected(target_sidecar_uuid or target_name)
                             if target_sidecar_uuid or target_name else False)
        cached = self._sidecar_display_identity
        if session_connected is False or (cached and cached[0] != target_sidecar_uuid.casefold()):
            self._sidecar_display_identity = cached = None
        matched_displays = []
        if self.config.auto_detect_ipad and not target_sidecar_uuid:
            sidecar_available = False

        if target_sidecar_uuid:
            sidecar_available = any(d.get("uuid", "").upper() == target_sidecar_uuid.upper() for d in sidecar_list)

        # Detect if USB iPad is present
        ipad_usb_present = False
        for u in usb_devices:
            if u["vendor_id"] == 1452:  # Apple Inc.
                # If specific USB serial configured, check exact match
                if target_usb_serial:
                    if u.get("serial") == target_usb_serial:
                        ipad_usb_present = True
                        break
                elif not self.config.auto_detect_ipad:
                    # Fallback check on product name
                    p_name = (u.get("product_name") or u.get("name") or "").lower()
                    if "ipad" in p_name:
                        ipad_usb_present = True
                        break

        # Filter physical displays and identify Sidecar displays
        physical_displays: List[DisplayInfo] = []
        main_display: Optional[DisplayInfo] = None

        for d in all_displays:
            d.excluded_from_physical_detection = self.is_display_ignored(d)
            if d.is_main:
                main_display = d

            # Check if this display is Sidecar
            d_name_lower = d.name.lower()
            if d.is_sidecar:
                # A different paired iPad must not satisfy the active target.
                matches_target = (
                    not (target_sidecar_uuid or target_name)
                    or (d.uuid and target_sidecar_uuid and d.uuid.upper() == target_sidecar_uuid.upper())
                    or (target_name and d_name_lower == target_name.lower() and
                        (not target_sidecar_uuid or len(targets) == 1) and
                        sum(s.get("name", "").casefold() == target_name.casefold() for s in sidecar_list) <= 1)
                    or (cached and d.uuid and d.uuid == cached[1])
                )
                if matches_target:
                    matched_displays.append(d)
                continue

            if d.excluded_from_physical_detection:
                continue

            physical_displays.append(d)

        sidecar_display_online = len(matched_displays) == 1
        sidecar_connected = sidecar_display_online
        if isinstance(session_connected, bool):
            sidecar_connected = session_connected
            if not session_connected:
                sidecar_display_online = False
        sidecar_display_id = matched_displays[0].display_id if sidecar_display_online else None
        if sidecar_display_online and target_sidecar_uuid and matched_displays[0].uuid:
            self._sidecar_display_identity = (target_sidecar_uuid.casefold(), matched_displays[0].uuid)
        identity_error = ''
        if session_connected is True and not sidecar_display_online and any(d.is_sidecar for d in all_displays):
            identity_error = 'Cannot identify the connected Sidecar display; keeping current displays.'

        # Deterministic topology signature per requirement 1:
        # Tuple of (tuple of sorted physical display IDs, ipad_usb_present)
        physical_ids = tuple(sorted(d.display_id for d in physical_displays))
        deterministic_signature = (physical_ids, ipad_usb_present)

        if self.config.auto_detect_ipad:
            deterministic_signature += (target_sidecar_uuid, target_usb_serial)

        actual = ActualState(
            resolved_ipad=target,
            physical_displays=physical_displays,
            online_displays=all_displays,
            sidecar_devices=sidecar_list,
            usb_devices=[u for u in usb_devices if u.get("vendor_id") == 1452],
            discovery_errors={key: error for key, error in (
                ("auto_detect", getattr(self, "auto_detect_error", "")),
                ("usb_events", getattr(self, "usb_monitor_error", "")),
                ("displays", getattr(self, "display_error", "")),
                ("usb", getattr(self, "usb_error", "")),
                ("sidecar", getattr(self.bd_cli, "sidecar_error", "")),
                ("sidecar_connection", getattr(self.bd_cli, "connection_error", "")),
                ("sidecar_identity", identity_error),
                ("identifiers", identifiers_error if isinstance(identifiers_error, str) and identifiers_error
                 else getattr(self.bd_cli, "identifiers_error", "")),
            ) if isinstance(error, str) and error},
            main_display=main_display,
            virtual_display_exists=v_exists,
            virtual_display_connected=v_conn,
            ipad_usb_present=ipad_usb_present,
            sidecar_available=sidecar_available,
            sidecar_connected=sidecar_connected,
            sidecar_display_online=sidecar_display_online,
            sidecar_display_id=sidecar_display_id,
            sleeping=False,
            topology_generation=current_generation,
            timestamp=time.time(),
        )

        duration_ms = (time.time() - t0) * 1000
        if duration_ms > 300:
            logger.debug(f"Topology observation took {duration_ms:.1f}ms")

        return actual, deterministic_signature
