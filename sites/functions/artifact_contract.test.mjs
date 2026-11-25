import assert from 'node:assert/strict';
const { default: nodeTest } = await import('node:test');
const test = globalThis.Deno?.test?.bind(globalThis.Deno) ?? nodeTest;

const SECRET = 'worker-test-secret';
const TASK = 'task-1';
const NEIGHBOUR_TASK = 'task-10';
let handler;

const realDeno = Object.getOwnPropertyDescriptor(globalThis, 'Deno');
const mockedDeno = {
  env: {
    get: (name) => ({
      PYTHON_API_ORIGIN: 'https://python.example',
      WORKER_SHARED_SECRET: SECRET,
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
globalThis.__LANDSCAPE_STORAGE__ = (await import('../../dev/storage-stub.mjs')).storage;
globalThis.fetch = async (url) => {
  throw new Error(`unexpected upstream call: ${url}`);
};
await import('./index.ts');
restoreDeno();

const serveHandler = handler;
handler = (request) => {
  installDenoMock();
  return Promise.resolve().then(() => serveHandler(request)).finally(restoreDeno);
};

function worker(path, method = 'GET', body, extraHeaders = {}) {
  return handler(new Request(`https://site.example${path}`, {
    method,
    headers: { 'x-worker-token': SECRET, ...extraHeaders },
    body,
  }));
}

function upload(taskId, filename, bytes) {
  return worker(
    `/functions/v1/app/internal/artifacts/${taskId}/${filename}`,
    'PUT',
    new Uint8Array(bytes),
    { 'content-type': 'application/octet-stream' },
  );
}

test('artifact list is scoped to the exact task segment', async () => {
  assert.equal((await upload(TASK, 'a.txt', [97])).status, 201);
  assert.equal((await upload(NEIGHBOUR_TASK, 'b.txt', [98])).status, 201);

  const response = await worker(`/functions/v1/app/internal/artifacts/${TASK}`);
  assert.equal(response.status, 200);
  assert.deepEqual(await response.json(), { artifacts: [{ name: 'a.txt', size: 1 }] });
});

test('a missing artifact is 404 instead of 500', async () => {
  const response = await worker(`/functions/v1/app/internal/artifacts/${TASK}/none.bin`);
  assert.equal(response.status, 404);
  assert.deepEqual(await response.json(), { error: 'artifact_not_found' });
});

test('a missing checksum is 404 instead of 500', async () => {
  const response = await worker(`/functions/v1/app/internal/artifact-checksums/${TASK}/none.bin`);
  assert.equal(response.status, 404);
  assert.deepEqual(await response.json(), { error: 'checksum_not_found' });
});

test('an upload above 50 MB is rejected with 413', async () => {
  const response = await worker(
    `/functions/v1/app/internal/artifacts/${TASK}/oversize.bin`,
    'PUT',
    new Uint8Array(50_000_001),
    { 'content-type': 'application/octet-stream' },
  );
  assert.equal(response.status, 413);
  assert.deepEqual(await response.json(), { error: 'request_too_large' });
});

test('mount prefixes are accepted only at the start of the path', async () => {
  const accepted = [
    '/health',
    '/functions/v1/app/health',
    '/app/health',
    '/app-abc123/health',
    '/app-abc123/functions/v1/app/health',
  ];
  for (const path of accepted) {
    const response = await handler(new Request(`https://site.example${path}`));
    assert.equal(response.status, 200, path);
    assert.equal((await response.json()).status, 'ok', path);
  }

  for (const path of [
    '/evil/functions/v1/app/health',
    '/x/app/health',
    '/evil/functions/v1/app/internal/artifacts/task-1/a.txt',
  ]) {
    const response = await handler(new Request(`https://site.example${path}`, {
      headers: { 'x-worker-token': SECRET },
    }));
    assert.equal(response.status, 404, path);
  }
});

test('an internal artifact route still works behind a gateway mount prefix', async () => {
  assert.equal((await upload(TASK, 'mounted.txt', [109])).status, 201);
  const response = await handler(new Request(
    `https://site.example/app-abc123/internal/artifacts/${TASK}/mounted.txt`,
    { headers: { 'x-worker-token': SECRET } },
  ));
  assert.equal(response.status, 200);
  assert.deepEqual(new Uint8Array(await response.arrayBuffer()), new Uint8Array([109]));
});

test('checksum mismatch is still rejected with 422', async () => {
  const response = await worker(
    `/functions/v1/app/internal/artifacts/${TASK}/bad.bin`,
    'PUT',
    new Uint8Array([1]),
    { 'x-artifact-sha256': '0'.repeat(64) },
  );
  assert.equal(response.status, 422);
});
