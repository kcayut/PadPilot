// Generate the Finder background using macOS fonts.
import AppKit

let output = URL(fileURLWithPath: CommandLine.arguments[1], isDirectory: true)
let canvas = NSSize(width: 960, height: 640)
func color(_ hex: Int) -> NSColor {
    NSColor(srgbRed: CGFloat((hex >> 16) & 255) / 255,
            green: CGFloat((hex >> 8) & 255) / 255,
            blue: CGFloat(hex & 255) / 255, alpha: 1)
}
let ink = color(0x102139), muted = color(0x526174), blue = color(0x075bce)
// Reserve both the real Finder icons and their filenames. Background copy may not enter.
let iconZones = [NSRect(x: 752, y: 94, width: 176, height: 102),
                 NSRect(x: 232, y: 281, width: 176, height: 118),
                 NSRect(x: 522, y: 281, width: 176, height: 118),
                 NSRect(x: 752, y: 460, width: 176, height: 120)]

let bitmap = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: 960,
    pixelsHigh: 640, bitsPerSample: 8, samplesPerPixel: 4,
    hasAlpha: true, isPlanar: false, colorSpaceName: .deviceRGB,
    bytesPerRow: 0, bitsPerPixel: 0)!
bitmap.size = canvas
let context = NSGraphicsContext(bitmapImageRep: bitmap)!.cgContext
context.translateBy(x: 0, y: canvas.height)
context.scaleBy(x: 1, y: -1)
NSGraphicsContext.saveGraphicsState()
NSGraphicsContext.current = NSGraphicsContext(cgContext: context, flipped: true)

func box(_ x: CGFloat, _ y: CGFloat, _ w: CGFloat, _ h: CGFloat, _ fill: NSColor) {
    fill.setFill()
    NSBezierPath(roundedRect: NSRect(x: x, y: y, width: w, height: h),
                 xRadius: 18, yRadius: 18).fill()
}
func text(_ value: String, _ x: CGFloat, _ y: CGFloat, _ width: CGFloat,
          _ size: CGFloat = 14, _ weight: NSFont.Weight = .regular,
          _ foreground: NSColor = ink) {
    let attributes: [NSAttributedString.Key: Any] = [
        .font: NSFont.systemFont(ofSize: size, weight: weight), .foregroundColor: foreground]
    let string = value as NSString
    precondition(string.size(withAttributes: attributes).width <= width,
                 "DMG text exceeds its column: \(value)")
    let bounds = NSRect(origin: NSPoint(x: x, y: y), size: string.size(withAttributes: attributes))
    precondition(!iconZones.contains { $0.intersects(bounds) }, "DMG text enters an icon zone: \(value)")
    string.draw(at: NSPoint(x: x, y: y), withAttributes: attributes)
}
func number(_ value: String, _ y: CGFloat) {
    box(44, y, 28, 28, blue)
    text(value, 53, y + 4, 20, 16, .semibold, .white)
}

color(0xf3f7fc).setFill()
NSRect(origin: .zero, size: canvas).fill()
text("PadPilot", 36, 16, 500, 30, .bold)
text("開始安裝  /  Get started  /  インストール", 38, 57, 650, 14, .regular, muted)
text("Apple Silicon  ·  macOS 14+", 710, 34, 230, 13, .medium, muted)

box(28, 90, 904, 108, color(0xe6effc))
number("1", 107)
text("先安裝並開啟 BetterDisplay（免費版即可）", 86, 105, 650, 19, .semibold)
text("Install & open BetterDisplay · No Pro required", 86, 141, 650, 14, .regular, muted)
text("BetterDisplay をインストールして起動 · Pro 不要", 86, 165, 650, 14, .regular, muted)

box(28, 210, 904, 194, .white)
number("2", 226)
text("拖入應用程式，再從應用程式開啟", 86, 224, 800, 19, .semibold)
text("Drag into Applications, then open there  /  アプリケーションへドラッグして起動", 86, 255, 800, 14, .regular, muted)
// Real Finder icons remain draggable; only the connecting arrow is artwork.
let arrow = NSBezierPath()
arrow.move(to: NSPoint(x: 430, y: 326))
arrow.line(to: NSPoint(x: 502, y: 326))
arrow.move(to: NSPoint(x: 489, y: 313))
arrow.line(to: NSPoint(x: 502, y: 326))
arrow.line(to: NSPoint(x: 489, y: 339))
arrow.lineWidth = 3
arrow.lineCapStyle = .round
arrow.lineJoinStyle = .round
blue.setStroke()
arrow.stroke()

box(28, 416, 904, 192, .white)
number("3", 432)
text("首次開啟被阻擋？手動允許一次", 86, 429, 650, 19, .semibold)
text("If blocked on first launch  /  初回起動がブロックされたら", 86, 460, 650, 13, .regular, muted)
text("系統設定 → 隱私權與安全性 → 強制打開 → 打開", 86, 489, 650, 15, .medium)
text("System Settings → Privacy & Security → Open Anyway → Open", 86, 518, 650, 13.5)
text("システム設定 → プライバシーとセキュリティ → このまま開く → 開く", 86, 546, 650, 13.5)
text("完整步驟  /  Full guide  /  詳しい手順 →", 86, 582, 650, 12, .regular, muted)
text("繁中 · EN · 日本語", 784, 584, 145, 12, .medium, muted)
text("未經 Apple 公證  ·  Not notarized by Apple  ·  Apple 公証なし", 36, 612, 890, 11, .regular, muted)

for zone in iconZones {
    let well = NSBezierPath(roundedRect: zone, xRadius: 14, yRadius: 14)
    color(0xf3f7fc).setFill()
    well.fill()
    color(0xd4e1f2).setStroke()
    well.lineWidth = 1
    well.stroke()
}

NSGraphicsContext.restoreGraphicsState()
try bitmap.representation(using: .png, properties: [:])!.write(to: output.appendingPathComponent("background.png"))
