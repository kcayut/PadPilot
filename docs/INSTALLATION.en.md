# PadPilot installation guide

[繁體中文](INSTALLATION.md) | **English** | [日本語](INSTALLATION.ja.md) · [Documentation](README.en.md)

PadPilot provides a **Swift/AppKit menu app, Python core, and Tk settings window**. The installer builds, installs, and starts `~/Applications/PadPilot.app`. No additional pip or Swift packages are needed.

## Prepare your environment

- macOS 14+; Apple Silicon is the primary validation environment.
- Python 3.10+. Settings require `tkinter` in that same Python environment. The installer does not install Python or Tk; there are no pip packages to install.
- Apple Command Line Tools to compile the app locally. Full Xcode is not required.
- [BetterDisplay](https://github.com/waydabber/BetterDisplay) with working CLI control. Check its documentation for licensing requirements.
- A Sidecar-compatible iPad. First confirm manual connection through macOS Screen Mirroring.

```bash
xcode-select --install
python3 --version
python3 -c "import tkinter"
xcrun --find swiftc
```

Missing Tk produces a warning: the daemon, CLI, and native menu can still be installed, but settings-window actions are disabled. Install Tk support matching the selected Python; do not mix Python installations. Sidecar requires a logged-in user session. PadPilot cannot take over before FileVault unlock. See [troubleshooting](TROUBLESHOOTING.en.md#filevault).

## Install or upgrade

Run from the project directory:

```bash
./scripts/install.sh --check
./scripts/install.sh
./bin/padpilot-cli status

# Automatically accept installation of missing BetterDisplay through Homebrew:
./scripts/install.sh --yes
```

`--check` is read-only: it does not invoke Homebrew, create configuration or logs, compile, start services, scan hardware, or change displays. Missing required components return a nonzero exit code; missing Tk is only a warning. Successful BetterDisplay CLI help does not verify its license or Sidecar availability. The GitHub repository is private and requires access; an existing source folder also works.

The installer:

1. Checks macOS 14+, Python 3.10+, Tk availability, the Swift compiler, BetterDisplay, and its CLI response. If BetterDisplay is missing, it can offer Homebrew installation. Refusal, installation failure, or an unusable CLI stops the process without claiming success.
2. Compiles and locally signs the app, then installs it in `~/Applications/PadPilot.app`.
3. Stops the previous service through the shared CLI, closes the previous native menu, and preserves settings and pairings.
4. Cleans up old integration links owned by this checkout, moving removed items to Trash without modifying other apps.
5. Preserves the launch-at-login preference and uses the shared `padpilot-cli autostart enable` flow when enabled, then starts the Python service and menu. A first installation enables launch at login. Success requires a structured socket reply from this checkout's daemon. Failure attempts to restore the prior LaunchAgent and settings; incomplete rollback is explicitly reported. A failed standalone start terminates the child it created.
6. Creates a CLI shortcut if `~/bin` exists and the name is available.

The app records the selected Python and source paths. **Keep that Python environment and source folder in place.** Python is not bundled. Reinstall after moving them; the installer refuses to overwrite an app or LaunchAgent owned by another checkout. Uninstall from the original location before moving. Developer ID signing, notarization, and automatic updates are not included.

## Open and pair

```bash
open -a BetterDisplay
open "$HOME/Applications/PadPilot.app"
```

Choose Settings & Pairing to discover devices, save pairings, and select the control target. Deleting a pairing requires confirmation. Alternatively:

```bash
./bin/padpilot-cli pair --interactive
./bin/padpilot-cli gui
./bin/padpilot-cli gui diagnostics
```

Configuration is stored in `~/Library/Application Support/PadPilot/config.json`. Existing pairings are preserved.

## Update and restore

Back up the prior source, save your changes, and close settings. After updating the source, repeat preflight → installation → status; the native binary is rebuilt too. The GUI About page displays `v0.1.0`, sharing `core.__version__` with the CLI and app. It also includes a GitHub link and inactive donation placeholders.

The installer preserves configuration and moves the previous app to Trash. It does not download updates, create Git tags, or publish releases. To downgrade to a compatible version, restore its source and reinstall. Restoring only the app from Trash does not restore the source it references.

## Local privacy and permissions

PadPilot configuration, runtime, and log directories use `0700`; configuration, status, IPC sockets, and logs use `0600`. Foreign-owned paths, symlinks, and multiply hard-linked state files are rejected, including under the `/tmp/PadPilot` fallback. Unsafe paths stop the operation rather than being deleted or taken over. See [safe startup troubleshooting](TROUBLESHOOTING.en.md#safe-startup).

IPC logs record known command names, not pairing payloads. Historical logs may contain device information; redact it before sharing. Uninstallation does not use broad process-name termination or remove another checkout's CLI link.

## Daily use and development

```bash
./bin/padpilot-cli start            # Start the service and show the menu
./bin/padpilot-cli stop             # Stop the service, keep the menu
./bin/padpilot-cli exit             # Stop the service and close the menu
./bin/padpilot-cli autostart status
./bin/padpilot-cli autostart toggle
python3 scripts/build_app.py        # Build build/PadPilot.app only; no install/start
./bin/padpilot-cli menu-json        # Read the menu model without a hardware scan
```

Tests cover native menu decoding in three languages, submenus, checked/disabled states, and the command allowlist:

```bash
python3 -m unittest discover -s tests
python3 scripts/check_gui_layout.py
python3 scripts/check_release.py --gui
```

Local release checks also cover shell syntax, plist validity, version consistency, ResourceWarning, and privacy patterns in current files and Git history. Reports are written to `build/release-check.json` and `build/privacy-scan.json`, without matched values. Reviewed historical exceptions are listed separately; new findings still return exit code 1 even if software tests pass. Omit `--gui` without a desktop session; GUI validation is then unverified. These checks do not replace [physical acceptance](development/2026-09-11-release-readiness.en.md).

## Uninstall

```bash
./scripts/uninstall.sh
./scripts/uninstall.sh --purge
```

Standard removal stops this checkout's service and menu, moves its app, LaunchAgent, and CLI link to Trash, and clears status snapshots. Configuration and logs remain; `--purge` also moves both to Trash and is recoverable. Source, BetterDisplay, other apps, and virtual displays are preserved.
