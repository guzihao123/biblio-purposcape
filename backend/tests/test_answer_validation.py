import pytest
from fastapi import HTTPException

from app.answer_validation import validate_answer_value


def mode_answer(**overrides):
    value = {'mode': 'E', 'custom': '为学院写一份政策证据简报'}
    value.update(overrides)
    return value


def test_mode_e_requires_and_accepts_a_custom_purpose():
    validate_answer_value('mode', mode_answer())

    with pytest.raises(HTTPException) as missing:
        validate_answer_value('mode', {'mode': 'E'})
    assert missing.value.status_code == 422
    assert 'custom purpose' in missing.value.detail['message']

    with pytest.raises(HTTPException):
        validate_answer_value('mode', mode_answer(custom='   '))


def test_mode_rejects_unknown_fields_and_unsupported_modes():
    with pytest.raises(HTTPException) as unknown:
        validate_answer_value('mode', mode_answer(unexpected='x'))
    assert unknown.value.status_code == 422
    assert 'unknown answer fields' in unknown.value.detail['message']

    with pytest.raises(HTTPException):
        validate_answer_value('mode', {'mode': 'F', 'custom': 'x'})


def test_mode_b_accepts_project_theme_selected_from_candidates():
    value = {
        'mode': 'B',
        'project': {'name': '车库暴露约束下的内涝损失联合校准', 'goal': '建立联合校准方法'},
        'theme': {
            'name': '车库暴露约束下的内涝损失联合校准',
            'goal': '建立联合校准方法',
            'object': '城市地下车库',
            'method': '联合建模与情景比较',
            'expected_output': '校准方法与验证协议',
        },
    }
    validate_answer_value('mode', value)


def test_mode_rejects_incomplete_or_malformed_project_theme():
    base = {'mode': 'B', 'project': {'name': '项目', 'goal': '目标'}}

    with pytest.raises(HTTPException) as missing_name:
        validate_answer_value('mode', {**base, 'theme': {'goal': '只有目标'}})
    assert 'theme requires a name or custom text' in missing_name.value.detail['message']

    with pytest.raises(HTTPException) as unknown:
        validate_answer_value('mode', {**base, 'theme': {'name': '主题', 'unknown': 'x'}})
    assert 'unknown answer fields' in unknown.value.detail['message']

    with pytest.raises(HTTPException):
        validate_answer_value('mode', {**base, 'theme': 'not-an-object'})


def test_mode_custom_purpose_has_a_length_limit():
    with pytest.raises(HTTPException) as too_long:
        validate_answer_value('mode', mode_answer(custom='用' * 2_001))
    assert too_long.value.status_code == 422
    assert 'too long' in too_long.value.detail['message']


def test_mode_b_requires_theme_and_project_name_goal():
    with pytest.raises(HTTPException) as missing:
        validate_answer_value('mode', {'mode': 'B'})
    assert 'project theme' in missing.value.detail['message']

    with pytest.raises(HTTPException):
        validate_answer_value('mode', {'mode': 'B', 'theme': {'name': '主题'}})

    with pytest.raises(HTTPException):
        validate_answer_value('mode', {
            'mode': 'B', 'theme': {'name': '主题'}, 'project': {'name': ' ', 'goal': '目标'},
        })

    validate_answer_value('mode', {
        'mode': 'B', 'theme': {'name': '主题'}, 'project': {'name': '项目', 'goal': '目标'},
    })


def test_mode_c_requires_route_and_information_choice():
    with pytest.raises(HTTPException) as missing:
        validate_answer_value('mode', {'mode': 'C'})
    assert 'C-mode task' in missing.value.detail['message']

    with pytest.raises(HTTPException):
        validate_answer_value('mode', {'mode': 'C', 'c_route': 'C2'})

    validate_answer_value('mode', {'mode': 'C', 'c_route': 'C2', 'c_info_route': 'skip'})
