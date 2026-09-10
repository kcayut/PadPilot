# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed
- Replaced the SwiftBar plugin with a native Swift/AppKit menu app, retaining the Python state engine, CLI, Tk settings, and shared translations.
- Added `menu-json`, native menu contract tests, and a dependency-free local app build.
- Installer now builds PadPilot.app and preserves existing preferences; owned legacy plugin links and uninstalled app integrations go to Trash. SwiftBar is no longer required.
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
