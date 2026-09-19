import AppKit
import Foundation
import Carbon

final class Actions: NSObject {
    @objc func perform(_ item: NSMenuItem) {}
}

@main
struct NativeMenuCheck {
    static func main() throws {
        _ = NSApplication.shared
        let model = try JSONDecoder().decode(MenuSnapshot.self,
            from: Data(contentsOf: URL(fileURLWithPath: CommandLine.arguments[1])))
        precondition(model.schema_version == 1 && !model.hidden)
        let actions = Actions()
        precondition(validAction(["action", "connect_ipad"]))
        precondition(ConnectionHotKey.label("ctrl+alt+cmd+i") == "⌃⌥⌘I")
        for invalid in ["i", "alt+i", "ctrl+ctrl+i", "ctrl+cmd+unknown", "ctrl+cmd+i;exit"] {
            precondition(ConnectionHotKey.parse(invalid) == nil)
        }
        // Exercise the actual Carbon callback with local synthetic hotkey events.
        // No keyboard input is injected and no Sidecar action is installed.
        let hotkey = ConnectionHotKey()
        var presses = 0
        hotkey.onPress = { presses += 1 }
        hotkey.configure("ctrl+alt+shift+cmd+9")
        precondition(hotkey.isRegistered, "Native shortcut registration failed: \(hotkey.errorCode)")
        let conflict = ConnectionHotKey()
        conflict.configure("ctrl+alt+shift+cmd+9")
        precondition(!conflict.isRegistered && conflict.errorCode != noErr)
        func send(_ kind: Int, id: UInt32 = 1) {
            var event: EventRef?
            precondition(CreateEvent(nil, OSType(kEventClassKeyboard), UInt32(kind), 0, 0, &event) == noErr)
            var identifier = EventHotKeyID(signature: ConnectionHotKey.signature, id: id)
            precondition(SetEventParameter(event!, EventParamName(kEventParamDirectObject), EventParamType(typeEventHotKeyID),
                                           MemoryLayout<EventHotKeyID>.size, &identifier) == noErr)
            _ = SendEventToEventTarget(event!, GetApplicationEventTarget())
            ReleaseEvent(event!)
        }
        send(kEventHotKeyPressed, id: 2)
        send(kEventHotKeyPressed); send(kEventHotKeyPressed)
        precondition(presses == 1)
        send(kEventHotKeyReleased); send(kEventHotKeyPressed)
        precondition(presses == 2)
        precondition(!hotkey.configure("ctrl+alt+shift+cmd+9"))
        hotkey.configure("")
        precondition(!hotkey.isRegistered)
        conflict.stop()
        conflict.configure("ctrl+alt+shift+cmd+9")
        precondition(conflict.isRegistered)
        conflict.stop()
        let shared = ConnectionHotKey.shared
        shared.configure("ctrl+alt+shift+cmd+8")
        let recorderWindow = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 300, height: 80),
                                      styleMask: [.titled], backing: .buffered, defer: false)
        recorderWindow.isReleasedWhenClosed = false
        let recorder = HotKeyRecorderButton(frame: NSRect(x: 10, y: 20, width: 250, height: 30))
        recorderWindow.contentView!.addSubview(recorder)
        var recorded: String?
        recorder.onCapture = { recorded = $0 }
        func key(_ code: UInt16, _ flags: NSEvent.ModifierFlags = []) -> NSEvent {
            NSEvent.keyEvent(with: .keyDown, location: .zero, modifierFlags: flags, timestamp: 0,
                             windowNumber: recorderWindow.windowNumber, context: nil, characters: "",
                             charactersIgnoringModifiers: "", isARepeat: false, keyCode: code)!
        }
        recorder.beginRecording()
        precondition(recorder.recording && !shared.isRegistered)
        recorder.keyDown(with: key(34)) // A plain letter must not become a global shortcut.
        precondition(recorder.recording && recorded == nil)
        precondition(recorder.performKeyEquivalent(with: key(122, [.control, .command])))
        precondition(recorded == "ctrl+cmd+f1" && !recorder.recording && shared.isRegistered)
        recorder.beginRecording(); recorder.keyDown(with: key(53))
        precondition(!recorder.recording && shared.isRegistered && recorded == "ctrl+cmd+f1")
        recorder.beginRecording()
        NotificationCenter.default.post(name: NSWindow.didResignKeyNotification, object: recorderWindow)
        precondition(!recorder.recording && shared.isRegistered)
        recorder.beginRecording(); recorderWindow.makeFirstResponder(nil)
        precondition(!recorder.recording && shared.isRegistered)
        recorderWindow.close(); shared.configure("")
        func flattened(_ menu: NSMenu) -> [NSMenuItem] {
            menu.items.flatMap { item in [item] + (item.submenu.map(flattened) ?? []) }
        }
        for busy in [false, true] {
            let menu = makeMenu(model.items, target: actions, action: #selector(Actions.perform(_:)), busy: busy)
            let items = flattened(menu).filter { !$0.isSeparatorItem }
            let rows = model.items.filter { !$0.separator }
            precondition(items.count == rows.count)
            for (item, row) in zip(items, rows) {
                precondition(item.title == row.title)
                precondition((item.image != nil) == (row.icon != nil))
                if row.icon != nil {
                    precondition(item.image?.isTemplate == true)
                    precondition(item.image?.size == NSSize(width: 18, height: 18))
                }
                precondition(item.isEnabled == (row.enabled && (!busy || row.args.isEmpty || row.args.first == "gui" || row.args == ["set-mode", "manual_only"])), "enabled mismatch: \(row.title), busy=\(busy), args=\(row.args)")
                precondition(item.state == (row.checked ? .on : .off))
                precondition((item.action == #selector(Actions.perform(_:))) == validAction(row.args))
                precondition(item.representedObject as? [String] == row.args)
            }
            precondition(menu.items.filter { $0.submenu != nil }.count == 5)
            precondition(items.last?.representedObject as? [String] == ["exit"])
        }
        let pendingMenu = makeMenu(model.items, target: actions, action: #selector(Actions.perform(_:)), busy: true, manualModePending: true)
        precondition(flattened(pendingMenu).first { $0.representedObject as? [String] == ["set-mode", "manual_only"] }?.isEnabled == false)
        let delegate = AppDelegate()
        delegate.checkPrepareActions(model)
        var completions: [(Result<Data, Error>) -> Void] = []
        delegate.checkRunCLI = { args, completion in
            if args == ["menu-json"] { completion(.success(try! JSONEncoder().encode(model))) }
            else { completions.append(completion) }
        }
        let staleError = NSError(domain: "Old command timed out", code: 1)
        delegate.checkPerformAction(["set-mode", "automatic"])
        delegate.checkPerformAction(["set-mode", "manual_only"])
        delegate.checkPerformAction(["set-mode", "manual_only"])
        delegate.checkPerformAction(["set-mode", "prefer_ipad"])
        precondition(completions.count == 2 && delegate.checkBusy)
        completions[0](.failure(staleError))
        precondition(delegate.checkBusy && delegate.checkErrors.isEmpty, "Old callback cleared the pending manual request")
        completions[1](.success(Data()))
        precondition(!delegate.checkBusy)
        delegate.checkPerformAction(["set-mode", "automatic"])
        delegate.checkPerformAction(["set-mode", "manual_only"])
        completions[3](.success(Data()))
        delegate.checkPerformAction(["set-mode", "prefer_ipad"])
        completions[2](.failure(staleError))
        precondition(delegate.checkBusy && delegate.checkErrors.isEmpty, "Late callback cleared a newer request or displayed an obsolete error")
        completions[4](.success(Data()))
        precondition(!delegate.checkBusy)
        precondition(validAction(["gui", "wizard", "--delete", String(repeating: "a", count: 64)]))
        precondition(SettingsRequest(url: URL(string: "padpilot://settings?page=diagnostics")!)?.page == "diagnostics")
        for url in ["https://settings?page=about", "padpilot://other", "padpilot://settings?page=../file",
                    "padpilot://settings?delete=bad", "padpilot://settings?page=about&page=settings",
                    "padpilot://settings?command=exit"] {
            precondition(SettingsRequest(url: URL(string: url)!) == nil)
        }
        for args in [["sh", "-c", "touch /tmp/no"], ["start", "--no-menu"],
                     ["action", "garbage"], ["gui", "wizard", "--delete", "../../file"], ["exit", "extra"]] {
            precondition(!validAction(args))
        }
        print("PASS: native menu decoding, nested menus, checked/disabled/busy items, and CLI argument allowlist")
    }
}
