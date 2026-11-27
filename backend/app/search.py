"""Live multi-source retrieval and deterministic limited/unlimited paper pools."""

import argparse
import json
import os
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
MODES = {'A', 'B', 'C1', 'C2', 'D', 'E'}
BASE_SOURCE = 'openalex'
SEARCH_SOURCES = ('openalex', 'arxiv', 'crossref', 'semantic_scholar')
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SCRIPT = PROJECT_ROOT / 'skill_runtime' / 'scripts' / 'search_papers.py'

# The Skill routes by topic, not by the user's assumed database preference:
# domain-only education/medical/social-science questions stay on OpenAlex,
# technical/AI questions add arXiv, and Chinese terms add Crossref bibliographic
# records. Semantic Scholar stays off unless a caller opts in explicitly.
_TECH_MARKERS = (
    '计算机', '人工智能', '机器学习', '深度学习', '神经网络', '大模型', '自然语言',
    '机器人', '算法', '工程', '自动化', '智能交通', '控制系统', '物理', '数学',
    'computer science', 'computer vision', 'machine learning', 'deep learning',
    'artificial intelligence', 'neural network', 'natural language',
    'large language model', 'algorithm', 'robotics', 'engineering', 'automation',
    'autonomous', 'control system', 'physics', 'mathematics', 'software',
)
_SHORT_EN_MARKERS = {'ai', 'llm', 'nlp', 'ml', 'cv'}
_DOMAIN_ONLY_MARKERS = (
    '教育', '医学', '医疗', '临床', '社科', '社会科学', '社会学',
    'education', 'medical', 'medicine', 'clinical', 'social science', 'sociology',
)
_CJK_RE = re.compile(r'[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]')

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
    direction: str = ''
    semantic_scholar: bool = False

    def __post_init__(self):
        if isinstance(self.terms, str) or isinstance(self.extensions, str):
            raise TypeError('terms and extensions must be sequences, not single strings')
        if not isinstance(self.direction, str) or not isinstance(self.semantic_scholar, bool):
            raise TypeError('direction must be a string and semantic_scholar must be a bool')
        terms = list(self.terms)
        extensions = list(self.extensions)
        if not terms or any(not isinstance(term, str) or not term.strip() for term in terms):
            raise ValueError('at least one non-empty selected term is required')
        if any(not isinstance(term, str) or not term.strip() for term in extensions):
            raise ValueError('extensions must be non-empty strings')
        mode = str(self.mode).upper()
        if mode not in MODES:
            raise ValueError('mode must be one of A, B, C1, C2, D, E')
        object.__setattr__(self, 'terms', terms)
        object.__setattr__(self, 'extensions', extensions)
        object.__setattr__(self, 'mode', mode)


@dataclass(frozen=True)
class SourcePlan:
    """Deterministic routing outcome, shared by both scope passes."""

    sources: Sequence[str]
    reasons: Sequence[str]
    technical: bool = False
    chinese: bool = False

    def as_dict(self):
        return {
            'sources': list(self.sources),
            'reasons': list(self.reasons),
            'technical': self.technical,
            'chinese': self.chinese,
        }


def _has_marker(text, marker):
    if marker in _SHORT_EN_MARKERS:
        return re.search(r'(?<![a-z])' + re.escape(marker) + r'(?![a-z])', text) is not None
    return marker in text


def plan_sources(direction='', terms=(), extensions=(), semantic_scholar=False):
    """Choose supplementary sources from the direction and verbatim terms.

    OpenAlex is always queried. arXiv is added for technical/AI topics (including
    AI applied to another domain). Crossref is added only when a Chinese selected
    or extension term is present; English-only term sets deliberately skip it even
    if the direction itself is written in Chinese. Semantic Scholar is opt-in
    because its bulk endpoint is rate-limited and has no referenced_works edges.
    """

    values = [str(direction or '')]
    selected_values = [str(value) for value in list(terms or []) + list(extensions or [])]
    values.extend(selected_values)
    haystack = ' '.join(values).casefold()
    chinese = any(_CJK_RE.search(value) for value in selected_values)
    technical = any(
        _has_marker(haystack, marker)
        for marker in tuple(_TECH_MARKERS) + tuple(sorted(_SHORT_EN_MARKERS))
    )
    domain_only = any(_has_marker(haystack, marker) for marker in _DOMAIN_ONLY_MARKERS)

    sources = [BASE_SOURCE]
    reasons = ['OpenAlex is the required base source']
    if technical:
        sources.append('arxiv')
        reasons.append('technical/AI topic markers detected')
    elif domain_only:
        reasons.append('domain-only education/medical/social-science topic stays on OpenAlex')
    else:
        reasons.append('no technical/AI marker detected')
    if chinese:
        sources.append('crossref')
        reasons.append('Chinese selected/extension term detected; Crossref adds bibliographic records')
    else:
        reasons.append('English-only request skips Crossref')
    if semantic_scholar:
        sources.append('semantic_scholar')
        reasons.append('Semantic Scholar explicitly requested as an optional supplement')
    return SourcePlan(tuple(sources), tuple(reasons), technical=technical, chinese=chinese)


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


def _matches_query_relaxed(text, query):
    tokens = _query_tokens(query)
    if not tokens:
        return False
    normalized_text = unicodedata.normalize('NFKC', text or '').casefold()
    hits = sum(token in normalized_text for token in tokens)
    required = max(1, (len(tokens) + 1) // 2)
    return hits >= required and (hits >= 2 or len(tokens) == 1)


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


_SOURCE_PREFERENCE = {
    'openalex': 0, 'crossref': 1, 'arxiv': 2, 'semantic_scholar': 3,
}


def _record_preference(paper):
    type_rank = {'article': 0, 'review': 0, 'preprint': 1}.get(paper.get('type'), 2)
    filled_fields = sum(not _missing(value) for key, value in paper.items() if not key.startswith('_'))
    return (
        1 if paper.get('_force_exclude') else 0,
        type_rank,
        _SOURCE_PREFERENCE.get(paper.get('source'), 4),
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
    retrieval_sources = set()
    references = set()
    for paper in group:
        origins.update(str(origin) for origin in paper.get('_origins') or [])
        retrieval_sources.update(str(source) for source in paper.get('_retrieval_sources') or [])
        if paper.get('source'):
            retrieval_sources.add(str(paper['source']))
        references.update(str(reference) for reference in paper.get('referenced_works') or [])
    if origins:
        merged['_origins'] = sorted(origins)
    if retrieval_sources:
        merged['_retrieval_sources'] = sorted(retrieval_sources)
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
    if mode in {'A', 'E'}:
        rank = paper.get('_retrieval_rank')
        rank_key = (0, rank) if rank is not None else (1, 0)
        # OpenAlex's relevance order is authoritative when available. Lexical
        # relevance is the deterministic fallback and tie-breaker; citations
        # and recency only rank records after those relevance signals. E is the
        # baseline scoping mode and shares A's selection order.
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
    retrieval_sources = set(paper.get('_retrieval_sources') or [])
    if paper.get('source'):
        retrieval_sources.add(str(paper['source']))
    if retrieval_sources:
        paper['retrieval_sources'] = sorted(retrieval_sources)
    for key in list(paper):
        if key.startswith('_') and key not in {'_origins', '_duplicate_count'}:
            del paper[key]
    return paper


def min_pool_size():
    raw = os.environ.get('SEARCH_MIN_POOL', '10')
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        return 10
    return max(0, value)


def merge_records(records, limit=MAX_POOL_SIZE, from_year=None, terms=None, mode='A', min_pool=0):
    """Merge identities, backfill real fields, filter, select, then number publicly."""

    mode = str(mode).upper()
    if mode not in MODES:
        raise ValueError('mode must be one of A, B, C1, C2, D, E')
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
    valid_candidates = []
    for group in groups.values():
        paper = _merge_group(group)
        if not paper['_title_key'] or paper['is_retracted'] or paper['_force_exclude']:
            continue
        if paper.get('type') not in PAPER_TYPES:
            continue
        if from_year is not None and (paper.get('year') is None or paper['year'] < from_year):
            continue
        valid_candidates.append(paper)

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

    if min_pool and len(eligible) < min_pool:
        selected_keys = {paper['_title_key'] for paper in eligible}
        for paper in valid_candidates:
            if len(eligible) >= min_pool:
                break
            if paper['_title_key'] in selected_keys:
                continue
            term_sets = [list(terms)] if terms is not None else (paper.get('_query_term_sets') or [])
            text = (paper.get('title') or '') + '\n' + (paper.get('abstract') or '')
            if not any(
                _matches_query_relaxed(text, query)
                for term_set in term_sets
                for query in term_set
            ):
                continue
            paper['_relevance_score'] = _lexical_relevance_score(
                paper.get('title'), paper.get('abstract'), term_sets
            )
            eligible.append(paper)
            selected_keys.add(paper['_title_key'])

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


def _degrade_reason(error):
    if isinstance(error, subprocess.TimeoutExpired):
        return 'timeout after {}s'.format(error.timeout)
    detail = ' '.join(str(error).split())
    return '{}: {}'.format(type(error).__name__, detail[:300] or 'no diagnostic')


class SearchService:
    """Run the Skill scripts by routed source; keep two independently scoped pools."""

    # search_papers.py uses a 30s socket timeout, bounded 429 backoff (<=60s for
    # OpenAlex/arXiv/Crossref, 30/60/90s for S2) and potentially two arXiv calls.
    # Outer limits leave room for those retries; an explicit timeout overrides all.
    SOURCE_TIMEOUTS = {
        'openalex': 300, 'arxiv': 180, 'crossref': 180, 'semantic_scholar': 300,
    }

    def __init__(
        self,
        output_dir,
        script_path=DEFAULT_SCRIPT,
        limit=MAX_POOL_SIZE,
        timeout=None,
        python_executable=None,
        source_timeouts=None,
    ):
        self.output_dir = Path(output_dir).resolve()
        self.script_path = Path(script_path).resolve()
        self.limit = min(int(limit), MAX_POOL_SIZE)
        if self.limit < 1:
            raise ValueError('limit must be between 1 and 50')
        if timeout is None:
            self.source_timeouts = dict(self.SOURCE_TIMEOUTS)
        else:
            self.source_timeouts = {
                source: int(timeout) for source in SEARCH_SOURCES
            }
        if source_timeouts:
            for source, value in source_timeouts.items():
                if source not in SEARCH_SOURCES:
                    raise ValueError('unknown source for timeout: {}'.format(source))
                self.source_timeouts[source] = int(value)
        self.timeout = self.source_timeouts[BASE_SOURCE]
        self.python_executable = python_executable or sys.executable

    def _retrieve(self, terms, from_year, output_path, source=BASE_SOURCE):
        if source not in SEARCH_SOURCES:
            raise ValueError('unknown search source: {}'.format(source))
        command = [self.python_executable, str(self.script_path), source]
        for term in terms:
            command.extend(['--query', term])
        # arXiv's script accepts but does not apply --from-year; the shared pool
        # filter still enforces it after retrieval.
        if from_year is not None and source != 'arxiv':
            command.extend(['--from-year', str(from_year)])
        command.extend([
            '--limit', str(self.limit), '--sort', 'relevance', '--out', str(output_path),
        ])
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=self.source_timeouts[source],
            check=False,
        )
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or '').strip()
            raise RuntimeError(
                '{} retrieval failed with exit code {}: {}'.format(
                    source, completed.returncode, detail or 'no subprocess diagnostic'
                )
            )
        try:
            payload = json.loads(output_path.read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError) as error:
            raise RuntimeError('{} retrieval did not write valid JSON: {}'.format(source, error)) from error
        if not isinstance(payload.get('papers'), list):
            raise RuntimeError('{} retrieval JSON has no papers list'.format(source))
        return payload, command

    def _append_log(
        self, scope, kind, command, payload, output_path,
        source=BASE_SOURCE, status='ok', reason=None, retrieval_sources=None,
    ):
        log_path = self.output_dir / 'search_log.md'
        if not log_path.exists():
            log_path.write_text('# Search log\n', encoding='utf-8')
        timestamp = datetime.now(timezone.utc).isoformat()
        papers = payload.get('papers') if isinstance(payload, dict) else None
        entry = (
            '\n## {timestamp} | {scope} | {kind}\n'
            '- Source: {source}\n'
            '- Status: {status}\n'
            '- Command: `{command}`\n'
            '- Hit count: {hits}\n'
            '- Returned count: {returned}\n'
            '- Output path: `{output}`\n'
        ).format(
            timestamp=timestamp,
            scope=scope,
            kind=kind,
            source=source,
            status=status,
            command=shlex.join(command).replace('`', '\\`'),
            hits=payload.get('total_hits') if isinstance(payload, dict) else None,
            returned=len(papers) if isinstance(papers, list) else 0,
            output=str(output_path),
        )
        if reason:
            safe_reason = ' '.join(str(reason).split()).replace('`', '\\`')[:500]
            entry += '- Reason: ' + safe_reason + '\n'
        if retrieval_sources is not None:
            entry += '- retrieval_sources: {}\n'.format(
                json.dumps(list(retrieval_sources), ensure_ascii=False)
            )
        with log_path.open('a', encoding='utf-8') as stream:
            stream.write(entry)

    def _append_merged_sources_log(self, scope, pool):
        """Mirror the papers.json retrieval_sources field after merging."""

        log_path = self.output_dir / 'search_log.md'
        payload = [
            {
                'ref_no': paper.get('ref_no'),
                'retrieval_sources': paper.get('retrieval_sources') or [],
                'doi': paper.get('doi'),
                'title': paper.get('title'),
            }
            for paper in pool['papers']
        ]
        entry = (
            '\n## {} | {} | retrieval_sources\n'
            '- retrieval_sources: {}\n'
        ).format(
            datetime.now(timezone.utc).isoformat(),
            scope,
            json.dumps(payload, ensure_ascii=False),
        )
        with log_path.open('a', encoding='utf-8') as stream:
            stream.write(entry)

    def run(self, request):
        self.output_dir.mkdir(parents=True, exist_ok=True)
        plan = plan_sources(
            direction=getattr(request, 'direction', '') or '',
            terms=request.terms,
            extensions=getattr(request, 'extensions', ()),
            semantic_scholar=getattr(request, 'semantic_scholar', False),
        )
        pools = {}
        degradations = []
        for scope in ('limited', 'unlimited'):
            records = []
            requests = [('selected', list(request.terms), 'selected')]
            requests.extend(
                ('extension', [extension], 'extension_{:02d}'.format(index))
                for index, extension in enumerate(request.extensions, 1)
            )
            for kind, terms, stem in requests:
                from_year = request.from_year if scope == 'limited' else None
                for source in plan.sources:
                    output_path = self.output_dir / '{}_{}_{}.json'.format(source, scope, stem)
                    try:
                        payload, command = self._retrieve(
                            terms, from_year, output_path, source=source
                        )
                    except (RuntimeError, OSError, subprocess.TimeoutExpired) as error:
                        reason = _degrade_reason(error)
                        if source == BASE_SOURCE:
                            raise
                        degradations.append({
                            'scope': scope, 'stem': stem, 'source': source, 'reason': reason,
                        })
                        self._append_log(
                            scope, stem,
                            [self.python_executable, str(self.script_path), source],
                            None, output_path, source=source,
                            status='degraded', reason=reason,
                            retrieval_sources=[],
                        )
                        continue
                    self._append_log(
                        scope, stem, command, payload, output_path, source=source,
                        retrieval_sources=[source],
                    )
                    for retrieval_rank, record in enumerate(payload['papers'], 1):
                        if not isinstance(record, dict):
                            continue
                        paper = deepcopy(record)
                        paper['_retrieval_rank'] = retrieval_rank
                        paper['_query_terms'] = list(terms)
                        paper['_query_kind'] = 'selected' if kind == 'selected' else 'extension'
                        paper['_retrieval_sources'] = [source]
                        origins = list(paper.get('_origins') or [])
                        origins.append('{}:{}'.format(scope, stem))
                        paper['_origins'] = origins
                        records.append(paper)

            pool = merge_records(
                records,
                limit=self.limit,
                from_year=request.from_year if scope == 'limited' else None,
                mode=request.mode,
                min_pool=min_pool_size(),
            )
            pool.update({
                'scope': scope,
                'terms': list(request.terms),
                'extensions': list(request.extensions),
                'sources': list(plan.sources),
                'degraded_sources': [item for item in degradations if item['scope'] == scope],
            })
            filename = 'papers.json' if scope == 'limited' else 'papers_all.json'
            _write_json(self.output_dir / filename, pool)
            self._append_merged_sources_log(scope, pool)
            pools[scope] = pool

        return {
            'limited': pools['limited'],
            'unlimited': pools['unlimited'],
            'search_log': str(self.output_dir / 'search_log.md'),
            'source_plan': plan.as_dict(),
            'degraded_sources': degradations,
        }


def _write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8'
    )
    temporary.replace(path)


def main(argv=None):
    parser = argparse.ArgumentParser(description='Retrieve real papers into two routed scoped pools.')
    parser.add_argument('--query', action='append', required=True, help='Exact selected user term; repeatable')
    parser.add_argument('--extension', action='append', default=[], help='Separate expansion term; repeatable')
    parser.add_argument('--direction', default='', help='Research direction used for topic routing')
    parser.add_argument('--semantic-scholar', action='store_true', help='Opt in to the optional S2 supplement')
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
        direction=args.direction,
        semantic_scholar=args.semantic_scholar,
    )
    try:
        if args.dry_run_output:
            with tempfile.TemporaryDirectory(prefix='purpose-landscape-search-') as directory:
                result = SearchService(output_dir=directory, limit=args.limit).run(request)
                limited = result['limited']
                output = Path(args.dry_run_output).resolve()
                _write_json(output, limited)
                print('Live routed smoke: {} returned records'.format(limited['count']))
                print('Sources: {}'.format(', '.join(limited['sources'])))
                print('Limited pool written to: {}'.format(output))
        else:
            result = SearchService(output_dir=args.output_dir, limit=args.limit).run(request)
            print('Limited pool: {}'.format(Path(result['limited']['scope'])))
            print('Sources: {}'.format(', '.join(result['source_plan']['sources'])))
            print('Output directory: {}'.format(Path(args.output_dir).resolve()))
            print('Search log: {}'.format(result['search_log']))
    except (RuntimeError, subprocess.TimeoutExpired) as error:
        parser.exit(1, 'Live retrieval failed: {}\n'.format(error))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
