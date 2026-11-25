"""离线异常矩阵共享件：哨兵秘密、假传输、罐头 Provider 异常与泄漏断言。

所有“密钥”都是显而易见的假值，只用于验证失败路径不把凭据写进
任何持久化或对外可见的表面。绝不触碰真实环境变量或网络。
"""

from types import SimpleNamespace

import httpx
import openai

FAKE_API_KEY = 'sk-fake-qwen-key-7f3a9c51e8b24d6f'
FAKE_BASE_URL = 'https://fake-user:fake-pass@qwen-fake-endpoint.internal:8443/v1'
FAKE_AUTH_HEADER = f'Bearer {FAKE_API_KEY}'
FAKE_PROVIDER_PRIVATE_RECORD = 'fake-provider-private-record-52de'
FAKE_PROVIDER_PRIVATE_NOTE = 'fake-provider-private-note-18bd'

LEAK_SENTINELS = (
    FAKE_API_KEY,
    FAKE_BASE_URL,
    'fake-user:fake-pass',
    FAKE_AUTH_HEADER,
    FAKE_PROVIDER_PRIVATE_RECORD,
    FAKE_PROVIDER_PRIVATE_NOTE,
)


def leak_hits(text):
    """返回 text 中出现的全部哨兵秘密；空列表表示无泄漏。"""
    if text is None:
        return []
    return [sentinel for sentinel in LEAK_SENTINELS if sentinel in str(text)]


def assert_no_leaks(text):
    hits = leak_hits(text)
    assert not hits, f'敏感信息泄漏: {hits} in {text!r}'


def fake_provider_request():
    """带假凭据请求头的假 httpx 请求对象（不发出任何网络请求）。"""
    return httpx.Request(
        'POST',
        FAKE_BASE_URL + '/chat/completions',
        headers={
            'Authorization': FAKE_AUTH_HEADER,
            'Content-Type': 'application/json',
        },
        json={'model': 'fake-model', 'messages': []},
    )


def make_401_error():
    """模拟 Provider 401：响应体回显了调用方使用的假 API Key。"""
    body = {'error': {
        'message': f'Incorrect API key provided: {FAKE_API_KEY}.',
        'type': 'invalid_request_error',
    }}
    response = httpx.Response(
        401,
        request=fake_provider_request(),
        headers={'Content-Type': 'application/json'},
        json=body,
    )
    return openai.AuthenticationError('invalid api key', response=response, body=body)


def make_429_error(retry_after='120'):
    """模拟 Provider 429；retry_after 可为合法秒数、非法字符串或 None（缺头）。"""
    headers = {}
    if retry_after is not None:
        headers['Retry-After'] = retry_after
    body = {'error': {
        'message': 'Rate limit reached for model fake-model',
        'type': 'rate_limit_error',
    }}
    response = httpx.Response(
        429,
        request=fake_provider_request(),
        headers=headers,
        json=body,
    )
    return openai.RateLimitError('rate limited', response=response, body=body)


def make_timeout_error():
    """模拟传输超时（无任何网络等待）。"""
    return openai.APITimeoutError(request=fake_provider_request())


def make_context_length_error():
    """模拟 400 上下文超长。"""
    body = {'error': {
        'message': (
            'This model\'s maximum context length is 131072 tokens; '
            'your request exceeded it.'
        ),
        'type': 'invalid_request_error',
    }}
    response = httpx.Response(
        400,
        request=fake_provider_request(),
        headers={'Content-Type': 'application/json'},
        json=body,
    )
    return openai.BadRequestError('context too long', response=response, body=body)


def make_provider_body_echo_error():
    """模拟异常消息里夹带 Provider 私密正文的极端情况。"""
    message = (
        'Provider response body: {\n'
        f'  "private_record": "{FAKE_PROVIDER_PRIVATE_RECORD}",\n'
        f'  "private_note": "{FAKE_PROVIDER_PRIVATE_NOTE}"\n'
        '}\n'
        f'Authorization: {FAKE_AUTH_HEADER}\n'
        f'base_url={FAKE_BASE_URL}'
    )
    return RuntimeError(message)


class ScriptedCompletions:
    """按脚本返回内容或抛出异常的假 completions 端点。"""

    def __init__(self, script):
        self._script = list(script)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if not self._script:
            raise AssertionError('假传输脚本已耗尽，存在计划外调用')
        step = self._script.pop(0)
        if isinstance(step, Exception):
            raise step
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=step))]
        )


class FakeOpenAIClient:
    """注入 ChatModel(client=...) 的假 OpenAI 客户端，全程无网络。"""

    def __init__(self, script):
        self.chat = SimpleNamespace(completions=ScriptedCompletions(script))

    @property
    def call_count(self):
        return len(self.chat.completions.calls)
