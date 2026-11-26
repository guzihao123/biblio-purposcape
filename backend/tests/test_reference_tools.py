import copy
import importlib.util
import json
import re
import subprocess
import sys
import urllib.error
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT_ROOT = ROOT / 'skill_runtime' / 'scripts'
FIXTURE_ROOT = Path(__file__).resolve().parent / 'fixtures' / 'references'


def load_script(name):
    path = SCRIPT_ROOT / f'{name}.py'
    spec = importlib.util.spec_from_file_location(f'reference_test_{name}', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


format_references = load_script('format_references')
verify_references = load_script('verify_references')
renumber_citations = load_script('renumber_citations')
pptx_to_text = load_script('pptx_to_text')


@pytest.fixture(autouse=True)
def forbid_real_registry_requests(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError('测试禁止真实 Crossref/DataCite 网络请求')

    monkeypatch.setattr(verify_references.urllib.request, 'urlopen', blocked)


@pytest.mark.parametrize('raw, expected', [
    ('Garcia Lopez, Juan', 'GARCIA LOPEZ J'),
    ('Ludwig van Beethoven', 'VAN BEETHOVEN L'),
    ('Jean-Luc Picard', 'PICARD J L'),
    ('Quizhpi-Gomez, Ana-Lucia', 'QUIZHPI-GOMEZ A L'),
    ('张伟', '张伟'),
])
def test_gbt_author_formats_only_unambiguous_names(raw, expected):
    formatted, manual = format_references.fmt_author(raw)
    assert formatted == expected
    assert manual is False


@pytest.mark.parametrize('raw', [
    'Juan Garcia Lopez',             # 无逗号时无法断定 Garcia Lopez 是否均为姓
    'Smith, John; Doe, Jane',        # 疑似多人合并在同一个作者字段
    'John Smith and Jane Doe',
    'World Health Organization',
    '中国科学院文献情报中心',
])
def test_gbt_author_uncertain_names_stay_verbatim_and_need_review(raw):
    formatted, manual = format_references.fmt_author(raw)
    assert formatted == raw
    assert manual is True


def test_gbt_entry_includes_volume_issue_pages_without_inventing_fields():
    paper = {
        'ref_no': 1,
        'authors': ['Garcia Lopez, Juan'],
        'title': 'A complete record.',
        'type': 'article',
        'venue': 'Journal of Fixtures',
        'year': 2024,
        'volume': '12',
        'issue': '3',
        'page': '101-110',
        'doi': 'https://doi.org/10.1000/complete',
    }
    text, review = format_references.entry(paper, '2026-11-24')
    assert text == (
        '[1] GARCIA LOPEZ J. A complete record[J]. '
        'Journal of Fixtures, 2024, 12(3): 101-110. DOI:10.1000/complete.'
    )
    assert review == []


def test_suspicious_title_and_corporate_author_are_disclosed():
    paper = {'title': 'A scraped title Author', 'authors': ['World Health Organization']}
    warnings = format_references.suspicious(paper)
    assert any('机构名' in warning for warning in warnings)
    assert any('Author' in warning and '核对原文标题' in warning for warning in warnings)


def test_retracted_paper_is_excluded_from_generated_references(tmp_path):
    papers = {'papers': [
        {
            'ref_no': 1, 'title': 'Valid record', 'authors': ['John Smith'],
            'year': 2024, 'venue': 'Journal of Fixtures', 'type': 'article',
            'abstract': 'A documented fact.', 'is_retracted': False,
        },
        {
            'ref_no': 2, 'title': 'Retracted record', 'authors': ['Jane Doe'],
            'year': 2023, 'venue': 'Journal of Fixtures', 'type': 'article',
            'abstract': 'Withdrawn evidence.', 'is_retracted': True,
        },
    ]}
    source = tmp_path / 'papers.json'
    source.write_text(json.dumps(papers), encoding='utf-8')
    output = tmp_path / 'references.md'
    result = subprocess.run(
        [sys.executable, str(SCRIPT_ROOT / 'format_references.py'), str(source), '--out', str(output)],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
    text = output.read_text(encoding='utf-8')
    assert '[1] SMITH J. Valid record[J].' in text
    assert '[2] DOE J. Retracted record[J].' not in text
    assert '已排除（撤稿）' in text
    assert 'ref 2' in text


def run_delivery_verifier(tmp_path, body, cite_no_abstract=False):
    papers = {'papers': [
        {
            'ref_no': 1, 'title': 'With abstract', 'abstract': 'A documented fact.',
            'evidence_level': 'A', 'year': 2024, 'authors': ['A Author'],
            'venue': 'Fixture Journal', 'doi': None, 'url': None,
            'is_retracted': False, 'referenced_works': [],
        },
        {
            'ref_no': 2, 'title': 'Bibliography only', 'abstract': '',
            'evidence_level': 'C', 'year': 2024, 'authors': ['B Author'],
            'venue': 'Fixture Journal', 'doi': None, 'url': None,
            'is_retracted': False, 'referenced_works': [],
        },
    ]}
    ledger = (
        '| 论断 | 引用序号 | 摘要原句摘录 | 证据等级 | 全文定位 | 全文原句 |\n'
        '|---|---:|---|---|---|---|\n'
        '| A documented fact | 1 | A documented fact. | A |  |  |\n'
    )
    if cite_no_abstract:
        ledger += '| Unsupported claim | 2 |  | C |  |  |\n'
    (tmp_path / 'papers.json').write_text(json.dumps(papers), encoding='utf-8')
    (tmp_path / 'evidence_ledger.md').write_text(ledger, encoding='utf-8')
    (tmp_path / '综述初稿.md').write_text(body, encoding='utf-8')
    local_script = tmp_path / 'verify_delivery.py'
    local_script.write_text((SCRIPT_ROOT / 'verify_delivery.py').read_text(encoding='utf-8'), encoding='utf-8')
    return subprocess.run(
        [sys.executable, str(local_script), '综述初稿.md', '0-1000'],
        cwd=tmp_path, capture_output=True, text=True, check=False,
    )


def test_no_abstract_paper_may_be_listed_but_not_cited(tmp_path):
    references = (
        '\n\n## 参考文献\n\n'
        '[1] A AUTHOR. With abstract[J]. Fixture Journal, 2024.\n'
        '[2] B AUTHOR. Bibliography only[J]. Fixture Journal, 2024.\n'
    )
    listed_only = run_delivery_verifier(tmp_path, '文献事实[1]。' + references)
    assert listed_only.returncode == 0, listed_only.stdout + listed_only.stderr
    assert '池内无摘要[2]仅可进参考文献' in listed_only.stdout

    cited = run_delivery_verifier(tmp_path, '文献事实[1]。无摘要论断[2]。' + references, cite_no_abstract=True)
    assert cited.returncode == 1
    assert '[FAIL] ⑦无摘要不得被正文引用' in cited.stdout
    assert 'ref 2 无摘要却被正文引用' in cited.stdout


def test_renumber_changes_only_real_body_citations():
    body = (
        '正文先引[2]，再引[1]。\n'
        'DOI 10.1234/example[1] 与 https://doi.org/10.1234/other[2] 不改。\n'
        'URL https://example.org/item/[2] 不改；年份[2024]与 ISBN 978-7-121-23456-7 不改。\n'
        '`inline [1]` 不改。\n\n'
        '| 证据 | DOI |\n'
        '| --- | --- |\n'
        '| 真正的表格引用[2] | 10.1234/table[1] |\n\n'
        '```python\n'
        'citation = "[2]"\n'
        '```\n'
    )
    refsec = (
        '\n[1] SMITH J. First original reference[J]. Fixture Journal, 2024.\n'
        '[2] DOE J. Second original reference[J]. Fixture Journal, 2023.\n'
    )
    drafts, shared_refsec, display_to_ref, cited, uncited = renumber_citations.renumber_many([
        ('draft.md', body, refsec),
    ])
    new_body = drafts[0][1]
    assert new_body.splitlines()[0] == '正文先引[1]，再引[2]。'
    assert '10.1234/example[1]' in new_body
    assert 'https://doi.org/10.1234/other[2]' in new_body
    assert 'https://example.org/item/[2]' in new_body
    assert '年份[2024]' in new_body
    assert 'ISBN 978-7-121-23456-7' in new_body
    assert '`inline [1]`' in new_body
    assert '| 真正的表格引用[1] | 10.1234/table[1] |' in new_body
    assert '| --- | --- |' in new_body
    assert 'citation = "[2]"' in new_body
    assert display_to_ref == {'1': 2, '2': 1}
    assert shared_refsec.index('[1] DOE J.') < shared_refsec.index('[2] SMITH J.')
    assert (cited, uncited) == (2, 0)
    assert renumber_citations.check_many([new_body], [shared_refsec], display_to_ref) == []


def run_renumber_in_directory(directory, filename, body):
    directory.mkdir()
    original = body + (
        '\n\n## 参考文献\n\n'
        '[1] SMITH J. First original reference[J]. Fixture Journal, 2024.\n'
        '[2] DOE J. Second original reference[J]. Fixture Journal, 2023.\n'
    )
    path = directory / filename
    path.write_text(original, encoding='utf-8')
    result = subprocess.run(
        [sys.executable, str(SCRIPT_ROOT / 'renumber_citations.py'), filename],
        cwd=directory, capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
    citation_map = json.loads((directory / 'citation_map.json').read_text(encoding='utf-8'))
    return path.read_text(encoding='utf-8'), citation_map


def restore_simple_body(text, citation_map):
    body = text.split('## 参考文献')[0]
    display_to_ref = citation_map['display_to_ref']
    return re.sub(r'\[(\d+)\]', lambda match: f'[{display_to_ref[match.group(1)]}]', body).strip()


def test_c1_c2_independent_maps_are_individually_reversible(tmp_path):
    c1_text, c1_map = run_renumber_in_directory(tmp_path / 'C1', 'C1_引言.md', 'C1 先引[2]，后引[1]。')
    c2_text, c2_map = run_renumber_in_directory(tmp_path / 'C2', 'C2_文献综述.md', 'C2 先引[1]，后引[2]。')

    assert c1_map['display_to_ref'] == {'1': 2, '2': 1}
    assert c2_map['display_to_ref'] == {'1': 1, '2': 2}
    assert c1_map['drafts'] == ['C1_引言.md']
    assert c2_map['drafts'] == ['C2_文献综述.md']
    assert restore_simple_body(c1_text, c1_map) == 'C1 先引[2]，后引[1]。'
    assert restore_simple_body(c2_text, c2_map) == 'C2 先引[1]，后引[2]。'
    for citation_map in (c1_map, c2_map):
        forward = {int(display): ref for display, ref in citation_map['display_to_ref'].items()}
        reverse = {ref: display for display, ref in forward.items()}
        assert len(reverse) == len(forward)
        assert {display: forward[display] for _, display in reverse.items()} == forward


def test_truncated_local_author_list_matches_registry_prefix():
    paper = {
        'title': 'Paper', 'authors': ['Wayne Xin Zhao', 'Kun Zhou'],
        'year': 2024, 'venue': 'Journal',
    }
    metadata = {
        'title': 'Paper',
        'authors': ['Zhao, Wayne Xin', 'Zhou, Kun', 'Li, Junyi'],
        'year': 2024, 'container': 'Journal',
        'volume': '', 'issue': '', 'page': '',
    }
    issues, _, _ = verify_references.compare(paper, metadata, 'crossref')
    assert not any('作者' in issue for issue in issues)


def test_middle_name_variant_is_not_an_author_mismatch():
    paper = {
        'title': 'Paper', 'authors': ['Aditya Pratap Singh'],
        'year': 2024, 'venue': 'Journal',
    }
    metadata = {
        'title': 'Paper', 'authors': ['Singh, Aditya'],
        'year': 2024, 'container': 'Journal',
        'volume': '', 'issue': '', 'page': '',
    }
    issues, _, _ = verify_references.compare(paper, metadata, 'crossref')
    assert not any('作者' in issue for issue in issues)


def test_erratum_is_reported_as_notice_not_a_delivery_failure(tmp_path, monkeypatch):
    metadata = {
        'title': ['Paper'], 'container-title': ['Journal'],
        'author': [{'family': 'Smith', 'given': 'John'}],
        'published': {'date-parts': [[2024]]},
        'update-to': [{'type': 'erratum', 'label': 'Erratum', 'DOI': '10.1000/erratum'}],
        'DOI': '10.1000/paper', 'type': 'journal-article', 'publisher': 'Fixture',
    }
    monkeypatch.setattr(
        verify_references, 'fetch_crossref',
        lambda doi: ('crossref', metadata),
    )
    papers = {'papers': [{
        'ref_no': 1, 'doi': '10.1000/paper', 'title': 'Paper',
        'authors': ['John Smith'], 'year': 2024, 'venue': 'Journal',
    }]}
    source = tmp_path / 'papers.json'
    report_path = tmp_path / 'references_check.md'
    source.write_text(json.dumps(papers, ensure_ascii=False), encoding='utf-8')
    monkeypatch.setattr(
        sys, 'argv',
        ['verify_references.py', str(source), '--out', str(report_path)],
    )

    assert verify_references.main() == 0
    report = report_path.read_text(encoding='utf-8')
    assert '更正关联（非撤稿，供人工参考）' in report
    assert '结论：**核验通过**（含更正关联，非撤稿）' in report
    assert '结论：**需人工核对**' not in report
    assert '更正关联 1 篇' in report


def test_local_author_list_longer_than_registry_is_flagged():
    paper = {
        'title': 'Paper', 'authors': ['A Author', 'B Author'],
        'year': 2024, 'venue': 'Journal',
    }
    metadata = {
        'title': 'Paper', 'authors': ['A Author'],
        'year': 2024, 'container': 'Journal',
        'volume': '', 'issue': '', 'page': '',
    }
    issues, _, _ = verify_references.compare(paper, metadata, 'crossref')
    assert any('作者人数不一致' in issue for issue in issues)


def test_cjk_title_and_author_mismatches_are_not_silently_equal():
    paper = {'title': '真实标题', 'authors': ['张伟'], 'year': 2024, 'venue': '期刊'}
    metadata = {
        'title': '另一标题', 'authors': ['李四'], 'year': 2024, 'container': '期刊',
        'volume': '', 'issue': '', 'page': '',
    }
    issues, _, _ = verify_references.compare(paper, metadata, 'crossref')
    assert any('标题不一致' in issue for issue in issues)
    assert any('作者名不一致' in issue for issue in issues)


def test_offline_crossref_datacite_report_covers_fill_mismatch_missing_and_retraction(tmp_path, monkeypatch):
    responses = json.loads((FIXTURE_ROOT / 'registry_responses.json').read_text(encoding='utf-8'))
    calls = []

    def fake_http_json(url, timeout=30):
        calls.append(url)
        if 'api.crossref.org/works/' in url:
            source, doi = 'crossref', url.split('api.crossref.org/works/', 1)[1]
        elif 'api.datacite.org/dois/' in url:
            source, doi = 'datacite', url.split('api.datacite.org/dois/', 1)[1]
        else:
            raise AssertionError(f'未预期请求：{url}')
        if doi not in responses[source]:
            raise urllib.error.HTTPError(url, 404, 'fixture not found', {}, None)
        return copy.deepcopy(responses[source][doi])

    monkeypatch.setattr(verify_references, 'http_json', fake_http_json)
    monkeypatch.setattr(verify_references.time, 'sleep', lambda _: None)
    papers = {'papers': [
        {
            'ref_no': 1, 'doi': '10.1000/complete', 'title': 'A complete record',
            'authors': ['John Smith'], 'year': 2024, 'venue': 'Journal of Fixtures',
        },
        {
            'ref_no': 2, 'doi': '10.1000/mismatch', 'title': 'Local title',
            'authors': ['John Smith'], 'year': 2024, 'venue': 'Journal of Fixtures',
        },
        {
            'ref_no': 3, 'doi': '10.2000/dataset', 'title': '数据集',
            'authors': ['张伟'], 'year': 2024, 'venue': 'Example repository',
        },
        {
            'ref_no': 4, 'doi': '10.9999/not-registered', 'title': 'Unregistered record',
            'authors': ['John Smith'], 'year': 2024, 'venue': 'Journal of Fixtures',
        },
        {
            'ref_no': 5, 'doi': '10.1000/retracted', 'title': 'Retracted record',
            'authors': ['John Smith'], 'year': 2023, 'venue': 'Journal of Fixtures',
        },
    ]}
    source = tmp_path / 'papers.json'
    report_path = tmp_path / 'references_check.md'
    source.write_text(json.dumps(papers, ensure_ascii=False), encoding='utf-8')
    monkeypatch.setattr(sys, 'argv', ['verify_references.py', str(source), '--out', str(report_path)])

    assert verify_references.main() == 0
    report = report_path.read_text(encoding='utf-8')
    assert '回填建议：卷=12；期=3；页码=101-110' in report
    assert '标题不一致：crossref「Registry title」vs 本地「Local title」' in report
    assert '作者名不一致：crossref「Doe, Jane」vs 本地「John Smith」' in report
    assert 'DOI：10.2000/dataset｜核验通道：datacite' in report
    assert 'DOI 10.9999/not-registered：Crossref 与 DataCite 均未收录（非撤稿，供人工参考）' in report
    retracted_section = report.split('## [5] Retracted record', 1)[1]
    assert '不得进入参考文献' in retracted_section
    assert '结论：**需人工核对**' in retracted_section
    assert '结论：**核验通过**' not in retracted_section
    assert '核验通过 2 篇；需人工核对 2 篇；含回填字段（卷/期/页）1 篇；撤稿关联 1 篇；更正关联 1 篇' in report
    assert sum('api.datacite.org' in url for url in calls) == 2


def test_pptx_text_falls_back_when_slidep_service_is_unavailable(tmp_path, monkeypatch, capfd):
    from pptx import Presentation

    deck = Presentation()
    slide = deck.slides.add_slide(deck.slide_layouts[1])
    slide.shapes.title.text = '参考文献'
    slide.placeholders[1].text = '[1] SMITH J. Offline extraction[J]. Fixture Journal, 2024.'
    source = tmp_path / 'deck.pptx'
    output = tmp_path / '汇报文本.md'
    deck.save(source)

    class FailedSlidep:
        returncode = 1
        stdout = ''
        stderr = 'Error: /localapi/open network error: TypeError: fetch failed'

    monkeypatch.setattr(pptx_to_text, 'find_slidep', lambda _: '/fake/slidep')
    monkeypatch.setattr(pptx_to_text.subprocess, 'run', lambda *args, **kwargs: FailedSlidep())
    monkeypatch.setattr(sys, 'argv', ['pptx_to_text.py', str(source), '--out', str(output)])

    assert pptx_to_text.main() == 0
    text = output.read_text(encoding='utf-8')
    assert '## 参考文献' in text
    assert '[1] SMITH J. Offline extraction[J]. Fixture Journal, 2024.' in text
    assert 'extractor=python-pptx-fallback' in capfd.readouterr().out


def test_preprint_venue_difference_is_notice_not_issue():
    paper = {'title': '真实标题', 'authors': ['张伟'], 'year': 2022, 'venue': 'arXiv preprint'}
    metadata = {
        'title': '真实标题', 'authors': ['张伟'], 'year': 2022,
        'container': '2022 IEEE International Conference on Software Testing, Verification and Validation Workshops (ICSTW)',
        'volume': '', 'issue': '', 'page': '',
    }
    issues, _fills, notices = verify_references.compare(paper, metadata, 'crossref')
    assert issues == []
    assert notices and '预印本' in notices[0]

    paper['venue'] = '某期刊'
    metadata['container'] = '另一期刊'
    issues, _fills, notices = verify_references.compare(paper, metadata, 'crossref')
    assert any('期刊/来源不一致' in issue for issue in issues)
    assert notices == []
