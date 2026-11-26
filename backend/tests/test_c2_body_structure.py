"""C2 正文结构回归：模型返回缺章节/缺七维/缺表/超字数正文时，必须由系统确定性修复。

对应线上 C6 验收失败（verify_delivery.py --mode C2 的 ⑤字数 与 ⑧模式形态 FAIL）。
所有内容只来自构件数据与 papers.json 摘要，不得虚构。
"""
import re

from app.writing import (
    WritingService,
    _backfill_c2_row_evidence,
    _c2_body_shape_errors,
    _c2_word_count,
)

from test_writing import EVIDENCE, PAPERS, SECOND_EVIDENCE, make_task


C2_SECTIONS = (
    '研究主题与检索范围', '关键词和检索策略', '代表性文献清单',
    '文献分类框架', '完整综述文本', '未来研究方向',
)
C2_DIMS = ('理论基础', '研究对象', '研究问题', '技术方法', '数据与实验', '研究结论', '研究局限')
COMPARISON_HEADER = '| 文献 | 研究问题 | 数据 | 核心方法 | 主要发现 | 局限性 |'
GAP_HEADER = '| 研究方向 | 已有进展 | 现有不足 | 文献证据 | 可深入研究的问题 |'


def full_c2_component_data():
    return {
        'scope': {
            'topic': '城市内涝与地下车库韧性',
            'objects': '城市建成区、地下车库与排水系统',
            'time_range': '2021–2025',
            'disciplines': '水文学、地理信息、机器学习',
            'evidence_boundary': '检索池 20 篇，摘要深度，未覆盖全文数据库',
        },
        'keywords': [
            {'concept': 'urban flooding', 'cn': '城市内涝', 'en_synonyms': 'pluvial flooding',
             'boolean': 'urban AND flooding', 'use': '背景'},
            {'concept': 'resilience', 'cn': '韧性', 'en_synonyms': 'flood resilience',
             'boolean': 'flood AND resilience', 'use': '进展'},
            {'concept': 'machine learning', 'cn': '机器学习', 'en_synonyms': 'random forest',
             'boolean': 'machine AND learning', 'use': '方法'},
        ],
        'search_strategy': {
            'databases': 'OpenAlex',
            'queries': ['urban flooding risk assessment', 'urban flood resilience'],
            'tracing': '参考文献追溯 2 篇',
            'screening': '2021 年起、英文、摘要可读',
            'systematic_review': False,
            'prisma': False,
        },
        'classification': [
            '系统韧性理论支撑风险评估从工程抗灾转向综合韧性 [1]',
            '城市建成区与地下车库暴露 [2]',
            '损失校准与恢复过程两个问题主线 [1][2]',
            '校准模型与地区调查两类技术方法 [1][2]',
            '校准数据与三地区调查数据 [1][2]',
            '误差降低与恢复差异两个主要结论 [1][2]',
            '暴露约束与模型联动两个研究局限 [1][2]',
        ],
        'comparison': [
            {'literature': '[1]', 'research_question': '损失误差校准', 'data': '校准数据集（据摘要）',
             'method': '校准模型', 'findings': '校准模型降低了城市内涝损失估计误差 [1]', 'limitation': '暴露约束未确认',
             'evidence': [EVIDENCE]},
            {'literature': '[2]', 'research_question': '暴露与恢复', 'data': '三个地区（据摘要）',
             'method': '地区调查', 'findings': '调查描述了车库暴露与恢复差异 [2]', 'limitation': '模型联动未确认',
             'evidence': [SECOND_EVIDENCE]},
            {'literature': '[1]', 'research_question': '联合校准可行性', 'data': '摘要未说明',
             'method': '比较综合', 'findings': '两类证据提供联合校准线索（分析）', 'limitation': '仅摘要',
             'evidence': [EVIDENCE, SECOND_EVIDENCE]},
        ],
        'synthesis': [
            {'direction': '损失校准', 'progress': '校准模型降低误差 [1]', 'representative_methods': '校准模型',
             'scenarios': '城市尺度', 'limit': '暴露约束未确认'},
            {'direction': '暴露调查', 'progress': '调查描述恢复差异 [2]', 'representative_methods': '地区调查',
             'scenarios': '社区尺度', 'limit': '模型联动未确认'},
            {'direction': '联合校准', 'progress': '两类证据分别发展 [1][2]', 'representative_methods': '联合建模',
             'scenarios': '跨区验证', 'limit': '缺少统一评价口径'},
        ],
        'route_comparison': [
            {'route': '校准模型', 'problem': '损失误差', 'performance': '摘要未报告指标',
             'conditions': '城市尺度', 'limitation': '暴露约束未确认', 'complementarity': '可吸收调查数据'},
            {'route': '地区调查', 'problem': '暴露与恢复', 'performance': '摘要未报告指标',
             'conditions': '社区尺度', 'limitation': '模型联动未确认', 'complementarity': '可为模型提供约束'},
        ],
        'gaps': [
            {'direction': '联合评估', 'progress': '模型与调查分别发展 [1][2]', 'limitation': '缺少联合校准机制',
             'evidence_text': '[1][2]', 'future_question': '如何建立联合校准机制？',
             'evidence': [EVIDENCE, SECOND_EVIDENCE]},
            {'direction': '跨区验证', 'progress': '调查覆盖三个地区 [2]', 'limitation': '暴露口径不统一',
             'evidence_text': '[2]', 'future_question': '暴露口径差异如何影响迁移？',
             'evidence': [SECOND_EVIDENCE]},
            {'direction': '恢复情景', 'progress': '恢复过程有差异线索 [2]', 'limitation': '动态约束缺失',
             'evidence_text': '[2]', 'future_question': '恢复路径如何进入损失模型？',
             'evidence': [SECOND_EVIDENCE]},
        ],
        'future_directions': [
            {'direction': '联合校准机制', 'basis': '两类证据分别发展但缺少统一评价', 'question': '如何建立联合校准机制？'},
            {'direction': '跨区迁移验证', 'basis': '现有调查覆盖三个地区', 'question': '暴露口径差异如何影响迁移？'},
            {'direction': '恢复情景建模', 'basis': '恢复差异线索存在', 'question': '恢复路径如何进入损失模型？'},
        ],
    }


def broken_c2_body():
    """模拟 C6 线上失败产物：节名不符、无七维、无强制表、字数 1331。"""
    padding = '静态指标难以反映动态风险过程，参数校准依赖经验取值，迁移能力未经验证 [1]。' * 24
    return '\n'.join([
        '# 城市内涝风险评估与韧性提升研究',
        '',
        '## 1. 研究范围与检索策略',
        '',
        '本综述聚焦城市内涝风险评估，基于 OpenAlex 检索出核心文献，证据边界以摘要为主。',
        '',
        '## 2. 分类框架',
        '',
        '现有文献分为评估模型与调查两类 [1][2]。',
        '',
        '## 3. 综合分析',
        '',
        padding,
        '',
        '## 4. 主要技术路线比较',
        '',
        '| 技术路线 | 解决的问题 | 性能/适用条件 | 局限 | 互补或融合可能 |',
        '|---|---|---|---|---|',
        '| 校准模型 | 损失误差 | 摘要未报告指标 | 暴露约束未确认 | 可吸收调查数据 |',
        '',
        '## 5. 研究空白分析',
        '',
        '1. 动态风险感知不足 [1]。',
        '2. 标准化缺失 [2]。',
        '',
        '## 6. 未来研究方向',
        '',
        '实时动态评估与可解释建模 [1][2]。',
        '',
        '## 参考文献',
        '',
        '[1] Drainage resilience study',
        '[2] Underground garage survey',
    ])


def structured_c2_body(extra_sentence, repeat):
    """结构齐全、可重复扩字的合规正文骨架。"""
    lines = [
        '# 城市内涝与地下车库韧性综述',
        '',
        '## 研究主题与检索范围',
        '',
        '本综述聚焦城市内涝与地下车库韧性，时间范围 2021–2025，学科跨水文与机器学习，证据边界为摘要深度。',
        '',
        '## 关键词和检索策略',
        '',
        '| 概念 | 中文词 | 英文词/同义词 | 组合与布尔逻辑 | 实际用途 |',
        '|---|---|---|---|---|',
        '| urban flooding | 城市内涝 | pluvial flooding | urban AND flooding | 背景 |',
        '',
        '## 代表性文献清单',
        '',
        '- [1]：校准模型降低损失估计误差 [1]。',
        '- [2]：调查描述暴露与恢复差异 [2]。',
        '',
        '## 文献分类框架',
        '',
    ]
    for dim in C2_DIMS:
        lines.append(f'- {dim}：池内文献已形成可归纳线索 [1][2]。')
    lines.extend([
        '',
        '## 不同研究方向的综合分析',
        '',
        '- 损失校准：校准模型降低误差 [1]，但暴露约束未确认。',
        '- 暴露调查：调查描述恢复差异 [2]，但模型联动未确认。',
        '',
        '## 主要技术路线比较',
        '',
        '| 技术路线 | 解决的问题 | 性能/适用条件 | 局限 | 互补或融合可能 |',
        '|---|---|---|---|---|',
        '| 校准模型 | 损失误差 | 城市尺度 | 暴露约束未确认 | 可吸收调查数据 |',
        '',
        '## 文献比较表',
        '',
        COMPARISON_HEADER,
        '|---|---|---|---|---|---|',
        '| [1] | 损失误差校准 | 校准数据集（据摘要） | 校准模型 | 误差降低 [1] | 暴露约束未确认 |',
        '| [2] | 暴露与恢复 | 三个地区（据摘要） | 地区调查 | 恢复差异 [2] | 模型联动未确认 |',
        '',
        '## 现有研究不足',
        '',
        '现有研究不足：两类证据尚未联动，联合校准机制缺失 [1][2]。',
        '',
        '## 研究空白分析表',
        '',
        GAP_HEADER,
        '|---|---|---|---|---|',
        '| 联合评估 | 模型与调查分别发展 [1][2] | 缺少联合校准机制 | [1][2] | 如何建立联合校准机制？ |',
        '',
        '## 未来研究方向',
        '',
        '- 联合校准机制：如何建立联合校准机制？',
        '- 跨区迁移验证：暴露口径差异如何影响迁移？',
        '',
        '## 完整综述文本',
        '',
        '综合池内文献，校准模型降低损失估计误差 [1]，调查揭示了暴露与恢复差异 [2]。'
        '现有研究不足在于两类证据尚未联动，研究空白集中于联合校准机制 [1][2]。',
    ])
    if repeat:
        lines.extend(['', extra_sentence * repeat])
    lines.extend([
        '',
        '## 参考文献',
        '',
        '[1] Drainage resilience study',
        '[2] Underground garage survey',
    ])
    return '\n'.join(lines)


def assert_c2_structure_ok(body):
    errors = _c2_body_shape_errors(body)
    assert errors == [], f'C2 结构仍不合格: {errors}'
    assert _c2_word_count(body) <= 1200
    assert not re.search(r'^#{1,4}\s*.*(?:讨论|discussion).*$', body, flags=re.M | re.I)


def test_broken_model_body_is_rebuilt_to_match_c2_shape(tmp_path):
    class BrokenModel:
        def __init__(self):
            self.body_calls = 0

        def complete_json(self, system_prompt, payload):
            if payload['stage'] == 'components':
                return {'components': full_c2_component_data()}
            self.body_calls += 1
            return {'body': broken_c2_body(), 'evidence': [EVIDENCE, SECOND_EVIDENCE]}

    model = BrokenModel()
    task = make_task('C2', tmp_path, component_data=None, user_results='')
    output = WritingService(workspace_root=tmp_path, model=model).produce(task)

    # 修复前该 broken 正文会原样通过（C6 线上失败），修复后必须被确定性重建
    assert output.body != broken_c2_body()
    assert model.body_calls == 2
    assert any(event.kind == 'c2_body_rebuilt' for event in task.events)
    assert_c2_structure_ok(output.body)


def test_overlength_model_body_is_compressed_into_range(tmp_path):
    class OverlengthModel:
        def __init__(self):
            self.body_calls = 0

        def complete_json(self, system_prompt, payload):
            if payload['stage'] == 'components':
                return {'components': full_c2_component_data()}
            self.body_calls += 1
            # 结构齐全但远超 1200 字
            return {
                'body': structured_c2_body('方向已有进展与不足并存，机制解释与数据口径仍需检验 [1][2]。', 40),
                'evidence': [EVIDENCE, SECOND_EVIDENCE],
            }

    model = OverlengthModel()
    task = make_task('C2', tmp_path, component_data=None, user_results='')
    output = WritingService(workspace_root=tmp_path, model=model).produce(task)

    assert 800 <= _c2_word_count(output.body) <= 1200
    assert_c2_structure_ok(output.body)


def test_valid_model_body_passes_through_without_rebuild(tmp_path):
    class GoodModel:
        def complete_json(self, system_prompt, payload):
            if payload['stage'] == 'components':
                return {'components': full_c2_component_data()}
            base = structured_c2_body('', 0)
            repeat = 0
            while _c2_word_count(base) < 860 and repeat < 60:
                repeat += 1
                base = structured_c2_body(
                    '方向已有进展与不足并存，机制解释与数据口径仍需检验 [1][2]。', repeat)
            return {'body': base, 'evidence': [EVIDENCE, SECOND_EVIDENCE]}

    model = GoodModel()
    task = make_task('C2', tmp_path, component_data=None, user_results='')
    output = WritingService(workspace_root=tmp_path, model=model).produce(task)

    assert not any(event.kind == 'c2_body_rebuilt' for event in task.events)
    assert 800 <= _c2_word_count(output.body) <= 1200
    assert_c2_structure_ok(output.body)


def test_outline_headings_match_the_c2_template_sections():
    from app.writing import OUTLINE_HEADINGS

    expected = [
        '研究主题与检索范围', '关键词和检索策略', '代表性文献清单', '文献分类框架',
        '不同研究方向的综合分析', '主要技术路线比较', '文献比较表', '现有研究不足',
        '研究空白分析表', '未来研究方向', '完整综述文本', '衔接与重复检查',
    ]
    assert OUTLINE_HEADINGS['C2'] == expected


def test_c2_component_schema_requires_row_evidence():
    from app.writing import COMPONENT_SCHEMAS

    schema = COMPONENT_SCHEMAS['C2']
    assert '"comparison"' in schema and '"gaps"' in schema
    comparison = schema.split('"comparison"', 1)[1].split('"synthesis"', 1)[0]
    gaps = schema.split('"gaps"', 1)[1].split('"future_directions"', 1)[0]
    assert '"evidence":[EVIDENCE]' in comparison
    assert '"evidence":[EVIDENCE]' in gaps


def test_c2_rows_without_evidence_are_backfilled_from_abstracts():
    data = full_c2_component_data()
    for key in ('comparison', 'gaps'):
        for row in data[key]:
            row.pop('evidence', None)
    repaired, filled = _backfill_c2_row_evidence(data, PAPERS)
    assert filled == len(repaired['comparison']) + len(repaired['gaps'])
    for key in ('comparison', 'gaps'):
        for row in repaired[key]:
            assert row['evidence']
            for item in row['evidence']:
                for ref, quote in item['quotes'].items():
                    assert quote in PAPERS[int(ref) - 1]['abstract']


def test_c2_backfill_parses_multi_reference_brackets():
    data = full_c2_component_data()
    for row in data['comparison'] + data['gaps']:
        row.pop('evidence', None)
    data['comparison'][0]['literature'] = '[1, 2]'
    repaired, filled = _backfill_c2_row_evidence(data, PAPERS)
    assert filled >= 1
    refs = {
        ref for item in repaired['comparison'][0]['evidence'] for ref in item['refs']
    }
    assert refs == {1, 2}


def test_c2_backfill_matches_rows_without_explicit_reference_numbers():
    data = full_c2_component_data()
    for row in data['comparison'] + data['gaps']:
        row.pop('evidence', None)
    data['comparison'][0]['literature'] = '城市内涝风险评估模型'
    data['comparison'][0]['findings'] = '校准模型降低了城市内涝损失估计误差'
    data['gaps'][0]['direction'] = '联合评估'
    data['gaps'][0]['evidence_text'] = ''
    repaired, filled = _backfill_c2_row_evidence(data, PAPERS)
    assert filled >= 1
    first = repaired['comparison'][0]
    assert first['evidence']
    assert re.search(r'\[\d+\]', first['literature'])
    gap = repaired['gaps'][0]
    assert gap['evidence']
    assert re.search(r'\[\d+\]', gap['evidence_text'])


def test_c2_backfill_replaces_evidence_without_refs():
    data = full_c2_component_data()
    for row in data['comparison'] + data['gaps']:
        row['evidence'] = [{'claim': 'incomplete', 'refs': [], 'quotes': {}}]
    repaired, filled = _backfill_c2_row_evidence(data, PAPERS)
    assert filled >= 1
    for key in ('comparison', 'gaps'):
        for row in repaired[key]:
            assert any(item.get('refs') for item in row['evidence'])
