# PadPilot troubleshooting and FAQ

[繁體中文](TROUBLESHOOTING.md) | **English** | [日本語](TROUBLESHOOTING.ja.md) · [Documentation](README.en.md)

For release Gatekeeper warnings, Python selection or recovery, and source-install migration, see the [prebuilt installation instructions](INSTALLATION.en.md). The BetterDisplay app must be installed and running; its separate CLI is optional.

This guide covers status warnings, hardware identification, connection failures, and recovery on macOS.

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
> PadPilot cannot display FileVault unlock or pre-login screens on an iPad.

**Symptom:** After a cold boot or restart, the iPad is blank and does not show the Mac login screen.

**Cause:** PadPilot's LaunchAgent starts after user login and depends on Sidecar in that session. FileVault unlock and pre-login screens are outside its scope. Enabling launch at login does not change this limitation.

**Recovery:**

1. Keep a physical display available to unlock and log in, then verify Sidecar manually.
2. After login, run `./bin/padpilot-cli status` and confirm a daemon response before testing iPad takeover.
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

PadPilot uses that interface for display roles and virtual screens. Without working CLI access and appropriate permissions, it cannot control them.

1. Open BetterDisplay.app.
2. Follow the [BetterDisplay CLI guide](https://github.com/waydabber/BetterDisplay/wiki/Integration-features,-CLI) for your installed version. Setting names and locations can vary.
3. Verify the required Pro license or active trial and the CLI path configured in PadPilot.
4. Test:

   ```bash
   betterdisplaycli get -identifiers
   ```

   Confirm a successful response containing the expected devices. A CLI response alone does not validate Sidecar pairing or the actual display.
5. If macOS requests Accessibility or Screen Recording access, verify the app actually requesting it, such as BetterDisplay. Do not grant access indiscriminately to Terminal or other apps. PadPilot's menu reads snapshots and calls the CLI.

<a id="generic-display"></a>
## 4. Generic Display placeholders

**Symptom:** A headless boot exposes `Generic Display` or `Generic`, causing an incorrect physical-display decision.

Some systems expose a placeholder framebuffer without a real monitor. PadPilot filters those exact known names; this is not a universal hardware-identification rule.

If a real monitor is named exactly `Generic` or `Generic Display`, save its status and separately collect EDID/identification data for investigation:

```bash
./bin/padpilot-cli status --json
```

Do not add a real physical monitor to the ignore list. Report its identifiers rather than broadening name-based exclusions.

<a id="cooldown"></a>
## 5. Connection loss, retries, and cooldown

**Symptom:** The menu shows that automatic retries are paused, with a cooldown during the first 30 seconds.

PadPilot limits connection attempts to three, with three seconds between retries, then sends one notification and pauses automatic retries while retaining the physical or virtual fallback. Retries stay paused after the 30-second cooldown, even if an unavailable iPad remains listed in Sidecar. USB event wakeup and automatic iPad detection can remain enabled.

1. Wake and unlock the iPad if needed.
2. Check the data cable and connectors. When the target iPad changes from absent to present in USB or Sidecar discovery, bounded retries resume after any remaining cooldown. If waking the screen produces no discovery change, choose Reconnect. Generic USB wakeups, Refresh, and physical monitor changes do not release the pause.
3. Once the cause is addressed, clear temporary overrides and cooldown when needed:

   ```bash
   ./bin/padpilot-cli action reset
   ```

The daemon reevaluates state. Choose Reconnect for a manual connection attempt. Successful submission is not proof that the connection completed.

<a id="autostart"></a>
## 6. Launch at login

**Symptom:** After restarting and logging in, the menu is missing and the daemon is not running.

1. Check startup and daemon status:

   ```bash
   ./bin/padpilot-cli autostart status
   ./bin/padpilot-cli status
   ```

2. Re-enable launch at login if necessary:

   ```bash
   ./bin/padpilot-cli autostart enable
   ```

3. The plist is bundled at `PadPilot.app/Contents/Library/LaunchAgents/com.padpilot.daemon.plist`; no file is created in `~/Library/LaunchAgents`. For `requiresApproval`, allow PadPilot in System Settings → General → Login Items. Stop and remove old development LaunchAgents manually; this version does not migrate them.

<a id="logs"></a>
## 7. Collecting logs

If the problem persists, prepare reproduction steps and relevant logs. The GitHub repository is private; submitting an issue requires access.

```bash
# Open status and diagnostics
./bin/padpilot-cli open-log

# Read log files
tail -n 50 ~/Library/Logs/PadPilot/padpilot.log
cat ~/Library/Logs/PadPilot/launchd.stderr.log
```

Review and redact personal paths and sensitive information before sharing.

<a id="safe-startup"></a>
## 8. Preflight, unsafe paths, and failed handshakes

- `FAIL: BetterDisplay CLI`: An installed app does not guarantee a working CLI. Verify CLI support and the saved executable path, then rerun `./scripts/install.sh --check`. Successful help is not license or hardware acceptance evidence.
- Settings will not open: after updating the source, rerun `./scripts/install.sh` to build the matching app.
- `Refusing unsafe state directory/file`: Stop and inspect ownership, symlinks, and hard links at the reported path. Do not recursively change permissions, delete, or take over `/tmp` or someone else's directory. Back up confirmed personal data before its owner repairs it.
- `Login service belongs to another ...`: The same-name app/service belongs to a different checkout. Use its uninstaller from the original source location, not broad process-name termination.
- `Daemon handshake failed`: This checkout's service has not been confirmed responsive, so installation is not successful. Inspect `~/Library/Logs/PadPilot/launchd.stderr.log` and `padpilot.log`, resolve the path, permissions, or BetterDisplay issue, and retry. `Rollback incomplete` also means restoration of the old state is unconfirmed; preserve evidence instead of repeatedly reinstalling.

IPC logs record command names only. Historical logs, diagnostics, and actual error messages may still contain device information. Redact serials, UUIDs, accounts, and personal paths before sharing.
