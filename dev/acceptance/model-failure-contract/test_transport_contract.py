"""传输层契约：ChatModel.complete_json 对异常与畸形响应的行为。

覆盖 Provider 401、429（合法/非法 Retry-After）、超时、空响应、
结构不符 JSON 等场景。契约要点：传输异常原样上抛（不吞、不转成
伪成功返回值）；解析失败只抛固定文案 ValueError，不携带 Provider 原文。
"""

import openai
import pytest

from app.qwen import ChatModel

from matrix_shared import (
    FakeOpenAIClient,
    make_401_error,
    make_429_error,
    make_context_length_error,
    make_timeout_error,
)

SYSTEM = 'Return JSON.'
PAYLOAD = {'papers': [{'ref': 1}]}


def complete_with(script):
    model = ChatModel(client=FakeOpenAIClient(script), model='fake-model')
    return model.complete_json(SYSTEM, PAYLOAD)


def test_401_authentication_error_propagates_unchanged_single_attempt():
    error = make_401_error()
    client = FakeOpenAIClient([error])

    with pytest.raises(type(error)) as raised:
        ChatModel(client=client, model='fake-model').complete_json(SYSTEM, PAYLOAD)

    assert raised.value is error
    assert client.call_count == 1


def test_429_with_valid_retry_after_propagates_without_in_call_retry():
    error = make_429_error('120')
    client = FakeOpenAIClient([error])

    with pytest.raises(openai.RateLimitError):
        ChatModel(client=client, model='fake-model').complete_json(SYSTEM, PAYLOAD)

    # complete_json 内部不做重试：一次 429 即一次调用即上抛。
    assert client.call_count == 1


def test_429_with_invalid_retry_after_values_still_propagate():
    for bad_value in ('not-a-number', '-5', '', '99999999999999999999'):
        error = make_429_error(bad_value)
        client = FakeOpenAIClient([error])
        with pytest.raises(Exception) as raised:
            ChatModel(client=client, model='fake-model').complete_json(SYSTEM, PAYLOAD)
        assert raised.value is error
        assert client.call_count == 1


def test_429_without_retry_after_header_still_propagates():
    error = make_429_error(retry_after=None)
    client = FakeOpenAIClient([error])

    with pytest.raises(Exception) as raised:
        ChatModel(client=client, model='fake-model').complete_json(SYSTEM, PAYLOAD)

    assert raised.value is error
    assert client.call_count == 1


def test_timeout_error_retries_bounded_and_then_returns(monkeypatch):
    from app.recovery import retry_call as real_retry_call

    monkeypatch.setattr(
        'app.qwen.retry_call',
        lambda call, **kwargs: real_retry_call(call, sleep=lambda _: None, **kwargs),
    )
    client = FakeOpenAIClient([make_timeout_error(), make_timeout_error(), '{"ok": true}'])

    assert ChatModel(client=client, model='fake-model').complete_json(SYSTEM, PAYLOAD) == {'ok': True}
    assert client.call_count == 3


def test_timeout_error_exhausts_bounded_attempts(monkeypatch):
    from app.recovery import retry_call as real_retry_call

    monkeypatch.setattr(
        'app.qwen.retry_call',
        lambda call, **kwargs: real_retry_call(call, sleep=lambda _: None, **kwargs),
    )
    errors = [make_timeout_error(), make_timeout_error(), make_timeout_error()]
    client = FakeOpenAIClient(errors)

    with pytest.raises(type(errors[-1])) as raised:
        ChatModel(client=client, model='fake-model').complete_json(SYSTEM, PAYLOAD)
    assert raised.value is errors[-1]
    assert client.call_count == 3


def test_context_length_400_propagates_unchanged():
    error = make_context_length_error()
    client = FakeOpenAIClient([error])

    with pytest.raises(type(error)) as raised:
        ChatModel(client=client, model='fake-model').complete_json(SYSTEM, PAYLOAD)

    assert raised.value is error
    assert client.call_count == 1


def test_empty_response_body_raises_value_error_without_provider_text():
    with pytest.raises(ValueError, match='valid JSON') as raised:
        complete_with([''])

    message = str(raised.value)
    assert 'Qwen response did not contain valid JSON' in message
    # 固定文案，不夹带 Provider 原文或响应体内容。
    assert len(message) < 80


@pytest.mark.parametrize('raw', ['42', '"hello"', 'true', '3.14'])
def test_scalar_json_raises_structure_error(raw):
    with pytest.raises(ValueError, match='object or array'):
        complete_with([raw])


def test_none_content_raises_value_error():
    # content=None 时 json.loads 抛 TypeError，被转换为固定文案 ValueError。
    with pytest.raises(ValueError, match='valid JSON'):
        complete_with([None])


def test_empty_choices_raises_value_error():
    client = FakeOpenAIClient(['unused'])

    class EmptyCompletions:
        def create(self, **kwargs):
            return type('R', (), {'choices': []})()

    client.chat.completions = EmptyCompletions()
    with pytest.raises(ValueError, match='valid JSON'):
        ChatModel(client=client, model='fake-model').complete_json(SYSTEM, PAYLOAD)


def test_valid_json_object_and_array_pass_through():
    assert complete_with(['{"a": 1}']) == {'a': 1}
    assert complete_with(['[1, 2]']) == [1, 2]
