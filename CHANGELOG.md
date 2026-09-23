# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0-dev.3] - 2026-09-23

Development prerelease for Apple Silicon and macOS 14+, with a directly downloadable SidecarSwitch DMG and three-language installation guidance.

### Changed
- Correct website language URLs and add canonical URLs and a three-page sitemap.

### Fixed
- Package standard macOS icon sizes directly in the ICNS container when the system icon encoder cannot rebuild even its own decoded icons.
- Select only published releases containing a matching SidecarSwitch DMG; report when no prebuilt download is available.

## [0.1.0-dev.2] - 2026-09-20

Second public development prerelease. Includes the following changes since `v0.1.0-dev.1`.

### Added
- A three-language DMG installation layout with a BetterDisplay download shortcut, drag-to-Applications guidance, first-launch approval steps, and an offline installation guide.
- Per-display controls in Connected displays to include or exclude a monitor from physical-display detection, saved by display UUID, with a reset to automatic detection. Generic placeholders remain excluded by default; Sidecar and virtual fallback roles are unchanged.
- Contact email in the website's ECPay support section.

### Fixed
- Switching to Manual only can cancel a blocked connection round without waiting for hardware discovery or a connection command to return. Stop subsequent retries and main-display changes, discard older queued controls and UI callbacks, and keep explicit new connection requests usable. Commands already sent to macOS may still finish.
- Keep status and Manual only requests responsive during slow IPC operations; preserve connection-request coalescing and prevent cancelled boot work from restarting.
- Recover from release-update failure even when the replacement CLI cannot run, after independently confirming the replacement service and processes have stopped. Preserve the app and backup if shutdown cannot be verified.
- Align BetterDisplay requirements across the three languages: current SidecarSwitch features work without Pro or a trial; BetterDisplay's own license terms still apply.
- Make troubleshooting commands usable from a DMG installation without a source checkout or separate Python installation; distinguish source-only repair steps.
- Remove obsolete private-testing and repository-access wording, clarify how to request a security contact without publishing vulnerability details, and document the published development release below.

### Changed
- Remove the remaining development-document directory and stop tracking local agent instructions.

## [0.1.0-dev.1] - 2026-09-16

First public GitHub development prerelease, built from `27ce07453dbed94fb2c4063a482e3705974c26b9`. Published at `2026-09-16 16:16:53 UTC` (`2026-09-17 00:16:53` in Taiwan). This is a prerelease, not a stable `0.1.0` release.

### Added
- Relocatable **Apple Silicon / macOS 14+** app with bundled CPython and native Swift components. Published DMG, ZIP, `SHA256SUMS`, and `build-info.json`; users do not need a compiler, Homebrew, or a separate Python installation.
- Shared bundled/external Python selection for the app, CLI, and background service, with a bundled-runtime recovery command if an external Python is missing.
- A configurable global connection shortcut and bounded one-shot connection requests. Fresh installations use Manual only with optional headless boot connection enabled: search for up to three 30-second rounds, then make at most one bounded connection round. A later disconnect does not start another manual-mode connection round.
- Automatic USB event wakeup, configurable iPad inference, and explicit saved pairing selection. Saved Sidecar identities take priority; ambiguous or incomplete discovery does not guess a control target.
- Traditional Chinese, English, and Japanese native settings, diagnostics, pairing management, About content, and user guides; localized help links pinned to the source revision.
- Public three-language introduction website with GitHub Pages deployment, illustrated setup guidance, and a real-device demonstration video.
- Optional external support links for PayPal, Ko-fi, O'Pay, and ECPay in the relevant README, About, and website surfaces.
- Software, native-menu, layout, installer, security, and release-relocation checks, plus macOS Python 3.10/3.14 CI and an independent history privacy gate. Tag-triggered builds publish development release assets.

### Changed
- Replace the SwiftBar integration and Tk settings window with a native AppKit menu and SwiftUI settings, retaining the shared Python state engine and CLI/IPC actions.
- Reuse the existing settings window and preserve its page and drafts. Opening the app shows settings and the menu; login/background startup shows the menu only. Use distinct Manual only and stopped-service icons and the project artwork for the app icon.
- Use an app-bundled `SMAppService` login agent. Exit stops display automation; an enabled native login service watches for the app moving to Trash and unregisters itself. No external LaunchAgent plist is installed by this version.
- Provide source and release installers, explicit dependency-install choices, custom Python/BetterDisplay paths, and uninstall previews. Preserve existing preferences and app locations; retain settings, logs, and shared dependencies by default.
- Change the license from MIT to PolyForm Noncommercial 1.0.0 with attribution in `NOTICE`, bundled with the app. Rights to copies previously obtained under MIT remain unchanged.

### Fixed
- Pause automatic Sidecar retries after repeated failure instead of repeatedly reconnecting to an unavailable cached target. Retain the physical or virtual fallback, including after iPad takeover.
- Require both the configured Sidecar session and its online display before takeover. Preserve verified session/display identity through discovery loss and avoid changing displays when identity is unknown.
- Use configuration revisions to reject stale GUI changes and retain the original revision of unsaved drafts. Reject malformed configuration without silently enabling automation or overwriting it.
- Verify daemon ownership and startup handshakes, use shared primary/fallback state-file selection, and restore prior installation state on supported failure paths.
- Harden state, log, and socket permissions; reject foreign or linked state paths; omit IPC payloads from logs; and restrict stop/uninstall operations to verified owned targets.
- Handle dangling integration symlinks on Python 3.10, resolve custom BetterDisplay paths at startup, and check both installation shell scripts in release validation.

### Limitations
- BetterDisplay must be installed and running separately; its built-in CLI is sufficient.
- This release is ad-hoc signed, without Developer ID signing or Apple notarization, and has no Intel build.
- Software and relocation checks do not establish Sidecar, USB hotplug, sleep/wake, or cold-boot acceptance on every user's hardware. FileVault unlock and pre-login display takeover are not supported.

## [0.1.0] - 2026-09-10

Historical internal development record retained from the original changelog; this was not a tagged public stable release. The SwiftBar, Tk, and MIT descriptions below describe that earlier state.

### Added
- **Display State Machine**:
  - Automatic detection and negotiation between physical monitors, USB/Wireless Sidecar iPad, and BetterDisplay virtual screens.
  - User override preservation with hardware **Topology Generation Tracking**.
  - **Single-Flight Transition Lock** preventing race conditions during concurrent USB insertion and display wake events.
  - Physical display flicker debouncing (4.0s) and Sidecar connection cooldown protection (3 attempts with 30s cooldown).
- **macOS Menu Bar Integration**:
  - Dynamic SwiftBar plugin with status indicators (`🖥️`, `📱`, `◻️`, `⚠️`, `⏸️`).
  - Ultra-fast (< 5ms) atomic snapshot reading with zero-overhead background sync.
- **Card-Style GUI**:
  - Native Tkinter Card UI for pairing, multi-device management, diagnostics, and settings.
  - Comprehensive health checks (FileVault, automatic login, BetterDisplay permissions, LaunchAgent autostart).
- **CLI Management**:
  - Full-featured `sidecarswitch-cli` for service lifecycle, pairing wizards, mode switching, status query, and inspection.
- **Open Source Preparation**:
  - Standard MIT License.
  - Restructured documentation, troubleshooting guide, and installation guides.
  - GitHub issue forms and PR templates.

[Unreleased]: https://github.com/kcayut/SidecarSwitch/compare/v0.1.0-dev.3...main
[0.1.0-dev.3]: https://github.com/kcayut/SidecarSwitch/releases/tag/v0.1.0-dev.3
[0.1.0-dev.1]: https://github.com/kcayut/SidecarSwitch/releases/tag/v0.1.0-dev.1
