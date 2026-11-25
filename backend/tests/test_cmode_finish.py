from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from test_writing import EVIDENCE, PAPERS, SECOND_EVIDENCE, component_data, make_task, successful_body

from app.answer_validation import validate_answer_value
from app.orchestration import Orchestrator
from app.writing import (
    C1_SKIP_RULE,
    C2_SKIP_RULE,
    COMPONENT_SCHEMAS,
    OUTLINE_HEADINGS,
    STYLE_REFERENCE_FILE,
    WritingService,
    extract_user_material,
)


class CapturingModel:
    def __init__(self, body='正文引用 [1][2]。'):
        self.body = body
        self.calls = []

    def complete_json(self, system_prompt, payload):
        self.calls.append((system_prompt, payload))
        if payload['stage'] == 'body':
            return {
                'body': self.body,
                'evidence': [EVIDENCE, SECOND_EVIDENCE],
            }
        raise AssertionError('component generation should not be needed in this fixture')


def test_c_info_answer_accepts_three_routes_and_rejects_missing_material():
    for route in ('skip', 'upload', 'oral'):
        value = {'mode': 'C', 'c_route': 'C1', 'c_info_route': route, 'c_material': ''}
        if route != 'skip':
            value['c_material'] = '题目：联合校准\n方法：调查与建模'
        validate_answer_value('mode', value)

    with pytest.raises(HTTPException):
        validate_answer_value('mode', {'mode': 'C', 'c_info_route': 'upload'})
    with pytest.raises(HTTPException):
        validate_answer_value('mode', {'mode': 'C', 'c_info_route': 'elsewhere'})
    with pytest.raises(HTTPException):
        validate_answer_value('mode', {'mode': 'A', 'c_info_route': 'skip'})


def test_writing_task_maps_c_material_and_target_journal(tmp_path):
    service = Orchestrator(artifact_root=tmp_path)
    task = SimpleNamespace(id='task-c')
    answers = {
        'direction': {'direction': '城市内涝'},
        'terms': {'terms': ['urban flooding']},
        'mode': {
            'mode': 'C',
            'c_route': 'C1',
            'c_info_route': 'oral',
            'c_material': '研究问题：车库暴露约束\n方法：调查与校准',
            'target_journal': 'Journal of Flood Risk Management',
        },
    }

    writing_task = service._writing_task(task, answers, 'C1', [], {})

    assert writing_task.user_results == '研究问题：车库暴露约束\n方法：调查与校准'
    assert writing_task.c_info_route == 'oral'
    assert writing_task.target_journal == 'Journal of Flood Risk Management'


def test_extract_user_material_pulls_question_method_and_innovation():
    material = extract_user_material(
        '题目：暴露约束下的损失联合校准\n'
        '摘要：现有模型未纳入车库暴露。\n'
        '方法：调查与校准模型\n'
        '结果：误差下降\n'
        '创新：动态暴露约束'
    )

    assert material['题目'] == '暴露约束下的损失联合校准'
    assert material['研究问题'] == '暴露约束下的损失联合校准'
    assert material['本文方法'] == '调查与校准模型'
    assert material['预期创新'] == '动态暴露约束'

    unlabelled = extract_user_material('本文关注车库暴露约束下的损失联合校准。方法采用调查与模型联动。')
    assert unlabelled['研究问题'] == '本文关注车库暴露约束下的损失联合校准。'
    assert '调查与模型联动' in unlabelled['摘要']


def test_c1_skip_keeps_gap_real_and_only_placeholders_this_paper_parts(tmp_path):
    model = CapturingModel()
    task = make_task(
        'C1', tmp_path, user_results='', c_info_route='skip', target_journal='',
        component_data=component_data('C1'),
    )

    output = WritingService(workspace_root=tmp_path, model=model).produce(task)

    stage, payload = model.calls[0]
    assert stage  # keep the captured system prompt in the failure output
    assert payload['c_writing_rules'] == C1_SKIP_RULE
    assert '研究空白必须' in payload['c_writing_rules']
    assert '占位' in payload['c_writing_rules']
    assert payload['user_material'] == {}
    assert payload['c_info_route'] == 'skip'
    assert 'Research Gap 分析表' in output.components.markdown
    assert '联合校准不足' in output.components.markdown


def test_c1_upload_extracts_material_and_target_journal_card_is_explicitly_degraded(tmp_path):
    papers = [
        {**PAPERS[0], 'venue': 'Science Advances'},
        {**PAPERS[1], 'venue': 'Journal of Flood Risk Management'},
    ]
    model = CapturingModel('本文关注暴露约束下的联合校准 [1][2]，并比较不同调查口径。')
    task = make_task(
        'C1', tmp_path, papers=papers, component_data=component_data('C1'),
        c_info_route='upload',
        user_results='题目：暴露约束下的联合校准\n方法：调查与校准模型\n创新：动态暴露约束',
        target_journal='Science Advances',
    )

    output = WritingService(workspace_root=tmp_path, model=model).produce(task)

    stage, payload = model.calls[0]
    assert stage
    assert payload['c_info_route'] == 'upload'
    assert payload['user_material']['本文方法'] == '调查与校准模型'
    assert payload['target_journal'] == 'Science Advances'
    assert 'Science Advances' in payload['style_reference_note']
    card = (tmp_path / task.id / STYLE_REFERENCE_FILE).read_text(encoding='utf-8')
    assert '目标期刊：Science Advances' in card
    assert '降级原因' in card
    assert '不抄写任何单篇范文措辞' in card
    assert output.body_path.exists()


def test_c2_is_review_not_discussion_and_never_asks_for_this_paper_results():
    schema = COMPONENT_SCHEMAS['C2']

    assert '本文结果' not in schema
    assert '"results"' not in schema
    assert '不要求本文结果' in C2_SKIP_RULE
    assert '不得写成 Discussion' in C2_SKIP_RULE
    assert OUTLINE_HEADINGS['C2'][-1] == '完整综述'
    assert not any('讨论' in heading for heading in OUTLINE_HEADINGS['C2'])


def test_c2_components_render_scope_strategy_synthesis_routes_and_future(tmp_path):
    data = component_data('C2')
    data.update({
        'scope': {
            'topic': '地下车库内涝损失评估',
            'objects': '城市地下车库与周边排水系统',
            'time_range': '2015–2026',
            'disciplines': '灾害风险、交通与城市规划',
            'evidence_boundary': '检索池仅摘要，未覆盖全文数据库',
        },
        'keywords': [
            {'concept': 'urban flooding', 'cn': '城市内涝', 'en_synonyms': 'pluvial flooding', 'boolean': 'urban AND flooding', 'use': '背景'},
            {'concept': 'underground garage', 'cn': '地下车库', 'en_synonyms': 'parking garage', 'boolean': 'garage AND (loss OR resilience)', 'use': '对象'},
        ],
        'search_strategy': {
            'databases': 'OpenAlex、Crossref',
            'queries': ['urban flooding AND underground garage'],
            'tracing': '参考文献追溯 2 篇',
            'screening': '2015 年起、英文、摘要可读',
            'systematic_review': False,
            'prisma': False,
        },
        'synthesis': [
            {'direction': '损失校准', 'progress': '模型误差下降 [1]', 'representative_methods': '校准模型', 'scenarios': '城市尺度', 'limit': '暴露约束未确认'},
            {'direction': '暴露调查', 'progress': '调查描述恢复差异 [2]', 'representative_methods': '地区调查', 'scenarios': '社区尺度', 'limit': '模型联动未确认'},
        ],
        'route_comparison': [
            {'route': '校准模型', 'problem': '损失误差', 'performance': '摘要未报告指标', 'conditions': '城市尺度', 'limitation': '暴露约束未确认', 'complementarity': '可吸收调查数据'},
            {'route': '地区调查', 'problem': '暴露与恢复', 'performance': '摘要未报告指标', 'conditions': '社区尺度', 'limitation': '模型联动未确认', 'complementarity': '可为模型提供约束'},
        ],
        'future_directions': [
            {'direction': '联合校准', 'basis': '两类证据分别发展但缺少统一评价', 'question': '如何建立联合校准机制？'},
            {'direction': '跨区迁移', 'basis': '现有调查覆盖三个地区', 'question': '暴露口径差异如何影响迁移？'},
        ],
    })
    task = make_task('C2', tmp_path, component_data=data)

    output = WritingService(workspace_root=tmp_path).produce(
        task, body_writer=lambda context: successful_body('综述正文 [1][2]。', [EVIDENCE, SECOND_EVIDENCE]),
    )

    markdown = output.components.markdown
    for heading in (
        '## 研究主题与检索范围',
        '## 关键词和检索策略',
        '## 不同研究方向的综合分析',
        '## 主要技术路线比较',
        '## 文献比较表',
        '## 研究空白分析表',
        '## 未来研究方向',
    ):
        assert heading in markdown
    assert 'OpenAlex、Crossref' in markdown
    assert '参考文献追溯 2 篇' in markdown
    assert '校准模型' in markdown
    assert '跨区迁移' in markdown
    assert '本研究发现' not in markdown


def test_c2_legacy_component_data_still_renders_new_sections(tmp_path):
    task = make_task('C2', tmp_path, component_data=component_data('C2'))

    output = WritingService(workspace_root=tmp_path).produce(
        task, body_writer=lambda context: successful_body('综述正文 [1][2]。', [EVIDENCE, SECOND_EVIDENCE]),
    )

    markdown = output.components.markdown
    assert '## 研究主题与检索范围' in markdown
    assert '检索池 2 篇' in markdown
    assert '## 主要技术路线比较' in markdown
    assert '## 未来研究方向' in markdown
