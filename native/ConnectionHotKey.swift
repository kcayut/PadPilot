import AppKit
import Carbon
import Combine

/// One registered shortcut for the menu app; no event tap or keyboard logging.
final class ConnectionHotKey: ObservableObject {
    static let shared = ConnectionHotKey()
    static let modifiers: [(String, String, UInt32)] = [
        ("ctrl", "⌃ Control", UInt32(controlKey)), ("alt", "⌥ Option", UInt32(optionKey)),
        ("shift", "⇧ Shift", UInt32(shiftKey)), ("cmd", "⌘ Command", UInt32(cmdKey))
    ]
    // Physical ANSI positions keep a saved shortcut stable across input sources.
    static let keys: [String: UInt32] = [
        "a": 0, "s": 1, "d": 2, "f": 3, "h": 4, "g": 5, "z": 6, "x": 7, "c": 8, "v": 9,
        "b": 11, "q": 12, "w": 13, "e": 14, "r": 15, "y": 16, "t": 17, "1": 18, "2": 19,
        "3": 20, "4": 21, "6": 22, "5": 23, "9": 25, "7": 26, "8": 28, "0": 29,
        "o": 31, "u": 32, "i": 34, "p": 35, "l": 37, "j": 38, "k": 40, "n": 45, "m": 46,
        "equal": 24, "minus": 27, "rightbracket": 30, "leftbracket": 33, "return": 36,
        "quote": 39, "semicolon": 41, "backslash": 42, "comma": 43, "slash": 44, "period": 47,
        "tab": 48, "space": 49, "grave": 50, "delete": 51, "escape": 53,
        "f1": 122, "f2": 120, "f3": 99, "f4": 118, "f5": 96, "f6": 97, "f7": 98,
        "f8": 100, "f9": 101, "f10": 109, "f11": 103, "f12": 111, "f13": 105, "f14": 107,
        "f15": 113, "f16": 106, "f17": 64, "f18": 79, "f19": 80, "f20": 90,
        "home": 115, "pageup": 116, "forwarddelete": 117, "end": 119, "pagedown": 121,
        "left": 123, "right": 124, "down": 125, "up": 126
    ]
    static func parse(_ shortcut: String) -> (UInt32, UInt32)? {
        let parts = shortcut.components(separatedBy: "+")
        guard let key = parts.last, let code = keys[key] else { return nil }
        let mods = Array(parts.dropLast())
        guard !mods.isEmpty, Set(mods).count == mods.count,
              mods.contains("ctrl") || mods.contains("cmd"),
              mods.allSatisfy({ part in modifiers.contains { $0.0 == part } }) else { return nil }
        return (code, modifiers.filter { mods.contains($0.0) }.reduce(0) { $0 | $1.2 })
    }
    static func label(_ shortcut: String) -> String {
        let parts = shortcut.components(separatedBy: "+")
        guard parse(shortcut) != nil else { return "" }
        return modifiers.filter { parts.contains($0.0) }.map { String($0.1.prefix(1)) }.joined()
            + (["space": "Space", "tab": "⇥", "return": "↩", "delete": "⌫", "forwarddelete": "⌦",
                "escape": "⎋", "home": "↖", "end": "↘", "pageup": "⇞", "pagedown": "⇟",
                "left": "←", "right": "→", "up": "↑", "down": "↓", "equal": "=", "minus": "-",
                "leftbracket": "[", "rightbracket": "]", "quote": "'", "semicolon": ";", "backslash": "\\",
                "comma": ",", "slash": "/", "period": ".", "grave": "`"] [parts.last ?? ""] ?? (parts.last ?? "").uppercased())
    }

    static func shortcut(for event: NSEvent) -> String? {
        guard let key = keys.first(where: { $0.value == UInt32(event.keyCode) })?.key else { return nil }
        let flags = event.modifierFlags
        let parts = [("ctrl", flags.contains(.control)), ("alt", flags.contains(.option)),
                     ("shift", flags.contains(.shift)), ("cmd", flags.contains(.command))]
        let value = (parts.filter { $0.1 }.map { $0.0 } + [key]).joined(separator: "+")
        return parse(value) == nil ? nil : value
    }

    @Published private(set) var errorCode: OSStatus = noErr
    private(set) var configuration: String?
    private var hotKey: EventHotKeyRef?
    private var handler: EventHandlerRef?
    private var held = false
    private var recording = false
    var onPress: (() -> Void)?
    var isRegistered: Bool { hotKey != nil }
    static let signature: OSType = 0x5064506C // PdPl

    @discardableResult
    func configure(_ shortcut: String) -> Bool {
        guard configuration != shortcut else { return false }
        stop()
        configuration = shortcut
        errorCode = noErr
        guard !shortcut.isEmpty && !recording else { return true }
        guard let (key, modifiers) = Self.parse(shortcut) else { errorCode = OSStatus(paramErr); return true }
        var events = [EventTypeSpec(eventClass: OSType(kEventClassKeyboard), eventKind: UInt32(kEventHotKeyPressed)),
                      EventTypeSpec(eventClass: OSType(kEventClassKeyboard), eventKind: UInt32(kEventHotKeyReleased))]
        errorCode = InstallEventHandler(GetApplicationEventTarget(), { _, event, context in
            guard let event, let context else { return OSStatus(eventNotHandledErr) }
            var identifier = EventHotKeyID()
            guard GetEventParameter(event, EventParamName(kEventParamDirectObject), EventParamType(typeEventHotKeyID),
                                    nil, MemoryLayout<EventHotKeyID>.size, nil, &identifier) == noErr,
                  identifier.signature == ConnectionHotKey.signature, identifier.id == 1 else {
                return OSStatus(eventNotHandledErr)
            }
            Unmanaged<ConnectionHotKey>.fromOpaque(context).takeUnretainedValue().receive(GetEventKind(event))
            return noErr
        }, events.count, &events, Unmanaged.passUnretained(self).toOpaque(), &handler)
        if errorCode == noErr {
            errorCode = RegisterEventHotKey(key, modifiers, EventHotKeyID(signature: Self.signature, id: 1),
                                           GetApplicationEventTarget(), OptionBits(kEventHotKeyExclusive), &hotKey)
        }
        if errorCode != noErr, let handler {
            RemoveEventHandler(handler)
            self.handler = nil
        }
        return true
    }
    func receive(_ kind: UInt32) {
        guard !recording else { return }
        if kind == UInt32(kEventHotKeyReleased) { held = false }
        else if kind == UInt32(kEventHotKeyPressed), !held {
            held = true
            onPress?()
        }
    }
    func suspendForRecording(_ value: Bool) {
        guard recording != value else { return }
        let saved = configuration ?? ""
        recording = value
        stop()
        configure(saved)
    }
    func stop() {
        if let hotKey { UnregisterEventHotKey(hotKey) }
        if let handler { RemoveEventHandler(handler) }
        hotKey = nil; handler = nil; held = false; configuration = nil
    }
    deinit { stop() }
}

/// Captures only while this focused button is recording; no keyboard event monitor.
final class HotKeyRecorderButton: NSButton {
    var onBegin: (() -> Void)?
    var onCapture: ((String) -> Void)?
    var idleTitle = ""
    var waitingTitle = ""
    var invalidTitle = ""
    private(set) var recording = false
    private var focusObserver: NSObjectProtocol?
    override var acceptsFirstResponder: Bool { true }

    override init(frame: NSRect) {
        super.init(frame: frame)
        bezelStyle = .rounded
        target = self
        action = #selector(beginRecording)
    }
    required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }
    @objc func beginRecording() {
        if recording { finish(nil); return }
        guard isEnabled, window?.makeFirstResponder(self) == true else { return }
        recording = true
        ConnectionHotKey.shared.suspendForRecording(true)
        title = waitingTitle
        onBegin?()
    }
    private func finish(_ shortcut: String?) {
        guard recording else { return }
        recording = false
        title = idleTitle
        ConnectionHotKey.shared.suspendForRecording(false)
        if let shortcut { onCapture?(shortcut) }
    }
    private func capture(_ event: NSEvent) {
        guard !event.isARepeat else { return }
        if event.keyCode == 53 && event.modifierFlags.intersection([.control, .option, .shift, .command]).isEmpty { finish(nil); return }
        if let shortcut = ConnectionHotKey.shortcut(for: event) { finish(shortcut) }
        else { title = invalidTitle; NSSound.beep() }
    }
    override func keyDown(with event: NSEvent) {
        if recording { capture(event) } else { super.keyDown(with: event) }
    }
    override func performKeyEquivalent(with event: NSEvent) -> Bool {
        guard recording, window?.firstResponder === self else { return super.performKeyEquivalent(with: event) }
        capture(event)
        return true
    }
    override func resignFirstResponder() -> Bool {
        finish(nil)
        return super.resignFirstResponder()
    }
    override func viewWillMove(toWindow newWindow: NSWindow?) {
        finish(nil)
        if let focusObserver { NotificationCenter.default.removeObserver(focusObserver) }
        focusObserver = newWindow.map { window in
            NotificationCenter.default.addObserver(forName: NSWindow.didResignKeyNotification, object: window, queue: .main) { [weak self] _ in self?.finish(nil) }
        }
        super.viewWillMove(toWindow: newWindow)
    }
    deinit {
        if let focusObserver { NotificationCenter.default.removeObserver(focusObserver) }
        if recording { ConnectionHotKey.shared.suspendForRecording(false) }
    }
}
