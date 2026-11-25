"""Open-access full-text acquisition, PDF extraction, and reading-depth audit.

Only the copied OA resolver/downloader chain and explicitly user-provided local
files are accepted. Full text supplements non-claim component slots; abstract
quotes remain the default claim evidence.
"""

import argparse
import importlib.util
import json
import re
import shlex
import sys
import tempfile
import unicodedata
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import pypdfium2 as pdfium


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OA_SCRIPT = PROJECT_ROOT / 'skill_runtime' / 'scripts' / 'oa_pdf.py'
OCR_REVIEW_NOTE = 'OCR 识别，待人工核对'
VERSION_LABELS = {'预印本', '接收稿', '正式版'}
FIGURE_CAPTION = re.compile(r'(?im)^\s*(?:figure|fig\.?|图)\s*\d+\s*[:.．]?')
ANCHOR = re.compile(r'(?m)^=== (page \d+|sec [^\n]+) ===\s*$')
DATA_AVAILABILITY_TERMS = (
    'data availability',
    'availability of data',
    'availability of data and materials',
    'data and materials availability',
    '数据可用性',
    '数据可获得性',
    '数据获取',
)


class FullTextExtractionError(ValueError):
    def __init__(self, message, failures=()):
        super().__init__(message)
        self.failures = list(failures)


def _load_oa_module(path):
    spec = importlib.util.spec_from_file_location('_purpose_landscape_web_oa_pdf', str(path))
    if spec is None or spec.loader is None:
        raise ImportError('Cannot load copied OA script: {}'.format(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


oa_pdf = _load_oa_module(DEFAULT_OA_SCRIPT)


def _value(record, key, default=None):
    if isinstance(record, dict):
        return record.get(key, default)
    return getattr(record, key, default)


def _normalized(value):
    return ' '.join(str(value or '').split())


def _version_label(*values):
    for value in values:
        key = re.sub(r'[\s_\-]+', '', unicodedata.normalize('NFKC', str(value or '')).casefold())
        if not key:
            continue
        if key in {
            'submitted', 'submittedversion', 'preprint', 'postedcontent', 'workingpaper',
            '预印本',
        }:
            return '预印本'
        if key in {
            'accepted', 'acceptedversion', 'acceptedmanuscript', 'authoracceptedmanuscript',
            'aam', '接收稿',
        }:
            return '接收稿'
        if key in {
            'published', 'publishedversion', 'versionofrecord', 'vor', 'article', 'review',
            'journalarticle', '正式版',
        }:
            return '正式版'
    return None


def _atomic_write(path, content):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp')
    if isinstance(content, bytes):
        temporary.write_bytes(content)
    else:
        temporary.write_text(content, encoding='utf-8')
    temporary.replace(path)


def _validate_pdf_page(document, page):
    if type(page) is not int or page < 0 or page >= len(document):
        raise IndexError('PDF page index is zero-based and must exist: {}'.format(page))


def _save_render(page, scale, crop, output_path):
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    bitmap = page.render(scale=scale, crop=crop)
    try:
        image = bitmap.to_pil()
        image.save(str(output_path), format='PNG')
    finally:
        bitmap.close()
    return output_path


def pdf_info(source):
    """Return deterministic local PDF metadata with one-based page numbers."""

    document = pdfium.PdfDocument(str(source))
    pages = []
    try:
        for index in range(len(document)):
            page = document[index]
            try:
                width, height = page.get_size()
                pages.append({
                    'page': index + 1,
                    'width': float(width),
                    'height': float(height),
                })
            finally:
                page.close()
    finally:
        document.close()
    return {'page_count': len(pages), 'pages': pages}


def render_pdf_page(source, page=0, scale=2.0, output_path=None):
    """Render one zero-based PDF page to PNG with pypdfium2."""

    if output_path is None:
        raise ValueError('output_path is required')
    if not isinstance(scale, (int, float)) or isinstance(scale, bool) or scale <= 0:
        raise ValueError('scale must be a positive number')
    document = pdfium.PdfDocument(str(source))
    try:
        _validate_pdf_page(document, page)
        pdf_page = document[page]
        try:
            return _save_render(pdf_page, float(scale), (0, 0, 0, 0), output_path)
        finally:
            pdf_page.close()
    finally:
        document.close()


def crop_pdf_page(source, page=0, scale=2.0, pixel_rect=None, output_path=None):
    """Crop a top-left-origin ``(x, y, width, height)`` pixel rectangle to PNG."""

    if output_path is None:
        raise ValueError('output_path is required')
    if pixel_rect is None or len(pixel_rect) != 4:
        raise ValueError('pixel_rect must contain x, y, width, height')
    if not isinstance(scale, (int, float)) or isinstance(scale, bool) or scale <= 0:
        raise ValueError('scale must be a positive number')
    x, y, width, height = (float(value) for value in pixel_rect)
    if x < 0 or y < 0 or width <= 0 or height <= 0:
        raise ValueError('crop origin must be nonnegative and crop dimensions positive')

    document = pdfium.PdfDocument(str(source))
    try:
        _validate_pdf_page(document, page)
        pdf_page = document[page]
        try:
            page_width, page_height = pdf_page.get_size()
            crop = (
                x / scale,
                page_height - (y + height) / scale,
                page_width - (x + width) / scale,
                y / scale,
            )
            if min(crop) < -1e-6:
                raise ValueError('pixel_rect exceeds the rendered page bounds')
            crop = tuple(max(0.0, value) for value in crop)
            return _save_render(pdf_page, float(scale), crop, output_path)
        finally:
            pdf_page.close()
    finally:
        document.close()


def read_pdf_pages(source):
    """Return born-digital page text using pypdfium2, without implicit OCR."""

    document = pdfium.PdfDocument(str(source))
    pages = []
    try:
        for index in range(len(document)):
            page = document[index]
            try:
                text_page = page.get_textpage()
                try:
                    pages.append(text_page.get_text_range(
                        0, text_page.count_chars(), errors='ignore', force_this=True
                    ).strip())
                finally:
                    text_page.close()
            finally:
                page.close()
    finally:
        document.close()
    return pages


def with_page_anchors(page_texts):
    return '\n\n'.join(
        '=== page {} ===\n{}'.format(index, text)
        for index, text in enumerate(page_texts, 1)
    )


def extract_pdf_text(source):
    """Extract all born-digital text with required one-based page anchors."""

    return with_page_anchors(read_pdf_pages(source))


def _local_name(tag):
    return str(tag).rsplit('}', 1)[-1]


def _node_text(node):
    return _normalized(''.join(node.itertext()))


def _xml_version(root):
    for node in root.iter():
        if _local_name(node.tag) == 'article-version':
            label = _version_label(_node_text(node))
            if label:
                return label
    return None


def extract_europepmc_text(source):
    """Extract JATS body/back text with exact section anchors, excluding references."""

    root = ET.parse(str(source)).getroot()

    def emit_section(section, forced_title=None):
        title = forced_title
        for child in section:
            if _local_name(child.tag) == 'title' and title is None:
                title = _node_text(child)
                break
        anchor = '=== sec {} ==='.format(_normalized(title or 'UNTITLED'))
        chunks = []
        direct_text = []

        def flush_direct():
            if direct_text:
                chunks.append(anchor + '\n' + '\n\n'.join(direct_text))
                direct_text[:] = []

        for child in section:
            name = _local_name(child.tag)
            if name in {'title', 'table-wrap', 'inline-formula', 'disp-formula', 'ref-list'}:
                continue
            if name == 'sec':
                flush_direct()
                chunks.extend(emit_section(child))
            elif name in {'notes', 'ack', 'app'}:
                flush_direct()
                note_title = child.get('notes-type') or child.get('id') or name
                chunks.extend(emit_section(child, forced_title=note_title))
            elif name == 'p':
                text = _node_text(child)
                if text:
                    direct_text.append(text)
            elif name not in {'fig', 'graphic', 'media', 'permissions'}:
                for paragraph in child.iter():
                    if _local_name(paragraph.tag) == 'p':
                        text = _node_text(paragraph)
                        if text:
                            direct_text.append(text)
        flush_direct()
        return chunks or [anchor]

    parts = []
    for container_name in ('body', 'back'):
        containers = [node for node in root.iter() if _local_name(node.tag) == container_name]
        for container in containers:
            direct_text = []

            def flush_container_direct():
                if direct_text:
                    parts.append('=== sec {} ===\n{}'.format(
                        container_name.capitalize(), '\n\n'.join(direct_text)
                    ))
                    direct_text[:] = []

            for child in container:
                name = _local_name(child.tag)
                if name == 'sec':
                    flush_container_direct()
                    parts.extend(emit_section(child))
                elif name in {'notes', 'ack', 'app'}:
                    flush_container_direct()
                    parts.extend(emit_section(child, forced_title=child.get('notes-type') or name))
                elif name == 'p':
                    text = _node_text(child)
                    if text:
                        direct_text.append(text)
            flush_container_direct()

    text = '\n\n'.join(part for part in parts if part and part.strip())
    if not text.strip():
        raise ValueError('Europe PMC XML contains no extractable body/back text')
    return text


def _segments(full_text):
    matches = list(ANCHOR.finditer(full_text or ''))
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(full_text)
        yield match.group(1), full_text[match.end():end].strip()


def _data_availability(full_text):
    for anchor, body in _segments(full_text):
        title = anchor[4:] if anchor.startswith('sec ') else ''
        title_matches = any(term in title.casefold() for term in DATA_AVAILABILITY_TERMS)
        lowered = body.casefold()
        starts = [lowered.find(term) for term in DATA_AVAILABILITY_TERMS if lowered.find(term) >= 0]
        if starts:
            excerpt = body[min(starts):].strip()
        elif title_matches:
            excerpt = body.strip()
        else:
            continue
        if not excerpt:
            continue
        if len(excerpt) > 1600:
            excerpt = excerpt[:1600].rsplit(' ', 1)[0].strip() + '…'
        return '{}: {}'.format(anchor, excerpt)
    return '未确认'


@dataclass(frozen=True)
class FullTextLedgerChannel:
    ref_no: int
    quote: str
    anchor: str
    source_url: object
    version: str
    channel: str = 'fulltext'
    verified: bool = True
    note: str = ''


@dataclass
class FullTextResult:
    ref_no: int
    purpose: str
    depth: str = '仅摘要'
    version: str = '未确认'
    original_abstract_quote: object = None
    data_availability: str = '未确认'
    source_url: object = None
    source_path: object = None
    fulltext_path: object = None
    figure_paths: list = field(default_factory=list)
    extraction_command: str = '未执行'
    failures: list = field(default_factory=list)
    ocr_used: bool = False
    ledger_channels: list = field(default_factory=list)
    excerpts: list = field(default_factory=list)
    non_claim_slots: dict = field(default_factory=dict)
    writing_reference: object = None
    claim_evidence_default: str = 'abstract'
    full_text: str = field(default='', repr=False)


class FullTextService:
    """Read OA/user documents during component production and audit every attempt."""

    def __init__(
        self,
        output_dir,
        resolver=None,
        binary_downloader=None,
        text_downloader=None,
        ocr=None,
        email=None,
        oa_script=DEFAULT_OA_SCRIPT,
    ):
        self.output_dir = Path(output_dir).resolve()
        self.email = email
        self.oa_script = Path(oa_script).resolve()
        self.oa_module = oa_pdf if self.oa_script == DEFAULT_OA_SCRIPT else _load_oa_module(self.oa_script)
        self.resolver = resolver
        self.binary_downloader = binary_downloader or self.oa_module.http_binary
        self.text_downloader = text_downloader or self.oa_module.http_text
        self.ocr = ocr

    def _resolve(self, paper):
        if self.resolver is not None:
            return self.resolver(paper)
        return self.oa_module.resolve(
            doi=_value(paper, 'doi'),
            arxiv_id=_value(paper, 'arxiv_id'),
            title=_value(paper, 'title'),
            year=_value(paper, 'year'),
            email=self.email,
        )

    def _fallback_paper_candidates(self, paper):
        """Use OA fields already returned by OpenAlex, never an arbitrary landing URL."""

        candidates = []
        explicit_oa_flag = _value(paper, 'is_oa', None)
        open_access = _value(paper, 'open_access', {}) or {}
        if explicit_oa_flag is False or (
            isinstance(open_access, dict) and open_access.get('is_oa') is False
        ):
            return candidates
        is_oa = bool(explicit_oa_flag)
        if isinstance(open_access, dict):
            is_oa = is_oa or bool(open_access.get('is_oa'))
        oa_url = _value(paper, 'oa_url') or (open_access.get('oa_url') if isinstance(open_access, dict) else None)
        pdf_url = _value(paper, 'pdf_url')
        best = _value(paper, 'best_oa_location', {}) or {}
        best_pdf_url = None
        if isinstance(best, dict):
            is_oa = is_oa or bool(best.get('is_oa'))
            best_pdf_url = best.get('pdf_url')
            pdf_url = pdf_url or best_pdf_url
            oa_url = oa_url or best.get('landing_page_url')
        if not (is_oa or oa_url or best_pdf_url):
            return candidates
        status = _value(paper, 'version') or _value(paper, 'oa_status') or _value(paper, 'type')
        for url in (pdf_url, oa_url):
            if url:
                candidates.append({
                    'url': url,
                    'source': 'paper_oa_metadata',
                    'status': status or '',
                    'kind': 'pdf',
                    'tier': 0,
                    'is_direct_pdf': url == pdf_url,
                })
        return candidates

    def _candidate_version(self, paper, candidate, source_path):
        if _value(paper, 'user_provided', False):
            return _version_label(_value(paper, 'version')) or '未确认'
        xml_label = None
        if source_path and source_path.suffix.casefold() == '.xml':
            try:
                xml_label = _xml_version(ET.parse(str(source_path)).getroot())
            except (ET.ParseError, OSError):
                xml_label = None
        return (
            xml_label
            or _version_label(candidate.get('status'), candidate.get('version'))
            or ('预印本' if candidate.get('source') == 'arxiv' else None)
            or _version_label(_value(paper, 'version'), _value(paper, 'type'))
            or ('正式版' if candidate.get('source') == 'europepmc_xml' else None)
            or '未确认'
        )

    def _acquire(self, paper, candidate, ref_no):
        url = candidate.get('url')
        if not isinstance(url, str) or urlparse(url).scheme not in {'http', 'https'}:
            raise ValueError('OA candidate must be an HTTP(S) URL')
        tier = candidate.get('tier', 0)
        tries = 1 if tier in (1, 3) else 2
        if candidate.get('kind') == 'xml':
            text, content_type = self.text_downloader(url, tries=tries)
            if 'html' in str(content_type or '').casefold() and '<article' not in text:
                raise ValueError('XML 候选返回网页')
            if '<article' not in text and '<?xml' not in text:
                raise ValueError('XML 内容不含 article 根节点')
            ET.fromstring(text)
            path = self.output_dir / 'fulltext_ref{}.xml'.format(ref_no)
            _atomic_write(path, text)
            return path
        data, content_type = self.binary_downloader(url, tries=tries)
        data = self.oa_module.validate_pdf_bytes(data, content_type)
        try:
            document = pdfium.PdfDocument(data)
            try:
                if len(document) < 1:
                    raise ValueError('PDF 没有页面')
            finally:
                document.close()
        except Exception as error:
            raise ValueError('PDF 响应不完整或无法解析: {}'.format(str(error)[:200])) from error
        path = self.output_dir / 'oa_pdfs' / 'source_ref{}.pdf'.format(ref_no)
        _atomic_write(path, data)
        return path

    def _load_ocr(self):
        if self.ocr is not None:
            return self.ocr
        try:
            from rapidocr import RapidOCR
        except ImportError as error:
            raise RuntimeError('扫描 PDF 需要 RapidOCR，但当前环境未安装') from error
        self.ocr = RapidOCR()
        return self.ocr

    @staticmethod
    def _ocr_text(result):
        if isinstance(result, str):
            return result.strip()
        if isinstance(result, tuple) and len(result) == 2 and isinstance(result[1], (int, float, list, tuple)):
            result = result[0]
        if isinstance(result, dict):
            values = result.get('txts') or result.get('texts') or result.get('text')
            if isinstance(values, str):
                return values.strip()
            if values:
                return '\n'.join(str(value) for value in values).strip()
        values = getattr(result, 'txts', None) or getattr(result, 'texts', None)
        if values:
            return '\n'.join(str(value) for value in values).strip()
        lines = []
        if isinstance(result, (list, tuple)):
            for item in result:
                if isinstance(item, str):
                    lines.append(item)
                elif isinstance(item, dict) and item.get('text'):
                    lines.append(str(item['text']))
                elif isinstance(item, (list, tuple)) and len(item) >= 2 and isinstance(item[1], str):
                    lines.append(item[1])
        return '\n'.join(lines).strip()

    def _extract_pdf(self, source_path, ref_no, figure_dir):
        page_texts = read_pdf_pages(source_path)
        if not page_texts:
            raise ValueError('PDF 没有页面')
        compact_lengths = [len(re.sub(r'\s+', '', text)) for text in page_texts]
        scanned_pages = [length < 8 for length in compact_lengths]
        ocr_used = False
        failures = []
        figures = []
        if any(scanned_pages):
            ocr = self._load_ocr()
            ocr_texts = list(page_texts)
            with tempfile.TemporaryDirectory(prefix='purpose-landscape-ocr-') as directory:
                for index, needs_ocr in enumerate(scanned_pages):
                    if not needs_ocr:
                        continue
                    image_path = Path(directory) / 'page_{}.png'.format(index + 1)
                    render_pdf_page(source_path, page=index, scale=2.0, output_path=image_path)
                    try:
                        text = self._ocr_text(ocr(str(image_path)))
                    except Exception as error:
                        failures.append('page {} OCR: {}'.format(index + 1, str(error)[:300]))
                        text = ''
                    else:
                        if not text:
                            failures.append('page {} OCR: 未识别到可用文本'.format(index + 1))
                    ocr_texts[index] = '[{}]\n{}'.format(OCR_REVIEW_NOTE, text) if text else ''
            if not any(ocr_texts[index].strip() for index, needs_ocr in enumerate(scanned_pages) if needs_ocr):
                raise FullTextExtractionError('扫描 PDF 经 OCR 仍无可用文本', failures)
            if failures:
                raise FullTextExtractionError('扫描 PDF 部分页面 OCR 失败；未获得完整全文', failures)
            page_texts = ocr_texts
            ocr_used = True
        else:
            for index, text in enumerate(page_texts):
                if not FIGURE_CAPTION.search(text):
                    continue
                figure_path = figure_dir / 'figure_ref{}_page{}.png'.format(ref_no, index + 1)
                try:
                    render_pdf_page(source_path, page=index, scale=2.0, output_path=figure_path)
                    figures.append(figure_path)
                except Exception as error:
                    failures.append('page {} figure render: {}'.format(index + 1, str(error)[:300]))
        return with_page_anchors(page_texts), figures, ocr_used, failures

    def _command(self, source_path, output_path, kind):
        if kind == 'xml':
            args = [sys.executable, str(Path(__file__).resolve()), 'xmltext', str(source_path), '--out', str(output_path)]
        else:
            args = [
                sys.executable, str(Path(__file__).resolve()), 'text', str(source_path),
                '--out', str(output_path), '--engine', 'pypdfium2', '--ocr',
            ]
        return shlex.join(args)

    def verify_quote(self, result, quote):
        """Verify a full-text quote inside one exact page/section, never across anchors."""

        if result.depth != '已读全文' or not isinstance(quote, str) or not _normalized(quote):
            return None
        normalized_quote = _normalized(quote)
        for anchor, body in _segments(result.full_text):
            if normalized_quote in _normalized(body):
                return FullTextLedgerChannel(
                    ref_no=result.ref_no,
                    quote=quote,
                    anchor=anchor,
                    source_url=result.source_url,
                    version=result.version,
                    note=OCR_REVIEW_NOTE if result.ocr_used else '',
                )
        return None

    @staticmethod
    def _attach_channels(ledger_entry, channels):
        if ledger_entry is None:
            return
        if isinstance(ledger_entry, dict):
            ledger_entry['fulltext_channels'] = channels
        else:
            setattr(ledger_entry, 'fulltext_channels', channels)

    def _append_log(self, paper, result):
        log_path = self.output_dir / 'search_log.md'
        if not log_path.exists():
            _atomic_write(log_path, '# Search log\n')
        timestamp = datetime.now(timezone.utc).isoformat()
        failures = result.failures or ['无']
        entry_lines = [
            '',
            '## {} | ref {} | OA full text'.format(timestamp, result.ref_no),
            '- Paper: {}'.format(_normalized(_value(paper, 'title')) or '(untitled)'),
            '- URL: {}'.format(result.source_url or '未找到可用 OA 全文'),
            '- Actual version: {}'.format(result.version),
            '- Reading purpose: {}'.format(result.purpose),
            '- Reading depth: {}'.format(result.depth),
            '- Extraction engine: pypdfium2 text/render/crop; Europe PMC JATS XML; RapidOCR only for scans',
            '- Extraction command: `{}`'.format(result.extraction_command.replace('`', '\\`')),
            '- Full text: {}'.format(result.fulltext_path or '仅摘要'),
            '- Figure PNGs: {}'.format(', '.join(str(path) for path in result.figure_paths) or '无'),
            '- OCR review note: {}'.format(OCR_REVIEW_NOTE if result.ocr_used else '未使用 OCR'),
            '- Data availability: {}'.format(result.data_availability),
        ]
        entry_lines.extend('- Failure: {}'.format(failure) for failure in failures)
        with log_path.open('a', encoding='utf-8') as stream:
            stream.write('\n'.join(entry_lines) + '\n')

    def _finish(self, paper, result, ledger_entry=None):
        if result.depth == '已读全文':
            result.data_availability = _data_availability(result.full_text)
            if result.ocr_used and result.data_availability != '未确认':
                result.data_availability = '{}；{}'.format(OCR_REVIEW_NOTE, result.data_availability)
            result.excerpts = [
                {
                    'quote': channel.quote,
                    'anchor': channel.anchor,
                    'note': channel.note,
                    'channel': channel.channel,
                }
                for channel in result.ledger_channels
            ]
            anchors = [anchor for anchor, _ in _segments(result.full_text)]
            result.non_claim_slots = {
                'data_availability': result.data_availability,
                'section_anchors': anchors,
                'version': result.version,
                'reading_depth': result.depth,
            }
            if result.purpose.startswith('C1'):
                result.writing_reference = {
                    'ref_no': result.ref_no,
                    'depth': result.depth,
                    'version': result.version,
                    'source_url': result.source_url,
                    'fulltext_path': result.fulltext_path,
                    'figure_paths': result.figure_paths,
                    'section_anchors': anchors,
                    'claim_evidence_default': 'abstract',
                }
        else:
            result.data_availability = '未确认'
            result.non_claim_slots = {
                'data_availability': '未确认',
                'version': result.version,
                'reading_depth': result.depth,
            }
            if result.purpose.startswith('C1'):
                result.writing_reference = {
                    'ref_no': result.ref_no,
                    'depth': result.depth,
                    'version': result.version,
                    'source_url': result.source_url,
                    'claim_evidence_default': 'abstract',
                }
        self._attach_channels(ledger_entry, result.ledger_channels)
        self._append_log(paper, result)
        return result

    def read_for_components(
        self,
        paper,
        purpose,
        ledger_entry=None,
        fulltext_quotes=None,
    ):
        """Acquire and read one document; failure always degrades to abstract-only metadata."""

        purpose = str(purpose or '').strip()
        if not purpose:
            raise ValueError('purpose is required for the component-production reading audit')
        ref = _value(paper, 'ref_no', _value(paper, 'ref'))
        if type(ref) is not int or ref <= 0:
            raise ValueError('paper.ref_no must be a positive integer')
        self.output_dir.mkdir(parents=True, exist_ok=True)
        abstract_quote = _value(ledger_entry, 'abstract_quote') if ledger_entry is not None else None
        if abstract_quote is None:
            abstract_quote = _value(paper, 'abstract')
        result = FullTextResult(
            ref_no=ref,
            purpose=purpose,
            original_abstract_quote=abstract_quote,
        )
        source_path = None
        candidate = {}

        if _value(paper, 'user_provided', False) and _value(paper, 'local_pdf'):
            supplied = Path(_value(paper, 'local_pdf')).resolve()
            if not supplied.is_file():
                result.failures.append('用户提供的 PDF 不存在: {}'.format(supplied))
                return self._finish(paper, result, ledger_entry)
            source_path = supplied
            result.source_url = 'user-provided'
            result.source_path = supplied
        else:
            try:
                resolution = self._resolve(paper) or {}
                candidates = list(resolution.get('candidates') or [])
                if not candidates:
                    candidates = self._fallback_paper_candidates(paper)
            except Exception as error:
                candidates = []
                result.failures.append('OA 定位失败: {}'.format(str(error)[:300]))
            if not candidates:
                result.failures.append('未找到开放获取全文；回退到仅摘要')
                return self._finish(paper, result, ledger_entry)
            for candidate in candidates:
                try:
                    source_path = self._acquire(paper, candidate, ref)
                    result.source_url = candidate.get('url')
                    result.source_path = source_path
                    break
                except Exception as error:
                    source_path = None
                    candidate_url = candidate.get('url') or '(missing URL)'
                    result.failures.append('{} {}: {}'.format(
                        candidate.get('source') or 'unknown', candidate_url, str(error)[:300]
                    ))
            if source_path is None:
                return self._finish(paper, result, ledger_entry)

        candidate_version = self._candidate_version(paper, candidate, source_path)
        output_path = self.output_dir / 'fulltext_ref{}.txt'.format(ref)
        kind = 'xml' if source_path.suffix.casefold() == '.xml' else 'pdf'
        result.extraction_command = self._command(source_path, output_path, kind)
        try:
            if kind == 'xml':
                full_text = extract_europepmc_text(source_path)
                figures = []
                ocr_used = False
            else:
                full_text, figures, ocr_used, extraction_failures = self._extract_pdf(
                    source_path, ref, self.output_dir / 'figures'
                )
                result.failures.extend(extraction_failures)
            if not full_text.strip():
                raise ValueError('全文提取结果为空')
            _atomic_write(output_path, full_text + '\n')
            result.depth = '已读全文'
            result.version = candidate_version
            result.fulltext_path = output_path
            result.full_text = full_text
            result.figure_paths = figures
            result.ocr_used = ocr_used
        except FullTextExtractionError as error:
            result.failures.extend(error.failures)
            result.failures.append('全文提取失败: {}'.format(str(error)[:300]))
            return self._finish(paper, result, ledger_entry)
        except Exception as error:
            result.failures.append('全文提取失败: {}'.format(str(error)[:300]))
            return self._finish(paper, result, ledger_entry)

        for quote in fulltext_quotes or []:
            channel = self.verify_quote(result, quote)
            if channel is not None:
                result.ledger_channels.append(channel)
            else:
                result.failures.append('全文引文未通过页/节精确核验: {}'.format(_normalized(quote)[:160]))
        return self._finish(paper, result, ledger_entry)


def main(argv=None):
    parser = argparse.ArgumentParser(description='pypdfium2 full-text extraction and PNG rendering')
    subparsers = parser.add_subparsers(dest='command', required=True)

    text_parser = subparsers.add_parser('text')
    text_parser.add_argument('source')
    text_parser.add_argument('--out', required=True)
    text_parser.add_argument('--engine', choices=['pypdfium2'], default='pypdfium2')
    text_parser.add_argument('--ocr', action='store_true', help='Permit RapidOCR only if the PDF is scanned')

    xml_parser = subparsers.add_parser('xmltext')
    xml_parser.add_argument('source')
    xml_parser.add_argument('--out', required=True)

    info_parser = subparsers.add_parser('info')
    info_parser.add_argument('source')

    render_parser = subparsers.add_parser('render')
    render_parser.add_argument('source')
    render_parser.add_argument('--page', type=int, default=0)
    render_parser.add_argument('--scale', type=float, default=2.0)
    render_parser.add_argument('--out', required=True)

    crop_parser = subparsers.add_parser('crop')
    crop_parser.add_argument('source')
    crop_parser.add_argument('--page', type=int, default=0)
    crop_parser.add_argument('--scale', type=float, default=2.0)
    crop_parser.add_argument('--px', nargs=4, type=float, required=True, metavar=('X', 'Y', 'W', 'H'))
    crop_parser.add_argument('--out', required=True)

    args = parser.parse_args(argv)
    if args.command == 'info':
        print(json.dumps(pdf_info(args.source), ensure_ascii=False, indent=2))
    elif args.command == 'text':
        output = Path(args.out)
        if args.ocr:
            service = FullTextService(output_dir=output.parent)
            text, _, _, failures = service._extract_pdf(Path(args.source), 0, output.parent / 'figures')
            for failure in failures:
                print(failure, file=sys.stderr)
        else:
            text = extract_pdf_text(args.source)
        _atomic_write(output, text + '\n')
    elif args.command == 'xmltext':
        _atomic_write(args.out, extract_europepmc_text(args.source) + '\n')
    elif args.command == 'render':
        render_pdf_page(args.source, page=args.page, scale=args.scale, output_path=args.out)
    elif args.command == 'crop':
        crop_pdf_page(
            args.source, page=args.page, scale=args.scale,
            pixel_rect=args.px, output_path=args.out,
        )
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
