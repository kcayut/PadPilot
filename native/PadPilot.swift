import AppKit
import Foundation
import Darwin

struct Runtime: Decodable {
    let python: String
    let project_root: String
}

struct MenuRow: Codable {
    let title: String
    let depth: Int
    let args: [String]
    let enabled: Bool
    let checked: Bool
    let separator: Bool
}

struct MenuSnapshot: Codable {
    let schema_version: Int
    let hidden: Bool
    let icon: String
    let items: [MenuRow]
}

// These are CLI argument arrays, never shell commands or device-provided code.
func validAction(_ args: [String]) -> Bool {
    if args.count == 1 { return ["start", "stop", "exit", "gui"].contains(args[0]) }
    if args.count == 2 {
        switch args[0] {
        case "action": return ["use_ipad_main", "use_ipad_secondary", "disconnect_ipad", "reconnect_sidecar", "refresh"].contains(args[1])
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
    private let support = FileManager.default.homeDirectoryForCurrentUser
        .appendingPathComponent("Library/Application Support/PadPilot")

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.accessory)
        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.squareLength)
        statusItem.button?.toolTip = "PadPilot"
        statusItem.button?.setAccessibilityLabel("PadPilot")
        setIcon("working")
        do {
            let resources = Bundle.main.resourceURL!
            runtime = try JSONDecoder().decode(Runtime.self, from: Data(contentsOf: resources.appendingPathComponent("runtime.json")))
            guard FileManager.default.isExecutableFile(atPath: runtime.python),
                  FileManager.default.fileExists(atPath: runtime.project_root + "/bin/padpilot-cli") else {
                throw NSError(domain: "PadPilot", code: 1, userInfo: [NSLocalizedDescriptionKey:
                    "Python or PadPilot source folder is missing. Rebuild/reinstall PadPilot from its current location."])
            }
            try FileManager.default.createDirectory(at: support.appendingPathComponent("runtime"), withIntermediateDirectories: true)
            lockFD = Darwin.open(support.appendingPathComponent("runtime/menu-app.lock").path, O_CREAT | O_RDWR | O_CLOEXEC, 0o600)
            guard lockFD >= 0 else { throw NSError(domain: NSPOSIXErrorDomain, code: Int(errno)) }
            guard flock(lockFD, LOCK_EX | LOCK_NB) == 0 else { NSApp.terminate(nil); return }
            // Explicitly opening the app resumes the service once. Stopping it from
            // the menu leaves it stopped; polling never starts or scans hardware.
            runCLI(["start", "--no-menu"], timeout: 15) { result in
                if case .failure(let error) = result { self.showError(error.localizedDescription) }
                self.refresh(force: true)
                let timer = Timer(timeInterval: 1, repeats: true) { [weak self] _ in self?.refresh() }
                self.timer = timer
                RunLoop.main.add(timer, forMode: .common)
            }
        } catch { showError(error.localizedDescription); recoveryMenu() }
    }

    private func setIcon(_ name: String) {
        let allowed = ["ipad", "physical", "virtual", "paused", "working", "warning"]
        let name = allowed.contains(name) ? name : "warning"
        let url = Bundle.main.resourceURL?.appendingPathComponent("menu-icons/\(name).png")
        let image = url.flatMap { NSImage(contentsOf: $0) }
            ?? NSImage(systemSymbolName: "display", accessibilityDescription: "PadPilot")
        image?.isTemplate = true
        image?.size = NSSize(width: 18, height: 18)
        statusItem.button?.image = image
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
                if model.hidden { NSApp.terminate(nil); return }
                self.setIcon(model.icon)
                if data != self.snapshotData {
                    self.snapshotData = data
                    self.snapshot = model
                    if !self.menuOpen { self.rebuildMenu() }
                }
            } catch {
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

    @objc private func performAction(_ item: NSMenuItem) {
        guard let args = item.representedObject as? [String], validAction(args), runtime != nil else { return }
        let isGUI = args.first == "gui"
        guard isGUI || !busy else { return }
        // Recheck the last refreshed model when a menu stayed open across a change.
        guard snapshot?.items.contains(where: { $0.args == args && $0.enabled }) == true else {
            refresh(force: true); return
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
        DispatchQueue.global(qos: .utility).async {
            let process = Process()
            let pipe = Pipe()
            process.executableURL = URL(fileURLWithPath: python)
            process.arguments = [root + "/bin/padpilot-cli"] + arguments
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
        if lockFD >= 0 { Darwin.close(lockFD) }
    }
}

#if !MENU_TESTING
@main
struct PadPilot {
    static func main() {
        let app = NSApplication.shared
        let delegate = AppDelegate()
        app.delegate = delegate
        withExtendedLifetime(delegate) { app.run() }
    }
}
#endif
