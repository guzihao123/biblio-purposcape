"""Evidence-audited JSON assembly for the seven literature graph modules.

The service deliberately does not infer relationships. Aggregate charts consume
OpenAlex aggregate payloads; pool charts consume only the supplied paper pools
and the evidence-bearing outputs from ``AnalysisService``.
"""

import json
import re
import unicodedata
from collections import Counter
from datetime import date
from pathlib import Path


RELATION_TYPES = {
    'support': {'name': '支持', 'color': '#61d6a6'},
    'improve': {'name': '改进', 'color': '#63b3ff'},
    'conflict': {'name': '冲突', 'color': '#ff7b7b'},
    'difference': {'name': '差异', 'color': '#b58cff'},
}
POLARITIES = {'pos', 'neg'}
CONFIDENCES = {'high', 'medium', 'low'}
CHART_ORDER = (
    'network', 'topics', 'compare', 'trend', 'knowledge', 'methods', 'relations'
)


def _value(record, key, default=None):
    if isinstance(record, dict):
        return record.get(key, default)
    return getattr(record, key, default)


def _text(value):
    return value.strip() if isinstance(value, str) and value.strip() else ''


def _ref(value):
    return value if type(value) is int and value > 0 else None


def _paper_ref(paper):
    return _ref(_value(paper, 'ref_no', _value(paper, 'ref')))


def _count(value):
    return value if type(value) is int and value >= 0 else None


def _label_key(value):
    normalized = unicodedata.normalize('NFKC', value or '')
    return ' '.join(normalized.split()).casefold()


def _verbatim(abstract, quote):
    if not isinstance(abstract, str) or not isinstance(quote, str):
        return False
    normalized_abstract = ' '.join(abstract.split())
    normalized_quote = ' '.join(quote.split())
    return bool(normalized_abstract and normalized_quote) and normalized_quote in normalized_abstract


def _identifiers(value):
    """Return canonical identifiers without ever matching titles or similarity."""

    if isinstance(value, dict):
        result = set()
        for key in ('id', 'doi', 'url'):
            result.update(_identifiers(value.get(key)))
        return result
    if isinstance(value, (list, tuple, set, frozenset)):
        result = set()
        for item in value:
            result.update(_identifiers(item))
        return result
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
    result = set()
    for key in ('id', 'doi', 'url'):
        result.update(_identifiers(_value(paper, key)))
    return result


def _deduplicate_papers(papers):
    """Keep the first stable public ref/id and never double-count duplicates."""

    unique = []
    seen_refs = set()
    seen_identifiers = set()
    for paper in papers if isinstance(papers, list) else []:
        if not isinstance(paper, dict) and not hasattr(paper, 'ref_no'):
            continue
        ref = _paper_ref(paper)
        identifiers = _paper_identifiers(paper)
        if ref is not None and ref in seen_refs:
            continue
        if identifiers and identifiers & seen_identifiers:
            continue
        if ref is None and not identifiers:
            continue
        unique.append(paper)
        if ref is not None:
            seen_refs.add(ref)
        seen_identifiers.update(identifiers)
    return unique


def _author_name(author):
    if isinstance(author, dict):
        return _text(author.get('name') or author.get('display_name'))
    return _text(author)


def _paper_label(paper):
    authors = _value(paper, 'authors', []) or []
    if isinstance(authors, str):
        authors = [authors]
    first = _author_name(authors[0]) if authors else ''
    year = _value(paper, 'year')
    suffix = ' {}'.format(year) if type(year) is int else ''
    if not first:
        return (_text(_value(paper, 'title')) or '未知作者') + suffix
    parts = first.split()
    if len(parts) >= 2:
        return '{}, {} {}{}'.format(parts[-1], parts[0][0].upper(), parts[1] and '' or '', suffix).replace('  ', ' ').strip()
    return first + suffix


def _paper_brief(paper):
    return {
        'ref': _paper_ref(paper),
        'ref_no': _paper_ref(paper),
        'label': _paper_label(paper),
        'title': _text(_value(paper, 'title')),
        'url': _text(_value(paper, 'url')) or _text(_value(paper, 'doi')),
    }


def _node_id(paper):
    for key in ('id', 'doi', 'url'):
        value = _text(_value(paper, key))
        if value:
            return value
    return 'ref:{}'.format(_paper_ref(paper))


def _network(papers):
    nodes = []
    node_by_ref = {}
    identifier_to_id = {}
    for paper in papers:
        node_id = _node_id(paper)
        abstract = _value(paper, 'abstract')
        node = {
            'id': node_id,
            'ref': _paper_ref(paper),
            'label': _paper_label(paper),
            'title': _text(_value(paper, 'title')),
            'authors': ', '.join(
                filter(None, (_author_name(author) for author in (_value(paper, 'authors', []) or [])))
            ) if not isinstance(_value(paper, 'authors'), str) else _text(_value(paper, 'authors')),
            'year': _value(paper, 'year') if type(_value(paper, 'year')) is int else None,
            'venue': _text(_value(paper, 'venue')),
            'cited': _count(_value(paper, 'cited_by_count')),
            'url': _text(_value(paper, 'url')) or _text(_value(paper, 'doi')),
        }
        if isinstance(abstract, str) and abstract.strip():
            node['excerpt'] = abstract[:200]
        nodes.append(node)
        if node['ref'] is not None:
            node_by_ref[node['ref']] = node_id
        for identifier in _paper_identifiers(paper):
            identifier_to_id[identifier] = node_id

    edges = []
    seen_edges = set()
    for paper in papers:
        source_id = _node_id(paper)
        references = _value(paper, 'referenced_works', []) or []
        for identifier in _identifiers(references):
            target_id = identifier_to_id.get(identifier)
            if target_id is None or target_id == source_id:
                continue
            pair = (source_id, target_id)
            if pair in seen_edges:
                continue
            seen_edges.add(pair)
            edge = {'s': source_id, 't': target_id}
            source_ref = _paper_ref(paper)
            target_paper = next(
                (candidate for candidate in papers if _node_id(candidate) == target_id), None
            )
            target_ref = _paper_ref(target_paper) if target_paper is not None else None
            if source_ref is not None:
                edge['s_ref'] = source_ref
            if target_ref is not None:
                edge['t_ref'] = target_ref
            edges.append(edge)
    return {
        'nodes': nodes,
        'edges': edges,
        'status': 'ready' if nodes else 'empty',
        'message': '' if nodes else '该范围暂无论文数据',
        'edge_status': 'ready' if edges else 'empty',
        'edge_message': '' if edges else '池内暂无真实互引（不补造引用边）',
    }, node_by_ref


def _payload(value):
    """Accept aggregate dictionaries or the JSON paths produced by Orchestrator."""

    if isinstance(value, (str, Path)):
        try:
            return json.loads(Path(value).read_text(encoding='utf-8'))
        except (OSError, ValueError, TypeError):
            return {}
    return value


def _groups(payload):
    payload = _payload(payload)
    if isinstance(payload, dict) and isinstance(payload.get('groups'), list):
        return payload['groups']
    return []


def _total_hits(payload):
    value = _value(_payload(payload), 'total_hits')
    return _count(value) or 0


def _topic_items(payload, translations, limit=None):
    items = []
    for position, group in enumerate(_groups(payload)):
        name = _text(_value(group, 'name'))
        count = _count(_value(group, 'count'))
        if not name or count is None:
            continue
        key = _text(_value(group, 'key'))
        items.append((position, {
            'name': name,
            'name_zh': _text(_value(group, 'name_zh'))
            or _text(translations.get(key)) or _text(translations.get(name)) or name,
            'count': count,
        }))
    items.sort(key=lambda item: (-item[1]['count'], item[0], item[1]['name']))
    if limit is not None:
        items = items[:limit]
    return [item for _, item in items]


def _year_items(payload):
    items = []
    for group in _groups(payload):
        raw_year = _value(group, 'name', _value(group, 'year'))
        count = _count(_value(group, 'count'))
        try:
            year = int(raw_year)
        except (TypeError, ValueError):
            continue
        if not 0 < year < 10000 or count is None:
            continue
        items.append({'year': year, 'count': count})
    items.sort(key=lambda item: item['year'])
    return items


def _topics_payload(stats, scope):
    topics = _value(stats, 'topics', {})
    if isinstance(topics, dict):
        if scope in topics:
            return topics[scope]
        if scope == 'all' and 'unlimited' in topics:
            return topics['unlimited']
    for key in ('stats_topics_{}'.format(scope), 'topics_{}'.format(scope)):
        payload = _value(stats, key)
        if payload is not None:
            return payload
    return {}


def _trend_payload(stats):
    for key in ('year', 'trend', 'stats_year', 'year_all', 'stats_year_all'):
        payload = _value(stats, key)
        if payload is not None:
            return payload
    return {}


def _series_payload(stats, group, index):
    container = _value(stats, 'series', _value(stats, 'topic_series', []))
    key = _text(_value(group, 'key'))
    name = _text(_value(group, 'name'))
    if isinstance(container, dict):
        return container.get(key) or container.get(name) or container.get(str(index + 1))
    if isinstance(container, list) and index < len(container):
        return container[index]
    return None


def _compare(stats, translations):
    topics_payload = _topics_payload(stats, 'all')
    groups = _groups(topics_payload)
    ranked = sorted(
        enumerate(groups),
        key=lambda item: (-(_count(_value(item[1], 'count')) or 0), item[0]),
    )[:4]
    compare = []
    for original_index, group in ranked:
        name = _text(_value(group, 'name'))
        if not name:
            continue
        payload = _series_payload(stats, group, original_index)
        series = _year_items(payload)
        if not series:
            continue
        key = _text(_value(group, 'key'))
        compare.append({
            'name': name,
            'name_zh': _text(_value(group, 'name_zh'))
            or _text(translations.get(key)) or _text(translations.get(name)) or name,
            'series': series,
        })
    return compare


def _valid_confidence(value):
    return value is None or value in CONFIDENCES


def _factor_votes(raw_votes, by_ref):
    votes = []
    seen = set()
    for raw in raw_votes if isinstance(raw_votes, list) else []:
        ref = _ref(_value(raw, 'ref', _value(raw, 'ref_no')))
        paper = by_ref.get(ref)
        factor = _text(_value(raw, 'factor'))
        outcome = _text(_value(raw, 'outcome'))
        polarity = _value(raw, 'polarity')
        quote = _value(raw, 'quote')
        effect = _value(raw, 'effect', '')
        confidence = _value(raw, 'confidence')
        if effect is None:
            effect = ''
        if (
            paper is None or not factor or not outcome or polarity not in POLARITIES
            or not isinstance(effect, str) or not _valid_confidence(confidence)
            or not _verbatim(_value(paper, 'abstract'), quote)
        ):
            continue
        identity = (ref, factor, outcome, polarity, effect, quote, confidence)
        if identity in seen:
            continue
        seen.add(identity)
        vote = {
            'factor': factor,
            'outcome': outcome,
            'polarity': polarity,
            'effect': effect,
            'ref': ref,
            'ref_no': ref,
            'quote': quote,
        }
        if confidence is not None:
            vote['confidence'] = confidence
        votes.append(vote)
    return votes


def _knowledge(raw_votes, papers, by_ref):
    votes = _factor_votes(raw_votes, by_ref)
    names = sorted(
        {vote['factor'] for vote in votes} | {vote['outcome'] for vote in votes},
        key=lambda name: (name.casefold(), name),
    )
    outgoing = {vote['factor'] for vote in votes}
    node_ids = {name: 'k{}'.format(index + 1) for index, name in enumerate(names)}
    nodes = [
        {
            'id': node_ids[name],
            'name': name,
            'type': 'factor' if name in outgoing else 'outcome',
            'papers': [],
        }
        for name in names
    ]
    node_by_name = {node['name']: node for node in nodes}
    grouped = {}
    pair_polarities = {}
    for vote in votes:
        grouped.setdefault((vote['factor'], vote['outcome'], vote['polarity']), []).append(vote)
        pair_polarities.setdefault((vote['factor'], vote['outcome']), set()).add(vote['polarity'])

    edges = []
    for key in sorted(grouped, key=lambda item: tuple(part.casefold() for part in item)):
        factor, outcome, polarity = key
        items = grouped[key]
        refs = sorted({vote['ref'] for vote in items})
        paper_list = [_paper_brief(by_ref[ref]) for ref in refs]
        effects = [vote['effect'] for vote in items if vote['effect']]
        effect = Counter(effects).most_common(1)[0][0] if effects else ''
        evidence = sorted(items, key=lambda vote: (vote['ref'], vote['quote']))
        edges.append({
            's': node_ids[factor],
            't': node_ids[outcome],
            'polarity': polarity,
            'effect': effect,
            'support': len(refs),
            'papers': paper_list,
            'evidence': evidence,
            'disputed': len(pair_polarities[(factor, outcome)]) > 1,
        })
        for name in (factor, outcome):
            node = node_by_name[name]
            existing = {paper['ref'] for paper in node['papers']}
            node['papers'].extend(paper for paper in paper_list if paper['ref'] not in existing)
            node['papers'].sort(key=lambda paper: paper['ref'])
    return {
        'nodes': nodes if edges else [],
        'edges': edges,
        'votes': votes if edges else [],
        'status': 'ready' if edges else 'empty',
        'message': '' if edges else '未凝练出可核验的影响关系（不硬造）',
    }


def _cluster_names(classification, scope_analysis):
    clusters = _value(classification, 'clusters', _value(scope_analysis, 'clusters', []))
    if not isinstance(clusters, list):
        return set()
    return {
        _label_key(_value(cluster, 'name'))
        for cluster in clusters if _text(_value(cluster, 'name'))
    }


def _flatten_methods(classification, scope_analysis):
    methods = _value(classification, 'methods', _value(scope_analysis, 'methods', []))
    flattened = []
    for entry in methods if isinstance(methods, list) else []:
        nested = _value(entry, 'methods')
        if isinstance(nested, list):
            ref = _value(entry, 'ref', _value(entry, 'ref_no'))
            parent_quote = _value(entry, 'quote')
            for method in nested:
                if isinstance(method, dict):
                    item = dict(method)
                    item.setdefault('ref', ref)
                    if parent_quote is not None:
                        item.setdefault('quote', parent_quote)
                    flattened.append(item)
        else:
            flattened.append(entry)
    return flattened


def _methods(classification, scope_analysis, topic, papers, by_ref):
    topic_names = _cluster_names(classification, scope_analysis)
    families = {}
    seen = set()
    for raw in _flatten_methods(classification, scope_analysis):
        ref = _ref(_value(raw, 'ref', _value(raw, 'ref_no')))
        paper = by_ref.get(ref)
        family = _text(_value(raw, 'family'))
        technique = _text(_value(raw, 'technique'))
        key = _text(_value(raw, 'key'))
        quote = _value(raw, 'quote')
        confidence = _value(raw, 'confidence')
        if (
            paper is None or not family or not technique
            or _label_key(family) == _label_key(technique)
            or _label_key(family) in topic_names or _label_key(technique) in topic_names
            or not _valid_confidence(confidence)
            or not _verbatim(_value(paper, 'abstract'), quote)
        ):
            continue
        identity = (ref, family, technique, key, quote)
        if identity in seen:
            continue
        seen.add(identity)
        evidence = {'ref': ref, 'ref_no': ref, 'quote': quote}
        if key:
            evidence['key'] = key
        if confidence is not None:
            evidence['confidence'] = confidence
        families.setdefault(family, {}).setdefault(technique, []).append(evidence)

    children = []
    for family in sorted(families, key=lambda name: (name.casefold(), name)):
        leaves = []
        family_refs = set()
        for technique in sorted(families[family], key=lambda name: (name.casefold(), name)):
            evidence = sorted(families[family][technique], key=lambda item: (item['ref'], item['quote']))
            refs = sorted({item['ref'] for item in evidence})
            family_refs.update(refs)
            leaves.append({
                'name': technique,
                'count': len(refs),
                'papers': [_paper_brief(by_ref[ref]) for ref in refs],
                'evidence': evidence,
            })
        children.append({
            'name': family,
            'count': len(family_refs),
            'papers': [_paper_brief(by_ref[ref]) for ref in sorted(family_refs)],
            'children': leaves,
        })
    return {
        'name': topic or '研究方法',
        'children': children,
        'status': 'ready' if children else 'empty',
        'message': '' if children else '暂无可核验的数据获取方法族与具体技术',
    }


def _relations(raw_relations, by_ref, node_by_ref):
    edges = []
    seen = set()
    for raw in raw_relations if isinstance(raw_relations, list) else []:
        source_ref = _ref(_value(raw, 's', _value(raw, 's_ref')))
        target_ref = _ref(_value(raw, 't', _value(raw, 't_ref')))
        evidence_ref = _ref(_value(raw, 'evidence_ref'))
        basis_ref = _ref(_value(raw, 'basis_ref'))
        relation_type = _value(raw, 'type')
        reason = _text(_value(raw, 'reason'))
        confidence = _value(raw, 'confidence')
        quote = _value(raw, 'quote')
        basis_quote = _value(raw, 'basis_quote')
        if (
            source_ref not in by_ref or target_ref not in by_ref or source_ref == target_ref
            or source_ref not in node_by_ref or target_ref not in node_by_ref
            or {source_ref, target_ref} != {evidence_ref, basis_ref}
            or relation_type not in RELATION_TYPES or not reason or confidence not in CONFIDENCES
            or not _verbatim(_value(by_ref.get(evidence_ref), 'abstract'), quote)
            or not _verbatim(_value(by_ref.get(basis_ref), 'abstract'), basis_quote)
        ):
            continue
        identity = (
            source_ref, target_ref, relation_type, evidence_ref, quote,
            basis_ref, basis_quote, confidence, reason,
        )
        if identity in seen:
            continue
        seen.add(identity)
        edges.append({
            's': node_by_ref[source_ref],
            't': node_by_ref[target_ref],
            's_ref': source_ref,
            't_ref': target_ref,
            'type': relation_type,
            'reason': reason,
            'evidence_ref': evidence_ref,
            'quote': quote,
            'basis_ref': basis_ref,
            'basis_quote': basis_quote,
            'confidence': confidence,
            'evidence': [
                {'role': 'evidence', 'ref': evidence_ref, 'ref_no': evidence_ref, 'quote': quote},
                {'role': 'basis', 'ref': basis_ref, 'ref_no': basis_ref, 'quote': basis_quote},
            ],
        })
    return {
        'types': {key: dict(value) for key, value in RELATION_TYPES.items()},
        'edges': edges,
        'status': 'ready' if edges else 'empty',
        'message': '' if edges else '暂无可核验的论文关系',
    }


def _scope_analysis(analysis, scope):
    if not isinstance(analysis, dict):
        return {}
    scoped = analysis.get(scope)
    if scoped is None and scope == 'all':
        scoped = analysis.get('unlimited')
    return scoped if isinstance(scoped, dict) else analysis


def _pool_for_scope(pools, scope):
    if not isinstance(pools, dict):
        return {}
    if 'papers' in pools and scope == 'all':
        return pools
    if scope in pools:
        return pools[scope]
    if scope == 'all':
        return pools.get('unlimited', {})
    return {}


def _evidence_documents(data):
    graph_lines = ['# 图谱证据台账', '']
    relation_lines = ['# 语义关系证据台账', '']
    for scope, scope_data in data['scopes'].items():
        graph_lines.extend(['## {}'.format(scope), ''])
        votes = scope_data['knowledge']['votes']
        if not votes:
            graph_lines.extend(['无可核验的因素→结局关系。', ''])
        for vote in votes:
            graph_lines.extend([
                '- {factor} → {outcome} | {polarity} | [{ref}]'.format(**vote),
                '  > {}'.format(' '.join(vote['quote'].split())),
            ])
        graph_lines.append('')
        relation_lines.extend(['## {}'.format(scope), ''])
        edges = scope_data['relations']['edges']
        if not edges:
            relation_lines.extend(['暂无可核验的论文关系。', ''])
        for edge in edges:
            relation_lines.extend([
                '- [{s_ref}] → [{t_ref}] | {type} | {confidence} | {reason}'.format(**edge),
                '  > [{}] {}'.format(edge['evidence_ref'], ' '.join(edge['quote'].split())),
                '  > [{}] {}'.format(edge['basis_ref'], ' '.join(edge['basis_quote'].split())),
            ])
        relation_lines.append('')
    return '\n'.join(graph_lines), '\n'.join(relation_lines)


def _write_json(path, payload):
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temporary.replace(path)


class GraphService:
    """Build frontend-ready data without model calls, retrieval, or invented edges."""

    def build(
        self,
        pools,
        stats,
        analysis,
        topic='',
        condition='',
        sources='',
        translations=None,
        generated_at=None,
        output_dir=None,
        task_dir=None,
    ):
        """Assemble seven modules and optionally persist JSON/evidence ledgers.

        ``pools`` accepts ``{'all': papers_all, 'limited': papers}`` (also
        ``unlimited`` as an alias). ``stats`` accepts aggregate dictionaries or
        JSON paths. ``analysis`` contains per-scope or shared ``classify`` /
        ``clusters``, ``methods``, ``factor_votes`` / ``votes`` and ``relations``
        outputs from ``AnalysisService``. ``task_dir`` is the orchestration alias
        for ``output_dir``.
        """

        if task_dir is not None:
            if output_dir is not None and Path(output_dir) != Path(task_dir):
                raise ValueError('output_dir and task_dir must refer to the same directory')
            output_dir = task_dir
        translations = translations if isinstance(translations, dict) else {}
        generated_at = _text(generated_at) or date.today().isoformat()
        if not topic and isinstance(pools, dict):
            topic = _text(pools.get('topic'))
            if not topic:
                topic = _text(_value(_pool_for_scope(pools, 'all'), 'topic'))

        scopes = {}
        scope_names = ['all']
        if isinstance(pools, dict) and ('limited' in pools or 'all' not in pools and 'unlimited' not in pools and 'papers' not in pools):
            if 'limited' in pools:
                scope_names.append('limited')
        for scope in scope_names:
            pool = _pool_for_scope(pools, scope)
            papers = _deduplicate_papers(_value(pool, 'papers', []))
            by_ref = {_paper_ref(paper): paper for paper in papers if _paper_ref(paper) is not None}
            scope_analysis = _scope_analysis(analysis, scope)
            classification = _value(scope_analysis, 'classify', _value(scope_analysis, 'classification', {}))
            network, node_by_ref = _network(papers)
            topics_payload = _payload(_topics_payload(stats, scope))
            topics = _topic_items(topics_payload, translations, limit=40)
            raw_votes = _value(scope_analysis, 'factor_votes', _value(scope_analysis, 'votes', []))
            knowledge = _knowledge(raw_votes, papers, by_ref)
            methods = _methods(classification, scope_analysis, topic, papers, by_ref)
            relations = _relations(_value(scope_analysis, 'relations', []), by_ref, node_by_ref)
            from_year = _value(pool, 'from_year', _value(topics_payload, 'from_year'))
            scope_data = {
                'label': '不限年限',
                'total_hits': _total_hits(topics_payload) or _count(_value(pool, 'total_hits')) or 0,
                'pool_count': len(papers),
                'topics': topics,
                'topics_status': 'ready' if topics else 'empty',
                'topics_message': '' if topics else '缺少该范围全量主题聚合统计（不以论文池计数替代）',
                'network': network,
                'knowledge': knowledge,
                'methods': methods,
                'relations': relations,
            }
            if scope == 'limited':
                current_year = int(generated_at[:4]) if re.match(r'^\d{4}', generated_at) else date.today().year
                scope_data['from_year'] = from_year if type(from_year) is int else None
                scope_data['label'] = (
                    '限定 {}–{}'.format(from_year, current_year)
                    if type(from_year) is int else '限定年限'
                )
            scopes[scope] = scope_data

        trend = _year_items(_trend_payload(stats))
        compare = _compare(stats, translations)
        data = {
            'topic': topic,
            'generated_at': generated_at,
            'condition': condition,
            'sources': sources,
            'chart_order': list(CHART_ORDER),
            'scope_switch': {
                'available': list(scopes),
                'scoped_charts': ['network', 'topics', 'knowledge', 'methods', 'relations'],
                'fixed_all_charts': ['compare', 'trend'],
            },
            'trend_all': trend,
            'trend_status': 'ready' if trend else 'empty',
            'trend_message': '' if trend else '缺少全量年度聚合统计（不以论文池计数替代）',
            'compare': compare,
            'compare_status': 'ready' if compare else 'empty',
            'compare_message': '' if compare else '缺少主题年度序列聚合统计',
            'scopes': scopes,
            'artifact_count': 0,
        }

        if output_dir is not None:
            output = Path(output_dir)
            output.mkdir(parents=True, exist_ok=True)
            graph_evidence, relations_evidence = _evidence_documents(data)
            data['artifact_count'] = 4
            _write_json(output / 'dashboard_data.json', data)
            _write_json(
                output / 'relations.json',
                {scope: scope_data['relations'] for scope, scope_data in scopes.items()},
            )
            (output / 'graph_evidence.md').write_text(graph_evidence, encoding='utf-8')
            (output / 'relations_evidence.md').write_text(relations_evidence, encoding='utf-8')
        return data
