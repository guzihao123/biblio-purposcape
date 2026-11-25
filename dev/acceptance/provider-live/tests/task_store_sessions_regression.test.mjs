// Regression: the worker sessions route must preserve a caller-supplied
// session id (WIRE-01) while keeping server-generated ids for anonymous
// callers. Run: node dev/acceptance/provider-live/tests/task_store_sessions_regression.test.mjs

import assert from 'node:assert/strict';
const { default: nodeTest } = await import('node:test');
const test = globalThis.Deno?.test?.bind(globalThis.Deno) ?? nodeTest;
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { createTaskStore, createWorkerTaskStoreHandler } from '../../../../sites/functions/task_store.ts';
import { FakeDatabase } from './fake_db.mjs';

const HERE = dirname(fileURLToPath(import.meta.url));

function harness() {
  const database = new FakeDatabase();
  let sequence = 0;
  const store = createTaskStore({
    database,
    idFactory: () => `generated-${++sequence}`,
  });
  const handler = createWorkerTaskStoreHandler({ store, workerToken: 'offline-wire-test-secret' });
  const call = (path, method = 'POST', body) => handler(new Request(`https://site.example${path}`, {
    method,
    headers: {
      'x-worker-token': 'offline-wire-test-secret',
      ...(body ? { 'content-type': 'application/json' } : {}),
    },
    ...(body !== undefined ? { body: JSON.stringify(body) } : {}),
  }));
  return { database, handler, call };
}

const SESSIONS = '/functions/v1/app/internal/task-store/sessions';

test('worker sync session preserves the caller-supplied id end to end', async () => {
  const { database, call } = harness();
  const wanted = 'wire-fixed-session-1';
  const response = await call(SESSIONS, 'POST', {
    client_ip: '203.0.113.10', user_agent: 'wire-regression', id: wanted,
  });
  assert.equal(response.status, 201);
  const session = await response.json();
  assert.equal(session.id, wanted);
  assert.equal(database.data.sessions.get(wanted).id, wanted);
  assert.equal(database.data.sessions.size, 1);
});

test('anonymous session creation without id keeps server-generated behavior', async () => {
  const { call } = harness();
  const first = await (await call(SESSIONS, 'POST', { client_ip: '', user_agent: '' })).json();
  const second = await (await call(SESSIONS, 'POST', { client_ip: '', user_agent: '' })).json();
  assert.match(first.id, /^[A-Za-z0-9-]{1,64}$/);
  assert.match(second.id, /^[A-Za-z0-9-]{1,64}$/);
  assert.notEqual(first.id, second.id);
});

test('illegal supplied session ids are rejected safely before any insert', async () => {
  const { database, call } = harness();
  for (const id of ['', 'has space', '../escape', 'x'.repeat(65), 123]) {
    const response = await call(SESSIONS, 'POST', { client_ip: '', user_agent: '', id });
    assert.equal(response.status, 422);
    assert.deepEqual(await response.json(), { error: 'invalid_session_id' });
  }
  assert.equal(database.data.sessions.size, 0);
});

test('sessions route still rejects non-POST methods', async () => {
  const { call } = harness();
  const response = await call(SESSIONS, 'GET');
  assert.equal(response.status, 405);
  assert.deepEqual(await response.json(), { error: 'method_not_allowed' });
});
