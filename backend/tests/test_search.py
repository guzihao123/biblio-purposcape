import argparse
import importlib.util
import json
import os
import sys
import urllib.error
from copy import deepcopy
from pathlib import Path

import pytest

from app.graphs import _network
from app.search import SearchRequest, SearchService, merge_records


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SEARCH_SCRIPT = PROJECT_ROOT / 'skill_runtime' / 'scripts' / 'search_papers.py'
INTEGRITY_PAYLOADS = Path(__file__).parent / 'fixtures' / 'search' / 'source_payloads.json'
SAMPLE_ROOT = Path(
    os.environ.get(
        'PURPOSE_LANDSCAPE_HCC_FIXTURES',
        '/Users/crisprcas_9/WorkBuddy/2026-11-06-20-49-06/'
        'landscape-hcc-immunotherapy-resistance-20261122',
    )
)
SELECTED_TERM = 'hepatocellular carcinoma immunotherapy resistance'
EXTENSIONS = [
    'liver cancer immunotherapy resistance',
    'hepatocellular carcinoma immune evasion',
]


def load_sample(name):
    return json.loads((SAMPLE_ROOT / name).read_text(encoding='utf-8'))


def load_integrity_records(tmp_path, monkeypatch):
    """Adapt fully synthetic source payloads without calling any network function."""

    payloads = json.loads(INTEGRITY_PAYLOADS.read_text(encoding='utf-8'))
    spec = importlib.util.spec_from_file_location('offline_search_papers', SEARCH_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    def fixture_fetch(url):
        if url.startswith('https://api.openalex.org/'):
            source = 'openalex'
        elif url.startswith('https://api.crossref.org/'):
            source = 'crossref'
        else:
            raise AssertionError('Unexpected fixture URL: ' + url)
        return json.dumps(payloads[source])

    monkeypatch.setattr(module, 'fetch', fixture_fetch)
    monkeypatch.setattr(
        module,
        '_fetch_s2',
        lambda url, headers: deepcopy(payloads['semantic_scholar']),
    )

    records = []
    functions = (
        ('openalex', module.search_openalex),
        ('crossref', module.search_crossref),
        ('semantic_scholar', module.search_semantic_scholar),
    )
    for source, function in functions:
        output = tmp_path / (source + '.json')
        args = argparse.Namespace(
            limit=100,
            query=['offline integrity'],
            from_year=None,
            count_only=False,
            sort='relevance',
            out=str(output),
            phrase_count=False,
        )
        function(args)
        records.extend(json.loads(output.read_text(encoding='utf-8'))['papers'])
    return payloads, records


def integrity_record(records, record_id):
    return next(deepcopy(record) for record in records if record['id'] == record_id)


@pytest.fixture
def sample_records():
    # These are real sample OpenAlex records. The two appended records are explicit
    # test mutations used to prove retraction and non-paper exclusion, never live data.
    records = deepcopy(load_sample('candidates_all.json')['papers'])
    retracted = deepcopy(records[0])
    retracted['id'] = 'fixture:retracted-record'
    retracted['doi'] = None
    retracted['title'] = 'Retracted: ' + retracted['title']
    retracted['is_retracted'] = True
    records.append(retracted)

    non_paper = deepcopy(records[1])
    non_paper['id'] = 'fixture:conference-abstract'
    non_paper['doi'] = None
    non_paper['title'] = 'Fixture conference abstract'
    non_paper['type'] = 'conference-abstract'
    records.append(non_paper)
    return records


def test_merge_removes_retracted_duplicates_and_caps_pool_at_fifty(sample_records):
    result = merge_records(sample_records, limit=50, from_year=2023)

    assert len(result['papers']) == 50
    assert all(not paper['is_retracted'] for paper in result['papers'])
    assert [paper['ref_no'] for paper in result['papers']] == list(range(1, 51))
    assert len({paper['title'].casefold() for paper in result['papers']}) == 50


def test_non_paper_records_never_replace_relevant_papers(sample_records):
    result = merge_records(sample_records, limit=50, from_year=None)

    assert all(paper['type'] in {'article', 'review', 'preprint'} for paper in result['papers'])
    assert all(paper['title'] != 'Fixture conference abstract' for paper in result['papers'])


def test_merge_by_normalized_title_backfills_real_abstract_and_links():
    original = deepcopy(load_sample('openalex_lim_t1.json')['papers'][1])
    incomplete = deepcopy(original)
    incomplete.update(
        doi=None,
        url=None,
        oa_url=None,
        pdf_url=None,
        abstract=None,
        title=original['title'].upper().replace(':', ' : '),
    )

    result = merge_records([incomplete, original], limit=50, from_year=None)

    assert len(result['papers']) == 1
    merged = result['papers'][0]
    assert merged['doi'] == original['doi']
    assert merged['abstract'] == original['abstract']
    assert merged['oa_url'] == original['oa_url']
    assert merged['url'] == original['url']
    assert merged['ref_no'] == 1
    assert merged['claim_eligible'] is True


def test_merge_by_normalized_doi_does_not_depend_on_doi_prefix_or_case():
    original = deepcopy(load_sample('openalex_lim_t1.json')['papers'][1])
    duplicate = deepcopy(original)
    duplicate['id'] = 'fixture:duplicate-doi'
    duplicate['title'] = 'A different display title for the same DOI'
    duplicate['doi'] = 'DOI:' + original['doi'].removeprefix('https://doi.org/').upper()
    duplicate['abstract'] = None

    result = merge_records([original, duplicate], limit=50, from_year=None)

    assert len(result['papers']) == 1
    assert result['papers'][0]['abstract'] == original['abstract']


def test_doi_less_openalex_url_does_not_block_genuine_doi_backfill():
    original = deepcopy(load_sample('openalex_lim_t1.json')['papers'][1])
    doi_less = deepcopy(original)
    doi_less.update(doi=None, url=original['id'])
    doi_less['cited_by_count'] = (original['cited_by_count'] or 0) + 100
    genuine_doi = deepcopy(original)
    genuine_doi.update(url=None, cited_by_count=0)

    result = merge_records([doi_less, genuine_doi], limit=50, from_year=None)

    assert len(result['papers']) == 1
    merged = result['papers'][0]
    assert merged['doi'] == original['doi']
    assert merged['url'] == original['id']
    assert not merged['doi'].startswith('https://doi.org/https://')


def test_any_irrelevant_duplicate_excludes_the_merged_record():
    original = deepcopy(load_sample('openalex_lim_t1.json')['papers'][1])
    unflagged = deepcopy(original)
    unflagged['relevant'] = True
    flagged = deepcopy(original)
    flagged.update(relevant=False, abstract=None)

    for records in ([flagged, unflagged], [unflagged, flagged]):
        result = merge_records(records, limit=50, from_year=None)
        assert result['papers'] == []


def test_no_abstract_paper_is_inventory_only_not_claim_eligible():
    paper = next(
        deepcopy(paper)
        for paper in load_sample('openalex_lim_t1.json')['papers']
        if paper['type'] in {'article', 'review', 'preprint'} and not paper['abstract']
    )

    result = merge_records([paper], limit=50, from_year=None)

    assert len(result['papers']) == 1
    assert result['papers'][0]['abstract'] is None
    assert result['papers'][0]['claim_eligible'] is False


def test_irrelevant_and_pre_cutoff_records_are_removed_before_numbering():
    candidates = load_sample('candidates_all.json')['papers']
    relevant = deepcopy(load_sample('openalex_lim_t1.json')['papers'][0])
    irrelevant = next(
        deepcopy(paper)
        for paper in candidates
        if paper['title'].startswith('Multiscale multimodal integration')
    )
    old = next(
        deepcopy(paper)
        for paper in candidates
        if paper['type'] in {'article', 'review', 'preprint'} and paper['year'] < 2023
    )

    relevant_result = merge_records(
        [irrelevant, relevant], limit=50, from_year=2023, terms=[SELECTED_TERM]
    )
    old_result = merge_records([old], limit=50, from_year=2023)

    assert [paper['doi'] for paper in relevant_result['papers']] == [relevant['doi']]
    assert relevant_result['papers'][0]['ref_no'] == 1
    assert old_result['papers'] == []


def test_ref_numbers_are_deterministic_and_never_reuse_candidate_ids(sample_records):
    records = deepcopy(sample_records[:10])
    for index, paper in enumerate(records):
        paper['candidate_id'] = 901 + index
        paper['ref_no'] = 900 - index

    forward = merge_records(records, limit=10, from_year=None, mode='A')
    reverse = merge_records(list(reversed(records)), limit=10, from_year=None, mode='A')

    forward_numbering = [(paper['ref_no'], paper['doi'], paper['title']) for paper in forward['papers']]
    reverse_numbering = [(paper['ref_no'], paper['doi'], paper['title']) for paper in reverse['papers']]
    assert forward_numbering == reverse_numbering
    assert [paper['ref_no'] for paper in forward['papers']] == list(range(1, 11))
    assert all('candidate_id' not in paper for paper in forward['papers'])


def test_mode_specific_selection_precedes_public_numbering(sample_records):
    records = deepcopy(sample_records[:4])
    most_cited, newer_tie, older_tie, less_relevant = records
    most_cited.update(
        title=SELECTED_TERM + ' citation signal', cited_by_count=50, year=2020
    )
    newer_tie.update(
        title=SELECTED_TERM + ' recency signal', cited_by_count=40, year=2025
    )
    older_tie.update(
        title=SELECTED_TERM + ' older tie', cited_by_count=40, year=2021
    )
    less_relevant.update(
        title='Hepatocellular carcinoma study with separated concepts',
        abstract='The query immunotherapy resistance is evaluated.',
        cited_by_count=10000,
        year=2026,
    )

    landscape = merge_records(
        records, limit=10, from_year=None, terms=[SELECTED_TERM], mode='A'
    )
    grant = merge_records(
        records, limit=10, from_year=None, terms=[SELECTED_TERM], mode='B'
    )

    assert [paper['id'] for paper in landscape['papers']] == [
        most_cited['id'], newer_tie['id'], older_tie['id'], less_relevant['id']
    ]
    assert landscape['papers'][0]['relevance_score'] == landscape['papers'][1]['relevance_score']
    assert landscape['papers'][0]['relevance_score'] > landscape['papers'][-1]['relevance_score']
    assert grant['papers'][0]['id'] == less_relevant['id']
    assert landscape['papers'][0]['ref_no'] == 1
    assert grant['papers'][0]['ref_no'] == 1


def test_mode_a_preserves_best_retrieval_relevance_rank_when_merging(sample_records):
    preferred, competitor = deepcopy(sample_records[:2])
    duplicate = deepcopy(preferred)
    preferred.update(retrieval_relevance_rank=7, cited_by_count=0, year=2020)
    duplicate.update(retrieval_relevance_rank=2, cited_by_count=0, year=2020)
    competitor.update(retrieval_relevance_rank=3, cited_by_count=10000, year=2026)

    result = merge_records(
        [preferred, competitor, duplicate], limit=10, from_year=None, mode='A'
    )

    assert len(result['papers']) == 2
    assert result['papers'][0]['retrieval_relevance_rank'] == 2
    assert result['papers'][0]['title'] == preferred['title']
    assert result['papers'][1]['id'] == competitor['id']
    assert result['papers'][1]['retrieval_relevance_rank'] == 3


def test_raw_retraction_flag_is_distinct_from_peer_review_type_filter(tmp_path, monkeypatch):
    payloads, records = load_integrity_records(tmp_path, monkeypatch)
    raw_retracted = next(
        work
        for work in payloads['openalex']['results']
        if work['id'] == 'https://openalex.org/W_RETRACTED'
    )
    assert raw_retracted['is_retracted'] is True
    assert not raw_retracted['title'].lower().startswith(
        ('retraction', 'retracted', 'corrigendum')
    )

    retracted = integrity_record(records, 'https://openalex.org/W_RETRACTED')
    peer_review = integrity_record(records, 'https://doi.org/10.1000/peer-review')
    assert retracted['type'] == 'article' and retracted['is_retracted'] is True
    assert peer_review['type'] == 'peer-review' and peer_review['is_retracted'] is False
    assert merge_records([retracted], limit=10)['papers'] == []
    assert merge_records([peer_review], limit=10)['papers'] == []

    # Removing only the raw flag retains the ordinary-titled article; changing only
    # the peer-review type retains that record. The two exclusions are independent.
    retracted['is_retracted'] = False
    peer_review['type'] = 'article'
    assert merge_records([retracted], limit=10)['count'] == 1
    assert merge_records([peer_review], limit=10)['count'] == 1


def test_article_review_preprint_survive_and_blank_abstract_is_inventory_only(
    tmp_path, monkeypatch
):
    _, records = load_integrity_records(tmp_path, monkeypatch)
    selected = [
        integrity_record(records, record_id)
        for record_id in (
            'https://openalex.org/W_TARGET',
            'https://openalex.org/W_REVIEW',
            'https://openalex.org/W_PREPRINT_ONLY',
            'https://openalex.org/W_EMPTY',
        )
    ]

    result = merge_records(selected, limit=10, mode='C1')
    by_id = {paper['id']: paper for paper in result['papers']}
    assert set(by_id) == {paper['id'] for paper in selected}
    assert {paper['type'] for paper in result['papers']} == {'article', 'review', 'preprint'}

    for blank in (None, '', '   '):
        empty = integrity_record(records, 'https://openalex.org/W_EMPTY')
        empty['abstract'] = blank
        paper = merge_records([empty], limit=10)['papers'][0]
        assert paper['claim_eligible'] is False


@pytest.mark.parametrize('retry_after, expected_wait', [
    ('2', 2),
    ('999999', 60),
    ('abc', 10),
    ('-5', 10),
    ('Wed, 21 Oct 2026 07:28:00 GMT', 10),
    (None, 10),
])
def test_fetch_honors_bounded_retry_after_without_network(retry_after, expected_wait, monkeypatch):
    spec = importlib.util.spec_from_file_location('retry_after_search_papers', SEARCH_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    sleeps = []
    attempts = []

    class SuccessfulResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return b'{"ok":true}'

    def fake_urlopen(request, timeout):
        attempts.append(request.full_url)
        if len(attempts) == 1:
            headers = {} if retry_after is None else {'Retry-After': retry_after}
            raise urllib.error.HTTPError(request.full_url, 429, 'limited', headers, None)
        return SuccessfulResponse()

    monkeypatch.setattr(module.urllib.request, 'urlopen', fake_urlopen)
    monkeypatch.setattr(module.time, 'sleep', sleeps.append)

    assert module.fetch('https://offline.invalid/retry-after', tries=2) == '{"ok":true}'
    assert sleeps == [expected_wait]
    assert len(attempts) == 2


def test_same_doi_cross_source_merge_prefers_openalex_and_backfills_real_fields(
    tmp_path, monkeypatch
):
    _, records = load_integrity_records(tmp_path, monkeypatch)
    shared = [
        integrity_record(records, record_id)
        for record_id in (
            'S2_SHARED',
            'https://doi.org/10.1000/shared',
            'https://openalex.org/W_SHARED',
        )
    ]

    result = merge_records(shared, limit=10, mode='C1')

    assert result['count'] == 1
    merged = result['papers'][0]
    assert merged['id'] == 'https://openalex.org/W_SHARED'
    assert merged['source'] == 'openalex'
    assert merged['title'] == 'Offline integrity shared DOI OpenAlex record'
    assert merged['abstract'] == 'OpenAlex abstract wins'
    assert merged['cited_by_count'] == 10
    assert merged['year'] == 2024
    assert merged['doi'] == 'https://doi.org/10.1000/shared'
    assert merged['volume'] == '12'
    assert merged['issue'] == '3'
    assert merged['page'] == '1-9'
    assert merged['publisher'] == 'Fixture Press'
    assert merged['pdf_url'] == 'https://fixture.invalid/s2-shared.pdf'
    assert merged['_duplicate_count'] == 3
    assert merged['ref_no'] == 1


def test_normalized_title_merges_preprint_and_formal_version_with_backfill(
    tmp_path, monkeypatch
):
    _, records = load_integrity_records(tmp_path, monkeypatch)
    preprint = integrity_record(records, 'https://openalex.org/W_VERSION_PREPRINT')
    formal = integrity_record(records, 'https://openalex.org/W_VERSION_ARTICLE')

    result = merge_records([preprint, formal], limit=10)

    assert result['count'] == 1
    merged = result['papers'][0]
    assert merged['id'] == 'https://openalex.org/W_VERSION_ARTICLE'
    assert merged['type'] == 'article'
    assert merged['doi'] == 'https://doi.org/10.1000/version-article'
    assert merged['abstract'] == 'Formal version abstract'
    assert merged['authors'] == ['Preprint Author']
    assert merged['oa_url'] == 'https://fixture.invalid/version-preprint.pdf'
    assert merged['referenced_works'] == ['https://openalex.org/W_TARGET']
    assert merged['_duplicate_count'] == 2
    assert merged['ref_no'] == 1


def test_s2_without_references_never_fabricates_citation_edges(tmp_path, monkeypatch):
    payloads, records = load_integrity_records(tmp_path, monkeypatch)
    raw_s2 = next(
        paper
        for paper in payloads['semantic_scholar']['data']
        if paper['paperId'] == 'S2_ISOLATED'
    )
    assert 'referenced_works' not in raw_s2

    selected = [
        integrity_record(records, 'S2_ISOLATED'),
        integrity_record(records, 'https://openalex.org/W_SHARED'),
        integrity_record(records, 'https://openalex.org/W_TARGET'),
    ]
    result = merge_records(selected, limit=10, mode='C1')
    s2 = next(paper for paper in result['papers'] if paper['id'] == 'S2_ISOLATED')
    assert s2['referenced_works'] == []

    network, _ = _network(result['papers'])
    assert {(edge['s'], edge['t']) for edge in network['edges']} == {
        ('https://openalex.org/W_SHARED', 'https://openalex.org/W_TARGET')
    }
    assert all(edge['s'] != 'S2_ISOLATED' for edge in network['edges'])


def test_relevance_and_merge_precede_citation_cutoff_and_public_numbering(
    tmp_path, monkeypatch
):
    _, records = load_integrity_records(tmp_path, monkeypatch)
    irrelevant = integrity_record(records, 'https://openalex.org/W_IRRELEVANT')
    low = integrity_record(records, 'https://openalex.org/W_RELEVANT_LOW')
    duplicate = deepcopy(low)
    duplicate.update(
        id='fixture:relevant-low-duplicate',
        title=low['title'].upper().replace(' ', ' : '),
        abstract=None,
    )
    medium = integrity_record(records, 'https://openalex.org/W_RELEVANT_MID')
    for index, paper in enumerate([irrelevant, duplicate, medium, low], 1):
        paper['candidate_id'] = 800 + index
        paper['ref_no'] = 900 + index

    result = merge_records(
        [irrelevant, duplicate, medium, low],
        limit=2,
        terms=['offline integrity'],
        mode='C1',
    )

    assert result['count'] == 2
    assert [paper['id'] for paper in result['papers']] == [
        'https://openalex.org/W_RELEVANT_MID',
        'https://openalex.org/W_RELEVANT_LOW',
    ]
    assert [paper['ref_no'] for paper in result['papers']] == [1, 2]
    assert result['papers'][1]['_duplicate_count'] == 2
    assert all('candidate_id' not in paper for paper in result['papers'])
    assert all(paper['id'] != irrelevant['id'] for paper in result['papers'])


FAKE_RETRIEVER = r'''
import argparse
import json
import os
import sys
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument('source')
parser.add_argument('--query', action='append', required=True)
parser.add_argument('--from-year', type=int)
parser.add_argument('--limit', type=int, required=True)
parser.add_argument('--sort', required=True)
parser.add_argument('--out', required=True)
args = parser.parse_args()

with open(os.environ['SEARCH_TEST_ARGV_LOG'], 'a', encoding='utf-8') as stream:
    stream.write(json.dumps(sys.argv[1:]) + '\n')

selected = os.environ['SEARCH_TEST_SELECTED_TERM']
sample_name = 'openalex_lim_t1.json' if args.query == [selected] else 'openalex_lim_ext.json'
payload = json.loads(Path(os.environ['SEARCH_TEST_SAMPLE_ROOT'], sample_name).read_text(encoding='utf-8'))
payload['query'] = args.query
payload['papers'] = payload['papers'][:args.limit]
Path(args.out).write_text(json.dumps(payload), encoding='utf-8')
print('offline fixture subprocess; not a network result')
'''


def run_offline_service(tmp_path, monkeypatch):
    script = tmp_path / 'fake_retriever.py'
    script.write_text(FAKE_RETRIEVER, encoding='utf-8')
    argv_log = tmp_path / 'argv.jsonl'
    monkeypatch.setenv('SEARCH_TEST_ARGV_LOG', str(argv_log))
    monkeypatch.setenv('SEARCH_TEST_SAMPLE_ROOT', str(SAMPLE_ROOT))
    monkeypatch.setenv('SEARCH_TEST_SELECTED_TERM', SELECTED_TERM)
    output_dir = tmp_path / 'run'
    request = SearchRequest(
        terms=[SELECTED_TERM],
        from_year=2023,
        mode='A',
        extensions=EXTENSIONS,
    )
    service = SearchService(output_dir=output_dir, script_path=script, limit=50)
    result = service.run(request)
    commands = [json.loads(line) for line in argv_log.read_text(encoding='utf-8').splitlines()]
    return result, commands, output_dir


def command_queries(command):
    return [command[index + 1] for index, value in enumerate(command) if value == '--query']


def test_service_uses_exact_selected_terms_and_scoped_year_arguments(tmp_path, monkeypatch):
    _, commands, _ = run_offline_service(tmp_path, monkeypatch)

    assert len(commands) == 6
    selected_commands = [command for command in commands if command_queries(command) == [SELECTED_TERM]]
    assert len(selected_commands) == 2
    limited = next(command for command in selected_commands if '--from-year' in command)
    unlimited = next(command for command in selected_commands if '--from-year' not in command)
    assert limited[limited.index('--from-year') + 1] == '2023'

    extension_commands = [command for command in commands if command not in selected_commands]
    assert {tuple(command_queries(command)) for command in extension_commands} == {
        (EXTENSIONS[0],),
        (EXTENSIONS[1],),
    }
    assert all(command_queries(command) != [SELECTED_TERM] + EXTENSIONS for command in commands)
    limited_commands = [command for command in commands if '--from-year' in command]
    assert len(limited_commands) == 3
    assert all(command[command.index('--from-year') + 1] == '2023' for command in limited_commands)
    assert len(commands) - len(limited_commands) == 3
    for command in commands:
        output_path = command[command.index('--out') + 1]
        if 'openalex_limited_' in output_path:
            assert command[command.index('--from-year') + 1] == '2023'
        else:
            assert 'openalex_unlimited_' in output_path
            assert '--from-year' not in command
    assert unlimited[unlimited.index('--query') + 1] == SELECTED_TERM


def test_service_writes_two_stable_pools_and_complete_search_log(tmp_path, monkeypatch):
    result, commands, output_dir = run_offline_service(tmp_path, monkeypatch)

    limited = json.loads((output_dir / 'papers.json').read_text(encoding='utf-8'))
    unlimited = json.loads((output_dir / 'papers_all.json').read_text(encoding='utf-8'))
    assert result['limited'] == limited
    assert result['unlimited'] == unlimited
    for payload, expected_year in [(limited, 2023), (unlimited, None)]:
        assert payload['terms'] == [SELECTED_TERM]
        assert payload['extensions'] == EXTENSIONS
        assert payload['from_year'] == expected_year
        assert 0 < payload['count'] <= 50
        assert payload['count'] == len(payload['papers'])
        assert [paper['ref_no'] for paper in payload['papers']] == list(
            range(1, payload['count'] + 1)
        )
        assert all('candidate_id' not in paper for paper in payload['papers'])
        assert all(paper['retrieval_relevance_rank'] >= 1 for paper in payload['papers'])
        assert payload['papers'][0]['retrieval_relevance_rank'] == 1
        assert all(paper['year'] >= 2023 for paper in limited['papers'])

    log = (output_dir / 'search_log.md').read_text(encoding='utf-8')
    assert log.count('- Command:') == len(commands) == 6
    assert log.count('- Hit count:') == 6
    assert log.count('- Returned count:') == 6
    assert log.count('- Output path:') == 6
    assert str(output_dir / 'openalex_limited_selected.json') in log
    assert str(output_dir / 'openalex_unlimited_selected.json') in log
    assert '1094' in log
    assert '1905' in log


@pytest.mark.skipif(
    os.environ.get('RUN_LIVE_OPENALEX_SMOKE') != '1',
    reason='Live OpenAlex smoke is opt-in; offline tests never access the network.',
)
def test_live_openalex_smoke_returns_five_real_records(tmp_path):
    request = SearchRequest(
        terms=[SELECTED_TERM], from_year=2023, mode='A', extensions=[]
    )
    result = SearchService(output_dir=tmp_path, limit=5).run(request)

    papers = result['limited']['papers']
    assert len(papers) == 5
    assert all(paper['source'] == 'openalex' for paper in papers)
    assert all(paper['id'] and paper['title'] for paper in papers)
    assert all(paper['type'] in {'article', 'review', 'preprint'} for paper in papers)
    assert [paper['ref_no'] for paper in papers] == [1, 2, 3, 4, 5]
