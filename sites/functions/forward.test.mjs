import assert from 'node:assert/strict';
const { default: nodeTest } = await import('node:test');
const test = globalThis.Deno?.test?.bind(globalThis.Deno) ?? nodeTest;

let handler;
const realDeno = Object.getOwnPropertyDescriptor(globalThis, 'Deno');
const mockedDeno = {
  env: { get: (name) => name === 'PYTHON_API_ORIGIN' ? 'https://python.example' : undefined },
  serve: (callback) => { handler = callback; },
};
function installDenoMock() {
  Object.defineProperty(globalThis, 'Deno', { configurable: true, value: mockedDeno });
}
function restoreDeno() {
  if (realDeno === undefined) delete globalThis.Deno;
  else Object.defineProperty(globalThis, 'Deno', realDeno);
}
installDenoMock();

const upstreamCalls = [];
globalThis.fetch = async (url, init = {}) => {
  upstreamCalls.push({ url, init });
  if (url === 'https://python.example/api/session') {
    return new Response(JSON.stringify({ session_id: 'public-session' }), {
      status: 201,
      headers: {
        'content-type': 'application/json',
        'set-cookie': 'invite_session=signed-public-cookie; HttpOnly; Secure; SameSite=lax',
      },
    });
  }
  if (url === 'https://python.example/api/tasks') {
    const key = new Headers(init.headers).get('idempotency-key');
    if (key !== null && (!key.trim() || key.trim().length > 255)) {
      return new Response(JSON.stringify({ error: 'invalid_idempotency_key' }), {
        status: 422,
        headers: { 'content-type': 'application/json' },
      });
    }
    return new Response(JSON.stringify({ id: 'task-1' }), {
      status: 201,
      headers: {
        'content-type': 'application/json',
        'cache-control': 'private, no-store',
        'set-cookie': 'invite_session=sec02-refreshed-cookie; HttpOnly; Secure',
        'x-upstream-private': 'do-not-forward',
      },
    });
  }
  if (url.startsWith('https://python.example/api/tasks/')) {
    const cookie = init.headers?.cookie || '';
    return new Response(JSON.stringify({ id: 'task-1', cookie_seen: Boolean(cookie) }), {
      status: cookie ? 200 : 401,
      headers: { 'content-type': 'application/json' },
    });
  }
  throw new Error(`unexpected upstream: ${url}`);
};

try {
  await import('./index.ts');
} finally {
  restoreDeno();
}
const serveHandler = handler;
handler = (request) => {
  installDenoMock();
  return Promise.resolve().then(() => serveHandler(request)).finally(restoreDeno);
};

async function postTask(headers = {}) {
  const response = await handler(new Request('https://site.example/functions/v1/app/tasks', {
    method: 'POST',
    headers,
  }));
  return { response, upstream: upstreamCalls.at(-1) };
}

function upstreamKey(upstream) {
  return new Headers(upstream.init.headers).get('idempotency-key');
}

test('session forwarding preserves Set-Cookie and visitor metadata', async () => {
  const request = new Request('https://site.example/functions/v1/app?action=session', {
    method: 'POST',
    headers: { 'user-agent': 'competition-agent', 'x-forwarded-for': '203.0.113.10' },
  });
  const response = await handler(request);
  assert.equal(response.status, 201);
  assert.match(response.headers.get('set-cookie'), /invite_session=signed-public-cookie/);
  const upstream = upstreamCalls.at(-1);
  assert.equal(upstream.init.body, '{}');
  assert.equal(upstream.init.headers['user-agent'], 'competition-agent');
  assert.equal(upstream.init.headers['x-forwarded-for'], '203.0.113.10');
});

test('task forwarding sends the public session cookie for owner checks', async () => {
  const request = new Request('https://site.example/functions/v1/app?action=task&id=123e4567-e89b-12d3-a456-426614174000', {
    headers: { cookie: 'invite_session=signed-public-cookie' },
  });
  const response = await handler(request);
  assert.equal(response.status, 200);
  const payload = await response.json();
  assert.equal(payload.cookie_seen, true);
  assert.equal(upstreamCalls.at(-1).init.headers.cookie, 'invite_session=signed-public-cookie');
});

test('task creation forwards first and same-key retry values unchanged', async () => {
  const key = 'sec02-test-retry-key';
  const first = await postTask({ 'Idempotency-Key': key });
  const retry = await postTask({ 'Idempotency-Key': key });
  assert.equal(first.response.status, 201);
  assert.equal(retry.response.status, 201);
  for (const upstream of [first.upstream, retry.upstream]) {
    assert.equal(upstream.url, 'https://python.example/api/tasks');
    assert.ok(upstreamKey(upstream) === key, 'forwarded key must equal the client key without logging it');
  }
});

test('different idempotency keys stay isolated across requests', async () => {
  const firstKey = 'sec02-test-key-a';
  const secondKey = 'sec02-test-key-b';
  const first = await postTask({ 'Idempotency-Key': firstKey });
  const second = await postTask({ 'Idempotency-Key': secondKey });
  assert.ok(upstreamKey(first.upstream) === firstKey, 'first request must retain its own key');
  assert.ok(upstreamKey(second.upstream) === secondKey, 'second request must retain its own key');
  assert.ok(upstreamKey(first.upstream) !== upstreamKey(second.upstream), 'different keys must not be mixed');
});

test('mixed-case Idempotency-Key spelling is read case-insensitively', async () => {
  const key = 'sec02-test-mixed-case-header';
  const headers = new Headers();
  headers.set('iDeMpOtEnCy-KeY', key);
  const { response, upstream } = await postTask(headers);
  assert.equal(response.status, 201);
  assert.ok(upstreamKey(upstream) === key, 'mixed-case input must preserve the original value');
});

test('missing idempotency key stays absent and creates no second-layer key', async () => {
  const { response, upstream } = await postTask();
  assert.equal(response.status, 201);
  assert.equal(upstream.url, 'https://python.example/api/tasks');
  assert.equal(new Headers(upstream.init.headers).has('idempotency-key'), false);
});

test('empty idempotency key reaches upstream validation without replacement', async () => {
  const { response, upstream } = await postTask({ 'Idempotency-Key': '' });
  assert.equal(response.status, 422);
  assert.equal(new Headers(upstream.init.headers).has('idempotency-key'), true);
  assert.equal(upstreamKey(upstream), '');
  assert.deepEqual(await response.json(), { error: 'invalid_idempotency_key' });
});

test('overlong idempotency key is neither dropped nor truncated before upstream validation', async () => {
  const key = 'K'.repeat(256);
  const { response, upstream } = await postTask({ 'Idempotency-Key': key });
  assert.equal(response.status, 422);
  assert.equal(upstreamKey(upstream)?.length, 256);
  assert.ok(upstreamKey(upstream) === key, 'overlong value must reach upstream unchanged');
  const errorBody = await response.text();
  assert.equal(errorBody.includes(key), false, 'upstream error body must not echo the key');
});

test('malformed header values are rejected before any upstream forwarding', () => {
  const before = upstreamCalls.length;
  for (const value of ['bad\nkey', 'bad\rkey', 'bad\0key']) {
    assert.throws(() => new Request('https://site.example/functions/v1/app/tasks', {
      method: 'POST',
      headers: { 'Idempotency-Key': value },
    }), TypeError);
  }
  assert.equal(upstreamCalls.length, before);
});

test('idempotency forwarding preserves token and response header allowlists', async () => {
  const { response, upstream } = await postTask({
    'Idempotency-Key': 'sec02-test-header-policy-key',
    cookie: 'invite_session=sec02-test-cookie',
    'x-admin-token': 'sec02-test-admin-token',
    'x-worker-token': 'sec02-test-worker-token',
  });
  const headers = new Headers(upstream.init.headers);
  assert.equal(headers.get('cookie'), 'invite_session=sec02-test-cookie');
  assert.equal(headers.get('x-admin-token'), 'sec02-test-admin-token');
  assert.equal(headers.has('x-worker-token'), false);
  assert.equal(response.headers.get('content-type'), 'application/json');
  assert.equal(response.headers.get('cache-control'), 'private, no-store');
  assert.match(response.headers.get('set-cookie'), /invite_session=sec02-refreshed-cookie/);
  assert.equal(response.headers.has('x-upstream-private'), false);
  assert.equal(response.headers.has('idempotency-key'), false);
});

test('answer bodies over 64 KiB are rejected without calling Python', async () => {
  const before = upstreamCalls.length;
  const response = await handler(new Request(
    'https://site.example/functions/v1/app/tasks/123e4567-e89b-12d3-a456-426614174000/answers/direction',
    { method: 'POST', headers: { cookie: 'invite_session=signed-public-cookie' }, body: 'x'.repeat(64 * 1024 + 1) },
  ));
  assert.equal(response.status, 413);
  assert.deepEqual(await response.json(), { error: 'answer_body_too_large' });
  assert.equal(upstreamCalls.length, before);
});

test('a 64 KiB answer body is forwarded unchanged', async () => {
  const body = 'x'.repeat(64 * 1024);
  const before = upstreamCalls.length;
  const response = await handler(new Request(
    'https://site.example/functions/v1/app/tasks/123e4567-e89b-12d3-a456-426614174000/answers/direction',
    { method: 'POST', headers: { cookie: 'invite_session=signed-public-cookie' }, body },
  ));
  assert.equal(response.status, 200);
  assert.equal(upstreamCalls.length, before + 1);
  const upstream = upstreamCalls.at(-1);
  assert.equal(upstream.url, 'https://python.example/api/tasks/123e4567-e89b-12d3-a456-426614174000/answers/direction');
  assert.equal(new TextDecoder().decode(upstream.init.body), body);
});
