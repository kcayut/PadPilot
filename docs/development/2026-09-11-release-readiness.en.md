# 0.1.0 Early Preview: P0/P1 acceptance

[繁體中文](2026-09-11-release-readiness.md) | **English** | [日本語](2026-09-11-release-readiness.ja.md) · [Development index](README.en.md)

Date: 2026-09-11. The initial pass covered GUI version information, installation reliability, local safety, and documentation. GitHub creation, Actions, remotes, branch protection, tags, Releases, and public security reporting were initially skipped at the maintainer's request. Version remains `0.1.0`, not stable.

Follow-up: the maintainer created a private GitHub repository and uploaded source and CI. The original `origin` remains, with a separate `github` remote. `.github/workflows/ci.yml` separates macOS/Python 3.10 and 3.14 software checks from Linux full-history privacy review. Both Python jobs, including native app builds, passed in the [first corrected CI run](https://github.com/kcayut/PadPilot/actions/runs/34508708985), with 163 tests at that point. The Python 3.10 dangling-link test now checks the link and its target directly instead of relying on glob behavior. That run reported tree=0, history=6. The maintainer subsequently accepted these six low-risk historical paths; the exact boundary is below. See [Actions](https://github.com/kcayut/PadPilot/actions/workflows/ci.yml) for later runs.

References to skipped GitHub work describe the initial scope, not a missing repository today. GitHub reported that private-repository branch protection requires Pro on the current plan. No upgrade or visibility change was made. Public security reporting, tags, and Releases are not configured.

## Checklist

| Item | Status | Result / remaining condition |
| --- | --- | --- |
| GUI version | Implemented | About reads `core.__version__`, shared with CLI/app; three-language and 840px checks. |
| P0-1 installation | Implemented | Read-only `--check`, optional Tk, required-dependency failures stop installation, shared autostart, handshake, and rollback. |
| P0-2 local safety | fixed | Private permissions, no IPC payload logging, safe fallback access/cleanup, and verified owned jobs/processes only. |
| P0-3 release gates | Local and CI implemented | Unit, shell, plist, version, GUI, ResourceWarning, and tree/history checks; Python 3.10/3.14 CI passed. macOS 14 and hardware acceptance remain outstanding. |
| P0-4 headless hardware | unknown | Physical procedures below still require actions and evidence, not simulated substitutes. |
| P1 documentation | Synchronized | Three-language README/docs, language navigation, GUI document routing, install/update/restore/removal, limitations, and acceptance matrix. |

`scripts/check_release.py --gui` writes `build/release-check.json` and per-check logs; `--scan-only` runs privacy patterns only. Reports omit matched values. Failed software checks or unreviewed findings return nonzero. `stable_ready` remains false while physical and supported-version acceptance is incomplete.

## Initial verification record

All 162 tests passed without ResourceWarning in the initial local pass. Three-language GUI, 840px layout, focus/draft/scroll preservation, native menu contract, shell, plist, version consistency, and `git diff --check` passed. Results were saved to local `build/release-check.json`; the overall result was 1 because historical privacy review was pending, not because software tests failed.

Real installation and repeated installation both succeeded: one daemon, one native app, verified owned LaunchAgent, socket handshake, and installed app signature/version. The main configuration's SHA-256 was unchanged after reinstall, preserving pairings/preferences. Configuration/runtime/log directories were `0700`; configuration, status, socket, and three active log files were `0600`. The previous app was recoverable from Trash. This was an existing development Mac, not a clean-machine or headless cold-boot test.

| Environment/scenario | Evidence |
| --- | --- |
| Apple Silicon arm64, macOS 26.6.2, Python 3.14.6, Tk 9.0 | Development/GUI/build environment for that pass, not full headless hardware certification. |
| Minimum Python 3.10 | Included in macOS 15 arm64 CI; see Actions for software results. Real GUI and hardware acceptance remain incomplete. |
| Minimum macOS 14 | Build target 14.0; not executed on that OS, unknown. |
| Intel Mac and other macOS/Tk combinations | Not executed, unknown. |
| Missing Tk, failed install, startup rollback, removal scope | Temporary-user-directory and fake-process tests, not clean-Mac end-to-end acceptance. |

## Local safety repair summary

Result: `fixed` within this P0-2 scope, not a whole-project security certification.

- **Trust boundaries:** Another local user could precreate `/tmp/PadPilot`; pairing payloads may contain UUIDs/serials; same-name LaunchAgents, CLI links, and processes may belong to another checkout.
- **Original risks:** Unrestricted state permissions, full IPC payload logging, linked fallback reads/cleanup, and overly broad process termination.
- **Shared repair:** `core/storage.py` checks ownership, file types, and links, enforces `0700`/`0600`, and writes atomically. GUI/menu/CLI/daemon share these guards. Active socket endpoints are not overwritten.
- **Commands/lifecycle:** Log known command names only, not payloads or raw unknown commands. Before stopping, verify the plist, loaded job source/arguments, and Python/script identity. Installer, CLI, and GUI share autostart. Failed child handshakes terminate and reap that child; login-start failure attempts to restore prior configuration and running state.
- **Independent follow-up fixes:** Added fallback cleanup, hidden-menu marker protection, failed child cleanup, and rollback after stopping the old service, with regression tests.
- **Preserved behavior:** JSON and legacy IPC, pairing transactions, normal state access, stale socket replacement, current-session operation with login startup disabled, and three-language GUI/menu. `--check` does not write state; missing Tk does not block core services.
- **Evidence:** `tests/test_release_safety.py`, `tests/test_install_check.py`, `tests/test_menu_pairing.py`, `tests/test_autostart.py`, `tests/test_native_app.py`, and actual Tk layout/language checks.
- **Limits:** Does not defend against arbitrary code execution under the same account or root. Does not rewrite old logs/history or guarantee all errors are de-identified. The scanner covers limited text patterns, not exhaustive secret discovery.

## Privacy acceptance and release work

The prior tree scan found no configured patterns. Six historical `private_path` findings were the addition/removal of the same local paths in an early README, installer, and LaunchAgent, not six credentials. On 2026-09-11 the maintainer accepted exposure of the local account name and source/log locations. History is retained, not cleaned or rewritten.

Exceptions apply only to the specified files in `4c7642471fc316991ff8e0ab1ec678e347ce7ed4` and `fc53785b1d385d21aac6e8f9d93f4638b0f348ab`, and only to `private_path`. They are listed in `scripts/check_release.py`. `accepted_history` retains their reviewed locations; `tree` and `history` contain unexempted findings. New commits, other files, credentials, and current files are not exempt. Revoke or rotate real credentials first if any are discovered. Accepting paths does not publish the repository, create tags/Releases, or complete hardware acceptance; private reporting described in `SECURITY.md` is not enabled.

Follow-up verification after localization and exact exceptions: 167 local tests passed, along with actual three-language GUI document/help clicks, 840px layout, and state-preservation checks. Results were tree=0, history=0, accepted_history=6. This is not headless hardware acceptance or confirmation that these changes have been pushed to GitHub.

The app references external Python/source and uses ad-hoc local signing. Developer ID, Apple notarization, DMG, bundled Python, and automatic updates were not included.

## P0-4 physical acceptance

Record Mac/macOS/iPadOS, cable/hub, BetterDisplay version, and pairing method first. Retain a physical monitor or prevalidated remote recovery. Do not disable FileVault to pass testing; pre-login output is unsupported.

| Action | Expected result | Status |
| --- | --- | --- |
| Cold boot without a monitor, then log in | Automatic Sidecar with selected iPad main; no pre-login output required | unknown |
| USB insert/remove | Wake existing evaluation without duplicate connections or uncontrolled retries | unknown |
| Sleep/wake | Restore state without persistent switching | unknown |
| Restart Sidecar/BetterDisplay | Detect failure and recover with cooldown-bounded retries | unknown |
| iPad connection failure | Retain `PadPilotVirtual` fallback | unknown |
| Two candidate iPads, no valid selected target | Do not guess or connect automatically | unknown |
| Reconnect physical monitor | Automatic mode returns stably to a physical main display | unknown |

For each, retain `padpilot-cli status --json` before/after/after stabilization, relevant logs, timestamps, and the actual visible result. Raw evidence may contain personal information; keep it in ignored local `build/` or another private folder and redact before publishing. Software does not unplug cables, sleep, or restart the Mac on the user's behalf.

## Repairs after the final review (2026-09-11)

Fixed installer rollback losing the pre-stop running state, inconsistent primary/fallback reads, malformed configuration silently enabling automation, incorrect Sidecar display identity, overwritten identifiers errors, missing GUI revision checks, fallback configuration omitted from purge, FileVault diagnostic grading, the unchecked uninstall script, and virtual-display hint interpolation. The PR template now uses the existing privacy gate. Installation, architecture, and troubleshooting guides were updated in all three languages. Long configuration paths wrap within the minimum window.

178 unit tests passed without ResourceWarning, along with the 840px widget/focus/draft/scroll checks and three-language GUI checks. Installation rollback uses temporary user directories and fake services, covering launchd, standalone, and previously stopped states; no live installation or service was changed. Both shell scripts were checked separately; plist, version, and diff checks passed. Privacy results: tree=0, history=0, accepted_history=6. These source changes have not been deployed or pushed.

The complete `check_release.py --gui` passed with isolated user directories; 34 tracked Markdown files had no broken local links. Read-only GitHub queries confirmed that the repository is still private; the private-reporting API returned 404, so a working reporting endpoint could not be verified.

The security policy no longer directs reporters to an unenabled feature or an unspecified profile contact. A publishable maintainer email or working private-reporting URL is still required; private reporting and public release remain not ready. macOS 14 and physical acceptance remain `unknown`; `stable_ready` remains false.
