# 📱 PadPilot

<p align="center">
  <a href="README.md">繁體中文</a> | <b>English</b>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/version-0.1.0-blue.svg" alt="Version">
  <img src="https://img.shields.io/badge/License-MIT-yellow.svg" alt="License: MIT">
  <img src="https://img.shields.io/badge/platform-macOS%2014%2B-lightgrey.svg" alt="Platform: macOS 14+">
  <img src="https://img.shields.io/badge/status-early%20preview-orange.svg" alt="Status: Early Preview">
</p>

**Automated Display & Sidecar State Manager for Mac mini + iPad (Headless Display State Manager)**

PadPilot is an automated display state manager engineered for Mac mini (and Mac Studio) paired with an iPad via USB-C. Designed around the core principles of **"Physical Display First, Manual Override Absolute Priority, Full State Transparency, and Long-Term Headless Fallback"**, PadPilot automatically connects your designated iPad via Sidecar and promotes it to the primary display when no physical monitor is attached. When a physical monitor is present, it maintains physical display primacy while offering seamless macOS Menu Bar and graphical controls.

---

## 🧭 Decision Logic (Flow)

```text
Physical display?
   │
   ├─ Yes → leave Sidecar alone (Physical monitor is primary; iPad stays tablet or secondary)
   │
   └─ No
       ├─ USB iPad → Sidecar → Main Display (No physical display; automatically set iPad as primary)
       └─ No iPad → BetterDisplay virtual fallback (Emergency headless virtual display for remote access)
```

---

## ⚠️ Requirements & System Limitations

1. **macOS Apple Silicon Only**: Optimized for Apple Silicon (M1/M2/M3/M4) architectures on macOS 14 (Sonoma) or newer.
2. **Logged-in User Session Required**:
   > [!WARNING]
   > **PadPilot cannot turn the iPad into a FileVault / pre-login display.**  
   > Apple Sidecar is a user-session-level service. If FileVault is enabled without auto-login, macOS cannot establish a Sidecar session before password entry. To achieve headless cold-boot into iPad, please disable FileVault and enable macOS automatic login (see [Troubleshooting Guide](docs/TROUBLESHOOTING.md)).
3. **Helper Dependencies**:
   - **[SwiftBar](https://github.com/swiftbar/SwiftBar)**: macOS Menu Bar dropdown and dynamic icon integration.
   - **[BetterDisplay](https://github.com/waydabber/BetterDisplay)**: Underlying display resolution management and headless virtual screen fallback.
4. **Apple Sidecar Prerequisites**: Both Mac and iPad must be signed into the same Apple Account with Wi-Fi and Bluetooth enabled. When connecting via cable for the first time, tap "Trust This Computer" on the iPad.

---

## 🌟 Key Features

- **Automated Context Switching**:
  - **Headless / On-the-go**: Automatically connects designated iPad via Sidecar and assigns it as Main Display when no monitor is attached.
  - **Desktop Mode**: Stays silent when HDMI/DisplayPort/Thunderbolt monitors are connected.
- **Absolute User Override Priority**:
  - Manually choose "Use as Secondary" or "Set as Main Display" anytime from the menu bar.
  - **Topology Generation Lock**: Manual choices bind to the current physical hardware generation; automation will never revert user overrides unless cable topology physically changes.
- **Single-Flight Concurrency & Debounce Protection**:
  - 4-second signal debounce prevents erratic switching during monitor input toggling.
  - 3-retry limit with 30-second cooldown protection against Sidecar connection storms.
- **BetterDisplay Headless Virtual Fallback**:
  - Provides a stable virtual display (`PadPilotVirtual`) for VNC, Screen Sharing, or SSH recovery if no display or iPad is available.
- **Ultra-Lightweight Menu Bar (< 5ms)**:
  - SwiftBar plugin reads atomically written JSON states without polling hardware, maintaining ~0.0% CPU overhead.

---

## ⚡ Quick Start

```bash
git clone https://github.com/kcayut/PadPilot.git
cd PadPilot
./scripts/install.sh
```
*(Add `--yes` or `-y` to automatically approve Homebrew dependency installations)*

---

## 📱 Pairing Your iPad

Connect your iPad to the Mac via USB-C, ensure both devices are signed in to the same Apple Account, and run the interactive pairing wizard:

```bash
./bin/padpilot-cli pair --interactive
```

Or open the graphical management window:
```bash
./bin/padpilot-cli gui
```

Open SwiftBar to access the menu bar controller:
```bash
open -a SwiftBar
```

---

## 🌐 Interface Language

PadPilot supports **English**, **繁體中文 (Traditional Chinese)**, and **日本語 (Japanese)**.
On first run, PadPilot automatically detects your macOS preferred system language (defaulting to English on non-Chinese/Japanese systems).

You can switch languages anytime via:
- **Menu Bar**: Select `🌐 Language` directly in the SwiftBar menu.
- **GUI**: Click the `🌐` dropdown in the top-right header of the management window.
- **CLI**: Run `./bin/padpilot-cli set-language <en|zh-Hant|ja>`.

Language settings take effect immediately across the Daemon, SwiftBar menu, and GUI. Hardware names, device serials, and system logs are preserved in their original form.

---

## 📄 License

This project is licensed under the [MIT License](LICENSE).
Copyright (c) 2026 kcayut.
