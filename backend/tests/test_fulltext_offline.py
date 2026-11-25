"""Offline-only OA/PDF regression tests; real network access is forbidden."""

import json
import socket
import struct
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

import app.fulltext as fulltext
from app.fulltext import FullTextService


FIXTURE_DIR = Path(__file__).parent / 'fixtures' / 'fulltext'


def _pdf_object(number, body):
    return '{} 0 obj\n{}\nendobj\n'.format(number, body).encode('latin-1')


def make_pdf(page_lines, scanned=False):
    """Build a deterministic two-dimensional PDF without network or PDF writers."""

    page_count = len(page_lines)
    font_number = 3 + page_count * 2
    objects = {}
    page_numbers = []
    for index, lines in enumerate(page_lines):
        page_number = 3 + index * 2
        content_number = page_number + 1
        page_numbers.append(page_number)
        commands = []
        if scanned:
            commands.append('0.75 0.75 0.75 rg 20 30 160 120 re f')
        else:
            for line_index, line in enumerate(lines):
                escaped = line.replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)')
                commands.append(
                    'BT /F1 10 Tf 20 {} Td ({}) Tj ET'.format(180 - line_index * 22, escaped)
                )
            if index == 0:
                # At scale 2 this is top-left pixel rectangle x=40..340, y=200..330.
                commands.append('0.8 0.2 0.2 rg 20 35 150 65 re f')
        stream = ('\n'.join(commands) + '\n').encode('latin-1')
        objects[page_number] = (
            '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] '
            '/Resources << /Font << /F1 {} 0 R >> >> /Contents {} 0 R >>'
        ).format(font_number, content_number)
        objects[content_number] = None
        objects[(content_number, 'stream')] = stream

    objects[1] = '<< /Type /Catalog /Pages 2 0 R >>'
    objects[2] = '<< /Type /Pages /Kids [{}] /Count {} >>'.format(
        ' '.join('{} 0 R'.format(number) for number in page_numbers), page_count
    )
    objects[font_number] = '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>'

    blob = bytearray(b'%PDF-1.4\n%\xe2\xe3\xcf\xd3\n')
    offsets = {}
    for number in sorted(key for key in objects if isinstance(key, int)):
        offsets[number] = len(blob)
        if objects[number] is None:
            stream = objects[(number, 'stream')]
            blob.extend('{} 0 obj\n'.format(number).encode('ascii'))
            blob.extend(b'<< /Length ' + str(len(stream)).encode('ascii') + b' >>\nstream\n')
            blob.extend(stream)
            blob.extend(b'endstream\nendobj\n')
        else:
            blob.extend(_pdf_object(number, objects[number]))
    xref = len(blob)
    blob.extend('xref\n0 {}\n'.format(font_number + 1).encode('ascii'))
    blob.extend(b'0000000000 65535 f \n')
    for number in range(1, font_number + 1):
        blob.extend('{:010d} 00000 n \n'.format(offsets[number]).encode('ascii'))
    blob.extend(
        'trailer\n<< /Size {} /Root 1 0 R >>\nstartxref\n{}\n%%EOF\n'.format(
            font_number + 1, xref
        ).encode('ascii')
    )
    return bytes(blob)


PDF_BYTES = make_pdf([
    ['Offline methods sentence.', 'Figure 1. Synthetic framework only.'],
    ['Offline comparison sentence.', 'Data availability: local fixture only.'],
])
SCANNED_PDF_BYTES = make_pdf([[]], scanned=True)


class FakeTransport:
    def __init__(self, responses=None, pdf=PDF_BYTES, xml=None):
        self.responses = responses or {}
        self.pdf = pdf
        self.xml = xml or (FIXTURE_DIR / 'article.xml').read_text(encoding='utf-8')
        self.calls = []

    def _response(self, kind, url, tries, default):
        self.calls.append((kind, url, tries))
        response = self.responses.get(url, default)
        if isinstance(response, Exception):
            raise response
        return response

    def binary(self, url, timeout=90, tries=2):
        return self._response('binary', url, tries, (self.pdf, 'application/pdf'))

    def text(self, url, timeout=40, tries=2):
        return self._response('xml', url, tries, (self.xml, 'application/xml'))


class FakeOCR:
    def __init__(self, text='Offline scanned sentence requiring review.'):
        self.text = text
        self.calls = []

    def __call__(self, image_path):
        self.calls.append(image_path)
        return [([[0, 0], [100, 0], [100, 20], [0, 20]], self.text, 0.99)]


def make_paper(candidates, ref_no=31, abstract='Only the original abstract supports claims.'):
    return SimpleNamespace(
        ref_no=ref_no,
        doi='10.5555/offline.fixture',
        arxiv_id=None,
        title='Offline synthetic fixture',
        abstract=abstract,
        type='article',
        resolution={'candidates': candidates},
    )


def candidate(tier, kind='pdf', status='published', source=None):
    return {
        'url': 'https://offline.example.test/tier{}.{}'.format(tier, 'xml' if kind == 'xml' else 'pdf'),
        'source': source or 'offline_tier{}'.format(tier),
        'status': status,
        'kind': kind,
        'tier': tier,
        'is_direct_pdf': kind == 'pdf',
    }


def make_service(tmp_path, paper, transport, ocr=None):
    return FullTextService(
        output_dir=tmp_path,
        resolver=lambda record: deepcopy(record.resolution),
        binary_downloader=transport.binary,
        text_downloader=transport.text,
        ocr=ocr,
    )


def png_size(path):
    data = Path(path).read_bytes()
    assert data.startswith(b'\x89PNG\r\n\x1a\n')
    return struct.unpack('>II', data[16:24])


@pytest.fixture(autouse=True)
def forbid_real_network(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError('Real network access is forbidden in offline full-text tests')

    monkeypatch.setattr(socket, 'create_connection', denied)
    monkeypatch.setattr(socket.socket, 'connect', denied)
    monkeypatch.setattr(socket.socket, 'connect_ex', denied)


@pytest.mark.parametrize('payload,content_type', [
    (b'<html><title>Landing page</title></html>', 'text/html'),
    (b'<!doctype html><meta http-equiv="refresh" content="0;url=download">', 'text/html'),
    (b'<html><title>403 Forbidden</title></html>', 'text/html'),
    (PDF_BYTES[:len(PDF_BYTES) // 2], 'application/pdf'),
])
def test_service_never_persists_html_error_or_truncated_pdf(tmp_path, payload, content_type):
    url = 'https://offline.example.test/tier0.pdf'
    transport = FakeTransport(responses={url: (payload, content_type)})
    paper = make_paper([candidate(0)])
    service = make_service(tmp_path, paper, transport)

    result = service.read_for_components(paper, purpose='C2_COMPARISON')

    assert result.depth == '仅摘要'
    assert result.fulltext_path is None
    assert result.original_abstract_quote == paper.abstract
    assert not (tmp_path / 'oa_pdfs' / 'source_ref31.pdf').exists()
    assert not list(tmp_path.rglob('*.pdf'))


def test_oa_downloader_rejects_truncated_pdf_before_writing(tmp_path, monkeypatch):
    monkeypatch.setattr(
        fulltext.oa_pdf, 'http_binary',
        lambda url, tries=2: (PDF_BYTES[:len(PDF_BYTES) // 2], 'application/pdf'),
    )
    resolution = {'doi': 'offline', 'candidates': [candidate(0)]}

    assert fulltext.oa_pdf.download(resolution, tmp_path) is None
    assert not list(tmp_path.rglob('*.pdf'))


def test_oa_downloader_accepts_complete_local_pdf(tmp_path, monkeypatch):
    monkeypatch.setattr(
        fulltext.oa_pdf, 'http_binary', lambda url, tries=2: (PDF_BYTES, 'application/pdf')
    )
    resolution = {'doi': 'offline', 'candidates': [candidate(0)]}

    path = fulltext.oa_pdf.download(resolution, tmp_path, quiet=True)

    assert path is not None
    assert Path(path).read_bytes() == PDF_BYTES


def test_tier0_to_tier3_fallback_single_try_and_abstract_degradation(tmp_path):
    candidates = [
        candidate(0),
        candidate(1, source='low_success_publisher'),
        candidate(2, kind='xml', status='PMC-OFFLINE'),
        candidate(3, source='pmc_pdf'),
    ]
    responses = {
        candidates[0]['url']: (b'<html>landing</html>', 'text/html'),
        candidates[1]['url']: RuntimeError('offline simulated HTTP 403'),
        candidates[2]['url']: ('<html>XML landing</html>', 'text/html'),
        candidates[3]['url']: (PDF_BYTES[:100], 'application/pdf'),
    }
    transport = FakeTransport(responses=responses)
    paper = make_paper(candidates)
    ledger = SimpleNamespace(abstract_quote=paper.abstract)
    service = make_service(tmp_path, paper, transport)

    result = service.read_for_components(
        paper,
        purpose='B_TECHNICAL_ROUTE',
        ledger_entry=ledger,
        fulltext_quotes=['Fabricated formula and reproduction detail.'],
    )

    assert [call[:2] for call in transport.calls] == [
        ('binary', candidates[0]['url']),
        ('binary', candidates[1]['url']),
        ('xml', candidates[2]['url']),
        ('binary', candidates[3]['url']),
    ]
    assert [call[2] for call in transport.calls] == [2, 1, 2, 1]
    assert result.depth == '仅摘要'
    assert result.version == '未确认'
    assert result.data_availability == '未确认'
    assert result.full_text == ''
    assert result.fulltext_path is None
    assert result.figure_paths == []
    assert result.ledger_channels == []
    assert result.excerpts == []
    assert ledger.abstract_quote == paper.abstract
    assert ledger.fulltext_channels == []
    assert not list(tmp_path.rglob('*.pdf'))
    assert not list(tmp_path.rglob('*.png'))
    assert not list(tmp_path.rglob('fulltext_ref*.txt'))
    assert len(result.failures) == 4
    assert any('XML 候选返回网页' in failure for failure in result.failures)
    log = (tmp_path / 'search_log.md').read_text(encoding='utf-8')
    assert '仅摘要' in log
    assert 'offline simulated HTTP 403' in log


def test_resolver_orders_tier0_tier1_tier2_tier3_with_fake_metadata(monkeypatch):
    work = {
        'title': 'Offline metadata fixture',
        'open_access': {
            'is_oa': True,
            'oa_url': 'https://repository.example.test/record.pdf',
            'oa_status': 'published',
        },
        'best_oa_location': {
            'pdf_url': 'https://onlinelibrary.wiley.com/offline.pdf',
            'version': 'accepted',
        },
        'locations': [{
            'is_oa': True,
            'pdf_url': 'https://pmc.ncbi.nlm.nih.gov/articles/PMC9/pdf/offline.pdf',
            'version': 'published',
        }],
    }
    monkeypatch.setattr(fulltext.oa_pdf, 'lookup_openalex_work', lambda doi, email=None: work)
    monkeypatch.setattr(fulltext.oa_pdf, 'europepmc_locate', lambda doi: 'PMC9')
    monkeypatch.setattr(
        fulltext.oa_pdf, 'http_json',
        lambda url, **kwargs: {
            'title': 'Offline metadata fixture',
            'isOpenAccess': False,
            'openAccessPdf': {},
            'externalIds': {},
        },
    )

    resolution = fulltext.oa_pdf.resolve(doi='10.5555/offline.fixture')

    assert [item['tier'] for item in resolution['candidates']] == [0, 1, 2, 3]
    assert [item['kind'] for item in resolution['candidates']] == ['pdf', 'pdf', 'xml', 'pdf']
    assert '只试一次' in resolution['candidates'][1]['note']
    assert '需浏览器验证' in resolution['candidates'][3]['note']


@pytest.mark.parametrize('status,expected', [
    ('submitted', '预印本'),
    ('accepted', '接收稿'),
    ('published', '正式版'),
])
def test_each_successful_pdf_version_is_labeled_separately(tmp_path, status, expected):
    transport = FakeTransport()
    paper = make_paper([candidate(0, status=status)])
    service = make_service(tmp_path, paper, transport)

    result = service.read_for_components(paper, purpose='C1_WRITING_REFERENCE')

    assert result.depth == '已读全文'
    assert result.version == expected
    assert result.writing_reference['version'] == expected
    assert result.writing_reference['depth'] == '已读全文'
    assert result.claim_evidence_default == 'abstract'


def test_pdf_info_render_crop_text_and_page_anchors(tmp_path):
    source = tmp_path / 'synthetic.pdf'
    source.write_bytes(PDF_BYTES)
    rendered = tmp_path / 'page1.png'
    cropped = tmp_path / 'crop.png'

    info = fulltext.pdf_info(source)
    fulltext.render_pdf_page(source, page=0, scale=2, output_path=rendered)
    fulltext.crop_pdf_page(
        source, page=0, scale=2, pixel_rect=(40, 200, 60, 40), output_path=cropped
    )
    text = fulltext.extract_pdf_text(source)

    assert info['page_count'] == 2
    assert info['pages'] == [
        {'page': 1, 'width': 200.0, 'height': 200.0},
        {'page': 2, 'width': 200.0, 'height': 200.0},
    ]
    assert png_size(rendered) == (400, 400)
    assert png_size(cropped) == (60, 40)
    with Image.open(cropped) as image:
        red, green, blue = image.convert('RGB').getpixel((30, 20))
        assert red > 150 and green < 100 and blue < 100
    assert text.splitlines()[0] == '=== page 1 ==='
    assert '\n\n=== page 2 ===\n' in text
    assert 'Offline methods sentence.' in text
    assert 'Offline comparison sentence.' in text


def test_info_cli_outputs_local_pdf_metadata(tmp_path, capsys):
    source = tmp_path / 'synthetic.pdf'
    source.write_bytes(PDF_BYTES)

    assert fulltext.main(['info', str(source)]) == 0
    output = json.loads(capsys.readouterr().out)

    assert output['page_count'] == 2
    assert output['pages'][0] == {'page': 1, 'width': 200.0, 'height': 200.0}


def test_jats_section_anchors_and_version_are_preserved(tmp_path):
    xml_source = FIXTURE_DIR / 'article.xml'
    text = fulltext.extract_europepmc_text(xml_source)

    assert [anchor for anchor, _ in fulltext._segments(text)] == [
        'sec Methods', 'sec Cohort', 'sec Results', 'sec Data availability',
    ]
    assert 'Exact offline XML methods sentence.' in text
    assert 'Nested offline section sentence.' in text
    assert 'Reference text must not enter the full text.' not in text
    assert fulltext._xml_version(fulltext.ET.parse(str(xml_source)).getroot()) == '接收稿'


def test_born_digital_pdf_does_not_invoke_ocr(tmp_path):
    transport = FakeTransport()
    ocr = FakeOCR()
    paper = make_paper([candidate(0)])
    service = make_service(tmp_path, paper, transport, ocr=ocr)

    result = service.read_for_components(paper, purpose='D_READING_CARD')

    assert result.depth == '已读全文'
    assert result.ocr_used is False
    assert ocr.calls == []
    assert '待人工核对' not in result.full_text


def test_scanned_pdf_uses_ocr_and_marks_text_for_human_review(tmp_path):
    transport = FakeTransport(pdf=SCANNED_PDF_BYTES)
    ocr = FakeOCR()
    paper = make_paper([candidate(0)])
    service = make_service(tmp_path, paper, transport, ocr=ocr)

    result = service.read_for_components(
        paper, purpose='D_READING_CARD', fulltext_quotes=[ocr.text]
    )

    assert result.depth == '已读全文'
    assert result.ocr_used is True
    assert len(ocr.calls) == 1
    assert result.full_text.startswith('=== page 1 ===\n[OCR 识别，待人工核对]')
    assert result.ledger_channels[0].note == 'OCR 识别，待人工核对'


def test_failed_fulltext_never_invents_figures_or_reproduction_details(tmp_path):
    transport = FakeTransport(
        responses={'https://offline.example.test/tier0.pdf': RuntimeError('offline unavailable')}
    )
    paper = make_paper([candidate(0)])
    ledger = SimpleNamespace(abstract_quote=paper.abstract)
    service = make_service(tmp_path, paper, transport)

    result = service.read_for_components(
        paper,
        purpose='B_TECHNICAL_ROUTE',
        ledger_entry=ledger,
        fulltext_quotes=[
            'Figure 9 shows an invented result.',
            'The fabricated equation exactly reproduces the experiment.',
        ],
    )

    assert result.depth == '仅摘要'
    assert result.original_abstract_quote == paper.abstract
    assert result.claim_evidence_default == 'abstract'
    assert result.non_claim_slots == {
        'data_availability': '未确认',
        'version': '未确认',
        'reading_depth': '仅摘要',
    }
    assert result.ledger_channels == []
    assert ledger.fulltext_channels == []
    assert result.figure_paths == []
    assert not list(tmp_path.rglob('*.png'))
