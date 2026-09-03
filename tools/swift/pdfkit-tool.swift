// pdfkit-tool — PDF text/layout extraction, page rendering, and Vision OCR.
// Pure macOS system frameworks: no Homebrew, no Python packages.
//
//   pdfkit-tool info    <pdf>
//   pdfkit-tool text    <pdf>
//   pdfkit-tool crop    <pdf> <page> <x> <y> <w> <h> <out.png> [--dpi N]
//   pdfkit-tool render  <pdf> <outdir> [--dpi N] [--page N] [--prefix P]
//   pdfkit-tool ocr     <image...>  [--json] [--langcorrect] [--minheight F]

import Foundation
import PDFKit
import Vision
import CoreGraphics
import ImageIO
import UniformTypeIdentifiers
import AppKit

func die(_ m: String) -> Never { FileHandle.standardError.write(("pdfkit-tool: " + m + "\n").data(using: .utf8)!); exit(1) }

func loadDoc(_ path: String) -> PDFDocument {
    guard let d = PDFDocument(url: URL(fileURLWithPath: path)) else { die("cannot open PDF: \(path)") }
    return d
}

func flagValue(_ args: [String], _ name: String) -> String? {
    guard let i = args.firstIndex(of: name), i + 1 < args.count else { return nil }
    return args[i + 1]
}

// MARK: - rendering

func renderPages(doc: PDFDocument, outDir: String, dpi: Double, only: Int?, prefix: String) {
    let fm = FileManager.default
    try? fm.createDirectory(atPath: outDir, withIntermediateDirectories: true)
    let scale = dpi / 72.0
    var written: [String] = []
    for i in 0..<doc.pageCount {
        if let only = only, only != i + 1 { continue }
        guard let page = doc.page(at: i) else { continue }
        let box = page.bounds(for: .mediaBox)
        let w = Int((box.width * scale).rounded()), h = Int((box.height * scale).rounded())
        guard let ctx = CGContext(data: nil, width: w, height: h, bitsPerComponent: 8,
                                  bytesPerRow: 0, space: CGColorSpaceCreateDeviceRGB(),
                                  bitmapInfo: CGImageAlphaInfo.noneSkipLast.rawValue) else { die("bitmap alloc failed") }
        ctx.setFillColor(CGColor(red: 1, green: 1, blue: 1, alpha: 1))
        ctx.fill(CGRect(x: 0, y: 0, width: w, height: h))
        ctx.saveGState()
        ctx.scaleBy(x: scale, y: scale)
        ctx.interpolationQuality = .high
        page.draw(with: .mediaBox, to: ctx)
        ctx.restoreGState()
        guard let img = ctx.makeImage() else { die("makeImage failed") }
        let name = String(format: "%@%03d.png", prefix, i + 1)
        let url = URL(fileURLWithPath: outDir).appendingPathComponent(name)
        guard let dest = CGImageDestinationCreateWithURL(url as CFURL, UTType.png.identifier as CFString, 1, nil) else { die("dest failed") }
        CGImageDestinationAddImage(dest, img, nil)
        CGImageDestinationFinalize(dest)
        written.append(name)
    }
    print(written.joined(separator: "\n"))
}

/// Render one sub-rectangle of a page, given in normalised top-left coordinates.
func cropPage(doc: PDFDocument, pageNo: Int, x: Double, y: Double, w: Double, h: Double,
              out: String, dpi: Double) {
    guard let page = doc.page(at: pageNo - 1) else { die("no page \(pageNo)") }
    let box = page.bounds(for: .mediaBox)
    let rect = CGRect(x: box.minX + box.width * x,
                      y: box.minY + box.height * (1 - y - h),
                      width: box.width * w, height: box.height * h)
    let scale = dpi / 72.0
    let pw = Int((rect.width * scale).rounded()), ph = Int((rect.height * scale).rounded())
    guard pw > 0, ph > 0, let ctx = CGContext(data: nil, width: pw, height: ph,
        bitsPerComponent: 8, bytesPerRow: 0, space: CGColorSpaceCreateDeviceRGB(),
        bitmapInfo: CGImageAlphaInfo.noneSkipLast.rawValue) else { die("bad crop rect") }
    ctx.setFillColor(CGColor(red: 1, green: 1, blue: 1, alpha: 1))
    ctx.fill(CGRect(x: 0, y: 0, width: pw, height: ph))
    ctx.scaleBy(x: scale, y: scale)
    ctx.translateBy(x: -rect.minX, y: -rect.minY)
    ctx.interpolationQuality = .high
    page.draw(with: .mediaBox, to: ctx)
    guard let img = ctx.makeImage(),
          let dest = CGImageDestinationCreateWithURL(URL(fileURLWithPath: out) as CFURL,
                                                     UTType.png.identifier as CFString, 1, nil)
    else { die("crop render failed") }
    CGImageDestinationAddImage(dest, img, nil)
    CGImageDestinationFinalize(dest)
    print(out)
}

/// Draw the app icon: rounded square, wordmark, no external assets.
func makeIcon(size: Int, out: String, maskable: Bool) {
    guard let ctx = CGContext(data: nil, width: size, height: size, bitsPerComponent: 8,
                              bytesPerRow: 0, space: CGColorSpaceCreateDeviceRGB(),
                              bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue)
    else { die("icon bitmap failed") }
    let s = CGFloat(size)
    // Maskable icons get cropped to a circle by the OS, so keep the art inset.
    let inset: CGFloat = maskable ? s * 0.10 : 0
    let box = CGRect(x: inset, y: inset, width: s - inset * 2, height: s - inset * 2)
    ctx.setFillColor(CGColor(red: 0.09, green: 0.10, blue: 0.13, alpha: 1))
    ctx.fill(CGRect(x: 0, y: 0, width: s, height: s))
    let path = CGPath(roundedRect: box, cornerWidth: box.width * 0.22,
                      cornerHeight: box.width * 0.22, transform: nil)
    ctx.addPath(path)
    ctx.setFillColor(CGColor(red: 0.11, green: 0.31, blue: 0.85, alpha: 1))
    ctx.fillPath()

    let nsctx = NSGraphicsContext(cgContext: ctx, flipped: false)
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.current = nsctx
    let title = "SC" as NSString
    let attrs: [NSAttributedString.Key: Any] = [
        .font: NSFont.systemFont(ofSize: box.width * 0.42, weight: .bold),
        .foregroundColor: NSColor.white,
    ]
    let sz = title.size(withAttributes: attrs)
    title.draw(at: CGPoint(x: box.midX - sz.width / 2,
                           y: box.midY - sz.height / 2 + box.width * 0.06),
               withAttributes: attrs)
    let sub = "午前II" as NSString
    let sattrs: [NSAttributedString.Key: Any] = [
        .font: NSFont.systemFont(ofSize: box.width * 0.15, weight: .semibold),
        .foregroundColor: NSColor(white: 1, alpha: 0.85),
    ]
    let ssz = sub.size(withAttributes: sattrs)
    sub.draw(at: CGPoint(x: box.midX - ssz.width / 2, y: box.minY + box.width * 0.12),
             withAttributes: sattrs)
    NSGraphicsContext.restoreGraphicsState()

    guard let img = ctx.makeImage(),
          let dest = CGImageDestinationCreateWithURL(URL(fileURLWithPath: out) as CFURL,
                                                     UTType.png.identifier as CFString, 1, nil)
    else { die("icon write failed") }
    CGImageDestinationAddImage(dest, img, nil)
    CGImageDestinationFinalize(dest)
    print(out)
}

// MARK: - Vision OCR

struct OCRLine: Codable { let text: String; let conf: Float; let x: Double; let y: Double; let w: Double; let h: Double }
struct OCRPage: Codable { let file: String; let width: Int; let height: Int; let lines: [OCRLine] }

func ocr(paths: [String], asJSON: Bool, langCorrect: Bool, minHeight: Float) {
    var pages: [OCRPage] = []
    for p in paths {
        guard let src = CGImageSourceCreateWithURL(URL(fileURLWithPath: p) as CFURL, nil),
              let img = CGImageSourceCreateImageAtIndex(src, 0, nil) else { die("cannot read image: \(p)") }
        let req = VNRecognizeTextRequest()
        req.recognitionLevel = .accurate
        req.recognitionLanguages = ["ja-JP", "en-US"]
        req.usesLanguageCorrection = langCorrect
        if minHeight > 0 { req.minimumTextHeight = minHeight }
        if #available(macOS 13.0, *) { req.revision = VNRecognizeTextRequestRevision3 }
        let handler = VNImageRequestHandler(cgImage: img, options: [:])
        do { try handler.perform([req]) } catch { die("Vision failed on \(p): \(error)") }
        let obs = (req.results ?? [])
        var lines: [OCRLine] = []
        for o in obs {
            guard let top = o.topCandidates(1).first else { continue }
            let bb = o.boundingBox   // normalised, origin bottom-left
            lines.append(OCRLine(text: top.string, conf: top.confidence,
                                 x: Double(bb.minX), y: Double(1 - bb.maxY),
                                 w: Double(bb.width), h: Double(bb.height)))
        }
        // Reading order: top-to-bottom, then left-to-right within a band.
        lines.sort { a, b in
            let band = max(a.h, b.h) * 0.6
            if abs(a.y - b.y) > band { return a.y < b.y }
            return a.x < b.x
        }
        pages.append(OCRPage(file: p, width: img.width, height: img.height, lines: lines))
    }
    if asJSON {
        let enc = JSONEncoder(); enc.outputFormatting = [.prettyPrinted, .withoutEscapingSlashes]
        print(String(data: try! enc.encode(pages), encoding: .utf8)!)
    } else {
        for pg in pages {
            if paths.count > 1 { print("=== \(pg.file) ===") }
            print(pg.lines.map { $0.text }.joined(separator: "\n"))
        }
    }
}

// MARK: - main

let argv = Array(CommandLine.arguments.dropFirst())
guard let cmd = argv.first else { die("usage: pdfkit-tool <info|text|render|crop|ocr|icon> ...") }
let rest = Array(argv.dropFirst())
let positional = { () -> [String] in
    var out: [String] = []; var i = 0
    while i < rest.count {
        if rest[i].hasPrefix("--") {
            if ["--json", "--langcorrect"].contains(rest[i]) { i += 1 } else { i += 2 }
        } else { out.append(rest[i]); i += 1 }
    }
    return out
}()

switch cmd {
case "info":
    let doc = loadDoc(positional[0])
    var per: [[String: Int]] = []
    for i in 0..<doc.pageCount {
        let s = doc.page(at: i)?.string ?? ""
        let b = doc.page(at: i)?.bounds(for: .mediaBox) ?? .zero
        per.append(["page": i + 1, "chars": s.count, "w": Int(b.width), "h": Int(b.height)])
    }
    let total = per.reduce(0) { $0 + ($1["chars"] ?? 0) }
    let obj: [String: Any] = ["path": positional[0], "pageCount": doc.pageCount, "totalChars": total, "pages": per]
    print(String(data: try! JSONSerialization.data(withJSONObject: obj, options: [.prettyPrinted]), encoding: .utf8)!)

case "text":
    let doc = loadDoc(positional[0])
    var parts: [String] = []
    for i in 0..<doc.pageCount { parts.append(doc.page(at: i)?.string ?? "") }
    print(parts.joined(separator: "\u{0C}\n"))

case "icon":
    guard positional.count >= 2 else { die("icon needs <size> <out.png>") }
    makeIcon(size: Int(positional[0]) ?? 192, out: positional[1],
             maskable: rest.contains("--maskable"))

case "crop":
    guard positional.count >= 7 else { die("crop needs <pdf> <page> <x> <y> <w> <h> <out.png>") }
    func d(_ v: String) -> Double? { Double(v) }
    cropPage(doc: loadDoc(positional[0]), pageNo: Int(positional[1]) ?? 1,
             x: d(positional[2]) ?? 0, y: d(positional[3]) ?? 0,
             w: d(positional[4]) ?? 1, h: d(positional[5]) ?? 1,
             out: positional[6], dpi: d(flagValue(rest, "--dpi") ?? "300") ?? 300)

case "render":
    guard positional.count >= 2 else { die("render needs <pdf> <outdir>") }
    let doc = loadDoc(positional[0])
    let dpi = Double(flagValue(rest, "--dpi") ?? "400") ?? 400
    let only = flagValue(rest, "--page").flatMap { Int($0) }
    renderPages(doc: doc, outDir: positional[1], dpi: dpi, only: only,
                prefix: flagValue(rest, "--prefix") ?? "page-")

case "ocr":
    guard !positional.isEmpty else { die("ocr needs at least one image") }
    ocr(paths: positional, asJSON: rest.contains("--json"),
        langCorrect: rest.contains("--langcorrect"),
        minHeight: Float(flagValue(rest, "--minheight") ?? "0") ?? 0)

default: die("unknown command: \(cmd)")
}
