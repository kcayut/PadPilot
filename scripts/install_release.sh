#!/usr/bin/env bash
# Fetch an official prebuilt development release; macOS tools handle download/mount.
set -euo pipefail
TAG=""
PYTHON_BIN=""
RUNTIME=""
TARGET="/Applications/SidecarSwitch.app"
YES=0
die() { printf 'SidecarSwitch: %s\n' "$*" >&2; exit 1; }
while [[ $# -gt 0 ]]; do
    case "$1" in
        --tag|--python|--target)
            [[ $# -ge 2 && -n "$2" ]] || die "$1 requires a value"
            case "$1" in
                --tag) TAG="$2" ;;
                --python) [[ "$RUNTIME" != bundled ]] || die 'Choose --bundled or --python'; PYTHON_BIN="$2"; RUNTIME=external ;;
                --target) TARGET="$2" ;;
            esac
            shift 2 ;;
        --bundled) [[ -z "$PYTHON_BIN" ]] || die 'Choose --bundled or --python'; RUNTIME=bundled; shift ;;
        --yes|-y) YES=1; shift ;;
        --help|-h)
            echo 'Usage: bash install_release.sh [--tag vX.Y.Z-dev.N] [--bundled | --python /path/to/python3] [--target /path/SidecarSwitch.app] [--yes]'
            echo 'Default: newest published SidecarSwitch DMG including prereleases. No compiler, Homebrew or system Python required.'
            exit 0 ;;
        *) die "Unknown option: $1" ;;
    esac
done
[[ "$(uname -s)" == Darwin && "$(uname -m)" == arm64 ]] || die 'Apple Silicon macOS required.'
VERSION="$(sw_vers -productVersion)"
[[ "${VERSION%%.*}" -ge 14 ]] || die 'macOS 14+ required.'
if [[ -z "$RUNTIME" && "$YES" == 0 ]]; then
    printf 'Python：1) 封裝版本 / bundled（預設） 2) 自己的 Python / external: '
    IFS= read -r CHOICE || die 'No input; use --yes --bundled for unattended installation.'
    case "$CHOICE" in
        ''|1) RUNTIME=bundled ;;
        2) printf 'Python 絕對路徑 / absolute path: '; IFS= read -r PYTHON_BIN; [[ -n "$PYTHON_BIN" ]] || die 'Python path required'; RUNTIME=external ;;
        *) die 'Select 1 or 2.' ;;
    esac
fi
[[ -n "$TAG" ]] && [[ "$TAG" =~ ^v[0-9]+\.[0-9]+\.[0-9]+(-(dev|alpha|beta|rc)\.[0-9]+)?$ ]] || [[ -z "$TAG" ]] || die 'Invalid release tag.'
umask 077
WORK_DIR="$(mktemp -d "${TMPDIR:-/tmp}/sidecarswitch-release.XXXXXX")"
MOUNT="$WORK_DIR/mounted"
cleanup() { [[ ! -d "$MOUNT" ]] || hdiutil detach "$MOUNT" -quiet || true; rm -rf "$WORK_DIR"; }
trap cleanup EXIT
download() { curl --fail --location --proto '=https' --tlsv1.2 --connect-timeout 15 --retry 2 "$1" --output "$2"; }
if [[ -z "$TAG" ]]; then
    download 'https://api.github.com/repos/kcayut/PadPilot/releases?per_page=100' "$WORK_DIR/releases.json" || die 'Could not read published releases.'
    INDEX=0
    while plutil -extract "$INDEX.tag_name" raw -o - "$WORK_DIR/releases.json" > "$WORK_DIR/tag" 2>/dev/null; do
        DRAFT="$(plutil -extract "$INDEX.draft" raw -o - "$WORK_DIR/releases.json")"
        CANDIDATE="$(cat "$WORK_DIR/tag")"
        if [[ "$DRAFT" == false && "$CANDIDATE" =~ ^v[0-9]+\.[0-9]+\.[0-9]+(-(dev|alpha|beta|rc)\.[0-9]+)?$ ]]; then
            ASSET_INDEX=0
            while NAME="$(plutil -extract "$INDEX.assets.$ASSET_INDEX.name" raw -o - "$WORK_DIR/releases.json" 2>/dev/null)"; do
                if [[ "$NAME" == "SidecarSwitch-${CANDIDATE#v}-macos-arm64.dmg" ]]; then TAG="$CANDIDATE"; break; fi
                ASSET_INDEX=$((ASSET_INDEX + 1))
            done
            [[ -z "$TAG" ]] || break
        fi
        INDEX=$((INDEX + 1))
    done
    [[ -n "$TAG" ]] || die 'No published SidecarSwitch release found yet. Use the source installer until the first tag is published.'
fi
ASSET="SidecarSwitch-${TAG#v}-macos-arm64.dmg"
BASE="https://github.com/kcayut/PadPilot/releases/download/$TAG"
echo "Downloading $TAG..."
download "$BASE/$ASSET" "$WORK_DIR/$ASSET" || die 'Release download failed; nothing installed.'
download "$BASE/SHA256SUMS" "$WORK_DIR/SHA256SUMS" || die 'Release checksums unavailable.'
EXPECTED="$(awk -v asset="$ASSET" '$2 == asset { print $1 }' "$WORK_DIR/SHA256SUMS")"
[[ "$EXPECTED" =~ ^[0-9a-f]{64}$ ]] || die 'Missing or invalid checksum.'
ACTUAL="$(shasum -a 256 "$WORK_DIR/$ASSET")"
[[ "${ACTUAL%% *}" == "$EXPECTED" ]] || die 'SHA-256 mismatch; nothing installed.'
hdiutil attach "$WORK_DIR/$ASSET" -readonly -nobrowse -mountpoint "$MOUNT" -quiet
APP="$MOUNT/SidecarSwitch.app"
codesign --verify --deep --strict "$APP"
ARGS=(--source "$APP" --target "$TARGET")
[[ -z "$PYTHON_BIN" ]] || ARGS+=(--python "$PYTHON_BIN")
"$APP/Contents/Resources/Python/bin/python3" -I -B \
    "$APP/Contents/Resources/SidecarSwitch/scripts/install_release.py" "${ARGS[@]}"
