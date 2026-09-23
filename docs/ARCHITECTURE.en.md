# SidecarSwitch architecture and design

[繁體中文](ARCHITECTURE.md) | **English** | [日本語](ARCHITECTURE.ja.md) · [Documentation](README.en.md)

SidecarSwitch is a deterministic display-state manager designed for headless Mac mini + iPad setups.

## Design principles

1. **Physical display priority:** In automatic mode without an active manual override, prefer the physical monitor and do not initiate Sidecar. Other modes follow their own policy; transitions are not guaranteed to be immediate.
2. **Manual control priority:** Choices such as making the iPad secondary take priority within the current hardware topology. Mode changes, resets, and topology changes trigger reevaluation.
3. **Observability:** Decisions and observed hardware state are written atomically to snapshots. The menu and GUI read them without heavy polling on the menu read path.
4. **Failure recovery:** Debounce, bounded retries, and cooldown reduce repeated connection pressure. They cannot guarantee that third-party services never fail.

## Components

```text
Swift / AppKit + SwiftUI SidecarSwitch.app
  ├─ SwiftUI settings → shared CLI/config transactions
  ├─ menu-json → core/menu.py → config.json + atomic status.json + daemon liveness
  └─ CLI argument arrays → sidecarswitch-cli → Unix socket → sidecarswitchd
                                                       ├─ Detector / IOKit / CoreGraphics
                                                       └─ StateEngine → BetterDisplay CLI
```

The menu checks snapshot file changes every second and calls `menu-json` only after a change or five seconds since its previous read. Reading the menu does not scan hardware. CLI subprocesses run off the AppKit main thread. An open menu is not rebuilt; updated content appears after it closes. Actions use argument arrays and an allowlist, never device names interpolated into shell commands. Login startup uses `SMAppService.agent` with an app-bundled LaunchAgent and a relative native executable path, which then runs the selected Python. No external startup plist is installed. Python runs as a child process: normal Exit does not restart it, while launchd restarts the service after a crash. The native service keeps watching app move events and unregisters itself when the app enters Trash.  A lock prevents duplicate menu instances. Stopping display automation keeps the menu; Exit also closes the menu. An enabled login service retains the removal watch.

## Core mechanisms

### 1. Topology generations

If a user chooses an iPad secondary display while no monitor exists, ordinary polling must not immediately force it back to main. Manual overrides are attached to a hardware generation. Topology changes, mode changes, or reset invalidate them. When a physical monitor exists, loss of the iPad connection can also clear its main/secondary override.

Global shortcuts and main/secondary connection requests in Manual only mode last for one round. The request is then cleared while the established connection remains. Manual only mode never reconnects automatically after a later disconnection or device reappearance.

### 2. Single-flight transitions

USB detection, display events, and the 30-second watchdog may arrive together. A shared lock serializes evaluation and configuration transactions; duplicate wakeups are coalesced so SidecarSwitch does not run competing transitions. Other applications may still control displays concurrently.

### 3. Debounce and cooldown

- Physical display loss starts a four-second debounce. If the monitor returns before expiry, the transfer is canceled. This avoids unnecessary iPad wakeups during brief signal changes, not all display failures.
- Sidecar connection attempts are limited to three, with three seconds between retries. Exhaustion sends one notification and keeps the fallback available. Expiry of the 30-second cooldown does not restart retries: the target iPad must change from absent to present in USB/Sidecar discovery, or the user must reconnect/reset manually. Query errors, generic USB wakeups, and physical monitor changes do not release the pause.

### 4. Virtual fallback

Without a physical monitor, the configured BetterDisplay virtual screen, normally `SidecarSwitchVirtual`, provides desktop fallback and remains connected after iPad takeover. Configure Screen Sharing/VNC or SSH yourself before relying on recovery. SidecarSwitch does not enable remote access; SSH does not itself depend on a virtual display.

### 5. Atomic snapshots

- The daemon writes observed state, desired state, and decision reasons to a temporary file, then uses `os.replace` to publish `~/Library/Application Support/SidecarSwitch/runtime/status.json` atomically.
- `core/menu.py` and the GUI consume snapshots. Configuration revision mismatches or stale data disable relevant controls while preserving unknown states. An explicit menu Refresh requests a hardware update through the CLI.

## USB events and temporary targets

`core/usb_events.py` uses ctypes to register IOKit first-match/terminated notifications for `IOUSBHostDevice`. Callbacks drain and release iterator objects, then only set the wakeup event. One daemon loop handles notifications, startup discovery, and the watchdog through the existing `StateEngine.evaluate`; native callbacks do not run BetterDisplay commands. Shutdown removes the RunLoop source and releases iterators and the notification port. Registration failures retain watchdog operation and produce diagnostics.

`usb_event_wakeup` and `auto_detect_ipad` default to true and use existing configuration transactions for persistence and live application. Both switches are under the initially collapsed Advanced options section. Previously saved disabled values remain disabled. Configuration changes and transitions share the evaluation lock so the target is not replaced mid-transition.

Automatic detection first uses an explicitly selected pairing with a Sidecar UUID. USB presence is not required for that pairing, and a temporarily missing discovery candidate does not replace its identity. Only without a valid selected pairing does detection infer a target from a unique USB candidate. The result lives in `ActualState.resolved_ipad` and is shared by connect, disconnect, reconnect, and main-display actions. USB serial and Sidecar UUID participate in the topology signature; changing devices invalidates overrides.

Inference does not write Config or the pairing list. Incomplete queries or ambiguous candidates prevent connection attempts. Saved USB/Sidecar mappings take priority; otherwise, unique candidates are a heuristic, not proof of matching hardware identity. The GUI and menu show the current target. Controls on the selected pairing recheck the target before dispatch; other pairings must first become the control target.

Native notification references: [Apple IOServiceAddMatchingNotification](https://developer.apple.com/documentation/iokit/1514362-ioserviceaddmatchingnotification) and the local macOS SDK `IOKitLib.h`. Notifications and wakeups are immediate; Sidecar completion still depends on discovery, existing operations, retries, and debounce.

## Configuration consistency and unknown state

Primary configuration/status files and `/tmp/SidecarSwitch` fallbacks share last-write-time selection, with ownership and file-type checks before reading. Invalid configuration prevents startup instead of applying defaults; the GUI disables saving and preserves the original file. GUI transactions send `expected_revision`; rename drafts retain their editing-start revision and require review after a conflict.

The detector keeps a verified Sidecar session UUID/display UUID mapping only for its current process. It reuses the mapping during discovery loss and clears it when the target changes or disconnection is confirmed. `ActualState.sidecar_display_id` is shared by main-display selection and satisfaction checks. A connected session with an unidentified display is unknown and leaves displays unchanged. A later successful identifiers query does not erase an earlier failure in the same observation.

## Global connection shortcut

Open Settings & Pairing → Operation & Preferences → Global Keyboard Shortcut. Click the key field, press a combination, then Save Shortcut; include Control or Command. Letters, digits, common punctuation, arrow/navigation keys, and F1–F20 are supported. Escape or switching windows cancels recording. The existing global shortcut is suspended during recording and restored on cancellation. No shortcut is registered until saved; change or disable it as needed. Use a keyboard connected directly to the Mac, with the Mac logged in and unlocked and the SidecarSwitch menu app and background service running. The shortcut is unavailable on the lock screen. Neither a physical monitor nor an open settings window is required.

- Manual mode normally accepts only explicit shortcut or menu commands. Its optional “Connect iPad at boot when no monitor is attached” checkbox permits one round after the service first starts in each boot session. Discovery runs for up to three 30-second rounds (90 seconds total), retaining the roughly two-second scan interval. If none finds a target, the boot connection flow stops. Connecting requires no physical monitor and an identifiable iPad target. A physical monitor, user operation, disabled setting, or deadline cancels the request. Restarting the app or service within the same boot does not retry. Enable launch at login to run this on login; it cannot connect before login.
- New installations default to Manual mode with boot connection enabled; updates preserve the existing mode. Settings and the menu bar list Manual before Automatic.
- Automatic mode keeps its existing automatic connections; the shortcut requests an additional bounded connection round.
- In Manual mode, completion, failure, or cancellation ends the round. Later disconnection, USB events, or iPad arrival never starts another connection.
- A round uses the existing maximum of three attempts and retry interval. Holding the key or repeating a request while busy does not replenish retries. A new press after completion can request another round.
- Without a physical monitor the iPad becomes primary; with one it becomes secondary. Prefer iPad mode keeps the iPad primary. An already connected, online iPad is not disconnected or reassigned.
- Saving the shortcut uses existing revision checks and CLI/IPC, without scanning or connecting hardware. Registration conflicts ask for another combination without a failure dialog. Sidecar itself may still display a system warning when connection fails.

Registration uses native macOS hotkeys, with no extra package or keyboard-monitoring Accessibility permission. Keys use physical keyboard positions and remain stable across input-source changes.

SidecarSwitch cannot determine in advance whether an iPad can successfully connect through Sidecar. A separate warning below Automatic mode explains that automatic attempts may frequently trigger macOS warning dialogs when the iPad cannot connect. Neither the available-device list nor USB detection guarantees a successful connection.
