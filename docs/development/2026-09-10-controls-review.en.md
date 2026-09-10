# 2026-09-10 controls, menu, and diagnostics review

[繁體中文](2026-09-10-controls-review.md) | **English** | [日本語](2026-09-10-controls-review.ja.md) · [Development index](README.en.md)

> Historical record: test counts and hardware results apply to this date and topology, not every hardware combination. See the [installation guide](../INSTALLATION.en.md) for current usage.

## Results

Eleven requested changes were implemented; 96 unit/regression tests passed. Real Tk widgets were checked at the minimum 840×500 window size: four control buttons stayed on one row without overflow, logs collapsed/expanded, and the search field was removed.

| Request | Implementation |
| --- | --- |
| 1 | Added a Control row with four equal-width buttons above the Sidecar UUID on paired cards. Other pairings must become the active target before control. |
| 2 | Fixed false disconnection when a saved name differs from the live Sidecar name. Query the session by Sidecar UUID and verify `off` after disconnect rather than trusting exit status alone. |
| 3 | Reviewed GUI/menu/CLI/daemon mappings; fixed the CLI path-setting entry, operation error codes, timeout handling, and disabled states. Verification scope is below. |
| 4 | Fixed reconnect canceling its own override, stale errors, omitted draft revisions, reentrant layout updates, and old virtual displays surviving an empty scan. |
| 5 | Used high-contrast text for light/dark menu appearances; unavailable actions remain gray. |
| 6 | Menu order: displays/devices → iPad controls → mode → daemon → settings/pairing → diagnostics → refresh displays → Exit. |
| 7 | Status and diagnostics open the GUI directly. |
| 8 | Each evaluation checks hardware and clears stale errors when the target is truly satisfied. A delayed Sidecar connection can clear cooldown; fallback alone does not count as connection success. GUI Refresh also requests reevaluation. |
| 9–10 | Removed log search, retained level filtering, added collapse/expand, and allowed diagnostic scrolling. |
| 11 | Added launch-at-login, BetterDisplay installation/CLI/login item, automatic login, FileVault, fallback, and pairing checks. Unknown and manual checks remain explicit. |

## Root cause and hardware evidence

Logs at 01:07:00 and 01:07:35 received `disconnect_ipad`, but `SidecarConn=False` incorrectly marked the target satisfied and skipped disconnect. The saved name was `iPad pro m2`, while the live name was `ky iPad pro m2`. The Sidecar session UUID and macOS display UUID also differ and must not be interchanged.

On 2026-09-10, with ROG PG279Q connected and wireless Sidecar:

| Shared action | Time | Observation |
| --- | --- | --- |
| Use as secondary | 01:29:30–33 | `IPAD_SECONDARY` reached; ROG PG279Q stayed main. |
| Make main | Around 01:30 | `IPAD_MAIN` reached; `ky iPad pro m2` was main. |
| Disconnect | 01:30:32–44 | `Sidecar disconnect verified` logged; physical main restored; no reconnection at the next watchdog. |
| Reconnect while disconnected | Around 01:31 | `IPAD_SECONDARY` restored without error. |
| Reconnect while connected | 01:32:09–15 | Disconnect verified before reconnect; secondary override preserved without error. |

Hardware checks used the production CLI/daemon path shared by GUI/menu actions. GUI bindings were checked separately by regression tests. Computer-use clicks did not reliably trigger Tk events and were not counted as successful interaction evidence. The actual GUI cards and diagnostics were opened and inspected.

After testing, Sidecar was disconnected and ROG restored as main. The existing LaunchAgent was restarted with the new code; state was normal with no error or cooldown.

## Button verification scope

| Controls | Verification |
| --- | --- |
| Four iPad actions | Shared path on hardware; GUI handler mapping and stale-target protection tests. |
| Search/Refresh | Daemon reevaluation before a new snapshot; live diagnostics read successfully. |
| Active target, save, name/USB updates, delete | Command review plus pairing, cancel confirmation, revision conflict, and unrelated-settings preservation tests. Draft revision now propagates. Real pairings were not deleted or changed for testing. |
| Operating modes | Three-mode/shared-entry review and mode/override/cooldown conflict tests. |
| BetterDisplay custom/default path | CLI parsing, stdin, dispatch, and path validation tests; fixed the missing accepted operation. |
| Virtual fallback selection | Live device/name uniqueness, clearing stale choices after an empty scan; real fallback settings unchanged. |
| Login startup, daemon, Exit | LaunchAgent, confirmed stop, menu preservation after stop failure, and Exit order tests; failure exit codes fixed. Real login preferences and Exit were not exercised. |
| Log filtering, refresh, external open, collapse/expand | Callback review and real Tk collapse/expand checks; external open reused the log-file entry. |

## Local diagnostics

Queries at 01:26–01:34 showed configured PadPilot login startup and a responsive daemon; BetterDisplay installed with usable CLI and an enabled/allowed login item for the current user; macOS automatic login configured; FileVault off; PadPilotVirtual and Sidecar UUID configured.

Login-item parsing only considers BetterDisplay entries for the current UID. Timeouts, unsupported queries, and insufficient permissions remain unknown. Apple Account, two-factor authentication, computer trust, and Universal Control are manual checks, not automatically verified. Automatic login, FileVault, and system security settings were not changed.

## Reproduction and limits

```sh
python3 -m unittest discover -s tests
python3 scripts/check_gui_layout.py
```

- 96 tests, layout, and `git diff --check` passed.
- The watchdog evaluated every 30 seconds; Refresh requested immediate evaluation. During an operation, the UI may first report requested. Updated hardware state and logs determine the final outcome.
- No cold boot with the physical monitor removed was performed.
- BetterDisplay arguments were checked against local `help -sidecarConnected`, `get -sidecarConnected -specifier=...`, and the [upstream CLI guide](https://github.com/waydabber/BetterDisplay/wiki/Integration-features,-CLI).

## Follow-up: independent diagnostic refresh

- Decision/state-machine refresh reevaluates and updates only that card.
- General checks remain non-authenticated with their own Refresh.
- BetterDisplay login-item queries moved to the authentication-required card. macOS may request an administrator account/password only after that card's explicit Refresh. macOS handles credentials; PadPilot does not collect or save them.
- Refresh preserves other cards, authentication results, and logs. General sidebar refresh does not invoke authenticated checks.
- 98 tests passed, including query separation and update scope. The 840px check verified three independent refresh buttons and log collapse. The actual system authentication flow was not triggered in this pass.
