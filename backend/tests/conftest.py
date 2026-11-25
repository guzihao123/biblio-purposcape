import fakeredis
import pytest

from app.main import app
from app.rate_limit import RateLimiter, get_rate_limiter


@pytest.fixture(autouse=True)
def isolated_rate_limiter(monkeypatch):
    """Exercise real route/worker wiring without requiring a local Redis server."""
    limiter = RateLimiter(connection=fakeredis.FakeStrictRedis())
    app.dependency_overrides[get_rate_limiter] = lambda: limiter
    monkeypatch.setattr('app.queueing.get_rate_limiter', lambda: limiter)
    yield limiter
    app.dependency_overrides.pop(get_rate_limiter, None)
