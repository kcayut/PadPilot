import AppKit
import Foundation
import ApplicationServices

private typealias CheckObject = [String: Any]
private func require(_ condition: @autoclosure () -> Bool, _ message: String) throws {
    if !condition() { throw NSError(domain: "PadPilotGUIRegression", code: 1, userInfo: [NSLocalizedDescriptionKey: message]) }
}
@MainActor private func settle() async {
    try? await Task.sleep(nanoseconds: 120_000_000)
    NSApp.updateWindows()
}
private func views(_ view: NSView) -> [NSView] { [view] + view.subviews.flatMap(views) }

private struct CheckElement {
    let element: AXUIElement
    let label: String
    let identifier: String
    let role: String
    let enabled: Bool
    let checked: Bool?
    let frame: NSRect
    @MainActor func press() -> Bool { AXUIElementPerformAction(element, kAXPressAction as CFString) == .success }
}
@MainActor private func elements(_ root: NSView) -> [CheckElement] {
        func value(_ element: AXUIElement, _ key: String) -> CFTypeRef? {
            var value: CFTypeRef?
            return AXUIElementCopyAttributeValue(element, key as CFString, &value) == .success ? value : nil
        }
        var result: [CheckElement] = []
        var seen = Set<CFHashCode>()
        func visit(_ element: AXUIElement, depth: Int = 0) {
            guard depth < 30, seen.insert(CFHash(element)).inserted else { return }
            AXUIElementSetMessagingTimeout(element, 0.5)
            let role = value(element, kAXRoleAttribute) as? String ?? ""
            let label = value(element, kAXTitleAttribute) as? String ?? value(element, kAXValueAttribute) as? String ?? value(element, kAXDescriptionAttribute) as? String ?? ""
            var point = CGPoint.zero, size = CGSize.zero
            if let origin = value(element, kAXPositionAttribute), CFGetTypeID(origin) == AXValueGetTypeID() { AXValueGetValue(origin as! AXValue, .cgPoint, &point) }
            if let dimensions = value(element, kAXSizeAttribute), CFGetTypeID(dimensions) == AXValueGetTypeID() { AXValueGetValue(dimensions as! AXValue, .cgSize, &size) }
            result.append(CheckElement(element: element, label: label,
                                       identifier: value(element, kAXIdentifierAttribute) as? String ?? "", role: role,
                                       enabled: value(element, kAXEnabledAttribute) as? Bool ?? true,
                                       checked: (value(element, kAXValueAttribute) as? NSNumber)?.boolValue,
                                       frame: NSRect(origin: point, size: size)))
            for child in value(element, kAXChildrenAttribute) as? [AXUIElement] ?? [] { visit(child, depth: depth + 1) }
        }
        let application = AXUIElementCreateApplication(getpid())
        if let window = (value(application, kAXWindowsAttribute) as? [AXUIElement])?.first { visit(window) }
        return result
}
private func commands(_ controller: SettingsWindowController) -> [CheckObject] {
    controller.checkSnapshot()["commands"] as? [CheckObject] ?? []
}
private func mutations(_ controller: SettingsWindowController) -> [CheckObject] {
    commands(controller).filter { ($0["args"] as? [String])?.first != "gui-data" }
}
@MainActor func runSettingsChecks(runtime: Runtime, fixtures: [String: [String: Any]], mode: String, output: URL) async throws {
    let pages = ["paired", "search", "settings", "displays", "virtual", "diagnostics", "about"]
    let languages = mode == "languages" ? ["zh-Hant", "en", "ja"] : ["zh-Hant"]
    let controller = SettingsWindowController(runtime: runtime)
    guard let window = controller.window, let content = window.contentView else { throw NSError(domain: "PadPilotGUIRegression", code: 3) }
    defer { window.close() }
    var inspected = 0
    for language in languages {
        guard let fixture = fixtures[language] else { throw NSError(domain: "Missing GUI fixture", code: 4) }
        let strings = fixture["strings"] as? [String: String] ?? [:]
        for page in pages {
            FileHandle.standardError.write(Data("Checking \(language)/\(page)\n".utf8))
            let pageRequests = commands(controller).count
            controller.loadFixture(fixture, page: page)
            controller.show(page: page)
            window.setContentSize(NSSize(width: 840, height: 500))
            await settle(); content.layoutSubtreeIfNeeded()
            let state = controller.checkSnapshot()
            try require(state["page"] as? String == page, "Wrong native page: \(language)/\(page), got \(state["page"] ?? "nil")")
            try require(state["language"] as? String == language, "Language selection was lost")
            try require(state["pages"] as? [String] == pages, "The native window must expose all seven pages")
            try require(window.isVisible && !window.isMiniaturized, "Settings window is not visible")
            try require(window.title == "PadPilot", "Window title must be PadPilot")
            try require(!views(content).contains { $0 is NSSplitView }, "Sidebar must remain fixed")
            try require(abs(content.bounds.width - 840) < 2, "840px content width was not respected")
            try require(content.fittingSize.width <= content.bounds.width + 2, "Native content exceeds minimum width: \(page)")
            var nodes = elements(content)
            if page == "paired" || page == "settings" {
                let title = strings[page == "paired" ? "設定" : "進階選項"] ?? ""
                let disclosure = nodes.first { $0.label == title && ($0.role == "AXDisclosureTriangle" || $0.role == "AXButton") }
                guard let disclosure else { throw NSError(domain: "Missing native disclosure: \(page)", code: 8) }
                try require(disclosure.frame.height >= 26 && disclosure.frame.width >= 60,
                            "Disclosure needs a framed, easily clickable button: \(page)/\(disclosure.role)/\(disclosure.frame)")
                if page == "paired" { try require(!nodes.contains { $0.label.contains("▼") }, "Paired settings duplicated the native disclosure arrow in its title") }
                let pressed = disclosure.press(); try require(pressed, "Native disclosure failed: \(page)")
                await settle(); nodes = elements(content)
            }
            let expectedKey = ["paired": "作為副螢幕", "search": "💡 搜尋與配對須知", "settings": "🛡️ 防護機制與保護參數", "displays": "Display", "virtual": "指定為備援螢幕", "diagnostics": "🩺 自動化決策與狀態機", "about": "支持 PadPilot"][page]!
            let expectedText = strings[expectedKey] ?? expectedKey
            try require(nodes.contains { $0.label == expectedText }, "Missing native page content: \(language)/\(page)/\(expectedText)")
            if page == "search" {
                try require(nodes.contains { $0.role == "AXButton" && $0.label == strings["配對"] && $0.enabled }, "The unpaired candidate has no enabled native Pair button")
            }
            if page == "displays" {
                let displayIDs = ["AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA", "BBBBBBBB-BBBB-4BBB-8BBB-BBBBBBBBBBBB",
                                  "CCCCCCCC-CCCC-4CCC-8CCC-CCCCCCCCCCCC", "DDDDDDDD-DDDD-4DDD-8DDD-DDDDDDDDDDDD",
                                  "EEEEEEEE-EEEE-4EEE-8EEE-EEEEEEEEEEEE", "unidentified.5"]
                let checkboxes = nodes.filter { $0.role == "AXCheckBox" && $0.identifier.hasPrefix("display-exclusion.") }
                try require(checkboxes.count == displayIDs.count, "Each display needs an exclusion checkbox: \(language)")
                for (index, uuid) in displayIDs.enumerated() {
                    guard let checkbox = checkboxes.first(where: { $0.identifier == "display-exclusion.\(uuid)" }) else {
                        throw NSError(domain: "Missing display exclusion checkbox: \(uuid)", code: 27)
                    }
                    try require(checkbox.label == strings["排除實體螢幕判斷"], "Display exclusion label was not localized: \(language)")
                    try require(checkbox.enabled == (index < 3) && checkbox.checked == (1...4).contains(index),
                                "Display exclusion state or protected role is incorrect: \(uuid)")
                    if index < 3 {
                        try require(nodes.contains { $0.label == "UUID \(uuid.prefix(8))" }, "Missing UUID to distinguish displays with the same name")
                    }
                }
                for key in ["只調整 PadPilot 的實體螢幕判斷，不會停用這個螢幕。", "Sidecar 與虛擬螢幕保留原用途，不計入實體螢幕判斷。", "無法取得螢幕識別碼，暫時不能調整。"] {
                    try require(nodes.contains { $0.label == strings[key] }, "Missing display exclusion explanation: \(language)/\(key)")
                }
                for (uuid, excluded) in [(displayIDs[0], true), (displayIDs[1], false)] {
                    guard let checkbox = elements(content).first(where: { $0.identifier == "display-exclusion.\(uuid)" && $0.role == "AXCheckBox" }) else {
                        throw NSError(domain: "Missing actionable display exclusion checkbox", code: 28)
                    }
                    let before = mutations(controller).count
                    try require(checkbox.press(), "Display exclusion checkbox could not be clicked")
                    await settle()
                    let command = mutations(controller).last ?? [:], payload = command["payload"] as? CheckObject ?? [:]
                    try require(mutations(controller).count == before + 1 && command["args"] as? [String] == ["change-settings", "set_display_exclusion"],
                                "Display exclusion bypassed the shared transaction")
                    try require(payload["uuid"] as? String == uuid && payload["excluded"] as? Bool == excluded && payload["__expected_revision__"] as? Int == 7,
                                "Display exclusion lost its precise UUID, value or revision")
                }
                guard let reset = elements(content).first(where: { $0.identifier == "display-exclusion-reset.\(displayIDs[2])" && $0.role == "AXButton" }) else {
                    throw NSError(domain: "Missing automatic display detection reset", code: 29)
                }
                try require(reset.label == strings["恢復自動判斷"] && reset.enabled && reset.press(), "Automatic detection reset is not localized or actionable")
                await settle()
                let resetCommand = mutations(controller).last ?? [:], resetPayload = resetCommand["payload"] as? CheckObject ?? [:]
                try require(resetCommand["args"] as? [String] == ["change-settings", "set_display_exclusion"]
                            && resetPayload["uuid"] as? String == displayIDs[2] && resetPayload["excluded"] is NSNull
                            && resetPayload["__expected_revision__"] as? Int == 7, "Automatic detection reset did not remove the precise override")
                var readonly = fixture; readonly["config_error"] = "Unreadable original config"
                controller.loadFixture(readonly, page: "displays"); await settle()
                try require(elements(content).filter { $0.identifier.hasPrefix("display-exclusion.") || $0.identifier.hasPrefix("display-exclusion-reset.") }.allSatisfy { !$0.enabled },
                            "Readonly settings allow display exclusion changes")
                controller.loadFixture(fixture, page: "displays"); await settle()
                nodes = elements(content)
            }
            if page == "settings" {
                try require(nodes.contains { $0.label == strings["全域快速鍵"] }, "Missing global shortcut settings")
                let headings = ["⚙️ 運作模式 (Operation Mode)", "🚀 登入時自動啟動 PadPilot：", "全域快速鍵"]
                    .compactMap { key in nodes.first { $0.label == (strings[key] ?? key) } }
                try require(headings.count == 3 && headings[0].frame.minY < headings[1].frame.minY
                            && headings[1].frame.minY < headings[2].frame.minY, "Login startup must immediately follow operation mode")
                for boot in [false, true] {
                    var startup = fixture
                    var startupConfig = startup["config"] as? CheckObject ?? [:]
                    startupConfig["autostart_on_login"] = !boot; startupConfig["connect_on_boot"] = !boot
                    startup["config"] = startupConfig; startup["login_service_status"] = boot ? "notRegistered" : "enabled"
                    controller.loadFixture(startup, page: "settings")
                    controller.checkRealConfirm(); await settle()
                    let label = strings[boot ? "開機無螢幕時自動連線 iPad" : "（隨 macOS 登入背景自動執行）"]
                    for accept in [false, true] {
                        guard let toggle = elements(content).first(where: { $0.label == label && $0.role == "AXCheckBox" }) else {
                            throw NSError(domain: "Missing startup toggle", code: 23)
                        }
                        let before = mutations(controller).count
                        try require(toggle.enabled && toggle.press(), "Startup toggle is not usable")
                        await settle()
                        guard let sheet = window.attachedSheet, let body = sheet.contentView else {
                            throw NSError(domain: "Missing linked startup confirmation", code: 24)
                        }
                        let detail = boot ? "啟用「開機無螢幕時自動連線 iPad」，也會一併啟用「登入時自動啟動 PadPilot」。是否繼續？"
                            : "停用登入時自動啟動，也會一併關閉「開機無螢幕時自動連線 iPad」。是否繼續？"
                        try require(views(body).compactMap { $0 as? NSTextField }.contains { $0.stringValue == (strings[detail] ?? detail) },
                                    "Confirmation does not explain both linked options")
                        guard let answer = views(body).compactMap({ $0 as? NSButton }).first(where: { $0.title == strings[accept ? "是" : "否"] }) else {
                            throw NSError(domain: "Missing confirmation answer", code: 25)
                        }
                        answer.performClick(nil); await settle()
                        try require(mutations(controller).count == before + (accept ? 1 : 0), "Startup confirmation submitted the wrong number of writes")
                        if accept {
                            let command = mutations(controller).last ?? [:]
                            let expected = boot ? ["change-settings", "set_connect_on_boot"] : ["autostart", "disable", "--expected-revision", "7"]
                            try require(command["args"] as? [String] == expected, "Linked startup bypassed the shared transaction")
                            if boot { try require((command["payload"] as? CheckObject)?["__expected_revision__"] as? Int == 7, "Boot confirmation lost its revision") }
                        }
                    }
                }
                // Independent changes must submit immediately, without a confirmation sheet.
                for (boot, loginEnabled, bootEnabled) in [(false, false, false), (false, false, true),
                                                           (false, true, false), (true, true, false), (true, true, true)] {
                    var startup = fixture
                    var startupConfig = startup["config"] as? CheckObject ?? [:]
                    startupConfig["autostart_on_login"] = loginEnabled; startupConfig["connect_on_boot"] = bootEnabled
                    startup["config"] = startupConfig; startup["login_service_status"] = loginEnabled ? "enabled" : "notRegistered"
                    controller.loadFixture(startup, page: "settings")
                    controller.checkRealConfirm(); await settle()
                    let label = strings[boot ? "開機無螢幕時自動連線 iPad" : "（隨 macOS 登入背景自動執行）"]
                    guard let toggle = elements(content).first(where: { $0.label == label && $0.role == "AXCheckBox" }) else {
                        throw NSError(domain: "Missing independent startup toggle", code: 26)
                    }
                    let before = mutations(controller).count
                    try require(toggle.enabled && toggle.press(), "Independent startup toggle is not usable")
                    await settle()
                    try require(window.attachedSheet == nil && mutations(controller).count == before + 1,
                                "An independent startup change requested confirmation instead of applying directly")
                }
                controller.loadFixture(fixture, page: "settings"); await settle()
                nodes = elements(content)
                guard let recorder = views(content).compactMap({ $0 as? HotKeyRecorderButton }).first else {
                    throw NSError(domain: "Missing shortcut recorder", code: 22)
                }
                recorder.beginRecording()
                let recordingRevision = controller.checkSnapshot()["config_revision"] as? Int ?? 0
                var newer = fixture
                var newerConfig = newer["config"] as? CheckObject ?? [:]
                newerConfig["revision"] = recordingRevision + 1; newer["config"] = newerConfig
                controller.checkApplyFixture(newer)
                let key = NSEvent.keyEvent(with: .keyDown, location: .zero, modifierFlags: [.control, .option, .command],
                                           timestamp: 0, windowNumber: window.windowNumber, context: nil, characters: "i",
                                           charactersIgnoringModifiers: "i", isARepeat: false, keyCode: 34)!
                try require(recorder.performKeyEquivalent(with: key), "Recorder did not capture the combination")
                try require((controller.checkSnapshot()["draft_revisions"] as? [String: Int])?["connection_hotkey"] == recordingRevision,
                            "Recording lost the editing-start revision after a background update")
                controller.checkApplyFixture(fixture)
                await settle(); nodes = elements(content)
                try require(nodes.contains { $0.label == strings["儲存快速鍵"] && $0.enabled }, "Recorded shortcut cannot be saved")
                try require(nodes.contains { $0.label == strings["開機無螢幕時自動連線 iPad"] && $0.checked == true }, "Boot connection default is not checked")
                let beforeShortcut = commands(controller).count
                controller.checkAction("set_connection_hotkey", payload: ["shortcut": "ctrl+alt+cmd+i"])
                await settle()
                let shortcutCommands = Array(commands(controller).dropFirst(beforeShortcut))
                try require(shortcutCommands.contains { $0["args"] as? [String] == ["change-settings", "set_connection_hotkey"] },
                            "Shortcut setting bypassed the CLI transaction")
                try require(!shortcutCommands.contains { ($0["args"] as? [String] ?? []).contains("--scan") },
                            "Saving a shortcut must not scan or connect displays")
                let beforeBoot = commands(controller).count
                controller.checkAction("set_connect_on_boot", payload: ["enabled": false])
                await settle()
                let bootCommands = Array(commands(controller).dropFirst(beforeBoot))
                try require(bootCommands.contains { $0["args"] as? [String] == ["change-settings", "set_connect_on_boot"] }, "Boot option bypassed the CLI")
                try require(!bootCommands.contains { ($0["args"] as? [String] ?? []).contains("--scan") }, "Boot option scanned hardware")
                guard let cli = nodes.first(where: { $0.label == "BetterDisplay CLI" && $0.role == "AXStaticText" }) else { throw NSError(domain: "Missing CLI integration label", code: 15) }
                var previous = cli
                for key in ["自動偵測", "手動設定", "恢復預設"] {
                    guard let item = nodes.first(where: { $0.label == strings[key] && $0.role == (key == "自動偵測" ? "AXStaticText" : "AXButton") }) else {
                        throw NSError(domain: "Missing CLI integration item: \(key)", code: 19)
                    }
                    try require(item.frame.minX >= previous.frame.maxX - 1 && abs(item.frame.midY - cli.frame.midY) < 12,
                                "CLI detection and path controls are not in order on one row: \(language)/\(key)")
                    previous = item
                }
            }
            if page == "diagnostics" {
                let automatic = nodes.first { $0.role == "AXCheckBox" && $0.label == strings["自動更新"] }
                try require(automatic?.checked == false, "Log automatic updates must be visibly off by default")
                try require(Array(commands(controller).dropFirst(pageRequests)).contains { $0["args"] as? [String] == ["gui-data", "--scan", "--diagnostics", "--logs"] },
                            "Opening diagnostics did not load the initial logs")
                guard let target = nodes.first(where: { $0.label == strings["期望目標："] }) else { throw NSError(domain: "Missing expected target row", code: 14) }
                try require(nodes.contains { $0.role == "AXButton" && $0.label == strings["重新整理"] && $0.frame.minX > target.frame.maxX && abs($0.frame.midY - target.frame.midY) < 12 },
                            "Decision refresh is not on the expected target row")
                for key in ["啟動與必要設定偵測", "啟動與必要設定偵測 — 需要使用者帳號密碼"] {
                    guard let heading = nodes.first(where: { $0.label == strings[key] }) else { throw NSError(domain: "Missing diagnostic card title: \(key)", code: 20) }
                    try require(nodes.contains { $0.role == "AXButton" && $0.label == strings["重新整理"] && $0.frame.minX > heading.frame.maxX && abs($0.frame.midY - heading.frame.midY) < 12 },
                                "Diagnostic refresh is not beside its card title: \(language)/\(key)")
                    let bodyKey = key == "啟動與必要設定偵測" ? "通過" : "查詢登入項目時，macOS 可能要求輸入管理員帳號與密碼。請在系統驗證視窗輸入；PadPilot 不會收集或儲存密碼。只有按此區重新整理才會查詢。"
                    guard let firstBody = nodes.first(where: { $0.label == strings[bodyKey] && $0.role == "AXStaticText" }) else { throw NSError(domain: "Missing diagnostic card body: \(key)", code: 21) }
                    try require(firstBody.frame.minX >= heading.frame.minX - 2 && firstBody.frame.minX <= heading.frame.minX + 30 && firstBody.frame.minY >= heading.frame.maxY - 2 && firstBody.frame.minY < heading.frame.maxY + 32,
                                "Diagnostic body is not aligned left immediately below its title: \(language)/\(key)")
                }
            }
            if language == "en" {
                for node in nodes where !["繁體中文", "日本語", "歐付寶2218408", "綠界科技"].contains(node.label) {
                    try require(!node.label.unicodeScalars.contains { (0x4e00...0x9fff).contains($0.value) }, "Untranslated native text: \(page)/\(node.label)")
                }
            }
            let text = nodes.map { "\($0.role): \($0.label)" }.filter { !$0.hasSuffix(": ") }
            try require(!text.isEmpty, "Native accessibility tree is empty")
            try text.joined(separator: "\n").write(to: output.appendingPathComponent("\(language)-\(page).txt"), atomically: true, encoding: .utf8)
            for node in nodes where ["AXButton", "AXTextField", "AXCheckBox", "AXPopUpButton"].contains(node.role) && node.frame.width > 0 {
                try require(node.frame.maxX <= window.frame.maxX + 2 && node.frame.minX >= window.frame.minX - 2,
                            "Native control overflows window: \(language)/\(page)/\(node.label)")
            }
            if page == "about" {
                for name in ["PayPal", "Ko-fi", "歐付寶2218408", "綠界科技"] {
                    let buttons = nodes.filter { $0.role == "AXButton" && $0.label == name }
                    try require(!buttons.isEmpty && buttons.allSatisfy { $0.enabled }, "Configured \(name) donation link must be enabled")
                }
                try require(text.contains { $0.contains("PolyForm Noncommercial 1.0.0") }, "About license is missing")
                try require(text.contains { $0.contains("v" + (fixture["version"] as? String ?? "")) }, "About version is missing")
            }
            inspected += 1
        }
    }

    guard let fixture = fixtures["zh-Hant"], let profile = (fixture["profiles"] as? [CheckObject])?.first,
          let profileKey = profile["key"] as? String, let uuid = profile["sidecar_uuid"] as? String else { throw NSError(domain: "Missing profile fixture", code: 5) }
    // Delay the actual controller's CLI callbacks to exercise cancellation while busy.
    var automatic = fixture, automaticConfig = fixture["config"] as? CheckObject ?? [:]
    automaticConfig["mode"] = "automatic"; automatic["config"] = automaticConfig
    controller.loadFixture(automatic, page: "settings"); controller.show(page: "settings")
    controller.checkDeferCommands(true)
    controller.checkProfileAction("reconnect_sidecar", key: profileKey)
    await settle()
    guard let manualButton = elements(content).first(where: { $0.identifier == "mode.manual_only" && $0.role == "AXButton" }) else {
        throw NSError(domain: "Missing manual-mode cancellation button", code: 30)
    }
    try require(elements(content).first(where: { $0.identifier == "mode.prefer_ipad" })?.enabled == false,
                "Busy settings enabled a competing automatic mode")
    try require(manualButton.enabled && manualButton.press(), "Busy settings prevented switching to manual mode")
    let manualPayload = mutations(controller).last?["payload"] as? CheckObject ?? [:]
    try require(manualPayload["mode"] as? String == "manual_only" && manualPayload["__expected_revision__"] == nil,
                "Cancellation reused a revision made stale by the pending command")
    let cancellationCount = mutations(controller).count
    controller.checkAction("set_mode", payload: ["mode": "manual_only"])
    controller.checkAction("set_mode", payload: ["mode": "prefer_ipad"])
    try require(mutations(controller).count == cancellationCount, "Pending cancellation allowed duplicate or competing requests")
    controller.checkCompleteCommand(0, error: "Obsolete connection timeout")
    try require(controller.checkSnapshot()["busy"] as? Bool == true
                && controller.checkSnapshot()["notice"] as? String != "Obsolete connection timeout",
                "Old control completion cleared the pending cancellation or displayed its error")
    controller.checkCompleteCommand(0)
    var manual = fixture, manualConfig = fixture["config"] as? CheckObject ?? [:]
    manualConfig["mode"] = "manual_only"; manualConfig["revision"] = 8; manual["config"] = manualConfig
    controller.checkApplyFixture(manual)
    controller.checkCompleteCommand(0)
    try require(controller.checkSnapshot()["busy"] as? Bool == false
                && controller.checkSnapshot()["config_revision"] as? Int == 8,
                "Manual-mode acknowledgement did not refresh the saved configuration")
    var connectingManual = manual, connectingStatus = manual["status"] as? CheckObject ?? [:]
    connectingStatus["runtime"] = ["transition_state": "CONNECTING_SIDECAR"]
    connectingManual["status"] = connectingStatus
    controller.checkApplyFixture(connectingManual); await settle()
    try require(elements(content).contains { $0.identifier == "mode.manual_only" && $0.enabled
                && $0.label == "停止目前連線嘗試" }, "An existing manual-mode connection has no cancellation button")

    controller.loadFixture(automatic, page: "settings")
    controller.checkRefresh("decision")
    controller.checkAction("set_mode", payload: ["mode": "manual_only"])
    controller.checkCompleteCommand(1)
    controller.checkApplyFixture(manual)
    controller.checkCompleteCommand(1)
    controller.checkAction("set_language", payload: ["language": "en"])
    controller.checkCompleteCommand(0, error: "Obsolete scan timeout")
    try require(controller.checkSnapshot()["busy"] as? Bool == true
                && controller.checkSnapshot()["notice"] as? String != "Obsolete scan timeout",
                "Late scan completion cleared a newer command or displayed its error")
    controller.checkCompleteCommand(0)
    controller.checkCompleteCommand(0)
    controller.checkDeferCommands(false)

    controller.loadFixture(fixture)
    controller.show()
    let initialNumber = window.windowNumber
    controller.show(page: "settings")
    try require(window.windowNumber == initialNumber, "Opening settings created another window")
    window.performMiniaturize(nil)
    await settle()
    try require(window.isMiniaturized, "Native minimize did not minimize the window")
    controller.show()
    await settle()
    try require(!window.isMiniaturized && window.isVisible && window.windowNumber == initialNumber, "Reopening minimized settings did not restore the same visible window")
    try require(controller.checkSnapshot()["page"] as? String == "settings", "Restoring a minimized window lost its current page")
    let before = mutations(controller).count
    controller.checkConfirm(false)
    controller.checkProfileAction("delete", key: profileKey)
    try require(mutations(controller).count == before, "Declining confirmation sent a mutation")
    controller.checkConfirm(true)
    controller.checkProfileAction("delete", key: profileKey)
    var last = mutations(controller).last ?? [:]
    try require(last["args"] as? [String] == ["change-settings", "delete_pairing"], "Delete bypassed the shared transaction")
    try require((last["payload"] as? CheckObject)?["key"] as? String == profileKey, "Delete used an imprecise profile identity")
    try require((last["payload"] as? CheckObject)?["__expected_revision__"] as? Int == 7, "Delete omitted the revision")

    controller.loadFixture(fixture)
    controller.checkRealConfirm()
    let modalStart = mutations(controller).count
    controller.checkProfileAction("delete", key: profileKey); await settle()
    guard let sheet = window.attachedSheet, let sheetContent = sheet.contentView else { throw NSError(domain: "Missing native confirmation sheet", code: 10) }
    let sheetButtons = views(sheetContent).compactMap { $0 as? NSButton }
    guard let no = sheetButtons.first(where: { $0.title == "否" }), let yes = sheetButtons.first(where: { $0.title == "是" }) else { throw NSError(domain: "Unlocalized confirmation choices", code: 11) }
    try require(!no.title.isEmpty && yes.keyEquivalent.isEmpty, "Yes must not be the keyboard default")
    var changedWhileConfirming = fixture, newerConfig = fixture["config"] as? CheckObject ?? [:]
    newerConfig["revision"] = 9; changedWhileConfirming["config"] = newerConfig
    controller.checkApplyFixture(changedWhileConfirming)
    yes.performClick(nil); await settle()
    try require(mutations(controller).count == modalStart + 1, "Native confirmation did not send exactly one mutation")
    try require((mutations(controller).last?["payload"] as? CheckObject)?["__expected_revision__"] as? Int == 7, "Confirmation failed to freeze the revision shown to the user")
    controller.loadFixture(fixture)
    controller.checkProfileAction("delete", key: profileKey); await settle()
    guard let cancel = window.attachedSheet?.contentView.flatMap({ views($0).compactMap { $0 as? NSButton }.first { $0.title == "否" } }) else { throw NSError(domain: "Missing native No button", code: 12) }
    let declineStart = mutations(controller).count
    cancel.performClick(nil); await settle()
    try require(mutations(controller).count == declineStart, "Clicking native No mutated configuration")
    for (character, code) in [("\u{1b}", UInt16(53)), ("\r", UInt16(36))] {
        controller.checkProfileAction("delete", key: profileKey); await settle()
        guard let keyboardSheet = window.attachedSheet,
              let key = NSEvent.keyEvent(with: .keyDown, location: .zero, modifierFlags: [], timestamp: ProcessInfo.processInfo.systemUptime,
                                        windowNumber: keyboardSheet.windowNumber, context: nil, characters: character,
                                        charactersIgnoringModifiers: character, isARepeat: false, keyCode: code) else {
            throw NSError(domain: "Missing native keyboard confirmation", code: 13)
        }
        NSApp.sendEvent(key); await settle()
        try require(window.attachedSheet == nil && mutations(controller).count == declineStart,
                    "Native confirmation key \(code) did not cancel without mutation")
    }
    controller.checkConfirm(true)

    let draftKey = "name.\(uuid)"
    controller.checkEdit(draftKey, value: "Unsaved name")
    for revision in 8...10 {
        var heartbeat = fixture
        heartbeat["status_revision"] = revision
        var actual = heartbeat["actual"] as? CheckObject ?? [:]; actual["timestamp"] = revision; heartbeat["actual"] = actual
        controller.checkApplyFixture(heartbeat); await settle()
        try require((controller.checkSnapshot()["drafts"] as? [String: String])?[draftKey] == "Unsaved name", "Heartbeat lost the draft")
    }
    var updated = fixture, configuration = fixture["config"] as? CheckObject ?? [:]
    configuration["revision"] = 9; updated["config"] = configuration
    controller.checkApplyFixture(updated)
    controller.checkEdit(draftKey, value: "Edited after external update")
    controller.checkProfileAction("name", key: profileKey)
    last = mutations(controller).last ?? [:]
    try require((last["payload"] as? CheckObject)?["__expected_revision__"] as? Int == 7, "Editing after external update lost the original draft revision")
    try require((controller.checkSnapshot()["drafts"] as? [String: String])?[draftKey] == nil, "Successful save did not clear its draft")

    controller.loadFixture(fixture)
    for action in ["use_ipad_main", "use_ipad_secondary", "disconnect_ipad", "reconnect_sidecar"] {
        controller.checkProfileAction(action, key: profileKey)
        try require(mutations(controller).last?["args"] as? [String] == ["action", action, "--expected-revision", "7", "--target-key", profileKey], "Control lost guarded identity: \(action)")
    }
    let count = mutations(controller).count
    let other = (fixture["profiles"] as? [CheckObject])?.last?["key"] as? String ?? ""
    controller.checkProfileAction("disconnect_ipad", key: other)
    try require(mutations(controller).count == count, "Non-target profile sent a control action")
    var readonly = fixture; readonly["config_error"] = "Unreadable original config"
    controller.checkApplyFixture(readonly)
    controller.checkAction("set_auto_detect_ipad", payload: ["enabled": true])
    controller.checkAction("set_mode", payload: ["mode": "manual_only"])
    controller.checkProfileAction("delete", key: profileKey)
    try require(mutations(controller).count == count, "Readonly window sent a mutation")
    controller.loadFixture(fixture)
    let languageStart = commands(controller).count
    controller.checkAction("set_language", payload: ["language": "en"])
    let languageCommands = Array(commands(controller).dropFirst(languageStart))
    try require(!languageCommands.contains { ($0["args"] as? [String] ?? []).contains("--scan") }, "Language change scanned hardware")
    for (section, flags) in [("decision", ["--refresh"]), ("system_checks", ["--scan", "--diagnostics"]), ("authenticated_checks", ["--admin-checks"]), ("logs", ["--logs"])] {
        let start = commands(controller).count
        controller.checkRefresh(section)
        let dispatched = Array(commands(controller).dropFirst(start))
        try require(dispatched.count == 1 && dispatched[0]["args"] as? [String] == ["gui-data"] + flags, "Diagnostic refresh crossed card boundaries: \(section)")
    }

    // Exercise a real native field, with the AppKit editor/focus surviving heartbeat updates.
    controller.loadFixture(fixture, page: "search"); controller.show(page: "search"); await settle()
    guard let field = views(content).compactMap({ $0 as? NSTextField }).first(where: { $0.isEditable && $0.stringValue == "New iPad" }) else {
        throw NSError(domain: "Missing real candidate name field", code: 6)
    }
    window.makeFirstResponder(field)
    guard let editor = field.currentEditor() else { throw NSError(domain: "Native name field cannot receive focus", code: 7) }
    editor.string = "Actual typed draft"
    field.stringValue = editor.string
    field.delegate?.controlTextDidChange?(Notification(name: NSControl.textDidChangeNotification, object: field))
    editor.selectedRange = NSRange(location: 3, length: 0)
    let candidateKey = "candidate.33333333-3333-4333-8333-333333333333"
    try require((controller.checkSnapshot()["drafts"] as? [String: String])?[candidateKey] == "Actual typed draft", "Typing into the actual field did not update its draft")
    for revision in 11...13 {
        var heartbeat = fixture; heartbeat["status_revision"] = revision
        controller.checkApplyFixture(heartbeat); await settle()
        try require(views(content).contains { $0 === field } && field.stringValue == "Actual typed draft", "Heartbeat replaced the native field or erased its text")
        try require(window.firstResponder === editor && editor.selectedRange.location == 3, "Heartbeat lost the field focus or cursor")
    }
    controller.checkEdit("candidateUSB.33333333-3333-4333-8333-333333333333", value: "USB456")
    let pairingStart = mutations(controller).count
    guard let pair = elements(content).first(where: { $0.role == "AXButton" && $0.label == "配對" && $0.enabled }) else {
        throw NSError(domain: "Missing actionable candidate Pair button", code: 16)
    }
    try require(pair.press(), "The native Pair button could not be pressed"); await settle()
    let paired = mutations(controller).last ?? [:], pairingPayload = paired["payload"] as? CheckObject ?? [:]
    let pairedIPad = pairingPayload["ipad"] as? CheckObject ?? [:]
    try require(mutations(controller).count == pairingStart + 1 && paired["args"] as? [String] == ["change-settings", "save_pairing"], "Pair did not use exactly one shared save_pairing transaction")
    try require(pairedIPad["sidecar_uuid"] as? String == "33333333-3333-4333-8333-333333333333" && pairedIPad["name"] as? String == "Actual typed draft" && pairedIPad["usb_serial"] as? String == "USB456",
                "Pair saved the wrong candidate identity or ignored its edited name/USB")
    try require(pairingPayload["activate"] as? Bool == false && pairingPayload["__expected_revision__"] as? Int == 7, "Pair changed the target implicitly or lost the draft revision")
    controller.loadFixture(fixture)
    controller.checkEdit(draftKey, value: "Keep after conflict")
    controller.checkFailure("CONFIG_CONFLICT: revision changed")
    controller.checkProfileAction("name", key: profileKey)
    try require((controller.checkSnapshot()["drafts"] as? [String: String])?[draftKey] == "Keep after conflict", "Revision conflict erased the draft")
    try require(!(controller.checkSnapshot()["notice"] as? String ?? "").isEmpty, "Revision conflict was hidden")

    var newer = fixture, newActual = fixture["actual"] as? CheckObject ?? [:]
    newActual["timestamp"] = Date().timeIntervalSince1970; newer["actual"] = newActual
    newer["fresh"] = true; controller.loadFixture(newer)
    var translated = fixtures["en"]!, translatedConfig = translated["config"] as? CheckObject ?? [:]
    translatedConfig["revision"] = 8; translatedConfig["updated_at"] = Date().timeIntervalSince1970
    translated["config"] = translatedConfig; translated["scanned"] = false
    controller.checkApplyFixture(translated)
    try require((controller.checkSnapshot()["actual"] as? CheckObject)?["timestamp"] as? Double == newActual["timestamp"] as? Double, "Language-only update discarded the newer hardware observation")
    translatedConfig["auto_detect_ipad"] = true; translated["config"] = translatedConfig
    controller.checkApplyFixture(translated)
    try require((controller.checkSnapshot()["actual"] as? CheckObject)?["timestamp"] as? Int == 100, "Semantic target change retained an unrelated observation")

    var logging = fixture
    logging["logs"] = "2026-09-11 10:00:00 [INFO] [test] payload [ERROR] [WARNING]\n2026-09-11 10:00:01 [WARNING] [test] warning\n2026-09-11 10:00:02 [ERROR] [test] payload [INFO]\nunstructured [INFO] text"
    controller.loadFixture(logging, page: "diagnostics")
    for (filter, count) in [("all", 4), ("info", 1), ("error", 1), ("warning", 2)] {
        try require(controller.checkLogFilter(filter).split(separator: "\n").count == count, "Log filter matched message text instead of the record level: \(filter)")
    }
    var noLogs = logging; noLogs.removeValue(forKey: "logs"); controller.checkApplyFixture(noLogs)
    try require(controller.checkSnapshot()["logText"] as? String == logging["logs"] as? String, "An unrelated snapshot cleared the logs")
    noLogs["logs"] = ""; controller.checkApplyFixture(noLogs)
    try require(controller.checkSnapshot()["logText"] as? String == "", "Empty log file did not clear old logs")
    logging["logs"] = (0..<200).map { "2026-09-11 10:00:00 [INFO] [test] line \($0)" }.joined(separator: "\n")
    controller.loadFixture(logging, page: "diagnostics"); controller.show(page: "diagnostics")
    _ = controller.checkLogFilter("all"); await settle()
    guard let log = views(content).compactMap({ $0 as? NSTextView }).first(where: { $0.accessibilityLabel() == "PadPilot logs" }), let scroll = log.enclosingScrollView else {
        throw NSError(domain: "Missing native independent log view", code: 9)
    }
    scroll.contentView.scroll(to: NSPoint(x: 0, y: 100)); scroll.reflectScrolledClipView(scroll.contentView)
    let logOrigin = scroll.contentView.bounds.origin
    var changedDecision = logging; changedDecision.removeValue(forKey: "logs")
    changedDecision["decision"] = ["reason": "Updated decision", "last_error": "Expected test error"]
    controller.checkApplyFixture(changedDecision); await settle()
    try require(views(content).contains { $0 === log } && scroll.contentView.bounds.origin == logOrigin, "Decision refresh replaced the log view or moved its scroll position")
    let autoLabel = (fixture["strings"] as? [String: String])?["自動更新"] ?? "自動更新"
    @MainActor func autoUpdateCheckbox() throws -> CheckElement {
        guard let checkbox = elements(content).first(where: { $0.role == "AXCheckBox" && $0.label == autoLabel }) else {
            throw NSError(domain: "Missing automatic log update checkbox", code: 17)
        }
        return checkbox
    }
    @MainActor func expectPoll(_ args: [String]) throws {
        let start = commands(controller).count
        controller.checkPoll()
        let requests = Array(commands(controller).dropFirst(start))
        try require(requests.count == 1 && requests[0]["args"] as? [String] == args, "Periodic log update used unexpected arguments: \(requests)")
    }
    try require(controller.checkSnapshot()["logs_auto_update"] as? Bool == false, "Log automatic updates did not default to off")
    try expectPoll(["gui-data"])
    let uncheckedAuto = try autoUpdateCheckbox()
    try require(uncheckedAuto.press(), "The native automatic-update checkbox could not be checked"); await settle()
    let checkedAuto = try autoUpdateCheckbox()
    try require(controller.checkSnapshot()["logs_auto_update"] as? Bool == true && checkedAuto.checked == true, "Checking automatic updates did not enable the model and native checkbox")
    try expectPoll(["gui-data", "--logs"])
    controller.show(page: "settings"); await settle()
    try expectPoll(["gui-data"])
    controller.show(page: "diagnostics"); await settle()
    let retainedAuto = try autoUpdateCheckbox()
    try require(retainedAuto.press(), "The native automatic-update checkbox could not be unchecked"); await settle()
    try expectPoll(["gui-data"])
    let manualLogStart = commands(controller).count
    guard let refreshLog = elements(content).first(where: { $0.role == "AXButton" && $0.label == "🔄 刷新日誌" }) else {
        throw NSError(domain: "Missing manual log refresh button", code: 18)
    }
    try require(refreshLog.press(), "The native log refresh button could not be pressed"); await settle()
    try require(Array(commands(controller).dropFirst(manualLogStart)).contains { $0["args"] as? [String] == ["gui-data", "--logs"] }, "Manual log refresh stopped working when automatic updates were off")
    controller.checkStop()
    let stopped = commands(controller).count
    controller.checkRefresh("system_checks")
    controller.checkPoll()
    try require(commands(controller).count == stopped && controller.checkSnapshot()["active"] as? Bool == false, "Closing settings kept polling or scanning hardware")

    print("PASS: \(inspected) native Swift pages at 840px, complete accessibility content and expanded controls; real confirmation clicks/keyboard/revisions, minimize/restore, real field typing/focus and candidate pairing, draft conflicts, readonly/target guards, language-only updates, independent diagnostics/log scrolling, opt-in log polling and exact log filters. AX reports are authoritative; screenshots are not used as assertions.")
}
