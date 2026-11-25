"""Independent live-services acceptance: offline reuse of real OpenAlex payloads
plus process-level fault injection. No new OpenAlex traffic is generated here.

Evidence inputs (produced by earlier live retrievals on 2026-11-24):
  - ordinary.json: 4 real records, query 'hepatocellular carcinoma immunotherapy resistance'
  - retracted_targeted_raw.json: raw OpenAlex response, filter is_retracted:true
"""

import json
import os
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from app.search import SearchService, merge_records

def _project_root():
    for parent in Path(__file__).resolve().parents:
        if (parent / 'skill_runtime' / 'scripts' / 'search_papers.py').is_file():
            return parent
    raise RuntimeError('project root not found from %s' % __file__)


EVIDENCE_DIR = Path(os.environ.get(
    'LIVE_ACCEPTANCE_ARTIFACT_DIR',
    _project_root() / 'dev' / 'acceptance' / 'live-services' / 'openalex-live',
))
SEARCH_SCRIPT = _project_root() / 'skill_runtime' / 'scripts' / 'search_papers.py'


def _load_script_module():
    import importlib.util

    spec = importlib.util.spec_from_file_location('acceptance_search_papers', SEARCH_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _real_papers():
    ordinary = json.loads((EVIDENCE_DIR / 'ordinary.json').read_text(encoding='utf-8'))
    retracted_raw = json.loads(
        (EVIDENCE_DIR / 'retracted_targeted_raw.json').read_text(encoding='utf-8')
    )
    module = _load_script_module()
    retracted_work = retracted_raw['results'][0]
    assert retracted_work.get('is_retracted') is True
    retracted_paper = {
        'source': 'openalex',
        'id': retracted_work.get('id'),
        'title': retracted_work.get('title') or retracted_work.get('display_name'),
        'year': retracted_work.get('publication_year'),
        'authors': [],
        'venue': None,
        'cited_by_count': retracted_work.get('cited_by_count'),
        'doi': retracted_work.get('doi'),
        'url': retracted_work.get('doi') or retracted_work.get('id'),
        'oa_url': (retracted_work.get('open_access') or {}).get('oa_url'),
        'pdf_url': None,
        'abstract': module.abstract_from_inverted(retracted_work.get('abstract_inverted_index')),
        'type': retracted_work.get('type'),
        'institutions': [],
        'countries': [],
        'is_retracted': True,
        'referenced_works': retracted_work.get('referenced_works') or [],
        'evidence_level': 'A',
    }
    return ordinary['papers'], [retracted_paper], retracted_work


def test_merge_excludes_real_retracted_record_and_numbers_stably(tmp_path):
    """Real is_retracted=true record must be dropped, ref_no stable 1..N."""
    ordinary, retracted, _ = _real_papers()
    records = list(ordinary) + list(retracted)
    merged = merge_records(records, limit=5, from_year=None, mode='A')

    retracted_id = retracted[0]['id']
    assert retracted_id not in {paper['id'] for paper in merged['papers']}
    assert all(not paper['is_retracted'] for paper in merged['papers'])
    assert [paper['ref_no'] for paper in merged['papers']] == list(
        range(1, merged['count'] + 1)
    )
    for paper in merged['papers']:
        assert paper['source'] == 'openalex'
        assert paper['type'] in {'article', 'review', 'preprint'}
        if paper['oa_url'] or paper['pdf_url']:
            assert paper['evidence_level'] == 'A'
        elif paper['abstract']:
            assert paper['evidence_level'] == 'B'
        else:
            assert paper['evidence_level'] == 'C'
        if not paper['abstract']:
            assert paper['claim_eligible'] is False
        else:
            assert paper['claim_eligible'] is True

    # The retrieval log must record the excluded retrieval for auditability.
    service = SearchService(output_dir=tmp_path, limit=5)
    payload = {'total_hits': 3, 'papers': retracted}
    command = ['python3', str(SEARCH_SCRIPT), 'openalex', '--query', '<retracted>', '--limit', '1']
    service._append_log('live_acceptance', 'retracted_targeted', command, payload, tmp_path / 'r.json')
    log = (tmp_path / 'search_log.md').read_text(encoding='utf-8')
    assert '- Returned count: 1' in log
    assert 'retracted_targeted' in log


def test_dual_scope_merge_dedup_prefers_openalex_and_year_scope():
    """Limited/unlimited pools dedup identities; OpenAlex record wins the merge."""
    ordinary, retracted, retracted_work = _real_papers()
    base = ordinary[1]  # A-level OpenAlex record with an abstract
    assert base['abstract']
    duplicate = dict(base)
    duplicate['source'] = 'semantic_scholar'
    duplicate['id'] = 'S2:' + str(base['id']).rsplit('/', 1)[-1]
    duplicate['abstract'] = None  # non-OpenAlex copy carries strictly less data
    duplicate['venue'] = 'Mirrored venue'
    duplicate['_query_kind'] = 'extension'
    duplicate['_query_terms'] = ['hepatocellular carcinoma immunotherapy resistance']
    duplicate['_origins'] = ['unlimited:extension_01']
    duplicate['_retrieval_rank'] = 1

    records = list(ordinary) + [duplicate] + list(retracted)
    limited = merge_records(records, limit=10, from_year=2023, mode='A')
    unlimited = merge_records(records, limit=10, from_year=None, mode='A')

    limited_ids = [paper['id'] for paper in limited['papers']]
    unlimited_ids = [paper['id'] for paper in unlimited['papers']]
    # Identity dedup: base and its S2 mirror collapse into one record per pool.
    assert len(limited_ids) == len(set(limited_ids))
    assert len(unlimited_ids) == len(set(unlimited_ids))
    by_title = {p['title']: p for p in unlimited['papers']}
    winner = by_title[base['title']]
    assert winner['source'] == 'openalex'
    assert winner['abstract']  # fields backfilled from the preferred OpenAlex record
    assert winner['_duplicate_count'] == 2
    assert winner['_origins'] == ['unlimited:extension_01'] or 'unlimited:extension_01' in winner['_origins']
    # Year scope: every limited-pool record honours from_year; unlimited keeps older too.
    assert all(p['year'] is None or p['year'] >= 2023 for p in limited['papers'])
    assert unlimited['count'] >= limited['count']
    assert retracted_work['id'] not in set(limited_ids) | set(unlimited_ids)


class _FlakyHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        plan = self.server.fault_plan
        index = min(getattr(self.server, '_hits', 0), len(plan) - 1)
        self.server._hits = getattr(self.server, '_hits', 0) + 1
        status, headers = plan[index]
        self.send_response(status)
        for key, value in headers.items():
            self.send_header(key, value)
        self.end_headers()
        if status == 200:
            self.wfile.write(b'{"ok": true}')

    def log_message(self, *args):
        pass


def _serve(plan):
    server = HTTPServer(('127.0.0.1', 0), _FlakyHandler)
    server._hits = 0
    server.fault_plan = plan
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, 'http://127.0.0.1:%d/' % server.server_port


def test_fault_injection_429_honors_retry_after():
    """Process-level fault injection: controlled local 429 endpoint.

    Regression: fetch() must honor the Retry-After header instead of the fixed
    10s default backoff. Fails on the unfixed provider (sleeps 10s+20s).
    """
    module = _load_script_module()
    server, url = _serve([
        (429, {'Retry-After': '1'}),
        (429, {'Retry-After': '1'}),
        (200, {}),
    ])
    try:
        started = time.monotonic()
        text = module.fetch(url, tries=3)
        elapsed = time.monotonic() - started
        assert json.loads(text)['ok'] is True
        assert server._hits == 3
        # Two Retry-After:1 waits plus transfer; must be well under the old
        # fixed 10s/20s backoff (which would cost >= 30s).
        assert elapsed < 12, 'Retry-After not honored (elapsed %.1fs)' % elapsed
    finally:
        server.shutdown()


def test_fault_injection_503_recovers_after_backoff():
    """Process-level fault injection: transient 503 then success."""
    module = _load_script_module()
    server, url = _serve([
        (503, {}),
        (503, {}),
        (200, {}),
    ])
    try:
        text = module.fetch(url, tries=3)
        assert json.loads(text)['ok'] is True
        assert server._hits == 3
    finally:
        server.shutdown()


def test_fault_injection_connection_refused_is_real_transport_failure():
    """Process-level fault injection: closed local port => URLError, zero external traffic."""
    import socket

    module = _load_script_module()
    probe = socket.socket()
    probe.bind(('127.0.0.1', 0))
    closed_port = probe.getsockname()[1]
    probe.close()  # port is now guaranteed closed

    started = time.monotonic()
    with pytest.raises(RuntimeError) as caught:
        module.fetch('http://127.0.0.1:%d/works' % closed_port, tries=2)
    elapsed = time.monotonic() - started
    assert 'Connection refused' in str(caught.value) or 'urlopen error' in str(caught.value)
    assert elapsed < 15  # fast local refusal, not a remote timeout


def test_fault_injection_429_retry_after_capped(monkeypatch):
    """Process-level fault injection: Retry-After is honored but never unbounded.

    Regression: a huge Retry-After must not be treated as an unlimited wait
    license. Fails on a provider that forwards the header value unchecked.
    """
    module = _load_script_module()
    server, url = _serve([(429, {'Retry-After': '999999'}), (200, {})])
    sleeps = []
    monkeypatch.setattr(module.time, 'sleep', lambda seconds: sleeps.append(seconds))
    try:
        assert json.loads(module.fetch(url, tries=2))['ok'] is True
        assert sleeps and all(wait <= 60 for wait in sleeps), (
            'Retry-After not capped: %r' % sleeps
        )
    finally:
        server.shutdown()


def test_fault_injection_429_retry_after_edge_cases(monkeypatch):
    """Missing/illegal/HTTP-date Retry-After falls back to the fixed backoff."""
    module = _load_script_module()
    cases = [
        ([(429, {}), (200, {})], [10]),
        ([(429, {'Retry-After': 'abc'}), (200, {})], [10]),
        ([(429, {'Retry-After': '-5'}), (200, {})], [10]),
        ([(429, {'Retry-After': 'Mon, 01 Jan 2035 00:00:00 GMT'}), (200, {})], [10]),
        ([(429, {'Retry-After': '2'}), (200, {})], [2]),
    ]
    for plan, expected_sleeps in cases:
        server, url = _serve(plan)
        sleeps = []
        monkeypatch.setattr(module.time, 'sleep', lambda seconds: sleeps.append(seconds))
        try:
            assert json.loads(module.fetch(url, tries=2))['ok'] is True
            assert sleeps == expected_sleeps, (plan, sleeps)
        finally:
            server.shutdown()


def test_fault_injection_429_error_message_has_no_secrets():
    """Exhausted 429 retries raise RuntimeError without leaking credentials."""
    module = _load_script_module()
    server, url = _serve([(429, {'Retry-After': '1', 'WWW-Authenticate': 'Bearer realm=x'})])
    try:
        with pytest.raises(RuntimeError) as caught:
            module.fetch('http://user:pass@127.0.0.1:%d/' % server.server_port, tries=1)
    finally:
        server.shutdown()
    message = str(caught.value).lower()
    for needle in ('user:pass', 'bearer', 'api_key', 'token', 'secret'):
        assert needle not in message


def test_retracted_targeted_request_constraints_filter():
    """a) The deterministic query really constrains is_retracted:true."""
    request_url = (
        EVIDENCE_DIR / 'retracted_targeted_request.txt'
    ).read_text(encoding='utf-8').strip()
    assert 'is_retracted%3Atrue' in request_url
    raw = json.loads((EVIDENCE_DIR / 'retracted_targeted_raw.json').read_text(encoding='utf-8'))
    assert raw['results'], 'targeted query returned no records'
    assert all(work.get('is_retracted') is True for work in raw['results'])


def test_retracted_candidates_include_original_research():
    """b) Candidates include the original retracted research, not only notices."""
    raw = json.loads((EVIDENCE_DIR / 'retracted_targeted_raw.json').read_text(encoding='utf-8'))
    original_research = [
        work for work in raw['results']
        if not (work.get('title') or '').casefold().startswith('retraction')
    ]
    assert original_research, 'no original retracted research among candidates'
    notice = [
        work for work in raw['results']
        if (work.get('title') or '').casefold().startswith('retraction')
    ]
    assert notice, 'expected a retraction notice alongside the original research'


def test_commentary_record_not_misjudged_as_retracted():
    """c) A Faculty-Opinions-style commentary is never flagged as retracted.

    The commentary (OpenAlex type 'peer-review') is legitimately outside the
    article/review/preprint pool policy; the assertion here is that retraction
    is not the reason, i.e. its is_retracted stays False.
    """
    from app.search import _normalize_record

    ordinary = json.loads((EVIDENCE_DIR / 'ordinary.json').read_text(encoding='utf-8'))
    commentary_payload = json.loads(
        (EVIDENCE_DIR / 'retracted.json').read_text(encoding='utf-8')
    )
    commentary = commentary_payload['papers'][0]
    assert commentary['is_retracted'] is False
    assert 'hydroxychloroquine' in commentary['title'].casefold()

    normalized = _normalize_record(commentary)
    assert normalized['is_retracted'] is False
    assert normalized['type'] == 'peer-review'  # excluded by pool type policy, not retraction

    merged = merge_records(
        list(ordinary['papers']) + [commentary], limit=10, from_year=None, mode='A'
    )
    retained = {paper['id']: paper for paper in merged['papers']}
    assert commentary['id'] not in retained


def test_retracted_original_excluded_from_both_scope_pools():
    """d) Real retracted record dropped from limited and unlimited pools + logged."""
    ordinary = json.loads((EVIDENCE_DIR / 'ordinary.json').read_text(encoding='utf-8'))
    raw = json.loads((EVIDENCE_DIR / 'retracted_targeted_raw.json').read_text(encoding='utf-8'))
    module = _load_script_module()
    work = next(
        w for w in raw['results']
        if not (w.get('title') or '').casefold().startswith('retraction')
    )
    retracted_paper = {
        'source': 'openalex',
        'id': work.get('id'),
        'title': work.get('title') or work.get('display_name'),
        'year': work.get('publication_year'),
        'authors': [],
        'venue': None,
        'doi': work.get('doi'),
        'url': work.get('doi') or work.get('id'),
        'oa_url': (work.get('open_access') or {}).get('oa_url'),
        'abstract': module.abstract_from_inverted(work.get('abstract_inverted_index')),
        'type': work.get('type'),
        'is_retracted': True,
        'evidence_level': 'A',
    }
    records = list(ordinary['papers']) + [retracted_paper]
    limited = merge_records(records, limit=10, from_year=2023, mode='A')
    unlimited = merge_records(records, limit=10, from_year=None, mode='A')
    retracted_id = retracted_paper['id']
    assert retracted_id not in {p['id'] for p in limited['papers']}
    assert retracted_id not in {p['id'] for p in unlimited['papers']}
    log = (EVIDENCE_DIR / 'search_log.md').read_text(encoding='utf-8')
    assert 'retracted_targeted' in log and '- Returned count: 1' in log


@pytest.mark.parametrize('artifact', [
    'search_log.md',
    'live_acceptance_summary.json',
    'accepted_papers.json',
    'ordinary.json',
    'retracted.json',
    'retracted_targeted_raw.json',
    'retracted_targeted_request.txt',
    'pytest_run.log',
])
def test_no_secrets_or_provider_bodies_in_artifacts(artifact):
    """Logs must not carry keys, tokens, provider bodies or credential paths."""
    path = EVIDENCE_DIR / artifact
    if not path.exists():
        pytest.skip('artifact %s not present this round' % artifact)
    text = path.read_text(encoding='utf-8')
    forbidden = [
        os.environ.get('QWEN_API_KEY') or '',
        'Bearer ',
        'Authorization:',
        'x-api-key:',
        '/.env',
        '.aws/credentials',
    ]
    for needle in forbidden:
        if needle:
            assert needle not in text, '%s leaked into %s' % (needle[:8], artifact)
    # Real secret shapes: long opaque key-like tokens must be absent. The
    # literal 'api_key=YOUR_KEY' is OpenAlex's own documentation notice in the
    # response meta, not a credential, so only non-placeholder assignments fail.
    import re

    assert not re.search(r'sk-[A-Za-z0-9]{10,}', text)
    for match in re.finditer(r"api_key=([^&\s\"']+)", text):
        assert match.group(1) == 'YOUR_KEY', 'real api_key value in %s' % artifact
