"""离线异常矩阵 conftest：假传输、假密钥、无网络、无真实环境变量。

整个测试会话期间删除 QWEN_* 环境变量，保证：
1. 测试绝不读取真实模型凭据；
2. 红色化扫描不会被真实环境值干扰；
3. ChatModel 在测试中始终通过 client= 注入假传输。
"""

import os
import sys
from pathlib import Path

import fakeredis
import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[3] / 'backend'
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.rate_limit import RateLimiter, RateLimitRule  # noqa: E402


@pytest.fixture(scope='session', autouse=True)
def no_real_model_environment():
    removed = {name: os.environ.pop(name, None) for name in (
        'QWEN_API_KEY', 'QWEN_BASE_URL', 'QWEN_MODEL',
    )}
    yield
    for name, value in removed.items():
        if value is not None:
            os.environ[name] = value


@pytest.fixture(autouse=True)
def isolated_limiter(monkeypatch):
    """本地配额限流器（内存 fakeredis），隔离测试间配额计数。

    rules 只含 run_stage 会消费的 retrieval/model 操作且额度宽松，
    不影响各失败用例；需要触发配额拒绝的用例自行替换 rules。
    """
    limiter = RateLimiter(
        connection=fakeredis.FakeStrictRedis(),
        rules={
            'retrieval': {'ip': RateLimitRule(1000, 3600)},
            'model': {'session': RateLimitRule(1000, 3600), 'ip': RateLimitRule(1000, 3600)},
        },
    )
    monkeypatch.setattr('app.queueing.get_rate_limiter', lambda: limiter)
    return limiter
