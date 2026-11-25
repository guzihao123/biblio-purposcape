import os
import shlex
import struct
import subprocess
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.fulltext import FullTextService, crop_pdf_page, render_pdf_page


def _pdf_object(number, body):
    return '{} 0 obj\n{}\nendobj\n'.format(number, body).encode('latin-1')


def make_pdf(page_lines, scanned=False):
    """Build a small, valid local PDF without a PDF-writing dependency."""

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
        if number in objects and objects[number] is None:
            stream = objects[(number, 'stream')]
            body = b'<< /Length ' + str(len(stream)).encode('ascii') + b' >>\nstream\n' + stream + b'endstream'
            blob.extend('{} 0 obj\n'.format(number).encode('ascii'))
            blob.extend(body)
            blob.extend(b'\nendobj\n')
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
    [
        'First page methods use a reproducible approach.',
        'Figure 1. Example framework for the study.',
    ],
    [
        'Comparison method uses two cohorts.',
        'Data availability: Data are available at example.org dataset.',
    ],
])
SCANNED_PDF_BYTES = make_pdf([[], []], scanned=True)
JATS_XML = '''<?xml version="1.0" encoding="UTF-8"?>
<article xmlns:xlink="http://www.w3.org/1999/xlink">
  <front><journal-meta><journal-title>Fixture Journal</journal-title></journal-meta>
    <article-meta><title-group><article-title>XML fixture</article-title></title-group>
      <article-version>accepted manuscript</article-version>
    </article-meta>
  </front>
  <body>
    <sec id="methods"><title>Methods</title><p>Exact XML methods quotation for verification.</p>
      <sec id="nested"><title>Cohort</title><p>Nested section text remains available.</p></sec>
    </sec>
  </body>
  <back><sec id="data"><title>Data availability</title><p>XML data are available on request.</p></sec>
    <ref-list><ref><mixed-citation>Reference text is not body text.</mixed-citation></ref></ref-list>
  </back>
</article>
'''


class FakeDownloads:
    def __init__(self, pdf=PDF_BYTES, xml=JATS_XML):
        self.pdf = pdf
        self.xml = xml
        self.binary_urls = []
        self.text_urls = []
        self.failures = {}

    def binary(self, url, timeout=90, tries=2):
        self.binary_urls.append(url)
        failure = self.failures.get(url)
        if failure:
            raise failure
        return self.pdf, 'application/pdf'

    def text(self, url, timeout=40, tries=2):
        self.text_urls.append(url)
        failure = self.failures.get(url)
        if failure:
            raise failure
        return self.xml, 'application/xml'


class FakeOCR:
    def __init__(self, text='扫描全文。Data availability: scanned data are unavailable.'):
        self.text = text
        self.calls = []

    def __call__(self, image_path):
        self.calls.append(image_path)
        return [([[0, 0], [100, 0], [100, 20], [0, 20]], self.text, 0.99)]


def make_paper(ref_no=7, status='published', source='openalex', abstract=None):
    return SimpleNamespace(
        ref_no=ref_no,
        doi='10.5555/fixture.7',
        arxiv_id=None,
        title='Local OA fixture',
        abstract=abstract if abstract is not None else 'Abstract claim sentence stays authoritative.',
        type='article',
        resolution={
            'doi': '10.5555/fixture.7',
            'title': 'Local OA fixture',
            'candidates': [{
                'url': 'https://oa.example.test/article.pdf',
                'source': source,
                'status': status,
                'kind': 'pdf',
                'tier': 0,
                'is_direct_pdf': True,
            }],
        },
    )


@pytest.fixture
def downloads():
    return FakeDownloads()


@pytest.fixture
def service(tmp_path, downloads):
    return FullTextService(
        output_dir=tmp_path,
        resolver=lambda paper: deepcopy(paper.resolution),
        binary_downloader=downloads.binary,
        text_downloader=downloads.text,
    )


@pytest.fixture
def oa_paper():
    return make_paper()


@pytest.fixture
def ledger_entry(oa_paper):
    return SimpleNamespace(abstract_quote=oa_paper.abstract)


@pytest.fixture
def paywalled_paper():
    paper = make_paper(ref_no=9)
    paper.resolution = {'candidates': []}
    return paper


def png_size(path):
    data = Path(path).read_bytes()
    assert data.startswith(b'\x89PNG\r\n\x1a\n')
    return struct.unpack('>II', data[16:24])


def test_full_text_marks_version_and_preserves_abstract_claims(service, oa_paper, ledger_entry):
    result = service.read_for_components(
        oa_paper, purpose='C2_COMPARISON', ledger_entry=ledger_entry
    )

    assert result.depth == '已读全文'
    assert result.version in {'预印本', '接收稿', '正式版'}
    assert result.version == '正式版'
    assert ledger_entry.abstract_quote == result.original_abstract_quote
    assert result.claim_evidence_default == 'abstract'
    assert result.fulltext_path.name == 'fulltext_ref7.txt'
    text = result.fulltext_path.read_text(encoding='utf-8')
    assert '=== page 1 ===' in text
    assert '=== page 2 ===' in text
    assert len(result.figure_paths) == 1
    assert png_size(result.figure_paths[0]) == (400, 400)
    assert result.source_url == 'https://oa.example.test/article.pdf'
    log = (service.output_dir / 'search_log.md').read_text(encoding='utf-8')
    for expected in (
        'https://oa.example.test/article.pdf', '正式版', 'C2_COMPARISON',
        'pypdfium2', '已读全文',
    ):
        assert expected in log


def test_paywalled_paper_falls_back_to_abstract(service, paywalled_paper, downloads):
    result = service.read_for_components(paywalled_paper, purpose='A_DATA_AVAILABILITY')

    assert result.depth == '仅摘要'
    assert result.data_availability == '未确认'
    assert result.version == '未确认'
    assert result.fulltext_path is None
    assert downloads.binary_urls == []
    log = (service.output_dir / 'search_log.md').read_text(encoding='utf-8')
    assert '仅摘要' in log
    assert 'A_DATA_AVAILABILITY' in log


def test_closed_pdf_metadata_is_not_promoted_to_oa(service, paywalled_paper, downloads):
    paywalled_paper.is_oa = False
    paywalled_paper.pdf_url = 'https://publisher.example.test/closed.pdf'

    result = service.read_for_components(paywalled_paper, purpose='C2_COMPARISON')

    assert result.depth == '仅摘要'
    assert downloads.binary_urls == []
    assert result.fulltext_path is None


def test_full_text_fills_data_availability_and_verifies_exact_page(service, oa_paper):
    result = service.read_for_components(
        oa_paper,
        purpose='A_DATA_AVAILABILITY',
        fulltext_quotes=[
            'Comparison method uses two cohorts.',
            'A fabricated sentence that is absent.',
        ],
    )

    assert 'Data are available at example.org dataset' in result.data_availability
    assert len(result.ledger_channels) == 1
    channel = result.ledger_channels[0]
    assert channel.anchor == 'page 2'
    assert channel.channel == 'fulltext'
    assert channel.verified is True
    assert service.verify_quote(result, 'A fabricated sentence that is absent.') is None
    assert result.original_abstract_quote == oa_paper.abstract


def test_europepmc_xml_uses_section_anchors_and_actual_version(tmp_path):
    downloads = FakeDownloads()
    paper = make_paper(ref_no=3)
    paper.resolution['candidates'] = [{
        'url': 'https://europepmc.example.test/PMC7/fullTextXML',
        'source': 'europepmc_xml',
        'status': 'PMC7',
        'kind': 'xml',
        'tier': 2,
        'is_direct_pdf': False,
    }]
    service = FullTextService(
        tmp_path,
        resolver=lambda record: deepcopy(record.resolution),
        binary_downloader=downloads.binary,
        text_downloader=downloads.text,
    )

    result = service.read_for_components(
        paper,
        purpose='C2_COMPARISON',
        fulltext_quotes=['Exact XML methods quotation for verification.'],
    )

    assert result.depth == '已读全文'
    assert result.version == '接收稿'
    text = result.fulltext_path.read_text(encoding='utf-8')
    assert '=== sec Methods ===' in text
    assert '=== sec Cohort ===' in text
    assert '=== sec Data availability ===' in text
    assert 'Reference text is not body text.' not in text
    assert result.ledger_channels[0].anchor == 'sec Methods'
    assert result.source_path.name == 'fulltext_ref3.xml'


def test_title_based_data_availability_uses_statement_and_exact_section_anchor(tmp_path):
    downloads = FakeDownloads()
    paper = make_paper(ref_no=18)
    paper.resolution['candidates'] = [{
        'url': 'https://europepmc.example.test/PMC18/fullTextXML',
        'source': 'europepmc_xml',
        'status': 'PMC18',
        'kind': 'xml',
        'tier': 2,
        'is_direct_pdf': False,
    }]
    service = FullTextService(
        tmp_path,
        resolver=lambda record: deepcopy(record.resolution),
        binary_downloader=downloads.binary,
        text_downloader=downloads.text,
    )

    result = service.read_for_components(paper, purpose='A_DATA_AVAILABILITY')

    assert result.depth == '已读全文'
    assert result.data_availability == 'sec Data availability: XML data are available on request.'
    assert result.non_claim_slots['data_availability'] == result.data_availability
    assert 'sec Data availability' in result.non_claim_slots['section_anchors']
    assert 'Reference text is not body text.' not in result.full_text


@pytest.mark.parametrize('status,source,expected', [
    ('submitted', 'arxiv', '预印本'),
    ('accepted', 'openalex', '接收稿'),
    ('published', 'openalex', '正式版'),
])
def test_full_text_records_actual_candidate_version(tmp_path, status, source, expected):
    paper = make_paper(ref_no=4, status=status, source=source)
    downloads = FakeDownloads()
    service = FullTextService(
        tmp_path,
        resolver=lambda record: deepcopy(record.resolution),
        binary_downloader=downloads.binary,
        text_downloader=downloads.text,
    )

    result = service.read_for_components(paper, purpose='D_READING_CARD')

    assert result.version == expected
    assert result.depth == '已读全文'


@pytest.mark.parametrize('purpose', [
    'A_DATA_AVAILABILITY', 'B_TECHNICAL_ROUTE', 'C1_WRITING_REFERENCE',
    'C2_COMPARISON', 'D_READING_CARD',
])
def test_component_purposes_have_explicit_reading_depth(service, oa_paper, purpose):
    result = service.read_for_components(oa_paper, purpose=purpose)

    assert result.depth == '已读全文'
    assert result.purpose == purpose
    if purpose == 'C1_WRITING_REFERENCE':
        assert result.writing_reference['depth'] == '已读全文'
        assert result.writing_reference['version'] == '正式版'
        assert result.writing_reference['ref_no'] == 7


def test_scanned_oa_pdf_uses_ocr_and_marks_every_excerpt(tmp_path):
    ocr = FakeOCR('Scanned sentence requiring review.')
    paper = make_paper(ref_no=8)
    downloads = FakeDownloads(pdf=SCANNED_PDF_BYTES)
    service = FullTextService(
        tmp_path,
        resolver=lambda record: deepcopy(record.resolution),
        binary_downloader=downloads.binary,
        text_downloader=downloads.text,
        ocr=ocr,
    )

    result = service.read_for_components(
        paper, purpose='D_READING_CARD', fulltext_quotes=['Scanned sentence requiring review.']
    )

    assert result.depth == '已读全文'
    assert result.ocr_used is True
    assert len(ocr.calls) == 2
    assert 'OCR 识别，待人工核对' in result.fulltext_path.read_text(encoding='utf-8')
    assert result.ledger_channels[0].note == 'OCR 识别，待人工核对'


def test_born_digital_pdf_never_invokes_ocr(tmp_path):
    ocr = FakeOCR()
    paper = make_paper(ref_no=10)
    downloads = FakeDownloads()
    service = FullTextService(
        tmp_path,
        resolver=lambda record: deepcopy(record.resolution),
        binary_downloader=downloads.binary,
        text_downloader=downloads.text,
        ocr=ocr,
    )

    result = service.read_for_components(paper, purpose='C2_COMPARISON')

    assert result.ocr_used is False
    assert ocr.calls == []


def test_scanned_data_availability_excerpt_carries_ocr_review_note(tmp_path):
    ocr = FakeOCR('Data availability: scanned dataset is available locally.')
    paper = make_paper(ref_no=16)
    downloads = FakeDownloads(pdf=SCANNED_PDF_BYTES)
    service = FullTextService(
        tmp_path,
        resolver=lambda record: deepcopy(record.resolution),
        binary_downloader=downloads.binary,
        text_downloader=downloads.text,
        ocr=ocr,
    )

    result = service.read_for_components(paper, purpose='A_DATA_AVAILABILITY')

    assert 'scanned dataset is available locally' in result.data_availability
    assert 'OCR 识别，待人工核对' in result.data_availability
    assert result.non_claim_slots['data_availability'] == result.data_availability


def test_ocr_failure_is_logged_when_scanned_pdf_falls_back(tmp_path):
    class FailingOCR:
        def __call__(self, image_path):
            raise ImportError('onnxruntime is not installed')

    paper = make_paper(ref_no=17)
    downloads = FakeDownloads(pdf=SCANNED_PDF_BYTES)
    service = FullTextService(
        tmp_path,
        resolver=lambda record: deepcopy(record.resolution),
        binary_downloader=downloads.binary,
        text_downloader=downloads.text,
        ocr=FailingOCR(),
    )

    result = service.read_for_components(paper, purpose='D_READING_CARD')

    assert result.depth == '仅摘要'
    assert result.data_availability == '未确认'
    assert any('onnxruntime is not installed' in failure for failure in result.failures)
    log = (tmp_path / 'search_log.md').read_text(encoding='utf-8')
    assert 'onnxruntime is not installed' in log


@pytest.mark.parametrize('failure_kind', ['exception', 'empty'])
def test_partial_page_ocr_failure_falls_back_and_preserves_page_diagnostic(tmp_path, failure_kind):
    class PartiallyFailingOCR:
        def __call__(self, image_path):
            if Path(image_path).name == 'page_2.png':
                if failure_kind == 'exception':
                    raise RuntimeError('OCR failed on required page two')
                return []
            return [(
                [[0, 0], [100, 0], [100, 20], [0, 20]],
                'Readable page one. Data availability: partial text must not be used.',
                0.99,
            )]

    paper = make_paper(ref_no=19)
    downloads = FakeDownloads(pdf=SCANNED_PDF_BYTES)
    service = FullTextService(
        tmp_path,
        resolver=lambda record: deepcopy(record.resolution),
        binary_downloader=downloads.binary,
        text_downloader=downloads.text,
        ocr=PartiallyFailingOCR(),
    )

    result = service.read_for_components(paper, purpose='A_DATA_AVAILABILITY')

    assert result.depth == '仅摘要'
    assert result.data_availability == '未确认'
    assert result.fulltext_path is None
    assert result.full_text == ''
    assert not (tmp_path / 'fulltext_ref19.txt').exists()
    assert any('page 2 OCR' in failure for failure in result.failures)
    log = (tmp_path / 'search_log.md').read_text(encoding='utf-8')
    assert 'page 2 OCR' in log
    assert '仅摘要' in log


def test_user_provided_scanned_pdf_may_use_ocr_without_oa_resolution(tmp_path):
    source = tmp_path / 'user-scan.pdf'
    source.write_bytes(SCANNED_PDF_BYTES)
    paper = make_paper(ref_no=11)
    paper.user_provided = True
    paper.local_pdf = source
    ocr = FakeOCR('User supplied scanned text.')
    service = FullTextService(
        tmp_path / 'output',
        resolver=lambda record: (_ for _ in ()).throw(AssertionError('OA resolution not allowed')),
        ocr=ocr,
    )

    result = service.read_for_components(paper, purpose='D_READING_CARD')

    assert result.depth == '已读全文'
    assert result.ocr_used is True
    assert result.source_url == 'user-provided'
    assert result.version == '未确认'


def test_pypdfium2_render_and_crop_produce_expected_png_dimensions(tmp_path):
    source = tmp_path / 'fixture.pdf'
    source.write_bytes(PDF_BYTES)
    rendered = tmp_path / 'page.png'
    cropped = tmp_path / 'crop.png'

    render_pdf_page(source, page=1, scale=1.5, output_path=rendered)
    crop_pdf_page(source, page=1, scale=2, pixel_rect=(10, 20, 50, 40), output_path=cropped)

    assert png_size(rendered) == (300, 300)
    assert png_size(cropped) == (50, 40)


def test_failed_candidate_is_logged_before_next_oa_candidate(tmp_path):
    paper = make_paper(ref_no=12)
    failed_url = 'https://oa.example.test/blocked.pdf'
    paper.resolution['candidates'].insert(0, {
        'url': failed_url,
        'source': 'openalex',
        'status': 'published',
        'kind': 'pdf',
        'tier': 1,
        'is_direct_pdf': True,
    })
    downloads = FakeDownloads()
    downloads.failures[failed_url] = RuntimeError('HTTP 403')
    service = FullTextService(
        tmp_path,
        resolver=lambda record: deepcopy(record.resolution),
        binary_downloader=downloads.binary,
        text_downloader=downloads.text,
    )

    result = service.read_for_components(paper, purpose='B_TECHNICAL_ROUTE')

    assert result.depth == '已读全文'
    assert downloads.binary_urls == [failed_url, 'https://oa.example.test/article.pdf']
    assert any('HTTP 403' in failure for failure in result.failures)
    log = (tmp_path / 'search_log.md').read_text(encoding='utf-8')
    assert failed_url in log
    assert 'HTTP 403' in log


def test_non_pdf_responses_fall_back_without_claiming_full_text(tmp_path):
    paper = make_paper(ref_no=13, abstract='Only the abstract remains available.')
    downloads = FakeDownloads(pdf=b'<html>paywall landing page</html>')
    service = FullTextService(
        tmp_path,
        resolver=lambda record: deepcopy(record.resolution),
        binary_downloader=downloads.binary,
        text_downloader=downloads.text,
    )

    result = service.read_for_components(paper, purpose='A_DATA_AVAILABILITY')

    assert result.depth == '仅摘要'
    assert result.data_availability == '未确认'
    assert result.original_abstract_quote == 'Only the abstract remains available.'
    assert not (tmp_path / 'fulltext_ref13.txt').exists()
    assert any('非 PDF' in failure for failure in result.failures)


def test_optional_fulltext_channel_never_replaces_abstract_ledger_quote(tmp_path):
    paper = make_paper(ref_no=14)
    ledger = SimpleNamespace(abstract_quote='Abstract claim sentence stays authoritative.')
    downloads = FakeDownloads()
    service = FullTextService(
        tmp_path,
        resolver=lambda record: deepcopy(record.resolution),
        binary_downloader=downloads.binary,
        text_downloader=downloads.text,
    )

    result = service.read_for_components(
        paper,
        purpose='C2_COMPARISON',
        ledger_entry=ledger,
        fulltext_quotes=['First page methods use a reproducible approach.'],
    )

    assert ledger.abstract_quote == 'Abstract claim sentence stays authoritative.'
    assert result.original_abstract_quote == ledger.abstract_quote
    assert len(ledger.fulltext_channels) == 1
    assert ledger.fulltext_channels[0].anchor == 'page 1'
    assert not hasattr(ledger, 'claim_quote')


def test_logged_extraction_command_can_be_replayed_offline(service, oa_paper):
    result = service.read_for_components(oa_paper, purpose='C2_COMPARISON')
    expected = result.fulltext_path.read_text(encoding='utf-8')
    environment = dict(os.environ)
    environment.pop('PYTHONPATH', None)

    completed = subprocess.run(
        shlex.split(result.extraction_command),
        cwd=Path(__file__).resolve().parents[2],
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert result.fulltext_path.read_text(encoding='utf-8') == expected
