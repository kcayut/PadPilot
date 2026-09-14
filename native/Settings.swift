import ServiceManagement
import AppKit
import SwiftUI
import Foundation
import Darwin

// Match Python's Path.home() for CLI launches and isolated release checks.
func padpilotHomeDirectory() -> URL {
    if let home = ProcessInfo.processInfo.environment["HOME"], home.hasPrefix("/") {
        return URL(fileURLWithPath: home, isDirectory: true)
    }
    return FileManager.default.homeDirectoryForCurrentUser
}

private typealias SettingsObject = [String: Any]
private typealias SettingsState<Value> = SwiftUI.State<Value>
private let settingsLogPattern = try! NSRegularExpression(pattern: "(?m)^(\\d{4}-\\d{2}-\\d{2} \\d{2}:\\d{2}:\\d{2})\\s+\\[([A-Z]+)\\]\\s+\\[(.*?)\\]\\s+(.*)$")
private func settingsFont(_ style: NSFont.TextStyle, monospaced: Bool = false) -> Font {
    let font = NSFont.preferredFont(forTextStyle: style)
    if monospaced { return .system(size: font.pointSize + 2, design: .monospaced) }
    return Font(NSFont(descriptor: font.fontDescriptor, size: font.pointSize + 2) ?? font)
}
private extension Dictionary where Key == String, Value == Any {
    func text(_ key: String, _ fallback: String = "") -> String {
        if let value = self[key] as? String { return value.isEmpty ? fallback : value }
        if let value = self[key] as? NSNumber { return value.stringValue }
        return fallback
    }
    func flag(_ key: String) -> Bool { (self[key] as? Bool) ?? false }
    func object(_ key: String) -> SettingsObject { self[key] as? SettingsObject ?? [:] }
    func rows(_ key: String) -> [SettingsObject] { self[key] as? [SettingsObject] ?? [] }
}

private let settingsPages: [(String, String, String)] = [
    ("paired", "已配對 iPad", "ipad"), ("search", "搜尋新裝置", "magnifyingglass"),
    ("settings", "運作與偏好", "gearshape"), ("displays", "連線螢幕狀態", "display.2"),
    ("virtual", "虛擬備援螢幕", "rectangle.dashed"), ("diagnostics", "狀態與診斷", "stethoscope"),
    ("about", "關於", "info.circle")
]
private let settingsModes: [(String, String, String)] = [
    ("manual_only", "僅手動模式", "平時只接受選單或全域快速鍵的手動要求；斷線後不自行重連。可另外啟用開機時的一次連線。"),
    ("automatic", "自動模式", "無實體螢幕時自動連線 iPad 並設為主螢幕；有實體螢幕時以實體為主，已連線的 iPad 保持為副螢幕。"),
    ("prefer_ipad", "偏好 iPad 模式", "即使已接上實體螢幕，依然優先連線 iPad 並將其作為主要顯示器。")
]

private final class SettingsModel: ObservableObject {
    @Published var data: SettingsObject = [:]
    @Published var page: String? = "paired"
    @Published var busy = false
    @Published var notice = ""
    @Published var drafts: [String: String] = [:]
    @Published var logFilter = "all"
    @Published var logsAutoUpdate = false
    @Published var logText = ""
    var draftRevisions: [String: Int] = [:]
    private let runtime: Runtime
    private var timer: Timer?
    private var reading = false
    private(set) var visible = false
    private var pendingSelection: (String, Bool)?
    private var pendingRefresh: (Bool, String?, Bool)?
    private var snapshotEpoch = 0
    #if PADPILOT_GUI_CHECKS
    var fixtureMode = false
    var recordedCommands: [[String: Any]] = []
    var confirmationAnswer: Bool?
    var injectedFailure: String?
    #else
    let fixtureMode = false
    #endif
    private var confirmationRevision: Int?
    var languageDidChange: (() -> Void)?
    weak var window: NSWindow?

    init(runtime: Runtime) { self.runtime = runtime }
    var config: SettingsObject { data.object("config") }
    var actual: SettingsObject { data.object("actual") }
    var status: SettingsObject { data.object("status") }
    var paths: SettingsObject { data.object("paths") }
    var revision: Int { (config["revision"] as? Int) ?? (data["config_revision"] as? Int) ?? 0 }
    var readonly: Bool { !data.text("config_error").isEmpty || data.isEmpty }
    var disabled: Bool { readonly || busy }
    var profiles: [SettingsObject] { data.rows("profiles") }
    var candidates: [SettingsObject] { actual.rows("sidecar_devices").filter { !$0.text("uuid").isEmpty } }
    var usbs: [SettingsObject] { actual.rows("usb_devices").filter { !$0.text("serial").isEmpty } }
    var virtuals: [SettingsObject] { data.rows("virtuals") }
    var language: String { config.text("language", "en") }
    func donationEnabled(_ name: String) -> Bool { !data.object("donations").text(name).isEmpty }
    var title: String { tr(settingsPages.first { $0.0 == page }?.1 ?? "PadPilot") }
    var modeTitle: String { tr(settingsModes.first { $0.0 == config.text("mode") }?.1 ?? "未知") }
    var targetName: String {
        if config.flag("auto_detect_ipad") { return actual.object("resolved_ipad").text("name", tr("尚無唯一目標")) }
        return config.object("ipad").text("name", tr("尚未指定"))
    }
    func tr(_ key: String, _ values: String...) -> String {
        var text = (data["strings"] as? [String: String])?[key] ?? key
        for (index, value) in values.enumerated() { text = text.replacingOccurrences(of: "{\(index)}", with: value) }
        return text
    }
    func profile(_ entry: SettingsObject) -> SettingsObject {
        if let ipad = entry["ipad"] as? SettingsObject { return ipad }
        return ["name": entry.text("name"), "sidecar_uuid": entry.text("sidecar_uuid"), "usb_serial": entry.text("usb_serial")]
    }
    func isTarget(_ entry: SettingsObject) -> Bool { entry.flag("is_target") }
    func binding(_ key: String, fallback: String) -> Binding<String> {
        Binding(get: { self.drafts[key] ?? fallback }, set: { value in
            if self.drafts[key] == nil { self.draftRevisions[key] = self.revision }
            self.drafts[key] = value
        })
    }
    func begin(page requestedPage: String, delete: String?, select: String?) {
        page = ["wizard": "search", "prefs": "settings", "help": "about"][requestedPage] ?? requestedPage
        if !settingsPages.contains(where: { $0.0 == page }) { page = "paired" }
        if let key = delete ?? select { pendingSelection = (key, delete != nil); page = "paired" }
        visible = true
        timer?.invalidate()
        if fixtureMode { return }
        timer = Timer.scheduledTimer(withTimeInterval: 3, repeats: true) { [weak self] _ in
            self?.poll()
        }
        // Opening an existing window never initiates another hardware scan.
        refresh(scan: data.isEmpty && delete == nil && select == nil)
    }
    func poll() {
        guard visible, !busy else { return }
        refresh()
    }
    func stop() {
        visible = false; snapshotEpoch += 1
        timer?.invalidate(); timer = nil; pendingRefresh = nil; pendingSelection = nil
    }
    func refresh(scan: Bool = false, section: String? = nil, rebaseDrafts: Bool = false) {
        guard visible else { return }
        if reading {
            if scan || section != nil || rebaseDrafts { pendingRefresh = (scan, section, rebaseDrafts) }
            return
        }
        guard !busy, window?.attachedSheet == nil else { return }
        reading = true
        let explicit = scan || section != nil
        if explicit { busy = true; notice = tr("處理中，請稍候…") }
        var args = ["gui-data"]
        if scan || section == "system_checks" || section == "diagnostics" { args.append("--scan") }
        if section == "system_checks" || section == "diagnostics" { args.append("--diagnostics") }
        if section == "authenticated_checks" { args.append("--admin-checks") }
        if section == "logs" || section == "diagnostics" || (section == nil && !scan && page == "diagnostics" && logsAutoUpdate) { args.append("--logs") }
        if section == "decision" { args.append("--refresh") }
        let epoch = snapshotEpoch
        execute(args, timeout: section == "authenticated_checks" ? 180 : (explicit ? 75 : 10)) { result in
            self.reading = false
            if explicit { self.busy = false }
            defer {
                if let pending = self.pendingRefresh {
                    self.pendingRefresh = nil
                    self.refresh(scan: pending.0, section: pending.1, rebaseDrafts: pending.2)
                }
            }
            guard self.visible, epoch == self.snapshotEpoch else { return }
            do {
                guard let next = try JSONSerialization.jsonObject(with: result.get()) as? SettingsObject,
                      next["schema_version"] as? Int == 1, next["config"] is SettingsObject else {
                    throw self.failure(self.tr("設定資料回應無效，請重新安裝 PadPilot。"))
                }
                guard self.window?.attachedSheet == nil else { return }
                self.applySnapshot(next)
                if rebaseDrafts { for key in self.drafts.keys { self.draftRevisions[key] = self.revision } }
                if let pending = self.pendingSelection {
                    self.pendingSelection = nil
                    if let entry = self.profiles.first(where: { $0.text("key") == pending.0 }) {
                        if pending.1 { self.delete(entry) } else { self.select(entry) }
                    } else { self.showError(self.tr("配對紀錄已變更或不存在，請重新開啟清單。")) }
                }
            } catch { if explicit || self.data.isEmpty { self.showError(error.localizedDescription) } }
        }
    }
    func applySnapshot(_ incoming: SettingsObject) {
        let previousLanguage = language
        let hadStrings = data["strings"] != nil
        var next = incoming
        var before = config, after = incoming.object("config")
        for key in ["revision", "language", "updated_at"] { before.removeValue(forKey: key); after.removeValue(forKey: key) }
        let sameSettings = NSDictionary(dictionary: before).isEqual(to: after)
        let oldStamp = actual["timestamp"] as? Double ?? 0
        let newStamp = incoming.object("actual")["timestamp"] as? Double ?? 0
        if sameSettings && oldStamp > newStamp {
            let age = Date().timeIntervalSince1970 - oldStamp
            next["actual"] = actual; next["hardware_snapshot"] = actual
            next["hardware_snapshot_age"] = max(0, age); next["fresh"] = age >= 0 && age <= 120
            let oldStrings = data["strings"] as? [String: String] ?? [:]
            let newStrings = incoming["strings"] as? [String: String] ?? [:]
            let statuses = ["已連線", "已偵測到 Sidecar", "僅 USB 已接上", "狀態未知", "未偵測到"]
            next["profiles"] = incoming.rows("profiles").map { entry -> SettingsObject in
                var updated = entry
                if let previous = profiles.first(where: { $0.text("key") == entry.text("key") }) {
                    let key = previous.text("status_key", statuses.first { (oldStrings[$0] ?? $0) == previous.text("status") } ?? "狀態未知")
                    updated["status_key"] = next.flag("fresh") ? key : "狀態未知"
                    updated["status"] = newStrings[updated.text("status_key")] ?? updated.text("status_key")
                }
                return updated
            }
            var decision = next.object("decision")
            decision["fresh"] = next.flag("fresh")
            if !next.flag("fresh") { decision["satisfaction"] = newStrings["資料待更新"] ?? "資料待更新" }
            next["decision"] = decision
        }
        if !next.flag("scanned") {
            for key in ["identifiers", "virtuals"] where data[key] != nil { next[key] = data[key] }
        }
        for key in ["system_checks", "authenticated_checks"] where next[key] == nil { next[key] = data[key] }
        data = next
        if let logs = next["logs"] as? String { logText = logs }
        window?.title = "PadPilot"
        notice = next.text("config_error", next.text("notice"))
        if notice.isEmpty {
            let errors = actual.object("discovery_errors").values.compactMap { $0 as? String }
            if !errors.isEmpty { notice = tr("部分狀態未知：") + errors.joined(separator: "；") }
            else if data.text("consistency_state") == "APPLYING_CONFIG" { notice = tr("正在套用新設定至硬體…") }
            else if data.text("consistency_state") == "REVISION_CONFLICT" { notice = tr("⚠️ 設定版本不同步，正在重新整理…") }
            else {
                let clock = DateFormatter()
                clock.locale = Locale(identifier: "en_US_POSIX"); clock.dateFormat = "HH:mm:ss"
                notice = tr("更新於 {0} · {1} 台已配對", clock.string(from: Date()), String(profiles.count))
            }
        }
        if !hadStrings || language != previousLanguage { languageDidChange?() }
    }
    func change(_ operation: String, _ values: SettingsObject, draftKey: String? = nil) {
        guard !disabled else { return }
        var payload = values
        payload["__expected_revision__"] = draftKey.flatMap { draftRevisions[$0] } ?? confirmationRevision ?? revision
        guard let input = try? JSONSerialization.data(withJSONObject: payload) else { return }
        snapshotEpoch += 1
        busy = true
        notice = tr("處理中，請稍候…")
        let args = operation == "set_autostart"
            ? ["autostart", values.flag("enabled") ? "enable" : "disable", "--expected-revision", String(payload["__expected_revision__"] as? Int ?? revision)]
            : ["change-settings", operation]
        execute(args, input: operation == "set_autostart" ? nil : input, timeout: 75) { result in
            self.busy = false
            switch result {
            case .success:
                if let key = draftKey { self.drafts.removeValue(forKey: key); self.draftRevisions.removeValue(forKey: key) }
                self.refresh(scan: !["set_language", "set_mode", "set_autostart", "set_connection_hotkey", "set_connect_on_boot"].contains(operation))
            case .failure(let error):
                let conflict = error.localizedDescription.contains("CONFIG_CONFLICT")
                self.showError(conflict ? self.tr("此設定已被其他來源（如 Menu Bar 或 CLI）修改。\n\n您輸入的內容已保留，請檢視最新狀態後再次儲存。") : error.localizedDescription) {
                    self.refresh(rebaseDrafts: conflict)
                }
            }
        }
    }
    func control(_ entry: SettingsObject, action: String) {
        guard !disabled, entry.flag("can_control"), !entry.text("key").isEmpty else { return }
        snapshotEpoch += 1
        busy = true
        execute(["action", action, "--expected-revision", String(revision), "--target-key", entry.text("key")], timeout: 75) { result in
            self.busy = false
            if case .failure(let error) = result { self.showError(error.localizedDescription) }
            self.refresh(scan: true)
        }
    }
    func delete(_ entry: SettingsObject) {
        let ipad = profile(entry)
        var detail = tr("裝置：{0}\n僅刪除 PadPilot 的配對紀錄，不解除 Apple 系統配對。", ipad.text("name"))
        if isTarget(entry) { detail += tr("\n這是目前主力 iPad；刪除後改為僅手動模式，保留目前螢幕連線。") }
        confirm(tr("確定刪除配對?"), detail, danger: true) { self.change("delete_pairing", ["key": entry.text("key")]) }
    }
    func select(_ entry: SettingsObject) {
        confirm(tr("指定為主要管理 iPad?"), tr("裝置：{0}\n當未接外接螢幕時，系統將自動連線此 iPad 並將其切換為主顯示器。\n（將清除原主力 iPad 的暫時覆寫）", profile(entry).text("name"))) {
            self.change("save_pairing", ["ipad": self.profile(entry), "activate": true])
        }
    }
    func saveName(_ entry: SettingsObject, key: String) {
        var ipad = profile(entry)
        let name = (drafts[key] ?? ipad.text("name")).trimmingCharacters(in: .whitespacesAndNewlines)
        guard !name.isEmpty else { showError(tr("請輸入有效的裝置名稱。")); return }
        guard name != ipad.text("name") else { return }
        confirm(tr("確定更新裝置名稱?"), tr("是否將名稱由：\n{0}\n\n更改成：\n{1}", ipad.text("name"), name)) {
            ipad["name"] = name
            self.change("save_pairing", ["ipad": ipad, "activate": self.isTarget(entry)], draftKey: key)
        }
    }
    func saveUSB(_ entry: SettingsObject, key: String) {
        var ipad = profile(entry)
        let serial = drafts[key] ?? ipad.text("usb_serial")
        guard serial != ipad.text("usb_serial") else { return }
        confirm(tr("確定更新 USB 設定?"), tr("裝置：{0}\n\n是否將 USB 序號由：\n原設定：{1}\n變更為：{2}", ipad.text("name"), ipad.text("usb_serial", tr("未設定")), serial.isEmpty ? tr("略過 / 未綁定") : serial)) {
            ipad["usb_serial"] = serial
            self.change("save_pairing", ["ipad": ipad, "activate": self.isTarget(entry)], draftKey: key)
        }
    }
    func saveCandidate(_ candidate: SettingsObject, activate: Bool) {
        let uuid = candidate.text("uuid"), key = "candidate.\(candidate.text("uuid"))"
        let name = (drafts[key] ?? candidate.text("name")).trimmingCharacters(in: .whitespacesAndNewlines)
        guard !name.isEmpty else { showError(tr("請輸入有效的裝置名稱。")); return }
        let save = { self.change("save_pairing", ["ipad": ["name": name, "sidecar_uuid": uuid, "usb_serial": self.drafts["candidateUSB.\(uuid)"] ?? ""], "activate": activate], draftKey: key) }
        if activate { confirm(tr("指定為主要管理 iPad?"), tr("當未接外接螢幕時，系統將自動連線並以此 iPad 作為主要顯示器。"), action: save) }
        else { save() }
    }
    func setVirtual(_ name: String) {
        guard !name.isEmpty else { return }
        confirm(tr("指定為虛擬備援?"), tr("螢幕：{0}\n之後以此螢幕作為備援；依目前模式可能啟用它，不主動移除原有備援連線。", name)) {
            self.change("set_virtual_display", ["name": name])
        }
    }
    func confirm(_ title: String, _ detail: String, danger: Bool = false, action: @escaping () -> Void) {
        guard !disabled, let window else { return }
        #if PADPILOT_GUI_CHECKS
        if fixtureMode, let answer = confirmationAnswer { if answer { action() }; return }
        #endif
        let expectedRevision = revision
        let alert = NSAlert()
        alert.messageText = title; alert.informativeText = detail
        alert.alertStyle = danger ? .warning : .informational
        alert.addButton(withTitle: tr("否")); alert.addButton(withTitle: tr("是"))
        alert.window.defaultButtonCell = alert.buttons[0].cell as? NSButtonCell
        alert.buttons[0].keyEquivalent = "\r"; alert.buttons[1].keyEquivalent = ""
        // AppKit clears the default button when its key becomes Escape. Keep Return
        // native and handle Escape only while this particular confirmation is open.
        let cancelKeyMonitor = NSEvent.addLocalMonitorForEvents(matching: .keyDown) { event in
            if event.window === alert.window && event.keyCode == 53 {
                alert.buttons[0].performClick(nil)
                return nil
            }
            return event
        }
        alert.beginSheetModal(for: window) { response in
            if let cancelKeyMonitor { NSEvent.removeMonitor(cancelKeyMonitor) }
            if response == .alertSecondButtonReturn {
                self.confirmationRevision = expectedRevision
                action()
                self.confirmationRevision = nil
            }
        }
    }
    func showError(_ message: String, completion: (() -> Void)? = nil) {
        notice = message
        guard !fixtureMode, visible, let window else { completion?(); return }
        let alert = NSAlert(); alert.messageText = "PadPilot"; alert.informativeText = message
        alert.alertStyle = .warning; alert.addButton(withTitle: tr("確認"))
        alert.beginSheetModal(for: window) { _ in completion?() }
    }
    func open(_ value: String) {
        guard let url = URL(string: value), ["https", "http"].contains(url.scheme?.lowercased() ?? "") else { return }
        NSWorkspace.shared.open(url)
    }
    func openLink(_ key: String) { open(data.object("links").text(key)) }
    func openLog() {
        let path = paths.text("log")
        if !path.isEmpty { NSWorkspace.shared.open(URL(fileURLWithPath: path)) }
    }
    var filteredLogs: String {
        if logFilter == "all" { return logText }
        return logText.split(separator: "\n", omittingEmptySubsequences: false).filter { line in
            let text = String(line)
            guard let match = settingsLogPattern.firstMatch(in: text, range: NSRange(location: 0, length: (text as NSString).length)) else { return false }
            let level = (text as NSString).substring(with: match.range(at: 2))
            switch logFilter {
            case "warning": return level == "WARNING" || level == "ERROR"
            case "error": return level == "ERROR"
            case "info": return level == "INFO"
            default: return true
            }
        }.joined(separator: "\n")
    }
    private func failure(_ message: String) -> NSError {
        NSError(domain: "PadPilot", code: 1, userInfo: [NSLocalizedDescriptionKey: message])
    }
    private func execute(_ arguments: [String], input: Data? = nil, timeout: Double, completion: @escaping (Result<Data, Error>) -> Void) {
        #if PADPILOT_GUI_CHECKS
        if fixtureMode {
            recordedCommands.append(["args": arguments, "payload": input.flatMap { try? JSONSerialization.jsonObject(with: $0) } ?? [:]])
            if arguments.first != "gui-data", let message = injectedFailure {
                injectedFailure = nil; completion(.failure(failure(message))); return
            }
            let response = arguments.first == "gui-data" ? (try? JSONSerialization.data(withJSONObject: data)) ?? Data() : Data()
            completion(.success(response)); return
        }
        #endif
        let runtime = runtime
        let commandError = tr("指令未完成或已逾時；請先檢查「狀態與診斷」，再決定是否重試。")
        DispatchQueue.global(qos: .utility).async {
            let process = Process(), output = Pipe(), errors = Pipe(), stdin = Pipe()
            process.executableURL = URL(fileURLWithPath: runtime.python)
            process.arguments = runtime.cliArguments + arguments
            process.currentDirectoryURL = URL(fileURLWithPath: runtime.project_root)
            process.standardOutput = output; process.standardError = errors
            process.standardInput = input == nil ? FileHandle.nullDevice : stdin
            var environment = ProcessInfo.processInfo.environment
            environment["PATH"] = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
            environment["PYTHONIOENCODING"] = "utf-8"; process.environment = environment
            do {
                try process.run()
                let deadline = DispatchWorkItem { if process.isRunning { process.terminate() } }
                DispatchQueue.global().asyncAfter(deadline: .now() + timeout, execute: deadline)
                // Drain both pipes independently: diagnostics must never corrupt JSON or fill stderr's pipe.
                let group = DispatchGroup()
                let errorBuffer = SettingsErrorBuffer()
                group.enter()
                DispatchQueue.global(qos: .utility).async {
                    errorBuffer.data = errors.fileHandleForReading.readDataToEndOfFile(); group.leave()
                }
                if let input { stdin.fileHandleForWriting.write(input); try? stdin.fileHandleForWriting.close() }
                let result = output.fileHandleForReading.readDataToEndOfFile()
                process.waitUntilExit(); group.wait(); deadline.cancel()
                if process.terminationStatus == 0 { DispatchQueue.main.async { completion(.success(result)) } }
                else {
                    let errorText = String(data: errorBuffer.data, encoding: .utf8) ?? ""
                    let text = errorText.isEmpty ? String(data: result, encoding: .utf8) ?? "" : errorText
                    let error = NSError(domain: "PadPilot", code: Int(process.terminationStatus), userInfo: [NSLocalizedDescriptionKey: text.isEmpty ? commandError : text])
                    DispatchQueue.main.async { completion(.failure(error)) }
                }
            } catch { DispatchQueue.main.async { completion(.failure(error)) } }
        }
    }
}

private final class SettingsErrorBuffer { var data = Data() }

final class SettingsWindowController: NSWindowController, NSWindowDelegate {
    private let model: SettingsModel
    private var settingsLock: Int32 = -1
    init(runtime: Runtime) {
        model = SettingsModel(runtime: runtime)
        let window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1000, height: 680),
                              styleMask: [.titled, .closable, .miniaturizable, .resizable], backing: .buffered, defer: false)
        window.contentMinSize = NSSize(width: 840, height: 500)
        window.isReleasedWhenClosed = false
        window.title = "PadPilot"
        super.init(window: window)
        model.window = window
        model.languageDidChange = { [weak self] in self?.updateMainMenu() }
        window.delegate = self
        window.contentView = NSHostingView(rootView: SettingsRootView(model: model))
        window.center()
        window.setFrameAutosaveName("PadPilotSettings")
    }
    required init?(coder: NSCoder) { nil }
    func show(page: String = "paired", delete: String? = nil, select: String? = nil) {
        guard let window else { return }
        if !model.fixtureMode && settingsLock < 0 {
            do { try lockSettings() }
            catch {
                let alert = NSAlert(); alert.messageText = "PadPilot"; alert.informativeText = error.localizedDescription; alert.runModal()
                return
            }
        }
        let requestedPage = (window.isVisible || window.isMiniaturized) && page == "paired" && delete == nil && select == nil ? model.page ?? page : page
        model.begin(page: requestedPage, delete: delete, select: select)
        updateMainMenu()
        if !model.fixtureMode { NSApp.setActivationPolicy(.regular) }
        if window.isMiniaturized { window.deminiaturize(nil) }
        showWindow(nil)
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }
    func windowWillClose(_ notification: Notification) {
        model.stop()
        if settingsLock >= 0 { Darwin.close(settingsLock); settingsLock = -1 }
        if !model.fixtureMode { NSApp.setActivationPolicy(.accessory) }
    }
    func windowDidBecomeKey(_ notification: Notification) { model.refresh() }
    private func updateMainMenu() {
        let menu = NSMenu()
        let appItem = NSMenuItem(title: "PadPilot", action: nil, keyEquivalent: "")
        let appMenu = NSMenu(title: "PadPilot")
        let about = NSMenuItem(title: model.tr("關於") + " PadPilot", action: #selector(showAbout), keyEquivalent: "")
        about.target = self; appMenu.addItem(about); appItem.submenu = appMenu; menu.addItem(appItem)
        let editItem = NSMenuItem(title: model.tr("編輯"), action: nil, keyEquivalent: "")
        let edit = NSMenu(title: model.tr("編輯"))
        for (title, selector, key) in [("剪下", #selector(NSText.cut(_:)), "x"), ("複製", #selector(NSText.copy(_:)), "c"), ("貼上", #selector(NSText.paste(_:)), "v"), ("全選", #selector(NSText.selectAll(_:)), "a")] {
            edit.addItem(NSMenuItem(title: model.tr(title), action: selector, keyEquivalent: key))
        }
        editItem.submenu = edit; menu.addItem(editItem)
        let windowItem = NSMenuItem(title: model.tr("視窗"), action: nil, keyEquivalent: "")
        let windows = NSMenu(title: model.tr("視窗"))
        windows.addItem(NSMenuItem(title: model.tr("關閉視窗"), action: #selector(NSWindow.performClose(_:)), keyEquivalent: "w"))
        windows.addItem(NSMenuItem(title: model.tr("最小化"), action: #selector(NSWindow.performMiniaturize(_:)), keyEquivalent: "m"))
        windowItem.submenu = windows; menu.addItem(windowItem)
        NSApp.mainMenu = menu; NSApp.windowsMenu = windows
    }
    @objc private func showAbout() { model.page = "about" }
    private func lockSettings() throws {
        let directory = padpilotHomeDirectory().appendingPathComponent("Library/Application Support/PadPilot/runtime")
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700])
        let attributes = try FileManager.default.attributesOfItem(atPath: directory.path)
        guard attributes[.type] as? FileAttributeType == .typeDirectory,
              (attributes[.ownerAccountID] as? NSNumber)?.uint32Value == getuid() else {
            throw NSError(domain: "PadPilot", code: 3, userInfo: [NSLocalizedDescriptionKey: model.tr("設定視窗執行目錄無法安全使用，請重新安裝 PadPilot。")])
        }
        let fd = Darwin.open(directory.appendingPathComponent("settings-window.lock").path, O_CREAT | O_RDWR | O_CLOEXEC | O_NOFOLLOW, 0o600)
        guard fd >= 0 else { throw NSError(domain: NSPOSIXErrorDomain, code: Int(errno)) }
        var info = stat()
        guard fstat(fd, &info) == 0, info.st_uid == getuid(), info.st_nlink == 1,
              (info.st_mode & S_IFMT) == S_IFREG, fchmod(fd, 0o600) == 0,
              flock(fd, LOCK_EX | LOCK_NB) == 0 else {
            Darwin.close(fd)
            throw NSError(domain: "PadPilot", code: 3, userInfo: [NSLocalizedDescriptionKey: model.tr("設定視窗已開啟或正在更新，請稍後重試。")])
        }
        settingsLock = fd
    }
    // The regression executable renders this same controller with recorded CLI calls.
    // Fixtures never access the daemon, hardware, or the user's installation lock.
    #if PADPILOT_GUI_CHECKS
    func loadFixture(_ fixture: [String: Any], page: String = "paired") {
        model.fixtureMode = true; model.stop(); model.data = [:]
        model.applySnapshot(fixture)
        model.begin(page: page, delete: nil, select: nil)
    }
    func checkApplyFixture(_ fixture: [String: Any]) { model.applySnapshot(fixture) }
    func checkEdit(_ key: String, value: String) { model.binding(key, fallback: "").wrappedValue = value }
    func checkAction(_ operation: String, payload: [String: Any]) { model.change(operation, payload) }
    func checkConfirm(_ answer: Bool) { model.confirmationAnswer = answer }
    func checkRealConfirm() { model.confirmationAnswer = nil }
    func checkStop() { model.stop() }
    func checkPoll() { model.poll() }
    func checkFailure(_ message: String) { model.injectedFailure = message }
    func checkLogFilter(_ key: String) -> String { model.logFilter = key; return model.filteredLogs }
    func checkRefresh(_ section: String) { model.refresh(section: section) }
    func checkProfileAction(_ action: String, key: String) {
        guard let entry = model.profiles.first(where: { $0.text("key") == key }) else { return }
        switch action {
        case "delete": model.delete(entry)
        case "select": model.select(entry)
        case "name": model.saveName(entry, key: "name.\(model.profile(entry).text("sidecar_uuid"))")
        case "usb": model.saveUSB(entry, key: "usb.\(model.profile(entry).text("sidecar_uuid"))")
        default: model.control(entry, action: action)
        }
    }
    func checkSnapshot() -> [String: Any] {
        ["page": model.page ?? "paired", "readonly": model.readonly, "busy": model.busy, "active": model.visible, "logs_auto_update": model.logsAutoUpdate,
         "visible": window?.isVisible ?? false, "minimized": window?.isMiniaturized ?? false,
         "window_number": window?.windowNumber ?? -1, "minimum_size": [window?.minSize.width ?? 0, window?.minSize.height ?? 0],
         "config_revision": model.revision, "language": model.language, "drafts": model.drafts, "draft_revisions": model.draftRevisions,
         "notice": model.notice, "actual": model.actual, "logText": model.logText,
         "donations": ["PayPal": model.donationEnabled("PayPal"), "Ko-fi": model.donationEnabled("Ko-fi")],
         "version": model.data.text("version"), "license": "PolyForm Noncommercial 1.0.0 · © 2026 kcayut",
         "commands": model.recordedCommands, "pages": settingsPages.map { $0.0 },
         "strings": model.data["strings"] ?? [:], "profiles": model.profiles]
    }
    #endif
}

private struct SettingsCard<Content: View>: View {
    var title: String
    @ViewBuilder var content: Content
    var body: some View {
        if title.isEmpty { GroupBox { cardContent } }
        else { GroupBox { cardContent } label: { Text(title).font(settingsFont(.headline)) } }
    }
    private var cardContent: some View {
        VStack(alignment: .leading, spacing: 12) { content }.frame(maxWidth: .infinity, alignment: .leading).padding(8)
    }
}

private struct SettingsDisclosureStyle: DisclosureGroupStyle {
    func makeBody(configuration: Configuration) -> some View {
        VStack(alignment: .leading, spacing: 0) {
            Button { configuration.isExpanded.toggle() } label: {
                HStack {
                    Image(systemName: configuration.isExpanded ? "chevron.down" : "chevron.right")
                        .accessibilityHidden(true)
                    configuration.label
                }.frame(minWidth: 72, minHeight: 24).contentShape(Rectangle())
            }.buttonStyle(.bordered).controlSize(.large)
            if configuration.isExpanded { configuration.content }
        }
    }
}

private struct SettingsRootView: View {
    @ObservedObject var model: SettingsModel
    var body: some View {
        HStack(spacing: 0) {
            VStack(spacing: 12) {
                List(selection: $model.page) {
                    ForEach(settingsPages, id: \.0) { page in
                        Label(model.tr(page.1), systemImage: page.2).tag(page.0)
                    }
                }.listStyle(.sidebar)
                VStack(alignment: .leading, spacing: 8) {
                    Text(model.tr(model.data.text("consistency_state") == "APPLYING_CONFIG" ? "模式：{0} (套用中…)" : "模式：{0}", model.modeTitle))
                    Text(model.tr("主力：{0}", model.targetName)).lineLimit(2)
                    Button(model.tr("🔄 重新整理狀態")) { model.refresh(scan: true) }.disabled(model.busy)
                    Button(model.tr("📖 使用說明")) { model.openLink("help") }.buttonStyle(.link).font(.body)
                    Button(model.tr("🩺 疑難排解")) { model.openLink("troubleshooting") }.buttonStyle(.link).font(.body)
                }.font(.caption).frame(maxWidth: .infinity, alignment: .leading).padding(14)
            }.frame(width: 200).background(.regularMaterial)
            Divider()
            GeometryReader { geometry in
            VStack(spacing: 0) {
                HStack(alignment: .center) {
                    Text(model.title).font(settingsFont(.title2).bold())
                    Spacer()
                    Picker("Language", selection: Binding(get: { model.language }, set: { model.change("set_language", ["language": $0]) })) {
                        Text("繁體中文").tag("zh-Hant"); Text("English").tag("en"); Text("日本語").tag("ja")
                    }.labelsHidden().frame(width: 130).disabled(model.disabled).accessibilityLabel("Language")
                }.padding(20)
                Divider()
                ScrollView {
                    VStack(alignment: .leading, spacing: 16) {
                        if !model.data.text("config_error").isEmpty {
                            Label(model.data.text("config_error"), systemImage: "exclamationmark.triangle.fill").foregroundStyle(.orange)
                        }
                        switch model.page {
                        case "search": SettingsSearchView(model: model)
                        case "settings": SettingsPreferencesView(model: model)
                        case "displays": SettingsDisplaysView(model: model)
                        case "virtual": SettingsVirtualView(model: model)
                        case "diagnostics": SettingsDiagnosticsView(model: model)
                        case "about": SettingsAboutView(model: model)
                        default: SettingsPairedView(model: model)
                        }
                    }.frame(maxWidth: .infinity, alignment: .leading).padding(20)
                }
                Divider()
                HStack {
                    Text(model.notice).font(settingsFont(.caption1)).foregroundStyle(.secondary).lineLimit(3).textSelection(.enabled)
                    Spacer()
                    if model.busy { ProgressView().controlSize(.small) }
                }.padding(12).frame(minHeight: 38)
            }.font(settingsFont(.body)).frame(width: geometry.size.width, height: geometry.size.height)
            }
        }.frame(minWidth: 840, minHeight: 500)
            .disclosureGroupStyle(SettingsDisclosureStyle())
            .pickerStyle(.menu)
            .menuStyle(.borderedButton)
    }
}

private struct SettingsPairedView: View {
    @ObservedObject var model: SettingsModel
    var body: some View {
        if model.config.flag("auto_detect_ipad") && model.config.object("ipad").text("sidecar_uuid").isEmpty {
            Text(model.tr("自動偵測已啟用；目前目標及控制請見選單列「iPad 控制」。已存配對保留不變。")).foregroundStyle(.secondary)
        }
        if model.profiles.isEmpty {
            SettingsCard(title: model.tr("尚未配對任何 iPad")) {
                Text(model.tr("請前往「搜尋新裝置」尋找身旁的 iPad 並完成配對設定。"))
                Button(model.tr("前往搜尋新裝置")) { model.page = "search" }.disabled(model.readonly)
            }
        }
        ForEach(Array(model.profiles.enumerated()), id: \.element.textKey) { _, entry in
            SettingsProfileCard(model: model, entry: entry)
        }
    }
}
private extension Dictionary where Key == String, Value == Any {
    var textKey: String { text("key", text("uuid", text("name"))) }
    var serialKey: String { text("serial") }
}

private struct SettingsProfileCard: View {
    @ObservedObject var model: SettingsModel
    let entry: SettingsObject
    @SettingsState private var expanded = false
    var ipad: SettingsObject { model.profile(entry) }
    var nameKey: String { "name.\(ipad.text("sidecar_uuid", entry.text("key")))" }
    var usbKey: String { "usb.\(ipad.text("sidecar_uuid", entry.text("key")))" }
    var body: some View {
        SettingsCard(title: "") {
            HStack {
                Label(ipad.text("name", model.tr("未命名 iPad")), systemImage: "ipad").font(settingsFont(.headline))
                Spacer()
                Text(model.tr(entry.text("status", "狀態未知"))).font(settingsFont(.caption1)).foregroundStyle(.secondary)
                Button(model.tr("刪除配對"), role: .destructive) { model.delete(entry) }.disabled(model.disabled)
            }
            if model.isTarget(entry) { Label(model.tr("★ 主要管理 iPad (自動接管)"), systemImage: "checkmark.circle.fill").font(settingsFont(.caption1)).foregroundStyle(.blue) }
            HStack {
                ForEach([("作為副螢幕", "use_ipad_secondary"), ("設為主螢幕", "use_ipad_main"), ("中斷連線", "disconnect_ipad"), ("重新連線", "reconnect_sidecar")], id: \.1) { title, action in
                    Button(model.tr(title)) { model.control(entry, action: action) }
                }
            }.disabled(model.disabled || !entry.flag("can_control"))
            if !model.isTarget(entry) { Text(model.tr("請先在「設定」中設為主要管理 iPad。")).font(settingsFont(.caption1)).foregroundStyle(.secondary) }
            Text("Sidecar UUID: \(ipad.text("sidecar_uuid", model.tr("未設定")))").font(settingsFont(.caption1, monospaced: true)).textSelection(.enabled)
            Text(model.tr("USB 序號:      {0}{1}", ipad.text("usb_serial", model.tr("未設定")), model.usbs.contains { $0.text("serial") == ipad.text("usb_serial") } ? model.tr(" (目前已接上 USB)") : "")).font(settingsFont(.caption1, monospaced: true)).textSelection(.enabled)
            DisclosureGroup(model.tr("設定"), isExpanded: $expanded) {
                VStack(alignment: .leading, spacing: 12) {
                    HStack {
                        TextField(model.tr("自訂名稱："), text: model.binding(nameKey, fallback: ipad.text("name")))
                        Button(model.tr("更新名稱")) { model.saveName(entry, key: nameKey) }
                    }
                    HStack {
                        SettingsUSBPicker(model: model, selection: model.binding(usbKey, fallback: ipad.text("usb_serial")), existing: ipad.text("usb_serial"))
                        Button(model.tr("更新 USB 設定")) { model.saveUSB(entry, key: usbKey) }
                    }
                    if !model.isTarget(entry) { Button(model.tr("設為主要管理 iPad")) { model.select(entry) } }
                    else { Text(model.tr("✓ 目前已是主要管理 iPad（無實體外接螢幕時自動連線接管）")).font(settingsFont(.caption1)).foregroundStyle(.blue) }
                }.padding(.top, 10).disabled(model.disabled)
            }
        }
    }
}

private struct SettingsUSBPicker: View {
    @ObservedObject var model: SettingsModel
    @Binding var selection: String
    var existing = ""
    var body: some View {
        Picker(model.tr("對應 USB："), selection: $selection) {
            Text(model.tr("略過 / 未綁定 USB")).tag("")
            if !existing.isEmpty && !model.usbs.contains(where: { $0.text("serial") == existing }) { Text(existing).tag(existing) }
            ForEach(model.usbs, id: \.serialKey) { usb in
                Text("\(usb.text("product_name", usb.text("name"))) · \(usb.text("serial"))").tag(usb.text("serial"))
            }
        }
    }
}

private struct SettingsSearchView: View {
    @ObservedObject var model: SettingsModel
    var body: some View {
        SettingsCard(title: model.tr("💡 搜尋與配對須知")) {
            Text(model.tr("請確認 Mac 與 iPad 登入相同 Apple Account，且藍牙與 Wi-Fi 已開啟；建議以 USB-C 直連確保無頭開機時自動接管。")).foregroundStyle(.secondary)
            Button(model.tr("🔍 搜尋可配對裝置")) { model.refresh(scan: true) }.disabled(model.disabled)
        }
        Text(model.tr("可配對裝置 ({0} 台)", String(model.candidates.count))).font(settingsFont(.headline))
        if !model.usbs.isEmpty {
            SettingsCard(title: "USB") {
                ForEach(model.usbs, id: \.serialKey) { usb in
                    Text("\(usb.text("product_name", usb.text("name"))) · \(usb.text("serial"))")
                        .font(settingsFont(.caption1, monospaced: true)).textSelection(.enabled)
                }
            }
        }
        if model.candidates.isEmpty {
            SettingsCard(title: model.tr("目前未偵測到 Sidecar 候選設備")) {
                Text(model.tr("若 iPad 已在身旁，請解鎖螢幕或在 macOS「控制中心 > 螢幕鏡像輸出」中確認是否能看到該 iPad。"))
            }
        }
        ForEach(model.candidates, id: \.textKey) { SettingsCandidateCard(model: model, candidate: $0) }
    }
}
private struct SettingsCandidateCard: View {
    @ObservedObject var model: SettingsModel
    let candidate: SettingsObject
    @SettingsState private var activate = false
    var uuid: String { candidate.text("uuid") }
    var pairedProfile: SettingsObject? { model.profiles.first { model.profile($0).text("sidecar_uuid").uppercased() == uuid.uppercased() } }
    var paired: Bool { pairedProfile != nil }
    var body: some View {
        SettingsCard(title: "") {
            HStack {
                Text(candidate.text("name", model.tr("未命名裝置"))).font(settingsFont(.headline))
                Spacer()
                if !paired {
                    Button(model.tr("配對")) { model.saveCandidate(candidate, activate: activate) }
                        .buttonStyle(.borderedProminent).disabled(model.disabled)
                }
            }
            Text("Sidecar UUID: \(uuid)").font(settingsFont(.caption1, monospaced: true)).textSelection(.enabled)
            Label(model.tr(paired ? "已在此 Mac 配對" : "新發現裝置"), systemImage: paired ? "checkmark.circle.fill" : "sparkle").font(settingsFont(.caption1)).foregroundStyle(.blue)
            Text(model.tr("目前關聯 USB:  {0}", pairedProfile.map { model.profile($0).text("usb_serial", model.tr("未綁定")) } ?? model.tr("未綁定")))
                .font(settingsFont(.caption1, monospaced: true)).textSelection(.enabled)
            if paired {
                Text(model.tr("✓ 此裝置已完成配對。若需自訂名稱、對應 USB 或設為主力 iPad，請至「已配對 iPad」分頁設定。"))
                Button(model.tr("前往「已配對 iPad」設定 →")) { model.page = "paired" }
            } else {
                TextField(model.tr("自訂名稱："), text: model.binding("candidate.\(uuid)", fallback: candidate.text("name"))).disabled(model.disabled)
                SettingsUSBPicker(model: model, selection: model.binding("candidateUSB.\(uuid)", fallback: "")).disabled(model.disabled)
                Toggle(model.tr("設為主要管理 iPad（無螢幕時自動接管）"), isOn: $activate).disabled(model.disabled)
            }
        }
    }
}

private struct SettingsHotKeyRecorder: NSViewRepresentable {
    @ObservedObject var model: SettingsModel
    let shortcut: String
    func makeNSView(context: Context) -> HotKeyRecorderButton { HotKeyRecorderButton(frame: .zero) }
    func updateNSView(_ button: HotKeyRecorderButton, context: Context) {
        button.idleTitle = shortcut.isEmpty ? model.tr("點選設定快速鍵") : ConnectionHotKey.label(shortcut)
        button.waitingTitle = model.tr("請按下快速鍵…（Esc 取消）")
        button.invalidTitle = model.tr("請搭配 Control 或 Command")
        button.isEnabled = !model.disabled
        if !button.recording { button.title = button.idleTitle }
        button.setAccessibilityHelp(model.tr("點選按鍵欄，按下組合後儲存；Esc 或切換視窗可取消。錄製期間暫停全域快速鍵。"))
        button.onBegin = {
            if model.drafts["connection_hotkey"] == nil { model.draftRevisions["connection_hotkey"] = model.revision }
        }
        button.onCapture = { value in
            model.drafts["connection_hotkey"] = value
        }
    }
}

private struct SettingsConnectionHotKey: View {
    @ObservedObject var model: SettingsModel
    @ObservedObject private var hotkey = ConnectionHotKey.shared
    private var shortcut: String {
        model.drafts["connection_hotkey"] ?? model.config.text("connection_hotkey")
    }
    var body: some View {
        SettingsCard(title: model.tr("全域快速鍵")) {
            Text(model.tr("按一次發起一輪連線；自動模式保留自動連線，手動模式不會在斷線後自行重連。"))
                .font(settingsFont(.callout)).foregroundStyle(.secondary)
            Text(model.tr("Mac 必須已登入並解鎖，才能使用全域快速鍵；鎖定畫面時無法使用。"))
                .font(settingsFont(.callout)).foregroundStyle(.orange)
            SettingsHotKeyRecorder(model: model, shortcut: shortcut)
                .frame(width: 250, height: 32)
            Text(model.tr("點選按鍵欄，按下組合後儲存；Esc 或切換視窗可取消。錄製期間暫停全域快速鍵。"))
                .font(settingsFont(.callout)).foregroundStyle(.secondary)
            HStack {
                Button(model.tr("儲存快速鍵")) {
                    model.change("set_connection_hotkey", ["shortcut": shortcut], draftKey: "connection_hotkey")
                }.disabled(model.disabled || ConnectionHotKey.parse(shortcut) == nil)
                Button(model.tr("停用快速鍵")) {
                    model.change("set_connection_hotkey", ["shortcut": ""], draftKey: "connection_hotkey")
                }.disabled(model.disabled || model.config.text("connection_hotkey").isEmpty)
            }
            Text(model.tr("至少選擇 Control 或 Command。使用連到 Mac 的鍵盤；沒有實體螢幕時連為主螢幕，有實體螢幕時連為副螢幕。"))
                .font(settingsFont(.callout)).foregroundStyle(.secondary)
            if model.config.text("connection_hotkey").isEmpty {
                Text(model.tr("快速鍵尚未啟用，儲存後生效。"))
            } else if hotkey.configuration == model.config.text("connection_hotkey") && hotkey.errorCode != 0 {
                Text(model.tr("無法啟用快速鍵，請改用其他組合。")).foregroundStyle(.orange)
            } else {
                Text(model.tr("已儲存：{0}", ConnectionHotKey.label(model.config.text("connection_hotkey"))))
            }
        }
    }
}

private struct SettingsPreferencesView: View {
    @ObservedObject var model: SettingsModel
    @SettingsState private var advanced = false
    @SettingsState private var pathEditor = false
    var body: some View {
        SettingsCard(title: model.tr("⚙️ 運作模式 (Operation Mode)")) {
            ForEach(settingsModes, id: \.0) { mode in
                VStack(alignment: .leading, spacing: 6) {
                    HStack {
                        Text(model.tr(mode.1)).font(settingsFont(.headline))
                        Spacer()
                        if model.config.text("mode") == mode.0 { Label(model.tr("✓ 目前生效中"), systemImage: "checkmark.circle.fill").foregroundStyle(.blue) }
                        else {
                            Button(model.tr("切換為此模式")) {
                                model.confirm(model.tr("切換至{0}?", model.tr(mode.1)), model.tr(mode.2)) { model.change("set_mode", ["mode": mode.0]) }
                            }.disabled(model.disabled)
                        }
                    }
                    Text(model.tr(mode.2)).font(settingsFont(.callout)).foregroundStyle(.secondary)
                    if mode.0 == "manual_only" {
                        Toggle(model.tr("開機無螢幕時自動連線 iPad"), isOn: Binding(
                            get: { model.config.flag("connect_on_boot") },
                            set: { model.change("set_connect_on_boot", ["enabled": $0]) }
                        )).disabled(model.disabled)
                        Text(model.tr("登入後最多偵測 3 輪，每輪 30 秒；找到目標就嘗試連線，三輪都找不到便停止。同次開機不重複，須啟用登入自動啟動。"))
                            .font(settingsFont(.callout)).foregroundStyle(.secondary)
                    } else if mode.0 == "automatic" {
                        Text(model.tr("目前技術無法事先確認 iPad 是否能成功連線 Sidecar；iPad 無法連線時，自動嘗試可能頻繁觸發 macOS 的警告視窗。"))
                            .font(settingsFont(.callout)).foregroundStyle(.orange)
                    }
                }.padding(10).frame(maxWidth: .infinity, alignment: .leading)
                    .background(model.config.text("mode") == mode.0 ? Color.accentColor.opacity(0.07) : Color.clear, in: RoundedRectangle(cornerRadius: 8))
            }
        }
        SettingsConnectionHotKey(model: model)
        SettingsCard(title: model.tr("🚀 登入時自動啟動 PadPilot：")) {
            Toggle(model.tr("（隨 macOS 登入背景自動執行）"), isOn: Binding(get: { model.data.text("login_service_status") == "enabled" }, set: { enabled in
                model.confirm(model.tr("確定{0}登入時自動啟動?", model.tr(enabled ? "啟用" : "停用")), model.tr(enabled ? "登入 macOS 時自動執行 PadPilot。" : "登入 macOS 時不自動執行 PadPilot。")) {
                    model.change("set_autostart", ["enabled": enabled])
                }
            })).disabled(model.disabled || model.data.text("login_service_status") == "unknown")
            if model.data.text("login_service_status") == "requiresApproval" {
                Text(model.tr("請到系統設定 → 一般 → 登入項目允許 PadPilot 背景執行"))
                    .font(settingsFont(.callout)).foregroundStyle(.secondary)
                Button(model.tr("開啟系統登入項目")) { SMAppService.openSystemSettingsLoginItems() }
                Button(model.tr("停用登入啟動")) { model.change("set_autostart", ["enabled": false]) }
                    .disabled(model.disabled)
            }
        }
        SettingsCard(title: "") {
            DisclosureGroup(model.tr("進階選項"), isExpanded: $advanced) {
                VStack(alignment: .leading, spacing: 16) {
                    detection
                    Divider()
                    protection
                    Divider()
                    integration
                }.padding(.top, 12)
            }
        }.sheet(isPresented: $pathEditor) { SettingsPathEditor(model: model, presented: $pathEditor) }
    }
    private var detection: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text(model.tr("USB 與 iPad 自動偵測")).font(settingsFont(.headline))
            ForEach([
                ("usb_event_wakeup", "USB 插拔即時喚醒", "收到原生 USB 事件即重新評估；保留防抖與 30 秒 Watchdog，非保證瞬間連線。"),
                ("auto_detect_ipad", "自動偵測 iPad（免 PadPilot 配對）", "優先沿用指定配對，支援無線 Sidecar；未指定有效配對時，才以唯一 USB iPad 與 Sidecar 候選推定。")
            ], id: \.0) { field, title, detail in
                Toggle(model.tr(title), isOn: Binding(get: { model.config.flag(field) }, set: { model.change("set_" + field, ["enabled": $0]) })).disabled(model.disabled)
                Text(model.tr(detail)).font(settingsFont(.caption1)).foregroundStyle(.secondary)
            }
            if model.config.flag("auto_detect_ipad") {
                Text(model.actual.object("resolved_ipad").text("name").isEmpty || !model.data.flag("fresh") ? model.tr("本次偵測目標：尚無唯一目標或狀態待更新") : model.tr("本次偵測目標：") + model.actual.object("resolved_ipad").text("name"))
            }
            Text(model.tr("免配對不會略過 Apple Sidecar 的帳號、信任與相容性要求；唯一候選仍是推定。")).font(settingsFont(.caption1)).foregroundStyle(.secondary)
        }
    }
    private var protection: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text(model.tr("🛡️ 防護機制與保護參數")).font(settingsFont(.headline))
            ForEach([
                ("debounce_seconds", "瞬斷防抖等待 (Debounce)", "實體螢幕拔插瞬斷時的緩衝計時，未滿前不觸發切換"),
                ("max_retries", "最大重試次數 (Max Retries)", "Sidecar 連線異常時的自動重試上限"),
                ("retry_interval", "重試間隔 (Retry Interval)", "每次重試之間的等待秒數"),
                ("cooldown_seconds", "冷卻保護時間 (Cooldown)", "重試全數失敗後進入冷卻，防止連線風暴")
            ], id: \.0) { key, title, detail in
                HStack(alignment: .top) {
                    VStack(alignment: .leading, spacing: 3) { Text(model.tr(title)); Text(model.tr(detail)).font(settingsFont(.caption1)).foregroundStyle(.secondary) }
                    Spacer()
                    Text(key == "max_retries" ? model.tr("{0} 次", model.config.text(key)) : model.tr("{0} 秒", model.config.text(key))).monospacedDigit()
                }
            }
            LabeledContent(model.tr("排除佔位名稱 (Ignore List)"), value: (model.config["ignore_list"] as? [String] ?? []).joined(separator: ", "))
            Text(model.tr("忽略特定佔位螢幕名稱（如 Generic Display）")).font(settingsFont(.caption1)).foregroundStyle(.secondary)
        }
    }
    private var integration: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text(model.tr("📁 系統路徑與整合")).font(settingsFont(.headline))
            HStack {
                Text("BetterDisplay CLI").bold()
                Text(model.tr(model.config.text("betterdisplaycli_path").isEmpty ? "自動偵測" : "手動指定")).font(settingsFont(.caption1)).foregroundStyle(.secondary)
                Spacer(minLength: 8)
                Button(model.tr("手動設定")) { pathEditor = true }
                Button(model.tr("恢復預設")) {
                    model.confirm(model.tr("恢復預設 CLI 路徑?"), model.tr("將清除手動指定的路徑，改為由系統自動探測 BetterDisplay CLI。")) {
                        model.change("set_betterdisplaycli_path", ["path": NSNull()])
                    }
                }.disabled(model.config.text("betterdisplaycli_path").isEmpty)
            }.disabled(model.disabled)
            Text(model.paths.text("betterdisplaycli").isEmpty ? model.tr("未找到可用的 BetterDisplay CLI") : model.paths.text("betterdisplaycli"))
                .font(settingsFont(.callout, monospaced: true)).textSelection(.enabled)
            Text(model.tr("設定檔位置：")).bold()
            Text(model.paths.text("config")).font(settingsFont(.caption1, monospaced: true)).textSelection(.enabled)
        }
    }
}

private struct SettingsPathEditor: View {
    @ObservedObject var model: SettingsModel
    @Binding var presented: Bool
    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            Text(model.tr("手動設定 BetterDisplay CLI 路徑")).font(settingsFont(.headline))
            Text(model.tr("請輸入或選擇 betterdisplaycli 執行檔，或 BetterDisplay.app 應用程式路徑：")).foregroundStyle(.secondary)
            HStack {
                TextField("BetterDisplay CLI", text: model.binding("betterdisplaycli_path", fallback: model.config.text("betterdisplaycli_path", model.paths.text("betterdisplaycli"))))
                    .textFieldStyle(.roundedBorder)
                Button(model.tr("瀏覽…")) {
                    let panel = NSOpenPanel()
                    panel.title = model.tr("選擇 BetterDisplay CLI 或 App")
                    panel.canChooseDirectories = false; panel.canChooseFiles = true
                    panel.treatsFilePackagesAsDirectories = false; panel.allowsMultipleSelection = false
                    if panel.runModal() == .OK, let url = panel.url {
                        model.binding("betterdisplaycli_path", fallback: "").wrappedValue = url.path
                    }
                }
            }
            HStack {
                Spacer()
                Button(model.tr("取消")) { presented = false }.keyboardShortcut(.cancelAction)
                Button(model.tr("儲存")) {
                    let path = (model.drafts["betterdisplaycli_path"] ?? model.paths.text("betterdisplaycli")).trimmingCharacters(in: .whitespacesAndNewlines)
                    guard !path.isEmpty else { return }
                    presented = false
                    model.change("set_betterdisplaycli_path", ["path": path], draftKey: "betterdisplaycli_path")
                }.keyboardShortcut(.defaultAction).disabled((model.drafts["betterdisplaycli_path"] ?? model.paths.text("betterdisplaycli")).trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || model.disabled)
            }
        }.font(settingsFont(.body)).padding(24).frame(width: 570)
    }
}

private struct SettingsDisplaysView: View {
    @ObservedObject var model: SettingsModel
    var body: some View {
        if !model.data.flag("fresh") {
            SettingsCard(title: model.tr("⚠️ 螢幕資料待更新")) {
                Text(model.tr("上次偵測資料已超過 120 秒或尚未取得，請點擊左側「重新整理狀態」。"))
            }
        } else if model.actual.rows("online_displays").isEmpty {
            SettingsCard(title: model.tr("目前無任何上線顯示器")) { EmptyView() }
        } else {
            ForEach(Array(model.actual.rows("online_displays").enumerated()), id: \.offset) { _, display in
                SettingsCard(title: "") {
                    HStack(alignment: .top) {
                        Label(display.text("name", model.tr("未命名螢幕")), systemImage: display.flag("is_sidecar") ? "ipad" : "display").font(settingsFont(.headline))
                        Spacer()
                        Text(model.tr(display.flag("is_main") ? "主顯示器" : "延伸顯示器")).foregroundStyle(display.flag("is_main") ? .blue : .secondary)
                    }
                    HStack {
                        Text("\(display.text("width", "0")) × \(display.text("height", "0"))").monospacedDigit()
                        Spacer()
                        Text(display.flag("is_sidecar") ? "Sidecar" : model.tr(display.flag("is_virtual") ? "虛擬螢幕" : "實體螢幕")).foregroundStyle(.secondary)
                    }
                }
            }
        }
    }
}

private struct SettingsVirtualView: View {
    @ObservedObject var model: SettingsModel
    var selection: String { model.drafts["virtual"] ?? model.config.text("virtual_display_name", model.virtuals.first?.text("name") ?? "") }
    var body: some View {
        SettingsCard(title: model.tr("◻️ BetterDisplay 虛擬備援螢幕設定")) {
            Text(model.tr("當未接外接螢幕且 Sidecar 連線斷線時，虛擬螢幕將作為無頭備援 Framebuffer，供遠端救援存取。"))
            Button(model.tr("🔄 重新探測")) { model.refresh(scan: true) }.disabled(model.disabled)
            if !model.virtuals.isEmpty {
                HStack {
                    Picker(model.tr("選擇指定備援螢幕："), selection: model.binding("virtual", fallback: selection)) {
                        if !model.virtuals.contains(where: { $0.text("name") == selection }) { Text(selection).tag(selection) }
                        ForEach(model.virtuals, id: \.textKey) { display in Text(display.text("name")).tag(display.text("name")) }
                    }
                    Button(model.tr("指定為備援螢幕")) { model.setVirtual(selection) }
                }.disabled(model.disabled)
            }
        }
        if model.virtuals.isEmpty {
            SettingsCard(title: model.tr("未探測到任何 BetterDisplay 虛擬螢幕")) {
                Text(model.tr("請先在 BetterDisplay App 中建立至少一個虛擬顯示器（建議命名為 PadPilotVirtual）。"))
            }
        }
        ForEach(model.virtuals, id: \.textKey) { display in
            SettingsCard(title: display.text("name")) {
                HStack {
                    Text(model.tr((Int(display.text("displayID")) ?? 0) > 0 ? "已連接" : "未連接")).foregroundStyle(.secondary)
                    Spacer()
                    if display.text("name") == model.config.text("virtual_display_name") { Label(model.tr("✓ 目前指定備援"), systemImage: "checkmark.circle.fill").foregroundStyle(.blue) }
                    else { Button(model.tr("設為此備援")) { model.setVirtual(display.text("name")) }.disabled(model.disabled) }
                }
            }
        }
    }
}

private struct SettingsDiagnosticsView: View {
    @ObservedObject var model: SettingsModel
    @SettingsState private var logsExpanded = true
    var body: some View {
        decision
        checks("system_checks", title: "啟動與必要設定偵測")
        checks("authenticated_checks", title: "啟動與必要設定偵測 — 需要使用者帳號密碼")
        SettingsCard(title: "") {
            DisclosureGroup(model.tr("📜 系統運行日誌 (padpilot.log)"), isExpanded: $logsExpanded) {
                VStack(alignment: .leading, spacing: 10) {
                    HStack {
                        Picker(model.tr("篩選："), selection: $model.logFilter) {
                            Text(model.tr("全部")).tag("all"); Text(model.tr("僅 WARNING / ERROR")).tag("warning")
                            Text(model.tr("僅 ERROR")).tag("error"); Text(model.tr("僅 INFO")).tag("info")
                        }.frame(maxWidth: 220)
                        Spacer()
                        Button(model.tr("🔄 刷新日誌")) { model.refresh(section: "logs") }.disabled(model.busy)
                        Button(model.tr("外部開啟")) { model.openLog() }
                    }
                    HStack {
                        Toggle(model.tr("自動更新"), isOn: $model.logsAutoUpdate)
                        Spacer()
                        Button(model.tr("複製")) {
                            NSPasteboard.general.clearContents(); NSPasteboard.general.setString(model.filteredLogs, forType: .string)
                        }
                    }
                    SettingsLogView(text: model.filteredLogs.isEmpty ? model.tr("（查無符合篩選條件的日誌紀錄）\n") : model.filteredLogs)
                        .frame(height: 340)
                }.padding(.top, 10)
            }
        }
        .onAppear { model.refresh(section: "diagnostics") }
    }
    private var decision: some View {
        SettingsCard(title: model.tr("🩺 自動化決策與狀態機")) {
            let decision = model.data.object("decision")
            HStack {
                Text(model.tr("期望目標："))
                Text(decision.text("role", model.tr("未知")))
                Spacer()
                Button(model.tr("重新整理")) { model.refresh(section: "decision") }.disabled(model.busy)
            }
            LabeledContent(model.tr("實際狀態："), value: decision.text("satisfaction", model.tr("資料待更新")))
            LabeledContent(model.tr("狀態機轉換："), value: decision.text("transition", "IDLE"))
            if decision.flag("cooldown") { Label(model.tr("⚠️ 冷卻保護中"), systemImage: "exclamationmark.triangle.fill").foregroundStyle(.orange) }
            Text(model.tr("決策依據：") + decision.text("reason", model.tr("尚無背景決策資訊"))).textSelection(.enabled)
            if !decision.text("last_error").isEmpty && decision.text("last_error") != model.tr("無") {
                Text(model.tr("最近錯誤：") + decision.text("last_error")).foregroundStyle(.red).textSelection(.enabled)
            }
        }
    }
    private func checks(_ section: String, title: String) -> some View {
        SettingsCard(title: "") {
            HStack {
                Text(model.tr(title)).font(settingsFont(.headline))
                Spacer()
                Button(model.tr("重新整理")) { model.refresh(section: section) }.fixedSize().disabled(model.busy)
            }
            if section == "system_checks" {
                HStack {
                    Label(model.tr("通過"), systemImage: "circle.fill").foregroundStyle(.green)
                    Label(model.tr("不通過"), systemImage: "circle.fill").foregroundStyle(.red)
                    Label(model.tr("尚未檢查"), systemImage: "circle.fill").foregroundStyle(.orange)
                }.font(settingsFont(.caption1))
            }
            if section == "authenticated_checks" {
                Text(model.tr("查詢登入項目時，macOS 可能要求輸入管理員帳號與密碼。請在系統驗證視窗輸入；PadPilot 不會收集或儲存密碼。只有按此區重新整理才會查詢。")).font(settingsFont(.caption1)).foregroundStyle(.secondary)
            }
            if model.data.rows(section).isEmpty { Text(model.tr("尚未檢查")).foregroundStyle(.secondary) }
            ForEach(Array(model.data.rows(section).enumerated()), id: \.offset) { _, row in
                let localized = row.object("localizations").object(model.language)
                let label = localized.text("label", row.text("label"))
                let value = localized.text("value", row.text("value"))
                let helpURL = localized.text("help_url", row.text("help_url"))
                HStack(alignment: .top) {
                    Image(systemName: "circle.fill").font(settingsFont(.caption1)).foregroundStyle(row.text("state") == "pass" ? .green : (row.text("state") == "fail" ? .red : .orange))
                        .accessibilityLabel(model.tr(row.text("state") == "pass" ? "通過" : (row.text("state") == "fail" ? "不通過" : "尚未檢查")))
                    VStack(alignment: .leading, spacing: 4) {
                        Text(label + ": " + value).textSelection(.enabled)
                        if label == "FileVault" || label == model.tr("macOS 自動登入") {
                            Text(model.tr("用於開機自動連接螢幕；本檢查僅讀取狀態，不會修改設定或讀取密碼。")).font(settingsFont(.caption1)).foregroundStyle(.secondary)
                        }
                    }
                    Spacer(minLength: 8)
                    if row.text("state") == "fail", !helpURL.isEmpty {
                        Button(model.tr("說明 ↗")) { model.open(helpURL) }.buttonStyle(.link)
                    }
                }
            }
        }
    }
}

private struct SettingsLogView: NSViewRepresentable {
    let text: String
    func makeNSView(context: Context) -> NSScrollView {
        let scroll = NSScrollView(); scroll.hasVerticalScroller = true; scroll.autohidesScrollers = true
        scroll.borderType = .bezelBorder
        let view = NSTextView()
        view.isEditable = false; view.isSelectable = true; view.isRichText = false
        view.autoresizingMask = [.width]
        view.minSize = NSSize(width: 0, height: 0); view.maxSize = NSSize(width: CGFloat.greatestFiniteMagnitude, height: CGFloat.greatestFiniteMagnitude)
        view.isVerticallyResizable = true; view.isHorizontallyResizable = false
        view.textContainer?.widthTracksTextView = true
        view.textContainerInset = NSSize(width: 8, height: 8)
        view.backgroundColor = NSColor(calibratedWhite: 0.10, alpha: 1)
        view.setAccessibilityLabel("PadPilot logs")
        scroll.documentView = view
        return scroll
    }
    func updateNSView(_ scroll: NSScrollView, context: Context) {
        guard let view = scroll.documentView as? NSTextView, view.string != text else { return }
        let origin = scroll.contentView.bounds.origin
        let atBottom = scroll.documentVisibleRect.maxY >= view.bounds.maxY - 20
        let selection = view.selectedRange()
        let value = NSMutableAttributedString(string: text, attributes: [.font: NSFont.monospacedSystemFont(ofSize: 13, weight: .regular), .foregroundColor: NSColor.white])
        for match in settingsLogPattern.matches(in: text, range: NSRange(location: 0, length: value.length)) {
                value.addAttribute(.foregroundColor, value: NSColor.gray, range: match.range(at: 1))
                value.addAttribute(.foregroundColor, value: NSColor.systemCyan, range: match.range(at: 3))
                let level = (text as NSString).substring(with: match.range(at: 2))
                value.addAttribute(.foregroundColor, value: level == "ERROR" ? NSColor.systemRed : (level == "WARNING" ? NSColor.systemOrange : NSColor.systemGreen), range: match.range(at: 2))
        }
        view.textStorage?.setAttributedString(value)
        view.setSelectedRange(NSRange(location: min(selection.location, value.length), length: 0))
        if atBottom { view.scrollToEndOfDocument(nil) }
        else { scroll.contentView.scroll(to: origin); scroll.reflectScrolledClipView(scroll.contentView) }
    }
}

private struct SettingsAboutView: View {
    @ObservedObject var model: SettingsModel
    var body: some View {
        SettingsCard(title: "PadPilot") {
            Text("v" + model.data.text("version")).font(settingsFont(.title1))
            Text(model.tr("Mac 的 Sidecar 顯示器自動化工具"))
            Text("PolyForm Noncommercial 1.0.0 · © 2026 kcayut").font(settingsFont(.caption1)).foregroundStyle(.secondary)
            Button(model.tr("在 GitHub 查看專案")) { model.openLink("github") }
        }
        SettingsCard(title: model.tr("支持 PadPilot")) {
            Text(model.tr("贊助完全自願，不影響任何功能的使用。")).foregroundStyle(.secondary)
            HStack {
                ForEach(["PayPal", "Ko-fi"], id: \.self) { name in
                    Button(name) { model.open(model.data.object("donations").text(name)) }
                        .disabled(!model.donationEnabled(name))
                }
            }
            if model.data.object("donations").values.allSatisfy({ ($0 as? String ?? "").isEmpty }) {
                Text(model.tr("贊助連結準備中，感謝你的支持。")).font(settingsFont(.caption1)).foregroundStyle(.secondary)
            }
        }
    }
}
