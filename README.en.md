<p align="center">
  <img src="assets/padpilot-icon.png" width="160" height="160" alt="PadPilot icon: a navigation arrow inside a tablet">
</p>

<h1 align="center">PadPilot</h1>

<p align="center">
  <b>Sidecar display automation for Mac</b><br>
  Let your iPad take the screen.
</p>

<p align="center">
  <a href="README.md">繁體中文</a> | <b>English</b> | <a href="README.ja.md">日本語</a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/version-0.1.0-blue.svg" alt="Version: 0.1.0">
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-PolyForm%20Noncommercial-blue.svg" alt="License: PolyForm Noncommercial 1.0.0"></a>
  <img src="https://img.shields.io/badge/platform-macOS%2014%2B-lightgrey.svg" alt="Platform: macOS 14+">
  <img src="https://img.shields.io/badge/status-early%20preview-orange.svg" alt="Status: Early Preview">
</p>

PadPilot is a macOS display automation tool built around **Apple Sidecar and BetterDisplay**, primarily for a Mac mini + iPad setup. When no physical monitor is connected, it attempts to connect your selected iPad and make it the main display. When a monitor returns, it adjusts display roles according to your operating mode and manual choices.

Use the menu bar, graphical settings window, or command line to control connections, manage pairings, and see the current state and the reason for each transition.

> [!IMPORTANT]
> **Early preview.** Test with a physical monitor or a working remote connection available.
> PadPilot operates after user login. **It cannot make an iPad show FileVault unlock or pre-login screens.** Disabling FileVault is not required for installation; headless cold boots and different hardware combinations still require real-device validation.

GUI help, troubleshooting, and diagnostic links open the matching version of the documentation on GitHub in the interface language. Private repository documents require a GitHub account with access. These links stay pinned to that version when newer versions are published.

## Features

- **Physical display priority**: Automatic mode does not initiate Sidecar when a physical monitor is available. An already-connected iPad can remain a secondary display.
- **Main and secondary iPad controls**: Connect, disconnect, reconnect, and switch roles. Save multiple pairings and select one active control target.
- **Virtual display fallback**: Use a BetterDisplay virtual screen for a headless desktop. The fallback display remains available after the iPad takes over.
- **USB event wakeup**: Hardware events wake the background evaluation loop, with discovery windows, periodic checks, debounce, and failure cooldown.
- **Visible decisions**: Search devices, manage pairings, and inspect status, diagnostics, and logs in the settings window. The menu bar reads snapshots produced by the background service.
- **Three interface languages**: English, Traditional Chinese, and Japanese. The core uses Python's standard library without additional pip packages.

## How it works

New installations default to `manual_only`, with “Connect iPad at boot when no monitor is attached” enabled. After login, discovery runs for up to three 30-second rounds (90 seconds total), stopping if none finds the target. Finding it without a physical monitor can request one connection round. Later connections require a menu or global shortcut request. If you switch to `automatic`, with no active manual override:

| Current setup | Expected behavior |
| --- | --- |
| A physical monitor is available | Use a physical main display. Do not initiate Sidecar; keep an already-connected iPad as secondary. |
| No physical monitor, but an iPad target is available | After debounce, attempt to connect Sidecar and make the iPad the main display. |
| Neither a physical monitor nor an iPad target is available | Use the configured BetterDisplay virtual screen as fallback. |

The `prefer_ipad` mode prioritizes an iPad main display. Manual choices take priority within the current hardware topology; a mode change, reset, or topology change triggers reevaluation.

Defaults are a **4-second** physical display disconnect debounce, up to **3** Sidecar connection attempts, **3 seconds** between retries, and a **30-second** failure cooldown. These timings are not a guarantee of connection completion time.

## Requirements

| Component | Requirement |
| --- | --- |
| Mac | Apple Silicon (arm64), macOS 14+. Intel Macs are not supported; hardware combinations still need validation. |
| iPad | A Sidecar-compatible iPad using the same Apple Account as the Mac, with two-factor authentication. |
| Python | CPython is bundled in releases; external Python must be Apple Silicon 3.10+. |
| [BetterDisplay](https://github.com/waydabber/BetterDisplay) | Provides Sidecar and display control. Use a release compatible with your macOS version and verify CLI access. Command-line control requires Pro or an active trial under the upstream licensing terms. |
| Apple Command Line Tools | Required only to build from source or package releases, not to run a release. |
| Connection | For initial setup, use a USB data cable and trust the Mac on the iPad. Wireless Sidecar additionally requires Wi-Fi, Bluetooth, and Handoff. |

See [Apple's Sidecar guide](https://support.apple.com/en-us/102597) for device compatibility and wired/wireless requirements. BetterDisplay features and licensing are governed by its [upstream documentation](https://github.com/waydabber/BetterDisplay#key-features); PadPilot's license does not cover third-party software licenses.

## Quick start

### 1. Install

First verify Sidecar works manually through macOS Screen Mirroring. Download the Apple Silicon `.dmg` from [GitHub Releases](https://github.com/kcayut/PadPilot/releases), drag **PadPilot.app into Applications**, then open the installed app. Swift and CPython are included. No separate Python, Homebrew, or Apple build tools are required; the native GUI, CLI, daemon, USB detection, and launch-at-login features share the same core.

This is a **development preview with ad-hoc signing, without Developer ID signing or Apple notarization**. macOS may warn that the developer cannot be verified or that it cannot check for malicious software. After verifying the download source, follow [Apple’s instructions](https://support.apple.com/en-us/102445) for System Settings → Privacy & Security → Open Anyway. For a damaged-app warning, download again and verify `SHA256SUMS`; do not assume every warning is harmless.

To choose Python yourself, download and run the [release installer](https://raw.githubusercontent.com/kcayut/PadPilot/main/scripts/install_release.sh), or run this from a source checkout:

```bash
bash scripts/install.sh --release
```

The script finds the newest published release, including prereleases, and lets you choose bundled CPython or your own Apple Silicon Python 3.10+. Options include `--tag v0.1.0-dev.1`, `--bundled`, and `--python /absolute/path/python3`. A maintainer must first push a tag to produce a release; the installer stops clearly if none is available. It verifies the download and installs while preserving settings. Open the installed app afterward.

The BetterDisplay **app must be installed and running**; `betterdisplaycli` alone is insufficient. The separate CLI is optional: PadPilot can use the app’s built-in interface and discover Applications, user Applications, and custom locations registered with macOS. A manually selected path takes priority.

Save settings and quit PadPilot before installing, updating, or changing Python. Pairings and settings live outside the app. When migrating from a source installation or changing installation locations, uninstall the old copy first and keep settings. See the [installation guide](docs/INSTALLATION.en.md). Developers can still build locally with `bash scripts/install.sh`; source mode requires keeping the source and selected Python in place.

The CLI examples below assume `/Applications/PadPilot.app`; substitute your actual location if different.

### 2. Select your iPad

Run the interactive pairing wizard in Terminal and select the iPad to control:

```bash
"/Applications/PadPilot.app/Contents/Resources/padpilot-cli" pair --interactive
```

Alternatively, open the settings window to discover devices, save pairings, and select the control target:

```bash
"/Applications/PadPilot.app/Contents/Resources/padpilot-cli" gui
```

PadPilot pairing records device identities; it does not replace Apple Account or “Trust This Computer” requirements. Multiple pairings can be saved, but only one iPad is managed as the active target at a time.

### 3. Check fallback and status

`status` separately reports whether the daemon responded to a handshake. Without a response, saved snapshots are not live state. `status --json` includes `daemon_responding` and the version; absent snapshots leave display state unknown.

For headless use, confirm that a virtual screen named `PadPilotVirtual` exists in BetterDisplay, or select an existing virtual screen in PadPilot's settings. If your version does not support automatic creation, create it once in BetterDisplay.

```bash
"/Applications/PadPilot.app/Contents/Resources/padpilot-cli" status
"/Applications/PadPilot.app/Contents/Resources/padpilot-cli" open-log
```

`open-log` opens the status and diagnostics window; `open-log --raw` opens the raw log. Configure Screen Sharing/VNC or SSH beforehand if you need remote recovery. PadPilot does not enable remote access, and SSH itself does not require a virtual display.

## USB wakeup and automatic discovery

Find these switches in **menu bar → Settings & Pairing → Operation & Preferences → Advanced options → USB & iPad Auto-detection**.

- **USB event wakeup** is enabled by default. IOKit notifications wake background evaluation, with a 30-second periodic check retained. Ordinary startup and USB events open a discovery window of up to 30 seconds, checking every 2 seconds. Manual mode with boot connection enabled extends startup discovery to at most three rounds. If notification registration fails, diagnostics report it and periodic checks remain active.
- **Automatic iPad detection** is enabled by default. An explicitly selected pairing with a Sidecar UUID takes priority. Without one, PadPilot infers a target from a unique USB iPad and Sidecar candidate, preferring saved identity mappings. Failed queries, missing candidates, or ambiguity prevent an iPad connection attempt.
- **Explicit pairing suits multiple-device environments**. Unique candidates are a heuristic, not proof that the USB and Sidecar identities belong to the same iPad. Disable automatic detection and pair explicitly when other iPads may be nearby. Inferred targets do not create or modify saved pairings.
- **Wired and wireless targets**: A selected pairing can continue to use Sidecar availability after USB is disconnected. An unpaired target inferred only from USB will not initiate a wireless fallback connection after unplugging.

The current control target is shown in settings and the menu bar. Both switches apply live; previously saved disabled settings are preserved.

## Menu bar and interface language

The menu bar uses **18 × 18 pt, Retina-ready monochrome icons** that adapt to macOS light and dark appearances. Hover for the PadPilot name; open the menu for the main display, operating mode, devices, and diagnostics.

<p align="center">
  <img src="assets/menu-icons/preview.png" width="630" alt="PadPilot menu icons: Sidecar, physical display, virtual fallback, Manual Only, service stopped, warning, and working">
</p>

The icons represent Sidecar, physical display, virtual fallback, Manual Only, service stopped, warning, and working, respectively. The pointing-hand icon (`manual.png`) means the background service is running in Manual Only mode, even when an iPad is connected; the pause icon (`paused.png`) means the background service has stopped. Errors take priority with a warning icon; applying settings or switching displays shows the working icon, then returns to the corresponding state icon. Assets are included in the repository; developers can rebuild them with `swift scripts/build_menu_icons.swift` after changing the design.

On first configuration, PadPilot selects a language from your macOS preferences, defaulting to English on non-Chinese/Japanese systems. Change it through the menu bar's Language menu, the GUI language selector, or `set-language`. GUI usage, troubleshooting, and diagnostic help links open local documents in the selected language. Device names, identifiers, and raw logs retain their original text.

## Common commands

Run these from any directory. If `~/bin` is on your PATH, you can also use `padpilot-cli` directly. Installation, update, and development scripts still run from the source directory.

```bash
# Status and settings
"/Applications/PadPilot.app/Contents/Resources/padpilot-cli" status --json
"/Applications/PadPilot.app/Contents/Resources/padpilot-cli" gui
"/Applications/PadPilot.app/Contents/Resources/padpilot-cli" set-language en        # Also accepts zh-Hant or ja

# Operating modes: choose one
"/Applications/PadPilot.app/Contents/Resources/padpilot-cli" set-mode automatic
"/Applications/PadPilot.app/Contents/Resources/padpilot-cli" set-mode manual_only
"/Applications/PadPilot.app/Contents/Resources/padpilot-cli" set-mode prefer_ipad

# Manual actions: choose as needed
"/Applications/PadPilot.app/Contents/Resources/padpilot-cli" action use_ipad_secondary
"/Applications/PadPilot.app/Contents/Resources/padpilot-cli" action use_ipad_main
"/Applications/PadPilot.app/Contents/Resources/padpilot-cli" action disconnect_ipad
"/Applications/PadPilot.app/Contents/Resources/padpilot-cli" action reconnect_sidecar
"/Applications/PadPilot.app/Contents/Resources/padpilot-cli" action refresh
"/Applications/PadPilot.app/Contents/Resources/padpilot-cli" action reset           # Clear temporary override and cooldown

# Background service and launch at login
"/Applications/PadPilot.app/Contents/Resources/padpilot-cli" stop
"/Applications/PadPilot.app/Contents/Resources/padpilot-cli" start
"/Applications/PadPilot.app/Contents/Resources/padpilot-cli" exit                  # Stop service and hide the PadPilot menu
"/Applications/PadPilot.app/Contents/Resources/padpilot-cli" autostart status
"/Applications/PadPilot.app/Contents/Resources/padpilot-cli" autostart toggle

# Version and complete command help
"/Applications/PadPilot.app/Contents/Resources/padpilot-cli" --version
"/Applications/PadPilot.app/Contents/Resources/padpilot-cli" --help
```

Release updates: quit PadPilot, then replace the app at the same location or rerun the release installer. Settings are preserved; choose Python when using the installer. Before changing locations, uninstall the old copy while keeping settings. The following rebuild instructions apply only to source installations.

Keep a backup of the prior source, save and close settings, then update the source and rerun `./scripts/install.sh --check`, `./scripts/install.sh`, and `"/Applications/PadPilot.app/Contents/Resources/padpilot-cli" status`. This also rebuilds the native app. The GUI About page, CLI `--version`, and app share one version source. About also includes GitHub and donation links; donation buttons remain disabled until recipient URLs are configured. The old app is recoverable from Trash, but restoring the app alone does not restore its referenced source.

## Limitations and troubleshooting

- **Sidecar is a prerequisite**: PadPilot does not add Sidecar support to incompatible devices or control Universal Control's keyboard and pointer routing.
- **Connection timing depends on macOS and the devices**: A USB notification, a 4-second debounce, or a successful command submission does not mean the iPad is displaying the desktop. Fallback takes priority during cooldown.
- **Headless setups still need validation**: Cold boot, sleep/wake, hub, and multiple-device combinations have not been comprehensively tested. No iPad display is provided before user login. Disabling FileVault and enabling automatic login are not guaranteed setup steps.
- **Other display controllers can conflict**: If another tool repeatedly changes the main display or Sidecar state, switch to `manual_only` and inspect the transition reasons and logs.

Configuration and runtime state normally live in `~/Library/Application Support/PadPilot/`; logs are in `~/Library/Logs/PadPilot/`. When reporting a problem, include versions, connection type, reproduction steps, and relevant logs. Redact device serials, UUIDs, accounts, and personal paths first.

Private directories use `0700`; configuration, status, sockets, and logs use `0600`. Foreign-owned or linked state paths are rejected. New IPC logs omit pairing payloads; existing historical logs are not erased. See the [release acceptance matrix (Traditional Chinese)](docs/development/2026-09-11-release-readiness.md) for tested environments and hardware scenarios still marked `unknown`.

## Uninstall

For a release app, save and close settings, then run the command below. The app and launch-at-login entry move to Trash; settings, pairings, and logs remain unless you also pass `--purge`.

```bash
"/Applications/PadPilot.app/Contents/Resources/padpilot-cli" --bundled-cli uninstall --yes
```

**Source installation**: Paste this into Terminal to choose what to remove:

```bash
/bin/bash "$HOME/Applications/PadPilot-source/scripts/uninstall.sh"
```

The uninstaller presents a removal summary for confirmation, then stops this checkout's service and menu and moves its app, LaunchAgent, and CLI entry to Trash. Configuration/pairings, logs, downloaded source, and third-party dependencies newly installed by the installer are separate choices, all kept by default. Existing Python, BetterDisplay, Homebrew, Apple tools, and virtual displays are not removed along with PadPilot.

For noninteractive app-only removal, add `--yes`. To also remove settings and logs, add `--yes --purge`; source and third-party dependencies still remain. With a manually obtained source copy, run `./scripts/uninstall.sh` from its directory. See [uninstall options](docs/INSTALLATION.en.md#uninstall).

## Documentation and contributing

- [Installation guide](docs/INSTALLATION.en.md)
- [Troubleshooting and FAQ](docs/TROUBLESHOOTING.en.md)
- [Architecture](docs/ARCHITECTURE.en.md)
- [Documentation index and languages](docs/README.en.md)
- [Development notes (Traditional Chinese)](docs/development/README.md) — maintainer history
- [Changelog](CHANGELOG.md)
- [Contributing guide](CONTRIBUTING.md) and [security policy](SECURITY.md)

The README and user guides under `docs/` are available in Traditional Chinese, English, and Japanese. Development notes are maintained in Traditional Chinese only. Issues, translation improvements, hardware compatibility reports, and pull requests are welcome. After code changes, run `python3 -m unittest discover -s tests -v`; for GUI changes, also follow the layout checks in the contributing guide. Automated tests do not substitute for physical cold-boot or hotplug validation.

## License and acknowledgments

Licensed under the [PolyForm Noncommercial License 1.0.0](LICENSE). Author: **kcayut**. Copyright (c) 2026 kcayut.

- Noncommercial use, modification, and distribution are permitted. Commercial uses outside the license's permitted purposes require separate authorization from the author.
- When distributing source code, binaries, or modified versions, include the license terms or their official URL and preserve every `Required Notice:` author and project attribution in [NOTICE](NOTICE). Built apps include `LICENSE` and `NOTICE`.
- The license also expressly permits use by charitable organizations, educational institutions, public research organizations, public safety or health organizations, environmental protection organizations, and government institutions, regardless of funding. The full license governs these permissions.

This is a source-available noncommercial license, not an OSI open-source license. The change applies to versions provided with this license; it does not revoke rights to versions previously obtained under MIT.

Thanks to [BetterDisplay](https://github.com/waydabber/BetterDisplay) for display control. PadPilot is an independent project, not affiliated with or endorsed by Apple or BetterDisplay.
