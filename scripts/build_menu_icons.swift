// Rebuild with: swift scripts/build_menu_icons.swift
import AppKit

let root = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent()
let output = root.appendingPathComponent("assets/menu-icons")
try FileManager.default.createDirectory(at: output, withIntermediateDirectories: true)
let states = ["ipad", "physical", "virtual", "manual", "paused", "warning", "working"]

func draw(_ state: String) {
    NSColor.black.set()
    let frame = NSBezierPath(roundedRect: NSRect(x: 3, y: 1, width: 12, height: 16), xRadius: 2.5, yRadius: 2.5)
    frame.lineWidth = 1.5
    frame.stroke()
    NSBezierPath(roundedRect: NSRect(x: 7, y: 3, width: 4, height: 1), xRadius: 0.5, yRadius: 0.5).fill()
    switch state {
    case "ipad":
        let arrow = NSBezierPath()
        arrow.move(to: NSPoint(x: 9, y: 14))
        arrow.line(to: NSPoint(x: 5.5, y: 6.5))
        arrow.line(to: NSPoint(x: 9, y: 8))
        arrow.line(to: NSPoint(x: 12.5, y: 6.5))
        arrow.close()
        arrow.fill()
    case "manual":
        NSImage(systemSymbolName: "hand.point.up.fill", accessibilityDescription: nil)!
            .draw(in: NSRect(x: 5.5, y: 5.5, width: 7, height: 9))
    case "paused":
        for x in [6.0, 10.0] { NSBezierPath(rect: NSRect(x: x, y: 7, width: 2, height: 6)).fill() }
    case "warning":
        NSBezierPath(roundedRect: NSRect(x: 8, y: 9, width: 2, height: 5), xRadius: 1, yRadius: 1).fill()
        NSBezierPath(ovalIn: NSRect(x: 8, y: 6, width: 2, height: 2)).fill()
    case "working":
        for x in [5.5, 8.25, 11.0] { NSBezierPath(ovalIn: NSRect(x: x, y: 9, width: 1.5, height: 1.5)).fill() }
    default:
        let screen = NSBezierPath(roundedRect: NSRect(x: 5.5, y: 8, width: 7, height: 5), xRadius: 0.75, yRadius: 0.75)
        screen.lineWidth = 1
        screen.stroke()
        if state == "physical" { NSBezierPath(rect: NSRect(x: 7, y: 6, width: 4, height: 1)).fill() }
    }
}

func png(width: Int, height: Int, scale: CGFloat, body: () -> Void) -> Data {
    let rep = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: width, pixelsHigh: height,
        bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false,
        colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0)!
    rep.size = NSSize(width: CGFloat(width) / scale, height: CGFloat(height) / scale)
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: rep)
    body()
    NSGraphicsContext.restoreGraphicsState()
    return rep.representation(using: .png, properties: [:])!
}

for state in states {
    try png(width: 36, height: 36, scale: 2) { draw(state) }
        .write(to: output.appendingPathComponent("\(state).png"))
}
try png(width: states.count * 120, height: 128, scale: 4) {
    NSColor.white.setFill()
    NSRect(x: 0, y: 0, width: states.count * 30, height: 32).fill()
    for (index, state) in states.enumerated() {
        NSGraphicsContext.saveGraphicsState()
        let move = NSAffineTransform()
        move.translateX(by: CGFloat(index * 30 + 6), yBy: 7)
        move.concat()
        draw(state)
        NSGraphicsContext.restoreGraphicsState()
    }
}.write(to: output.appendingPathComponent("preview.png"))
