import json
from types import SimpleNamespace

import fakeredis
import pytest
from redis.exceptions import RedisError

from app.rate_limit import (
    RATE_LIMIT_MESSAGE,
    RATE_LIMIT_UNAVAILABLE_MESSAGE,
    RateLimiter,
    RateLimitRule,
    enforce_rate_limit,
    source_ip_from_request,
)


@pytest.fixture
def connection():
    return fakeredis.FakeStrictRedis()


def task_rules(session_limit=1, ip_limit=2, window=60):
    return {
        'task_create': {
            'session': RateLimitRule(session_limit, window),
            'ip': RateLimitRule(ip_limit, window),
        }
    }


def test_anonymous_session_creation_is_limited_by_source_ip(connection):
    limiter = RateLimiter(
        connection,
        rules={'session_create': {'ip': RateLimitRule(1, 60)}},
        clock=lambda: 0,
    )

    assert limiter.consume('session_create', source_ip='203.0.113.10').allowed
    denied = limiter.consume('session_create', source_ip='203.0.113.10')

    assert not denied.allowed
    assert denied.status_code == 429
    assert denied.retry_after == 60
    assert denied.headers == {'Retry-After': '60'}


def test_session_denial_does_not_partially_charge_ip_or_other_sessions(connection):
    limiter = RateLimiter(connection, rules=task_rules(), clock=lambda: 0)

    assert limiter.consume('task_create', 'session-a', '203.0.113.10').allowed
    session_denied = limiter.consume('task_create', 'session-a', '203.0.113.10')
    assert not session_denied.allowed

    # If the denied session-a request had charged IP, this request would fail.
    assert limiter.consume('task_create', 'session-b', '203.0.113.10').allowed
    ip_denied = limiter.consume('task_create', 'session-c', '203.0.113.10')
    assert not ip_denied.allowed
    assert ip_denied.retry_after == 60


def test_idempotent_network_retry_does_not_charge_session_or_ip_twice(connection):
    limiter = RateLimiter(connection, rules=task_rules(ip_limit=1))
    first = limiter.consume(
        'task_create',
        'session-a',
        '203.0.113.10',
        idempotency_key='request-123',
    )
    replay = limiter.consume(
        'task_create',
        'session-a',
        '203.0.113.10',
        idempotency_key='request-123',
    )

    assert first.allowed and not first.replayed
    assert replay.allowed and replay.replayed
    denied = limiter.consume(
        'task_create',
        'session-a',
        '203.0.113.10',
        idempotency_key='different-request',
    )
    assert not denied.allowed


def test_idempotency_replay_survives_window_boundary_without_new_charge(connection):
    now = [59.0]
    limiter = RateLimiter(
        connection,
        rules=task_rules(ip_limit=1),
        clock=lambda: now[0],
    )
    assert limiter.consume('task_create', 'a', 'ip', idempotency_key='same').allowed
    keys_before_replay = set(connection.keys('*'))

    now[0] = 60.0
    replay = limiter.consume('task_create', 'a', 'ip', idempotency_key='same')

    assert replay.allowed and replay.replayed
    assert set(connection.keys('*')) == keys_before_replay
    # A genuinely new operation is allowed in the new fixed window.
    assert limiter.consume('task_create', 'a', 'ip', idempotency_key='new').allowed


def test_same_client_key_cannot_replay_another_sessions_quota(connection):
    limiter = RateLimiter(connection, rules=task_rules(session_limit=2, ip_limit=2))
    assert limiter.consume('task_create', 'a', 'ip', idempotency_key='shared').allowed

    other = limiter.consume('task_create', 'b', 'ip', idempotency_key='shared')

    assert other.allowed
    assert not other.replayed


def test_fixed_window_boundary_and_retry_after_are_exact(connection):
    now = [59.2]
    limiter = RateLimiter(
        connection,
        rules=task_rules(ip_limit=10),
        clock=lambda: now[0],
    )

    assert limiter.consume('task_create', 'a', 'ip').allowed
    denied = limiter.consume('task_create', 'a', 'ip')
    assert denied.retry_after == 1

    now[0] = 60.0
    assert limiter.consume('task_create', 'a', 'ip').allowed
    now[0] = 119.0
    assert limiter.consume('task_create', 'a', 'ip').retry_after == 1
    now[0] = 120.0
    assert limiter.consume('task_create', 'a', 'ip').allowed


def test_forwarding_headers_are_ignored_at_http_boundary(connection):
    limiter = RateLimiter(
        connection,
        rules={'session_create': {'ip': RateLimitRule(1, 60)}},
    )
    request = SimpleNamespace(
        client=SimpleNamespace(host='203.0.113.20'),
        headers={
            'forwarded': 'for=198.51.100.1',
            'x-forwarded-for': '198.51.100.2',
            'x-real-ip': '198.51.100.3',
        },
    )

    assert source_ip_from_request(request) == '203.0.113.20'
    assert enforce_rate_limit(limiter, 'session_create', request).allowed
    with pytest.raises(Exception) as exc_info:
        enforce_rate_limit(limiter, 'session_create', request)
    assert exc_info.value.status_code == 429


def test_denial_contains_safe_public_detail_and_no_internal_diagnostics(connection):
    limiter = RateLimiter(connection, rules=task_rules(), clock=lambda: 0)
    limiter.consume('task_create', 'a', 'ip')

    error = limiter.consume('task_create', 'a', 'ip').as_http_exception()
    serialized = json.dumps(error.detail, ensure_ascii=False)

    assert error.status_code == 429
    assert error.headers == {'Retry-After': '60'}
    assert error.detail == {
        'code': 'rate_limited',
        'message': RATE_LIMIT_MESSAGE,
        'retry_after': 60,
    }
    assert 'traceback' not in serialized.lower()
    assert 'redis' not in serialized.lower()
    assert '/Users/' not in serialized


def test_redis_unavailable_fails_closed_with_safe_retry_information():
    secret = 'rate-limit-test-secret'

    class BrokenPipeline:
        def __enter__(self):
            raise RedisError(
                f'redis://:{secret}@private.internal/0 failed at /Users/private/server.py'
            )

        def __exit__(self, *args):
            return False

    class BrokenRedis:
        def pipeline(self):
            return BrokenPipeline()

    result = RateLimiter(BrokenRedis(), rules=task_rules()).consume('task_create', 'a', 'ip')
    serialized = json.dumps(result.detail, ensure_ascii=False)

    assert not result.allowed
    assert result.status_code == 503
    assert result.retry_after == 5
    assert result.headers == {'Retry-After': '5'}
    assert result.detail == {
        'code': 'rate_limit_unavailable',
        'message': RATE_LIMIT_UNAVAILABLE_MESSAGE,
        'retry_after': 5,
    }
    assert secret not in serialized
    assert 'private.internal' not in serialized
    assert '/Users/' not in serialized


def test_missing_redis_configuration_is_also_safe_unavailable():
    result = RateLimiter(redis_url='', rules=task_rules()).consume('task_create', 'a', 'ip')

    assert result.status_code == 503
    assert result.code == 'rate_limit_unavailable'


def test_model_and_retrieval_stages_have_independent_testable_policies(connection):
    rules = {
        'model': {
            'session': RateLimitRule(1, 60),
            'ip': RateLimitRule(2, 60),
        },
        'retrieval': {
            'session': RateLimitRule(1, 60),
            'ip': RateLimitRule(2, 60),
        },
    }
    limiter = RateLimiter(connection, rules=rules)

    assert limiter.consume_for_stage('search', 'a', 'ip').allowed
    assert not limiter.consume_for_stage('retrieval', 'a', 'ip').allowed
    assert limiter.consume_for_stage('analysis', 'a', 'ip').allowed
    assert not limiter.consume_for_stage('generate', 'a', 'ip').allowed
    with pytest.raises(ValueError, match='Unknown rate-limit stage'):
        limiter.consume_for_stage('missing', 'a', 'ip')


def test_oversized_cost_denies_without_creating_any_counter(connection):
    limiter = RateLimiter(connection, rules=task_rules(), clock=lambda: 0)

    denied = limiter.consume('task_create', 'a', 'ip', cost=2)

    assert not denied.allowed
    assert connection.dbsize() == 0


def test_invalid_idempotency_key_is_rejected_before_redis_write(connection):
    limiter = RateLimiter(connection, rules=task_rules(), clock=lambda: 0)

    with pytest.raises(ValueError, match='must not be empty'):
        limiter.consume('task_create', 'a', 'ip', idempotency_key='  ')
    assert connection.dbsize() == 0



def test_forwarded_ip_is_used_only_through_explicitly_trusted_proxy_layers():
    request = SimpleNamespace(
        client=SimpleNamespace(host='10.0.0.1'),
        headers={'x-forwarded-for': '203.0.113.50, 10.0.0.2'},
    )

    assert source_ip_from_request(request, ['10.0.0.0/8']) == '203.0.113.50'
    assert source_ip_from_request(request, []) == '10.0.0.1'

    direct = SimpleNamespace(
        client=SimpleNamespace(host='198.51.100.20'),
        headers={'x-forwarded-for': '203.0.113.50'},
    )
    assert source_ip_from_request(direct, ['10.0.0.0/8']) == '198.51.100.20'


def test_malformed_forwarding_header_falls_back_to_trusted_socket_peer():
    request = SimpleNamespace(
        client=SimpleNamespace(host='10.0.0.1'),
        headers={'x-forwarded-for': 'not-an-ip'},
    )

    assert source_ip_from_request(request, ['10.0.0.0/8']) == '10.0.0.1'


def test_same_session_retry_changing_ip_still_consumes_quota_once(connection):
    limiter = RateLimiter(connection, rules=task_rules(ip_limit=2), clock=lambda: 0)

    first = limiter.consume('task_create', 'session-a', 'ip-one', idempotency_key='same')
    replay = limiter.consume('task_create', 'session-a', 'ip-two', idempotency_key='same')

    assert first.allowed
    assert replay.allowed and replay.replayed
    assert not limiter.consume(
        'task_create', 'session-a', 'ip-two', idempotency_key='different'
    ).allowed


def test_multi_proxy_chain_skips_only_explicitly_trusted_nodes():
    request = SimpleNamespace(
        client=SimpleNamespace(host='10.0.0.1'),
        headers={'x-forwarded-for': '198.51.100.8, 172.16.0.20, 10.0.0.2'},
    )

    assert source_ip_from_request(request, ['10.0.0.0/8']) == '172.16.0.20'
    assert source_ip_from_request(
        request,
        ['10.0.0.0/8', '172.16.0.0/16'],
    ) == '198.51.100.8'


@pytest.mark.parametrize(
    ('forwarded', 'expected'),
    [
        ('', '10.0.0.1'),
        ('   ,  , ', '10.0.0.1'),
        ('  203.0.113.50  ,  10.0.0.2  , ', '203.0.113.50'),
        ('203.0.113.50, not-an-ip, 10.0.0.2', '10.0.0.1'),
    ],
)
def test_empty_whitespace_and_invalid_multi_hop_headers_fail_closed(forwarded, expected):
    request = SimpleNamespace(
        client=SimpleNamespace(host='10.0.0.1'),
        headers={'x-forwarded-for': forwarded},
    )

    assert source_ip_from_request(request, ['10.0.0.0/8']) == expected


@pytest.mark.parametrize(
    ('peer', 'forwarded', 'trusted', 'expected'),
    [
        ('203.0.113.10', '198.51.100.20', '203.0.113.0/24', '198.51.100.20'),
        ('2001:db8::10', '2001:db8:1::20', '2001:db8::/32', '2001:db8:1::20'),
        ('::ffff:10.0.0.1', '::ffff:203.0.113.50', '::ffff:10.0.0.1', '::ffff:cb00:7132'),
        ('::ffff:10.0.0.1', '203.0.113.50', '10.0.0.0/8', '::ffff:a00:1'),
    ],
)
def test_ipv4_ipv6_and_ipv4_mapped_ipv6_have_explicit_trust_behavior(
    peer,
    forwarded,
    trusted,
    expected,
):
    request = SimpleNamespace(
        client=SimpleNamespace(host=peer),
        headers={'x-forwarded-for': forwarded},
    )

    import ipaddress
    assert ipaddress.ip_address(source_ip_from_request(request, [trusted])) == ipaddress.ip_address(expected)


def test_invalid_trusted_proxy_configuration_is_not_silently_ignored(monkeypatch):
    monkeypatch.setenv(
        'TRUSTED_PROXY_IPS',
        '10.0.0.0/8, not-a-network, 0.0.0.0/0',
    )
    request = SimpleNamespace(
        client=SimpleNamespace(host='10.0.0.1'),
        headers={'x-forwarded-for': '203.0.113.50'},
    )

    with pytest.raises(ValueError):
        source_ip_from_request(request)
    with pytest.raises(ValueError):
        RateLimiter(redis_url='', trusted_proxies=['0.0.0.0/0', 'not-a-network'])
