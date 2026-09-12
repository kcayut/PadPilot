import AppKit
import Foundation
import Darwin

struct Runtime: Decodable {
    let python: String
    let project_root: String
    var bundled: Bool? = nil

    static func load(bundle: URL = Bundle.main.bundleURL, useBundled: Bool = false) throws -> Runtime {
        let resources = bundle.appendingPathComponent("Contents/Resources")
        let metadata = try JSONDecoder().decode(Runtime.self, from: Data(contentsOf: resources.appendingPathComponent("runtime.json")))
        if metadata.bundled != true { return metadata }
        guard metadata.python == "Python/bin/python3", metadata.project_root == "PadPilot" else {
            throw NSError(domain: "PadPilot", code: 1, userInfo: [NSLocalizedDescriptionKey: "Invalid bundled runtime"])
        }
        var python = resources.appendingPathComponent(metadata.python).standardizedFileURL.path
        if !useBundled {
            let support = padpilotHomeDirectory().appendingPathComponent("Library/Application Support/PadPilot")
            var directory = stat()
            if lstat(support.path, &directory) == 0 {
                guard (directory.st_mode & S_IFMT) == S_IFDIR, directory.st_uid == getuid() else {
                    throw NSError(domain: "PadPilot", code: 1, userInfo: [NSLocalizedDescriptionKey: "Unsafe Python preference directory"])
                }
            } else if errno != ENOENT { throw NSError(domain: NSPOSIXErrorDomain, code: Int(errno)) }
            let path = support.appendingPathComponent("python-runtime.json")
            let fd = Darwin.open(path.path, O_RDONLY | O_NOFOLLOW | O_NONBLOCK)
            if fd >= 0 {
                let handle = FileHandle(fileDescriptor: fd, closeOnDealloc: true)
                defer { try? handle.close() }
                var info = stat()
                guard fstat(fd, &info) == 0, (info.st_mode & S_IFMT) == S_IFREG,
                      info.st_uid == getuid(), info.st_nlink == 1, info.st_size < 16384 else {
                    throw NSError(domain: "PadPilot", code: 1, userInfo: [NSLocalizedDescriptionKey: "Unsafe Python preference file"])
                }
                guard let value = try JSONSerialization.jsonObject(with: handle.readDataToEndOfFile()) as? [String: String],
                      Set(value.keys).isSubset(of: ["python"]), value["python"] == nil || value["python"]!.hasPrefix("/") else {
                    throw NSError(domain: "PadPilot", code: 1, userInfo: [NSLocalizedDescriptionKey: "Invalid Python preference"])
                }
                if let selected = value["python"] { python = selected }
            } else if errno != ENOENT { throw NSError(domain: NSPOSIXErrorDomain, code: Int(errno)) }
        }
        guard FileManager.default.isExecutableFile(atPath: python) else {
            throw NSError(domain: "PadPilot", code: 1, userInfo: [NSLocalizedDescriptionKey:
                "Selected Python is unavailable. Exit PadPilot and run the app's Contents/Resources/padpilot-cli --bundled-cli runtime bundled. / 選定的 Python 已不存在；請離開 PadPilot，使用內建 CLI 切回封裝版本。"])
        }
        return Runtime(python: python, project_root: resources.appendingPathComponent("PadPilot").path, bundled: true)
    }

    var cliArguments: [String] {
        (bundled == true ? ["-I", "-B"] : []) + [project_root + "/bin/padpilot-cli"]
    }
}

struct SettingsRequest {
    var page = "paired"
    var delete: String?
    var select: String?

    init?(url: URL) {
        guard url.scheme == "padpilot", url.host == "settings",
              let parts = URLComponents(url: url, resolvingAgainstBaseURL: false) else { return nil }
        var values: [String: String] = [:]
        for item in parts.queryItems ?? [] {
            guard ["page", "delete", "select"].contains(item.name), values[item.name] == nil,
                  let value = item.value else { return nil }
            values[item.name] = value
        }
        page = values["page"] ?? "paired"
        guard ["paired", "search", "settings", "displays", "virtual", "diagnostics", "about"].contains(page) else { return nil }
        for key in ["delete", "select"] {
            if let value = values[key], value.range(of: "^[0-9a-f]{64}$", options: .regularExpression) == nil { return nil }
        }
        delete = values["delete"]
        select = values["select"]
        if delete != nil && select != nil { return nil }
    }
}

struct MenuRow: Codable {
    let title: String
    let depth: Int
    let args: [String]
    let enabled: Bool
    let checked: Bool
    let separator: Bool
    var icon: String? = nil
}

func menuIcon(_ name: String) -> NSImage? {
    let allowed = ["ipad", "physical", "virtual", "paused", "working", "warning"]
    let name = allowed.contains(name) ? name : "warning"
    let url = Bundle.main.resourceURL?.appendingPathComponent("menu-icons/\(name).png")
    let image = url.flatMap { NSImage(contentsOf: $0) }
        ?? NSImage(systemSymbolName: "display", accessibilityDescription: "PadPilot")
    image?.isTemplate = true
    image?.size = NSSize(width: 18, height: 18)
    return image
}

struct MenuSnapshot: Codable {
    let schema_version: Int
    let hidden: Bool
    let icon: String
    let items: [MenuRow]
    var connection_hotkey: String? = nil
    var hotkey_error_message: String? = nil
}

// These are CLI argument arrays, never shell commands or device-provided code.
func validAction(_ args: [String]) -> Bool {
    if args.count == 1 { return ["start", "stop", "exit", "gui"].contains(args[0]) }
    if args.count == 2 {
        switch args[0] {
        case "action": return ["use_ipad_main", "use_ipad_secondary", "disconnect_ipad", "reconnect_sidecar", "connect_ipad", "refresh"].contains(args[1])
        case "set-mode": return ["automatic", "manual_only", "prefer_ipad"].contains(args[1])
        case "set-language": return ["en", "zh-Hant", "ja"].contains(args[1])
        case "autostart": return args[1] == "toggle"
        case "gui": return args[1] == "diagnostics"
        default: return false
        }
    }
    return args.count == 4 && args[0] == "gui" && args[1] == "wizard"
        && ["--select", "--delete"].contains(args[2])
        && args[3].range(of: "^[0-9a-f]{64}$", options: .regularExpression) != nil
}

func makeMenu(_ rows: [MenuRow], target: AnyObject, action: Selector, busy: Bool) -> NSMenu {
    let root = NSMenu()
    root.autoenablesItems = false
    var stack = [root]
    for row in rows {
        guard row.depth >= 0 && row.depth <= 4 else { continue }
        while stack.count > row.depth + 1 { stack.removeLast() }
        if row.depth == stack.count, let parent = stack.last?.items.last, !parent.isSeparatorItem {
            let submenu = NSMenu(title: parent.title)
            submenu.autoenablesItems = false
            parent.submenu = submenu
            stack.append(submenu)
        }
        guard row.depth == stack.count - 1, let menu = stack.last else { continue }
        if row.separator {
            if !menu.items.isEmpty && menu.items.last?.isSeparatorItem == false {
                menu.addItem(.separator())
            }
            continue
        }
        let allowed = validAction(row.args)
        let item = NSMenuItem(title: row.title, action: allowed ? action : nil, keyEquivalent: "")
        if let icon = row.icon { item.image = menuIcon(icon) }
        item.target = target
        item.representedObject = row.args
        item.isEnabled = row.enabled && (!busy || row.args.isEmpty || row.args.first == "gui")
        item.state = row.checked ? .on : .off
        menu.addItem(item)
    }
    return root
}

final class AppDelegate: NSObject, NSApplicationDelegate, NSMenuDelegate {
    private var statusItem: NSStatusItem!
    private var runtime: Runtime!
    private var timer: Timer?
    private var snapshot: MenuSnapshot?
    private var snapshotData: Data?
    private var reading = false
    private var busy = false
    private var menuOpen = false
    private var lastRead = Date.distantPast
    private var lastSignature = ""
    private var lockFD: Int32 = -1
    private var settingsController: SettingsWindowController?
    private var pendingSettings: [SettingsRequest] = []
    private var ready = false
    private var awaitingSettingsRequest = false
    private let support = padpilotHomeDirectory()
        .appendingPathComponent("Library/Application Support/PadPilot")

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.accessory)
        if let iconURL = Bundle.main.url(forResource: "PadPilot", withExtension: "icns"),
           let icon = NSImage(contentsOf: iconURL) { NSApp.applicationIconImage = icon }
        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.squareLength)
        statusItem.button?.toolTip = "PadPilot"
        statusItem.button?.setAccessibilityLabel("PadPilot")
        setIcon("working")
        do {
            runtime = try Runtime.load()
            if runtime.bundled == true && (Bundle.main.bundleURL.path.hasPrefix("/Volumes/") || Bundle.main.bundleURL.path.contains("/AppTranslocation/")) {
                throw NSError(domain: "PadPilot", code: 1, userInfo: [NSLocalizedDescriptionKey:
                    "Drag PadPilot to Applications, then open that copy. / 請先將 PadPilot 拖入「應用程式」，再開啟安裝的版本。 / PadPilot をアプリケーションに移動してから開いてください。"])
            }
            guard FileManager.default.isExecutableFile(atPath: runtime.python),
                  FileManager.default.fileExists(atPath: runtime.project_root + "/bin/padpilot-cli") else {
                throw NSError(domain: "PadPilot", code: 1, userInfo: [NSLocalizedDescriptionKey:
                    "Python or PadPilot source folder is missing. Rebuild/reinstall PadPilot from its current location."])
            }
            for directory in [support, support.appendingPathComponent("runtime")] {
                try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true,
                    attributes: [.posixPermissions: 0o700])
                let attributes = try FileManager.default.attributesOfItem(atPath: directory.path)
                guard attributes[.type] as? FileAttributeType == .typeDirectory,
                      (attributes[.ownerAccountID] as? NSNumber)?.uint32Value == getuid() else {
                    throw NSError(domain: "PadPilot", code: 3, userInfo: [NSLocalizedDescriptionKey: "Unsafe runtime directory"])
                }
                try FileManager.default.setAttributes([.posixPermissions: 0o700], ofItemAtPath: directory.path)
            }
            lockFD = Darwin.open(support.appendingPathComponent("runtime/menu-app.lock").path, O_CREAT | O_RDWR | O_CLOEXEC | O_NOFOLLOW, 0o600)
            guard lockFD >= 0 else { throw NSError(domain: NSPOSIXErrorDomain, code: Int(errno)) }
            var info = stat()
            guard fstat(lockFD, &info) == 0, info.st_uid == getuid(), info.st_nlink == 1,
                  (info.st_mode & S_IFMT) == S_IFREG else {
                throw NSError(domain: "PadPilot", code: 3, userInfo: [NSLocalizedDescriptionKey: "Unsafe runtime lock"])
            }
            guard fchmod(lockFD, 0o600) == 0 else { throw NSError(domain: NSPOSIXErrorDomain, code: Int(errno)) }
            guard flock(lockFD, LOCK_EX | LOCK_NB) == 0 else {
                // Launch Services normally reuses the running bundle. Also bring
                // it forward if another owned build already holds the app lock.
                if let existing = NSRunningApplication.runningApplications(withBundleIdentifier: "com.padpilot.app")
                    .first(where: { application in
                        guard application.processIdentifier != ProcessInfo.processInfo.processIdentifier,
                              let bundle = application.bundleURL,
                              let other = try? Runtime.load(bundle: bundle) else { return false }
                        return other.project_root == self.runtime.project_root
                    }),
                   let bundle = existing.bundleURL {
                    let requests = pendingSettings
                    if !requests.isEmpty || !CommandLine.arguments.contains("--menu-only") {
                        guard Bundle(url: bundle)?.object(forInfoDictionaryKey: "CFBundleURLTypes") != nil else {
                            showError("Close the previous PadPilot app, then reopen Settings. / 請先關閉舊版 PadPilot，再重新開啟設定。")
                            NSApp.terminate(nil); return
                        }
                        let urls = requests.isEmpty ? [URL(string: "padpilot://settings")!] : requests.map { request -> URL in
                            var parts = URLComponents(string: "padpilot://settings")!
                            parts.queryItems = [URLQueryItem(name: "page", value: request.page)]
                            if let key = request.delete { parts.queryItems?.append(URLQueryItem(name: "delete", value: key)) }
                            if let key = request.select { parts.queryItems?.append(URLQueryItem(name: "select", value: key)) }
                            return parts.url!
                        }
                        let configuration = NSWorkspace.OpenConfiguration()
                        configuration.createsNewApplicationInstance = false
                        NSWorkspace.shared.open(urls, withApplicationAt: bundle, configuration: configuration) { _, _ in
                            DispatchQueue.main.async { NSApp.terminate(nil) }
                        }
                        return
                    }
                } else if !CommandLine.arguments.contains("--menu-only") || !pendingSettings.isEmpty {
                    showError("Another PadPilot checkout is running. Close it before opening these settings. / 請先關閉另一份 PadPilot，再開啟這份設定。")
                }
                NSApp.terminate(nil); return
            }
            ready = true
            ConnectionHotKey.shared.onPress = { [weak self] in self?.requestConnection() }
            let settingsOnly = CommandLine.arguments.contains("--settings") || !pendingSettings.isEmpty
            awaitingSettingsRequest = settingsOnly && pendingSettings.isEmpty
            for request in pendingSettings { showSettings(request.page, delete: request.delete, select: request.select) }
            pendingSettings.removeAll()
            if settingsOnly {
                beginPolling()
                return
            }
            if !CommandLine.arguments.contains("--menu-only") { showSettings() }
            // Explicitly opening the app resumes the service once. Stopping it from
            // the menu leaves it stopped; polling never starts or scans hardware.
            runCLI(["start", "--no-menu"], timeout: 75) { result in
                if case .failure(let error) = result { self.showError(error.localizedDescription) }
                self.beginPolling()
            }
        } catch { showError(error.localizedDescription); recoveryMenu() }
    }

    private func beginPolling() {
        refresh(force: true)
        let timer = Timer(timeInterval: 1, repeats: true) { [weak self] _ in self?.refresh() }
        self.timer = timer
        RunLoop.main.add(timer, forMode: .common)
    }

    func application(_ application: NSApplication, open urls: [URL]) {
        for url in urls {
            guard let request = SettingsRequest(url: url) else { continue }
            awaitingSettingsRequest = false
            if ready { showSettings(request.page, delete: request.delete, select: request.select) }
            else { pendingSettings.append(request) }
        }
    }

    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        if ready { showSettings() }
        return false
    }

    private func showSettings(_ page: String = "paired", delete: String? = nil, select: String? = nil) {
        guard runtime != nil else { return }
        if settingsController == nil { settingsController = SettingsWindowController(runtime: runtime) }
        settingsController?.show(page: page == "wizard" ? "search" : page, delete: delete, select: select)
    }

    #if MENU_TESTING
    var checkMenuVisible: Bool { statusItem?.isVisible == true && statusItem.menu != nil }
    #endif

    private func setIcon(_ name: String) {
        statusItem.button?.image = menuIcon(name)
    }

    private func signature() -> String {
        let fallback = URL(fileURLWithPath: "/tmp/PadPilot")
        let files = [support.appendingPathComponent("config.json"), support.appendingPathComponent("runtime/status.json"),
                     support.appendingPathComponent("menu-hidden"), fallback.appendingPathComponent("config.json"),
                     fallback.appendingPathComponent("runtime/status.json"), fallback.appendingPathComponent("menu-hidden")]
        return files.map { url in
            let values = try? url.resourceValues(forKeys: [.contentModificationDateKey, .fileSizeKey])
            return "\(values?.contentModificationDate?.timeIntervalSince1970 ?? 0):\(values?.fileSize ?? 0)"
        }.joined(separator: ";")
    }

    private func refresh(force: Bool = false) {
        guard runtime != nil, !reading, !busy else { return }
        let signature = signature()
        // Read the snapshots after file changes; the 5s fallback also discovers a
        // crashed daemon and freshness expiry without keeping a Python process alive.
        guard force || signature != lastSignature || Date().timeIntervalSince(lastRead) >= 5 else { return }
        reading = true
        lastSignature = signature
        lastRead = Date()
        runCLI(["menu-json"], timeout: 5) { result in
            self.reading = false
            do {
                let data = try result.get()
                let model = try JSONDecoder().decode(MenuSnapshot.self, from: data)
                guard model.schema_version == 1 else { throw NSError(domain: "PadPilot", code: 2,
                    userInfo: [NSLocalizedDescriptionKey: "Unsupported menu schema. Rebuild PadPilot.app."]) }
                self.statusItem.isVisible = !model.hidden
                if ConnectionHotKey.shared.configure(model.hidden ? "" : model.connection_hotkey ?? ""),
                   ConnectionHotKey.shared.errorCode != noErr {
                    self.shortcutNotice(model.hotkey_error_message ?? "Cannot register connection shortcut.")
                }
                if model.hidden && !self.awaitingSettingsRequest,
                   self.settingsController?.window?.isVisible != true,
                   self.settingsController?.window?.isMiniaturized != true {
                    NSApp.terminate(nil); return
                }
                self.setIcon(model.icon)
                if data != self.snapshotData {
                    self.snapshotData = data
                    self.snapshot = model
                    if !self.menuOpen { self.rebuildMenu() }
                }
            } catch {
                ConnectionHotKey.shared.configure("")
                self.snapshotData = nil
                self.snapshot = nil
                self.setIcon("warning")
                if !self.menuOpen { self.recoveryMenu(error.localizedDescription) }
            }
        }
    }

    private func rebuildMenu() {
        guard let snapshot else { recoveryMenu(); return }
        let menu = makeMenu(snapshot.items, target: self, action: #selector(performAction(_:)), busy: busy)
        menu.delegate = self
        statusItem.menu = menu
    }

    private func recoveryMenu(_ message: String = "PadPilot is not ready") {
        let menu = NSMenu()
        menu.autoenablesItems = false
        let info = NSMenuItem(title: message, action: nil, keyEquivalent: "")
        info.isEnabled = false
        menu.addItem(info)
        let retry = NSMenuItem(title: "Retry / 重試", action: #selector(retryRefresh), keyEquivalent: "")
        retry.target = self
        menu.addItem(retry)
        let quit = NSMenuItem(title: "Close Menu / 關閉選單", action: #selector(closeMenu), keyEquivalent: "")
        quit.target = self
        menu.addItem(quit)
        statusItem.menu = menu
    }

    @objc private func retryRefresh() { refresh(force: true) }
    @objc private func closeMenu() { NSApp.terminate(nil) }

    func menuWillOpen(_ menu: NSMenu) { menuOpen = true; refresh(force: true) }
    func menuDidClose(_ menu: NSMenu) {
        menuOpen = false
        DispatchQueue.main.async { self.rebuildMenu() }
    }

    private func requestConnection() {
        guard !busy, runtime != nil, snapshot?.hidden == false else { return }
        busy = true
        runCLI(["action", "connect_ipad"], timeout: 75) { result in
            self.busy = false
            if case .failure(let error) = result {
                self.shortcutNotice(error.localizedDescription)
            }
            self.refresh(force: true)
        }
    }

    private func shortcutNotice(_ message: String) {
        // Connection errors never use showError's modal NSAlert.
        statusItem.button?.toolTip = message
        let notification = NSUserNotification()
        notification.identifier = "padpilot-connection-shortcut"
        notification.title = "PadPilot"
        notification.informativeText = message
        NSUserNotificationCenter.default.deliver(notification)
    }

    @objc private func performAction(_ item: NSMenuItem) {
        guard let args = item.representedObject as? [String], validAction(args), runtime != nil else { return }
        let isGUI = args.first == "gui"
        guard isGUI || !busy else { return }
        // Recheck the last refreshed model when a menu stayed open across a change.
        guard snapshot?.items.contains(where: { $0.args == args && $0.enabled }) == true else {
            refresh(force: true); return
        }
        if isGUI {
            showSettings(args.count > 1 ? args[1] : "paired",
                         delete: args.count == 4 && args[2] == "--delete" ? args[3] : nil,
                         select: args.count == 4 && args[2] == "--select" ? args[3] : nil)
            return
        }
        if !isGUI { busy = true; setIcon("working") }
        runCLI(args, timeout: isGUI ? nil : 75) { result in
            if !isGUI { self.busy = false }
            switch result {
            case .success:
                if args == ["exit"] { NSApp.terminate(nil); return }
            case .failure(let error): self.showError(error.localizedDescription)
            }
            self.refresh(force: true)
        }
    }

    private func showError(_ message: String) {
        let alert = NSAlert()
        alert.messageText = "PadPilot"
        alert.informativeText = message
        alert.alertStyle = .warning
        NSApp.activate(ignoringOtherApps: true)
        alert.runModal()
    }

    private func runCLI(_ arguments: [String], timeout: Double?, completion: @escaping (Result<Data, Error>) -> Void) {
        let python = runtime.python
        let root = runtime.project_root
        let cliArguments = runtime.cliArguments
        DispatchQueue.global(qos: .utility).async {
            let process = Process()
            let pipe = Pipe()
            process.executableURL = URL(fileURLWithPath: python)
            process.arguments = cliArguments + arguments
            process.currentDirectoryURL = URL(fileURLWithPath: root)
            process.standardInput = FileHandle.nullDevice
            process.standardOutput = pipe
            process.standardError = pipe
            var environment = ProcessInfo.processInfo.environment
            environment["PATH"] = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
            environment["PYTHONIOENCODING"] = "utf-8"
            process.environment = environment
            do {
                try process.run()
                let deadline = timeout.map { seconds -> DispatchWorkItem in
                    let work = DispatchWorkItem {
                        if process.isRunning { process.terminate() }
                    }
                    DispatchQueue.global().asyncAfter(deadline: .now() + seconds, execute: work)
                    return work
                }
                let data = pipe.fileHandleForReading.readDataToEndOfFile()
                process.waitUntilExit()
                deadline?.cancel()
                let result: Result<Data, Error>
                if process.terminationStatus == 0 { result = .success(data) }
                else {
                    let message = String(data: data, encoding: .utf8) ?? ""
                    result = .failure(NSError(domain: "PadPilot", code: Int(process.terminationStatus), userInfo:
                        [NSLocalizedDescriptionKey: message.isEmpty ? "Command failed or timed out. Its result is unknown; check Status & Diagnostics before retrying." : message]))
                }
                DispatchQueue.main.async { completion(result) }
            } catch { DispatchQueue.main.async { completion(.failure(error)) } }
        }
    }

    func applicationWillTerminate(_ notification: Notification) {
        timer?.invalidate()
        ConnectionHotKey.shared.stop()
        if lockFD >= 0 { Darwin.close(lockFD) }
    }
}

#if !MENU_TESTING
@main
struct PadPilot {
    static func main() {
        let arguments = Array(CommandLine.arguments.dropFirst())
        if arguments.first == "--locate-betterdisplay" {
            if let url = NSWorkspace.shared.urlForApplication(withBundleIdentifier: "pro.betterdisplay.BetterDisplay") {
                print(url.path); exit(0)
            }
            exit(1)
        }
        if ["--cli", "--bundled-cli", "--runtime-info"].contains(arguments.first ?? "") {
            do {
                let runtime = try Runtime.load(useBundled: arguments.first == "--bundled-cli")
                if arguments.first == "--runtime-info" {
                    let data = try JSONSerialization.data(withJSONObject: ["python": runtime.python, "project_root": runtime.project_root, "bundled": runtime.bundled == true], options: [.sortedKeys])
                    FileHandle.standardOutput.write(data); print(); return
                }
                let process = Process()
                process.executableURL = URL(fileURLWithPath: runtime.python)
                process.arguments = runtime.cliArguments + Array(arguments.dropFirst())
                process.currentDirectoryURL = URL(fileURLWithPath: runtime.project_root)
                process.standardInput = FileHandle.standardInput
                process.standardOutput = FileHandle.standardOutput
                process.standardError = FileHandle.standardError
                try process.run(); process.waitUntilExit(); exit(process.terminationStatus)
            } catch {
                FileHandle.standardError.write(Data(("PadPilot: \(error.localizedDescription)\n").utf8)); exit(1)
            }
        }
        let app = NSApplication.shared
        let delegate = AppDelegate()
        app.delegate = delegate
        withExtendedLifetime(delegate) { app.run() }
    }
}
#endif
