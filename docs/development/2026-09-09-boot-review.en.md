# PadPilot headless boot repair and logic review

[繁體中文](2026-09-09-boot-review.md) | **English** | [日本語](2026-09-09-boot-review.ja.md) · [Development index](README.en.md)

> Historical record: tests, limitations, and implementation details describe the version at that time. See the [installation guide](../INSTALLATION.en.md) for current usage.

Date: 2026-09-09 (Asia/Taipei).

## Conclusion and evidence

At 00:00:54, 00:00:57, and 00:01:27, `~/Library/Logs/PadPilot/padpilot.log` recorded `Physical=['Generic Display']`, `USB_iPad=False`, and `SidecarAvail=True`, with a `PHYSICAL` decision. This confirms that this boot did not take the iPad takeover path. It does not prove that all Apple Silicon systems, Generic names, or vendor=0 displays are placeholders.

The code already allowed a paired Sidecar target before USB became ready. Correcting the exact placeholder-name classification makes this input choose `IPAD_MAIN`. Tests reproduce the detector → policy → connect/main-display call path and verify that the ROG physical monitor still takes priority.

## Conflicts repaired

| Conflict | Repair |
| --- | --- |
| Generic Display counted as physical and ended warmup early | Exclude exact Generic/Generic Display names, not all vendor=0 devices. |
| Empty ignore entries or virtual names matched every display | Ignore empty matching values. |
| Prefer iPad and manual main/secondary bypassed Automatic cooldown | Use one cooldown check for every decision requiring Sidecar connection. |
| Manual disconnect cleared the override and allowed immediate reconnection | Preserve an explicit `IPAD_DISCONNECTED` override for the topology. |
| Failed main-display change still removed virtual fallback | Require command success and a fresh observation of the correct main display before removal. |
| A virtual main display could satisfy the secondary target when a monitor returned | Require the actual main display to belong to the physical list and complete the return target. |
| A connected Sidecar target disappeared from discovery and selected virtual fallback | Keep the iPad-main decision when the session is already connected. |
| Manual mode/reconnect and automatic switching controlled hardware concurrently | Serialize with the shared state lock and recheck topology after connection waits. |
| Final observation did not update generation/debounce | Share generation, override invalidation, and debounce updates across observation paths. |
| IPC timeout deleted the socket and falsely reported daemon stop | Keep the socket and report the command outcome as unconfirmed. |
| Any VirtualScreen was treated as PadPilotVirtual | Match the configured full name; missing displayID is not a connected display. |
| Failed probing claimed all capabilities | Separate executable availability from capability confirmation and probe after BetterDisplay starts. |
| Existing tests wrote real configuration/state or refreshed the menu | Isolate saves, exports, and system interactions. |

Repairs use the Python standard library and existing test tools; no new dependencies.

## Verification and hardware state

- Before repair, 26 tests passed but did not cover this boot condition or several conflicting paths.
- After repair, 40 tests passed on 2026-09-09, covering boot inputs, physical priority, cooldown, manual disconnect, fallback retention/removal, IPC timeout, and mode changes during transitions.
- Command: `python3 -m unittest discover -s tests`.
- The existing LaunchAgent restarted the repaired version at 01:01:46. Evaluation succeeded at 01:01:47: ROG was physical/main, the paired Sidecar target was available, PadPilotVirtual was configured, state was IDLE, and last_error was empty.
- Automatic mode, login startup, and saved pairings were preserved.
- An unplugged cold boot after repair had not been performed. Tests were not treated as proof of actual iPad display output.

## Remaining limits at that time

1. Generic-name classification was a shortcut based on this machine. A real display with that exact name requires EDID/registry investigation; cross-model correctness was not claimed.
2. Hardware changes used startup warmup and 30-second polling, without native sleep/wake monitoring. Four-second debounce did not promise completion within four seconds; the README was corrected.
3. Slow Sidecar calls can delay manual commands under serialized control. IPC timeout does not cancel the command. Multiple iPads, malformed configuration, and cross-user temporary paths were not comprehensively validated.
4. `autostart` then inferred enabled state from plist existence and could only warn on loading failure. The live launchd job was checked directly, but lifecycle management was not fully rebuilt in that repair.

## Cold-boot acceptance procedure

1. Keep Automatic enabled and verify the iPad is available to Sidecar. Disconnect the physical monitor and restart the Mac.
2. After login, expect takeover with `Physical=[]` and `Desired=IPAD_MAIN`, not the Generic Display `PHYSICAL` decision.
3. Verify actual iPad output and main-display status; reconnect ROG and verify physical priority in Automatic.
4. On failure, retain logs from `Daemon starting up` and the corresponding status.json. Distinguish unavailable target, connection failure, main-display failure, and classification errors. Manual success does not replace cold-boot evidence.

## Follow-up: retain virtual fallback

At 01:14:41 and 01:15:01, virtual fallback removal and Sidecar termination occurred in the same second. The first termination at 01:14:26 was earlier, so fallback removal was not confirmed as the sole cause.

The follow-up connects configured PadPilotVirtual before headless Sidecar takeover and keeps it after the iPad becomes main. This supersedes the table's removal-after-confirmation behavior. Fallback remains an additional display; iPad lock settings, retries, and cooldown were unchanged. Whether this prevents repeated exits during cold boot still requires hardware validation.
