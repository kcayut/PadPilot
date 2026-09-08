#!/usr/bin/env python3
"""Interactive / automated iPad pairing wizard for PadPilot."""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.betterdisplay import BetterDisplayCLI
from core.config import get_config_file_path, load_config, save_config
from core.detector import DisplayDetector


def main() -> None:
    print("==================================================")
    print("        📱 PadPilot iPad Pairing Wizard")
    print("==================================================")
    print("\nScanning for USB Apple devices and Sidecar displays...\n")

    cfg = load_config()
    bd_cli = BetterDisplayCLI(cfg.betterdisplaycli_path)
    detector = DisplayDetector(cfg, bd_cli)

    usb_devices = detector.parse_usb_devices()
    apple_usbs = [u for u in usb_devices if u.get("vendor_id") == 1452]
    sidecar_devices = bd_cli.get_sidecar_list()

    print("--- [Detected USB Apple Devices] ---")
    if not apple_usbs:
        print("  (None found. Ensure iPad is connected via USB-C cable)")
    else:
        for idx, dev in enumerate(apple_usbs):
            p_name = dev.get("product_name") or dev.get("name") or "Unknown"
            serial = dev.get("serial") or "No Serial"
            print(f"  [{idx+1}] {p_name} | Serial: {serial}")

    print("\n--- [Detected Sidecar Capable Devices] ---")
    if not sidecar_devices:
        print("  (None found. Ensure iPad and Mac mini share the same Apple Account and Wi-Fi/Bluetooth/USB are active)")
    else:
        for idx, dev in enumerate(sidecar_devices):
            name = dev.get("name", "Unknown")
            uuid = dev.get("uuid", "No UUID")
            print(f"  [{idx+1}] {name} | UUID: {uuid}")

    print("\n--------------------------------------------------")
    name_input = input("Enter iPad Name (or leave blank to keep current): ").strip()
    uuid_input = input("Enter Sidecar UUID (or leave blank to keep current): ").strip()
    serial_input = input("Enter USB Serial (or leave blank to keep current): ").strip()

    if name_input:
        cfg.ipad.name = name_input
    if uuid_input:
        cfg.ipad.sidecar_uuid = uuid_input
    if serial_input:
        cfg.ipad.usb_serial = serial_input

    save_config(cfg)
    print(f"\n✓ Configuration saved to {get_config_file_path()}:")
    print(json.dumps(cfg.ipad.to_dict(), indent=2))
    print("\nPairing complete!")


if __name__ == "__main__":
    main()
