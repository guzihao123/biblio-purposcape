"""A/B/C 门控回流回归：构件或正文不达标时先返工，最多三轮，再走确定性重建。"""
import re
from copy import deepcopy

from app.writing import (
    WritingService,
    _a_body_shape_errors,
    _a_word_count,
    _b_body_shape_errors,
    _b_word_count,
    _c1_body_shape_errors,
    _c1_word_count,
    _d_body_shape_errors,
    _d_word_count,
)

from test_writing import (
    EVIDENCE,
    SECOND_EVIDENCE,
    component_data,
    make_task,
    valid_b_body,
)


def valid_a_body():
    intro = (
        '本领域围绕城市内涝与地下车库韧性形成损失评估与暴露调查两个分堆，'
        '池内证据分别来自校准模型与地区调查 [1][2]。'
    )
    cards = []
    for index, title in enumerate(('联合校准', '恢复情景比较', '跨区迁移验证'), 1):
        marker = f'第 {index} 推荐' if index < 3 else f'储备方向（第 {index} 推荐）'
        cards.append('\n'.join([
            f'### 方向卡·{title}｜{marker}',
            f'- 核心研究问题：{title}需要回答的关键变量如何进入现有证据链？',
            '- 数据可得性：池内摘要提供方法与数据线索 [1][2]，公开性未确认。',
            '- 研究价值：高',
            '- 可行性：中',
            '- 创新潜力：高',
            '- 实施难度：中',
            '- 主要风险：数据公开性未确认',
            '- 第 1 推荐理由：直接连接两类证据（分析）' if index == 1 else '',
        ]).strip())
    analysis = (
        '从证据边界看，摘要只支持方法与关联线索，不支持把不同论文的模型和结果视为已完成头对头比较；'
        '因此方向排序按证据衔接度、数据可得性与实施难度综合判断（分析）。'
    )
    return '\n\n'.join([
        '# 城市内涝与地下车库韧性',
        '## 领域格局与全景树（分堆）',
        intro * 8,
        '## 研究空白',
        '空白1：损失模型与车库暴露恢复数据尚未形成联合校准 [1][2]（数据型理由：缺少统一数据口径）。',
        '空白2：恢复过程尚未作为损失模型的动态约束 [1][2]（机制型理由：变量尚未进入校准流程）。',
        '空白3：跨区验证缺少统一暴露口径 [1][2]（方法型理由：口径差异影响模型迁移比较）。',
        '## 方向卡与排序',
        '\n\n'.join(cards),
        '## 趋势与结论',
        analysis * 6,
        f'综合来看，第 1 推荐方向优先连接现有两类证据（推荐理由：证据衔接度最高），主要风险是数据公开性未确认。',
    ])


def test_a_standard_short_body_is_reworked_until_rebuilt(tmp_path):
    class ShortBodyModel:
        def __init__(self):
            self.body_calls = 0

        def complete_json(self, system_prompt, payload):
            assert payload['stage'] == 'body'
            self.body_calls += 1
            return {'body': '# 短稿\n\n领域骨架与方向线索 [1]。', 'evidence': [EVIDENCE, SECOND_EVIDENCE]}

    model = ShortBodyModel()
    task = make_task('A', tmp_path)
    output = WritingService(workspace_root=tmp_path, model=model).produce(task)

    assert model.body_calls == 1
    assert _a_body_shape_errors(output.body) == []
    assert 1500 <= _a_word_count(output.body) <= 2500
    assert any(event.kind == 'body_rework' for event in task.events)
    assert any(event.kind == 'a_body_rebuilt' for event in task.events)


def test_a_components_get_three_rounds_before_failing(tmp_path):
    class LateValidComponents:
        def __init__(self):
            self.calls = 0

        def complete_json(self, system_prompt, payload):
            assert payload['stage'] == 'components'
            self.calls += 1
            data = deepcopy(component_data('A'))
            if self.calls < 3:
                data['directions'] = data['directions'][:2]
            return {'components': data}

    model = LateValidComponents()
    task = make_task('A', tmp_path, component_data=None)
    output = WritingService(workspace_root=tmp_path, model=model).produce_components(task)

    assert model.calls == 3
    assert '方向卡' in output.markdown
    assert any(event.kind == 'component_rework' for event in task.events)


def test_b_body_gets_three_rounds_before_rebuild(tmp_path):
    class LateValidBody:
        def __init__(self):
            self.body_calls = 0

        def complete_json(self, system_prompt, payload):
            if payload['stage'] == 'components':
                return {'components': component_data('B')}
            self.body_calls += 1
            if self.body_calls < 3:
                return {'body': '# 项目甲\n\n过短论述 [1]。', 'evidence': [EVIDENCE]}
            return {'body': valid_b_body(), 'evidence': [EVIDENCE]}

    model = LateValidBody()
    task = make_task('B', tmp_path, component_data=None)
    output = WritingService(workspace_root=tmp_path, model=model).produce(task)

    assert model.body_calls == 3
    assert _b_body_shape_errors(output.body) == []
    assert 2000 <= _b_word_count(output.body) <= 3000
    assert any(event.kind == 'body_rework' for event in task.events)


def test_c1_short_body_is_expanded_into_the_word_gate(tmp_path):
    class ShortC1Body:
        def complete_json(self, system_prompt, payload):
            if payload['stage'] == 'components':
                return {'components': component_data('C1')}
            return {'body': '# 引言\n\n这是一段过短的引言 [1]。', 'evidence': [EVIDENCE]}

    task = make_task('C1', tmp_path, component_data=None)
    output = WritingService(workspace_root=tmp_path, model=ShortC1Body()).produce(task)

    assert _c1_body_shape_errors(output.body) == []
    assert 800 <= _c1_word_count(output.body) <= 1200
    assert 'Research Gap 分析表' in output.body
    assert re.search(r'\[\d+\]', output.body.split('## 完整引言')[1])

def test_d_short_body_is_reworked_into_the_mode_gate(tmp_path):
    class ShortDModel:
        def __init__(self):
            self.body_calls = 0

        def complete_json(self, system_prompt, payload):
            assert payload['stage'] == 'body'
            self.body_calls += 1
            return {
                'body': '# 本次调研\n\n研究进展与不足需要进一步展开 [1]。',
                'evidence': [EVIDENCE, SECOND_EVIDENCE],
            }

    model = ShortDModel()
    task = make_task('D', tmp_path)
    output = WritingService(workspace_root=tmp_path, model=model).produce(task)

    assert model.body_calls == 1
    assert _d_body_shape_errors(output.body) == []
    assert 3000 <= _d_word_count(output.body) <= 6000
    assert any(event.kind == 'd_body_rebuilt' for event in task.events)
    assert any(event.kind == 'body_rework' for event in task.events)


def test_c1_component_quote_is_repaired_from_the_abstract(tmp_path):
    class InvalidComponentQuote:
        def complete_json(self, system_prompt, payload):
            assert payload['stage'] == 'components'
            data = deepcopy(component_data('C1'))
            data['paragraph_cards'][0]['evidence'][0]['quotes']['1'] = 'Not present in the abstract.'
            return {'components': data}

    task = make_task('C1', tmp_path, component_data=None)
    output = WritingService(workspace_root=tmp_path, model=InvalidComponentQuote()).produce_components(task)

    assert all('Not present in the abstract.' not in item.get('quote', '') for item in output.evidence)
    assert any('calibrated model' in item.get('quote', '') for item in output.evidence)
    assert '段落卡·' in output.markdown


def test_c1_body_quote_is_repaired_without_retry_failure(tmp_path):
    class InvalidBodyQuote:
        def __init__(self):
            self.body_calls = 0

        def complete_json(self, system_prompt, payload):
            if payload['stage'] == 'components':
                return {'components': component_data('C1')}
            self.body_calls += 1
            return {
                'body': '正文引用 [1]。',
                'evidence': [{
                    'claim': 'Invalid quote',
                    'refs': [1],
                    'quotes': {'1': 'Not present in the abstract.'},
                }],
            }

    model = InvalidBodyQuote()
    task = make_task('C1', tmp_path, component_data=None)
    output = WritingService(workspace_root=tmp_path, model=model).produce(task)

    assert model.body_calls == 1
    assert 'Not present in the abstract.' not in output.body
    assert any('calibrated model' in item.get('quote', '') for item in output.evidence)
