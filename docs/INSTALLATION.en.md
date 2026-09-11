# PadPilot installation guide

[繁體中文](INSTALLATION.md) | **English** | [日本語](INSTALLATION.ja.md) · [Documentation](README.en.md)

PadPilot provides a **Swift/AppKit menu, native SwiftUI settings window, and Python core**. The installer builds, installs, and starts `~/Applications/PadPilot.app`. No additional pip or Swift packages are needed.

Before installing or uninstalling, save your changes and close PadPilot settings and diagnostics windows; an open window stops the operation with instructions to retry.

## Prepare your environment

- macOS 14+; Apple Silicon is the primary validation environment.
- Python 3.10+ for the background core. Settings are built into the native app.
- Apple Command Line Tools to compile locally. Full Xcode is not required.
- [BetterDisplay](https://github.com/waydabber/BetterDisplay) with working CLI control, subject to its licensing requirements.
- A Sidecar-compatible iPad. First confirm manual connection through macOS Screen Mirroring.

You do not need to install each dependency first: the installer detects them, then offers reuse, a custom path, or installation. Sidecar needs a logged-in user session; PadPilot cannot take over before FileVault unlock. See [troubleshooting](TROUBLESHOOTING.en.md#filevault).

## Copy and paste installation

Paste the entire block into Terminal:

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

**Publication prerequisite:** [kcayut/PadPilot](https://github.com/kcayut/PadPilot) must be public and these scripts must be published on `main`. A private repository or missing script returns 404; until publication, use an authorized source copy and the local installation steps below. The command downloads the complete script to a temporary file before running it; the source archive is also checked for unsafe paths and file types before extraction.

Downloading requires neither Git nor Python. Source is kept in `~/Applications/PadPilot-source`; an unrelated existing folder is never overwritten. Rerunning reuses that source and resumes installation without downloading updates. Keep `.padpilot-install.json`: it records the managed source and newly installed dependencies for the uninstaller.

## Dependency choices and local installation

With an existing source copy, run `./scripts/install.sh` from its project directory. After using the download command above:

```bash
cd "$HOME/Applications/PadPilot-source"
./scripts/install.sh --check
./scripts/install.sh
"$HOME/bin/padpilot-cli" status
```

`--check` is a complete read-only preflight: it does not invoke Homebrew, create configuration or logs, compile, start services, scan hardware, or change displays. Missing required components return a nonzero exit code.

Interactive installation shows detected Python and BetterDisplay paths, then lets you reuse them, enter another path, or install missing dependencies. Installing Homebrew or using it to install dependencies requires consent; any administrator password is handled by the official installer. Apple Command Line Tools must finish in the macOS installation dialog before you rerun PadPilot's installer.

```bash
# Select an existing environment; keep quotes around paths containing spaces.
./scripts/install.sh --python "/path/to/python3" --betterdisplay-path "/Applications/BetterDisplay.app"

# Noninteractive: reuse existing dependencies; stop if required ones are missing.
./scripts/install.sh --yes

# Explicitly allow installation of missing dependencies through Homebrew.
./scripts/install.sh --yes --install-deps
```

`--python` accepts a Python executable; `--betterdisplay-path` accepts an `.app` folder or CLI executable. `--yes` does not authorize third-party installation and stops if required dependencies are missing: install them manually or add `--install-deps`. Successful BetterDisplay CLI help does not verify its license, Sidecar, or a working display.

Homebrew installation uses Python 3.14, plus the official [betterdisplay cask](https://formulae.brew.sh/cask/betterdisplay). `--yes --install-deps` may still require an administrator password or an Apple installation dialog; it does not guarantee unattended setup.

The installer builds and locally signs `~/Applications/PadPilot.app`, preserving configuration, pairings, and login preferences; a first install enables launch at login. After restarting and signing in to macOS, the daemon and menu bar start automatically without rerunning the installer. It records LaunchAgent and service state before stopping the old service and menu through the shared CLI. Success requires a structured handshake from the new daemon. Failed startup attempts to restore the previous app, LaunchAgent, and running state; any rollback failure is reported explicitly.

The installer attempts to create `~/bin/padpilot-cli` with the selected Python. An entry owned by another program is preserved; use `"$HOME/Applications/PadPilot.app/Contents/Resources/padpilot-cli"` in that case. **Keep the selected Python environment and source folder in place.** The app references both. Reinstall after moving them; an app or LaunchAgent owned by another source path is not taken over. Bundled Python, Developer ID signing, notarization, and automatic updates are not included.

## Open and pair

```bash
open -a BetterDisplay
open "$HOME/Applications/PadPilot.app"
```

Choose Settings & Pairing to discover devices, save pairings, and select the control target. Deleting a pairing requires confirmation. Alternatively:

```bash
"$HOME/bin/padpilot-cli" pair --interactive
"$HOME/bin/padpilot-cli" gui
"$HOME/bin/padpilot-cli" gui diagnostics
```

Configuration is stored in `~/Library/Application Support/PadPilot/config.json`. Existing pairings are preserved.

If writing there fails, PadPilot uses `/tmp/PadPilot/config.json`. The daemon, CLI, GUI, menu, and installer preflight select the most recently written file across both locations; status snapshots follow the same rule. The fallback is temporary storage, not a durable backup: repair the primary location's write access. Invalid configuration is never reset or overwritten automatically. Service startup fails, and the GUI reports an error and disables saving. Back up the original file, then repair its JSON or restore a known valid configuration.

## Update and restore

Back up the prior source, save your changes, and close settings. After updating the source, repeat preflight → installation → status; the native binary is rebuilt too. The GUI About page displays `v0.1.0`, sharing `core.__version__` with the CLI and app. It also includes a GitHub link and inactive donation placeholders.

The installer preserves configuration and moves the previous app to Trash. It does not download updates, create Git tags, or publish releases. Restoring only the app from Trash does not restore the source it references.

## Local privacy and permissions

PadPilot configuration, runtime, and log directories use `0700`; configuration, status, IPC sockets, and logs use `0600`. Foreign-owned paths, symlinks, and multiply hard-linked state files are rejected, including under the `/tmp/PadPilot` fallback. Unsafe paths stop the operation rather than being deleted or taken over. See [safe startup troubleshooting](TROUBLESHOOTING.en.md#safe-startup).

IPC logs record known command names, not pairing payloads. Historical logs may contain device information; redact it before sharing. Uninstallation does not use broad process-name termination or remove another checkout's CLI link.

## Daily use and development

```bash
"$HOME/bin/padpilot-cli" start            # Start the service and show the menu
"$HOME/bin/padpilot-cli" stop             # Stop the service, keep the menu
"$HOME/bin/padpilot-cli" exit             # Stop the service and close the menu
"$HOME/bin/padpilot-cli" autostart status
"$HOME/bin/padpilot-cli" autostart toggle
python3 scripts/build_app.py        # Build build/PadPilot.app only; no install/start
"$HOME/bin/padpilot-cli" menu-json        # Read the menu model without a hardware scan
```

Tests cover native menu decoding in three languages, submenus, checked/disabled states, and the command allowlist:

```bash
python3 -m unittest discover -s tests
python3 scripts/check_gui_layout.py
python3 scripts/check_release.py --gui
```

Local release checks also cover shell syntax, plist validity, version consistency, ResourceWarning, and privacy patterns in current files and Git history. Reports are written to `build/release-check.json` and `build/privacy-scan.json`, without matched values. Reviewed historical exceptions are listed separately; new findings still return exit code 1 even if software tests pass. Omit `--gui` without a desktop session; GUI validation is then unverified. These checks do not replace [physical acceptance (Traditional Chinese)](development/2026-09-11-release-readiness.md).

## Uninstall

Run this from any directory:

```bash
/bin/bash "$HOME/Applications/PadPilot-source/scripts/uninstall.sh"
```

For a manually obtained source copy, run `./scripts/uninstall.sh` from its original project directory. The wizard asks separately about settings/pairings, logs, managed source, and each third-party dependency newly installed by the installer. **All are kept by default.** It presents a complete removal summary for confirmation before stopping this checkout's service and menu and removing its app, LaunchAgent, and CLI integration.

| Option | Behavior |
| --- | --- |
| `--yes` | Remove the PadPilot app and integrations noninteractively; keep settings, logs, source, and third-party dependencies. |
| `--yes --purge` | Also remove settings/pairings and logs, including any `/tmp/PadPilot/config.json` fallback. |
| `--remove-config` / `--remove-logs` | Select configuration or logs individually. |
| `--remove-source` | Also remove the downloader-managed `~/Applications/PadPilot-source`; manually obtained source is never deleted automatically. |
| `--remove-dependency NAME` | Select a Homebrew item recorded as newly installed in the receipt; repeat for multiple items. Pre-existing software without that record is not uninstalled automatically. |

The app, integrations, settings, logs, and selected source are moved to Trash and can be recovered. Third-party dependencies are uninstalled through Homebrew, outside PadPilot's Trash recovery; `autoremove` and `--zap` are not used. Python required by other Homebrew packages is kept. Homebrew itself, Apple Command Line Tools, system Python, pre-existing BetterDisplay, and virtual displays are not removed along with PadPilot.

Removing BetterDisplay may disconnect Sidecar or virtual displays and requires an additional confirmation. Noninteractive removal also needs explicit `--allow-display-disconnect`. Only remove Python or source when PadPilot is no longer needed; if source is retained, rerunning the installer restores the installation.
