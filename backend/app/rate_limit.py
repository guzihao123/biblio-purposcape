"""Atomic, identity-aware rate limits for public anonymous access."""

import hashlib
import ipaddress
import math
import os
import time
from dataclasses import dataclass
from functools import lru_cache

import redis
from redis.exceptions import RedisError, WatchError

from app.config import get_settings


RATE_LIMIT_MESSAGE = '请求过于频繁，请稍后重试。'
RATE_LIMIT_UNAVAILABLE_MESSAGE = '服务暂时不可用，请稍后重试。'


@dataclass(frozen=True)
class RateLimitRule:
    """A fixed-window allowance for one operation and identity dimension."""

    limit: int
    window_seconds: int

    def __post_init__(self):
        if isinstance(self.limit, bool) or not isinstance(self.limit, int) or self.limit < 1:
            raise ValueError('Rate-limit allowance must be a positive integer')
        if (
            isinstance(self.window_seconds, bool)
            or not isinstance(self.window_seconds, int)
            or self.window_seconds < 1
        ):
            raise ValueError('Rate-limit window must be a positive integer')


@dataclass(frozen=True)
class RateLimitResult:
    """A safe result that can be returned directly at an HTTP boundary."""

    allowed: bool
    code: str = 'ok'
    message: str = ''
    status_code: int = 200
    retry_after: int = 0
    replayed: bool = False

    @property
    def headers(self):
        if self.allowed or self.retry_after < 1:
            return {}
        return {'Retry-After': str(self.retry_after)}

    @property
    def detail(self):
        if self.allowed:
            return None
        return {
            'code': self.code,
            'message': self.message,
            'retry_after': self.retry_after,
        }

    def as_http_exception(self):
        if self.allowed:
            return None
        from fastapi import HTTPException

        return HTTPException(
            status_code=self.status_code,
            detail=self.detail,
            headers=self.headers,
        )

    def raise_if_denied(self):
        if not self.allowed:
            raise self.as_http_exception()


# Conservative defaults; tests and deployments can inject explicit policies.
DEFAULT_RULES = {
    'session_create': {
        'ip': RateLimitRule(limit=10, window_seconds=3600),
    },
    'task_create': {
        'session': RateLimitRule(limit=3, window_seconds=86400),
        'ip': RateLimitRule(limit=30, window_seconds=86400),
    },
    'model': {
        'session': RateLimitRule(limit=30, window_seconds=86400),
        'ip': RateLimitRule(limit=120, window_seconds=86400),
    },
    'retrieval': {
        'session': RateLimitRule(limit=10, window_seconds=3600),
        'ip': RateLimitRule(limit=60, window_seconds=3600),
    },
}

_OPERATION_ALIASES = {
    'anonymous_session': 'session_create',
    'session': 'session_create',
    'task': 'task_create',
}
_RETRIEVAL_STAGES = {'search', 'retrieve', 'retrieval', 'fulltext'}
_MODEL_STAGES = {
    'analysis',
    'classify',
    'classification',
    'generate',
    'generation',
    'writing',
    'delivery',
    'model',
}


def normalize_idempotency_key(value):
    if value is None:
        return None
    normalized = str(value).strip()
    if not normalized:
        raise ValueError('Idempotency key must not be empty')
    if len(normalized) > 255:
        raise ValueError('Idempotency key is too long')
    return normalized


def _trusted_networks(values):
    if values is None:
        values = os.environ.get('TRUSTED_PROXY_IPS', '')
    if isinstance(values, str):
        values = values.split(',')
    networks = []
    for value in values:
        normalized = str(value).strip()
        if normalized:
            networks.append(ipaddress.ip_network(normalized, strict=False))
    return tuple(networks)


def _is_trusted(address, networks):
    return any(address in network for network in networks)


def source_ip_from_request(request, trusted_proxies=None):
    """Resolve the peer, using forwarding headers only from configured proxies."""
    client = getattr(request, 'client', None)
    host = getattr(client, 'host', '') if client is not None else ''
    try:
        peer = ipaddress.ip_address(host)
    except ValueError:
        return str(host or 'unknown')[:128]

    networks = _trusted_networks(trusted_proxies)
    if not networks or not _is_trusted(peer, networks):
        return peer.compressed

    forwarded = getattr(request, 'headers', {}).get('x-forwarded-for', '')
    parts = [part.strip() for part in forwarded.split(',') if part.strip()]
    try:
        chain = [ipaddress.ip_address(part) for part in parts]
    except ValueError:
        return peer.compressed

    # Walk from the immediate proxy towards the client, skipping only proxies
    # explicitly configured by the server. Direct visitors cannot opt into this.
    for address in reversed(chain):
        if not _is_trusted(address, networks):
            return address.compressed
    return chain[0].compressed if chain else peer.compressed


def _digest(value):
    return hashlib.sha256(str(value).encode('utf-8')).hexdigest()


def _retry_after(now, window_seconds):
    remaining = window_seconds - (now % window_seconds)
    return max(1, int(math.ceil(remaining)))


class RateLimiter:
    """Redis fixed windows with atomic all-dimension accounting."""

    def __init__(
        self,
        connection=None,
        redis_url=None,
        rules=None,
        clock=None,
        idempotency_ttl=86400,
        unavailable_retry_after=5,
        contention_retries=3,
        trusted_proxies=None,
    ):
        self.rules = rules or DEFAULT_RULES
        self.clock = clock or time.time
        self.idempotency_ttl = int(idempotency_ttl)
        self.unavailable_retry_after = max(1, int(unavailable_retry_after))
        self.contention_retries = max(1, int(contention_retries))
        self.trusted_proxies = _trusted_networks(trusted_proxies)
        if self.idempotency_ttl < 1:
            raise ValueError('Idempotency TTL must be positive')

        self.connection = connection
        if self.connection is None:
            url = redis_url if redis_url is not None else get_settings().redis_url
            if url:
                self.connection = redis.from_url(
                    url,
                    socket_connect_timeout=1.0,
                    socket_timeout=1.0,
                )

    def source_ip(self, request):
        return source_ip_from_request(request, self.trusted_proxies)

    def _operation(self, operation):
        normalized = _OPERATION_ALIASES.get(operation, operation)
        if normalized not in self.rules:
            raise ValueError('Unknown rate-limit operation')
        return normalized

    def _counter_key(self, operation, dimension, identity, rule, now):
        bucket = int(now // rule.window_seconds)
        return ':'.join(
            (
                'public-rate-limit',
                'v1',
                operation,
                dimension,
                _digest(identity),
                str(rule.window_seconds),
                str(bucket),
            )
        )

    def _idempotency_key(self, operation, session_id, source_ip, key):
        normalized = normalize_idempotency_key(key)
        if normalized is None:
            return None
        # A session retry remains the same logical request even if its IP changes.
        identity = (
            'session\x00' + str(session_id)
            if session_id is not None
            else 'ip\x00' + str(source_ip or '')
        )
        scope = '\x00'.join((operation, identity, normalized))
        return 'public-rate-limit:v1:idempotency:' + _digest(scope)

    def _unavailable(self):
        return RateLimitResult(
            allowed=False,
            code='rate_limit_unavailable',
            message=RATE_LIMIT_UNAVAILABLE_MESSAGE,
            status_code=503,
            retry_after=self.unavailable_retry_after,
        )

    def consume(
        self,
        operation,
        session_id=None,
        source_ip=None,
        idempotency_key=None,
        cost=1,
    ):
        """Consume all applicable identity quotas or consume none of them."""
        operation = self._operation(operation)
        if isinstance(cost, bool) or not isinstance(cost, int) or cost < 1:
            raise ValueError('Rate-limit cost must be a positive integer')

        configured = self.rules[operation]
        identities = {}
        if session_id is not None and 'session' in configured:
            identities['session'] = str(session_id)
        if source_ip is not None and 'ip' in configured:
            identities['ip'] = str(source_ip)
        if not identities:
            raise ValueError('A configured session or source IP identity is required')

        now = float(self.clock())
        keys = []
        limits = []
        windows = []
        for dimension, identity in identities.items():
            rule = configured[dimension]
            keys.append(self._counter_key(operation, dimension, identity, rule, now))
            limits.append(rule.limit)
            windows.append(rule.window_seconds)
        idempotency_key = self._idempotency_key(
            operation, session_id, source_ip, idempotency_key
        )

        if self.connection is None:
            return self._unavailable()

        try:
            return self._consume_atomic(
                keys,
                limits,
                windows,
                now,
                cost,
                idempotency_key,
            )
        except (RedisError, OSError, ValueError):
            return self._unavailable()

    def _consume_atomic(self, keys, limits, windows, now, cost, idempotency_key):
        watch_keys = list(keys)
        if idempotency_key is not None:
            watch_keys.append(idempotency_key)

        with self.connection.pipeline() as pipeline:
            for _ in range(self.contention_retries):
                try:
                    pipeline.watch(*watch_keys)
                    if idempotency_key is not None and pipeline.get(idempotency_key):
                        pipeline.unwatch()
                        return RateLimitResult(allowed=True, replayed=True)

                    current = [int(value or 0) for value in pipeline.mget(keys)]
                    retry_after = 0
                    for index, used in enumerate(current):
                        if used + cost > limits[index]:
                            retry_after = max(
                                retry_after,
                                _retry_after(now, windows[index]),
                            )
                    if retry_after:
                        pipeline.unwatch()
                        return RateLimitResult(
                            allowed=False,
                            code='rate_limited',
                            message=RATE_LIMIT_MESSAGE,
                            status_code=429,
                            retry_after=retry_after,
                        )

                    pipeline.multi()
                    for index, used in enumerate(current):
                        if used == 0:
                            pipeline.set(keys[index], cost, ex=windows[index])
                        else:
                            pipeline.incrby(keys[index], cost)
                    if idempotency_key is not None:
                        pipeline.set(idempotency_key, '1', ex=self.idempotency_ttl)
                    pipeline.execute()
                    return RateLimitResult(allowed=True)
                except WatchError:
                    pipeline.reset()

        return self._unavailable()

    def consume_for_stage(
        self,
        stage,
        session_id=None,
        source_ip=None,
        idempotency_key=None,
        cost=1,
    ):
        if stage in _RETRIEVAL_STAGES:
            operation = 'retrieval'
        elif stage in _MODEL_STAGES:
            operation = 'model'
        else:
            raise ValueError('Unknown rate-limit stage')
        return self.consume(
            operation,
            session_id=session_id,
            source_ip=source_ip,
            idempotency_key=idempotency_key,
            cost=cost,
        )


@lru_cache
def get_rate_limiter():
    """Shared application/worker dependency; tests may override or clear it."""
    return RateLimiter()


def enforce_rate_limit(
    limiter,
    operation,
    request,
    session_id=None,
    idempotency_key=None,
    cost=1,
):
    result = limiter.consume(
        operation,
        session_id=session_id,
        source_ip=limiter.source_ip(request),
        idempotency_key=idempotency_key,
        cost=cost,
    )
    result.raise_if_denied()
    return result
