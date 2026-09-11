# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed
- Restore the previous app, LaunchAgent, and pre-install running state after installation failure; purge recoverable fallback configuration too.
- Share latest-file selection across primary/fallback readers and installer preflight; reject malformed configuration without silently enabling automation or overwriting the original.
- Preserve verified Sidecar session/display identity during discovery loss, retain errors across repeated identifier queries, and avoid switching displays when identity is unknown.
- Send GUI configuration revisions for optimistic concurrency; preserve the original revision of unsaved rename drafts.
- Treat FileVault and automatic login as informational checks, interpolate virtual-display names correctly, and check both shell scripts independently in release gates.
- Align the PR privacy checklist with the documented release scanner.

### Changed
- Added a copy-and-paste source installer and interactive Python/Tk, BetterDisplay, and Apple build-tool setup with custom paths and explicit dependency-install consent.
- Added uninstall previews and separate configuration, log, managed-source, and recorded-dependency choices; existing shared dependencies remain preserved by default.
- App, launchd, and the installed CLI shortcut use the selected Python; custom BetterDisplay paths also work during startup, and setup protects open settings windows.
- GUI help and diagnostic links now open localized GitHub documentation pinned to the source revision; source archives retain the revision and copies without revision metadata use the matching version tag.
- Changed licensing from MIT to PolyForm Noncommercial 1.0.0, with required attribution to kcayut in NOTICE; updated the three READMEs and About page, and bundled LICENSE/NOTICE in built apps. Previously granted MIT rights remain unchanged.
- Added a localized About page with the shared version, GitHub link, and disabled Buy Me a Coffee/PayPal placeholders until recipient URLs are configured; moved the version out of the sidebar.
- Settings GUI displays the shared application version; usage and diagnostic help links open bundled guides in the selected language.
- Added Japanese README, English/Japanese documentation, language navigation, and a clearly labeled development archive.
- Accepted six reviewed historical private-path findings by exact commit, file, and category; current files and new historical findings remain blocking.
- Added read-only installer preflight, optional Tk GUI support, shared launchd startup with a verified daemon handshake, and failure rollback.
- Hardened private state/log/socket permissions, rejected foreign and linked state paths, removed IPC payload logging, and limited stop/uninstall to verified owned targets.
- Added local release gates, redacted tree/history privacy findings, installer/security regression tests, and an explicit physical acceptance checklist.
- Added GitHub Actions for macOS/Python 3.10 and 3.14 software checks plus an independent full-history privacy gate. Repository access is private; public publishing remains deferred.
- Replaced the SwiftBar plugin with a native Swift/AppKit menu app, retaining the Python state engine, CLI, Tk settings, and shared translations.
- Added `menu-json`, native menu contract tests, and a dependency-free local app build.
- Installer builds PadPilot.app and preserves existing preferences; owned legacy plugin links and uninstalled app integrations go to Trash.
- App still references the local Python and source checkout; standalone Python bundling, release signing, and notarization are not included.

## [0.1.0] - 2026-09-10

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
  - Full-featured `padpilot-cli` for service lifecycle, pairing wizards, mode switching, status query, and inspection.
- **Open Source Preparation**:
  - Standard MIT License.
  - Restructured documentation, troubleshooting guide, and installation guides.
  - GitHub issue forms and PR templates.
