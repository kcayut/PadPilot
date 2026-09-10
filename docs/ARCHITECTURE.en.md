# PadPilot architecture and design

[繁體中文](ARCHITECTURE.md) | **English** | [日本語](ARCHITECTURE.ja.md) · [Documentation](README.en.md)

PadPilot is a deterministic display-state manager designed for headless Mac mini + iPad setups.

## Design principles

1. **Physical display priority:** In automatic mode without an active manual override, prefer the physical monitor and do not initiate Sidecar. Other modes follow their own policy; transitions are not guaranteed to be immediate.
2. **Manual control priority:** Choices such as making the iPad secondary take priority within the current hardware topology. Mode changes, resets, and topology changes trigger reevaluation.
3. **Observability:** Decisions and observed hardware state are written atomically to snapshots. The menu and GUI read them without heavy polling on the menu read path.
4. **Failure recovery:** Debounce, bounded retries, and cooldown reduce repeated connection pressure. They cannot guarantee that third-party services never fail.

## Components

```text
Swift / AppKit PadPilot.app
  ├─ menu-json → core/menu.py → config.json + atomic status.json + daemon liveness
  └─ CLI argument arrays → padpilot-cli → Unix socket → padpilotd
                                                       ├─ Detector / IOKit / CoreGraphics
                                                       └─ StateEngine → BetterDisplay CLI
Tk settings GUI ─────────────→ shared CLI/config transactions
```

The menu checks snapshot file changes every second and calls `menu-json` only after a change or five seconds since its previous read. Reading the menu does not scan hardware. CLI subprocesses run off the AppKit main thread. An open menu is not rebuilt; updated content appears after it closes. Actions use argument arrays and an allowlist, never device names interpolated into shell commands. The LaunchAgent starts Python after login, then opens the native app. A lock prevents duplicate menu instances. Stopping the service keeps the menu; Exit closes both.

## Core mechanisms

### 1. Topology generations

If a user chooses an iPad secondary display while no monitor exists, ordinary polling must not immediately force it back to main. Manual overrides are attached to a hardware generation. Topology changes, mode changes, or reset invalidate them. When a physical monitor exists, loss of the iPad connection can also clear its main/secondary override.

### 2. Single-flight transitions

USB detection, display events, and the 30-second watchdog may arrive together. A shared lock serializes evaluation and configuration transactions; duplicate wakeups are coalesced so PadPilot does not run competing transitions. Other applications may still control displays concurrently.

### 3. Debounce and cooldown

- Physical display loss starts a four-second debounce. If the monitor returns before expiry, the transfer is canceled. This avoids unnecessary iPad wakeups during brief signal changes, not all display failures.
- Sidecar connection attempts are limited to three, with three seconds between retries and a 30-second cooldown after failure. The menu indicates the warning state.

### 4. Virtual fallback

Without a physical monitor, the configured BetterDisplay virtual screen, normally `PadPilotVirtual`, provides desktop fallback and remains connected after iPad takeover. Configure Screen Sharing/VNC or SSH yourself before relying on recovery. PadPilot does not enable remote access; SSH does not itself depend on a virtual display.

### 5. Atomic snapshots

- The daemon writes observed state, desired state, and decision reasons to a temporary file, then uses `os.replace` to publish `~/Library/Application Support/PadPilot/runtime/status.json` atomically.
- `core/menu.py` and the GUI consume snapshots. Configuration revision mismatches or stale data disable relevant controls while preserving unknown states. An explicit menu Refresh requests a hardware update through the CLI.

## USB events and temporary targets

`core/usb_events.py` uses ctypes to register IOKit first-match/terminated notifications for `IOUSBHostDevice`. Callbacks drain and release iterator objects, then only set the wakeup event. One daemon loop handles notifications, startup discovery, and the watchdog through the existing `StateEngine.evaluate`; native callbacks do not run BetterDisplay commands. Shutdown removes the RunLoop source and releases iterators and the notification port. Registration failures retain watchdog operation and produce diagnostics.

`usb_event_wakeup` and `auto_detect_ipad` default to true and use existing configuration transactions for persistence and live application. Both switches are under the initially collapsed Advanced options section. Previously saved disabled values remain disabled. Configuration changes and transitions share the evaluation lock so the target is not replaced mid-transition.

Automatic detection first uses an explicitly selected pairing with a Sidecar UUID. USB presence is not required for that pairing, and a temporarily missing discovery candidate does not replace its identity. Only without a valid selected pairing does detection infer a target from a unique USB candidate. The result lives in `ActualState.resolved_ipad` and is shared by connect, disconnect, reconnect, and main-display actions. USB serial and Sidecar UUID participate in the topology signature; changing devices invalidates overrides.

Inference does not write Config or the pairing list. Incomplete queries or ambiguous candidates prevent connection attempts. Saved USB/Sidecar mappings take priority; otherwise, unique candidates are a heuristic, not proof of matching hardware identity. The GUI and menu show the current target. Controls on the selected pairing recheck the target before dispatch; other pairings must first become the control target.

Native notification references: [Apple IOServiceAddMatchingNotification](https://developer.apple.com/documentation/iokit/1514362-ioserviceaddmatchingnotification) and the local macOS SDK `IOKitLib.h`. Notifications and wakeups are immediate; Sidecar completion still depends on discovery, existing operations, retries, and debounce.
