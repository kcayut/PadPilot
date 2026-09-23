# SidecarSwitch troubleshooting and FAQ

[繁體中文](TROUBLESHOOTING.md) | **English** | [日本語](TROUBLESHOOTING.ja.md) · [Documentation](README.en.md)

For release Gatekeeper warnings, Python selection or recovery, and source-install migration, see the [prebuilt installation instructions](INSTALLATION.en.md). The BetterDisplay app must be installed and running; its separate CLI is optional.

This guide covers status warnings, hardware identification, connection failures, and recovery on macOS.

## Select your installed SidecarSwitch first

DMG users do not need a source checkout or a separate Python installation. Run these commands in Terminal. Set the path to the CLI inside your installed app, then use the same Terminal window for the commands below:

```bash
SIDECARSWITCH_CLI="/Applications/SidecarSwitch.app/Contents/Resources/sidecarswitch-cli"
"$SIDECARSWITCH_CLI" --version
```

For an app in your personal Applications folder, change the first line to `SIDECARSWITCH_CLI="$HOME/Applications/SidecarSwitch.app/Contents/Resources/sidecarswitch-cli"`; use the actual path for any other location. Source-install users should enter their project directory, activate the Python environment used for installation, and set `SIDECARSWITCH_CLI="$PWD/bin/sidecarswitch-cli"`. Steps marked “source installations only” do not apply to a DMG installation.

## Contents

- [1. FileVault and headless cold boot](#filevault)
- [2. Sidecar session prerequisites](#sidecar-session)
- [3. BetterDisplay permissions and CLI](#betterdisplay)
- [4. Generic Display placeholders](#generic-display)
- [5. Connection loss, retries, and cooldown](#cooldown)
- [6. Launch at login](#autostart)
- [7. Collecting logs](#logs)
- [8. Preflight, unsafe paths, and failed handshakes](#safe-startup)

<a id="filevault"></a>
## 1. FileVault and headless cold boot

> [!WARNING]
> SidecarSwitch cannot display FileVault unlock or pre-login screens on an iPad.

**Symptom:** After a cold boot or restart, the iPad is blank and does not show the Mac login screen.

**Cause:** SidecarSwitch's LaunchAgent starts after user login and depends on Sidecar in that session. FileVault unlock and pre-login screens are outside its scope. Enabling launch at login does not change this limitation.

**Recovery:**

1. Keep a physical display available to unlock and log in, then verify Sidecar manually.
2. After login, run `"$SIDECARSWITCH_CLI" status` and confirm a daemon response before testing iPad takeover.
3. Validate your own cold-boot and recovery procedure before headless use. Different hardware combinations still need testing.

**Installation does not require disabling FileVault or enabling automatic login.** Those settings affect data and account security and do not guarantee a Sidecar connection within seconds. Do not lower system security to pass a check.

These checks assess conditions for automatic display connection after startup: automatic login enabled is green “Pass” and disabled is red “Fail”; FileVault off is “Pass” and on is “Fail”. Unchecked or unknown states remain amber. The checks only read status; they do not change settings or read passwords. Passing does not guarantee a Sidecar connection.

<a id="sidecar-session"></a>
## 2. Sidecar session prerequisites

**Symptom:** USB detects the iPad, but Sidecar attempts repeatedly time out or fail.

Check:

1. The Mac and iPad use the same Apple Account.
2. Two-factor authentication is enabled for that account.
3. For USB, use a data cable and accept Trust This Computer on the unlocked iPad.
4. Wireless Sidecar requires Wi-Fi, Bluetooth, and Handoff. Check the [Apple Sidecar guide](https://support.apple.com/en-us/102597) for full compatibility and wired/wireless requirements.

<a id="betterdisplay"></a>
## 3. BetterDisplay permissions and CLI

**Symptom:** Diagnostics show an unavailable BetterDisplay control interface or cannot find `betterdisplaycli`.

SidecarSwitch uses that interface for display roles and virtual screens. Without working CLI access and appropriate permissions, it cannot control them.

1. Open BetterDisplay.app.
2. Follow the [BetterDisplay CLI guide](https://github.com/waydabber/BetterDisplay/wiki/Integration-features,-CLI) for your installed version. Setting names and locations can vary.
3. Current SidecarSwitch features work with BetterDisplay’s free mode; Pro or a trial is not required. Confirm that BetterDisplay is running and SidecarSwitch uses the correct app or CLI path.
4. Test the CLI built into BetterDisplay; the separate `betterdisplaycli` is not needed. This example assumes BetterDisplay is in `/Applications`; substitute its actual app path if installed elsewhere:

   ```bash
   "/Applications/BetterDisplay.app/Contents/MacOS/BetterDisplay" get -identifiers
   ```

   Confirm a successful response containing the expected devices. A CLI response alone does not validate Sidecar pairing or the actual display.
5. If macOS requests Accessibility or Screen Recording access, verify the app actually requesting it, such as BetterDisplay. Do not grant access indiscriminately to Terminal or other apps. SidecarSwitch's menu reads snapshots and calls the CLI.

<a id="generic-display"></a>
## 4. Generic Display placeholders

**Symptom:** SidecarSwitch reports a physical monitor when none is attached, or excludes a real monitor named `Generic Display` / `Generic`, causing an unexpected Automatic mode decision.

Some Macs expose a `Generic` / `Generic Display` placeholder during headless startup, so SidecarSwitch excludes those exact names by default. This observed rule does not prove that every display with either name is a placeholder.

1. Open **Connected displays** and find its card. Excluded displays remain in the list.
2. Check **“Exclude from physical display detection”** to stop counting it as a physical monitor. Uncheck it to include a real Generic monitor. **“Restore automatic detection”** clears this display's individual setting and restores the default rules.
3. Settings are saved by display UUID, so identically named displays do not affect each other. Without a stable UUID, the setting cannot be changed; refresh and check that BetterDisplay is running and can identify the display.

This option only changes whether a physical monitor is considered present. It does not turn off the display or stop SidecarSwitch from controlling it. **Excluding every physical monitor makes Automatic mode treat the Mac as having none, so it may try to let the iPad take over.** Sidecar and an identified virtual fallback already do not count as physical monitors; their purpose and controls remain unchanged.

<a id="cooldown"></a>
## 5. Connection loss, retries, and cooldown

**Symptom:** The menu shows that automatic retries are paused, with a cooldown during the first 30 seconds.

SidecarSwitch limits connection attempts to three, with three seconds between retries, then sends one notification and pauses automatic retries while retaining the physical or virtual fallback. Retries stay paused after the 30-second cooldown, even if an unavailable iPad remains listed in Sidecar. USB event wakeup and automatic iPad detection can remain enabled.

To stop the current automatic connection round, select Manual only to cancel its waiting and further retries. A command already sent to macOS may still complete; you can still explicitly connect afterward using a button or shortcut.

1. Wake and unlock the iPad if needed.
2. Check the data cable and connectors. When the target iPad changes from absent to present in USB or Sidecar discovery, bounded retries resume after any remaining cooldown. If waking the screen produces no discovery change, choose Reconnect. Generic USB wakeups, Refresh, and physical monitor changes do not release the pause.
3. Once the cause is addressed, clear temporary overrides and cooldown when needed:

   ```bash
   "$SIDECARSWITCH_CLI" action reset
   ```

The daemon reevaluates state. Choose Reconnect for a manual connection attempt. Successful submission is not proof that the connection completed.

<a id="autostart"></a>
## 6. Launch at login

**Symptom:** After restarting and logging in, the menu is missing and the daemon is not running.

1. Check startup and daemon status:

   ```bash
   "$SIDECARSWITCH_CLI" autostart status
   "$SIDECARSWITCH_CLI" status
   ```

2. Re-enable launch at login if necessary:

   ```bash
   "$SIDECARSWITCH_CLI" autostart enable
   ```

3. The plist is bundled at `SidecarSwitch.app/Contents/Library/LaunchAgents/com.sidecarswitch.daemon.plist`; no file is created in `~/Library/LaunchAgents`. For `requiresApproval`, allow SidecarSwitch in System Settings → General → Login Items.

<a id="logs"></a>
## 7. Collecting logs

If the problem persists, include reproduction steps, versions, and relevant logs in a [GitHub issue](https://github.com/kcayut/SidecarSwitch/issues). For security vulnerabilities, read the [security policy](../SECURITY.md) first and keep vulnerability details out of public issues.

```bash
# Open status and diagnostics
"$SIDECARSWITCH_CLI" open-log

# Read log files
tail -n 50 ~/Library/Logs/SidecarSwitch/sidecarswitch.log
cat ~/Library/Logs/SidecarSwitch/launchd.stderr.log
```

Review and redact personal paths and sensitive information before sharing.

<a id="safe-startup"></a>
## 8. Preflight, unsafe paths, and failed handshakes

- `FAIL: BetterDisplay CLI`: An installed app does not guarantee a working CLI. Verify CLI support and the saved executable path, then open diagnostics with `"$SIDECARSWITCH_CLI" gui diagnostics` and refresh the BetterDisplay card. For source installations only, run `./scripts/install.sh --check` from the project directory. Successful help does not prove that Sidecar or the display works.
- Settings will not open: for a DMG installation, follow the [release recovery steps](INSTALLATION.en.md#change-or-recover-python-afterward), or download and install the release again. For source installations only, rerun `./scripts/install.sh` after updating the source to build the matching app.
- `Refusing unsafe state directory/file`: Stop and inspect ownership, symlinks, and hard links at the reported path. Do not recursively change permissions, delete, or take over `/tmp` or someone else's directory. Back up confirmed personal data before its owner repairs it.
- `Login service belongs to another ...`: The same-name app/service belongs to a different checkout. Use its uninstaller from the original source location, not broad process-name termination.
- `Daemon handshake failed`: This checkout's service has not been confirmed responsive, so installation is not successful. Inspect `~/Library/Logs/SidecarSwitch/launchd.stderr.log` and `sidecarswitch.log`, resolve the path, permissions, or BetterDisplay issue, and retry. `Rollback incomplete` also means restoration of the old state is unconfirmed; preserve evidence instead of repeatedly reinstalling.
- Failed release update: even if the replacement CLI cannot run, the installer must confirm that the replacement app and background service have stopped before restoring the old version. If shutdown cannot be confirmed, it preserves the current app and backup and reports `Rollback incomplete`; keep them and the error details rather than repeatedly installing over them.

IPC logs record command names only. Historical logs, diagnostics, and actual error messages may still contain device information. Redact serials, UUIDs, accounts, and personal paths before sharing.
