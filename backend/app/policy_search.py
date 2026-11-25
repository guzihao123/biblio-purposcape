"""Official policy material collection and the separate [M] evidence channel."""

import re
import shutil
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
            source_type != 'republication'
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
        )
        self.materials.append(material)
        self._archive_source(source, citation)
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
        elif source.get('html'):
            (target_dir / '{}.html'.format(name)).write_text(source['html'], encoding='utf-8')

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
