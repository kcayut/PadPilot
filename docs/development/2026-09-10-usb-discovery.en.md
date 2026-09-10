# USB event wakeup and unpaired iPad discovery

[繁體中文](2026-09-10-usb-discovery.md) | **English** | [日本語](2026-09-10-usb-discovery.ja.md) · [Development index](README.en.md)

> Historical record: the table describes the initial implementation. Automatic detection is now enabled by default and prioritizes explicitly selected pairings; see the [current architecture](../ARCHITECTURE.en.md).

The USB & iPad Auto-detection settings card reuses GUI → CLI → IPC → configuration transactions and the state engine.

| Switch | Initial default | Behavior |
| --- | --- | --- |
| USB event wakeup | Enabled | IOKit first-match/terminated callbacks wake the existing evaluation loop; discovery, debounce, cooldown, and watchdog remain active. |
| Automatic iPad detection | Disabled | Require one USB iPad, prefer a saved mapping, otherwise require one Sidecar candidate. The target exists only in observed state. |

The menu shows the current target. In this initial implementation, saved-pairing controls were disabled during automatic detection so an old label could not operate a different device. Configuration changes waited for the shared evaluation lock. No external packages were added.

## Verification

- `python3 -m unittest discover -s tests`: 115 passed, including 11 new tests covering configuration validation, CLI/IPC dispatch, native registration and stop/restart, fallback to watchdog, wakeup of the original loop, unique unpaired candidates, saved mapping priority, no connection on ambiguity/query failure, identity changes, main-display dispatch, manual mode, and cooldown.
- `python3 scripts/check_gui_layout.py`: 840px layout passed; both switches were visible and dispatched correct settings. Saved-pairing controls were disabled under automatic detection.
- `git diff --check`: passed.
- Native IOKit registration, stop, and restart worked locally. After restarting the existing LaunchAgent at 08:23, logs confirmed `Native USB notifications active`; state included `resolved_ipad` with no discovery error.
- The user's Manual Only mode, pairings, and ROG PG279Q main display were preserved. Unpaired automatic connection was not enabled.

## Limits

A unique USB candidate and unique Sidecar candidate are an inference, not proof of identical hardware. Multiple-iPad environments should use explicit pairing. Apple Account, trust, and Sidecar compatibility requirements remain unchanged.

This pass did not physically insert/remove an iPad, substitute another unpaired iPad, or cold-boot without a monitor. Those scenarios are not accepted by these results, and millisecond Sidecar completion is not claimed. Automatic connection also requires Automatic or Prefer iPad mode.
