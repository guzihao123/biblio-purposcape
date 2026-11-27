"""D-mode original-figure acquisition and slide/manifest planning.

The module deliberately keeps the writing/cards layer untouched.  It only:
1. resolves OA full text through ``FullTextService`` / ``oa_pdf.py``;
2. uses the copied ``skill_runtime/scripts/pdf_figures.py`` for PDF render/crop;
3. falls back to the Europe PMC JATS figure package when the PDF is blocked;
4. writes ``figures/ref<n>_fig<k>_<name>.png`` and an acquisition log.

No image is ever drawn or synthesized by this module.
"""

from __future__ import annotations

import io
import json
import os
import re
import shutil
import subprocess
import sys
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse
from xml.etree import ElementTree as ET

from PIL import Image, ImageChops, ImageOps

from app.fulltext import FullTextService, read_pdf_pages


PROJECT_ROOT = Path(__file__).resolve().parents[2]
PDF_FIGURES = PROJECT_ROOT / "skill_runtime" / "scripts" / "pdf_figures.py"
EUROPEPMC_API = "https://www.ebi.ac.uk/europepmc/webservices/rest"
XLINK_HREF = "{http://www.w3.org/1999/xlink}href"

CAPTION_RE = re.compile(
    r"^\s*(?:figure|fig\.?|图)\s*([0-9]+[A-Za-z]?)\s*[\.:：|]?\s*(.*)$",
    re.IGNORECASE,
)
PAGE_ANCHOR_RE = re.compile(r"(?m)^=== page\s+(\d+)\s+===\s*$")
PMC_RE = re.compile(r"PMC\d+", re.IGNORECASE)
SLOT_KEYWORDS = (
    ("concept", ("overview", "microenvironment", "landscape", "conceptual", "framework", "network", "axis")),
    ("method", ("study design", "workflow", "pipeline", "schematic", "experimental design")),
    ("architecture", ("binds", "ubiquitin", "degradation", "phosphorylat", "mechanism", "pathway", "signaling", "complex", "structure", "transcription", "effector", "attenuat", "mediates", "drives", "activation of", "modulates", "reprograms", "regulat")),
    ("comparison", ("comparison", "compared", "cohort", "patients", "clinical", "trial", "survival", "response", "associated with", "outcome")),
)
BREAKTHROUGH_START = ("blocking", "blockade", "inhibition of", "combination", "combined treatment", "treatment with", "targeting")
BREAKTHROUGH_ANY = ("enhanced anti-tumor", "enhanced antitumor", "sensitiz", "eradicat", "overcome", "restores")
SLOT_NAMES = {
    "concept": "概念框架",
    "method": "研究设计",
    "architecture": "机制模型",
    "comparison": "临床比较",
    "breakthrough": "治疗验证",
    "reading": "结果图",
}


def _normalized(value):
    return " ".join(str(value or "").split())


def _local_name(tag):
    return str(tag).rsplit("}", 1)[-1]


def _figure_number(label, href=""):
    match = re.search(r"([0-9]+[A-Za-z]?)", str(label or ""))
    if match:
        return match.group(1)
    match = re.search(r"(?:g|fig(?:ure)?)[-_]?([0-9]+[A-Za-z]?)", str(href or ""), re.IGNORECASE)
    return match.group(1) if match else ""


def _safe_name(text, fallback):
    cleaned = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "_", _normalized(text)).strip("_")
    return (cleaned[:24].strip("_") or fallback).lower() if cleaned else fallback


def _lead_sentence(caption):
    """Caption text before the first panel marker such as ``(A)``/``(a–c)``."""

    full = _normalized(caption)
    lead = re.split(r"\(\s*[aA](?=[\s\)\u2013\u2014,\-])", full, maxsplit=1)[0]
    return lead.casefold()


def _short_name(caption, fig_no):
    return SLOT_NAMES.get(_slot_for_caption(caption), f"fig{fig_no}" if fig_no else "figure")


def _slot_for_caption(caption):
    full = _normalized(caption).casefold()
    lead = _lead_sentence(caption)
    if lead.startswith(("overview", "an overview", "conceptual")) or "immune microenvironment" in lead or "immunosuppressive cells" in lead:
        return "concept"
    if lead.startswith(("predicted model", "a schematic model", "schematic model", "proposed model")):
        return "architecture"
    if "study design" in full[:200] and not any(keyword in lead for keyword in BREAKTHROUGH_START):
        return "method"
    if lead.startswith(BREAKTHROUGH_START):
        return "breakthrough"
    for slot, keywords in SLOT_KEYWORDS:
        if slot == "method":
            continue
        if any(keyword in lead for keyword in keywords):
            return slot
    if any(keyword in lead for keyword in BREAKTHROUGH_ANY):
        return "breakthrough"
    return "reading"


def _pdf_backend():
    """Return the renderer that ``pdf_figures.py`` will actually use."""
    forced = os.environ.get("PDF_FIGURES_BACKEND", "").strip().lower()
    try:
        import fitz  # noqa: F401
        if forced != "pdfium":
            return "PyMuPDF"
    except Exception:
        pass
    try:
        import pypdfium2  # noqa: F401
        if forced != "swift":
            return "pypdfium2"
    except Exception:
        pass
    return "PDFKit(Swift)"


def _has_oa_hint(paper):
    """Only auto-start network work when the paper carries an OA clue.

    A DOI-only record can still be resolved by the CLI, but the delivery path
    must stay fast and offline-safe for synthetic/test papers.  Callers that
    want DOI-only resolution can pass an explicitly configured service.
    """

    for key in ("oa_url", "pdf_url", "open_access", "best_oa_location", "is_oa"):
        value = paper.get(key)
        if isinstance(value, dict):
            if any(value.get(k) for k in ("oa_url", "pdf_url", "is_oa", "landing_page_url")):
                return True
        elif value:
            return True
    return False


@dataclass
class FigureAsset:
    ref_no: int
    fig_no: str
    name: str
    path: Path
    caption: str
    description: str
    source_url: str
    version: str
    original_page: str
    acquisition: str
    slot: str = "reading"
    asset_url: str = ""
    crop_mode: str = ""
    crop_meta: dict = field(default_factory=dict)

    def caption_line(self):
        page = self.original_page or "【待核实】"
        version = self.version or "未确认"
        return f"[{self.ref_no}] Fig.{self.fig_no}，原文 p{page}，{version} OA 版本"

    def manifest_entry(self, slide_page, relative_to):
        try:
            source = str(self.path.resolve().relative_to(Path(relative_to).resolve()))
        except ValueError:
            source = str(self.path)
        entry = {
            "page": slide_page,
            "kind": "image",
            "name": self.caption_line(),
            "source": source,
            "oa_url": self.source_url,
            "ref_no": self.ref_no,
            "figure_no": f"Fig.{self.fig_no}",
            "original_page": self.original_page,
            "version": self.version,
            "acquisition": self.acquisition,
            "caption": self.caption,
            "description": self.description,
            "slot": self.slot,
        }
        if self.asset_url:
            entry["asset_url"] = self.asset_url
        return entry


@dataclass
class FigureBundle:
    assets: list = field(default_factory=list)
    attempts: list = field(default_factory=list)

    def by_ref(self, ref_no):
        return [asset for asset in self.assets if asset.ref_no == int(ref_no)]

    def pick(self, slot, preferred_ref=None, exclude=()):
        candidates = [asset for asset in self.assets if asset.path not in set(exclude)]
        if preferred_ref is not None:
            preferred = [asset for asset in candidates if asset.ref_no == int(preferred_ref) and asset.slot == slot]
            if preferred:
                return preferred[0]
        for asset in candidates:
            if asset.slot == slot:
                return asset
        return None

    def degraded_for_ref(self, ref_no):
        for attempt in self.attempts:
            if attempt.get("ref_no") == int(ref_no):
                return attempt
        return None


@dataclass
class _LocalFulltext:
    """Minimal ``FullTextResult``-shaped object for a cached local document."""

    source_path: Path
    source_url: str = ""
    version: str = "正式版"
    depth: str = "已读全文"
    failures: list = field(default_factory=list)


def _trim_white(path):
    """Trim uniform white margins introduced by PDF page-object crops."""

    try:
        image = Image.open(path).convert("RGB")
        background = Image.new("RGB", image.size, (255, 255, 255))
        difference = ImageChops.difference(image, background).convert("L")
        bbox = difference.point(lambda value: 255 if value > 12 else 0).getbbox()
        if bbox and bbox != (0, 0, image.width, image.height):
            image = image.crop(bbox)
        image.save(path, format="PNG", optimize=True)
    except Exception:
        return path
    return path


def _normalize_png(source, destination, max_width=1800):
    image = Image.open(source)
    if getattr(image, "n_frames", 1) > 1:
        image.seek(0)
    image = ImageOps.exif_transpose(image)
    if image.mode not in {"RGB", "RGBA"}:
        image = image.convert("RGB")
    if image.width > max_width:
        ratio = max_width / float(image.width)
        image = image.resize((max_width, max(1, int(image.height * ratio))), Image.LANCZOS)
    destination.parent.mkdir(parents=True, exist_ok=True)
    image.save(destination, format="PNG", optimize=True)
    return destination


TABLE_CAPTION_RE = re.compile(r"^\s*(?:table|tab\.?|表)\s*[0-9]+", re.IGNORECASE)
TABLE_HEADER_WORDS = (
    "used dataset", "crash type", "records no", "analysis period", "severity levels",
    "methodology", "key findings", "input factors", "age groups", "study used",
)


def _looks_like_table_header(text):
    """Cheap, conservative guard against absorbing a table header into a caption."""

    lowered = _normalized(text).casefold()
    return sum(1 for word in TABLE_HEADER_WORDS if word in lowered) >= 2


def _figure_caption_from_lines(lines, match_index):
    pieces = [lines[match_index].strip()]
    for line in lines[match_index + 1:match_index + 3]:
        stripped = line.strip()
        if not stripped or CAPTION_RE.match(stripped) or TABLE_CAPTION_RE.match(stripped):
            break
        if _looks_like_table_header(stripped):
            break
        pieces.append(stripped)
    return _normalized(" ".join(pieces))


def _largest_object_bbox(pdf_path, page_index):
    """Return the largest non-background page-object box in PDF points."""

    import pypdfium2 as pdfium

    document = pdfium.PdfDocument(str(pdf_path))
    try:
        page = document[page_index]
        try:
            page_width, page_height = page.get_size()
            page_area = page_width * page_height
            best = None
            for obj in page.get_objects():
                try:
                    x0, y0, x1, y1 = obj.get_pos()
                except Exception:
                    continue
                width = x1 - x0
                height = y1 - y0
                if width < page_width * 0.2 or height < page_height * 0.1:
                    continue
                if width * height > page_area * 0.92:
                    continue
                if best is None or width * height > best[2] * best[3]:
                    best = (x0, y0, x1, y1)
            if best:
                return best, page_width, page_height
            try:
                import fitz
            except ImportError:
                fitz = None
            if fitz is not None:
                pdf = fitz.open(str(pdf_path))
                try:
                    pdf_page = pdf[page_index]
                    best_area = 0
                    best_rect = None
                    for image in pdf_page.get_images(full=True):
                        try:
                            rect = pdf_page.get_image_bbox(image)
                        except Exception:
                            continue
                        area = rect.width * rect.height
                        if area > best_area:
                            best_area = area
                            best_rect = rect
                    if best_rect is not None:
                        return (
                            best_rect.x0,
                            page_height - best_rect.y1,
                            best_rect.x1,
                            page_height - best_rect.y0,
                        ), page_width, page_height
                finally:
                    pdf.close()
        finally:
            page.close()
    finally:
        document.close()
    return None, 0, 0


def _page_graphic_boxes(pdf_path, page_index):
    """Collect graphic object boxes on a page, in PDF points (y from bottom).

    Only image (type 3) and path (type 2) objects are considered.  Thin rules,
    footer/header strips and sub-pixel decorations are dropped so they cannot
    be mistaken for figure artwork.
    """

    import pypdfium2 as pdfium

    document = pdfium.PdfDocument(str(pdf_path))
    try:
        page = document[page_index]
        try:
            page_width, page_height = page.get_size()
            boxes = []
            for obj in page.get_objects():
                if obj.type not in (2, 3):
                    continue
                try:
                    x0, y0, x1, y1 = obj.get_pos()
                except Exception:
                    continue
                box_width, box_height = x1 - x0, y1 - y0
                if box_width < page_width * 0.03 or box_height < page_height * 0.01:
                    continue
                if box_height < 5 and box_width > page_width * 0.4:
                    continue
                if y0 > page_height * 0.94 and box_height < page_height * 0.05:
                    continue
                boxes.append((x0, y0, x1, y1))
            return boxes, page_width, page_height
        finally:
            page.close()
    finally:
        document.close()


def _caption_anchor_in_pdf(pdf_path, page_index, caption):
    """Return ``(left, top, right)`` of the caption anchor, in PDF coordinates."""

    import pypdfium2 as pdfium

    token = _normalized(caption)[:9]
    if not token:
        return None
    document = pdfium.PdfDocument(str(pdf_path))
    try:
        page = document[page_index]
        try:
            text_page = page.get_textpage()
            try:
                searcher = text_page.search(token)
                occurrence = searcher.get_next()
                if occurrence is None:
                    return None
                index, _count = occurrence
                x0, y0, x1, y1 = text_page.get_charbox(index)
                return (x0, y1, x1)
            finally:
                text_page.close()
        finally:
            page.close()
    finally:
        document.close()


def _column_aware_crop_pixels(pdf_path, page_index, caption, scale=2.0):
    """Locate a figure from its caption anchor plus nearby graphic objects.

    The crop is bounded by the actual artwork: its left/right edges come from
    the graphic cluster sharing the caption's column, and its top edge comes
    from the cluster's top instead of a fixed page margin.  When no reliable
    boundary exists the function degrades instead of guessing a full-width
    band, so a right-column body text or a table above the figure can never be
    silently pulled into the crop.

    Returns ``(px, meta)`` where ``px`` is ``(x, y, w, h)`` at ``scale`` or
    ``None``.  ``meta`` records the decision for the acquisition log.
    """

    anchor = _caption_anchor_in_pdf(pdf_path, page_index, caption)
    if anchor is None:
        return None, {"mode": "degraded", "reason": "图注锚点未在文本层定位"}
    caption_left, caption_top, caption_right = anchor
    boxes, page_width, page_height = _page_graphic_boxes(pdf_path, page_index)
    if not boxes:
        return None, {"mode": "degraded", "reason": "页面无可用图形对象"}

    vertical_tolerance = page_height * 0.02
    # Captions often start at the column's left edge while a wide figure is
    # centred on the page.  A quarter-page tolerance covers that offset but
    # still excludes graphics in the opposite column.
    horizontal_tolerance = page_width * 0.25
    max_gap = page_height * 0.55
    cluster_gap = page_height * 0.08
    candidates = [
        box
        for box in boxes
        if box[1] >= caption_top - vertical_tolerance
        and box[2] >= caption_left - horizontal_tolerance
        and box[0] <= caption_right + horizontal_tolerance
        and box[1] - caption_top <= max_gap
    ]
    if not candidates:
        return None, {
            "mode": "degraded",
            "reason": "图注上方同列无可靠图形对象",
            "caption_top": round(caption_top, 1),
        }

    # Seed with the artwork closest above the caption, then merge graphic
    # objects that touch it vertically and overlap horizontally.  This keeps
    # a multi-panel vector figure in one cluster while excluding a table that
    # sits well above the artwork or a second figure in the other column.
    seed = min(candidates, key=lambda box: box[1])
    cluster = [seed]
    cx0, cy0, cx1, cy1 = seed
    changed = True
    while changed:
        changed = False
        for box in boxes:
            if box in cluster:
                continue
            x0, y0, x1, y1 = box
            if x1 < cx0 - horizontal_tolerance or x0 > cx1 + horizontal_tolerance:
                continue
            if y0 > cy1 + cluster_gap or y1 < cy0 - cluster_gap:
                continue
            cluster.append(box)
            cx0, cx1 = min(cx0, x0), max(cx1, x1)
            cy0, cy1 = min(cy0, y0), max(cy1, y1)
            changed = True

    left = max(0.0, cx0 - 3.0)
    right = min(page_width, cx1 + 3.0)
    top_pdf = min(page_height, cy1 + 3.0)
    bottom_pdf = max(0.0, caption_top - 2.0)
    if (top_pdf - bottom_pdf) < page_height * 0.06 or (right - left) < page_width * 0.12:
        return None, {
            "mode": "degraded",
            "reason": "图区高度或宽度不足，拒绝整栏裁切",
            "caption_top": round(caption_top, 1),
        }
    px = (
        round(left * scale, 2),
        round((page_height - top_pdf) * scale, 2),
        round((right - left) * scale, 2),
        round((top_pdf - bottom_pdf) * scale, 2),
    )
    meta = {
        "mode": "column_aware",
        "graphic_box": [round(value, 1) for value in (cx0, cy0, cx1, cy1)],
        "caption_top": round(caption_top, 1),
        "caption_gap": round(cy0 - caption_top, 1),
        "cluster_objects": len(cluster),
    }
    return px, meta


def _embedded_image_for_caption(pdf_path, page_index, caption, destination, previous_reason=""):
    """Extract the page's embedded bitmap when the vector crop has no reliable box.

    This is deliberately a last resort: it uses the largest/nearest native
    bitmap on the page and records why the column-aware crop was skipped, so a
    degraded extraction remains distinguishable from a precise crop.
    """

    import pypdfium2 as pdfium

    destination = Path(destination)
    document = pdfium.PdfDocument(str(pdf_path))
    try:
        page = document[page_index]
        try:
            page_width, page_height = page.get_size()
            try:
                anchor = _caption_anchor_in_pdf(pdf_path, page_index, caption)
            except Exception:
                anchor = None
            candidates = []
            for obj in page.get_objects():
                if obj.type != 3:
                    continue
                try:
                    x0, y0, x1, y1 = obj.get_pos()
                    native_width, native_height = obj.get_size()
                except Exception:
                    continue
                width, height = x1 - x0, y1 - y0
                if width < page_width * 0.03 or height < page_height * 0.03:
                    continue
                if min(native_width, native_height) < 120:
                    continue
                candidates.append({
                    "obj": obj,
                    "box": (x0, y0, x1, y1),
                    "native": (native_width, native_height),
                    "area": width * height,
                })
            if not candidates:
                return None
            chosen = None
            if anchor is not None:
                caption_top = anchor[1]
                above = [
                    item for item in candidates
                    if item["box"][1] >= caption_top - page_height * 0.15
                ]
                if above:
                    chosen = min(
                        above,
                        key=lambda item: (abs(item["box"][1] - caption_top), -item["area"]),
                    )
            if chosen is None:
                chosen = max(candidates, key=lambda item: item["area"])
            bitmap = chosen["obj"].get_bitmap(render=False)
            image = bitmap.to_pil()
            if min(image.size) < 120:
                return None
            temporary = destination.with_suffix(".tmp.png")
            image.save(temporary, format="PNG")
            _normalize_png(temporary, destination)
            temporary.unlink(missing_ok=True)
            _trim_white(destination)
            box = [round(value, 1) for value in chosen["box"]]
            return {
                "mode": "embedded_image",
                "reason": previous_reason or "列感知裁切失败，改用内嵌位图",
                "display_box": box,
                "image_size": [image.width, image.height],
            }
        finally:
            page.close()
    finally:
        document.close()


def _figures_from_pdf(source_path, ref_no, figure_dir, oa_url="", version="正式版", acquisition=None):
    """Render+crop the artwork for every accepted caption, including same-page figures.

    Each caption is an independent anchor: multiple captions on one page now
    yield multiple assets.  The crop region is derived from the graphic objects
    that share the caption's column, so a neighbouring column or a table above
    the artwork is not swept into the image.  Duplicated figure numbers are
    still cropped once, and a caption without a reliable graphic boundary is
    recorded as a degradation rather than cropped by a page-wide fallback.
    """

    figure_dir = Path(figure_dir)
    figure_dir.mkdir(parents=True, exist_ok=True)
    assets = []
    failures = []
    seen_figs = set()
    page_texts = read_pdf_pages(source_path)
    seen_embedded = set()
    for index, text in enumerate(page_texts):
        lines = text.splitlines()
        for line_index, line in enumerate(lines):
            match = CAPTION_RE.match(line.strip())
            if not match:
                continue
            fig_no = match.group(1)
            if fig_no in seen_figs:
                continue
            rest = match.group(2).lstrip()
            if rest.startswith((')', ',', ';')) or re.match(r'^[a-z]', rest):
                continue
            caption = _figure_caption_from_lines(lines, line_index)
            if not caption:
                continue
            scale = 2.0
            px, crop_meta = _column_aware_crop_pixels(source_path, index, caption, scale)
            name = _short_name(caption, fig_no)
            destination = figure_dir / f"ref{ref_no}_fig{fig_no}_{name}.png"
            temporary = figure_dir / f".ref{ref_no}_fig{fig_no}.tmp.png"
            asset = None
            failure_reason = ""
            if px is not None:
                completed = subprocess.run(
                    [
                        sys.executable,
                        str(PDF_FIGURES),
                        str(source_path),
                        "crop",
                        "--page",
                        str(index),
                        "--scale",
                        str(scale),
                        "--px",
                        ",".join(str(value) for value in px),
                        "--out",
                        str(temporary),
                    ],
                    capture_output=True,
                    text=True,
                    timeout=120,
                )
                if completed.returncode == 0 and temporary.is_file():
                    _normalize_png(temporary, destination)
                    temporary.unlink(missing_ok=True)
                    _trim_white(destination)
                    asset = FigureAsset(
                        ref_no=ref_no,
                        fig_no=fig_no,
                        name=name,
                        path=destination,
                        caption=caption,
                        description=f"原文 p{index + 1} 图区渲染裁切（图注锚点 + 同列图形块边界）。",
                        source_url=oa_url or str(source_path),
                        version=version or "正式版",
                        original_page=str(index + 1),
                        acquisition=acquisition or "OA PDF 渲染裁切（pdf_figures.py crop，Swift/PDFKit 或 PyMuPDF）",
                        slot=_slot_for_caption(caption),
                        crop_mode=crop_meta.get("mode", ""),
                        crop_meta=crop_meta,
                    )
                else:
                    temporary.unlink(missing_ok=True)
                    failure_reason = (
                        f"pdf_figures 裁切失败 "
                        f"{(completed.stderr or completed.stdout).strip()[:180]}"
                    )
            else:
                failure_reason = crop_meta.get("reason", "未定位到可靠图区")

            if asset is None:
                embedded = _embedded_image_for_caption(
                    source_path,
                    index,
                    caption,
                    destination,
                    previous_reason=failure_reason,
                )
                if embedded:
                    key = (
                        index,
                        tuple(embedded.get("display_box") or []),
                        tuple(embedded.get("image_size") or []),
                    )
                    if key in seen_embedded:
                        failures.append(
                            f"page {index + 1} Fig.{fig_no}: {failure_reason}；内嵌图已用于其他图注"
                        )
                        continue
                    seen_embedded.add(key)
                    asset = FigureAsset(
                        ref_no=ref_no,
                        fig_no=fig_no,
                        name=name,
                        path=destination,
                        caption=caption,
                        description=f"原文 p{index + 1} 内嵌位图提取（列感知裁切失败后兜底）。",
                        source_url=oa_url or str(source_path),
                        version=version or "正式版",
                        original_page=str(index + 1),
                        acquisition="OA PDF 内嵌位图（pdf_figures.py 兜底）",
                        slot=_slot_for_caption(caption),
                        crop_mode="embedded_image",
                        crop_meta=embedded,
                    )
                else:
                    failures.append(
                        f"page {index + 1} Fig.{fig_no}: {failure_reason}；内嵌图兜底未找到"
                    )
                    continue

            seen_figs.add(fig_no)
            assets.append(asset)
    return assets, failures


def _jats_figures(xml_path):
    root = ET.parse(str(xml_path)).getroot()
    pmcid = ""
    for node in root.iter():
        if _local_name(node.tag) == "article-id" and node.attrib.get("pub-id-type") in {"pmc", "pmcid"}:
            pmcid = _normalized("".join(node.itertext()))
            break
    if not pmcid:
        match = PMC_RE.search(str(xml_path))
        pmcid = match.group(0) if match else ""
    figures = []
    for node in root.iter():
        if _local_name(node.tag) != "fig":
            continue
        label = ""
        caption = ""
        href = ""
        for child in node:
            name = _local_name(child.tag)
            if name == "label":
                label = _normalized("".join(child.itertext()))
            elif name == "caption":
                caption = _normalized("".join(child.itertext()))
            elif name == "graphic":
                href = child.attrib.get(XLINK_HREF) or child.attrib.get("href") or ""
        if not href:
            for child in node.iter():
                if _local_name(child.tag) == "graphic":
                    href = child.attrib.get(XLINK_HREF) or child.attrib.get("href") or ""
                    if href:
                        break
        fig_no = _figure_number(label, href)
        if fig_no and (label or caption) and href:
            figures.append(
                {
                    "label": label,
                    "fig_no": fig_no,
                    "caption": caption or label,
                    "href": href,
                }
            )
    return pmcid, figures


def _select_package_member(names, href):
    basename = Path(href).name
    candidates = [name for name in names if Path(name).name == basename]
    if not candidates:
        stem = Path(basename).stem
        candidates = [name for name in names if stem and stem in name]
    if not candidates:
        return None
    priority = (".jpg", ".jpeg", ".png", ".tif", ".tiff", ".gif")
    for suffix in priority:
        for name in candidates:
            if name.casefold().endswith(suffix):
                return name
    return candidates[0]


def _figures_from_jats(source_path, ref_no, figure_dir, service, attempt):
    """Use the OA JATS graphic package; the PDF itself may be bot-blocked."""

    assets = []
    failures = []
    pmcid, figures = _jats_figures(source_path)
    if not pmcid:
        return assets, ["JATS XML 未找到 PMCID，无法定位图像包"]
    package_url = f"{EUROPEPMC_API}/{pmcid}/supplementaryFiles"
    attempt["figure_package_url"] = package_url
    try:
        data, content_type = service.oa_module.http_binary(package_url, tries=3, timeout=60)
    except Exception as error:
        return assets, [f"Europe PMC 图像包下载失败: {type(error).__name__}: {str(error)[:180]}"]
    if not zipfile.is_zipfile(io.BytesIO(data)):
        return assets, [f"图像包不是 ZIP（{content_type or '未知类型'}，{len(data)} bytes）"]
    with zipfile.ZipFile(io.BytesIO(data)) as package:
        names = package.namelist()
        for figure in figures:
            href = figure.get("href") or ""
            member = _select_package_member(names, href)
            if not member:
                failures.append(f"Fig.{figure.get('fig_no') or '?'} 图像包缺少 {href or 'href'}")
                continue
            fig_no = figure.get("fig_no") or _figure_number("", href)
            caption = figure.get("caption") or figure.get("label") or ""
            name = _short_name(caption, fig_no)
            destination = figure_dir / f"ref{ref_no}_fig{fig_no}_{name}.png"
            temporary = figure_dir / f".ref{ref_no}_fig{fig_no}.tmp{Path(member).suffix}"
            temporary.write_bytes(package.read(member))
            try:
                _normalize_png(temporary, destination)
            except Exception as error:
                failures.append(f"Fig.{fig_no} 图像转换失败: {type(error).__name__}: {str(error)[:120]}")
                temporary.unlink(missing_ok=True)
                continue
            temporary.unlink(missing_ok=True)
            article_url = attempt.get("oa_url") or f"https://pmc.ncbi.nlm.nih.gov/articles/{pmcid}/"
            assets.append(
                FigureAsset(
                    ref_no=ref_no,
                    fig_no=fig_no,
                    name=name,
                    path=destination,
                    caption=caption,
                    description=f"Europe PMC JATS 图像包 {member}（原始图像文件，非 PDF 裁切）。",
                    source_url=article_url,
                    version=attempt.get("version") or "正式版",
                    original_page="【待核实】",
                    acquisition="Europe PMC JATS XML + supplementaryFiles 图像包（PDF 直链被反爬拦截）",
                    slot=_slot_for_caption(caption),
                    asset_url=f"{package_url}#{member}",
                )
            )
    return assets, failures


def _write_log(output_dir, bundle):
    log_path = Path(output_dir) / "figure_acquisition_log.md"
    lines = [
        "# D 原文图获取日志",
        "",
        f"- 生成时间：{datetime.now().isoformat(timespec='seconds')}",
        "- 原则：只使用 OA PDF / Europe PMC JATS 图像包；未取得时写 OA 链接、文字描述与【待核实】，不重绘、不伪造。",
        "",
        "## 逐篇定位结果",
        "",
        "| ref | OA 定位 / 版本 | 阅读深度 | 图数 | 结果 |",
        "|---|---|---|---|---|",
    ]
    for attempt in bundle.attempts:
        assets = bundle.by_ref(attempt.get("ref_no", 0))
        lines.append(
            "| [{ref}] | {url} / {version} | {depth} | {count} | {status} |".format(
                ref=attempt.get("ref_no", "?"),
                url=attempt.get("source_url") or attempt.get("oa_url") or "未提供 OA 链接",
                version=attempt.get("version") or "未确认",
                depth=attempt.get("depth") or "仅摘要",
                count=len(assets),
                status=attempt.get("status") or "未获取",
            )
        )
    lines.extend(["", "## 逐篇明细", ""])
    for attempt in bundle.attempts:
        lines.append(f"### [{attempt.get('ref_no')}] {attempt.get('title') or '(untitled)'}")
        lines.append(f"- OA 链接：{attempt.get('oa_url') or '未提供'}")
        lines.append(f"- 实际版本：{attempt.get('version') or '未确认'}")
        lines.append(f"- 阅读深度：{attempt.get('depth') or '仅摘要'}")
        lines.append(f"- 定位/下载：{attempt.get('status') or '未获取'}")
        if attempt.get("pdf_backend"):
            lines.append(f"- PDF 后端：{attempt['pdf_backend']}")
        if attempt.get("acquisition"):
            lines.append(f"- 获取方式：{attempt['acquisition']}")
        for failure in attempt.get("failures") or []:
            lines.append(f"- 失败记录：{failure}")
        assets = bundle.by_ref(attempt.get("ref_no", 0))
        if assets:
            for asset in assets:
                lines.append(
                    f"- 图片：`{asset.path.name}`｜{asset.caption_line()}｜获取方式：{asset.acquisition}"
                )
        else:
            lines.append(
                "- 降级：页面保留 OA 链接与文字说明，并标【待核实】；不把摘要或示意图冒充原文图。"
            )
        lines.append("")
    log_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return log_path


def _supplemental_pdf_images(source_path, ref_no, figure_dir, needed=2):
    """Extract real embedded bitmaps when caption-based crops miss the artwork."""
    figure_dir = Path(figure_dir)
    figure_dir.mkdir(parents=True, exist_ok=True)
    assets = []
    try:
        pages = read_pdf_pages(source_path)
    except Exception:
        return assets
    for page_index in range(min(len(pages), 16)):
        if len(assets) >= needed:
            break
        destination = figure_dir / f"ref{ref_no}_supp{len(assets) + 1}.png"
        meta = _embedded_image_for_caption(
            source_path,
            page_index,
            '',
            destination,
            previous_reason='图注未定位，补充页面内嵌位图',
        )
        if meta:
            assets.append(FigureAsset(
                ref_no=ref_no,
                fig_no=f'S{len(assets) + 1}',
                name='补充原图',
                path=destination,
                caption='补充原图（未定位到图注，使用页面内嵌位图）',
                description=f'原文 p{page_index + 1} 页面内嵌位图补充。',
                source_url=str(source_path),
                version='正式版',
                original_page=str(page_index + 1),
                acquisition='OA PDF 页面内嵌位图补充（图注定位失败）',
                slot='reading',
                crop_mode='embedded_image',
                crop_meta=meta,
            ))
            continue
        # Last resort for vector-only pages: crop the largest graphic object.
        try:
            bbox, page_width, page_height = _largest_object_bbox(source_path, page_index)
        except Exception:
            bbox, page_width, page_height = None, 0, 0
        if not bbox or page_width <= 0 or page_height <= 0:
            continue
        x0, y0, x1, y1 = bbox
        scale = 2.0
        px = (
            round(max(0, x0) * scale, 2),
            round(max(0, page_height - y1) * scale, 2),
            round(max(1, x1 - x0) * scale, 2),
            round(max(1, y1 - y0) * scale, 2),
        )
        temporary = figure_dir / f'.ref{ref_no}_supp{len(assets) + 1}.tmp.png'
        completed = subprocess.run(
            [sys.executable, str(PDF_FIGURES), str(source_path), 'crop', '--page', str(page_index),
             '--scale', str(scale), '--px', ','.join(str(value) for value in px), '--out', str(temporary)],
            capture_output=True, text=True, timeout=120,
        )
        if completed.returncode != 0 or not temporary.is_file():
            continue
        _normalize_png(temporary, destination)
        temporary.unlink(missing_ok=True)
        _trim_white(destination)
        assets.append(FigureAsset(
            ref_no=ref_no,
            fig_no=f'S{len(assets) + 1}',
            name='补充原图',
            path=destination,
            caption='补充原图（未定位到图注，使用页面最大图形区域）',
            description=f'原文 p{page_index + 1} 页面最大图形区域裁切补充。',
            source_url=str(source_path),
            version='正式版',
            original_page=str(page_index + 1),
            acquisition='OA PDF 页面图形区域补充（图注定位失败）',
            slot='reading',
            crop_mode='page_graphic',
            crop_meta={'mode': 'page_graphic', 'display_box': [round(v, 1) for v in bbox]},
        ))
    return assets


FRAMEWORK_PREFERRED_REFS = (4, 2, 3)


def prepare_d_figures(
    papers,
    reading_cards,
    output_dir,
    *,
    service=None,
    include_supporting=True,
    max_refs=5,
    figure_dirname="figures",
    allow_network=True,
    local_pdfs=None,
    allow_doi_fallback=False,
):
    """Acquire figures for the D reading set, returning a planning bundle.

    ``service`` is injectable for offline tests.  When omitted, the normal
    ``FullTextService`` contract (OA resolver + copied oa_pdf.py) is used.
    """

    output_dir = Path(output_dir)
    figure_dir = output_dir / figure_dirname
    figure_dir.mkdir(parents=True, exist_ok=True)
    papers = list(papers or [])
    paper_by_ref = {int(paper.get("ref_no") or paper.get("ref") or 0): paper for paper in papers}
    refs = []
    for card in reading_cards or []:
        try:
            ref = int(card.get("ref"))
        except (TypeError, ValueError):
            continue
        if ref and ref not in refs:
            refs.append(ref)
    reading_count = len(refs)
    if include_supporting:
        for paper in papers:
            try:
                ref = int(paper.get("ref_no") or paper.get("ref") or 0)
            except (TypeError, ValueError):
                continue
            if ref and ref not in refs:
                refs.append(ref)
    framework = [ref for ref in FRAMEWORK_PREFERRED_REFS if ref in paper_by_ref and ref not in refs[:reading_count]]
    refs = refs[:reading_count] + framework + [ref for ref in refs[reading_count:] if ref not in framework]
    refs = refs[:max(max_refs, reading_count + len(framework))]
    bundle = FigureBundle()
    if not refs:
        _write_log(output_dir, bundle)
        return bundle

    if service is None:
        service = FullTextService(output_dir=output_dir)
    for ref in refs:
        paper = paper_by_ref.get(ref, {})
        attempt = {
            "ref_no": ref,
            "title": _normalized(paper.get("title")),
            "oa_url": paper.get("doi") or paper.get("oa_url") or paper.get("pdf_url") or "",
            "pdf_url": paper.get("pdf_url") or paper.get("oa_url") or "",
            "version": "未确认",
            "depth": "仅摘要",
            "status": "未获取",
            "source_url": "",
            "pdf_backend": "",
            "failures": [],
        }
        if not paper:
            attempt["failures"].append("papers.json 中没有该 ref，无法定位")
            bundle.attempts.append(attempt)
            continue
        local_pdf = (local_pdfs or {}).get(ref)
        if not local_pdf:
            cached_pdf = output_dir / "oa_pdfs" / f"source_ref{ref}.pdf"
            if cached_pdf.is_file():
                local_pdf = cached_pdf
        cached_xml = output_dir / f"fulltext_ref{ref}.xml"
        local_source = None
        local_kind = ""
        if local_pdf:
            local_source = Path(local_pdf)
            local_kind = "pdf"
        elif cached_xml.is_file():
            local_source = cached_xml
            local_kind = "xml"
        if local_source is not None:
            if not local_source.is_file():
                attempt["failures"].append(f"本地全文不存在: {local_source}")
                attempt["status"] = "未定位到可用本地全文"
                bundle.attempts.append(attempt)
                continue
            result = _LocalFulltext(
                source_path=local_source,
                source_url=attempt["oa_url"],
            )
        else:
            if not allow_network:
                attempt["failures"].append("本次运行禁用网络，仅登记 OA 线索")
                attempt["status"] = "未尝试（网络关闭）"
                bundle.attempts.append(attempt)
                continue
            if not _has_oa_hint(paper):
                if not (allow_doi_fallback and str(paper.get("doi") or "").strip()):
                    attempt["failures"].append("题录没有 OA URL/开放获取标记，未发起网络定位")
                    attempt["status"] = "未尝试（无 OA 线索）"
                    bundle.attempts.append(attempt)
                    continue
            try:
                result = service.read_for_components(paper, purpose="D_READING_CARD")
            except Exception as error:
                attempt["failures"].append(f"FullTextService 读取失败: {type(error).__name__}: {str(error)[:180]}")
                bundle.attempts.append(attempt)
                continue
        attempt.update(
            {
                "source_url": result.source_url or "",
                "version": result.version or "未确认",
                "depth": result.depth or "仅摘要",
                "status": "已定位" if result.source_path else "未定位到可用 OA 全文",
            }
        )
        if local_kind == "pdf":
            attempt["status"] = "已定位（本地 OA PDF）"
            attempt["acquisition"] = "本地 OA PDF"
        elif local_kind == "xml":
            attempt["status"] = "已定位（本地缓存全文）"
            attempt["acquisition"] = "本地缓存 Europe PMC JATS XML"
        attempt["failures"].extend(result.failures or [])
        if not result.source_path:
            bundle.attempts.append(attempt)
            continue
        source_path = Path(result.source_path)
        if source_path.suffix.casefold() == '.pdf':
            attempt['source_path'] = str(source_path)
        assets = []
        failures = []
        try:
            if source_path.suffix.casefold() == ".pdf":
                attempt["pdf_backend"] = _pdf_backend()
                assets, failures = _figures_from_pdf(
                    source_path,
                    ref,
                    figure_dir,
                    oa_url=attempt["oa_url"],
                    version=result.version or "正式版",
                    acquisition="本地 OA PDF 渲染裁切（pdf_figures.py crop）" if local_pdf else None,
                )
            elif source_path.suffix.casefold() == ".xml":
                assets, failures = _figures_from_jats(source_path, ref, figure_dir, service, attempt)
            else:
                failures.append(f"不支持的全文格式：{source_path.suffix}")
        except Exception as error:
            failures.append(f"原图抽取失败: {type(error).__name__}: {str(error)[:180]}")
        attempt["failures"].extend(failures)
        if assets:
            attempt["status"] = f"已取得 {len(assets)} 张原图"
            bundle.assets.extend(assets)
        else:
            attempt["status"] = "已定位全文但未取得可嵌入原图"
        bundle.attempts.append(attempt)
    if len(bundle.assets) < 2:
        for attempt in bundle.attempts:
            source_path = attempt.get('source_path')
            if not source_path or not Path(source_path).is_file():
                continue
            added = _supplemental_pdf_images(
                source_path,
                attempt.get('ref_no'),
                figure_dir,
                needed=2 - len(bundle.assets),
            )
            if not added:
                continue
            bundle.assets.extend(added)
            attempt['status'] = (
                f'已取得 {len(bundle.by_ref(attempt.get("ref_no") or 0))} 张原图（含内嵌位图补充）'
            )
            attempt.setdefault('failures', []).append(
                f'图注定位未取得足够图片，已补充 {len(added)} 张页面内嵌位图'
            )
            if len(bundle.assets) >= 2:
                break
    _write_log(output_dir, bundle)
    return bundle


def _find_slide(slides, predicate):
    return next((slide for slide in slides if predicate(slide)), None)


def _reading_pages(slides):
    pages = {}
    for slide in slides:
        match = re.search(r"代表作精读\s*\[(\d+)\]", slide.get("title", ""))
        if not match:
            continue
        ref = int(match.group(1))
        pages.setdefault(ref, []).append(slide)
    return pages


def _degraded_entry(ref_no, attempt, description):
    return {
        "degraded": True,
        "allow_degraded": True,
        "reason": "; ".join(attempt.get("failures") or [])[:500] or "未取得 OA 原图",
        "attempt_log": "; ".join(
            filter(
                None,
                [
                    f"OA 链接：{attempt.get('oa_url') or '未提供'}",
                    f"定位结果：{attempt.get('status') or '未获取'}",
                    f"版本：{attempt.get('version') or '未确认'}",
                ],
            )
        ),
        "oa_url": attempt.get("oa_url") or "",
        "ref_no": ref_no,
        "description": description,
    }


def decorate_d_slides(slides, bundle):
    """Attach real figures to existing pages without changing page order."""

    if bundle is None:
        return slides
    used = set()

    concept_page = _find_slide(slides, lambda slide: slide.get("title") == "研究背景与科学问题")
    method_pages = [slide for slide in slides if slide.get("title") == "核心方法与技术路线"]
    method_page = next((slide for slide in method_pages if slide.get("layout") != "table"), None)
    trend_page = _find_slide(slides, lambda slide: slide.get("title") == "发展趋势｜不足→潜在突破")
    progress_pages = [slide for slide in slides if str(slide.get("title", "")).startswith("研究进展｜")]

    concept = bundle.pick("concept", preferred_ref=FRAMEWORK_PREFERRED_REFS[0], exclude=used)
    if concept_page and concept:
        concept_page.setdefault("figures", []).append(concept)
        used.add(concept.path)
    elif concept_page:
        attempt = next((item for item in bundle.attempts if item.get("ref_no") == FRAMEWORK_PREFERRED_REFS[0]), {})
        if not attempt:
            attempt = {"failures": [f"ref{FRAMEWORK_PREFERRED_REFS[0]} 无采集记录（超出采集集或未取得全文）"], "status": "未获取"}
        concept_page.setdefault("degraded_figures", []).append(
            _degraded_entry(FRAMEWORK_PREFERRED_REFS[0], attempt, "概念框架页未取得可用 OA 原图，保留研究链条示意并标【待核实】。")
        )

    overview_page = next(
        (slide for slide in progress_pages if "微环境" in slide.get("title", "") or "总览" in slide.get("title", "")),
        None,
    )
    comparison = bundle.pick("comparison", preferred_ref=FRAMEWORK_PREFERRED_REFS[0], exclude=used)
    if overview_page and comparison:
        overview_page.setdefault("figures", []).append(comparison)
        used.add(comparison.path)

    method = bundle.pick("method", preferred_ref=FRAMEWORK_PREFERRED_REFS[1], exclude=used) or bundle.pick("architecture", exclude=used)
    if method_page and method:
        method_page.setdefault("figures", []).append(method)
        used.add(method.path)
    elif method_page:
        attempt = next((item for item in bundle.attempts if item.get("ref_no") == FRAMEWORK_PREFERRED_REFS[1]), {})
        if not attempt:
            attempt = {"failures": [f"ref{FRAMEWORK_PREFERRED_REFS[1]} 无采集记录（超出采集集或未取得全文）"], "status": "未获取"}
        method_page.setdefault("degraded_figures", []).append(
            _degraded_entry(FRAMEWORK_PREFERRED_REFS[1], attempt, "技术路线页未取得可用 OA 原图，保留方法对比表并标【待核实】。")
        )

    mechanism_page = next(
        (slide for slide in progress_pages if "乳酸化" in slide.get("title", "") or "稳定性" in slide.get("title", "")),
        None,
    )
    architecture = bundle.pick("architecture", preferred_ref=FRAMEWORK_PREFERRED_REFS[2], exclude=used)
    if mechanism_page and architecture:
        mechanism_page.setdefault("figures", []).append(architecture)
        used.add(architecture.path)

    for ref_no, pages in _reading_pages(slides).items():
        assets = bundle.by_ref(ref_no)
        method_slide = next((slide for slide in pages if "方法与数据" in slide.get("title", "")), pages[0])
        finding_slide = next((slide for slide in pages if "发现与启发" in slide.get("title", "")), None)
        if not assets:
            attempt = bundle.degraded_for_ref(ref_no) or {}
            description = (
                f"[{ref_no}] 原文图未获取；OA 链接与文字描述见 ppt_asset_manifest.json，"
                "不把摘要示意图当作原文图。"
            )
            method_slide.setdefault("degraded_figures", []).append(
                _degraded_entry(ref_no, attempt, description)
            )
            continue
        first = next(
            (asset for asset in assets if asset.path not in used and asset.slot in {"method", "reading"}),
            next((asset for asset in assets if asset.path not in used), None),
        )
        if first is None:
            attempt = bundle.degraded_for_ref(ref_no) or {}
            method_slide.setdefault("degraded_figures", []).append(
                _degraded_entry(
                    ref_no, attempt,
                    f"[{ref_no}] 可用原图已用于其他页，本页未嵌入；OA 链接与文字描述见 ppt_asset_manifest.json，不把摘要示意图当作原文图。",
                )
            )
            continue
        method_slide.setdefault("figures", []).append(first)
        used.add(first.path)
        if finding_slide:
            second = next(
                (
                    asset
                    for asset in assets
                    if asset.path not in used and asset.slot in {"architecture", "breakthrough", "reading"}
                ),
                None,
            )
            if second:
                finding_slide.setdefault("figures", []).append(second)
                used.add(second.path)

    if trend_page:
        breakthrough = bundle.pick("breakthrough", preferred_ref=3, exclude=used)
        if breakthrough:
            trend_page.setdefault("figures", []).append(breakthrough)
            used.add(breakthrough.path)

    # Guarantee: if at least two real assets exist, place at least two of them
    # even when their semantic slots do not match the preferred pages.
    if len(used) < 2:
        empty_pages = [slide for slide in slides if not slide.get("figures")]
        for asset in bundle.assets:
            if asset.path in used:
                continue
            page = next((slide for slide in empty_pages if not slide.get("figures")), None)
            if page is None:
                break
            page.setdefault("figures", []).append(asset)
            used.add(asset.path)
            if len(used) >= 2:
                break

    return slides


def manifest_entries(slides, relative_to):
    entries = []
    for slide in slides:
        page = slide.get("n")
        for asset in slide.get("figures", []):
            entries.append(asset.manifest_entry(page, relative_to))
        for degraded in slide.get("degraded_figures", []):
            entry = {
                "page": page,
                "kind": "image",
                "name": f"[{degraded.get('ref_no', '?')}] 原文图降级记录",
                "expected_text": [slide.get("title", "")],
            }
            entry.update(degraded)
            entries.append(entry)
    return entries
