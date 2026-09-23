#!/usr/bin/env bash
# Download an official source archive, then run the same installer as a checkout.
set -euo pipefail

SOURCE_ROOT="$HOME/Applications/SidecarSwitch-source"
ARCHIVE_URL="https://codeload.github.com/kcayut/SidecarSwitch/tar.gz/refs/heads/main"
die() { printf 'SidecarSwitch: %s\n' "$*" >&2; exit 1; }

case "${1:-}" in
    --help|-h)
        echo "Usage: bash bootstrap.sh [installer options]"
        echo "Installs source in ~/Applications/SidecarSwitch-source, then runs scripts/install.sh."
        echo "Existing managed source is reused, never updated or overwritten."
        echo "Options: --yes --install-deps --check --python PATH --betterdisplay-path PATH"
        exit 0 ;;
esac
[[ "$(uname -s)" == Darwin ]] || die "macOS 14 or later is required."
ARGS=("$@")
while [[ $# -gt 0 ]]; do
    case "$1" in
        --yes|-y|--install-deps|--check) shift ;;
        --python|--betterdisplay-path)
            [[ $# -ge 2 && -n "$2" ]] || die "$1 requires a path."
            shift 2 ;;
        *) die "Unknown option: $1. Use --help for usage." ;;
    esac
done

[[ ! -L "$HOME/Applications" ]] || die "~/Applications is a symbolic link. Use a source checkout and scripts/install.sh instead."
if [[ -e "$HOME/Applications" ]]; then
    [[ -d "$HOME/Applications" && -O "$HOME/Applications" ]] || die "~/Applications must be a directory owned by you."
fi
if [[ -e "$SOURCE_ROOT" || -L "$SOURCE_ROOT" ]]; then
    RECEIPT="$SOURCE_ROOT/.sidecarswitch-install.json"
    [[ -d "$SOURCE_ROOT" && ! -L "$SOURCE_ROOT" && -O "$SOURCE_ROOT" &&
       -f "$RECEIPT" && ! -L "$RECEIPT" && -O "$RECEIPT" &&
       -f "$SOURCE_ROOT/scripts/install.sh" && ! -L "$SOURCE_ROOT/scripts/install.sh" &&
       ! -L "$SOURCE_ROOT/scripts" && -O "$SOURCE_ROOT/scripts/install.sh" ]] ||
        die "Existing path is not a managed SidecarSwitch source folder: $SOURCE_ROOT. Nothing was overwritten."
    grep -Eq '"schema"[[:space:]]*:[[:space:]]*1([[:space:]]*[,}])' "$RECEIPT" &&
        grep -Eq '"managed_source"[[:space:]]*:[[:space:]]*true([[:space:]]*[,}])' "$RECEIPT" ||
        die "Existing source has no valid managed-install receipt. Nothing was overwritten."
    echo "Reusing existing source: $SOURCE_ROOT"
    exec /bin/bash "$SOURCE_ROOT/scripts/install.sh" ${ARGS[@]+"${ARGS[@]}"}
fi
for ARG in ${ARGS[@]+"${ARGS[@]}"}; do
    [[ "$ARG" != --check ]] || die "No installed source to check. Download a source copy first, then run scripts/install.sh --check."
done

umask 077
WORK_DIR="$(mktemp -d "${TMPDIR:-/tmp}/sidecarswitch-download.XXXXXX")"
trap 'rm -rf "$WORK_DIR"' EXIT
echo "Downloading SidecarSwitch source from the official GitHub repository..."
curl --fail --location --proto '=https' --tlsv1.2 --connect-timeout 15 --retry 2 \
    "$ARCHIVE_URL" --output "$WORK_DIR/source.tar.gz" ||
    die "Download failed. The repository and main branch must be public; a private/unpublished repository may return 404. No installer was run."

# Only ordinary files/directories under the expected root may be extracted.
tar -tzf "$WORK_DIR/source.tar.gz" > "$WORK_DIR/members" || die "Invalid source archive."
[[ -s "$WORK_DIR/members" ]] || die "Empty source archive."
while IFS= read -r MEMBER; do
    case "$MEMBER" in
        SidecarSwitch-main|SidecarSwitch-main/|SidecarSwitch-main/*) ;;
        *) die "Unexpected archive path. Nothing was installed." ;;
    esac
    case "/$MEMBER/" in
        */../*|*/./*|*\\*) die "Unsafe archive path. Nothing was installed." ;;
    esac
    [[ "$MEMBER" != *[[:cntrl:]]* ]] || die "Invalid archive filename."
done < "$WORK_DIR/members"
tar -tvzf "$WORK_DIR/source.tar.gz" > "$WORK_DIR/types" || die "Cannot inspect source archive."
LC_ALL=C awk 'substr($0, 1, 1) != "-" && substr($0, 1, 1) != "d" { exit 1 }' "$WORK_DIR/types" ||
    die "Source archive contains links or special files. Nothing was installed."
mkdir "$WORK_DIR/extracted"
tar -xzf "$WORK_DIR/source.tar.gz" --no-same-owner --no-same-permissions -C "$WORK_DIR/extracted"
[[ -f "$WORK_DIR/extracted/SidecarSwitch-main/scripts/install.sh" &&
   -f "$WORK_DIR/extracted/SidecarSwitch-main/scripts/uninstall.sh" ]] || die "Archive is missing the SidecarSwitch installer."
cat > "$WORK_DIR/extracted/SidecarSwitch-main/.sidecarswitch-install.json" <<'EOF'
{"schema": 1, "managed_source": true, "dependencies": []}
EOF
mkdir -p "$HOME/Applications"
[[ ! -e "$SOURCE_ROOT" && ! -L "$SOURCE_ROOT" ]] || die "Source destination appeared during download. Nothing was overwritten."
mv "$WORK_DIR/extracted/SidecarSwitch-main" "$SOURCE_ROOT"
echo "Source saved in: $SOURCE_ROOT"
echo 'Keep this folder while SidecarSwitch is installed. Rerun this command to resume installation.'
/bin/bash "$SOURCE_ROOT/scripts/install.sh" ${ARGS[@]+"${ARGS[@]}"}
