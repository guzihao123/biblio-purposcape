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


def _figure_caption_from_lines(lines, match_index):
    pieces = [lines[match_index].strip()]
    for line in lines[match_index + 1:match_index + 3]:
        stripped = line.strip()
        if not stripped or CAPTION_RE.match(stripped):
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


def _caption_crop_pixels(pdf_path, page_index, caption, scale=2.0):
    """Crop from the page's top content margin down to the caption top.

    Review/research figure pages usually put the caption directly under the
    artwork.  This keeps the figure title and all labels (the largest-object
    box alone often clips the title or a table header).
    """

    import pypdfium2 as pdfium

    token = _normalized(caption)[:9]
    if not token:
        return None
    document = pdfium.PdfDocument(str(pdf_path))
    try:
        page = document[page_index]
        try:
            page_width, page_height = page.get_size()
            text_page = page.get_textpage()
            try:
                searcher = text_page.search(token)
                occurrence = searcher.get_next()
                if occurrence is None:
                    return None
                index, _count = occurrence
                x0, y0, _x1, caption_top = text_page.get_charbox(index)
                top_px = page_height * 0.055
                bottom_px = page_height - caption_top - 3
                left_px = page_width * 0.035
                right_px = page_width * 0.965
                if bottom_px - top_px < page_height * 0.18:
                    return None
                return (
                    round(left_px * scale, 2),
                    round(top_px * scale, 2),
                    round((right_px - left_px) * scale, 2),
                    round((bottom_px - top_px) * scale, 2),
                )
            finally:
                text_page.close()
        finally:
            page.close()
    finally:
        document.close()


def _figures_from_pdf(source_path, ref_no, figure_dir, oa_url="", version="正式版", acquisition=None):
    """Render+crop the figure region on each caption page."""

    figure_dir = Path(figure_dir)
    figure_dir.mkdir(parents=True, exist_ok=True)
    assets = []
    failures = []
    page_texts = read_pdf_pages(source_path)
    for index, text in enumerate(page_texts):
        lines = text.splitlines()
        for line_index, line in enumerate(lines):
            match = CAPTION_RE.match(line.strip())
            if not match:
                continue
            fig_no = match.group(1)
            rest = match.group(2).lstrip()
            if rest.startswith((')', ',', ';')) or re.match(r'^[a-z]', rest):
                continue
            caption = _figure_caption_from_lines(lines, line_index)
            if not caption:
                continue
            bbox, page_width, page_height = _largest_object_bbox(source_path, index)
            crop_page = index
            if bbox is None:
                for offset in (1, -1):
                    candidate = index + offset
                    if 0 <= candidate < len(page_texts):
                        bbox, page_width, page_height = _largest_object_bbox(source_path, candidate)
                        if bbox is not None:
                            crop_page = candidate
                            break
            scale = 2.0
            px = _caption_crop_pixels(source_path, index, caption, scale) if crop_page == index else None
            if px is None and bbox is not None:
                x0, y0, x1, y1 = bbox
                margin = 4.0
                x0 = max(0.0, x0 - margin)
                y0 = min(page_height, y0 + margin)
                x1 = min(page_width, x1 + margin)
                y1 = max(0.0, y1 - margin)
                px = (
                    round(x0 * scale, 2),
                    round((page_height - y1) * scale, 2),
                    round((x1 - x0) * scale, 2),
                    round((y1 - y0) * scale, 2),
                )
            if px is None:
                failures.append(f"page {index + 1} Fig.{fig_no}: 未定位到图对象")
                continue
            name = _short_name(caption, fig_no)
            destination = figure_dir / f"ref{ref_no}_fig{fig_no}_{name}.png"
            temporary = figure_dir / f".ref{ref_no}_fig{fig_no}.tmp.png"
            completed = subprocess.run(
                [
                    sys.executable,
                    str(PDF_FIGURES),
                    str(source_path),
                    "crop",
                    "--page",
                    str(crop_page),
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
            if completed.returncode != 0 or not temporary.is_file():
                failures.append(
                    f"page {index + 1} Fig.{fig_no}: pdf_figures 裁切失败 "
                    f"{(completed.stderr or completed.stdout).strip()[:180]}"
                )
                continue
            _normalize_png(temporary, destination)
            temporary.unlink(missing_ok=True)
            _trim_white(destination)
            assets.append(
                FigureAsset(
                    ref_no=ref_no,
                    fig_no=fig_no,
                    name=name,
                    path=destination,
                    caption=caption,
                    description=f"原文 p{index + 1} 图区渲染裁切（页顶至图注上沿）。",
                    source_url=oa_url or str(source_path),
                    version=version or "正式版",
                    original_page=str(crop_page + 1),
                    acquisition=acquisition or "OA PDF 渲染裁切（pdf_figures.py crop，Swift/PDFKit 或 PyMuPDF）",
                    slot=_slot_for_caption(caption),
                )
            )
            break
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
    if include_supporting:
        for paper in papers:
            try:
                ref = int(paper.get("ref_no") or paper.get("ref") or 0)
            except (TypeError, ValueError):
                continue
            if ref and ref not in refs:
                refs.append(ref)
    refs = refs[:max_refs]
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
        assets = []
        failures = []
        try:
            if source_path.suffix.casefold() == ".pdf":
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

    concept = bundle.pick("concept", preferred_ref=4, exclude=used)
    if concept_page and concept:
        concept_page.setdefault("figures", []).append(concept)
        used.add(concept.path)
    elif concept_page:
        attempt = next((item for item in bundle.attempts if item.get("title")), {})
        concept_page.setdefault("degraded_figures", []).append(
            _degraded_entry(4, attempt, "概念框架页未取得可用 OA 原图，保留研究链条示意并标【待核实】。")
        )

    overview_page = next(
        (slide for slide in progress_pages if "微环境" in slide.get("title", "") or "总览" in slide.get("title", "")),
        None,
    )
    comparison = bundle.pick("comparison", preferred_ref=4, exclude=used)
    if overview_page and comparison:
        overview_page.setdefault("figures", []).append(comparison)
        used.add(comparison.path)

    method = bundle.pick("method", preferred_ref=2, exclude=used) or bundle.pick("architecture", exclude=used)
    if method_page and method:
        method_page.setdefault("figures", []).append(method)
        used.add(method.path)
    elif method_page:
        attempt = next((item for item in bundle.attempts if item.get("ref_no") == 2), {})
        method_page.setdefault("degraded_figures", []).append(
            _degraded_entry(2, attempt, "技术路线页未取得可用 OA 原图，保留方法对比表并标【待核实】。")
        )

    mechanism_page = next(
        (slide for slide in progress_pages if "乳酸化" in slide.get("title", "") or "稳定性" in slide.get("title", "")),
        None,
    )
    architecture = bundle.pick("architecture", preferred_ref=3, exclude=used)
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
