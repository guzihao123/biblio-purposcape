"""Official policy material collection and the separate [M] evidence channel."""

import re
import shutil
import tempfile
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse

from docx import Document

from app.fulltext import FullTextExtractionError, FullTextService, _segments


class _BlockHTMLParser(HTMLParser):
    BLOCKS = {'p', 'h1', 'h2', 'h3', 'h4', 'li', 'div', 'section', 'article'}

    def __init__(self):
        super().__init__()
        self.blocks = []
        self.current_tag = None
        self.current_parts = []
        self.hidden = 0

    def _flush(self):
        if self.current_tag is not None:
            text = ' '.join(''.join(self.current_parts).split())
            if text:
                self.blocks.append((self.current_tag, text))
            self.current_tag = None
            self.current_parts = []

    def handle_starttag(self, tag, attrs):
        if tag in {'script', 'style', 'noscript'}:
            self.hidden += 1
        if tag in self.BLOCKS:
            self._flush()
            self.current_tag = tag
            self.current_parts = []

    def handle_endtag(self, tag):
        if tag in {'script', 'style', 'noscript'} and self.hidden:
            self.hidden -= 1
        if tag in self.BLOCKS:
            self._flush()

    def handle_data(self, data):
        if not self.hidden and self.current_tag is not None:
            self.current_parts.append(data)

    def close(self):
        super().close()
        self._flush()


_POLICY_EXCERPT_HINTS = (
    '应当', '必须', '要求', '目标', '到20', '达到', '覆盖', '保障', '支持', '纳入',
    '实施', '比例', '万元', '不得', '禁止', 'percent', 'shall',
)
_PLAIN_SENTENCE_SPLIT = re.compile(r'(?<=[。！？!?；;\n])')


def _plain_text_excerpts(raw, limit=8):
    """Return verbatim sentence excerpts with positional anchors."""
    text = '\n'.join(line.rstrip() for line in str(raw or '').splitlines()).strip()
    if not text:
        return []
    sentences = []
    for piece in _PLAIN_SENTENCE_SPLIT.split(text):
        sentence = ' '.join(piece.split())
        if sentence:
            sentences.append(sentence)
    if not sentences:
        return []
    candidates = list(enumerate(sentences, 1))
    prioritized = [
        item for item in candidates
        if any(hint in item[1] for hint in _POLICY_EXCERPT_HINTS)
    ]
    chosen = sorted((prioritized or candidates)[:limit])
    return [PolicyExcerpt(sentence, '文本 第{}句'.format(index)) for index, sentence in chosen]


@dataclass(frozen=True)
class PolicyExcerpt:
    text: str
    anchor: str


@dataclass
class PolicyMaterial:
    accepted: bool
    reason: str = ''
    citation: str = ''
    title: str = ''
    issuer: str = ''
    document_number: str = ''
    issued_at: str = ''
    published_at: str = ''
    source_url: str = ''
    source_path: str = ''
    source_type: str = 'official'
    excerpts: list = field(default_factory=list)
    excerpt_note: str = ''
    included_in_n_pool: bool = False
    source_link: str = ''
    repost_note: str = ''
    archived_path: str = ''


class PolicyService:
    def __init__(self, output_dir, discovery=None, fetcher=None, ocr=None):
        self.output_dir = Path(output_dir).resolve()
        self.discovery = discovery
        self.fetcher = fetcher
        self.ocr = ocr
        self.materials = []

    @staticmethod
    def _official_url(url):
        hostname = (urlparse(url).hostname or '').casefold()
        return hostname == 'gov.cn' or hostname.endswith('.gov.cn')

    def search_and_collect(self, query):
        if self.discovery is None:
            return PolicyMaterial(False, '未配置政策搜索服务，无法确认官方原文覆盖范围')
        if self.fetcher is None:
            return PolicyMaterial(False, '搜索仅用于发现，未配置官方原文抓取与核验器')
        candidates = self.discovery(query)
        candidates.sort(key=lambda item: 0 if item.get('source_type', 'official') == 'official' else 1)
        result = PolicyMaterial(False, '未找到可核验的官方政策原文')
        for candidate in candidates:
            fetched = self.fetcher(candidate)
            result = self.collect(fetched)
            if result.accepted:
                return result
        return result

    def collect(self, source):
        source = dict(source)
        user_provided = bool(source.get('user_provided'))
        if user_provided and not source.get('local_path'):
            return PolicyMaterial(False, '用户自有材料必须提供本地文件，不能用非官方网页代替')
        if not user_provided and not self._official_url(source.get('url', '')):
            return PolicyMaterial(False, '政策原文必须来自官方页面或 gov.cn 转载')
        source_type = source.get('source_type')
        if source.get('is_republication') is True:
            source_type = 'republication'
        elif source_type is None and 'is_republication' in source:
            source_type = 'official'
        if user_provided:
            source_type = 'user_material'
        if source_type not in {'official', 'republication', 'user_material'}:
            return PolicyMaterial(False, '必须注明来源类型：官方原文、gov.cn 转载或用户自有材料')
        required = (source.get('issuer'), source.get('document_number'), source.get('issued_at'))
        if not all(value and str(value).strip() for value in required):
            return PolicyMaterial(False, '发布机构、文号和成文日期为政策材料三要素，缺项必须人工补齐')
        if source_type == 'republication' and not str(source.get('published_at') or '').strip():
            return PolicyMaterial(False, '转载政策须同时记录成文日期与转载发布日期')
        if (
            source_type not in {'republication', 'user_material'}
            and source.get('published_at')
            and source['published_at'] != source['issued_at']
        ):
            return PolicyMaterial(False, '成文日期与发布日期不同，可能为转载，须提供官方原文链接并标为转载')
        if source_type == 'republication':
            if not source.get('original_url'):
                return PolicyMaterial(False, '转载政策须记录官方原文链接 original_url')
            if self.fetcher is None:
                return PolicyMaterial(False, '转载政策须使用官方原文抓取器核验转载关系')
            original = self.fetcher({'url': source['original_url']})
            if (
                original.get('title') != source.get('title')
                or original.get('document_number') != source.get('document_number')
            ):
                return PolicyMaterial(False, '转载件与官方原文的标题或文号不一致')

        try:
            excerpts, excerpt_note = self._extract(source)
        except (OSError, ValueError, FullTextExtractionError) as error:
            return PolicyMaterial(False, '政策原文解析失败：{}'.format(str(error)[:300]))
        if not excerpts:
            return PolicyMaterial(False, '未提取到可引用的政策原文')

        citation = '[M{}]'.format(len(self.materials) + 1)
        material = PolicyMaterial(
            True,
            citation=citation,
            title=source.get('title', ''),
            issuer=source['issuer'],
            document_number=source['document_number'],
            issued_at=source['issued_at'],
            published_at=source.get('published_at', ''),
            source_url='' if source_type == 'user_material' else source.get('url', ''),
            source_path=source.get('local_path', ''),
            source_type=source_type,
            excerpts=excerpts,
            excerpt_note=excerpt_note,
            source_link=str(source.get('source_link') or '').strip(),
            repost_note=str(source.get('repost_note') or '').strip(),
        )
        self.materials.append(material)
        archived = self._archive_source(source, citation)
        material.archived_path = str(archived) if archived else ''
        self._append_listing(material, source_type == 'republication')
        return material

    def _extract(self, source):
        kind = source.get('content_type') or Path(source.get('local_path', '')).suffix.casefold().lstrip('.')
        if kind in {'html', 'htm'} or (source.get('html') and not source.get('local_path')):
            raw = Path(source['local_path']).read_text(encoding='utf-8') if source.get('local_path') else source.get('html', '')
            parser = _BlockHTMLParser()
            parser.feed(raw)
            parser.close()
            excerpts = []
            for index, (tag, text) in enumerate(parser.blocks, 1):
                anchor = 'HTML 第{}段'.format(index) if tag == 'p' else 'HTML {}（{}）'.format(tag, text)
                excerpts.append(PolicyExcerpt(text, anchor))
            if not excerpts and '<' not in raw and '>' not in raw:
                text = ' '.join(raw.split())
                if text:
                    excerpts.append(PolicyExcerpt(text, '文本 第1段'))
            return excerpts, ''
        if kind == 'docx':
            document = Document(source['local_path'])
            excerpts = [
                PolicyExcerpt(' '.join(paragraph.text.split()), 'docx 第{}段'.format(index))
                for index, paragraph in enumerate(document.paragraphs, 1)
                if paragraph.text.strip()
            ]
            return excerpts, ''
        if kind in {'txt', 'text', 'md', 'markdown'}:
            raw = Path(source['local_path']).read_text(encoding='utf-8')
            return _plain_text_excerpts(raw), ''
        if kind == 'pdf':
            service = FullTextService(self.output_dir / 'policy_pdfs', ocr=source.get('ocr') or self.ocr)
            full_text, _, ocr_used, _ = service._extract_pdf(
                Path(source['local_path']), 1, self.output_dir / 'policy_pdfs' / 'figures'
            )
            excerpts = []
            for anchor, body in _segments(full_text):
                page = int(anchor.split()[1])
                text = re.sub(r'^\[OCR 识别，待人工核对\]\s*', '', body).strip()
                if text:
                    excerpts.append(PolicyExcerpt(text, 'page {}'.format(page)))
            return excerpts, 'OCR 识别，待人工核对' if ocr_used else ''
        raise ValueError('不支持的政策材料格式：{}'.format(kind or '未知'))

    def _archive_source(self, source, citation):
        target_dir = self.output_dir / 'policy_docs'
        target_dir.mkdir(parents=True, exist_ok=True)
        name = citation.strip('[]')
        local_path = source.get('local_path')
        if local_path:
            target = target_dir / '{}_{}'.format(name, Path(local_path).name)
            if Path(local_path).resolve() != target.resolve():
                shutil.copyfile(local_path, target)
            return target
        elif source.get('html'):
            target = target_dir / '{}.html'.format(name)
            target.write_text(source['html'], encoding='utf-8')
            return target
        return None

    def _append_listing(self, material, is_republication):
        path = self.output_dir / '非论文材料清单.md'
        if not path.exists():
            path.write_text('# 非论文材料清单\n\n[M] 与论文 [n] 分通道著录，不进入论文池或 verify_delivery.py 的 [n] 检查。\n', encoding='utf-8')
        lines = [
            '\n## {} {}\n'.format(material.citation, material.title),
            '- 发布机构：{}'.format(material.issuer),
            '- 文号：{}'.format(material.document_number),
            '- 成文日期：{}'.format(material.issued_at),
        ]
        if is_republication:
            lines.append('- 转载发布日期：{}'.format(material.published_at))
        elif material.published_at:
            lines.append('- 发布日期：{}'.format(material.published_at))
        lines.append('- 链接：{}'.format(material.source_link or material.source_url or '未提供'))
        if material.repost_note:
            lines.append('- 转载注明：{}'.format(material.repost_note))
        if material.source_type == 'user_material':
            lines.append('- 来源：用户自有材料（非官方检索证据）')
        elif material.source_url:
            lines.append('- 官方来源：{}'.format(material.source_url))
        if material.source_path:
            lines.append('- 原件：policy_docs/{}_{}'.format(material.citation.strip('[]'), Path(material.source_path).name))
        if material.excerpt_note:
            lines.append('- 识别说明：{}'.format(material.excerpt_note))
        lines.append('- 关键句逐字摘录：')
        for excerpt in material.excerpts:
            lines.append('  - {}：{}'.format(excerpt.anchor, excerpt.text))
        with path.open('a', encoding='utf-8') as handle:
            handle.write('\n'.join(lines) + '\n')


# B-mode input bridge. It only parses text the user pasted or a URL the user
# explicitly supplied; it never discovers policy pages by itself.
_METADATA_LABELS = {
    '标题': 'title', '名称': 'title',
    '发布机构': 'issuer', '机构': 'issuer', '发文机关': 'issuer',
    '文号': 'document_number', '发文字号': 'document_number',
    '成文日期': 'issued_at',
    '发布日期': 'published_at', '转载发布日期': 'published_at',
    '链接': 'link', '来源链接': 'link', '网址': 'link', 'url': 'link',
    '原文链接': 'original_url', '官方原文链接': 'original_url',
    '来源': 'source', '转载': 'repost',
    '正文': 'body_start',
}
_METADATA_LINE = re.compile(r'^\s*(?:[-*]\s*)?([^:：]{1,12})\s*[:：]\s*(.*?)\s*$')
_BLOCK_SEPARATOR = re.compile(r'^\s*(?:-{3,}|={3,})\s*$', re.M)
_BARE_URL = re.compile(r'^https?://\S+$', re.I)


@dataclass
class MaterialCollection:
    output_dir: Path
    items: list = field(default_factory=list)
    rejected: list = field(default_factory=list)

    @property
    def listing_text(self):
        path = Path(self.output_dir) / '非论文材料清单.md'
        return path.read_text(encoding='utf-8') if path.exists() else ''

    @property
    def originals(self):
        return {
            Path(item['original_path']).name: Path(item['original_path'])
            for item in self.items if item.get('original_path')
        }


def _material_payload(material):
    return {
        'citation': material.citation,
        'title': material.title,
        'issuer': material.issuer,
        'document_number': material.document_number,
        'issued_at': material.issued_at,
        'published_at': material.published_at,
        'link': material.source_link or material.source_url or '未提供',
        'source_type': material.source_type,
        'repost_note': material.repost_note,
        'excerpt_note': material.excerpt_note,
        'excerpts': [{'text': item.text, 'anchor': item.anchor} for item in material.excerpts],
        'original_path': material.archived_path,
        'included_in_n_pool': material.included_in_n_pool,
    }


def _parse_material_block(block):
    metadata = {}
    body_lines = []
    stripped = str(block or '').strip()
    if _BARE_URL.match(stripped):
        return {'link': stripped}, ''
    for line in str(block or '').splitlines():
        if not line.strip():
            continue
        match = _METADATA_LINE.match(line)
        key = _METADATA_LABELS.get(match.group(1).strip().casefold()) if match else None
        if key:
            if key == 'body_start':
                continue
            metadata[key] = match.group(2).strip()
            continue
        body_lines.append(line.rstrip())
    return metadata, '\n'.join(body_lines).strip()


def collect_b_materials(output_dir, raw_input, fetcher=None):
    """Collect B-mode [M] materials from pasted text or explicitly given official URLs.

    No discovery/search is performed. A bare link is only fetched when the
    caller supplies an authorized, URL-targeted fetcher.
    """
    output_dir = Path(output_dir).resolve()
    collection = MaterialCollection(output_dir=output_dir)
    raw = str(raw_input or '').strip()
    if not raw:
        return collection
    service = PolicyService(output_dir, fetcher=fetcher)
    for index, block in enumerate(_BLOCK_SEPARATOR.split(raw), 1):
        metadata, body = _parse_material_block(block)
        metadata_keys = ('title', 'issuer', 'document_number', 'issued_at')
        link = metadata.get('link', '')
        if not body and link and not any(metadata.get(key) for key in metadata_keys):
            if fetcher is None:
                collection.rejected.append(
                    '第{}段：仅提供链接 {}，未粘贴全文且未配置授权抓取器；未发起网络请求'.format(index, link)
                )
                continue
            if not PolicyService._official_url(link):
                collection.rejected.append(
                    '第{}段：链接 {} 不是 gov.cn 官方页面，未抓取'.format(index, link)
                )
                continue
            try:
                result = service.collect(fetcher({'url': link}))
            except Exception as error:
                collection.rejected.append(
                    '第{}段：官方链接抓取失败：{}'.format(index, str(error)[:200])
                )
                continue
            if result.accepted:
                collection.items.append(_material_payload(result))
            else:
                collection.rejected.append('第{}段：{}'.format(index, result.reason))
            continue

        if not body:
            collection.rejected.append('第{}段：未提供可摘录的原文正文'.format(index))
            continue
        missing = [
            label for label, key in (
                ('发布机构', 'issuer'), ('文号', 'document_number'), ('成文日期', 'issued_at'),
            ) if not metadata.get(key)
        ]
        if missing:
            collection.rejected.append(
                '第{}段：缺政策三要素（{}），已跳过，未编造元数据'.format(index, '、'.join(missing))
            )
            continue

        source_note = metadata.get('source', '')
        repost_flag = str(metadata.get('repost') or '').strip().casefold() in {
            '是', 'yes', 'true', '1', '转载',
        }
        repost = bool(
            repost_flag
            or ('转载' in source_note and '非转载' not in source_note)
            or metadata.get('original_url')
            or (
                metadata.get('published_at')
                and metadata['published_at'] != metadata['issued_at']
            )
        )
        repost_note = ''
        if repost:
            parts = ['gov.cn 转载文本（按用户粘贴内容著录，未联网核验转载关系）']
            if metadata.get('original_url'):
                parts.append('官方原文链接：{}'.format(metadata['original_url']))
            if metadata.get('published_at'):
                parts.append('转载发布日期：{}'.format(metadata['published_at']))
            if source_note:
                parts.append('来源注明：{}'.format(source_note))
            repost_note = '；'.join(parts)

        title = metadata.get('title') or link or '用户材料第{}段'.format(index)
        slug = re.sub(r'[^\w\u4e00-\u9fff.\-]', '_', title)[:48] or 'material_{}'.format(index)
        with tempfile.TemporaryDirectory(prefix='bmaterials-') as temp_dir:
            local_path = Path(temp_dir) / '{}.txt'.format(slug)
            local_path.write_text(body, encoding='utf-8')
            result = service.collect({
                'user_provided': True,
                'local_path': str(local_path),
                'content_type': 'txt',
                'title': title,
                'issuer': metadata['issuer'],
                'document_number': metadata['document_number'],
                'issued_at': metadata['issued_at'],
                'published_at': metadata.get('published_at', ''),
                'source_link': link,
                'repost_note': repost_note,
                'url': link,
            })
        if result.accepted:
            collection.items.append(_material_payload(result))
        else:
            collection.rejected.append('第{}段：{}'.format(index, result.reason))
    return collection
