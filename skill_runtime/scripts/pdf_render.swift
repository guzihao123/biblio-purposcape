// pdf_render.swift — PDFKit 零第三方 PDF 渲染/裁切/取文本后端（macOS 系统框架）。
// 由 pdf_figures.py 在无 PyMuPDF 时编译调用；也可单独使用。
// 用法: pdf_render <pdf> <out.png> [--page N] [--scale S] [--crop-px x,y,w,h] [--text out.txt] [--info]
//   --crop-px 的像素坐标基于「同 --scale 的整页渲染图」，左上角原点。
import Foundation
import CoreGraphics
import PDFKit
import ImageIO

func die(_ m: String) -> Never {
    FileHandle.standardError.write((m + "\n").data(using: .utf8)!)
    exit(1)
}

let args = CommandLine.arguments
guard args.count >= 2 else {
    die("usage: pdf_render <pdf> <out.png> [--page N] [--scale S] [--crop-px x,y,w,h] [--text out.txt] [--info]")
}
let pdfPath = args[1]
var outPath = (args.count > 2 && !args[2].hasPrefix("--")) ? args[2] : ""
var pageIdx = 0
var scale: CGFloat = 2
var cropPx: CGRect? = nil
var textOut: String? = nil
var infoOnly = false
var i = 2
while i < args.count {
    let a = args[i]
    switch a {
    case "--page": pageIdx = Int(args[i + 1]) ?? 0; i += 2
    case "--scale": scale = CGFloat(Double(args[i + 1]) ?? 2); i += 2
    case "--crop-px":
        let p = args[i + 1].split(separator: ",").map { Double($0) ?? 0 }
        if p.count == 4 { cropPx = CGRect(x: p[0], y: p[1], width: p[2], height: p[3]) }
        i += 2
    case "--text": textOut = args[i + 1]; i += 2
    case "--info": infoOnly = true; i += 1
    default: i += 1
    }
}
guard let doc = PDFDocument(url: URL(fileURLWithPath: pdfPath)) else { die("cannot open pdf: \(pdfPath)") }
if infoOnly {
    print("pages=\(doc.pageCount)")
    for j in 0..<doc.pageCount {
        if let pg = doc.page(at: j) {
            let b = pg.bounds(for: .mediaBox)
            print("page \(j): \(Int(b.width))x\(Int(b.height)) pt")
        }
    }
    exit(0)
}
guard let page = doc.page(at: pageIdx) else { die("page out of range: \(pageIdx)") }
let bounds = page.bounds(for: .mediaBox)
if let t = textOut {
    let s = page.string ?? ""
    try? s.write(toFile: t, atomically: true, encoding: .utf8)
}
if outPath.isEmpty { exit(0) }
var rect = bounds
if let cp = cropPx {
    let x = cp.minX / scale
    let w = cp.width / scale
    let h = cp.height / scale
    let y = bounds.height - (cp.minY + cp.height) / scale
    rect = CGRect(x: x, y: y, width: w, height: h)
}
let w = max(1, Int(rect.width * scale))
let h = max(1, Int(rect.height * scale))
let cs = CGColorSpaceCreateDeviceRGB()
guard let ctx = CGContext(data: nil, width: w, height: h, bitsPerComponent: 8,
                          bytesPerRow: 0, space: cs,
                          bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue) else { die("bitmap ctx") }
ctx.setFillColor(CGColor(red: 1, green: 1, blue: 1, alpha: 1))
ctx.fill(CGRect(x: 0, y: 0, width: w, height: h))
ctx.scaleBy(x: scale, y: scale)
ctx.translateBy(x: -rect.minX, y: -rect.minY)
page.draw(with: .mediaBox, to: ctx)
guard let img = ctx.makeImage() else { die("makeImage") }
let url = URL(fileURLWithPath: outPath) as CFURL
guard let dest = CGImageDestinationCreateWithURL(url, "public.png" as CFString, 1, nil) else { die("png dest") }
CGImageDestinationAddImage(dest, img, nil)
if !CGImageDestinationFinalize(dest) { die("write png failed") }
print("ok \(w)x\(h) page=\(pageIdx)")