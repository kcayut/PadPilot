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

In the default `automatic` mode, with no active manual override:

| Current setup | Expected behavior |
| --- | --- |
| A physical monitor is available | Use a physical main display. Do not initiate Sidecar; keep an already-connected iPad as secondary. |
| No physical monitor, but an iPad target is available | After debounce, attempt to connect Sidecar and make the iPad the main display. |
| Neither a physical monitor nor an iPad target is available | Use the configured BetterDisplay virtual screen as fallback. |

Two additional modes are available: `manual_only` pauses automatic switching while keeping manual controls, and `prefer_ipad` prioritizes an iPad main display. Manual choices take priority within the current hardware topology; a mode change, reset, or topology change triggers reevaluation.

Defaults are a **4-second** physical display disconnect debounce, up to **3** Sidecar connection attempts, **3 seconds** between retries, and a **30-second** failure cooldown. These timings are not a guarantee of connection completion time.

## Requirements

| Component | Requirement |
| --- | --- |
| Mac | The project targets macOS 14+, primarily on Apple Silicon Mac mini. Other model and OS combinations are not comprehensively validated. |
| iPad | A Sidecar-compatible iPad using the same Apple Account as the Mac, with two-factor authentication. |
| Python | Python 3.10+ for the background core. The installer detects dependencies and offers reuse, a custom path, or installation. |
| [BetterDisplay](https://github.com/waydabber/BetterDisplay) | Provides Sidecar and display control. Use a release compatible with your macOS version and verify CLI access. Command-line control requires Pro or an active trial under the upstream licensing terms. |
| Apple Command Line Tools | Builds the Swift/AppKit menu and native SwiftUI settings window; install using `xcode-select --install`. |
| Connection | For initial setup, use a USB data cable and trust the Mac on the iPad. Wireless Sidecar additionally requires Wi-Fi, Bluetooth, and Handoff. |

See [Apple's Sidecar guide](https://support.apple.com/en-us/102597) for device compatibility and wired/wireless requirements. BetterDisplay features and licensing are governed by its [upstream documentation](https://github.com/waydabber/BetterDisplay#key-features); PadPilot's license does not cover third-party software licenses.

## Quick start

### 1. Install

First verify that Sidecar works manually through macOS Screen Mirroring, then paste this entire block into Terminal:

```bash
(
  set -e
  installer="$(mktemp -t padpilot-install)"
  trap 'rm -f "$installer"' EXIT
  curl --fail --location --proto '=https' --tlsv1.2 \
    https://raw.githubusercontent.com/kcayut/PadPilot/main/scripts/bootstrap.sh \
    --output "$installer"
  /bin/bash "$installer"
)
```

**This download entry point requires [kcayut/PadPilot](https://github.com/kcayut/PadPilot) to be public and these installation scripts to be published on `main`.** Private repositories or unpublished scripts return 404; failed downloads never run the installer. With an existing source copy, run `./scripts/install.sh` from its project directory.

The installer detects Python, BetterDisplay, and Apple's build tools, then offers to reuse a detected dependency, enter a path, or install what is missing. Homebrew installation requires consent, including installing Homebrew itself if absent. Apple Command Line Tools use the macOS installation dialog; finish it and rerun the same command.

Before installing or uninstalling, save your changes and close PadPilot settings and diagnostics windows; an open window stops the operation with instructions to retry.

Source is kept in `~/Applications/PadPilot-source`. Rerunning reuses that folder and resumes installation; it does not overwrite source or download updates. The app is installed in `~/Applications/PadPilot.app`, preserving pairings, mode, and login preferences. A first install enables launch at login. Success requires a daemon handshake; failed startup attempts to restore the previous app and service state.

```bash
"$HOME/bin/padpilot-cli" status
open "$HOME/Applications/PadPilot.app"
```

The CLI shortcut uses the Python selected during installation. If another program owns `~/bin/padpilot-cli`, use `"$HOME/Applications/PadPilot.app/Contents/Resources/padpilot-cli"` instead. **Keep the Python environment and source folder in place**; this remains a locally built app that references its source. See the [installation guide](docs/INSTALLATION.en.md) for read-only checks, custom paths, and noninteractive options. A BetterDisplay CLI response does not verify licensing, Sidecar pairing, or an actual working display.

### 2. Select your iPad

Run the interactive pairing wizard in Terminal and select the iPad to control:

```bash
"$HOME/bin/padpilot-cli" pair --interactive
```

Alternatively, open the settings window to discover devices, save pairings, and select the control target:

```bash
"$HOME/bin/padpilot-cli" gui
```

PadPilot pairing records device identities; it does not replace Apple Account or “Trust This Computer” requirements. Multiple pairings can be saved, but only one iPad is managed as the active target at a time.

### 3. Check fallback and status

`status` separately reports whether the daemon responded to a handshake. Without a response, saved snapshots are not live state. `status --json` includes `daemon_responding` and the version; absent snapshots leave display state unknown.

For headless use, confirm that a virtual screen named `PadPilotVirtual` exists in BetterDisplay, or select an existing virtual screen in PadPilot's settings. If your version does not support automatic creation, create it once in BetterDisplay.

```bash
"$HOME/bin/padpilot-cli" status
"$HOME/bin/padpilot-cli" open-log
```

`open-log` opens the status and diagnostics window; `open-log --raw` opens the raw log. Configure Screen Sharing/VNC or SSH beforehand if you need remote recovery. PadPilot does not enable remote access, and SSH itself does not require a virtual display.

## USB wakeup and automatic discovery

Find these switches in **menu bar → Settings & Pairing → Operation & Preferences → Advanced options → USB & iPad Auto-detection**.

- **USB event wakeup** is enabled by default. IOKit notifications wake background evaluation, with a 30-second periodic check retained. Startup and USB events open a discovery window of up to 30 seconds, checking every 2 seconds. If notification registration fails, diagnostics report it and periodic checks remain active.
- **Automatic iPad detection** is enabled by default. An explicitly selected pairing with a Sidecar UUID takes priority. Without one, PadPilot infers a target from a unique USB iPad and Sidecar candidate, preferring saved identity mappings. Failed queries, missing candidates, or ambiguity prevent an iPad connection attempt.
- **Explicit pairing suits multiple-device environments**. Unique candidates are a heuristic, not proof that the USB and Sidecar identities belong to the same iPad. Disable automatic detection and pair explicitly when other iPads may be nearby. Inferred targets do not create or modify saved pairings.
- **Wired and wireless targets**: A selected pairing can continue to use Sidecar availability after USB is disconnected. An unpaired target inferred only from USB will not initiate a wireless fallback connection after unplugging.

The current control target is shown in settings and the menu bar. Both switches apply live; previously saved disabled settings are preserved.

## Menu bar and interface language

The menu bar uses **18 × 18 pt, Retina-ready monochrome icons** that adapt to macOS light and dark appearances. Hover for the PadPilot name; open the menu for the main display, operating mode, devices, and diagnostics.

<p align="center">
  <img src="assets/menu-icons/preview.png" width="540" alt="PadPilot menu icons: Sidecar, physical display, virtual fallback, paused, warning, and working">
</p>

The icons represent Sidecar, physical display, virtual fallback, paused, warning, and working, respectively. Assets are included in the repository; developers can rebuild them with `swift scripts/build_menu_icons.swift` after changing the design.

On first configuration, PadPilot selects a language from your macOS preferences, defaulting to English on non-Chinese/Japanese systems. Change it through the menu bar's Language menu, the GUI language selector, or `set-language`. GUI usage, troubleshooting, and diagnostic help links open local documents in the selected language. Device names, identifiers, and raw logs retain their original text.

## Common commands

Run these from any directory. If `~/bin` is on your PATH, you can also use `padpilot-cli` directly. Installation, update, and development scripts still run from the source directory.

```bash
# Status and settings
"$HOME/bin/padpilot-cli" status --json
"$HOME/bin/padpilot-cli" gui
"$HOME/bin/padpilot-cli" set-language en        # Also accepts zh-Hant or ja

# Operating modes: choose one
"$HOME/bin/padpilot-cli" set-mode automatic
"$HOME/bin/padpilot-cli" set-mode manual_only
"$HOME/bin/padpilot-cli" set-mode prefer_ipad

# Manual actions: choose as needed
"$HOME/bin/padpilot-cli" action use_ipad_secondary
"$HOME/bin/padpilot-cli" action use_ipad_main
"$HOME/bin/padpilot-cli" action disconnect_ipad
"$HOME/bin/padpilot-cli" action reconnect_sidecar
"$HOME/bin/padpilot-cli" action refresh
"$HOME/bin/padpilot-cli" action reset           # Clear temporary override and cooldown

# Background service and launch at login
"$HOME/bin/padpilot-cli" stop
"$HOME/bin/padpilot-cli" start
"$HOME/bin/padpilot-cli" exit                  # Stop service and hide the PadPilot menu
"$HOME/bin/padpilot-cli" autostart status
"$HOME/bin/padpilot-cli" autostart toggle

# Version and complete command help
"$HOME/bin/padpilot-cli" --version
"$HOME/bin/padpilot-cli" --help
```

Keep a backup of the prior source, save and close settings, then update the source and rerun `./scripts/install.sh --check`, `./scripts/install.sh`, and `"$HOME/bin/padpilot-cli" status`. This also rebuilds the native app. The GUI About page, CLI `--version`, and app share one version source. About also includes GitHub and donation links; donation buttons remain disabled until recipient URLs are configured. The old app is recoverable from Trash, but restoring the app alone does not restore its referenced source.

## Limitations and troubleshooting

- **Sidecar is a prerequisite**: PadPilot does not add Sidecar support to incompatible devices or control Universal Control's keyboard and pointer routing.
- **Connection timing depends on macOS and the devices**: A USB notification, a 4-second debounce, or a successful command submission does not mean the iPad is displaying the desktop. Fallback takes priority during cooldown.
- **Headless setups still need validation**: Cold boot, sleep/wake, hub, and multiple-device combinations have not been comprehensively tested. No iPad display is provided before user login. Disabling FileVault and enabling automatic login are not guaranteed setup steps.
- **Other display controllers can conflict**: If another tool repeatedly changes the main display or Sidecar state, switch to `manual_only` and inspect the transition reasons and logs.

Configuration and runtime state normally live in `~/Library/Application Support/PadPilot/`; logs are in `~/Library/Logs/PadPilot/`. When reporting a problem, include versions, connection type, reproduction steps, and relevant logs. Redact device serials, UUIDs, accounts, and personal paths first.

Private directories use `0700`; configuration, status, sockets, and logs use `0600`. Foreign-owned or linked state paths are rejected. New IPC logs omit pairing payloads; existing historical logs are not erased. See the [release acceptance matrix (Traditional Chinese)](docs/development/2026-09-11-release-readiness.md) for tested environments and hardware scenarios still marked `unknown`.

## Uninstall

Paste this into Terminal to choose what to remove:

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
