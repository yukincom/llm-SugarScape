// Package the supplied artwork as a transparent macOS icon, without an inset.
// Run from the repository root: swift tools/build_app_icon.swift
import AppKit
import Foundation

let root = URL(fileURLWithPath: FileManager.default.currentDirectoryPath)
let assets = root.appendingPathComponent("assets/branding")
let source = NSImage(contentsOf: assets.appendingPathComponent("app-icon-source.png"))!
let sourceRep = NSBitmapImageRep(data: try Data(contentsOf: assets.appendingPathComponent("app-icon-source.png")))!
source.size = NSSize(width: sourceRep.pixelsWide, height: sourceRep.pixelsHigh)
let side = max(source.size.width, source.size.height)
let iconset = root.appendingPathComponent("build/AppIcon.iconset")
try FileManager.default.createDirectory(at: iconset, withIntermediateDirectories: true)

func png(size: Int) -> Data {
    let bitmap = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: size, pixelsHigh: size,
                                 bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true,
                                 isPlanar: false, colorSpaceName: .deviceRGB, bytesPerRow: 0,
                                 bitsPerPixel: 0)!
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: bitmap)
    NSGraphicsContext.current!.imageInterpolation = .high
    NSColor.clear.setFill()
    NSRect(x: 0, y: 0, width: size, height: size).fill(using: .copy)
    // The source spans the full width. Only transparent space is added above
    // and below; no safety margin or smaller subject is introduced.
    let scale = CGFloat(size) / side
    let width = source.size.width * scale
    let height = source.size.height * scale
    source.draw(in: NSRect(x: (CGFloat(size) - width) / 2,
                          y: (CGFloat(size) - height) / 2, width: width, height: height),
                from: .zero, operation: .copy, fraction: 1)
    NSGraphicsContext.restoreGraphicsState()
    return bitmap.representation(using: .png, properties: [:])!
}

try png(size: Int(side)).write(to: assets.appendingPathComponent("app-icon.png"))
for points in [16, 32, 128, 256, 512] {
    for scale in [1, 2] {
        let suffix = scale == 2 ? "@2x" : ""
        try png(size: points * scale).write(to: iconset.appendingPathComponent("icon_\(points)x\(points)\(suffix).png"))
    }
}
let task = Process()
task.executableURL = URL(fileURLWithPath: "/usr/bin/iconutil")
task.arguments = ["--convert", "icns", iconset.path, "--output", assets.appendingPathComponent("AppIcon.icns").path]
try task.run()
task.waitUntilExit()
guard task.terminationStatus == 0 else {
    fputs("iconutil failed\n", stderr)
    exit(task.terminationStatus)
}
print("Created assets/branding/AppIcon.icns")
