# Read-only Python bootstrap for source installers. App selection after Python
# starts is authoritative in core.runtime.find_app; this never changes an App.
source_python() {
    local owner app runtime root python bundle
    owner="$(plutil -extract app raw -expect string -o - "$HOME/Library/Application Support/SidecarSwitch/login-service.json" 2>/dev/null || true)"
    for app in "$owner" "$HOME/Applications/SidecarSwitch.app" /Applications/SidecarSwitch.app "$PROJECT_ROOT/build/SidecarSwitch.app"; do
        [[ "$app" == /* && -d "$app" && ! -L "$app" ]] || continue
        runtime="$app/Contents/Resources/runtime.json"
        [[ -f "$runtime" && ! -L "$runtime" ]] || continue
        bundle="$(plutil -extract CFBundleIdentifier raw -expect string -o - "$app/Contents/Info.plist" 2>/dev/null || true)"
        [[ "$bundle" == com.sidecarswitch.app ]] || continue
        root="$(plutil -extract project_root raw -expect string -o - "$runtime" 2>/dev/null || true)"
        [[ "$root" == /* && -d "$root" && "$(cd "$root" && pwd -P)" == "$PROJECT_ROOT" ]] || continue
        python="$(plutil -extract python raw -expect string -o - "$runtime" 2>/dev/null || true)"
        [[ "$python" == /* ]] || continue
        if valid_python "$python"; then printf '%s\n' "$python"; return 0; fi
    done
    return 1
}
