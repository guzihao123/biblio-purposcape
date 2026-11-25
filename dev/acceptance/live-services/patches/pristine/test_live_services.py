"""Opt-in live-service acceptance; no fixtures are used as network responses."""

import argparse
import importlib.util
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import pytest

from app.analysis import verbatim_quote
from app.candidates import CandidateService
from app.qwen import ChatModel
from app.search import SearchService, merge_records


ROOT = Path(__file__).resolve().parents[2]
SEARCH_SCRIPT = ROOT / 'skill_runtime' / 'scripts' / 'search_papers.py'
NORMAL_QUERY = 'hepatocellular carcinoma immunotherapy resistance'
RETRACTED_QUERY = (
    'Hydroxychloroquine or chloroquine with or without a macrolide '
    'for treatment of COVID-19 multinational registry analysis'
)

LIVE_OPENALEX = pytest.mark.skipif(
    os.environ.get('RUN_LIVE_OPENALEX_ACCEPTANCE') != '1',
    reason='Live OpenAlex acceptance is opt-in.',
)
LIVE_QWEN = pytest.mark.skipif(
    not (
        os.environ.get('RUN_LIVE_QWEN_ACCEPTANCE') == '1'
        and os.environ.get('QWEN_BILLING_AUTHORIZED') == '1'
        and os.environ.get('QWEN_API_KEY')
        and os.environ.get('QWEN_BASE_URL')
    ),
    reason='Requires explicit live/billing opt-in and both Qwen environment variables.',
)


def _search_module():
    spec = importlib.util.spec_from_file_location('live_search_papers', SEARCH_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _live_qwen_model():
    # Disable SDK retries so each test issues at most one paid model request.
    from openai import OpenAI

    client = OpenAI(
        api_key=os.environ['QWEN_API_KEY'],
        base_url=os.environ['QWEN_BASE_URL'],
        max_retries=0,
        timeout=45,
    )
    return ChatModel(client=client, model=os.environ.get('QWEN_MODEL') or 'qwen-plus')


@LIVE_OPENALEX
def test_live_openalex_five_records_metadata_retraction_and_log(tmp_path, monkeypatch):
    """Retrieve exactly four ordinary records and one genuinely retracted record."""

    output_dir = Path(os.environ.get('LIVE_ACCEPTANCE_ARTIFACT_DIR', str(tmp_path)))
    output_dir.mkdir(parents=True, exist_ok=True)
    module = _search_module()
    attempts = []
    raw_payloads = []
    logical_requests = []
    summary = {
        'service': 'OpenAlex',
        'result': 'not_completed',
        'logical_requests': logical_requests,
        'http_attempts': attempts,
        'paper_count': 0,
        'papers': [],
    }
    real_urlopen = urllib.request.urlopen
    real_fetch = module.fetch

    def counting_urlopen(request, *args, **kwargs):
        url = request.full_url if hasattr(request, 'full_url') else str(request)
        parsed = urllib.parse.urlsplit(url)
        attempt = {'endpoint': parsed.netloc + parsed.path}
        try:
            response = real_urlopen(request, *args, **kwargs)
        except urllib.error.HTTPError as error:
            attempt.update(status=error.code, error_type='HTTPError')
            attempts.append(attempt)
            raise
        except Exception as error:
            attempt.update(status=None, error_type=type(error).__name__)
            attempts.append(attempt)
            raise
        attempt.update(status=getattr(response, 'status', 200), error_type=None)
        attempts.append(attempt)
        return response

    def capturing_fetch(url, *args, **kwargs):
        text = real_fetch(url, *args, **kwargs)
        raw_payloads.append(json.loads(text))
        return text

    monkeypatch.setattr(urllib.request, 'urlopen', counting_urlopen)
    monkeypatch.setattr(module, 'fetch', capturing_fetch)

    def retrieve(query, limit, from_year, stem):
        logical_requests.append({'query_kind': stem, 'requested_records': limit})
        output = output_dir / '{}.json'.format(stem)
        args = argparse.Namespace(
            limit=limit,
            query=[query],
            from_year=from_year,
            count_only=False,
            sort='relevance',
            out=str(output),
            phrase_count=False,
        )
        before_raw = len(raw_payloads)
        module.search_openalex(args)
        assert len(raw_payloads) == before_raw + 1
        payload = json.loads(output.read_text(encoding='utf-8'))
        command = [sys.executable, str(SEARCH_SCRIPT), 'openalex', '--query', query]
        if from_year is not None:
            command.extend(['--from-year', str(from_year)])
        command.extend(['--limit', str(limit), '--sort', 'relevance', '--out', str(output)])
        SearchService(output_dir=output_dir, limit=limit)._append_log(
            'live_acceptance', stem, command, payload, output
        )
        return payload, raw_payloads[-1]

    try:
        ordinary, ordinary_raw = retrieve(NORMAL_QUERY, 4, 2023, 'ordinary')
        retracted, retracted_raw = retrieve(RETRACTED_QUERY, 1, None, 'retracted')
        assert len(ordinary['papers']) == 4
        assert len(retracted['papers']) == 1
        assert retracted_raw['results'][0].get('is_retracted') is True

        raw_works = ordinary_raw['results'] + retracted_raw['results']
        papers = ordinary['papers'] + retracted['papers']
        assert len(papers) == len(raw_works) == 5
        assert len({paper['id'] for paper in papers}) == 5
        by_id = {work.get('id'): work for work in raw_works}
        for paper in papers:
            work = by_id[paper['id']]
            assert paper['source'] == 'openalex'
            assert paper['title'] == (work.get('title') or work.get('display_name'))
            assert paper['year'] == work.get('publication_year')
            assert paper['doi'] == work.get('doi')
            assert paper['type'] in {'article', 'review', 'preprint'}
            assert paper['abstract'] == module.abstract_from_inverted(
                work.get('abstract_inverted_index')
            )
        assert any(paper['abstract'] for paper in ordinary['papers'])

        merged = merge_records(papers, limit=5, from_year=None, mode='A')
        retained_ids = {paper['id'] for paper in merged['papers']}
        assert retracted['papers'][0]['id'] not in retained_ids
        assert all(not paper['is_retracted'] for paper in merged['papers'])
        assert [paper['ref_no'] for paper in merged['papers']] == list(
            range(1, merged['count'] + 1)
        )
        for paper in merged['papers']:
            if not paper['abstract']:
                assert paper['claim_eligible'] is False

        log = (output_dir / 'search_log.md').read_text(encoding='utf-8')
        assert log.count('- Command:') == 2
        assert log.count('- Hit count:') == 2
        assert log.count('- Returned count:') == 2
        assert '- Returned count: 4' in log
        assert '- Returned count: 1' in log

        accepted_path = output_dir / 'accepted_papers.json'
        accepted_path.write_text(
            json.dumps(merged, ensure_ascii=False, indent=2) + '\n', encoding='utf-8'
        )
        summary.update({
            'result': 'passed',
            'paper_count': len(papers),
            'retained_count': merged['count'],
            'retracted_input_id': retracted['papers'][0]['id'],
            'retracted_excluded': True,
            'empty_abstract_ids': [paper['id'] for paper in papers if not paper['abstract']],
            'accepted_papers_path': str(accepted_path),
            'search_log_path': str(output_dir / 'search_log.md'),
            'papers': [
                {
                    'id': paper['id'],
                    'doi': paper['doi'],
                    'title': paper['title'],
                    'year': paper['year'],
                    'authors': paper['authors'],
                    'venue': paper['venue'],
                    'type': paper['type'],
                    'abstract_chars': len(paper['abstract'] or ''),
                    'is_retracted': paper['is_retracted'],
                }
                for paper in papers
            ],
        })
    except Exception as error:
        summary.update(result='failed', error_type=type(error).__name__)
        raise
    finally:
        (output_dir / 'live_acceptance_summary.json').write_text(
            json.dumps(summary, ensure_ascii=False, indent=2) + '\n', encoding='utf-8'
        )


@LIVE_QWEN
def test_live_qwen_candidate_terms_once():
    options = CandidateService(
        model=_live_qwen_model(), count_runner=lambda _query: None
    ).generate('肝细胞癌免疫治疗耐药', 'A')

    assert 1 <= len(options) <= 4
    assert len({option['en'] for option in options}) == len(options)
    for option in options:
        assert option['zh'] and option['en'] and option['description']
        assert option['hits'] is None
        assert '命中未知' in option['label']


@LIVE_QWEN
def test_live_qwen_widget_json_once_with_verbatim_abstract_evidence():
    papers_path = os.environ.get('LIVE_OPENALEX_PAPERS')
    if not papers_path:
        pytest.skip('LIVE_OPENALEX_PAPERS is required before the paid widget call.')
    papers = json.loads(Path(papers_path).read_text(encoding='utf-8'))['papers']
    eligible = [paper for paper in papers if paper.get('abstract')][:2]
    if not eligible:
        pytest.skip('No abstract-bearing live paper is available; no paid call made.')
    payload_papers = [
        {'ref': paper['ref_no'], 'title': paper['title'], 'abstract': paper['abstract']}
        for paper in eligible
    ]
    by_ref = {paper['ref_no']: paper for paper in eligible}

    response = _live_qwen_model().complete_json(
        '你是文献小组件生成器。只返回 JSON 对象 {"widget":{"title":字符串,'
        '"claims":[{"text":字符串,"ref":整数,"quote":字符串}]}}，最多 2 条。'
        'quote 必须逐字摘自对应 ref 的输入摘要，不得改写或补入全文事实。',
        {'papers': payload_papers, 'max_claims': 2},
    )
    widget = response.get('widget') if isinstance(response, dict) else None
    assert isinstance(widget, dict) and str(widget.get('title') or '').strip()
    claims = widget.get('claims')
    assert isinstance(claims, list) and 1 <= len(claims) <= 2
    for claim in claims:
        assert str(claim.get('text') or '').strip()
        paper = by_ref.get(claim.get('ref'))
        assert paper is not None
        assert verbatim_quote(paper['abstract'], claim.get('quote'))
