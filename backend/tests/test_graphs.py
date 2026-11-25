import json
from copy import deepcopy
from pathlib import Path

import pytest

from app.graphs import CHART_ORDER, GraphService


FIXTURE_ROOT = Path(__file__).parent / 'fixtures' / 'graphs'
TRANSLATIONS = {
    'Cancer Immunotherapy and Biomarkers': '癌症免疫治疗与生物标志物',
    'Hepatocellular Carcinoma Treatment and Prognosis': '肝细胞癌治疗与预后',
    'Immune cells in cancer': '癌症中的免疫细胞',
    'Colorectal Cancer Treatments and Studies': '结直肠癌治疗与研究',
}


def load_fixture(name):
    return json.loads((FIXTURE_ROOT / name).read_text(encoding='utf-8'))


@pytest.fixture
def graph_inputs():
    return {
        'pools': {
            'all': load_fixture('papers_all.json'),
            'limited': load_fixture('papers.json'),
        },
        'stats': {
            'year': load_fixture('stats_year.json'),
            'topics': {
                'all': load_fixture('stats_topics_all.json'),
                'limited': load_fixture('stats_topics_limited.json'),
            },
            'series': [load_fixture('stats_series_{}.json'.format(index)) for index in range(1, 5)],
        },
        'analysis': load_fixture('analysis.json'),
    }


def build(inputs, **changes):
    options = {
        'topic': '肝癌免疫治疗耐药机制的最新进展',
        'condition': '模式 A；真实测试样本',
        'sources': 'OpenAlex 真实聚合与论文池',
        'translations': TRANSLATIONS,
        'generated_at': '2026-11-22',
    }
    options.update(changes)
    return GraphService().build(
        inputs['pools'], inputs['stats'], inputs['analysis'], **options
    )


def normalized(value):
    return ' '.join(value.split())


def test_real_fixture_builds_seven_frontend_modules_and_preserves_scope_switch(graph_inputs):
    data = build(graph_inputs)

    assert data['chart_order'] == list(CHART_ORDER)
    assert set(data['scopes']) == {'all', 'limited'}
    assert data['scope_switch']['available'] == ['all', 'limited']
    assert data['scope_switch']['fixed_all_charts'] == ['compare', 'trend']
    assert data['trend_status'] == 'ready'
    assert data['compare_status'] == 'ready'
    assert len(data['compare']) == 4
    assert data['trend_all'][-1] == {'year': 2026, 'count': 395}
    assert data['compare'][0]['name_zh'] == '癌症免疫治疗与生物标志物'

    for scope, expected_hits in (('all', 1428), ('limited', 1094)):
        scoped = data['scopes'][scope]
        assert scoped['total_hits'] == expected_hits
        assert scoped['pool_count'] == 50
        assert scoped['topics_status'] == 'ready'
        assert len(scoped['topics']) == 40
        assert scoped['network']['status'] == 'ready'
        assert scoped['knowledge']['status'] == 'ready'
        assert scoped['methods']['status'] == 'ready'
        assert scoped['relations']['status'] == 'ready'
    assert data['scopes']['limited']['from_year'] == 2023
    assert data['scopes']['limited']['label'] == '限定 2023–2026'


def test_network_edges_are_exactly_real_pool_references(graph_inputs):
    data = build(graph_inputs)

    for scope in ('all', 'limited'):
        papers = graph_inputs['pools'][scope]['papers']
        ids = {paper['id'] for paper in papers}
        expected = {
            (paper['id'], target)
            for paper in papers
            for target in paper.get('referenced_works', [])
            if target in ids and target != paper['id']
        }
        network = data['scopes'][scope]['network']
        drawn = {(edge['s'], edge['t']) for edge in network['edges']}

        assert drawn == expected
        assert len(drawn) == len(network['edges'])
        assert len({node['id'] for node in network['nodes']}) == 50
        assert all(
            edge['s'] in ids and edge['t'] in ids for edge in network['edges']
        )


def test_factor_edges_retain_verbatim_quotes_refs_and_unique_support(graph_inputs):
    data = build(graph_inputs)

    for scope in ('all', 'limited'):
        by_ref = {paper['ref_no']: paper for paper in graph_inputs['pools'][scope]['papers']}
        knowledge = data['scopes'][scope]['knowledge']
        assert knowledge['votes']
        for edge in knowledge['edges']:
            refs = {paper['ref'] for paper in edge['papers']}
            assert edge['support'] == len(refs)
            assert edge['support'] == len({vote['ref_no'] for vote in edge['evidence']})
            for vote in edge['evidence']:
                assert vote['ref'] == vote['ref_no']
                assert normalized(vote['quote']) in normalized(by_ref[vote['ref_no']]['abstract'])
                assert vote['factor'] and vote['outcome']
                assert vote['polarity'] in {'pos', 'neg'}


def test_semantic_edges_retain_both_verbatim_quotes_and_public_refs(graph_inputs):
    data = build(graph_inputs)

    for scope in ('all', 'limited'):
        by_ref = {paper['ref_no']: paper for paper in graph_inputs['pools'][scope]['papers']}
        edges = data['scopes'][scope]['relations']['edges']
        assert edges
        for edge in edges:
            assert {edge['s_ref'], edge['t_ref']} == {edge['evidence_ref'], edge['basis_ref']}
            assert normalized(edge['quote']) in normalized(by_ref[edge['evidence_ref']]['abstract'])
            assert normalized(edge['basis_quote']) in normalized(by_ref[edge['basis_ref']]['abstract'])
            assert [(item['ref_no'], item['quote']) for item in edge['evidence']] == [
                (edge['evidence_ref'], edge['quote']),
                (edge['basis_ref'], edge['basis_quote']),
            ]


def test_no_abstract_paper_remains_a_network_node_but_cannot_supply_evidence(graph_inputs):
    papers = graph_inputs['pools']['all']['papers']
    no_abstract = next(paper for paper in papers if not paper.get('abstract'))
    ref = no_abstract['ref_no']
    quoted = next(paper for paper in papers if paper.get('abstract'))
    analysis = graph_inputs['analysis']['all']
    analysis['factor_votes'].append({
        'factor': '无摘要因素', 'outcome': '伪造结局', 'polarity': 'pos',
        'ref': ref, 'quote': quoted['abstract'],
    })
    analysis['classify']['methods'].append({
        'ref': ref, 'key': 'no_abstract_method',
        'family': '实验与干预', 'technique': '伪造实验技术', 'quote': quoted['abstract'],
    })
    analysis['relations'].append({
        's': ref, 't': quoted['ref_no'], 'type': 'support', 'reason': '伪造关系',
        'evidence_ref': ref, 'quote': quoted['abstract'],
        'basis_ref': quoted['ref_no'], 'basis_quote': quoted['abstract'], 'confidence': 'high',
    })

    scoped = build(graph_inputs)['scopes']['all']
    node = next(node for node in scoped['network']['nodes'] if node['ref'] == ref)
    assert 'excerpt' not in node
    assert all(vote['ref_no'] != ref for vote in scoped['knowledge']['votes'])
    method_refs = {
        paper['ref']
        for family in scoped['methods']['children']
        for leaf in family['children']
        for paper in leaf['papers']
    }
    assert ref not in method_refs
    assert all(ref not in {edge['s_ref'], edge['t_ref']} for edge in scoped['relations']['edges'])


def test_empty_data_returns_explicit_empty_states_without_fake_graphs():
    inputs = {
        'pools': {
            'all': {'papers': []},
            'limited': {'papers': [], 'from_year': 2023},
        },
        'stats': {
            'year': {'groups': []},
            'topics': {'all': {'groups': []}, 'limited': {'groups': []}},
            'series': [],
        },
        'analysis': {
            scope: {'classify': {'clusters': [], 'methods': []}, 'factor_votes': [], 'relations': []}
            for scope in ('all', 'limited')
        },
    }

    data = build(inputs)

    assert data['trend_all'] == [] and data['trend_status'] == 'empty'
    assert data['compare'] == [] and data['compare_status'] == 'empty'
    for scoped in data['scopes'].values():
        assert scoped['topics'] == [] and scoped['topics_status'] == 'empty'
        assert scoped['network'] == {
            'nodes': [], 'edges': [], 'status': 'empty',
            'message': '该范围暂无论文数据', 'edge_status': 'empty',
            'edge_message': '池内暂无真实互引（不补造引用边）',
        }
        assert scoped['knowledge']['nodes'] == []
        assert scoped['knowledge']['edges'] == []
        assert scoped['knowledge']['votes'] == []
        assert scoped['knowledge']['status'] == 'empty'
        assert scoped['methods']['children'] == []
        assert scoped['methods']['status'] == 'empty'
        assert scoped['relations']['edges'] == []
        assert scoped['relations']['status'] == 'empty'


def test_duplicate_papers_and_analysis_records_do_not_change_output(graph_inputs):
    baseline = build(graph_inputs)
    for scope in ('all', 'limited'):
        inputs = graph_inputs
        inputs['pools'][scope]['papers'].append(deepcopy(inputs['pools'][scope]['papers'][0]))
        analysis = inputs['analysis'][scope]
        analysis['factor_votes'].append(deepcopy(analysis['factor_votes'][0]))
        analysis['classify']['methods'].append(deepcopy(analysis['classify']['methods'][0]))
        analysis['relations'].append(deepcopy(analysis['relations'][0]))

    assert build(graph_inputs) == baseline


def test_invalid_factor_evidence_is_rejected(graph_inputs):
    baseline = build(graph_inputs)['scopes']['all']['knowledge']
    votes = graph_inputs['analysis']['all']['factor_votes']
    valid = deepcopy(votes[0])
    no_abstract_ref = next(
        paper['ref_no'] for paper in graph_inputs['pools']['all']['papers'] if not paper.get('abstract')
    )
    votes.extend([
        {**valid, 'ref': 9999},
        {**valid, 'quote': 'not in abstract'},
        {**valid, 'polarity': 'positive'},
        {**valid, 'ref': no_abstract_ref},
        {**valid, 'factor': ''},
    ])

    assert build(graph_inputs)['scopes']['all']['knowledge'] == baseline


def test_wrong_semantic_evidence_refs_quotes_and_labels_are_rejected(graph_inputs):
    baseline = build(graph_inputs)['scopes']['all']['relations']
    relations = graph_inputs['analysis']['all']['relations']
    valid = deepcopy(relations[0])
    other_quote = valid['basis_quote']
    relations.extend([
        {**valid, 'quote': 'fabricated evidence'},
        {**valid, 'evidence_ref': valid['basis_ref'], 'quote': other_quote},
        {**valid, 'type': 'causes'},
        {**valid, 't': 9999, 'basis_ref': 9999},
        {**valid, 'confidence': 'certain'},
        {**valid, 'basis_quote': ''},
    ])

    assert build(graph_inputs)['scopes']['all']['relations'] == baseline


def test_method_tree_is_strictly_family_then_technique_and_never_topic_clusters(graph_inputs):
    data = build(graph_inputs)

    for scope in ('all', 'limited'):
        topic_names = {
            normalized(cluster['name']).casefold()
            for cluster in graph_inputs['analysis'][scope]['classify']['clusters']
        }
        by_ref = {paper['ref_no']: paper for paper in graph_inputs['pools'][scope]['papers']}
        tree = data['scopes'][scope]['methods']
        assert tree['children']
        for family in tree['children']:
            assert normalized(family['name']).casefold() not in topic_names
            assert family['children']
            family_refs = set()
            for leaf in family['children']:
                assert normalized(leaf['name']).casefold() not in topic_names
                assert normalized(leaf['name']).casefold() != normalized(family['name']).casefold()
                assert 'children' not in leaf
                refs = {paper['ref'] for paper in leaf['papers']}
                assert leaf['count'] == len(refs)
                family_refs.update(refs)
                for evidence in leaf['evidence']:
                    assert normalized(evidence['quote']) in normalized(by_ref[evidence['ref_no']]['abstract'])
            assert family['count'] == len(family_refs)


def test_invalid_method_levels_topic_names_and_quotes_are_rejected(graph_inputs):
    baseline = build(graph_inputs)['scopes']['all']['methods']
    analysis = graph_inputs['analysis']['all']['classify']
    valid = deepcopy(analysis['methods'][0])
    topic_name = analysis['clusters'][0]['name']
    analysis['methods'].extend([
        {**valid, 'key': 'same_labels', 'technique': valid['family']},
        {**valid, 'key': 'topic_family', 'family': topic_name},
        {**valid, 'key': 'topic_technique', 'technique': topic_name},
        {**valid, 'key': 'bad_quote', 'quote': 'fabricated method evidence'},
        {**valid, 'key': 'bad_confidence', 'confidence': 'certain'},
    ])

    assert build(graph_inputs)['scopes']['all']['methods'] == baseline


def test_missing_aggregates_never_fall_back_to_pool_counts(graph_inputs):
    graph_inputs['stats'] = {}

    data = build(graph_inputs)

    assert data['trend_all'] == [] and data['trend_status'] == 'empty'
    assert data['compare'] == [] and data['compare_status'] == 'empty'
    for scoped in data['scopes'].values():
        assert scoped['topics'] == []
        assert scoped['topics_status'] == 'empty'
        assert scoped['total_hits'] == 0
        assert scoped['pool_count'] == 50
        assert scoped['network']['nodes']


def test_optional_json_and_evidence_artifacts_are_serializable(graph_inputs, tmp_path):
    data = build(graph_inputs, output_dir=tmp_path)

    assert json.loads((tmp_path / 'dashboard_data.json').read_text(encoding='utf-8')) == data
    relations = json.loads((tmp_path / 'relations.json').read_text(encoding='utf-8'))
    assert set(relations) == {'all', 'limited'}
    assert relations['all']['edges'] == data['scopes']['all']['relations']['edges']
    graph_evidence = (tmp_path / 'graph_evidence.md').read_text(encoding='utf-8')
    relation_evidence = (tmp_path / 'relations_evidence.md').read_text(encoding='utf-8')
    first_vote = data['scopes']['all']['knowledge']['votes'][0]
    first_relation = data['scopes']['all']['relations']['edges'][0]
    assert normalized(first_vote['quote']) in graph_evidence
    assert normalized(first_relation['quote']) in relation_evidence
    assert normalized(first_relation['basis_quote']) in relation_evidence


def test_orchestration_task_dir_and_aggregate_json_paths(graph_inputs, tmp_path):
    stats = graph_inputs['stats']
    stats.pop('year')
    stats.pop('topics')
    stats['year_all'] = str(FIXTURE_ROOT / 'stats_year.json')
    stats['topics_all'] = str(FIXTURE_ROOT / 'stats_topics_all.json')
    stats['topics_limited'] = str(FIXTURE_ROOT / 'stats_topics_limited.json')

    data = GraphService().build(
        pools=graph_inputs['pools'],
        stats=stats,
        analysis=graph_inputs['analysis'],
        topic='真实编排接口测试',
        generated_at='2026-11-22',
        task_dir=tmp_path,
    )

    assert data['artifact_count'] == 4
    assert data['trend_status'] == 'ready'
    assert data['trend_all'][-1] == {'year': 2026, 'count': 395}
    assert data['scopes']['all']['topics_status'] == 'ready'
    assert data['scopes']['limited']['topics_status'] == 'ready'
    assert (tmp_path / 'dashboard_data.json').exists()
    assert (tmp_path / 'relations.json').exists()
    assert (tmp_path / 'graph_evidence.md').exists()
    assert (tmp_path / 'relations_evidence.md').exists()
