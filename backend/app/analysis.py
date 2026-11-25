"""Structured literature analysis with mandatory abstract-evidence auditing."""

import json
import re
import unicodedata
from dataclasses import dataclass
from typing import Optional


CONFIDENCE_LABELS = {'high', 'medium', 'low'}
RELATION_LABELS = {'support', 'improve', 'conflict', 'difference'}
POLARITY_LABELS = {'pos', 'neg'}
MAX_CROSS_BATCH_PAIRS = 20
MIN_PAIR_SIMILARITY = 0.12

# These are examples of broad acquisition families, not a closed list of methods.
GENERIC_METHOD_FAMILIES = (
    '文献与二手数据',
    '问卷调查与观察性数据',
    '临床与生物样本',
    '实验与干预',
    '计算建模与仿真',
    '数据驱动与机器学习',
    '测量表征与工程验证',
)

_SIMILARITY_STOP_WORDS = {
    'a', 'an', 'and', 'are', 'as', 'at', 'be', 'by', 'for', 'from', 'in',
    'is', 'it', 'of', 'on', 'or', 'our', 'that', 'the', 'their', 'this',
    'to', 'using', 'we', 'were', 'with',
}


@dataclass(frozen=True)
class FactorVote:
    factor: str
    outcome: str
    polarity: str
    ref: int
    quote: str
    effect: str = ''
    confidence: Optional[str] = None


@dataclass(frozen=True)
class SemanticRelation:
    s: int
    t: int
    type: str
    reason: str
    evidence_ref: int
    quote: str
    basis_ref: int
    basis_quote: str
    confidence: str


def verbatim_quote(abstract, quote):
    """Accept only nonempty normalized-whitespace substrings of a real abstract."""

    if not isinstance(abstract, str) or not isinstance(quote, str):
        return False
    normalize = lambda value: ' '.join(value.split())
    normalized_abstract = normalize(abstract)
    normalized_quote = normalize(quote)
    return bool(normalized_abstract and normalized_quote) and normalized_quote in normalized_abstract


def _value(record, key, default=None):
    if isinstance(record, dict):
        return record.get(key, default)
    return getattr(record, key, default)


def _paper_ref(paper):
    ref = _value(paper, 'ref_no', _value(paper, 'ref'))
    return ref if type(ref) is int and ref > 0 else None


def _item_ref(item, key='ref'):
    if not isinstance(item, dict):
        return None
    ref = item.get(key)
    return ref if type(ref) is int and ref > 0 else None


def _text(value):
    return value.strip() if isinstance(value, str) and value.strip() else None


def _confidence(value, required=True):
    if value is None and not required:
        return None
    return value if value in CONFIDENCE_LABELS else None


def _abstract_index(papers):
    indexed = {}
    for paper in papers:
        ref = _paper_ref(paper)
        abstract = _value(paper, 'abstract')
        if ref is None or not isinstance(abstract, str) or not abstract.strip():
            continue
        if ref in indexed:
            raise ValueError('Duplicate paper ref_no: {}'.format(ref))
        indexed[ref] = (paper, abstract)
    return indexed


def _paper_payload(indexed):
    return [
        {
            'ref': ref,
            'title': _value(paper, 'title', '') or '',
            'abstract': abstract,
        }
        for ref, (paper, abstract) in indexed.items()
    ]


def _batches(items, size):
    for start in range(0, len(items), size):
        yield items[start:start + size]


def _batch_index(indexed, batch):
    return {item['ref']: indexed[item['ref']] for item in batch}


def _label_key(value):
    normalized = unicodedata.normalize('NFKC', value or '')
    return ' '.join(normalized.split()).casefold()


def _valid_method_role(item):
    declared_roles = [item[key] for key in ('role', 'type') if key in item]
    for role in declared_roles:
        if not isinstance(role, str):
            return False
        normalized = re.sub(r'[\s-]+', '_', _label_key(role))
        if normalized != 'method':
            return False
    return True


def _valid_method_labels(key, family, technique, topic_names):
    if not key or not re.fullmatch(r'[a-z][a-z0-9_]{0,79}', key):
        return False
    if not family or not technique or family == technique:
        return False
    if _label_key(family) in topic_names or _label_key(technique) in topic_names:
        return False
    return True


def _identifier(value):
    if isinstance(value, dict):
        identifiers = set()
        for key in ('id', 'doi', 'url'):
            identifiers.update(_identifier(value.get(key)))
        return identifiers
    if isinstance(value, (list, tuple, set, frozenset)):
        identifiers = set()
        for item in value:
            identifiers.update(_identifier(item))
        return identifiers
    if not isinstance(value, str) or not value.strip():
        return set()
    normalized = unicodedata.normalize('NFKC', value).strip().casefold().rstrip('/')
    normalized = re.sub(r'^https?://(?:dx\.)?doi\.org/', 'doi:', normalized)
    normalized = re.sub(r'^doi:\s*', 'doi:', normalized)
    openalex = re.fullmatch(r'https?://openalex\.org/([^/]+)', normalized)
    if openalex:
        normalized = 'openalex:' + openalex.group(1)
    return {normalized}


def _paper_identifiers(paper):
    identifiers = set()
    for key in ('id', 'doi', 'url'):
        identifiers.update(_identifier(_value(paper, key)))
    return identifiers


def _citation_linked(left, right):
    for citing, cited in ((left, right), (right, left)):
        references = _value(citing, 'referenced_works', ()) or ()
        if isinstance(references, (str, dict)):
            references = [references]
        reference_ids = set()
        for reference in references:
            reference_ids.update(_identifier(reference))
        if reference_ids & _paper_identifiers(cited):
            return True
    return False


def _text_tokens(value):
    normalized = unicodedata.normalize('NFKC', str(value or '')).casefold()
    raw_tokens = re.findall(
        r'[a-z0-9]+(?:[-+][a-z0-9]+)*|[\u3400-\u9fff]+', normalized
    )
    tokens = set()
    for token in raw_tokens:
        if re.fullmatch(r'[\u3400-\u9fff]+', token):
            if len(token) == 1:
                tokens.add(token)
            else:
                tokens.update(token[index:index + 2] for index in range(len(token) - 1))
        elif not token.isdigit() and len(token) > 1 and token not in _SIMILARITY_STOP_WORDS:
            tokens.add(token)
    return tokens


def _jaccard(left, right):
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def _paper_similarity(left, right):
    left_title = _text_tokens(_value(left, 'title', ''))
    right_title = _text_tokens(_value(right, 'title', ''))
    left_text = left_title | _text_tokens(_value(left, 'abstract', ''))
    right_text = right_title | _text_tokens(_value(right, 'abstract', ''))
    return max(_jaccard(left_title, right_title), _jaccard(left_text, right_text))


def _cross_batch_candidates(indexed, batches):
    batch_by_ref = {
        item['ref']: batch_number
        for batch_number, batch in enumerate(batches)
        for item in batch
    }
    refs = sorted(indexed)
    candidates = []
    for index, left_ref in enumerate(refs):
        for right_ref in refs[index + 1:]:
            if batch_by_ref[left_ref] == batch_by_ref[right_ref]:
                continue
            left = indexed[left_ref][0]
            right = indexed[right_ref][0]
            citation = _citation_linked(left, right)
            similarity = _paper_similarity(left, right)
            similar = similarity >= MIN_PAIR_SIMILARITY
            if not citation and not similar:
                continue
            signals = []
            if citation:
                signals.append('citation')
            if similar:
                signals.append('title_abstract_similarity')
            candidates.append((
                0 if citation else 1,
                -similarity,
                left_ref,
                right_ref,
                signals,
                similarity,
            ))
    candidates.sort()
    return [
        {
            's': left_ref,
            't': right_ref,
            'discovery': signals,
            'similarity': round(similarity, 6),
        }
        for _, _, left_ref, right_ref, signals, similarity in candidates[:MAX_CROSS_BATCH_PAIRS]
    ]


def _parse_relation(item, available):
    if not isinstance(item, dict):
        return None
    s = _item_ref(item, 's')
    t = _item_ref(item, 't')
    evidence_ref = _item_ref(item, 'evidence_ref')
    basis_ref = _item_ref(item, 'basis_ref')
    relation_type = item.get('type')
    reason = _text(item.get('reason'))
    confidence = _confidence(item.get('confidence'))
    quote = item.get('quote')
    basis_quote = item.get('basis_quote')
    if (
        s not in available or t not in available or s == t
        or evidence_ref not in available or basis_ref not in available
        or {s, t} != {evidence_ref, basis_ref}
        or relation_type not in RELATION_LABELS or not reason or not confidence
        or not verbatim_quote(available[evidence_ref][1], quote)
        or not verbatim_quote(available[basis_ref][1], basis_quote)
    ):
        return None
    return SemanticRelation(
        s=s,
        t=t,
        type=relation_type,
        reason=reason,
        evidence_ref=evidence_ref,
        quote=quote,
        basis_ref=basis_ref,
        basis_quote=basis_quote,
        confidence=confidence,
    )


class AnalysisService:
    """Run small-batch model calls and drop every unsupported model assertion."""

    def __init__(self, model, batch_size=4):
        if type(batch_size) is not int or not 1 <= batch_size <= 10:
            raise ValueError('batch_size must be an integer between 1 and 10')
        self.model = model
        self.batch_size = batch_size

    def _complete(self, system_prompt, batch):
        return self.model.complete_json(system_prompt, {'papers': batch})

    def _structured(self, system_prompt, payload, *keys):
        # Thinking-disabled responses occasionally omit a top-level list; retry once
        # before degrading to an honestly empty result rather than failing the stage.
        for _ in range(2):
            response = self.model.complete_json(system_prompt, payload)
            if isinstance(response, dict) and all(
                isinstance(response.get(key), list) for key in keys
            ):
                return {key: response[key] for key in keys}
        return {key: [] for key in keys}

    def classify(self, papers):
        """Return evidence-bound topics and open acquisition-family → technique methods."""

        indexed = _abstract_index(papers)
        output = {'clusters': [], 'methods': []}
        family_examples = json.dumps(GENERIC_METHOD_FAMILIES, ensure_ascii=False)
        prompt = (
            'Classify only the supplied abstracts. Return JSON with clusters and methods lists. '
            'Every cluster needs ref, name, quote, confidence; every method needs ref, key, '
            'family, technique, quote, confidence. confidence is high, medium, or low. quote '
            'must be one continuous verbatim source sentence from that ref abstract. Methods '
            'are data-acquisition family -> concrete technique, never research topic names. '
            'Use a descriptive snake_case key; do not choose from a closed domain taxonomy. '
            'The family must say how data/evidence was acquired and the technique must name '
            'the concrete method or analysis action. A method may include a generic role '
            'or type field; when supplied it must be method. Research topics, comparison '
            'objects, and variable-processing steps are not methods and must be omitted. '
            'Examples of broad families (not an exclusive list): ' + family_examples
        )
        for batch in _batches(_paper_payload(indexed), self.batch_size):
            raw = self._structured(prompt, {'papers': batch}, 'clusters', 'methods')
            raw_clusters = raw['clusters']
            raw_methods = raw['methods']
            available = _batch_index(indexed, batch)
            topic_names = {
                _label_key(name)
                for name in (
                    _text(item.get('name'))
                    for item in raw_clusters
                    if isinstance(item, dict)
                )
                if name
            }

            for item in raw_clusters:
                if not isinstance(item, dict):
                    continue
                ref = _item_ref(item)
                name = _text(item.get('name'))
                confidence = _confidence(item.get('confidence'))
                quote = item.get('quote')
                if (
                    ref not in available or not name or not confidence
                    or not verbatim_quote(available[ref][1], quote)
                ):
                    continue
                output['clusters'].append({
                    'ref': ref,
                    'name': name,
                    'quote': quote,
                    'confidence': confidence,
                })

            for item in raw_methods:
                if not isinstance(item, dict):
                    continue
                ref = _item_ref(item)
                key = _text(item.get('key'))
                family = _text(item.get('family'))
                technique = _text(item.get('technique'))
                confidence = _confidence(item.get('confidence'))
                quote = item.get('quote')
                if (
                    ref not in available or not confidence
                    or not _valid_method_role(item)
                    or not _valid_method_labels(key, family, technique, topic_names)
                    or not verbatim_quote(available[ref][1], quote)
                ):
                    continue
                output['methods'].append({
                    'ref': ref,
                    'key': key,
                    'family': family,
                    'technique': technique,
                    'quote': quote,
                    'confidence': confidence,
                })
        return output

    def extract_factor_votes(self, papers):
        """Extract factor/outcome votes only when their exact abstract evidence exists."""

        indexed = _abstract_index(papers)
        votes = []
        prompt = (
            'Extract factor-to-outcome claims from only the supplied abstracts. Return JSON '
            'with a votes list. Each vote needs nonempty factor, outcome, polarity (pos or '
            'neg), ref, quote, and may include effect and confidence (high, medium, or low). '
            'quote must be a continuous verbatim source sentence from the referenced abstract. '
            'Never infer claims for papers without an abstract and never fabricate a ref or quote.'
        )
        for batch in _batches(_paper_payload(indexed), self.batch_size):
            raw = self._structured(prompt, {'papers': batch}, 'votes')
            available = _batch_index(indexed, batch)
            for item in raw['votes']:
                if not isinstance(item, dict):
                    continue
                ref = _item_ref(item)
                factor = _text(item.get('factor'))
                outcome = _text(item.get('outcome'))
                polarity = item.get('polarity')
                quote = item.get('quote')
                confidence = item.get('confidence')
                if (
                    ref not in available or not factor or not outcome
                    or polarity not in POLARITY_LABELS
                    or (confidence is not None and not _confidence(confidence))
                    or not verbatim_quote(available[ref][1], quote)
                ):
                    continue
                effect = item.get('effect', '')
                if effect is None:
                    effect = ''
                if not isinstance(effect, str):
                    continue
                votes.append(FactorVote(
                    factor=factor,
                    outcome=outcome,
                    polarity=polarity,
                    ref=ref,
                    quote=quote,
                    effect=effect,
                    confidence=confidence,
                ))
        return votes

    def extract_relations(self, papers):
        """Extract audited edges within batches and across bounded candidate pairs."""

        indexed = _abstract_index(papers)
        relations = []
        prompt = (
            'Compare only the supplied abstracts. Return JSON with a relations list. Each '
            'relation needs integer s, t, evidence_ref, basis_ref; type (support, improve, '
            'conflict, or difference); nonempty reason; quote; basis_quote; and confidence '
            '(high, medium, or low). quote and basis_quote must be continuous verbatim source '
            'sentences from evidence_ref and basis_ref respectively. Evidence refs must be the '
            'two edge endpoints. Missing abstracts, refs, labels, confidence, or exact evidence '
            'means omit the relation.'
        )
        batches = list(_batches(_paper_payload(indexed), self.batch_size))
        for batch in batches:
            raw = self._structured(prompt, {'papers': batch}, 'relations')
            available = _batch_index(indexed, batch)
            for item in raw['relations']:
                relation = _parse_relation(item, available)
                if relation is not None:
                    relations.append(relation)

        candidates = _cross_batch_candidates(indexed, batches)
        candidate_prompt = prompt + (
            ' This call contains one candidate pair discovered across the original batches; '
            'evaluate only that pair and do not invent additional pairs.'
        )
        for candidate in candidates:
            pair_refs = (candidate['s'], candidate['t'])
            pair_index = {ref: indexed[ref] for ref in pair_refs}
            pair = _paper_payload(pair_index)
            response = self._structured(
                candidate_prompt,
                {'papers': pair, 'candidate_pairs': [candidate]},
                'relations',
            )
            available = _batch_index(indexed, pair)
            for item in response['relations']:
                relation = _parse_relation(item, available)
                if relation is not None:
                    relations.append(relation)
        return relations
