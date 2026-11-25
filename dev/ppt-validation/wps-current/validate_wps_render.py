from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from datetime import datetime
from pathlib import Path

import pypdfium2 as pdfium
from PIL import Image, ImageDraw, ImageStat
from pptx import Presentation


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalized(value: str) -> str:
    return re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]", "", value).lower()


def contact_sheet(paths: list[Path], output: Path) -> None:
    columns = 3
    thumb_width, thumb_height, label_height = 480, 270, 28
    rows = (len(paths) + columns - 1) // columns
    sheet = Image.new("RGB", (columns * thumb_width, rows * (thumb_height + label_height)), "#20242b")
    draw = ImageDraw.Draw(sheet)
    for index, path in enumerate(paths):
        with Image.open(path) as source:
            image = source.convert("RGB")
        image.thumbnail((thumb_width, thumb_height), Image.Resampling.LANCZOS)
        x = (index % columns) * thumb_width
        y = (index // columns) * (thumb_height + label_height)
        sheet.paste(image, (x, y))
        draw.text((x + 10, y + thumb_height + 7), f"Page {index + 1}", fill="white")
    sheet.save(output, optimize=True)


def main() -> None:
    here = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser()
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--pptx", type=Path, default=here / "肝细胞癌免疫治疗耐药机制组会汇报.pptx")
    parser.add_argument("--ocr", type=Path, default=here.parent / "tools" / "ocr_image")
    parser.add_argument("--output-dir", type=Path, default=here)
    parser.add_argument(
        "--render-method",
        default="WPS Office full-document PDF export; pypdfium2 rasterization and local macOS OCR",
    )
    args = parser.parse_args()
    pdf_path = args.pdf.resolve()
    pptx_path = args.pptx.resolve()
    if not pdf_path.is_file():
        raise SystemExit(f"WPS PDF not found: {pdf_path}")
    if not args.ocr.is_file():
        raise SystemExit(f"Local OCR tool not found: {args.ocr}")

    source_hash_before = sha256(pptx_path)
    expected_pages = len(Presentation(pptx_path).slides)
    document = pdfium.PdfDocument(str(pdf_path))
    if len(document) != expected_pages:
        raise SystemExit(f"Page mismatch: PPTX={expected_pages}, pypdfium2={len(document)}")

    work_dir = args.output_dir.resolve()
    work_dir.mkdir(parents=True, exist_ok=True)
    output = work_dir / "rendered"
    output.mkdir(exist_ok=True)
    critical = {
        3: ["研究背景与科学问题", "研究对象", "方法", "证据", "决策", "作用链条"],
        6: ["年度趋势", "文献数", "2024", "2025"],
        7: ["主题分布", "文献数", "髓系代谢", "动态分层", "乳酸化", "免疫微环境"],
        12: ["核心方法与技术路线", "输入", "方法", "验证", "输出"],
        22: ["发展趋势", "潜在突破"],
        25: ["参考文献"],
    }
    page_records = []
    page_paths = []
    failures = []
    for index in range(expected_pages):
        page_number = index + 1
        page = document[index]
        pdf_text = page.get_textpage().get_text_bounded()
        image = page.render(scale=2.0).to_pil().convert("RGB")
        page_path = output / f"page-{page_number:02d}.png"
        image.save(page_path, optimize=True)
        page_paths.append(page_path)
        ocr_result = subprocess.run(
            [str(args.ocr), str(page_path)], capture_output=True, text=True, check=False,
        )
        ocr_text = ocr_result.stdout
        if ocr_result.returncode:
            failures.append(f"page {page_number}: OCR exit {ocr_result.returncode}: {ocr_result.stderr.strip()}")
        expected = critical.get(page_number, [])
        missing_pdf = [label for label in expected if normalized(label) not in normalized(pdf_text)]
        missing_ocr = [label for label in expected if normalized(label) not in normalized(ocr_text)]
        grayscale = image.convert("L")
        stats = ImageStat.Stat(grayscale)
        if stats.stddev[0] < 3:
            failures.append(f"page {page_number}: blank or nearly blank raster")
        if missing_pdf:
            failures.append(f"page {page_number}: PDF text missing {missing_pdf}")
        if missing_ocr:
            failures.append(f"page {page_number}: raster OCR missing {missing_ocr}")
        (output / f"page-{page_number:02d}.ocr.txt").write_text(ocr_text, encoding="utf-8")
        page_records.append({
            "page": page_number,
            "pdf_points": list(page.get_size()),
            "pixels": list(image.size),
            "png_sha256": sha256(page_path),
            "grayscale_stddev": round(stats.stddev[0], 3),
            "pdf_cjk_characters": sum("\u4e00" <= char <= "\u9fff" for char in pdf_text),
            "pdf_replacement_characters": pdf_text.count("\ufffd"),
            "ocr_cjk_characters": sum("\u4e00" <= char <= "\u9fff" for char in ocr_text),
            "critical_labels": expected,
            "missing_pdf_labels": missing_pdf,
            "missing_ocr_labels": missing_ocr,
        })

    sheets = []
    for start in range(0, expected_pages, 12):
        end = min(start + 12, expected_pages)
        sheet_path = work_dir / f"contact-sheet-{start + 1:02d}-{end:02d}.png"
        contact_sheet(page_paths[start:end], sheet_path)
        sheets.append({"path": sheet_path.name, "sha256": sha256(sheet_path)})
    source_hash_after = sha256(pptx_path)
    if source_hash_after != source_hash_before:
        failures.append("source PPTX changed during rendering")
    report = {
        "created_at": datetime.now().astimezone().isoformat(),
        "render_method": args.render_method,
        "source_pptx": str(pptx_path),
        "source_pptx_sha256_before": source_hash_before,
        "source_pptx_sha256_after": source_hash_after,
        "source_pdf": str(pdf_path),
        "source_pdf_sha256": sha256(pdf_path),
        "pdf_metadata": document.get_metadata_dict(),
        "expected_pages": expected_pages,
        "rendered_pages": len(page_records),
        "contact_sheets": sheets,
        "automated_result": "failed" if failures else "passed",
        "failures": failures,
        "visual_review_boundary": "Automated raster/OCR checks do not replace manual visual inspection or LibreOffice/PowerPoint rendering.",
        "pages": page_records,
    }
    (work_dir / "validation.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "pages"}, ensure_ascii=False, indent=2))
    raise SystemExit(1 if failures else 0)


if __name__ == "__main__":
    main()
