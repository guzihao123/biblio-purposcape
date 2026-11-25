import json
import subprocess
import sys
from pathlib import Path

from docx import Document

from app.fulltext import FullTextService
from app.policy_search import PolicyService
from test_fulltext import make_pdf


def source(url='https://www.gov.cn/zhengce/example.htm', **overrides):
    data = {
        'title': '示例政策文件',
        'url': url,
        'issuer': '国务院',
        'document_number': '国发〔2024〕1号',
        'issued_at': '2024-01-01',
        'published_at': '2024-01-01',
        'content_type': 'html',
        'source_type': 'official',
        'html': '<html><body><h1>示例政策文件</h1><p>到2030年形成完整示范体系。</p></body></html>',
    }
    data.update(overrides)
    return data


def test_policy_requires_official_source_and_three_metadata_fields(tmp_path):
    result = PolicyService(tmp_path).collect(source(url='https://example.com/policy'))
    assert result.accepted is False
    assert result.reason == '政策原文必须来自官方页面或 gov.cn 转载'


def test_official_html_creates_m1_material_and_preserves_both_dates(tmp_path):
    result = PolicyService(tmp_path, fetcher=lambda candidate: source(url=candidate['url'])).collect(source(is_republication=True, published_at='2024-01-02', original_url='https://www.gov.cn/zhengce/original.htm'))
    assert result.accepted is True
    assert result.citation == '[M1]'
    assert result.included_in_n_pool is False
    assert any('到2030年形成完整示范体系。' in excerpt.text for excerpt in result.excerpts)
    listing = (tmp_path / '非论文材料清单.md').read_text()
    assert '国发〔2024〕1号' in listing
    assert '成文日期：2024-01-01' in listing
    assert '转载发布日期：2024-01-02' in listing
    assert '[M1]' in listing


def test_docx_is_parsed_with_page_or_section_anchor(tmp_path):
    document = Document()
    document.add_paragraph('到2025年完成基础研究布局。')
    path = tmp_path / 'policy.docx'
    document.save(path)
    result = PolicyService(tmp_path).collect(source(url='https://www.gov.cn/zhengce/docx.htm', local_path=str(path), content_type='docx'))
    assert result.accepted is True
    assert result.excerpts[0].text == '到2025年完成基础研究布局。'
    assert result.excerpts[0].anchor == 'docx 第1段'


def test_ocr_excerpt_requires_human_review(tmp_path):
    path = tmp_path / 'scan.pdf'
    path.write_bytes(make_pdf([[]], scanned=True))
    result = PolicyService(tmp_path).collect(source(
        url='https://www.gov.cn/zhengce/scan.htm',
        local_path=str(path),
        content_type='pdf',
        ocr=lambda _: '到2035年形成长期目标。',
    ))
    assert result.accepted is True
    assert result.citation == '[M1]'
    assert 'OCR 识别，待人工核对' in result.excerpt_note
    assert result.excerpts[0].anchor == 'page 1'
    assert '到2035年形成长期目标。' in result.excerpts[0].text


def test_missing_document_number_is_rejected(tmp_path):
    result = PolicyService(tmp_path).collect(source(document_number=''))
    assert result.accepted is False
    assert '发布机构、文号和成文日期' in result.reason


def test_missing_search_credentials_returns_coverage_boundary(tmp_path):
    result = PolicyService(tmp_path).search_and_collect('城市内涝 政策')
    assert result.accepted is False
    assert '未配置政策搜索服务' in result.reason
    assert not (tmp_path / '非论文材料清单.md').exists()


def test_republication_requires_republish_date(tmp_path):
    result = PolicyService(tmp_path).collect(source(source_type='republication', published_at=''))
    assert result.accepted is False
    assert '转载发布日期' in result.reason


def test_user_material_requires_local_file_and_is_clearly_marked(tmp_path):
    service = PolicyService(tmp_path)
    rejected = service.collect(source(user_provided=True, url='https://example.com/user-policy'))
    assert rejected.accepted is False
    assert '本地文件' in rejected.reason

    path = tmp_path / 'user.txt'
    path.write_text('用户提供的政策原文。', encoding='utf-8')
    accepted = service.collect(source(user_provided=True, url='https://example.com/user-policy', local_path=str(path), content_type='html', html=path.read_text()))
    assert accepted.accepted is True
    assert accepted.source_type == 'user_material'
    assert accepted.source_url == ''
    assert '用户自有材料（非官方检索证据）' in (tmp_path / '非论文材料清单.md').read_text()


def test_user_file_overrides_inline_html_for_provenance(tmp_path):
    path = tmp_path / 'local.html'
    path.write_text('<p>本地文件中的政策原文。</p>', encoding='utf-8')
    result = PolicyService(tmp_path).collect(source(
        user_provided=True,
        local_path=str(path),
        html='<p>与本地文件无关的网页内容。</p>',
        content_type='html',
    ))
    assert result.accepted is True
    assert result.excerpts[0].text == '本地文件中的政策原文。'


def test_mislabeled_republication_is_rejected(tmp_path):
    result = PolicyService(tmp_path).collect(source(source_type='official', published_at='2024-01-02'))
    assert result.accepted is False
    assert '可能为转载' in result.reason


def test_source_type_is_required_for_network_material(tmp_path):
    data = source()
    del data['source_type']
    result = PolicyService(tmp_path).collect(data)
    assert result.accepted is False
    assert '来源类型' in result.reason


def test_blank_html_is_rejected_and_html_has_exact_anchors(tmp_path):
    service = PolicyService(tmp_path)
    blank = service.collect(source(html='<html><body><script>var x=1;</script></body></html>'))
    assert blank.accepted is False
    assert '未提取到可引用的政策原文' in blank.reason

    markup_only = service.collect(source(html='<!DOCTYPE html><!-- comment -->'))
    assert markup_only.accepted is False

    visible = service.collect(source(html='<div>可见政策正文。</div>'))
    assert visible.accepted is True
    assert visible.excerpts[0].text == '可见政策正文。'

    result = service.collect(source())
    assert result.accepted is True
    assert result.excerpts[0].text
    assert result.excerpts[0].anchor != 'HTML 正文'
    assert 'HTML' in result.excerpts[0].anchor


def test_discovery_requires_fetcher_and_prioritizes_official_originals(tmp_path):
    candidates = [
        source(url='https://www.gov.cn/zhengce/republish.htm', source_type='republication', title='转载件', original_url='https://www.gov.cn/zhengce/original.htm'),
        source(url='https://www.gov.cn/zhengce/original.htm', source_type='official', title='原文件'),
    ]
    service = PolicyService(tmp_path, discovery=lambda _: candidates)
    missing_fetcher = service.search_and_collect('示例')
    assert missing_fetcher.accepted is False
    assert '原文抓取' in missing_fetcher.reason

    service = PolicyService(tmp_path, discovery=lambda _: candidates, fetcher=lambda candidate: candidate)
    result = service.search_and_collect('示例')
    assert result.accepted is True
    assert result.title == '原文件'


def test_mixed_pdf_ocr_only_scanned_pages(tmp_path):
    path = tmp_path / 'mixed.pdf'
    path.write_bytes(make_pdf([['Born digital page text'], []]))
    full_text, _, ocr_used, _ = FullTextService(tmp_path, ocr=lambda _: '扫描页识别文字')._extract_pdf(path, 1, tmp_path / 'figures')
    assert ocr_used is True
    assert 'Born digital page text' in full_text
    assert full_text.count('OCR 识别，待人工核对') == 1
    assert '扫描页识别文字' in full_text


def test_m_material_is_not_counted_as_n_citation_by_verify_script(tmp_path):
    papers = {'topic': 'test', 'from_year': None, 'merged_at': '2026-11-23', 'count': 1, 'papers': [{
        'ref_no': 1, 'title': 'Fixture', 'abstract': 'A documented fact.', 'evidence_level': 'A',
        'year': 2024, 'authors': ['A Author'], 'venue': 'Fixture Journal', 'cited_by_count': 0,
        'doi': None, 'url': None, 'is_retracted': False, 'referenced_works': [],
    }]}
    (tmp_path / 'papers.json').write_text(json.dumps(papers), encoding='utf-8')
    (tmp_path / 'evidence_ledger.md').write_text('| 论断 | 引用序号 | 摘要原句摘录 | 证据等级 | 全文定位 | 全文原句 |\n|---|---:|---|---|---|---|\n| A documented fact | 1 | A documented fact. | A |  |  |\n', encoding='utf-8')
    (tmp_path / '综述初稿.md').write_text('政策材料见[M1]。文献事实[1]。\n\n## 参考文献\n\n[1] A Author. Fixture[J]. Fixture Journal, 2024.\n', encoding='utf-8')
    script = Path(__file__).resolve().parents[2] / 'skill_runtime' / 'scripts' / 'verify_delivery.py'
    local_script = tmp_path / 'verify_delivery.py'
    local_script.write_text(script.read_text(), encoding='utf-8')
    result = subprocess.run([sys.executable, str(local_script), str(tmp_path / '综述初稿.md'), '0-1000'], cwd=tmp_path, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert '全部 8 项无失败' in result.stdout
