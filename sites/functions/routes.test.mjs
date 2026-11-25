import assert from 'node:assert/strict';
const { default: nodeTest } = await import('node:test');
const test = globalThis.Deno?.test?.bind(globalThis.Deno) ?? nodeTest;

const TASK_ID = '123e4567-e89b-12d3-a456-426614174000';
const SESSION_ID = '123e4567-e89b-12d3-a456-426614174001';
const UNKNOWN_SESSION_ID = '123e4567-e89b-12d3-a456-426614174002';
const ADMIN_TOKEN = 'route-test-admin-token';
let handler;
const realDeno = Object.getOwnPropertyDescriptor(globalThis, 'Deno');
const mockedDeno = {
  env: {
    get: (name) => ({
      PYTHON_API_ORIGIN: 'https://python.example',
      WORKER_SHARED_SECRET: 'worker-test-secret',
    })[name],
  },
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
  if (url === `https://python.example/api/tasks/${TASK_ID}/answers/mode`) {
    return new Response(JSON.stringify({ next_card: 'terms' }), {
      status: 200,
      headers: { 'content-type': 'application/json' },
    });
  }
  if (url === `https://python.example/api/tasks/${TASK_ID}/artifacts/report.docx?signature=signed`) {
    return new Response(new Uint8Array([80, 75, 3, 4]), {
      status: 200,
      headers: {
        'content-type': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        'content-disposition': 'attachment; filename="report.docx"',
        'cache-control': 'private, no-store',
      },
    });
  }
  const revoke = url.match(/^https:\/\/python\.example\/api\/admin\/sessions\/([0-9a-f-]{36})\/revoke$/i);
  if (revoke) {
    const headers = new Headers(init.headers);
    if (headers.get('x-admin-token') !== ADMIN_TOKEN) {
      return new Response(JSON.stringify({ error: 'admin_unauthorized' }), {
        status: 403,
        headers: { 'content-type': 'application/json' },
      });
    }
    if (revoke[1] === UNKNOWN_SESSION_ID) {
      return new Response(JSON.stringify({ error: 'session_not_found' }), {
        status: 404,
        headers: { 'content-type': 'application/json' },
      });
    }
    return new Response(JSON.stringify({ session_id: revoke[1], revoked: true }), {
      status: 200,
      headers: {
        'content-type': 'application/json',
        'cache-control': 'no-store',
        'x-upstream-private': 'do-not-forward',
      },
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

test('answer subroute forwards the exact answer JSON and session cookie', async () => {
  const response = await handler(new Request(`https://site.example/functions/v1/app/tasks/${TASK_ID}/answers/mode`, {
    method: 'POST',
    headers: { cookie: 'invite_session=signed', 'content-type': 'application/json' },
    body: JSON.stringify({ value: { mode: 'A' } }),
  }));
  assert.equal(response.status, 200);
  assert.deepEqual(await response.json(), { next_card: 'terms' });
  const upstream = upstreamCalls.at(-1);
  assert.equal(upstream.init.headers.cookie, 'invite_session=signed');
  assert.equal(new TextDecoder().decode(upstream.init.body), JSON.stringify({ value: { mode: 'A' } }));
});

test('artifact subroute streams Word bytes and preserves approved download headers', async () => {
  const response = await handler(new Request(`https://site.example/functions/v1/app/tasks/${TASK_ID}/artifacts/report.docx?signature=signed`, {
    headers: { cookie: 'invite_session=signed' },
  }));
  assert.equal(response.status, 200);
  assert.equal(response.headers.get('content-disposition'), 'attachment; filename="report.docx"');
  assert.equal(response.headers.get('cache-control'), 'private, no-store');
  assert.deepEqual(new Uint8Array(await response.arrayBuffer()), new Uint8Array([80, 75, 3, 4]));
});

test('worker storage route rejects a wrong token and round-trips bytes through the import-mapped local stub', async () => {
  const runningInNode = typeof Deno === 'undefined';
  if (runningInNode) {
    const { storage } = await import('../../dev/storage-stub.mjs');
    globalThis.__LANDSCAPE_STORAGE__ = storage;
  }
  try {
    const path = `/functions/v1/app/internal/artifacts/${TASK_ID}/report.docx`;
    const denied = await handler(new Request(`https://site.example${path}`, {
      method: 'PUT',
      headers: { 'x-worker-token': 'wrong' },
      body: 'bad',
    }));
    assert.equal(denied.status, 403);

    const uploaded = await handler(new Request(`https://site.example${path}`, {
      method: 'PUT',
      headers: { 'x-worker-token': 'worker-test-secret', 'content-type': 'application/test' },
      body: new Uint8Array([80, 75, 3, 4]),
    }));
    assert.equal(uploaded.status, 201);
    assert.deepEqual(await uploaded.json(), { ok: true, name: 'report.docx', size: 4 });

    const listing = await handler(new Request(`https://site.example/functions/v1/app/internal/artifacts/${TASK_ID}`, {
      headers: { 'x-worker-token': 'worker-test-secret' },
    }));
    assert.equal(listing.status, 200);
    assert.deepEqual(await listing.json(), {
      artifacts: [{ name: 'report.docx', size: 4 }],
    });

    const downloaded = await handler(new Request(`https://site.example${path}`, {
      headers: { 'x-worker-token': 'worker-test-secret' },
    }));
    assert.equal(downloaded.status, 200);
    assert.equal(downloaded.headers.get('content-type'), 'application/test');
    assert.deepEqual(new Uint8Array(await downloaded.arrayBuffer()), new Uint8Array([80, 75, 3, 4]));

    const checksum = await handler(new Request(`https://site.example/functions/v1/app/internal/artifact-checksums/${TASK_ID}/report.docx`, {
      headers: { 'x-worker-token': 'worker-test-secret' },
    }));
    assert.equal(checksum.status, 200);
    const expectedDigest = await crypto.subtle.digest('SHA-256', new Uint8Array([80, 75, 3, 4]));
    const expectedHex = Array.from(new Uint8Array(expectedDigest), (byte) => byte.toString(16).padStart(2, '0')).join('');
    assert.equal(await checksum.text(), expectedHex);

    const mismatched = await handler(new Request(`https://site.example${path}`, {
      method: 'PUT',
      headers: {
        'x-worker-token': 'worker-test-secret',
        'x-artifact-sha256': '0'.repeat(64),
      },
      body: new Uint8Array([80, 75, 3, 4]),
    }));
    assert.equal(mismatched.status, 422);
  } finally {
    if (runningInNode) delete globalThis.__LANDSCAPE_STORAGE__;
  }
});

function revoke(sessionId = SESSION_ID, headers = {}, method = 'POST') {
  return handler(new Request(`https://site.example/functions/v1/app/admin/sessions/${sessionId}/revoke`, {
    method,
    headers,
  }));
}

test('admin revoke forwards only its token and preserves safe JSON and response headers', async () => {
  const response = await revoke(SESSION_ID, {
    'x-admin-token': ADMIN_TOKEN,
    cookie: 'invite_session=signed-anonymous-cookie',
    'x-worker-token': 'worker-test-secret',
    'user-agent': 'private-user-agent',
    'x-forwarded-for': '203.0.113.44',
    'idempotency-key': 'revoke-idempotency-secret',
    'x-signature': 'artifact-signature',
  });
  assert.equal(response.status, 200);
  assert.equal(response.headers.get('content-type'), 'application/json');
  assert.equal(response.headers.get('cache-control'), 'no-store');
  assert.equal(response.headers.has('x-upstream-private'), false);
  const responseText = await response.text();
  assert.deepEqual(JSON.parse(responseText), { session_id: SESSION_ID, revoked: true });

  const upstream = upstreamCalls.at(-1);
  assert.equal(upstream.url, `https://python.example/api/admin/sessions/${SESSION_ID}/revoke`);
  assert.equal(upstream.init.method, 'POST');
  assert.equal(upstream.init.body, '{}');
  const headers = new Headers(upstream.init.headers);
  assert.equal(headers.get('x-admin-token'), ADMIN_TOKEN);
  assert.deepEqual([...headers.keys()].sort(), ['content-type', 'x-admin-token']);

  for (const secret of [
    ADMIN_TOKEN,
    'signed-anonymous-cookie',
    'worker-test-secret',
    'private-user-agent',
    '203.0.113.44',
    'revoke-idempotency-secret',
    'artifact-signature',
  ]) {
    assert.equal(responseText.includes(secret), false, `response must not echo ${secret}`);
  }
});

test('missing or wrong admin tokens, anonymous cookies, and worker tokens cannot revoke', async () => {
  const cases = [
    ['missing token', {}, ''],
    ['wrong token', { 'x-admin-token': 'wrong-admin-token' }, 'wrong-admin-token'],
    ['anonymous cookie', { cookie: 'invite_session=ordinary-anonymous-cookie' }, 'ordinary-anonymous-cookie'],
    ['worker token', { 'x-worker-token': 'worker-test-secret' }, 'worker-test-secret'],
  ];
  for (const [, requestHeaders, secret] of cases) {
    const response = await revoke(SESSION_ID, requestHeaders);
    assert.equal(response.status, 403);
    const responseText = await response.text();
    assert.deepEqual(JSON.parse(responseText), { error: 'admin_unauthorized' });
    if (secret) assert.equal(responseText.includes(secret), false);
    const headers = new Headers(upstreamCalls.at(-1).init.headers);
    assert.notEqual(headers.get('x-admin-token'), ADMIN_TOKEN);
    assert.equal(headers.has('cookie'), false);
    assert.equal(headers.has('x-worker-token'), false);
  }
});

test('admin revoke preserves an upstream 404 without exposing request metadata', async () => {
  const response = await revoke(UNKNOWN_SESSION_ID, {
    'x-admin-token': ADMIN_TOKEN,
    cookie: 'invite_session=unknown-session-cookie',
  });
  assert.equal(response.status, 404);
  const responseText = await response.text();
  assert.deepEqual(JSON.parse(responseText), { error: 'session_not_found' });
  assert.equal(responseText.includes(ADMIN_TOKEN), false);
  assert.equal(responseText.includes('unknown-session-cookie'), false);
});

test('repeated admin revokes remain upstream-idempotent and never call a worker route', async () => {
  const before = upstreamCalls.length;
  const first = await revoke(SESSION_ID, { 'x-admin-token': ADMIN_TOKEN });
  const second = await revoke(SESSION_ID, { 'x-admin-token': ADMIN_TOKEN });
  assert.equal(first.status, 200);
  assert.equal(second.status, 200);
  assert.deepEqual(await first.json(), { session_id: SESSION_ID, revoked: true });
  assert.deepEqual(await second.json(), { session_id: SESSION_ID, revoked: true });
  assert.equal(upstreamCalls.length, before + 2);
  for (const upstream of upstreamCalls.slice(before)) {
    assert.equal(upstream.url, `https://python.example/api/admin/sessions/${SESSION_ID}/revoke`);
    assert.equal(upstream.url.includes('worker'), false);
  }
});

test('unsafe session paths and non-POST methods are rejected before forwarding', async () => {
  const before = upstreamCalls.length;
  const paths = [
    '/admin/sessions/not-a-session/revoke',
    `/admin/sessions/${'g'.repeat(36)}/revoke`,
    `/admin/sessions/${SESSION_ID}extra/revoke`,
    `/admin/sessions/${SESSION_ID}/revoke/`,
    `/admin/sessions/${SESSION_ID}%2F..%2Fworker%2Fcancel/revoke`,
  ];
  for (const path of paths) {
    const response = await handler(new Request(`https://site.example/functions/v1/app${path}`, {
      method: 'POST',
      headers: { 'x-admin-token': ADMIN_TOKEN },
    }));
    assert.equal(response.status, 404);
    assert.deepEqual(await response.json(), { error: 'not_found' });
  }
  const getResponse = await revoke(SESSION_ID, { 'x-admin-token': ADMIN_TOKEN }, 'GET');
  assert.equal(getResponse.status, 404);
  assert.deepEqual(await getResponse.json(), { error: 'not_found' });
  assert.equal(upstreamCalls.length, before);
});
