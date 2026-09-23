import AppKit
import Foundation

@main
struct NativeLaunchCheck {
    static func main() {
        let app = NSApplication.shared
        let delegate = AppDelegate()
        app.delegate = delegate
        Task { @MainActor in
            for _ in 0..<50 {
                if delegate.checkMenuVisible { break }
                try? await Task.sleep(nanoseconds: 100_000_000)
            }
            precondition(delegate.checkMenuVisible, "Launch must create the menu bar item")
            func settings() -> NSWindow? { app.windows.first { $0.title == "SidecarSwitch" && $0.isVisible } }
            precondition((settings() != nil) == !CommandLine.arguments.contains("--menu-only"),
                         "A normal app launch opens the GUI; background startup leaves it closed")
            _ = delegate.applicationShouldHandleReopen(app, hasVisibleWindows: settings() != nil)
            guard let window = settings() else { preconditionFailure("Reopen must show the GUI") }
            window.miniaturize(nil)
            _ = delegate.applicationShouldHandleReopen(app, hasVisibleWindows: false)
            precondition(window.isVisible && !window.isMiniaturized, "Reopen must restore a minimized GUI")
            window.close()
            delegate.application(app, open: [URL(string: "sidecarswitch://menu")!])
            precondition(settings() == nil && delegate.checkMenuVisible, "Background requests leave the GUI closed")
            _ = delegate.applicationShouldHandleReopen(app, hasVisibleWindows: false)
            precondition(settings() === window && delegate.checkMenuVisible, "Reopen must reuse the closed GUI and existing menu")
            window.close()
            print("PASS: GUI and menu startup, background launch, close and reopen, minimize and restore")
            exit(0)
        }
        withExtendedLifetime(delegate) { app.run() }
    }
}
