"""Live OpenAlex retrieval and deterministic limited/unlimited paper pools."""

import argparse
import json
import re
import shlex
import subprocess
import sys
import tempfile
import unicodedata
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Sequence
from urllib.parse import unquote


MAX_POOL_SIZE = 50
PAPER_TYPES = {'article', 'review', 'preprint'}
MODES = {'A', 'B', 'C1', 'C2', 'D'}
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SCRIPT = PROJECT_ROOT / 'skill_runtime' / 'scripts' / 'search_papers.py'

_TYPE_ALIASES = {
    'article': 'article',
    'journal-article': 'article',
    'journalarticle': 'article',
    'research-article': 'article',
    'review': 'review',
    'review-article': 'review',
    'reviewarticle': 'review',
    'preprint': 'preprint',
    'posted-content': 'preprint',
}
_STOP_WORDS = {
    'a', 'an', 'and', 'at', 'by', 'for', 'from', 'in', 'of', 'on', 'or',
    'the', 'to', 'with',
}


@dataclass(frozen=True)
class SearchRequest:
    """Selected terms and extensions remain distinct, verbatim inputs."""

    terms: Sequence[str]
    from_year: Optional[int]
    mode: str
    extensions: Sequence[str] = ()

    def __post_init__(self):
        if isinstance(self.terms, str) or isinstance(self.extensions, str):
            raise TypeError('terms and extensions must be sequences, not single strings')
        terms = list(self.terms)
        extensions = list(self.extensions)
        if not terms or any(not isinstance(term, str) or not term.strip() for term in terms):
            raise ValueError('at least one non-empty selected term is required')
        if any(not isinstance(term, str) or not term.strip() for term in extensions):
            raise ValueError('extensions must be non-empty strings')
        mode = str(self.mode).upper()
        if mode not in MODES:
            raise ValueError('mode must be one of A, B, C1, C2, D')
        object.__setattr__(self, 'terms', terms)
        object.__setattr__(self, 'extensions', extensions)
        object.__setattr__(self, 'mode', mode)


def _missing(value):
    return value is None or (isinstance(value, str) and not value.strip()) or (
        isinstance(value, (list, dict, tuple, set)) and not value
    )


def _as_int(value, default=None):
    if value is None or isinstance(value, bool):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _doi_key(value):
    if not isinstance(value, str) or not value.strip():
        return None
    doi = unquote(value.strip().strip('<>'))
    doi = re.sub(r'^https?://(?:dx\.)?doi\.org/', '', doi, flags=re.IGNORECASE)
    doi = re.sub(r'^doi:\s*', '', doi, flags=re.IGNORECASE)
    doi = doi.strip().rstrip('.,;').casefold()
    if not re.fullmatch(r'10\.\d{4,9}/\S+', doi):
        return None
    return doi


def _title_key(value):
    normalized = unicodedata.normalize('NFKC', str(value or '')).casefold()
    return ''.join(character for character in normalized if character.isalnum())


def _normalized_type(value):
    key = re.sub(r'[\s_]+', '-', str(value or '').strip().casefold())
    return _TYPE_ALIASES.get(key, key or None)


def _query_tokens(query):
    normalized = unicodedata.normalize('NFKC', str(query or '')).casefold()
    return [
        token for token in re.findall(r'[^\W_]+', normalized, flags=re.UNICODE)
        if token not in _STOP_WORDS
    ]


def _matches_query(text, query):
    text_key = _title_key(text)
    query_key = _title_key(query)
    if not query_key:
        return False
    if query_key in text_key:
        return True
    normalized_text = unicodedata.normalize('NFKC', text).casefold()
    tokens = _query_tokens(query)
    return bool(tokens) and all(token in normalized_text for token in tokens)


def _lexical_relevance_score(title, abstract, term_sets):
    """Score the best matching query using only deterministic lexical evidence."""

    text = (title or '') + '\n' + (abstract or '')
    title_key = _title_key(title)
    text_key = _title_key(text)
    normalized_title = unicodedata.normalize('NFKC', title or '').casefold()
    normalized_text = unicodedata.normalize('NFKC', text).casefold()
    best = 0
    for term_set in term_sets:
        for query in term_set:
            query_key = _title_key(query)
            if not query_key:
                continue
            # Exact phrase evidence dominates token coverage; title evidence is
            # stronger than abstract/body evidence. Coverage is scored per mille
            # so integer arithmetic is stable across Python versions/platforms.
            score = 0
            if query_key in title_key:
                score += 1_000_000
            if query_key in text_key:
                score += 500_000
            tokens = _query_tokens(query)
            if tokens:
                title_hits = sum(token in normalized_title for token in tokens)
                text_hits = sum(token in normalized_text for token in tokens)
                score += 10_000 * title_hits // len(tokens)
                score += 1_000 * text_hits // len(tokens)
            best = max(best, score)
    return best


def _normalize_record(record):
    paper = deepcopy(record)
    paper['title'] = str(paper.get('title') or '').strip()
    paper['type'] = _normalized_type(paper.get('type'))
    paper['year'] = _as_int(paper.get('year'))
    paper['cited_by_count'] = _as_int(paper.get('cited_by_count'))
    retrieval_rank = _as_int(
        paper.get('_retrieval_rank') or paper.get('retrieval_relevance_rank')
    )
    paper['_retrieval_rank'] = (
        retrieval_rank if retrieval_rank is not None and retrieval_rank > 0 else None
    )
    paper.pop('retrieval_relevance_rank', None)
    paper.pop('relevance_score', None)

    doi = _doi_key(paper.get('doi')) or _doi_key(paper.get('url'))
    paper['doi'] = 'https://doi.org/' + doi if doi else None
    if _missing(paper.get('url')) and paper['doi']:
        paper['url'] = paper['doi']
    if _missing(paper.get('url')) and str(paper.get('id') or '').startswith('http'):
        paper['url'] = paper['id']

    title_lower = paper['title'].casefold()
    paper['is_retracted'] = bool(paper.get('is_retracted')) or (
        title_lower.startswith(('retraction', 'retracted', 'corrigendum'))
        or '撤稿' in title_lower
    )
    paper['_force_exclude'] = (
        paper.get('relevant') is False
        or paper.get('_relevant') is False
        or paper.get('is_relevant') is False
    )
    paper['_doi_key'] = doi
    paper['_title_key'] = _title_key(paper['title'])
    return paper


def _record_preference(paper):
    type_rank = {'article': 0, 'review': 0, 'preprint': 1}.get(paper.get('type'), 2)
    filled_fields = sum(not _missing(value) for key, value in paper.items() if not key.startswith('_'))
    return (
        1 if paper.get('_force_exclude') else 0,
        type_rank,
        0 if paper.get('source') == 'openalex' else 1,
        1 if paper.get('_query_kind') == 'extension' else 0,
        0 if not _missing(paper.get('abstract')) else 1,
        -(paper.get('cited_by_count') or 0),
        -(paper.get('year') or 0),
        -filled_fields,
        paper.get('_title_key') or '',
        paper.get('_doi_key') or '',
        json.dumps(paper, ensure_ascii=False, sort_keys=True, default=str),
    )


def _merge_group(group):
    ordered = sorted(group, key=_record_preference)
    merged = deepcopy(ordered[0])
    for paper in ordered[1:]:
        for key, value in paper.items():
            if key in {'candidate_id', 'ref_no'}:
                continue
            if _missing(merged.get(key)) and not _missing(value):
                merged[key] = deepcopy(value)

    merged['is_retracted'] = any(paper.get('is_retracted') for paper in group)
    merged['_force_exclude'] = any(paper.get('_force_exclude') for paper in group)
    ranks = [
        paper['_retrieval_rank'] for paper in group
        if paper.get('_retrieval_rank') is not None
    ]
    merged['_retrieval_rank'] = min(ranks) if ranks else None
    kinds = {paper.get('_query_kind') for paper in group if paper.get('_query_kind')}
    merged['_query_kind'] = 'selected' if not kinds or 'selected' in kinds else 'extension'

    term_sets = []
    seen_term_sets = set()
    for paper in group:
        terms = paper.get('_query_terms') or []
        key = tuple(terms)
        if key and key not in seen_term_sets:
            seen_term_sets.add(key)
            term_sets.append(list(terms))
    merged['_query_term_sets'] = sorted(term_sets)

    origins = set()
    references = set()
    for paper in group:
        origins.update(str(origin) for origin in paper.get('_origins') or [])
        references.update(str(reference) for reference in paper.get('referenced_works') or [])
    if origins:
        merged['_origins'] = sorted(origins)
    if references:
        merged['referenced_works'] = sorted(references)
    merged['_duplicate_count'] = len(group)

    if merged.get('doi'):
        merged['doi'] = 'https://doi.org/' + merged['_doi_key']
    if _missing(merged.get('url')) and merged.get('doi'):
        merged['url'] = merged['doi']
    return merged


def _selection_key(paper, mode):
    selected_origin = 1 if paper.get('_query_kind') == 'extension' else 0
    citations = -(paper.get('cited_by_count') or 0)
    recency = -(paper.get('year') or 0)
    abstract_last = 0 if not _missing(paper.get('abstract')) else 1
    if mode == 'A':
        rank = paper.get('_retrieval_rank')
        rank_key = (0, rank) if rank is not None else (1, 0)
        # OpenAlex's relevance order is authoritative when available. Lexical
        # relevance is the deterministic fallback and tie-breaker; citations
        # and recency only rank records after those relevance signals.
        mode_key = rank_key + (-paper.get('_relevance_score', 0), citations, recency)
    elif mode == 'B':
        mode_key = (recency, citations)
    elif mode == 'C2':
        mode_key = (abstract_last, citations, recency)
    elif mode == 'D':
        mode_key = (abstract_last, recency, citations)
    else:  # C1 established-writing references prioritize citations.
        mode_key = (citations, recency)
    return (
        (selected_origin,) + mode_key + (
            paper.get('_title_key') or '',
            paper.get('_doi_key') or str(paper.get('id') or ''),
        )
    )


def _finish_paper(paper):
    paper['claim_eligible'] = not _missing(paper.get('abstract'))
    if paper.get('oa_url') or paper.get('pdf_url'):
        paper['evidence_level'] = 'A'
    elif paper.get('abstract'):
        paper['evidence_level'] = 'B'
    else:
        paper['evidence_level'] = 'C'
    paper.pop('candidate_id', None)
    paper.pop('ref_no', None)
    paper['relevance_score'] = paper.get('_relevance_score', 0)
    if paper.get('_retrieval_rank') is not None:
        paper['retrieval_relevance_rank'] = paper['_retrieval_rank']
    for key in list(paper):
        if key.startswith('_') and key not in {'_origins', '_duplicate_count'}:
            del paper[key]
    return paper


def merge_records(records, limit=MAX_POOL_SIZE, from_year=None, terms=None, mode='A'):
    """Merge identities, backfill real fields, filter, select, then number publicly."""

    mode = str(mode).upper()
    if mode not in MODES:
        raise ValueError('mode must be one of A, B, C1, C2, D')
    limit = int(limit)
    if limit < 0:
        raise ValueError('limit cannot be negative')
    limit = min(limit, MAX_POOL_SIZE)
    normalized = [_normalize_record(record) for record in records if isinstance(record, dict)]

    parents = list(range(len(normalized)))

    def find(index):
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    def union(left, right):
        left_root, right_root = find(left), find(right)
        if left_root != right_root:
            if left_root < right_root:
                parents[right_root] = left_root
            else:
                parents[left_root] = right_root

    owners = {}
    for index, paper in enumerate(normalized):
        for identity in (('doi', paper['_doi_key']), ('title', paper['_title_key'])):
            if not identity[1]:
                continue
            if identity in owners:
                union(index, owners[identity])
            else:
                owners[identity] = index

    groups = {}
    for index in range(len(normalized)):
        groups.setdefault(find(index), []).append(normalized[index])

    eligible = []
    for group in groups.values():
        paper = _merge_group(group)
        if not paper['_title_key'] or paper['is_retracted'] or paper['_force_exclude']:
            continue
        if paper.get('type') not in PAPER_TYPES:
            continue
        if from_year is not None and (paper.get('year') is None or paper['year'] < from_year):
            continue

        if terms is not None:
            term_sets = [list(terms)]
        else:
            term_sets = paper.get('_query_term_sets') or []
        paper['_relevance_score'] = _lexical_relevance_score(
            paper.get('title'), paper.get('abstract'), term_sets
        )
        if term_sets:
            text = (paper.get('title') or '') + '\n' + (paper.get('abstract') or '')
            if not any(
                _matches_query(text, query)
                for term_set in term_sets
                for query in term_set
            ):
                continue
        eligible.append(paper)

    eligible.sort(key=lambda paper: _selection_key(paper, mode))
    selected = [_finish_paper(paper) for paper in eligible[:limit]]
    for ref_no, paper in enumerate(selected, 1):
        paper['ref_no'] = ref_no
    return {
        'mode': mode,
        'from_year': from_year,
        'count': len(selected),
        'papers': selected,
    }


class SearchService:
    """Run the copied Skill script and persist two independently scoped pools."""

    def __init__(
        self,
        output_dir,
        script_path=DEFAULT_SCRIPT,
        limit=MAX_POOL_SIZE,
        timeout=120,
        python_executable=None,
    ):
        self.output_dir = Path(output_dir).resolve()
        self.script_path = Path(script_path).resolve()
        self.limit = min(int(limit), MAX_POOL_SIZE)
        if self.limit < 1:
            raise ValueError('limit must be between 1 and 50')
        self.timeout = timeout
        self.python_executable = python_executable or sys.executable

    def _retrieve(self, terms, from_year, output_path):
        command = [self.python_executable, str(self.script_path), 'openalex']
        for term in terms:
            command.extend(['--query', term])
        if from_year is not None:
            command.extend(['--from-year', str(from_year)])
        command.extend([
            '--limit', str(self.limit), '--sort', 'relevance', '--out', str(output_path),
        ])
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=self.timeout,
            check=False,
        )
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or '').strip()
            raise RuntimeError(
                'OpenAlex retrieval failed with exit code {}: {}'.format(
                    completed.returncode, detail or 'no subprocess diagnostic'
                )
            )
        try:
            payload = json.loads(output_path.read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError) as error:
            raise RuntimeError('OpenAlex retrieval did not write valid JSON: {}'.format(error)) from error
        if not isinstance(payload.get('papers'), list):
            raise RuntimeError('OpenAlex retrieval JSON has no papers list')
        return payload, command

    def _append_log(self, scope, kind, command, payload, output_path):
        log_path = self.output_dir / 'search_log.md'
        if not log_path.exists():
            log_path.write_text('# Search log\n', encoding='utf-8')
        timestamp = datetime.now(timezone.utc).isoformat()
        entry = (
            '\n## {timestamp} | {scope} | {kind}\n'
            '- Command: `{command}`\n'
            '- Hit count: {hits}\n'
            '- Returned count: {returned}\n'
            '- Output path: `{output}`\n'
        ).format(
            timestamp=timestamp,
            scope=scope,
            kind=kind,
            command=shlex.join(command).replace('`', '\\`'),
            hits=payload.get('total_hits'),
            returned=len(payload['papers']),
            output=str(output_path),
        )
        with log_path.open('a', encoding='utf-8') as stream:
            stream.write(entry)

    def run(self, request):
        self.output_dir.mkdir(parents=True, exist_ok=True)
        pools = {}
        for scope in ('limited', 'unlimited'):
            records = []
            requests = [('selected', list(request.terms), 'selected')]
            requests.extend(
                ('extension', [extension], 'extension_{:02d}'.format(index))
                for index, extension in enumerate(request.extensions, 1)
            )
            for kind, terms, stem in requests:
                output_path = self.output_dir / 'openalex_{}_{}.json'.format(scope, stem)
                from_year = request.from_year if scope == 'limited' else None
                payload, command = self._retrieve(terms, from_year, output_path)
                self._append_log(scope, stem, command, payload, output_path)
                for retrieval_rank, record in enumerate(payload['papers'], 1):
                    if not isinstance(record, dict):
                        continue
                    paper = deepcopy(record)
                    paper['_retrieval_rank'] = retrieval_rank
                    paper['_query_terms'] = list(terms)
                    paper['_query_kind'] = 'selected' if kind == 'selected' else 'extension'
                    origins = list(paper.get('_origins') or [])
                    origins.append('{}:{}'.format(scope, stem))
                    paper['_origins'] = origins
                    records.append(paper)

            pool = merge_records(
                records,
                limit=self.limit,
                from_year=request.from_year if scope == 'limited' else None,
                mode=request.mode,
            )
            pool.update({
                'scope': scope,
                'terms': list(request.terms),
                'extensions': list(request.extensions),
            })
            filename = 'papers.json' if scope == 'limited' else 'papers_all.json'
            _write_json(self.output_dir / filename, pool)
            pools[scope] = pool

        return {
            'limited': pools['limited'],
            'unlimited': pools['unlimited'],
            'search_log': str(self.output_dir / 'search_log.md'),
        }


def _write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8'
    )
    temporary.replace(path)


def main(argv=None):
    parser = argparse.ArgumentParser(description='Retrieve real OpenAlex papers into two scoped pools.')
    parser.add_argument('--query', action='append', required=True, help='Exact selected user term; repeatable')
    parser.add_argument('--extension', action='append', default=[], help='Separate expansion term; repeatable')
    parser.add_argument('--from-year', type=int, default=None)
    parser.add_argument('--mode', default='A', choices=sorted(MODES))
    parser.add_argument('--limit', type=int, default=MAX_POOL_SIZE)
    parser.add_argument('--output-dir', help='Directory for both pools, raw JSON, and search_log.md')
    parser.add_argument(
        '--dry-run-output',
        help='Run live retrieval but write only the limited pool to this explicit JSON path',
    )
    args = parser.parse_args(argv)
    if not args.dry_run_output and not args.output_dir:
        parser.error('--output-dir is required unless --dry-run-output is supplied')

    request = SearchRequest(
        terms=args.query,
        from_year=args.from_year,
        mode=args.mode,
        extensions=args.extension,
    )
    try:
        if args.dry_run_output:
            with tempfile.TemporaryDirectory(prefix='purpose-landscape-openalex-') as directory:
                result = SearchService(output_dir=directory, limit=args.limit).run(request)
                limited = result['limited']
                output = Path(args.dry_run_output).resolve()
                _write_json(output, limited)
                print('Live OpenAlex smoke: {} returned records'.format(limited['count']))
                print('Limited pool written to: {}'.format(output))
        else:
            result = SearchService(output_dir=args.output_dir, limit=args.limit).run(request)
            print('Limited pool: {}'.format(Path(result['limited']['scope'])))
            print('Output directory: {}'.format(Path(args.output_dir).resolve()))
            print('Search log: {}'.format(result['search_log']))
    except (RuntimeError, subprocess.TimeoutExpired) as error:
        parser.exit(1, 'Live OpenAlex retrieval failed: {}\n'.format(error))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
