// Render an SVG to a square, transparent, interlaced sRGB PNG.
// Usage: swift scripts/render_icon.swift in.svg out.png size
import AppKit
import ImageIO
import UniformTypeIdentifiers

let args = CommandLine.arguments
guard args.count == 4, let size = Int(args[3]) else {
    FileHandle.standardError.write("usage: render_icon.swift in.svg out.png size\n".data(using: .utf8)!)
    exit(2)
}
guard let image = NSImage(contentsOf: URL(fileURLWithPath: args[1])) else {
    FileHandle.standardError.write("cannot load \(args[1])\n".data(using: .utf8)!)
    exit(1)
}

let space = CGColorSpace(name: CGColorSpace.sRGB)!
let ctx = CGContext(
    data: nil, width: size, height: size, bitsPerComponent: 8, bytesPerRow: 0,
    space: space, bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue)!
ctx.interpolationQuality = .high
NSGraphicsContext.current = NSGraphicsContext(cgContext: ctx, flipped: false)
image.draw(in: NSRect(x: 0, y: 0, width: size, height: size))
NSGraphicsContext.current = nil

let out = URL(fileURLWithPath: args[2]) as CFURL
let dest = CGImageDestinationCreateWithURL(out, UTType.png.identifier as CFString, 1, nil)!
let props = [kCGImagePropertyPNGDictionary: [kCGImagePropertyPNGInterlaceType: 1]] as CFDictionary
CGImageDestinationAddImage(dest, ctx.makeImage()!, props)
guard CGImageDestinationFinalize(dest) else { exit(1) }
