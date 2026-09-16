#!/usr/bin/env bash
# Resolve the installed interpreter without importing PadPilot or changing state.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd -P)"
for argument in "$@"; do
    if [[ "$argument" == --help || "$argument" == -h ]]; then
        cat <<'EOF'
用法 / Usage: scripts/uninstall.sh [選項 / options]
  無選項 / no options       逐項選擇並確認 / Choose items, then confirm the preview
  --yes, -y                 略過互動 / Apply explicit options without prompting
  --purge                   設定、配對與日誌 / Trash settings, pairing and logs
  --remove-config           設定與配對 / Trash settings and pairing
  --remove-logs             日誌 / Trash logs
  --remove-source           受管來源 / Trash bootstrap-managed source
  --remove-dependency NAME   指定依賴，可重複 / Remove a recorded dependency; repeatable
  --allow-display-disconnect 確認可能中斷唯一螢幕 / Accept losing the only display
  --help, -h                顯示說明 / Show help
無互動終端時必須使用 --yes。Homebrew、系統 Python、Apple 開發工具永遠保留。
Without a terminal, --yes is required. Homebrew, system Python and Apple developer tools are always kept.
原安裝 Python 已不存在時，可用 PADPILOT_PYTHON=/絕對路徑/python3 指定替代版本。
If the recorded Python is missing, set PADPILOT_PYTHON=/absolute/path/python3 to use a replacement.
EOF
        exit 0
    fi
done
[[ "$(uname -s)" == Darwin ]] || { echo '解除安裝需要 macOS。 / Uninstall requires macOS.' >&2; exit 1; }
valid_python() {
    [[ "$1" == /* && -x "$1" ]] && "$1" -B -c 'import sys; sys.exit(sys.version_info < (3, 10))' >/dev/null 2>&1
}
source "$SCRIPT_DIR/source_runtime.sh"
PYTHON_BIN="${PADPILOT_PYTHON:-}"
if [[ -z "$PYTHON_BIN" ]]; then
    PYTHON_BIN="$(source_python || true)"
fi
if [[ -z "$PYTHON_BIN" ]]; then
    PYTHON_CANDIDATES=(
        /opt/homebrew/opt/python@3.14/bin/python3.14 /opt/homebrew/bin/python3.14
        /usr/local/opt/python@3.14/bin/python3.14 /usr/local/bin/python3.14
        /opt/homebrew/bin/python3 /usr/local/bin/python3
        /Library/Frameworks/Python.framework/Versions/Current/bin/python3
        /Library/Frameworks/Python.framework/Versions/*/bin/python3
        "$(command -v python3 || true)"
    )
    for candidate in "${PYTHON_CANDIDATES[@]}"; do
        if valid_python "$candidate"; then
            PYTHON_BIN="$candidate"
            break
        fi
    done
fi
valid_python "$PYTHON_BIN" || {
    if [[ -n "${PADPILOT_PYTHON:-}" ]]; then
        echo 'PADPILOT_PYTHON 必須指向可用的 Python 3.10+。 / PADPILOT_PYTHON must point to a usable Python 3.10+.' >&2
    else
        echo '找不到可用的 Python 3.10+，請指定替代路徑。 / No usable Python 3.10+; set PADPILOT_PYTHON=/absolute/path/python3.' >&2
    fi
    exit 1
}
exec "$PYTHON_BIN" -B "$SCRIPT_DIR/uninstall_interactive.py" "$@"
