#!/usr/bin/env python3
"""pdf_figures.py — PDF 图/全文提取 helper（模式 D 增强；第 4.5 步配套，2026-11-22 增）。

后端优先 PyMuPDF(fitz)，无则回退 macOS PDFKit（Swift，scripts/pdf_render.swift 自动编译，零第三方）。
仅处理开放获取 PDF（oa_pdf.py 下载）或用户自有 PDF；不绕过付费墙。
读图/读全文后写入交付物须标"已读全文"及实际版本（预印本/接收稿/正式版）。

子命令：
  info                                  页数与页面尺寸
  render --page N --scale S --out PNG   整页渲染（默认 page=0 scale=2）
  crop   --page N --scale S --px x,y,w,h --out PNG   裁切图区（px 基于同 scale 整页渲染图，左上角原点）
  text   --page N [--all] [--no-page-marks] --out TXT
                                        取文本（--all 取全文，默认插 === page N === 锚点供全文证据链引用）
  images --out DIR [--min-size 200]     抽内嵌位图（仅 PyMuPDF；矢量框架图请用 render+crop）

用法示例：
  python3 pdf_figures.py paper.pdf info
  python3 pdf_figures.py paper.pdf render --page 2 --scale 2 --out p3.png
  python3 pdf_figures.py paper.pdf crop --page 2 --scale 2 --px 120,300,900,520 --out fig1.png
  python3 pdf_figures.py paper.pdf text --all --out fulltext.txt
  python3 pdf_figures.py article.xml xmltext --out fulltext.txt   # Europe PMC JATS XML 取全文
"""
import argparse
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SWIFT_SRC = os.path.join(HERE, "pdf_render.swift")
SWIFT_BIN = os.path.join(HERE, "pdf_render")


def have_fitz():
    try:
        import fitz  # noqa: F401
        return True
    except Exception:
        return False


def ensure_swift():
    if not os.path.exists(SWIFT_BIN) or os.path.getmtime(SWIFT_SRC) > os.path.getmtime(SWIFT_BIN):
        r = subprocess.run(["swiftc", "-O", SWIFT_SRC, "-o", SWIFT_BIN],
                           capture_output=True, text=True)
        if r.returncode != 0:
            sys.exit("swiftc 编译失败（需 macOS + Xcode CLT）:\n" + r.stderr)
    return SWIFT_BIN


def run_swift(args):
    r = subprocess.run([ensure_swift()] + args, capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit("pdf_render 失败:\n" + (r.stderr or r.stdout))
    return r.stdout.strip()


def parse_px(s):
    p = [float(x) for x in s.split(",")]
    if len(p) != 4:
        sys.exit("--px 需 x,y,w,h 四个数")
    return p


def main():
    ap = argparse.ArgumentParser(description="PDF 图/全文提取（PyMuPDF 优先，PDFKit 回退）")
    ap.add_argument("pdf")
    ap.add_argument("command", choices=["info", "render", "crop", "text", "images", "xmltext"])
    ap.add_argument("--page", type=int, default=0)
    ap.add_argument("--scale", type=float, default=2.0)
    ap.add_argument("--px", help="x,y,w,h（同 scale 整页图像素，左上原点）")
    ap.add_argument("--out", help="输出文件/目录")
    ap.add_argument("--all", action="store_true", help="text 取全文")
    ap.add_argument("--no-page-marks", action="store_true",
                    help="text --all 不插 === page N === 锚点（默认插，供全文证据链定位）")
    ap.add_argument("--min-size", type=int, default=200, help="images 最小边长过滤")
    a = ap.parse_args()

    if not os.path.exists(a.pdf):
        sys.exit("文件不存在: " + a.pdf)

    if a.command == "xmltext":
        # Europe PMC JATS XML → 带章节锚点的纯文本（XML 无真实页码，用 sec 名定位）
        import html
        import re
        raw = open(a.pdf, encoding="utf-8").read()
        raw = re.sub(r"<(table-wrap|inline-formula|disp-formula)\b[^>]*>.*?</\1>", " ", raw, flags=re.S)
        raw = re.sub(r"<sec\b[^>]*>\s*<title>(.*?)</title>",
                     lambda m: "@@SEC@@" + m.group(1) + "@@END@@", raw, flags=re.S)
        txt = html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", raw))).strip()
        txt = re.sub(r"@@SEC@@(.*?)@@END@@", r"\n\n=== sec \1 ===\n", txt)
        with open(a.out, "w", encoding="utf-8") as f:
            f.write(txt)
        print("ok chars=%d secs=%d -> %s" % (
            len(txt), txt.count("=== sec "), a.out))
        return

    fitz = have_fitz()
    backend = "PyMuPDF" if fitz else "PDFKit(Swift)"
    print("backend=" + backend)

    if fitz:
        import fitz
        doc = fitz.open(a.pdf)
        if a.command == "info":
            print("pages=%d" % len(doc))
            for i, pg in enumerate(doc):
                r = pg.rect
                print("page %d: %dx%d pt" % (i, int(r.width), int(r.height)))
        elif a.command == "render":
            pg = doc[a.page]
            pix = pg.get_pixmap(matrix=fitz.Matrix(a.scale, a.scale))
            pix.save(a.out)
            print("ok %dx%d page=%d -> %s" % (pix.width, pix.height, a.page, a.out))
        elif a.command == "crop":
            x, y, w, h = parse_px(a.px)
            clip = fitz.Rect(x / a.scale, y / a.scale, (x + w) / a.scale, (y + h) / a.scale)
            pix = doc[a.page].get_pixmap(matrix=fitz.Matrix(a.scale, a.scale), clip=clip)
            pix.save(a.out)
            print("ok %dx%d page=%d -> %s" % (pix.width, pix.height, a.page, a.out))
        elif a.command == "text":
            if a.all:
                if a.no_page_marks:
                    txt = "\n\n".join(pg.get_text() for pg in doc)
                else:
                    txt = "\n\n".join("=== page %d ===\n%s" % (i + 1, pg.get_text())
                                      for i, pg in enumerate(doc))
            else:
                txt = doc[a.page].get_text()
            with open(a.out, "w", encoding="utf-8") as f:
                f.write(txt)
            print("ok chars=%d -> %s" % (len(txt), a.out))
        elif a.command == "images":
            os.makedirs(a.out, exist_ok=True)
            seen, n = set(), 0
            for i in range(len(doc)):
                for img in doc.get_page_images(i, full=True):
                    xref = img[0]
                    if xref in seen:
                        continue
                    seen.add(xref)
                    d = doc.extract_image(xref)
                    if min(d.get("width", 0), d.get("height", 0)) < a.min_size:
                        continue
                    fn = os.path.join(a.out, "p%d_x%d.%s" % (i + 1, xref, d["ext"]))
                    with open(fn, "wb") as f:
                        f.write(d["image"])
                    print("saved %s (%dx%d)" % (fn, d["width"], d["height"]))
                    n += 1
            print("images=%d（矢量图未含，请用 render+crop）" % n)
        return

    # PDFKit 回退
    if a.command == "info":
        print(run_swift([a.pdf, "--info"]))
    elif a.command == "render":
        print(run_swift([a.pdf, a.out, "--page", str(a.page), "--scale", str(a.scale)]))
    elif a.command == "crop":
        print(run_swift([a.pdf, a.out, "--page", str(a.page), "--scale", str(a.scale),
                         "--crop-px", a.px]))
    elif a.command == "text":
        if a.all:
            n = int(run_swift([a.pdf, "--info"]).splitlines()[0].split("=")[1])
            parts = []
            for i in range(n):
                tmp = a.out + ".p%d" % i
                run_swift([a.pdf, "--text", tmp, "--page", str(i)])
                with open(tmp, encoding="utf-8") as f:
                    parts.append(f.read())
                os.remove(tmp)
            if a.no_page_marks:
                txt = "\n\n".join(parts)
            else:
                txt = "\n\n".join("=== page %d ===\n%s" % (i + 1, p) for i, p in enumerate(parts))
            with open(a.out, "w", encoding="utf-8") as f:
                f.write(txt)
            print("ok chars=%d -> %s" % (len(txt), a.out))
        else:
            print(run_swift([a.pdf, "--text", a.out, "--page", str(a.page)]))
    elif a.command == "images":
        sys.exit("images 需 PyMuPDF（python3 -m pip install --user pymupdf）；"
                 "矢量框架图请用 render+crop 拿。")


if __name__ == "__main__":
    main()