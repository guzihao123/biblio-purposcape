import json
import os
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

import app.qwen as qwen_module
from app.analysis import AnalysisService, verbatim_quote
from app.qwen import ChatModel


SAMPLE_ROOT = Path(
    os.environ.get(
        'PURPOSE_LANDSCAPE_HCC_FIXTURES',
        '/Users/crisprcas_9/WorkBuddy/2026-11-06-20-49-06/'
        'landscape-hcc-immunotherapy-resistance-20261122',
    )
)
VALID_METHOD = {
    'key': 'cell_pathway',
    'family': '细胞与分子生物学实验',
    'technique': '分子互作与通路机制实验（Co-IP、ChIP、RNA-seq）',
}


def load_sample(name):
    return json.loads((SAMPLE_ROOT / name).read_text(encoding='utf-8'))


def sample_paper(index=0):
    return SimpleNamespace(**deepcopy(load_sample('papers.json')['papers'][index]))


class FakeModel:
    def __init__(self):
        self.responses = []
        self.calls = []

    def queue_json(self, payload):
        self.responses.append(deepcopy(payload))

    def complete_json(self, system_prompt, payload):
        self.calls.append((system_prompt, deepcopy(payload)))
        if not self.responses:
            raise AssertionError('No fake JSON response was queued')
        return self.responses.pop(0)


class FakeCompletions:
    def __init__(self, content):
        self.content = content
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=self.content))]
        )


class FakeOpenAIClient:
    def __init__(self, content='{"ok": true}'):
        self.chat = SimpleNamespace(completions=FakeCompletions(content))


@pytest.fixture
def fake_model():
    return FakeModel()


@pytest.fixture
def paper():
    return sample_paper()


def valid_method(ref, quote, **changes):
    method = {
        'ref': ref,
        **VALID_METHOD,
        'quote': quote,
        'confidence': 'high',
    }
    method.update(changes)
    return method


def test_invalid_model_quote_is_rejected(fake_model, paper):
    fake_model.queue_json({'votes': [
        {'factor': '乳酸', 'outcome': 'M2极化', 'polarity': 'pos', 'ref': 1, 'quote': paper.abstract},
        {'factor': '虚构因素', 'outcome': '耐药', 'polarity': 'pos', 'ref': 1, 'quote': 'not in abstract'}
    ]})
    votes = AnalysisService(fake_model).extract_factor_votes([paper])
    assert len(votes) == 1
    assert votes[0].quote in paper.abstract


def test_verbatim_quote_normalizes_whitespace_but_rejects_empty_evidence(paper):
    with_line_breaks = paper.abstract.replace(' ', '\n', 3)

    assert verbatim_quote(paper.abstract, with_line_breaks)
    assert not verbatim_quote(paper.abstract, 'not in abstract')
    assert not verbatim_quote(paper.abstract, '')
    assert not verbatim_quote(None, paper.abstract)
    assert not verbatim_quote('   ', paper.abstract)


def test_factor_votes_reject_missing_unknown_refs_and_invalid_labels(fake_model, paper):
    valid = {
        'factor': 'S1P',
        'outcome': '免疫治疗耐药',
        'polarity': 'pos',
        'ref': 1,
        'quote': paper.abstract,
    }
    missing_ref = {key: value for key, value in valid.items() if key != 'ref'}
    unknown_ref = {**valid, 'ref': 999}
    invalid_polarity = {**valid, 'polarity': 'positive'}
    missing_factor = {**valid, 'factor': ''}
    fake_model.queue_json({'votes': [missing_ref, unknown_ref, invalid_polarity, missing_factor]})

    assert AnalysisService(fake_model).extract_factor_votes([paper]) == []


def test_no_abstract_is_not_sent_or_persisted_as_a_factor_vote(fake_model, paper):
    no_abstract = sample_paper(1)
    no_abstract.abstract = None
    fake_model.queue_json({'votes': [
        {
            'factor': '真实因素', 'outcome': '耐药', 'polarity': 'pos',
            'ref': paper.ref_no, 'quote': paper.abstract,
        },
        {
            'factor': '无摘要因素', 'outcome': '耐药', 'polarity': 'pos',
            'ref': no_abstract.ref_no, 'quote': paper.abstract,
        },
    ]})

    votes = AnalysisService(fake_model).extract_factor_votes([paper, no_abstract])

    assert [vote.ref for vote in votes] == [paper.ref_no]
    sent_refs = [item['ref'] for item in fake_model.calls[0][1]['papers']]
    assert sent_refs == [paper.ref_no]


def test_classify_returns_topic_assignment_and_acquisition_family_method(fake_model, paper):
    fake_model.queue_json({
        'clusters': [{
            'ref': paper.ref_no,
            'name': '免疫微环境与细胞互作',
            'quote': paper.abstract,
            'confidence': 'high',
        }],
        'methods': [valid_method(paper.ref_no, paper.abstract)],
    })

    result = AnalysisService(fake_model).classify([paper])

    assert result['clusters'] == [{
        'ref': paper.ref_no,
        'name': '免疫微环境与细胞互作',
        'quote': paper.abstract,
        'confidence': 'high',
    }]
    assert result['methods'] == [{
        'ref': paper.ref_no,
        **VALID_METHOD,
        'quote': paper.abstract,
        'confidence': 'high',
    }]


def test_classify_retries_malformed_json_shape_before_giving_up(fake_model, paper):
    fake_model.queue_json({'unexpected': []})
    fake_model.queue_json({
        'clusters': [],
        'methods': [valid_method(paper.ref_no, paper.abstract)],
    })

    result = AnalysisService(fake_model).classify([paper])

    assert [method['key'] for method in result['methods']] == [VALID_METHOD['key']]
    assert len(fake_model.calls) == 2


def test_classify_accepts_domain_general_acquisition_families_and_techniques(fake_model):
    education_abstract = (
        'We administered a validated questionnaire to 1,200 students and used structural '
        'equation modeling to examine feedback, motivation, and achievement.'
    )
    materials_abstract = (
        'We combined density functional theory (DFT) calculations with active learning '
        'to screen alloy catalysts and validated candidate structures experimentally.'
    )
    education = SimpleNamespace(
        ref_no=101,
        title='School feedback and student achievement',
        abstract=education_abstract,
    )
    materials = SimpleNamespace(
        ref_no=102,
        title='Accelerated alloy catalyst discovery',
        abstract=materials_abstract,
    )
    questionnaire = {
        'ref': 101,
        'key': 'questionnaire_sem',
        'family': '问卷调查与量化数据',
        'technique': 'Questionnaire survey and structural equation modeling (SEM)',
        'quote': education_abstract,
        'confidence': 'high',
    }
    dft_active_learning = {
        'ref': 102,
        'key': 'dft_active_learning',
        'family': '计算建模与数据驱动研究',
        'technique': 'Density functional theory (DFT) and active learning',
        'quote': materials_abstract,
        'confidence': 'high',
    }
    topic_as_method = {
        'ref': 101,
        'key': 'education_outcomes',
        'family': '课后服务与学业成效',
        'technique': '课后服务与学业成效',
        'quote': education_abstract,
        'confidence': 'high',
    }
    fake_model.queue_json({
        'clusters': [],
        'methods': [questionnaire, dft_active_learning, topic_as_method],
    })

    result = AnalysisService(fake_model).classify([education, materials])

    assert result['methods'] == [questionnaire, dft_active_learning]
    assert all(
        method['quote'] in paper.abstract
        for method, paper in zip(result['methods'], [education, materials])
    )


def test_classify_accepts_open_domain_methods_and_rejects_non_method_roles(fake_model):
    abstract = (
        'We conducted qualitative fieldwork with paramedics and used grounded theory '
        'coding to develop an account of professional identity.'
    )
    paper = SimpleNamespace(
        ref_no=111,
        title='Paramedic professional identity',
        abstract=abstract,
    )
    topic_name = 'Paramedic professional identity'
    method = {
        'ref': 111,
        'key': 'fieldwork_grounded_theory',
        'family': 'Qualitative fieldwork',
        'technique': 'Grounded theory coding',
        'role': 'method',
        'quote': abstract,
        'confidence': 'high',
    }
    exact_topic = {
        **method,
        'key': 'topic_as_method',
        'family': topic_name,
    }
    non_methods = [
        {
            **method,
            'key': 'non_method_{}'.format(index),
            'role': role,
        }
        for index, role in enumerate((
            'research topic',
            'comparison object',
            'variable-processing step',
        ))
    ]
    fake_model.queue_json({
        'clusters': [{
            'ref': 111,
            'name': topic_name,
            'quote': abstract,
            'confidence': 'high',
        }],
        'methods': [method, exact_topic, *non_methods],
    })

    result = AnalysisService(fake_model).classify([paper])

    assert result['methods'] == [{
        'ref': 111,
        'key': 'fieldwork_grounded_theory',
        'family': 'Qualitative fieldwork',
        'technique': 'Grounded theory coding',
        'quote': abstract,
        'confidence': 'high',
    }]


def test_classify_rejects_invalid_methods_and_topic_names_as_method_branches(fake_model, paper):
    topic_name = '临床耐药与治疗策略'
    fake_model.queue_json({
        'clusters': [{
            'ref': paper.ref_no, 'name': topic_name,
            'quote': paper.abstract, 'confidence': 'high',
        }],
        'methods': [
            valid_method(
                paper.ref_no, paper.abstract, key='clinical_resistance',
                family=topic_name, technique=topic_name,
            ),
            valid_method(paper.ref_no, paper.abstract, family=topic_name),
            valid_method(paper.ref_no, paper.abstract, technique=topic_name),
            valid_method(paper.ref_no, paper.abstract, confidence='certain'),
            valid_method(
                paper.ref_no, paper.abstract,
                family='not an acquisition family', role='research topic',
            ),
        ],
    })

    result = AnalysisService(fake_model).classify([paper])

    assert len(result['clusters']) == 1
    assert result['methods'] == []


def test_classify_rejects_fabricated_cluster_and_method_quotes(fake_model, paper):
    fake_model.queue_json({
        'clusters': [{
            'ref': paper.ref_no, 'name': '代谢重编程与细胞死亡',
            'quote': 'fabricated cluster evidence', 'confidence': 'medium',
        }],
        'methods': [valid_method(paper.ref_no, 'fabricated method evidence')],
    })

    assert AnalysisService(fake_model).classify([paper]) == {'clusters': [], 'methods': []}


def test_classify_processes_real_abstracts_in_small_batches(fake_model):
    papers = [
        SimpleNamespace(**deepcopy(record))
        for record in load_sample('papers.json')['papers']
        if record.get('abstract')
    ][:5]
    for _ in range(3):
        fake_model.queue_json({'clusters': [], 'methods': []})

    result = AnalysisService(fake_model, batch_size=2).classify(papers)

    assert result == {'clusters': [], 'methods': []}
    assert [len(call[1]['papers']) for call in fake_model.calls] == [2, 2, 1]
    assert all(
        set(item) == {'ref', 'title', 'abstract'}
        for call in fake_model.calls
        for item in call[1]['papers']
    )


def test_relation_requires_two_real_verbatim_quotes_and_valid_label(fake_model):
    relation = deepcopy(load_sample('relations_input.json')['limited'][0])
    records = load_sample('papers.json')['papers']
    by_ref = {record['ref_no']: record for record in records}
    source = SimpleNamespace(**deepcopy(by_ref[relation['s']]))
    target = SimpleNamespace(**deepcopy(by_ref[relation['t']]))
    relation['quote'] = relation['quote'].replace(' ', '\n', 2)
    fake_model.queue_json({'relations': [relation]})

    edges = AnalysisService(fake_model).extract_relations([target, source])

    assert len(edges) == 1
    edge = edges[0]
    assert (edge.s, edge.t, edge.type) == (source.ref_no, target.ref_no, 'support')
    assert edge.evidence_ref == source.ref_no
    assert edge.basis_ref == target.ref_no
    assert edge.confidence == 'high'
    assert verbatim_quote(source.abstract, edge.quote)
    assert verbatim_quote(target.abstract, edge.basis_quote)


@pytest.mark.parametrize('candidate_signal', ['citation', 'similarity'])
def test_relation_discovers_candidates_across_original_batches(fake_model, candidate_signal):
    if candidate_signal == 'citation':
        source_title = 'Teacher feedback in primary schools'
        target_title = 'Stable alloy catalyst surfaces'
        source_abstract = 'We used interviews to study teacher feedback in primary schools.'
        target_abstract = 'Density functional theory calculations reveal stable catalyst surfaces.'
    else:
        source_title = 'Teacher feedback and student motivation'
        target_title = 'Teacher feedback and student motivation: a replication'
        source_abstract = (
            'We administered the same validated questionnaire to students and used structural '
            'equation modeling to examine teacher feedback, motivation, and achievement.'
        )
        target_abstract = source_abstract + ' The replication confirmed the observed association.'

    source = SimpleNamespace(
        ref_no=101,
        id='https://openalex.org/W101',
        doi=None,
        url='https://openalex.org/W101',
        title=source_title,
        abstract=source_abstract,
        referenced_works=(
            ['https://openalex.org/W202'] if candidate_signal == 'citation' else []
        ),
    )
    target = SimpleNamespace(
        ref_no=202,
        id='https://openalex.org/W202',
        doi=None,
        url='https://openalex.org/W202',
        title=target_title,
        abstract=target_abstract,
        referenced_works=[],
    )
    relation = {
        's': 101,
        't': 202,
        'type': 'support',
        'reason': 'The candidate studies provide convergent evidence.',
        'evidence_ref': 101,
        'quote': source_abstract,
        'basis_ref': 202,
        'basis_quote': target_abstract,
        'confidence': 'high',
    }
    fake_model.queue_json({'relations': []})
    fake_model.queue_json({'relations': []})
    fake_model.queue_json({'relations': [relation]})

    edges = AnalysisService(fake_model, batch_size=1).extract_relations([source, target])

    assert len(edges) == 1
    edge = edges[0]
    assert (edge.s, edge.t, edge.evidence_ref, edge.basis_ref) == (101, 202, 101, 202)
    assert verbatim_quote(source_abstract, edge.quote)
    assert verbatim_quote(target_abstract, edge.basis_quote)
    assert [
        [paper['ref'] for paper in call[1]['papers']]
        for call in fake_model.calls
    ] == [[101], [202], [101, 202]]


def test_relation_discovers_structured_citation_references_without_unhashable_errors(fake_model):
    source_abstract = 'Ethnographic observation identifies routines that support team learning.'
    target_abstract = 'A field experiment confirms that team routines improve learning.'
    source = SimpleNamespace(
        ref_no=101,
        id='https://openalex.org/W101',
        doi=None,
        url='https://openalex.org/W101',
        title='Ethnography of team learning routines',
        abstract=source_abstract,
        referenced_works=[
            'https://openalex.org/W999',
            {'id': 'https://openalex.org/W202'},
            {'doi': 'https://doi.org/10.5000/structured-reference'},
            [({'id': 'https://openalex.org/W998'},)],
            {'https://openalex.org/W997', ('10.5000/unrelated',)},
        ],
    )
    target = SimpleNamespace(
        ref_no=202,
        id='https://openalex.org/W202',
        doi='https://doi.org/10.5000/structured-reference',
        url='https://openalex.org/W202',
        title='Field experiment on team learning',
        abstract=target_abstract,
        referenced_works=[],
    )
    relation = {
        's': 101,
        't': 202,
        'type': 'support',
        'reason': 'The observation and experiment provide convergent evidence.',
        'evidence_ref': 101,
        'quote': source_abstract,
        'basis_ref': 202,
        'basis_quote': target_abstract,
        'confidence': 'high',
    }
    fake_model.queue_json({'relations': []})
    fake_model.queue_json({'relations': []})
    fake_model.queue_json({'relations': [relation]})

    edges = AnalysisService(fake_model, batch_size=1).extract_relations([source, target])

    assert len(edges) == 1
    assert (edges[0].s, edges[0].t) == (101, 202)
    assert 'citation' in fake_model.calls[-1][1]['candidate_pairs'][0]['discovery']


def test_relations_reject_bad_evidence_refs_labels_and_no_abstract_endpoints(fake_model):
    valid = deepcopy(load_sample('relations_input.json')['limited'][0])
    records = load_sample('papers.json')['papers']
    by_ref = {record['ref_no']: record for record in records}
    source = SimpleNamespace(**deepcopy(by_ref[valid['s']]))
    target = SimpleNamespace(**deepcopy(by_ref[valid['t']]))
    no_abstract = sample_paper(0)
    no_abstract.abstract = None

    fabricated = {**valid, 'quote': 'not in abstract'}
    missing_ref = {key: value for key, value in valid.items() if key != 'evidence_ref'}
    unknown_target = {**valid, 't': 999, 'basis_ref': 999}
    invalid_label = {**valid, 'type': 'causes'}
    missing_confidence = {key: value for key, value in valid.items() if key != 'confidence'}
    no_abstract_edge = {
        **valid,
        't': no_abstract.ref_no,
        'basis_ref': no_abstract.ref_no,
    }
    fake_model.queue_json({'relations': [
        valid, fabricated, missing_ref, unknown_target,
        invalid_label, missing_confidence, no_abstract_edge,
    ]})

    edges = AnalysisService(fake_model).extract_relations([source, target, no_abstract])

    assert len(edges) == 1
    assert edges[0].s == valid['s']


def test_chat_model_uses_qwen_environment_and_openai_json_mode(monkeypatch):
    client = FakeOpenAIClient()
    constructor = {}

    def fake_openai(**kwargs):
        constructor.update(kwargs)
        return client

    monkeypatch.setattr(qwen_module, 'OpenAI', fake_openai)
    monkeypatch.setenv('QWEN_API_KEY', 'test-only-key')
    monkeypatch.setenv('QWEN_BASE_URL', 'https://qwen.example.test/v1')
    monkeypatch.setenv('QWEN_MODEL', 'qwen-plus')

    model = ChatModel()
    result = model.complete_json('Return structured evidence.', {'papers': [{'ref': 1}]})

    assert result == {'ok': True}
    assert constructor == {
        'api_key': 'test-only-key',
        'base_url': 'https://qwen.example.test/v1',
    }
    request = client.chat.completions.calls[0]
    assert request['model'] == 'qwen-plus'
    assert request['response_format'] == {'type': 'json_object'}
    assert request['messages'][0] == {
        'role': 'system', 'content': 'Return structured evidence.',
    }
    assert json.loads(request['messages'][1]['content']) == {'papers': [{'ref': 1}]}


def test_chat_model_disables_thinking_for_structured_json_calls():
    client = FakeOpenAIClient()

    model = ChatModel(client=client)
    model.complete_json('Return JSON.', {'papers': []})

    request = client.chat.completions.calls[0]
    assert request.get('extra_body') == {'enable_thinking': False}


def test_chat_model_requires_environment_credentials(monkeypatch):
    monkeypatch.delenv('QWEN_API_KEY', raising=False)
    monkeypatch.delenv('QWEN_BASE_URL', raising=False)

    with pytest.raises(RuntimeError, match='QWEN_API_KEY'):
        ChatModel()

    monkeypatch.setenv('QWEN_API_KEY', 'test-only-key')
    with pytest.raises(RuntimeError, match='QWEN_BASE_URL'):
        ChatModel()


def test_chat_model_rejects_non_json_model_content():
    model = ChatModel(client=FakeOpenAIClient('not valid JSON'))

    with pytest.raises(ValueError, match='valid JSON'):
        model.complete_json('Return JSON.', {})
