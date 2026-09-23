# SidecarSwitch installation guide

[繁體中文](INSTALLATION.md) | **English** | [日本語](INSTALLATION.ja.md) · [Documentation](README.en.md)

## Download a prebuilt app (recommended)

Releases support Apple Silicon and macOS 14+, with no Intel build. Download the `.dmg` from [GitHub Releases](https://github.com/kcayut/PadPilot/releases), drag `SidecarSwitch.app` into Applications, and open it. ZIP, `SHA256SUMS`, and `build-info.json` are also provided. Swift, CPython, its standard library, and SidecarSwitch’s core are bundled; no user-side compiler or pip packages are needed.

Double-click the installed app to open its control window and menu bar icon together. Closing the window keeps the menu bar icon available; double-click again to reopen the window. Login and background startup show only the menu bar icon.

New installations default to Manual only with “Connect iPad at boot when no monitor is attached” enabled. With launch at login enabled, it searches after login for up to three 30-second rounds (90 seconds total), stopping if none finds the target. Finding it without a physical monitor requests at most one connection round (up to three attempts). Later connections require a menu command or global shortcut; disconnection does not trigger reconnection. Restarting the app within the same boot does not retry. Updates preserve the existing mode and shortcut. This option cannot guarantee that the iPad will connect; see the [connection rules](ARCHITECTURE.en.md#global-connection-shortcut).

**Development releases use ad-hoc signing without Developer ID signing or Apple notarization.** For developer-verification or malware-check warnings, verify the source and follow [Apple’s instructions](https://support.apple.com/en-us/102445) for Privacy & Security → Open Anyway. For a damaged-app warning, download again and check SHA-256. Do not disable Gatekeeper globally or assume every warning is harmless.

Install and run the BetterDisplay app separately. Current SidecarSwitch features work with its free mode; Pro or a trial is not required. The separate `betterdisplaycli` is optional; the app’s built-in CLI is sufficient. Discovery covers `/Applications`, `~/Applications`, and locations registered with LaunchServices. Advanced settings also accept a custom app or CLI path.

### Script installation and Python selection

Save and close SidecarSwitch settings. Download the official installer and run it; no existing Python is needed:

```bash
(
  set -e
  installer="$(mktemp -t sidecarswitch-release-install)"
  trap 'rm -f "$installer"' EXIT
  curl --fail --location --proto '=https' --tlsv1.2 \
    https://raw.githubusercontent.com/kcayut/PadPilot/main/scripts/install_release.sh \
    --output "$installer"
  /bin/bash "$installer"
)
```

The installer selects the newest published release including prereleases, checks SHA-256, mounts the DMG read-only, and runs its bundled Python. The default destination is `/Applications/SidecarSwitch.app`. If it is not writable, use `--target "$HOME/Applications/SidecarSwitch.app"`; sudo is unnecessary. It stops if no release exists, without switching to source installation.

- `--bundled`: use bundled CPython; `--yes` without a Python option also selects this.
- `--python /absolute/path/python3`: use Apple Silicon CPython 3.10+ after version, architecture, and required-module validation.
- `--tag v0.1.0-dev.1`: select an existing release explicitly.

On a fresh installation, open the app to start its service. Updates unregister the native login service before replacing the app, then restore previously enabled login startup and running state. Items blocked by macOS or awaiting approval are not automatically requested again. Settings and pairings remain; script updates still ask for Python again. Failed installation attempts to restore the app, preferences, and service. Before changing installation locations, use the CLI below to remove the original installation while keeping settings.

### Change or recover Python afterward

The GUI, CLI, daemon, and launch-at-login entry share the choice stored in `~/Library/Application Support/SidecarSwitch/python-runtime.json`, outside the sealed app. Quit SidecarSwitch first:

```bash
"/Applications/SidecarSwitch.app/Contents/Resources/sidecarswitch-cli" --bundled-cli runtime external --python /absolute/path/python3
"/Applications/SidecarSwitch.app/Contents/Resources/sidecarswitch-cli" --bundled-cli runtime bundled
"/Applications/SidecarSwitch.app/Contents/Resources/sidecarswitch-cli" runtime status
```

Choose one of the first two commands: external Python or bundled Python. `--bundled-cli` also recovers from a deleted external Python. Do not select Python inside another SidecarSwitch.app.

**Remove a release by choosing Exit from the menu, then dragging SidecarSwitch.app from Applications to Trash.** Exit stops display automation; the enabled native login service keeps an event-based watch on the app without polling. Moving the app to Trash automatically unregisters and stops that service. The trashed app will not start background Python. Settings, pairings, and logs remain. Its name may take time to disappear from Login Items.

Optional CLI cleanup, for example to remove data too or change installation locations: settings and logs are kept by default; add `--purge` to move them to Trash. Run this before removing the app:

```bash
"/Applications/SidecarSwitch.app/Contents/Resources/sidecarswitch-cli" --bundled-cli uninstall --yes
```

### Maintainers: automatic tag releases

These commands assume the GitHub remote is named `github`. A direct GitHub clone usually names it `origin`; check `git remote -v` and substitute the correct name. Pushing to Gitea does not trigger GitHub Actions.

```bash
git tag v0.1.0-dev.1
git push github v0.1.0-dev.1
```

Commit the intended changes first. Tags support `vX.Y.Z` and `vX.Y.Z-dev.N` / `alpha.N` / `beta.N` / `rc.N`. **Push the tag to GitHub; a local tag alone does not trigger a build.** The ARM workflow runs software checks, compilation, packaging, and relocation tests, then automatically publishes a prerelease after all assets are uploaded. No Apple certificate or manual approval is needed. Published releases are not overwritten; use a new tag for fixes. Failed drafts can be rerun. Physical-device acceptance remains unknown.

For the same local artifacts, use Python 3.12+ and Apple build tools. In a build virtual environment, run `python3 -m pip install -r scripts/dmg-requirements.txt`, then `python3 scripts/build_release.py --tag v0.1.0-dev.1`. Output is `dist/<tag>/`. The DMG layout packages are build tools only and are not bundled in the app runtime; `--no-dmg` skips the DMG and this dependency. CPython’s upstream URL and SHA-256 are pinned in `scripts/python-runtime.json`; its licenses remain included. The full tag and build commit are recorded in the artifacts.

<a id="source-installation"></a>
## Source installation (development)

The remaining steps apply only to a locally compiled source installation.

SidecarSwitch provides a **Swift/AppKit menu, native SwiftUI settings window, and Python core**. The installer builds, installs, and starts `~/Applications/SidecarSwitch.app`. No additional pip or Swift packages are needed.

Before installing or uninstalling, save your changes and close SidecarSwitch settings and diagnostics windows; an open window stops the operation with instructions to retry.

## Prepare your environment

- macOS 14+; Apple Silicon is the primary validation environment.
- Python 3.10+ for the background core. Settings are built into the native app.
- Apple Command Line Tools to compile locally. Full Xcode is not required.
- [BetterDisplay](https://github.com/waydabber/BetterDisplay) with working CLI control, subject to its licensing requirements.
- A Sidecar-compatible iPad. First confirm manual connection through macOS Screen Mirroring.

You do not need to install each dependency first: the installer detects them, then offers reuse, a custom path, or installation. Sidecar needs a logged-in user session; SidecarSwitch cannot take over before FileVault unlock. See [troubleshooting](TROUBLESHOOTING.en.md#filevault).

## Copy and paste installation

Paste the entire block into Terminal:

```bash
(
  set -e
  installer="$(mktemp -t sidecarswitch-install)"
  trap 'rm -f "$installer"' EXIT
  curl --fail --location --proto '=https' --tlsv1.2 \
    https://raw.githubusercontent.com/kcayut/PadPilot/main/scripts/bootstrap.sh \
    --output "$installer"
  /bin/bash "$installer"
)
```

**Download behavior:** The script is downloaded from `main` in [SidecarSwitch](https://github.com/kcayut/PadPilot). For a 404 response, check the URL or use the DMG from [Releases](https://github.com/kcayut/PadPilot/releases). The complete script is downloaded to a temporary file before running it; source archives are checked for unsafe paths and file types before extraction.

Downloading requires neither Git nor Python. Source is kept in `~/Applications/SidecarSwitch-source`; an unrelated existing folder is never overwritten. Rerunning reuses that source and resumes installation without downloading updates. Keep `.sidecarswitch-install.json`: it records the managed source and newly installed dependencies for the uninstaller.

## Dependency choices and local installation

With an existing source copy, run `./scripts/install.sh` from its project directory. After using the download command above:

```bash
cd "$HOME/Applications/SidecarSwitch-source"
./scripts/install.sh --check
./scripts/install.sh
"$HOME/bin/sidecarswitch-cli" status
```

`--check` is a complete read-only preflight: it does not invoke Homebrew, create configuration or logs, compile, start services, scan hardware, or change displays. Missing required components return a nonzero exit code.

Interactive installation shows detected Python and BetterDisplay paths, then lets you reuse them, enter another path, or install missing dependencies. Installing Homebrew or using it to install dependencies requires consent; any administrator password is handled by the official installer. Apple Command Line Tools must finish in the macOS installation dialog before you rerun SidecarSwitch's installer.

```bash
# Select an existing environment; keep quotes around paths containing spaces.
./scripts/install.sh --python "/path/to/python3" --betterdisplay-path "/Applications/BetterDisplay.app"

# Noninteractive: reuse existing dependencies; stop if required ones are missing.
./scripts/install.sh --yes

# Explicitly allow installation of missing dependencies through Homebrew.
./scripts/install.sh --yes --install-deps
```

`--python` accepts a Python executable; `--betterdisplay-path` accepts an `.app` folder or CLI executable. `--yes` does not authorize third-party installation and stops if required dependencies are missing: install them manually or add `--install-deps`. Successful BetterDisplay CLI help does not verify Sidecar or a working display.

Homebrew installation uses Python 3.14, plus the official [betterdisplay cask](https://formulae.brew.sh/cask/betterdisplay). `--yes --install-deps` may still require an administrator password or an Apple installation dialog; it does not guarantee unattended setup.

The installer builds and locally signs `~/Applications/SidecarSwitch.app`, preserving settings and pairings. First startup registers the bundled login service with macOS. If approval is required, allow SidecarSwitch in System Settings → General → Login Items. Later launches respect system-level disablement. The installer unregisters before replacing the app; failure attempts to restore the app, preferences, and previous service state. Exit stops only the current session; the system registration still governs the next login.

The installer attempts to create `~/bin/sidecarswitch-cli` with the selected Python. An entry owned by another program is preserved; use `"$HOME/Applications/SidecarSwitch.app/Contents/Resources/sidecarswitch-cli"` in that case. **Keep the selected Python environment and source folder in place.** The app references both. Reinstall after moving them; an app or LaunchAgent owned by another source path is not taken over. Source installations do not include bundled Python, Developer ID signing, notarization, or automatic updates.

## Open and pair

```bash
open -a BetterDisplay
open "$HOME/Applications/SidecarSwitch.app"
```

Choose Settings & Pairing to discover devices, save pairings, and select the control target. Deleting a pairing requires confirmation. Alternatively:

```bash
"$HOME/bin/sidecarswitch-cli" pair --interactive
"$HOME/bin/sidecarswitch-cli" gui
"$HOME/bin/sidecarswitch-cli" gui diagnostics
```

Configuration is stored in `~/Library/Application Support/SidecarSwitch/config.json`. Existing pairings are preserved.

If writing there fails, SidecarSwitch uses `/tmp/SidecarSwitch/config.json`. The daemon, CLI, GUI, menu, and installer preflight select the most recently written file across both locations; status snapshots follow the same rule. The fallback is temporary storage, not a durable backup: repair the primary location's write access. Invalid configuration is never reset or overwritten automatically. Service startup fails, and the GUI reports an error and disables saving. Back up the original file, then repair its JSON or restore a known valid configuration.

## Update and restore

Back up the prior source, save your changes, and close settings. After updating the source, repeat preflight → installation → status; the native binary is rebuilt too. The GUI About page displays `v0.1.0`, sharing `core.__version__` with the CLI and app. It also includes a GitHub link and inactive donation placeholders.

The installer preserves configuration and moves the previous app to Trash. It does not download updates, create Git tags, or publish releases. Restoring only the app from Trash does not restore the source it references.

## Local privacy and permissions

SidecarSwitch configuration, runtime, and log directories use `0700`; configuration, status, IPC sockets, and logs use `0600`. Foreign-owned paths, symlinks, and multiply hard-linked state files are rejected, including under the `/tmp/SidecarSwitch` fallback. Unsafe paths stop the operation rather than being deleted or taken over. See [safe startup troubleshooting](TROUBLESHOOTING.en.md#safe-startup).

IPC logs record known command names, not pairing payloads. Historical logs may contain device information; redact it before sharing. Uninstallation does not use broad process-name termination or remove another checkout's CLI link.

## Daily use and development

```bash
"$HOME/bin/sidecarswitch-cli" start            # Start the service and show the menu
"$HOME/bin/sidecarswitch-cli" stop             # Stop the service, keep the menu
"$HOME/bin/sidecarswitch-cli" exit             # Stop the service and close the menu
"$HOME/bin/sidecarswitch-cli" autostart status
"$HOME/bin/sidecarswitch-cli" autostart toggle
python3 scripts/build_app.py        # Build build/SidecarSwitch.app only; no install/start
"$HOME/bin/sidecarswitch-cli" menu-json        # Read the menu model without a hardware scan
```

Tests cover native menu decoding in three languages, submenus, checked/disabled states, and the command allowlist:

```bash
python3 -m unittest discover -s tests
python3 scripts/check_gui_layout.py
python3 scripts/check_release.py --gui
```

Local release checks also cover shell syntax, plist validity, version consistency, ResourceWarning, and privacy patterns in current files and Git history. Reports are written to `build/release-check.json` and `build/privacy-scan.json`, without matched values. Reviewed historical exceptions are listed separately; new findings still return exit code 1 even if software tests pass. Omit `--gui` without a desktop session; GUI validation is then unverified. These checks do not replace physical acceptance testing.

## Uninstall

Run this from any directory:

```bash
/bin/bash "$HOME/Applications/SidecarSwitch-source/scripts/uninstall.sh"
```

For a manually obtained source copy, run `./scripts/uninstall.sh` from its original project directory. The wizard asks separately about settings/pairings, logs, managed source, and each third-party dependency newly installed by the installer. **All are kept by default.** It presents a complete removal summary for confirmation before stopping this checkout's service and menu and unregistering its login service and removing its app and CLI integration.

| Option | Behavior |
| --- | --- |
| `--yes` | Remove the SidecarSwitch app and integrations noninteractively; keep settings, logs, source, and third-party dependencies. |
| `--yes --purge` | Also remove settings/pairings and logs, including any `/tmp/SidecarSwitch/config.json` fallback. |
| `--remove-config` / `--remove-logs` | Select configuration or logs individually. |
| `--remove-source` | Also remove the downloader-managed `~/Applications/SidecarSwitch-source`; manually obtained source is never deleted automatically. |
| `--remove-dependency NAME` | Select a Homebrew item recorded as newly installed in the receipt; repeat for multiple items. Pre-existing software without that record is not uninstalled automatically. |

The app, integrations, settings, logs, and selected source are moved to Trash and can be recovered. Third-party dependencies are uninstalled through Homebrew, outside SidecarSwitch's Trash recovery; `autoremove` and `--zap` are not used. Python required by other Homebrew packages is kept. Homebrew itself, Apple Command Line Tools, system Python, pre-existing BetterDisplay, and virtual displays are not removed along with SidecarSwitch.

Removing BetterDisplay may disconnect Sidecar or virtual displays and requires an additional confirmation. Noninteractive removal also needs explicit `--allow-display-disconnect`. Only remove Python or source when SidecarSwitch is no longer needed; if source is retained, rerunning the installer restores the installation.
