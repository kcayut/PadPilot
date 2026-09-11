import AppKit
import Foundation

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
                precondition(item.isEnabled == (row.enabled && (!busy || row.args.isEmpty || row.args.first == "gui")), "enabled mismatch: \(row.title), busy=\(busy), args=\(row.args)")
                precondition(item.state == (row.checked ? .on : .off))
                precondition((item.action == #selector(Actions.perform(_:))) == validAction(row.args))
                precondition(item.representedObject as? [String] == row.args)
            }
            precondition(menu.items.filter { $0.submenu != nil }.count == 5)
            precondition(items.last?.representedObject as? [String] == ["exit"])
        }
        precondition(validAction(["gui", "wizard", "--delete", String(repeating: "a", count: 64)]))
        for args in [["sh", "-c", "touch /tmp/no"], ["start", "--no-menu"],
                     ["action", "garbage"], ["gui", "wizard", "--delete", "../../file"], ["exit", "extra"]] {
            precondition(!validAction(args))
        }
        print("PASS: native menu decoding, nested menus, checked/disabled/busy items, and CLI argument allowlist")
    }
}
