from copy import deepcopy

import pytest

from app.writing import (
    WritingInputError,
    WritingService,
    _b_body_shape_errors,
    _b_word_count,
    _normalize_b_headings,
    _repair_b_body,
    _validate_b_body,
)
from test_writing import EVIDENCE, SECOND_EVIDENCE, component_data, make_task


def oversized_b_body():
    text = deepcopy(component_data('B'))
    body = '\n'.join([
        '# 项目甲',
        '',
        '本项目拟建立联合校准方法，并在三个地区开展验证。',
        '',
        '## 已有研究对本项目技术路线的支撑',
        '',
        '- 研究内容（一）：资产 [1]。',
        '- 研究内容（二）：资产 [2]。',
        '- 研究内容（三）：资产 [1][2]。',
        '',
        '## 关键不足',
        '',
        '| 不足 | 科学问题 | 研究内容 |',
        '|---|---|---|',
        '| 证据不足 | 如何校准 | 研究内容（一） |',
        '',
        '## 六段论证链',
        '',
        '**研究需求**：需求 [1]。**已有进展**：进展 [2]。**现有不足**：不足 [1]。',
        '**科学问题**：问题 [1]。**项目切入点**：本项目切入 [2]。**预期贡献**：贡献 [1]。',
        '',
        '## 研究内容',
        '',
        '本项目将补充数据并校准模型 [1]。' * 260,
        '',
        '## 参考文献',
        '[1] X',
        '[2] Y',
    ])
    return text, body


def test_repair_adds_real_demand_and_compacts_to_b_budget(tmp_path):
    data, body = oversized_b_body()
    task = make_task('B', tmp_path)
    task.component_data = data
    assert _b_word_count(body) > 3000
    assert any('missing 刚性需求段' in error for error in _b_body_shape_errors(body))

    repaired = _repair_b_body(body, task)
    validated = _validate_b_body(repaired)

    assert validated == _normalize_b_headings(repaired)
    assert '刚性需求段（若不开展本项目）' in validated
    assert data['demand']['text'] in validated
    assert 2000 <= _b_word_count(validated) <= 3000
    assert _b_body_shape_errors(validated) == []


def test_validate_can_repair_b_body_with_component_context(tmp_path):
    data, body = oversized_b_body()
    task = make_task('B', tmp_path)
    task.component_data = data

    with pytest.raises(WritingInputError):
        _validate_b_body(body)

    validated = _validate_b_body(body, task)
    assert 2000 <= _b_word_count(validated) <= 3000
    assert _b_body_shape_errors(validated) == []


def test_repair_does_not_duplicate_existing_demand_section(tmp_path):
    data, body = oversized_b_body()
    task = make_task('B', tmp_path)
    task.component_data = data
    demand = f"## 刚性需求段（若不开展本项目）\n\n{data['demand']['text']} [1][2]\n\n"
    body = body.replace('# 项目甲\n\n', '# 项目甲\n\n' + demand, 1)

    repaired = _repair_b_body(body, task)

    assert repaired.count('刚性需求段（若不开展本项目）') == 1


class _StubModel:
    def __init__(self, body):
        self.body = body

    def complete_json(self, system_prompt, payload):
        if payload.get('stage') == 'components':
            return {'components': component_data('B')}
        return {'body': self.body, 'evidence': [EVIDENCE, SECOND_EVIDENCE]}


def test_normal_b_path_repairs_oversized_body_without_rebuild(tmp_path):
    data, body = oversized_b_body()
    task = make_task('B', tmp_path)
    task.component_data = data
    service = WritingService(workspace_root=tmp_path, model=_StubModel(body))

    output = service.produce(task)
    text = output.body_path.read_text(encoding='utf-8')

    assert _b_body_shape_errors(text) == []
    assert 2000 <= _b_word_count(text) <= 3000
    assert '刚性需求段（若不开展本项目）' in text
