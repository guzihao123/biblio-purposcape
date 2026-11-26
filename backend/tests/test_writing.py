from pathlib import Path

import pytest

from app.writing import (
    B_PROJECT_GENERATION_RULE,
    B_SYSTEM_GENERATED_PLACEHOLDER,
    WritingInputError,
    WritingService,
    WritingTask,
    _b_body_shape_errors,
    _b_word_count,
    _normalize_b_headings,
    _render_b,
)


PAPERS = [
    {
        'ref_no': 1,
        'title': 'Drainage resilience study',
        'abstract': 'The calibrated model reduced urban flood loss estimation error.',
        'evidence_level': 'B',
        'claim_eligible': True,
    },
    {
        'ref_no': 2,
        'title': 'Underground garage survey',
        'abstract': 'The survey describes garage exposure and recovery across three districts.',
        'evidence_level': 'A',
        'claim_eligible': True,
    },
    {
        'ref_no': 3,
        'title': 'Bibliographic only study',
        'abstract': '',
        'evidence_level': 'C',
        'claim_eligible': False,
    },
]

def valid_b_body(filler_repeats=80):
    filler = '本项目围绕联合校准方法开展研究，现有证据支持继续推进[1]。'
    return '\n'.join([
        '# 项目甲',
        '',
        '本项目拟建立联合校准方法，若不开展本项目，风险将持续累积 [1]。',
        '',
        '## 已有研究对本项目技术路线的支撑（强制构件二：逐项挂研究内容编号）',
        '',
        '- 研究内容（一）：资产 [1]。',
        '- 研究内容（二）：资产 [1]。',
        '- 研究内容（三）：资产 [1]。',
        '',
        '## 关键不足',
        '',
        '| 不足 | 科学问题 | 研究内容 |',
        '|---|---|---|',
        '| 证据不足 | 如何校准 | 研究内容（一） |',
        '',
        '## 六段论证链',
        '',
        '**研究需求**：需求 [1]。**已有进展**：进展 [1]。**现有不足**：不足 [1]。',
        '**科学问题**：问题 [1]。**项目切入点**：本项目切入 [1]。**预期贡献**：贡献 [1]。',
        '',
        '## 研究内容',
        '',
        filler * filler_repeats,
        '',
        '## 参考文献',
        '[1] X',
    ])


EVIDENCE = {
    'claim': 'The calibrated model improved loss estimation.',
    'refs': [1],
    'quotes': {'1': 'The calibrated model reduced urban flood loss estimation error.'},
}

SECOND_EVIDENCE = {
    'claim': 'The survey describes exposure and recovery.',
    'refs': [2],
    'quotes': {'2': 'The survey describes garage exposure and recovery across three districts.'},
}


def component_data(mode):
    if mode == 'E':
        return {
            'markdown': '## 用途落实\n\n按自定义用途组织的构件 [1]（据摘要）。',
            'evidence': [EVIDENCE],
        }
    if mode == 'A_DIALOGUE':
        categories = ['理论创新型选题', '方法创新型选题', '研究对象拓展型选题', '数据与实证创新型选题', '机制解释型选题', '前沿交叉型选题', '应用需求驱动型选题']
        groups = []
        for category_index, category in enumerate(categories, 1):
            slots = []
            for slot_index in (1, 2):
                slots.append({
                    'title': f'{category}方向 {slot_index}',
                    'core_question': f'问题 {category_index}-{slot_index}如何形成可验证机制？',
                    'data_availability': '池内研究提供数据线索 [1][2]，公开性未确认。',
                    'research_value': '高', 'feasibility': '中', 'innovation_potential': '高', 'implementation_difficulty': '中',
                    'rank': slot_index,
                    'opportunity': f'对应{category}机会（分析）',
                    'risk': '数据公开性未确认',
                    'evidence': [EVIDENCE, SECOND_EVIDENCE],
                })
            groups.append({'category': category, 'slots': slots})
        return {
            **component_data('A'),
            'topic_groups': groups,
            'overall_first': {
                'topic': '方法创新型选题方向 1',
                'reason': '直接连接损失校准与暴露证据（分析）',
                'risk': '公开数据可得性未确认',
                'evidence': [EVIDENCE, SECOND_EVIDENCE],
            },
        }
    if mode == 'A':
        return {
            'landscape': [
                {'direction': '损失评估', 'paper_refs': [1, 2], 'share': '2/2', 'venues': '池内统计'},
            ],
            'gaps': [
                {'gap': '损失模型与车库暴露恢复数据尚未形成联合校准', 'reason': '数据与方法衔接不足', 'evidence': [EVIDENCE, SECOND_EVIDENCE]},
                {'gap': '恢复过程尚未作为损失模型的动态约束', 'reason': '机制变量尚未进入现有校准流程', 'evidence': [EVIDENCE, SECOND_EVIDENCE]},
                {'gap': '跨区验证缺少统一暴露口径', 'reason': '数据口径影响模型迁移与比较', 'evidence': [EVIDENCE, SECOND_EVIDENCE]},
            ],
            'directions': [
                {
                    'title': '车库暴露约束下的损失校准',
                    'core_question': '暴露与恢复数据如何约束损失模型？',
                    'data_availability': '池内调查研究提供数据线索 [2]，公开性未确认。',
                    'research_value': '高', 'feasibility': '中', 'innovation_potential': '高', 'implementation_difficulty': '中',
                    'rank': 1,
                    'first_reason': '直接回应联合校准缺口（分析）',
                    'risk': '数据公开性未确认',
                    'evidence': [EVIDENCE, SECOND_EVIDENCE],
                },
                {
                    'title': '恢复过程的情景比较',
                    'core_question': '不同恢复路径如何改变损失评估？',
                    'data_availability': '现有摘要仅提供情景线索 [1][2]。',
                    'research_value': '中', 'feasibility': '中', 'innovation_potential': '中', 'implementation_difficulty': '高',
                    'rank': 2,
                    'first_reason': '', 'risk': '情景参数不足', 'evidence': [EVIDENCE, SECOND_EVIDENCE],
                },
                {
                    'title': '储备方向：跨区迁移验证',
                    'core_question': '模型跨区迁移时误差如何变化？',
                    'data_availability': '跨区数据可得性未确认。',
                    'research_value': '中', 'feasibility': '低', 'innovation_potential': '中', 'implementation_difficulty': '高',
                    'rank': 3,
                    'first_reason': '', 'risk': '外部验证数据不足', 'evidence': [EVIDENCE, SECOND_EVIDENCE],
                },
            ],
        }
    if mode == 'B':
        return {
            'demand': {'text': '若不开展本项目，车库损失评估仍缺少暴露与恢复联合校准。', 'evidence': [EVIDENCE, SECOND_EVIDENCE]},
            'assets': [
                {'name': '损失校准模型', 'research_content': '研究内容（1）', 'evidence': [EVIDENCE]},
                {'name': '暴露与恢复调查', 'research_content': '研究内容（2）', 'evidence': [SECOND_EVIDENCE]},
                {'name': '跨区比较框架', 'research_content': '研究内容（3）', 'evidence': [EVIDENCE, SECOND_EVIDENCE]},
            ],
            'mappings': [
                {'limitation': '模型校准缺少暴露约束', 'scientific_question': '暴露如何约束损失误差？', 'research_content': '研究内容（1）', 'evidence': [EVIDENCE, SECOND_EVIDENCE]},
            ],
            'chain': {
                '研究需求': {'text': '本项目需要联合校准。', 'evidence': [EVIDENCE]},
                '已有进展': {'text': '已有模型与调查可复用。', 'evidence': [SECOND_EVIDENCE]},
                '现有不足': {'text': '两类证据尚未联动。', 'evidence': [EVIDENCE, SECOND_EVIDENCE]},
                '关键科学问题': {'text': '本项目拟解释暴露约束机制。', 'evidence': [EVIDENCE]},
                '项目切入点': {'text': '本项目将建立联合校准流程。', 'evidence': [SECOND_EVIDENCE]},
                '预期贡献': {'text': '本项目将形成可核验的校准协议。', 'evidence': [EVIDENCE, SECOND_EVIDENCE]},
            },
            'innovations': [
                {'innovation': '暴露—恢复联合校准', 'difference': '区别于单独损失建模', 'evidence': [EVIDENCE, SECOND_EVIDENCE]},
            ],
        }
    if mode == 'C1':
        functions = ['背景重要性', '研究进展', '现有研究不足', '研究思路与方法', '研究贡献']
        return {
            'paragraph_cards': [
                {'function': function, 'claim': f'{function}围绕本文问题展开。', 'evidence': [EVIDENCE]}
                for function in functions
            ],
            'gaps': [
                {'gap': '联合校准不足', 'evidence': [EVIDENCE, SECOND_EVIDENCE], 'response': '本文将暴露数据纳入校准。'},
            ],
        }
    if mode == 'C2':
        return {
            'classification': ['数据驱动评估', '暴露与恢复调查'],
            'comparison': [
                {
                    'literature': '[1]', 'research_question': '损失误差', 'data': '摘要未说明',
                    'method': '校准模型', 'findings': '误差降低 [1]', 'limitation': '暴露约束未确认',
                    'evidence': [EVIDENCE],
                },
                {
                    'literature': '[2]', 'research_question': '暴露与恢复', 'data': '三个地区（据摘要）',
                    'method': '调查', 'findings': '描述恢复差异 [2]', 'limitation': '模型联动未确认',
                    'evidence': [SECOND_EVIDENCE],
                },
            ],
            'gaps': [
                {
                    'direction': '联合评估', 'progress': '模型与调查分别发展', 'limitation': '缺少联合校准',
                    'evidence_text': '[1][2]', 'future_question': '如何建立联合校准机制？',
                    'evidence': [EVIDENCE, SECOND_EVIDENCE],
                },
            ],
        }
    if mode == 'D':
        return {
            'progress': [
                {'direction': '损失评估', 'refs': [1], 'summary': '校准模型降低误差 [1]', 'evidence': [EVIDENCE]},
                {'direction': '暴露与恢复', 'refs': [2], 'summary': '调查描述暴露与恢复 [2]', 'evidence': [SECOND_EVIDENCE]},
                {'direction': '联合校准', 'refs': [1, 2], 'summary': '两类证据提供联合研究线索（分析）', 'evidence': [EVIDENCE, SECOND_EVIDENCE]},
            ],
            'method_comparison': [
                {'family': '计算建模与仿真', 'technique': '校准模型', 'data': '摘要未说明', 'strength': '误差评估', 'limitation': '暴露约束未确认', 'refs': [1], 'evidence': [EVIDENCE]},
                {'family': '问卷调查与观察性数据', 'technique': '地区调查', 'data': '三个地区（据摘要）', 'strength': '恢复情景', 'limitation': '模型联动未确认', 'refs': [2], 'evidence': [SECOND_EVIDENCE]},
                {'family': '文献与二手数据', 'technique': '比较综合', 'data': '池内摘要', 'strength': '跨方法对照', 'limitation': '仅摘要', 'refs': [1, 2], 'evidence': [EVIDENCE, SECOND_EVIDENCE]},
            ],
            'reading_cards': [
                {
                    'ref': 1, 'title': PAPERS[0]['title'], 'reason': '方法代表', 'research_question': '损失误差',
                    'data': '摘要未说明', 'method': '校准模型', 'findings': '误差降低 [1]',
                    'limitations': '细节未确认', 'team_relevance': '可借鉴校准流程', 'reading_depth': '仅摘要',
                    'evidence': [EVIDENCE],
                },
                {
                    'ref': 2, 'title': PAPERS[1]['title'], 'reason': '数据代表', 'research_question': '暴露与恢复',
                    'data': '三个地区（据摘要）', 'method': '调查', 'findings': '描述恢复差异 [2]',
                    'limitations': '模型联动未确认', 'team_relevance': '可借鉴调查设计', 'reading_depth': '仅摘要',
                    'evidence': [SECOND_EVIDENCE],
                },
                {
                    'ref': 1, 'title': PAPERS[0]['title'] + '：复核', 'reason': '交叉复核', 'research_question': '联合校准',
                    'data': '摘要未说明', 'method': '比较分析', 'findings': '提供联合线索（分析）',
                    'limitations': '仅摘要', 'team_relevance': '形成讨论问题', 'reading_depth': '仅摘要',
                    'evidence': [EVIDENCE, SECOND_EVIDENCE],
                },
            ],
            'ranking': [
                {'rank': 1, 'topic': '联合校准机制', 'reason': '直接连接两类证据（分析）', 'risk': '数据未确认'},
                {'rank': 2, 'topic': '恢复情景比较', 'reason': '利用现有调查线索（分析）', 'risk': '情景不足'},
                {'rank': 3, 'topic': '跨区迁移', 'reason': '检验模型泛化（分析）', 'risk': '外部数据不足'},
            ],
            'discussion_questions': ['联合校准需要哪些新增数据？', '团队能否复用现有调查？'],
        }
    raise AssertionError(mode)


def make_task(mode, tmp_path, **overrides):
    values = {
        'id': f'{mode}-task',
        'mode': mode,
        'direction': '城市内涝与地下车库韧性',
        'papers': PAPERS,
        'component_data': component_data(mode),
        'search_overview': {
            'databases': ['OpenAlex'],
            'queries': ['urban flooding'],
            'from_year': 2021,
            'pool_count': 2,
        },
        'project': {
            'name': '车库暴露约束下的损失联合校准',
            'goal': '建立暴露、恢复与损失联合校准方法',
            'funding': '未指定',
            'research_contents': ['研究内容（1）联合建模', '研究内容（2）调查校准', '研究内容（3）跨区验证'],
            'technical_route': '输入→联合建模→跨区验证→输出',
            'feasibility': '数据公开性未确认；工具可复用；团队与预实验基础未提供。',
            'expected_outcomes': '联合校准方法、验证协议与论文。',
        },
        'team_context': '未提供团队背景',
        'analysis': {'clusters': ['损失评估', '暴露调查']},
    }
    values.update(overrides)
    return WritingTask(**values)


def successful_body(text, evidence=None):
    return {'text': text, 'evidence': evidence if evidence is not None else [EVIDENCE]}


def test_components_outline_and_sample_precede_body(tmp_path):
    task = make_task('A', tmp_path)
    service = WritingService(workspace_root=tmp_path)

    def body_writer(context):
        assert (tmp_path / task.id / 'outline.md').exists()
        assert (tmp_path / task.id / 'sample.md').exists()
        return successful_body('领域格局与方向卡正文 [1]。')

    output = service.produce(task, body_writer=body_writer)

    assert [event.kind for event in task.events] == [
        'components_ready', 'outline_ready', 'sample_ready', 'body_ready',
    ]
    assert output.body_path.name == '综述初稿.md'
    ledger = (tmp_path / task.id / 'evidence_ledger.md').read_text(encoding='utf-8')
    assert '| 1 | The calibrated model reduced urban flood loss estimation error. | B |' in ledger
    assert '| [1] |' not in ledger
    assert '核心研究问题' in output.sample
    assert '数据可得性' in output.sample
    assert '第 1 推荐' in output.sample


def test_landscape_pool_refs_are_not_treated_as_evidence_citations(tmp_path):
    data = component_data('A')
    data['landscape'][0]['paper_refs'] = [3]
    service = WritingService(workspace_root=tmp_path)
    task = make_task('A', tmp_path, component_data=data)

    output = service.produce_components(task)

    assert '篇号 3' in output.markdown
    assert '[3]' not in output.markdown.split('空白证据表')[0]


def test_d_reading_card_structural_ref_does_not_require_evidence(tmp_path):
    data = component_data('D')
    data['reading_cards'][0]['ref'] = 3
    data['reading_cards'][0].pop('evidence', None)
    task = make_task('D', tmp_path, component_data=data)

    output = WritingService(workspace_root=tmp_path).produce_components(task)

    assert '精读页·[3]' in output.markdown
    assert 3 in output.structural_refs


def test_c_body_invalid_evidence_is_dropped_after_strict_retries(tmp_path):
    class InvalidEvidenceModel:
        def __init__(self):
            self.body_calls = 0

        def complete_json(self, system_prompt, payload):
            if payload['stage'] == 'components':
                return {'components': component_data('C1')}
            self.body_calls += 1
            return {
                'body': '正文引用不合法证据 [1]。',
                'evidence': [{
                    'claim': 'Unsupported',
                    'refs': [1],
                    'quotes': {'1': 'Not present in the abstract.'},
                }],
            }

    model = InvalidEvidenceModel()
    task = make_task('C1', tmp_path, component_data=None)
    output = WritingService(workspace_root=tmp_path, model=model).produce(task)

    assert model.body_calls == 2
    assert '[1]' not in output.body
    assert '证据修复' in output.body
    assert any(event.kind == 'evidence_repair' for event in task.events)


def test_unsupported_prose_citation_is_repaired_after_strict_retries(tmp_path):
    class InvalidCitationModel:
        def __init__(self):
            self.calls = 0

        def complete_json(self, system_prompt, payload):
            self.calls += 1
            data = component_data('A')
            data['directions'][0]['core_question'] = '无证据的正文引用 [3] 如何保留？'
            return {'components': data}

    model = InvalidCitationModel()
    task = make_task('A', tmp_path, component_data=None)
    output = WritingService(workspace_root=tmp_path, model=model).produce_components(task)

    assert model.calls == 2
    assert '[3]' not in output.markdown
    assert '引用修复：已移除 1 处无证据编号' in output.markdown
    assert any(
        event.kind == 'citation_repair' and event.payload.get('stage') == 'components'
        for event in task.events
    )
    assert all(item['ref'] != 3 for item in output.evidence)


def test_a_components_include_ranked_direction_cards_and_real_evidence(tmp_path):
    service = WritingService(workspace_root=tmp_path)
    output = service.produce_components(make_task('A', tmp_path))

    assert '空白证据表' in output.markdown
    assert '研究价值' in output.markdown
    assert '可行性' in output.markdown
    assert '创新潜力' in output.markdown
    assert '实施难度' in output.markdown
    assert '[1][2]' in output.markdown


def test_a_dialogue_has_seven_ordered_categories_with_two_slots_and_overall_first(tmp_path):
    service = WritingService(workspace_root=tmp_path)
    task = make_task('A_DIALOGUE', tmp_path)
    output = service.produce_components(task)

    categories = ['理论创新型选题', '方法创新型选题', '研究对象拓展型选题', '数据与实证创新型选题', '机制解释型选题', '前沿交叉型选题', '应用需求驱动型选题']
    positions = [output.markdown.index(category) for category in categories]
    assert positions == sorted(positions)
    assert output.markdown.count('选题 1') == 7
    assert output.markdown.count('选题 2') == 7
    assert '类内第 1 推荐' in output.markdown
    assert '综合第 1 推荐' in output.markdown
    sample = service.produce_outline_and_sample(task, output).sample
    assert '核心研究问题' in sample
    assert '数据可得性' in sample


def test_a_dialogue_rejects_a_category_without_two_slots(tmp_path):
    task = make_task('A_DIALOGUE', tmp_path)
    task.component_data['topic_groups'][0]['slots'] = task.component_data['topic_groups'][0]['slots'][:1]

    with pytest.raises(WritingInputError, match='two slots'):
        WritingService(workspace_root=tmp_path).produce_components(task)


def test_b_support_heading_annotation_is_normalized_and_shape_passes():
    body = valid_b_body()
    assert any('固定节名' in error for error in _b_body_shape_errors(body))
    normalized = _normalize_b_headings(body)
    assert '## 已有研究对本项目技术路线的支撑' in normalized
    assert '强制构件二' not in normalized
    assert _b_body_shape_errors(normalized) == []


def test_b_overlong_body_is_compacted_before_delivery(tmp_path):
    class OverlongModel:
        def __init__(self):
            self.compactions = 0

        def complete_json(self, system_prompt, payload):
            if payload.get('stage') == 'components':
                return {'components': component_data('B')}
            if 'validation_errors' in payload:
                self.compactions += 1
                return {'body': valid_b_body()}
            return {'body': valid_b_body(filler_repeats=140), 'evidence': [EVIDENCE]}

    model = OverlongModel()
    task = make_task('B', tmp_path, component_data=None, project={'name': '项目甲', 'goal': '目标乙'})
    output = WritingService(workspace_root=tmp_path, model=model).produce(task)

    assert model.compactions == 1
    assert 2000 <= _b_word_count(output.body) <= 3000
    assert any(event.kind == 'b_body_compacted' for event in task.events)


def test_b_components_include_project_demand_mapping_and_six_link_chain(tmp_path):
    service = WritingService(workspace_root=tmp_path)
    output = service.produce_components(make_task('B', tmp_path))

    assert '若不开展本项目' in output.markdown
    assert '不足↔科学问题↔研究内容' in output.markdown
    for name in ('研究需求', '已有进展', '现有不足', '关键科学问题', '项目切入点', '预期贡献'):
        assert name in output.markdown
    sample = service.produce_outline_and_sample(make_task('B', tmp_path), output).sample
    assert '项目名称' in sample
    assert '技术路线' not in sample or '对解表' in sample or '刚性需求' in sample


def test_b_minimal_project_generates_components_and_body_without_key_error(tmp_path):
    project = {
        'name': '车库暴露约束下的损失联合校准',
        'goal': '建立暴露、恢复与损失联合校准方法',
        'funding': '未指定',
    }
    task = make_task('B', tmp_path, project=project)
    service = WritingService(workspace_root=tmp_path)

    output = service.produce(
        task,
        body_writer=lambda context: successful_body('本项目拟建立联合校准方法 [1]。'),
    )

    for section in ('研究内容与技术路线', '技术路线', '可行性', '预期成果'):
        assert section in output.components.markdown
    assert output.components.markdown.count(B_SYSTEM_GENERATED_PLACEHOLDER) == 4
    assert output.body_path.exists()
    assert '本项目拟建立联合校准方法 [1]' in output.body_path.read_text(encoding='utf-8')


def test_b_render_uses_placeholder_for_missing_or_empty_project_fields(tmp_path):
    task = make_task('B', tmp_path, project={'name': '项目甲', 'goal': '目标乙', 'funding': '未指定'})
    markdown = _render_b(task, component_data('B'))
    assert markdown.count(B_SYSTEM_GENERATED_PLACEHOLDER) == 4

    task = make_task('B', tmp_path, project={
        'name': '项目甲', 'goal': '目标乙', 'funding': '未指定',
        'research_contents': [], 'technical_route': '', 'feasibility': '  ', 'expected_outcomes': '',
    })
    assert _render_b(task, component_data('B')).count(B_SYSTEM_GENERATED_PLACEHOLDER) == 4


def test_b_full_project_still_renders_user_supplied_plan_fields(tmp_path):
    output = WritingService(workspace_root=tmp_path).produce_components(make_task('B', tmp_path))

    assert '研究内容（1）联合建模' in output.markdown
    assert '技术路线：输入→联合建模→跨区验证→输出' in output.markdown
    assert '可行性：数据公开性未确认' in output.markdown
    assert '预期成果：联合校准方法、验证协议与论文。' in output.markdown
    assert B_SYSTEM_GENERATED_PLACEHOLDER not in output.markdown


def test_c1_has_five_paragraph_cards_and_research_gap(tmp_path):
    service = WritingService(workspace_root=tmp_path)
    output = service.produce_components(make_task('C1', tmp_path))

    assert output.markdown.count('段落卡·') == 5
    assert 'Research Gap 分析表' in output.markdown
    assert '现有研究不足' in output.markdown


def test_c2_without_user_results_contains_comparison_template_and_no_invented_findings(tmp_path):
    service = WritingService(workspace_root=tmp_path)
    task = make_task('C2', tmp_path, user_results='')
    output = service.produce_components(task)

    assert '文献比较表' in output.markdown
    assert '研究空白分析表' in output.markdown
    assert '本研究发现' not in output.markdown
    assert '比较表模板' in output.c2


def test_d_has_nine_part_inputs_method_table_and_three_complete_reading_pages(tmp_path):
    service = WritingService(workspace_root=tmp_path)
    task = make_task('D', tmp_path)
    components = service.produce_components(task)
    outline = service.produce_outline_and_sample(task, components)

    assert '检索概况' in components.markdown
    assert '方法对比表' in components.markdown
    assert components.markdown.count('精读页·') == 3
    assert '阅读深度：仅摘要' in components.markdown
    assert '选题排序' in components.markdown
    assert '组会讨论问题' in components.markdown
    assert '检索概况' in outline.sample and '精读页·' in outline.sample


def test_invalid_component_quote_is_rejected_before_body(tmp_path):
    task = make_task('A', tmp_path)
    bad = {'claim': 'Unsupported', 'refs': [1], 'quotes': {'1': 'This sentence is not in the abstract.'}}
    task.component_data['gaps'][0]['evidence'] = [bad, SECOND_EVIDENCE]
    service = WritingService(workspace_root=tmp_path)

    with pytest.raises(WritingInputError, match='abstract'):
        service.produce(task, body_writer=lambda context: successful_body('不得生成'))

    assert task.events == []


def test_bibliographic_only_paper_cannot_support_components(tmp_path):
    task = make_task('A', tmp_path)
    bad = {'claim': 'Unsupported', 'refs': [3], 'quotes': {'3': 'No abstract exists.'}}
    task.component_data['gaps'][0]['evidence'] = [bad, SECOND_EVIDENCE]

    with pytest.raises(WritingInputError, match='claim-eligible'):
        WritingService(workspace_root=tmp_path).produce_components(task)


def test_body_evidence_is_bound_to_abstract_and_written_to_ledger(tmp_path):
    task = make_task('C1', tmp_path)
    service = WritingService(workspace_root=tmp_path)

    output = service.produce(
        task,
        body_writer=lambda context: successful_body('研究问题重要，现有模型改善了损失估计 [1]。'),
    )

    ledger = (tmp_path / task.id / 'evidence_ledger.md').read_text()
    assert 'The calibrated model reduced urban flood loss estimation error.' in ledger
    assert '| B |' in ledger
    assert output.evidence[0]['level'] == 'B'


def test_missing_body_composer_fails_honestly(tmp_path):
    task = make_task('A', tmp_path)

    with pytest.raises(WritingInputError, match='body composer'):
        WritingService(workspace_root=tmp_path).produce(task)


def test_model_can_generate_components_and_body_without_a_custom_writer(tmp_path):
    class FakeModel:
        def __init__(self):
            self.stages = []
            self.payloads = []

        def complete_json(self, system_prompt, payload):
            self.stages.append(payload['stage'])
            self.payloads.append(payload)
            if payload['stage'] == 'components':
                return {'components': component_data('A')}
            return {
                'body': '该领域分为损失评估与暴露调查两块，模型改善了损失估计 [1]。',
                'evidence': [EVIDENCE],
            }

    model = FakeModel()
    task = make_task('A', tmp_path, component_data=None)
    output = WritingService(workspace_root=tmp_path, model=model).produce(task)

    assert model.stages == ['components', 'body']
    assert all('方向卡' in payload['mode_template'] for payload in model.payloads)
    assert all(payload['analysis'] == {'clusters': ['损失评估', '暴露调查']} for payload in model.payloads)
    assert output.body_path.exists()
    assert '（据摘要）' in output.body


def test_components_with_uncited_reference_are_retried_once(tmp_path):
    class RetryModel:
        def __init__(self):
            self.components_calls = 0

        def complete_json(self, system_prompt, payload):
            self.components_calls += 1
            data = component_data('A')
            if self.components_calls == 1:
                data['landscape'][0]['direction'] = '损失评估与暴露调查 [3]'
            return {'components': data}

    model = RetryModel()
    task = make_task('A', tmp_path, component_data=None)
    output = WritingService(workspace_root=tmp_path, model=model).produce(
        task, body_writer=lambda context: successful_body('领域格局与方向卡正文 [1]。'),
    )

    assert model.components_calls == 2
    assert '方向卡' in output.components.markdown


def test_body_prompt_carries_length_and_blank_row_rules(tmp_path):
    class FakeModel:
        def __init__(self):
            self.payloads = []

        def complete_json(self, system_prompt, payload):
            self.payloads.append(payload)
            if payload['stage'] == 'components':
                return {'components': component_data('A')}
            return {'body': '领域格局与方向卡正文 [1]。', 'evidence': [EVIDENCE]}

    model = FakeModel()
    task = make_task('A', tmp_path, component_data=None)
    WritingService(workspace_root=tmp_path, model=model).produce(task)

    body_payload = [p for p in model.payloads if p['stage'] == 'body'][0]
    assert body_payload['length_target'] == '1500-2500'
    assert '空白1：' in body_payload['format_rules']


def test_b_model_payloads_require_system_generated_plan_sections(tmp_path):
    class FakeModel:
        def __init__(self):
            self.calls = []

        def complete_json(self, system_prompt, payload):
            self.calls.append((system_prompt, payload))
            if payload['stage'] == 'components':
                return {'components': component_data('B')}
            return {'body': valid_b_body(), 'evidence': [EVIDENCE]}

    model = FakeModel()
    task = make_task('B', tmp_path, component_data=None, project={'name': '项目甲', 'goal': '目标乙'})
    WritingService(workspace_root=tmp_path, model=model).produce(task)

    assert [payload['stage'] for _, payload in model.calls] == ['components', 'body']
    for system_prompt, payload in model.calls:
        assert payload['project_generation_rules'] == B_PROJECT_GENERATION_RULE
        assert '研究内容（3–4 项）' in payload['project_generation_rules']
        assert '不得留空' in payload['project_generation_rules']
        assert B_PROJECT_GENERATION_RULE in system_prompt


def test_model_body_unsupported_citation_is_repaired_after_retries(tmp_path):
    class InvalidCitationModel:
        def __init__(self):
            self.body_calls = 0

        def complete_json(self, system_prompt, payload):
            if payload['stage'] == 'components':
                return {'components': component_data('A')}
            self.body_calls += 1
            return {
                'body': '正文引用未入账文献 [3]，但仍保留有效引用 [1]。',
                'evidence': [EVIDENCE],
            }

    model = InvalidCitationModel()
    task = make_task('A', tmp_path, component_data=None)
    output = WritingService(workspace_root=tmp_path, model=model).produce(task)

    assert model.body_calls == 2
    assert '[3]' not in output.body
    assert '引用修复：已移除 1 处无证据编号' in output.body
    assert any(
        event.kind == 'citation_repair' and event.payload.get('stage') == 'body'
        for event in task.events
    )


def test_body_with_uncited_reference_is_retried_once(tmp_path):
    class RetryModel:
        def __init__(self):
            self.body_calls = 0

        def complete_json(self, system_prompt, payload):
            if payload['stage'] == 'components':
                return {'components': component_data('A')}
            self.body_calls += 1
            if self.body_calls == 1:
                return {'body': '领域格局引用未入账文献 [3]。', 'evidence': [EVIDENCE]}
            return {'body': '领域格局与方向卡正文 [1]。', 'evidence': [EVIDENCE]}

    model = RetryModel()
    task = make_task('A', tmp_path, component_data=None)
    output = WritingService(workspace_root=tmp_path, model=model).produce(task)

    assert model.body_calls == 2
    assert '[1]' in output.body


def test_component_prompt_carries_machine_readable_schema(tmp_path):
    class FakeModel:
        def __init__(self):
            self.payloads = []

        def complete_json(self, system_prompt, payload):
            self.payloads.append(payload)
            return {'components': component_data('A')}

    model = FakeModel()
    task = make_task('A', tmp_path, component_data=None)
    WritingService(workspace_root=tmp_path, model=model).produce_components(task)

    schema = model.payloads[0]['components_schema']
    assert 'directions' in schema
    assert 'gaps' in schema
    assert '3' in schema


def test_invalid_generated_component_shape_is_retried_once(tmp_path):
    class RetryModel:
        def __init__(self):
            self.components_calls = 0

        def complete_json(self, system_prompt, payload):
            self.components_calls += 1
            broken = component_data('A')
            broken['directions'] = broken['directions'][:1]
            if self.components_calls == 1:
                return {'components': broken}
            return {'components': component_data('A')}

    model = RetryModel()
    task = make_task('A', tmp_path, component_data=None)
    output = WritingService(workspace_root=tmp_path, model=model).produce(
        task, body_writer=lambda context: successful_body('领域格局与方向卡正文 [1]。'),
    )

    assert model.components_calls == 2
    assert '方向卡' in output.components.markdown


def test_generated_component_shape_failure_after_retry_is_reported(tmp_path):
    class BadModel:
        def __init__(self):
            self.components_calls = 0

        def complete_json(self, system_prompt, payload):
            self.components_calls += 1
            broken = component_data('A')
            broken['directions'] = broken['directions'][:1]
            return {'components': broken}

    model = BadModel()
    task = make_task('A', tmp_path, component_data=None)

    with pytest.raises(WritingInputError, match='3–5 direction cards'):
        WritingService(workspace_root=tmp_path, model=model).produce(
            task, body_writer=successful_body('正文 [1]。'),
        )
    assert model.components_calls == 2


def test_template_override_is_used_for_both_model_calls(tmp_path):
    class FakeModel:
        def __init__(self):
            self.templates = []

        def complete_json(self, system_prompt, payload):
            self.templates.append(payload['mode_template'])
            if payload['stage'] == 'components':
                return {'components': component_data('A')}
            return {'body': '领域格局 [1]。', 'evidence': [EVIDENCE]}

    model = FakeModel()
    task = make_task('A', tmp_path, component_data=None)
    WritingService(
        workspace_root=tmp_path,
        model=model,
        template_overrides={'A': 'PINNED VERSION TEMPLATE'},
    ).produce(task)

    assert model.templates == ['PINNED VERSION TEMPLATE', 'PINNED VERSION TEMPLATE']


def test_body_prompt_requests_json_mode(tmp_path):
    class PromptModel:
        def __init__(self):
            self.prompts = []

        def complete_json(self, system_prompt, payload):
            self.prompts.append(system_prompt)
            if payload['stage'] == 'components':
                return {'components': component_data('A')}
            return {'body': '领域格局正文 [1]。', 'evidence': [EVIDENCE]}

    model = PromptModel()
    task = make_task('A', tmp_path, component_data=None)
    WritingService(workspace_root=tmp_path, model=model).produce(task)

    assert 'JSON' in model.prompts[-1]


def test_b_component_invalid_evidence_is_dropped_after_retries(tmp_path):
    class InvalidEvidenceModel:
        def __init__(self):
            self.calls = 0

        def complete_json(self, system_prompt, payload):
            self.calls += 1
            data = component_data('B')
            data['demand']['evidence'] = [{
                'claim': 'Unsupported', 'refs': [3],
                'quotes': {'3': 'No abstract exists.'},
            }]
            return {'components': data}

    model = InvalidEvidenceModel()
    task = make_task('B', tmp_path, component_data=None)
    output = WritingService(workspace_root=tmp_path, model=model).produce_components(task)

    assert model.calls == 2
    assert '证据修复' in output.markdown
    assert any(event.kind == 'evidence_repair' for event in task.events)
    assert 'No abstract exists' not in output.markdown


def test_c2_body_prompt_requires_the_structured_review_sections(tmp_path):
    class PromptModel:
        def __init__(self):
            self.prompts = []

        def complete_json(self, system_prompt, payload):
            self.prompts.append(system_prompt)
            if payload['stage'] == 'components':
                return {'components': component_data('C2')}
            return {'body': '结构化综述 [1]。', 'evidence': [EVIDENCE]}

    model = PromptModel()
    task = make_task('C2', tmp_path, component_data=None)
    WritingService(workspace_root=tmp_path, model=model).produce(task)

    prompt = model.prompts[-1]
    for marker in ('研究主题与检索范围', '文献分类框架', '完整综述文本', '800–1200'):
        assert marker in prompt


def test_body_citation_without_a_ledger_entry_is_rejected(tmp_path):
    task = make_task('A', tmp_path)

    with pytest.raises(WritingInputError, match='no evidence'):
        WritingService(workspace_root=tmp_path).produce(
            task,
            body_writer=lambda context: successful_body('两篇研究形成互补 [1][2]。'),
        )

    assert not (tmp_path / task.id / '综述初稿.md').exists()


def test_invalid_body_quote_does_not_emit_body_ready(tmp_path):
    task = make_task('A', tmp_path)
    bad = {'claim': 'Unsupported', 'refs': [1], 'quotes': {'1': 'Not present in the abstract.'}}

    with pytest.raises(WritingInputError, match='abstract'):
        WritingService(workspace_root=tmp_path).produce(
            task,
            body_writer=lambda context: successful_body('错误论断 [1]。', [bad]),
        )

    assert [event.kind for event in task.events] == ['components_ready', 'outline_ready', 'sample_ready']


def test_component_shape_requirements_are_enforced(tmp_path):
    service = WritingService(workspace_root=tmp_path)

    a = make_task('A', tmp_path)
    a.component_data['directions'] = a.component_data['directions'][:2]
    with pytest.raises(WritingInputError, match='3–5 direction'):
        service.produce_components(a)

    b = make_task('B', tmp_path)
    del b.component_data['chain']['预期贡献']
    with pytest.raises(WritingInputError, match='six-link'):
        service.produce_components(b)

    c1 = make_task('C1', tmp_path)
    c1.component_data['paragraph_cards'] = c1.component_data['paragraph_cards'][:3]
    with pytest.raises(WritingInputError, match='4–6 paragraph'):
        service.produce_components(c1)

    d = make_task('D', tmp_path)
    d.component_data['reading_cards'] = d.component_data['reading_cards'][:2]
    with pytest.raises(WritingInputError, match='3–5 reading'):
        service.produce_components(d)


def test_a_requires_three_to_five_evidence_backed_gaps(tmp_path):
    task = make_task('A', tmp_path)
    task.component_data['gaps'] = task.component_data['gaps'][:2]

    with pytest.raises(WritingInputError, match='3–5 gap'):
        WritingService(workspace_root=tmp_path).produce_components(task)


def test_e_mode_uses_custom_purpose_markdown_component_and_body_file(tmp_path):
    class EModel:
        def __init__(self):
            self.calls = []

        def complete_json(self, system_prompt, payload):
            self.calls.append((system_prompt, payload))
            if payload['stage'] == 'components':
                return {'components': {
                    'markdown': '## 用途落实\n\n按政策简报用途组织证据 [1]（据摘要）。',
                    'evidence': [EVIDENCE],
                }}
            return {'body': '政策简报用途下的综述正文 [1]（据摘要）。', 'evidence': [EVIDENCE]}

    model = EModel()
    task = make_task(
        'E',
        tmp_path,
        component_data=None,
        custom_purpose='为学院写一份面向政策制定的交通安全证据简报',
    )
    output = WritingService(workspace_root=tmp_path, model=model).produce(task)

    assert [payload['stage'] for _, payload in model.calls] == ['components', 'body']
    for system_prompt, payload in model.calls:
        assert payload['custom_purpose'] == task.custom_purpose
        assert payload['custom_purpose_rules']
        assert 'E 模式是用户自定义用途' in system_prompt
    assert '用途落实' in output.components.markdown
    assert output.body_path.name == '综述初稿.md'
    assert '按用户用途定制的提纲' in output.outline


def test_b_project_theme_is_rendered_into_components(tmp_path):
    theme = {
        'name': '车库暴露约束下的损失联合校准',
        'goal': '建立暴露、恢复与损失联合校准方法',
        'object': '城市地下车库',
        'method': '联合建模与情景比较',
        'expected_output': '校准方法与验证协议',
    }
    task = make_task(
        'B',
        tmp_path,
        project={
            'name': '车库暴露约束下的损失联合校准',
            'goal': '建立暴露、恢复与损失联合校准方法',
            'funding': '未指定',
            'theme': theme,
        },
    )
    output = WritingService(workspace_root=tmp_path).produce(
        task,
        body_writer=lambda context: successful_body('本项目拟建立联合校准方法 [1]。'),
    )

    markdown = output.components.markdown
    assert '## 项目主题（用户选定）' in markdown
    assert '- 研究对象：城市地下车库' in markdown
    assert '- 方法：联合建模与情景比较' in markdown
    assert '- 预期产出：校准方法与验证协议' in markdown
