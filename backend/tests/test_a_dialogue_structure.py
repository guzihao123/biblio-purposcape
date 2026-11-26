import re
from copy import deepcopy
from pathlib import Path

from app.writing import (
    FORMAT_RULES,
    WritingService,
    _a_dialogue_shape_errors,
    _a_dialogue_word_count,
    _ensure_a_dialogue_intro,
    _pad_a_dialogue_body,
    _render_a_dialogue,
    _rebuild_a_dialogue_body,
)

from test_writing import EVIDENCE, SECOND_EVIDENCE, component_data, make_task


def dialogue_body_without_key_points():
    data = component_data('A_DIALOGUE')
    body = _render_a_dialogue(data)
    body = re.sub(r'^### 选题 ([12])｜', r'- 选题 \1｜', body, flags=re.M)
    return data, body


def test_a_dialogue_prompt_requires_opening_key_points():
    rule = FORMAT_RULES['A_DIALOGUE']
    assert '领域格局与对话要点' in rule
    assert '5–8' in rule
    assert '研究空白' in rule


def test_a_dialogue_missing_key_points_are_injected_from_components(tmp_path):
    data, body = dialogue_body_without_key_points()
    task = make_task('A_DIALOGUE', tmp_path)
    task.component_data = data

    before = _a_dialogue_shape_errors(body)
    assert any('key points' in error or 'research-gap' in error for error in before)

    repaired = _ensure_a_dialogue_intro(body, task)
    errors = _a_dialogue_shape_errors(repaired)
    assert errors == []
    assert 1500 <= _a_dialogue_word_count(repaired) <= 4000

    pre_body = repaired.split('理论创新型选题', 1)[0]
    key_lines = [
        line for line in pre_body.splitlines()
        if re.match(r'^\s*[-*]\s+', line) and re.search(r'\[\d+\]', line)
    ]
    assert 5 <= len(key_lines) <= 8
    assert sum(1 for line in key_lines if '空白' in line) >= 3
    assert '领域格局' in repaired[:800]


def test_a_dialogue_rebuild_uses_components_and_passes_shape(tmp_path):
    data, _ = dialogue_body_without_key_points()
    task = make_task('A_DIALOGUE', tmp_path)
    task.component_data = data

    rebuilt = _rebuild_a_dialogue_body(task)
    assert rebuilt is not None
    assert _a_dialogue_shape_errors(rebuilt.text) == []
    assert 1500 <= _a_dialogue_word_count(rebuilt.text) <= 4000
    assert re.search(r'\[\d+\]', rebuilt.text)
    assert '领域格局与对话要点' in rebuilt.text


def test_a_dialogue_rebuild_compacts_long_slots_within_word_limit(tmp_path):
    data, _ = dialogue_body_without_key_points()
    for group in data['topic_groups']:
        for slot in group['slots']:
            for key in ('core_question', 'data_availability', 'opportunity', 'risk'):
                slot[key] = slot[key] * 3
    task = make_task('A_DIALOGUE', tmp_path)
    task.component_data = data

    rebuilt = _rebuild_a_dialogue_body(task)
    assert rebuilt is not None
    assert _a_dialogue_shape_errors(rebuilt.text) == []
    assert 1500 <= _a_dialogue_word_count(rebuilt.text) <= 4000


def _short_dialogue_body(data, task):
    short = deepcopy(data)
    for group in short['topic_groups']:
        for slot in group['slots']:
            for key in ('core_question', 'opportunity', 'risk', 'data_availability'):
                slot[key] = '简述。'
    body = _render_a_dialogue(short)
    body = re.sub(r'^### 选题 ([12])｜', r'- 选题 \1｜', body, flags=re.M)
    return _ensure_a_dialogue_intro(body, task)


def _rich_gaps(data):
    rich = deepcopy(data)
    for gap in rich['gaps']:
        gap['reason'] = gap['reason'] * 4
    for row in rich['landscape']:
        row['share'] = row['share'] * 4
    return rich


def _unlabeled_b_groups(text):
    bad = []
    for match in re.finditer(r'(?:\[\d+\])+', text):
        refs = [int(ref) for ref in re.findall(r'\[(\d+)\]', match.group(0))]
        if 1 in refs and not text[match.end():].startswith(('（据摘要）', '（部分据摘要）')):
            bad.append(match.group(0))
    return bad


def test_pad_noop_when_word_count_sufficient(tmp_path):
    data, body = dialogue_body_without_key_points()
    task = make_task('A_DIALOGUE', tmp_path)
    task.component_data = data
    body = _ensure_a_dialogue_intro(body, task)
    assert _a_dialogue_word_count(body) >= 1500
    assert _pad_a_dialogue_body(body, task) == body


def test_pad_appends_evidence_boundary_with_audited_refs(tmp_path):
    data, _ = dialogue_body_without_key_points()
    task = make_task('A_DIALOGUE', tmp_path)
    task.component_data = data
    body = _short_dialogue_body(data, task)
    assert _a_dialogue_word_count(body) < 1500

    padded = _pad_a_dialogue_body(body, task)
    assert '## 证据边界与待核对事项' in padded
    assert _a_dialogue_word_count(padded) > _a_dialogue_word_count(body)
    section = padded.split('## 证据边界与待核对事项', 1)[1]
    refs = {int(ref) for ref in re.findall(r'\[(\d+)\]', section)}
    assert refs and refs <= {1, 2}


def test_pad_closes_short_body_when_evidence_text_rich(tmp_path):
    data, _ = dialogue_body_without_key_points()
    task = make_task('A_DIALOGUE', tmp_path)
    task.component_data = data
    body = _short_dialogue_body(data, task)
    task.component_data = _rich_gaps(data)

    padded = _pad_a_dialogue_body(body, task)
    assert _a_dialogue_word_count(padded) >= 1500
    assert _a_dialogue_shape_errors(padded) == []


def test_pad_noop_without_evidence(tmp_path):
    data, _ = dialogue_body_without_key_points()
    stripped = deepcopy(data)
    for gap in stripped['gaps']:
        gap['evidence'] = []
    for row in stripped['landscape']:
        row['evidence'] = []
    task = make_task('A_DIALOGUE', tmp_path)
    task.component_data = stripped
    body = _short_dialogue_body(data, task)
    assert _pad_a_dialogue_body(body, task) == body


def test_rebuild_labels_b_level_citations(tmp_path):
    data, _ = dialogue_body_without_key_points()
    task = make_task('A_DIALOGUE', tmp_path)
    task.component_data = data

    rebuilt = _rebuild_a_dialogue_body(task)
    assert rebuilt is not None
    assert _a_dialogue_shape_errors(rebuilt.text) == []
    assert _unlabeled_b_groups(rebuilt.text) == []


class _StubModel:
    def __init__(self, data, body):
        self.data = data
        self.body = body

    def complete_json(self, system_prompt, payload):
        if payload.get('stage') == 'components':
            return {'components': self.data}
        return {'body': self.body, 'evidence': [deepcopy(EVIDENCE), deepcopy(SECOND_EVIDENCE)]}


def test_normal_path_short_body_pads_and_labels(tmp_path):
    data, _ = dialogue_body_without_key_points()
    task = make_task('A_DIALOGUE', tmp_path)
    task.component_data = data
    body = _short_dialogue_body(data, task)
    task.component_data = _rich_gaps(data)

    service = WritingService(workspace_root=tmp_path, model=_StubModel(task.component_data, body))
    output = service.produce(task)
    text = output.body_path.read_text(encoding='utf-8')
    assert '## 证据边界与待核对事项' in text
    assert _a_dialogue_shape_errors(text) == []
    assert _unlabeled_b_groups(text) == []
    assert 'a_dialogue_rebuilt' not in [event.kind for event in task.events]
