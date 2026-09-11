#!/usr/bin/env bash
# Native app + Python core. All dependency changes require an explicit choice.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd -P)"
CHECK_ONLY=0
ASSUME_YES=0
INSTALL_DEPS=0
PYTHON_BIN=""
BETTERDISPLAY_PATH=""
BREW_BIN=""

usage() {
    cat <<'HELP'
Usage: bash scripts/install.sh [options]
  --check                 唯讀檢查 / read-only dependency check
  --yes, -y               沿用現有依賴並安裝 PadPilot / accept existing dependencies
  --install-deps          同意安裝缺少的依賴 / allow missing dependency installation
  --python PATH           指定 Python 3.10+ 執行檔 / Python executable
  --betterdisplay-path PATH  指定 BetterDisplay.app 或 CLI / app or executable
  --help, -h              顯示說明 / help
--yes 不會自行安裝第三方依賴；需另外指定 --install-deps。
HELP
}
fail() { printf '\n錯誤 / Error: %s\n' "$*" >&2; exit 1; }
while [[ $# -gt 0 ]]; do
    case "$1" in
        --check) CHECK_ONLY=1; shift ;;
        --yes|-y) ASSUME_YES=1; shift ;;
        --install-deps) INSTALL_DEPS=1; shift ;;
        --python|--betterdisplay-path)
            [[ $# -ge 2 && -n "$2" ]] || fail "$1 需要路徑 / requires a path"
            if [[ "$1" == --python ]]; then PYTHON_BIN="$2"; else BETTERDISPLAY_PATH="$2"; fi
            shift 2 ;;
        --help|-h) usage; exit 0 ;;
        *) usage >&2; fail "未知參數 / unknown option: $1" ;;
    esac
done
[[ "$(uname -s)" == Darwin ]] || fail 'PadPilot 需要 macOS 14+ / requires macOS 14 or later.'
MAC_VERSION="$(sw_vers -productVersion)"
[[ "${MAC_VERSION%%.*}" =~ ^[0-9]+$ && "${MAC_VERSION%%.*}" -ge 14 ]] || fail 'PadPilot 需要 macOS 14+ / requires macOS 14 or later.'

# A saved bootstrap script can still read the terminal when its stdin is a pipe.
exec 3<&0
if [[ ! -t 0 && -t 1 ]]; then { exec 3</dev/tty; } 2>/dev/null || true; fi
ask() {
    printf '%s ' "$1" >&2
    IFS= read -r REPLY <&3 || fail '未收到選擇；請在終端機執行，或以 --yes 使用現有依賴。 / No input; run in a terminal or use --yes.'
}
expand_path() {
    case "$REPLY" in '~/'*) REPLY="$HOME/${REPLY#\~/}" ;; esac
}
have_clt() {
    [[ -n "${DEVELOPER_DIR:-}" ]] || xcode-select -p >/dev/null 2>&1 || return 1
    xcrun --find swiftc >/dev/null 2>&1
}
valid_python() {
    [[ -f "$1" && -x "$1" ]] || return 1
    # Apple's python3 stub can open an installer merely by being executed.
    [[ "$1" != /usr/bin/python3 ]] || have_clt || return 1
    "$1" -B -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1
}
find_python() {
    local candidate runtime
    if [[ -z "$PYTHON_BIN" ]]; then
        runtime="$HOME/Applications/PadPilot.app/Contents/Resources/runtime.json"
        if [[ -f "$runtime" && ! -L "$runtime" && "$(plutil -extract project_root raw -o - "$runtime" 2>/dev/null || true)" == "$PROJECT_ROOT" ]]; then
            candidate="$(plutil -extract python raw -o - "$runtime" 2>/dev/null || true)"
            if valid_python "$candidate"; then PYTHON_BIN="$candidate"; fi
        fi
    fi
    if [[ -n "$PYTHON_BIN" ]]; then
        REPLY="$PYTHON_BIN"; expand_path; PYTHON_BIN="$REPLY"
        valid_python "$PYTHON_BIN"
        return $?
    fi
    for candidate in "$(command -v python3 || true)" \
        /opt/homebrew/opt/python@3.14/bin/python3.14 /usr/local/opt/python@3.14/bin/python3.14 \
        /opt/homebrew/bin/python3 /usr/local/bin/python3 \
        /Library/Frameworks/Python.framework/Versions/Current/bin/python3 \
        /Library/Frameworks/Python.framework/Versions/3.*/bin/python3; do
        valid_python "$candidate" || continue
        PYTHON_BIN="$candidate"; return 0
    done
    return 1
}
check_args() {
    CHECK_ARGS=("$SCRIPT_DIR/check_install.py")
    if [[ -n "$BETTERDISPLAY_PATH" ]]; then CHECK_ARGS+=(--betterdisplay-path "$BETTERDISPLAY_PATH"); fi
}
if [[ "$CHECK_ONLY" == 1 ]]; then
    find_python || fail '找不到 Python 3.10+。可用 --python PATH 指定；檢查未安裝或啟動任何服務。 / Python 3.10+ not found; no changes made.'
    check_args
    exec "$PYTHON_BIN" -B "${CHECK_ARGS[@]}"
fi

[[ "$EUID" -ne 0 ]] || fail '請以一般使用者執行，不要使用 sudo；安裝器會在需要時提示管理員密碼。 / Run as your normal user, without sudo.'
RECEIPT="$PROJECT_ROOT/.padpilot-install.json"
[[ -w "$SCRIPT_DIR/.." && ! -L "$RECEIPT" ]] || fail '原始碼目錄不可寫入或安裝紀錄是連結；請移至你擁有的目錄後重試。'
[[ ! -e "$RECEIPT" || ( -f "$RECEIPT" && -w "$RECEIPT" ) ]] || fail '無法安全更新安裝紀錄；尚未安裝依賴。'
printf '\nPadPilot 安裝精靈 / Setup\n先偵測依賴，再由你選擇沿用、指定路徑或安裝。\n'
CLT_REQUESTED=0
while ! have_clt; do
    if [[ "$INSTALL_DEPS" == 1 && "$CLT_REQUESTED" == 0 ]]; then REPLY=i
    elif [[ "$ASSUME_YES" == 1 ]]; then fail '缺少 Apple Command Line Tools；請先安裝或加上 --install-deps。'
    else ask '缺少 Swift 編譯工具：[i] 開啟 Apple 安裝程式 / install、[m] 指定 Developer 目錄 / path、[q] 取消 [q]:'; fi
    case "$REPLY" in
        i|I)
            xcode-select --install || fail '無法開啟 Apple 安裝程式；請完成 xcode-select --install 後重試。'
            printf '\n請在 Apple 視窗完成 Command Line Tools 安裝。 / Finish installation in the Apple dialog.\n'
            [[ "$ASSUME_YES" == 0 ]] || fail 'Apple 安裝尚待完成；完成後重新執行相同指令。'
            ask '完成後按 Enter 重新檢查，或輸入 q 離開 / Enter to retry, q to quit:'
            [[ "$REPLY" != q && "$REPLY" != Q ]] || exit 1
            CLT_REQUESTED=1 ;;
        m|M)
            ask 'Developer 目錄（例如 /Applications/Xcode.app/Contents/Developer）:'
            expand_path
            [[ "$REPLY" == /* && -d "$REPLY" ]] || { printf '路徑不存在 / Directory not found.\n' >&2; continue; }
            export DEVELOPER_DIR="$REPLY" ;;
        *) fail '已取消；依賴尚未齊備。 / Cancelled; dependencies are incomplete.' ;;
    esac
done
printf '✓ Apple Swift compiler\n'

ensure_brew() {
    local candidate installer
    if valid_python "$PYTHON_BIN"; then
        "$PYTHON_BIN" -B -c 'import sys; sys.path.insert(0, sys.argv[1]); from setup_state import read_receipt; read_receipt()' "$SCRIPT_DIR"
    fi
    for candidate in "${BREW_BIN:-}" "$(command -v brew || true)" /opt/homebrew/bin/brew /usr/local/bin/brew; do
        if [[ -f "$candidate" && -x "$candidate" ]]; then BREW_BIN="$candidate"; return; fi
    done
    while true; do
        if [[ "$INSTALL_DEPS" == 1 ]]; then REPLY=i
        elif [[ "$ASSUME_YES" == 1 ]]; then fail '找不到 Homebrew；請先手動安裝依賴，或加上 --install-deps。'
        else ask '找不到 Homebrew：[i] 執行官方安裝程式 / install、[m] 指定 brew 路徑 / path、[q] 取消 [q]:'; fi
        case "$REPLY" in
            i|I)
                printf '將執行 Homebrew 官方安裝程式，可能要求管理員密碼。 / Installing Homebrew; an administrator password may be required.\n'
                installer="$(mktemp -t padpilot-homebrew)"
                if ! curl --fail --show-error --location --proto '=https' --tlsv1.2 \
                    https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh -o "$installer"; then
                    rm -f "$installer"; fail '無法下載 Homebrew 安裝程式。 / Homebrew download failed.'
                fi
                if [[ "$ASSUME_YES" == 1 ]]; then export NONINTERACTIVE=1; fi
                if ! /bin/bash "$installer" <&3; then
                    rm -f "$installer"; fail 'Homebrew 安裝未完成；可手動完成後重試。 / Homebrew installation did not complete.'
                fi
                rm -f "$installer"
                for candidate in /opt/homebrew/bin/brew /usr/local/bin/brew; do
                    if [[ -f "$candidate" && -x "$candidate" ]]; then BREW_BIN="$candidate"; return; fi
                done
                fail '安裝後仍找不到 brew，請重新執行並指定路徑。 / Cannot locate brew after installation.' ;;
            m|M)
                ask 'brew 執行檔完整路徑 / Full path to brew:'; expand_path
                if [[ "$REPLY" == /* && -f "$REPLY" && -x "$REPLY" ]]; then BREW_BIN="$REPLY"; return; fi
                printf '找不到可執行檔 / Executable not found.\n' >&2 ;;
            *) fail '已取消 Homebrew 安裝。 / Homebrew installation cancelled.' ;;
        esac
    done
}
brew_install() {
    local kind="$1" name="$2" existed=0 status=0 prefix
    if [[ -n "$("$BREW_BIN" list "--$kind" --versions "$name" 2>/dev/null || true)" ]]; then existed=1; fi
    "$BREW_BIN" install "--$kind" "$name" || status=$?
    if [[ "$name" == python@3.14 && -n "$("$BREW_BIN" list --formula --versions "$name" 2>/dev/null || true)" ]]; then
        prefix="$("$BREW_BIN" --prefix python@3.14)"
        PYTHON_BIN="$prefix/bin/python3.14"
    fi
    if [[ "$existed" == 0 && -n "$("$BREW_BIN" list "--$kind" --versions "$name" 2>/dev/null || true)" ]]; then
        valid_python "$PYTHON_BIN" || fail "已安裝 $name，但無可用 Python 記錄；請保留 Homebrew 安裝訊息。"
        "$PYTHON_BIN" -B "$SCRIPT_DIR/setup_state.py" --record-dependency "$kind" "$name" --brew "$BREW_BIN"
    fi
    [[ "$status" == 0 ]] || fail "Homebrew 安裝 $name 失敗；已完成的依賴已記錄，可修正問題後重試。"
}
install_python() {
    ensure_brew
    brew_install formula python@3.14
    find_python || fail '新安裝的 Python 無法執行。 / Installed Python is not usable.'
}
find_python || true
while true; do
    if [[ -n "$PYTHON_BIN" ]] && valid_python "$PYTHON_BIN"; then
        printf 'Python: %s\n' "$PYTHON_BIN"
        if [[ "$ASSUME_YES" == 1 ]]; then break; fi
        ask 'Python：[Enter] 沿用 / use、[m] 指定其他路徑 / path、[i] 安裝 Python / install、[q] 取消:'
        [[ -n "$REPLY" ]] || break
    elif [[ "$INSTALL_DEPS" == 1 ]]; then REPLY=i
    elif [[ "$ASSUME_YES" == 1 ]]; then fail '找不到 Python 3.10+；請用 --python PATH 指定或加上 --install-deps。'
    else ask '缺少 Python 3.10+：[m] 指定路徑 / path、[i] 安裝 Python / install、[q] 取消 [q]:'; fi
    case "$REPLY" in
        m|M)
            ask 'Python 執行檔完整路徑 / Full path to Python:'; expand_path
            PYTHON_BIN="$REPLY"
            find_python || printf '需要可執行的 Python 3.10+ / A working Python 3.10+ is required.\n' >&2 ;;
        i|I) install_python; break ;;
        *) fail '已取消 Python 設定。 / Python setup cancelled.' ;;
    esac
done

# Use the same read-only config/path resolver as preflight, without importing config.
resolve_betterdisplay() {
    "$PYTHON_BIN" -B -c 'import sys; sys.path.insert(0, sys.argv[1]); from check_install import resolve_betterdisplay_path; print(resolve_betterdisplay_path(sys.argv[2] or None) or "")' "$SCRIPT_DIR" "$BETTERDISPLAY_PATH"
}
REPLY="$BETTERDISPLAY_PATH"; expand_path; BETTERDISPLAY_PATH="$REPLY"
BETTERDISPLAY_FOUND="$(resolve_betterdisplay)" || fail '無法讀取 BetterDisplay 設定；請先修正設定檔。'
while true; do
    if [[ -n "$BETTERDISPLAY_FOUND" ]]; then
        printf 'BetterDisplay: %s\n' "$BETTERDISPLAY_FOUND"
        if [[ "$ASSUME_YES" == 1 ]]; then break; fi
        ask 'BetterDisplay：[Enter] 沿用 / use、[m] 指定其他路徑 / path、[i] Homebrew 安裝 / install、[q] 取消:'
        [[ -n "$REPLY" ]] || break
    elif [[ "$INSTALL_DEPS" == 1 ]]; then REPLY=i
    elif [[ "$ASSUME_YES" == 1 ]]; then fail '找不到 BetterDisplay；請用 --betterdisplay-path PATH 指定或加上 --install-deps。'
    else ask '缺少 BetterDisplay：[m] 指定 .app 或 CLI / path、[i] Homebrew 安裝 / install、[q] 取消 [q]:'; fi
    case "$REPLY" in
        m|M)
            ask 'BetterDisplay.app 或 CLI 完整路徑 / Full path to app or CLI:'; expand_path
            BETTERDISPLAY_PATH="$REPLY" ;;
        i|I)
            ensure_brew
            brew_install cask betterdisplay
            BETTERDISPLAY_PATH="$("$BREW_BIN" --prefix)/bin/betterdisplaycli"
            if [[ ! -x "$BETTERDISPLAY_PATH" ]]; then BETTERDISPLAY_PATH=/Applications/BetterDisplay.app; fi ;;
        *) fail '已取消 BetterDisplay 設定。 / BetterDisplay setup cancelled.' ;;
    esac
    BETTERDISPLAY_FOUND="$(resolve_betterdisplay)" || fail '無法讀取 BetterDisplay 設定。'
    [[ -n "$BETTERDISPLAY_FOUND" || "$INSTALL_DEPS" == 0 ]] || fail '安裝後仍找不到 BetterDisplay，請用 --betterdisplay-path 指定。'
done
BETTERDISPLAY_PATH="$BETTERDISPLAY_FOUND"
check_args
"$PYTHON_BIN" -B "${CHECK_ARGS[@]}"
printf '\n將安裝 / Install: ~/Applications/PadPilot.app\nPython: %s\nBetterDisplay: %s\n' "$PYTHON_BIN" "$BETTERDISPLAY_PATH"
if [[ "$ASSUME_YES" == 0 ]]; then
    ask '繼續安裝 PadPilot？ / Install PadPilot? [Y/n]:'
    case "$REPLY" in ''|y|Y|yes|YES) ;; *) fail '已取消 PadPilot 安裝；已安裝的依賴保留並已記錄。' ;; esac
fi
exec "$PYTHON_BIN" -B "$SCRIPT_DIR/manage_app.py" --betterdisplay-path "$BETTERDISPLAY_PATH"
