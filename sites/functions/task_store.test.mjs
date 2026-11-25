import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { existsSync } from 'node:fs';
import { readFile } from 'node:fs/promises';
import { dirname, join } from 'node:path';
const { default: nodeTest } = await import('node:test');
const test = globalThis.Deno?.test?.bind(globalThis.Deno) ?? nodeTest;
import { fileURLToPath } from 'node:url';

import {
  createTaskStore,
  createWorkerTaskStoreHandler,
  TaskStoreError,
} from './task_store.ts';

// 未验证真实 Provider 权限与原子性：这里只使用本地假数据库验证固定契约。
const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = join(HERE, '..', '..');
const QUOTA = Object.freeze({ limit: 20, window_seconds: 3600 });
const HASH = 'a'.repeat(64);

function emptyData() {
  return {
    sessions: new Map(), skills: new Map(), tasks: new Map(),
    artifacts: new Map(), quotas: new Map(), answers: new Map(),
    jobs: new Map(), progress: new Map(), events: new Map(),
  };
}

function clone(value) {
  return structuredClone(value);
}

class FakeDatabase {
  constructor() {
    this.data = emptyData();
    this.chain = Promise.resolve();
    this.failNext = null;
    this.operations = [];
  }

  transaction(work) {
    const execute = async () => {
      const working = clone(this.data);
      const tx = {
        query: async (sql, parameters = []) => this.query(working, sql, parameters),
      };
      const result = await work(tx);
      this.data = working;
      return result;
    };
    const result = this.chain.then(execute, execute);
    this.chain = result.then(() => undefined, () => undefined);
    return result;
  }

  query(data, sql, parameters) {
    const match = sql.match(/\/\* ([a-z_]+) \*\//);
    assert.ok(match, 'fake adapter rejected SQL outside the fixed operation allowlist');
    const operation = match[1];
    this.operations.push(operation);
    if (this.failNext) {
      const failure = this.failNext;
      if (!failure.operation || failure.operation === operation) {
        this.failNext = null;
        throw failure.error || failure;
      }
    }
    const rows = this.rows(data, operation, parameters);
    return { rows };
  }

  rows(data, operation, p) {
    const ownedTask = (taskId, sessionId) => {
      const task = data.tasks.get(taskId);
      return task && task.session_id === sessionId ? task : null;
    };
    switch (operation) {
      case 'create_session': {
        const [id, client_ip, user_agent, now, expires_at, revoked_at] = p;
        assert.equal(data.sessions.has(id), false);
        const row = {
          id, client_ip, user_agent, created_at: now, last_seen_at: now,
          expires_at, revoked_at,
        };
        data.sessions.set(id, row);
        return [clone(row)];
      }
      case 'get_latest_published_skill': {
        const rows = [...data.skills.values()]
          .filter((row) => row.state === 'published')
          .sort((left, right) => right.version - left.version);
        return rows.length ? [clone(rows[0])] : [];
      }
      case 'get_session': {
        const row = data.sessions.get(p[0]);
        return row ? [clone(row)] : [];
      }
      case 'upsert_skill_version': {
        const [id, version, parent_id, state, content, content_hash, report, created_at, published_at] = p;
        const row = {
          id, version, parent_id, state, content: JSON.parse(content), content_hash,
          regression_report: report ? JSON.parse(report) : null, created_at, published_at,
        };
        data.skills.set(id, row);
        return [clone(row)];
      }
      case 'get_published_skill': {
        const row = data.skills.get(p[0]);
        return row && row.state === 'published' ? [{ id: row.id }] : [];
      }
      case 'get_skill_version': {
        const row = data.skills.get(p[0]);
        return row ? [clone(row)] : [];
      }
      case 'find_task_by_key': {
        const row = [...data.tasks.values()].find((task) => (
          task.session_id === p[0] && task.idempotency_key === p[1]
        ));
        return row ? [clone(row)] : [];
      }
      case 'insert_task': {
        const [id, session_id, skill_version_id, idempotency_key, state, next_card, now] = p;
        const conflict = [...data.tasks.values()].some((task) => (
          task.session_id === session_id && task.idempotency_key === idempotency_key
        ));
        if (conflict) return [];
        const row = {
          id, session_id, skill_version_id, idempotency_key, state, next_card,
          revision: 1, created_at: now, updated_at: now,
        };
        data.tasks.set(id, row);
        return [clone(row)];
      }
      case 'consume_task_quota': {
        const [session_id, window_start, limit, cost, now] = p;
        const key = `${session_id}\u0000${window_start}`;
        const current = data.quotas.get(key);
        const used = (current?.used || 0) + cost;
        if (used > limit) return [];
        const row = current || { session_id, window_start, used: 0, created_at: now };
        row.used = used;
        row.updated_at = now;
        data.quotas.set(key, row);
        return [{ used }];
      }
      case 'get_owned_task': {
        const row = ownedTask(p[0], p[1]);
        return row ? [clone(row)] : [];
      }
      case 'list_owned_tasks': {
        return [...data.tasks.values()]
          .filter((task) => task.session_id === p[0])
          .sort((left, right) => right.created_at.localeCompare(left.created_at) || right.id.localeCompare(left.id))
          .slice(p[2], p[2] + p[1]).map(clone);
      }
      case 'update_owned_task_state': {
        const [task_id, session_id, state, next_card, revision, now] = p;
        const row = ownedTask(task_id, session_id);
        if (!row || row.revision !== revision) return [];
        Object.assign(row, { state, next_card, revision: revision + 1, updated_at: now });
        return [clone(row)];
      }
      case 'get_task_answer': {
        const row = data.answers.get(`${p[0]}\u0000${p[1]}`);
        return row ? [clone(row)] : [];
      }
      case 'list_task_answers': {
        return [...data.answers.values()]
          .filter((row) => row.task_id === p[0])
          .sort((left, right) => left.card_id.localeCompare(right.card_id))
          .map(clone);
      }
      case 'insert_task_answer': {
        const [task_id, card_id, value, now] = p;
        const key = `${task_id}\u0000${card_id}`;
        if (data.answers.has(key)) return [];
        const row = { task_id, card_id, value: JSON.parse(value), created_at: now, updated_at: now };
        data.answers.set(key, row);
        return [clone(row)];
      }
      case 'update_task_answer': {
        const [task_id, card_id, value, now] = p;
        const key = `${task_id}\u0000${card_id}`;
        const previous = data.answers.get(key);
        if (!previous) return [];
        const row = { ...previous, value: JSON.parse(value), updated_at: now };
        data.answers.set(key, row);
        return [clone(row)];
      }
      case 'list_owned_artifacts': {
        if (!ownedTask(p[0], p[1])) return [];
        return [...data.artifacts.values()]
          .filter((row) => row.task_id === p[0])
          .sort((left, right) => left.name.localeCompare(right.name)).map(clone);
      }
      case 'upsert_owned_artifact': {
        const [task_id, session_id, name, object_path, size_bytes, content_type, checksum, metadata, now] = p;
        if (!ownedTask(task_id, session_id)) return [];
        const key = `${task_id}\u0000${name}`;
        const previous = data.artifacts.get(key);
        const row = {
          task_id, name, object_path, size_bytes, content_type,
          checksum_sha256: checksum, metadata: JSON.parse(metadata),
          created_at: previous?.created_at || now, updated_at: now,
        };
        data.artifacts.set(key, row);
        return [clone(row)];
      }
      case 'get_stage_job_natural': {
        const [task_id, stage, input_hash] = p;
        const row = [...data.jobs.values()].find((job) => (
          job.task_id === task_id && job.stage === stage && job.input_hash === input_hash
        ));
        return row ? [clone(row)] : [];
      }
      case 'get_stage_job': {
        const row = [...data.jobs.values()].find((job) => job.id === p[0] && job.task_id === p[1]);
        return row ? [clone(row)] : [];
      }
      case 'insert_stage_job': {
        const [id, task_id, stage, input_hash, task_revision] = p;
        if (!ownedTask(task_id, data.tasks.get(task_id)?.session_id)) return [];
        if ([...data.jobs.values()].some((job) => (
          job.task_id === task_id && job.stage === stage && job.input_hash === input_hash
        ))) return [];
        const now = new Date().toISOString();
        const row = {
          id, task_id, stage, input_hash, status: 'queued', attempt: 0,
          revision: 1, task_revision, lease_token: null, next_retry_at: null,
          started_at: null, finished_at: null, created_at: now, updated_at: now,
        };
        data.jobs.set(id, row);
        return [clone(row)];
      }
      case 'get_job_progress': {
        const row = data.progress.get(p[0]);
        return row ? [clone(row)] : [];
      }
      case 'get_latest_task_progress': {
        const row = data.progress.get(p[0]);
        if (!row) return [];
        const job = data.jobs.get(row.job_id);
        return [{ ...clone(row), stage: job?.stage, input_hash: job?.input_hash }];
      }
      case 'upsert_job_progress': {
        const [task_id, job_id, message, checkpoint, protected_traceback] = p;
        if (!data.jobs.has(job_id)) return [];
        const previous = data.progress.get(task_id);
        const row = {
          task_id, job_id, message, checkpoint: checkpoint ? JSON.parse(checkpoint) : null,
          protected_traceback,
          updated_at: new Date().toISOString(),
          created_at: previous?.created_at || new Date().toISOString(),
        };
        data.progress.set(task_id, row);
        return [clone(row)];
      }
      case 'append_job_event': {
        const [task_id, job_id, event_type, event_key, payload] = p;
        if ([...data.events.values()].some((event) => event.event_key === event_key)) return [];
        const row = {
          id: data.events.size + 1, task_id, job_id, event_type, event_key,
          payload: JSON.parse(payload), created_at: new Date().toISOString(),
        };
        data.events.set(row.id, row);
        return [clone(row)];
      }
      case 'update_job_started': {
        const [id, task_id, revision, lease_token] = p;
        const row = data.jobs.get(id);
        if (!row || row.task_id !== task_id || row.revision !== revision || row.status !== 'queued') return [];
        if (row.next_retry_at && row.next_retry_at > new Date().toISOString()) return [];
        Object.assign(row, {
          status: 'started', attempt: row.attempt + 1, revision: row.revision + 1,
          lease_token, started_at: new Date().toISOString(), updated_at: new Date().toISOString(),
        });
        return [clone(row)];
      }
      case 'update_job_completed': {
        const [id, task_id, revision, lease_token, input_hash] = p;
        const row = data.jobs.get(id);
        if (!row || row.task_id !== task_id || row.revision !== revision ||
            row.status !== 'started' || row.lease_token !== lease_token || row.input_hash !== input_hash) return [];
        Object.assign(row, {
          status: 'completed', revision: row.revision + 1, lease_token: null,
          finished_at: new Date().toISOString(), updated_at: new Date().toISOString(),
        });
        return [clone(row)];
      }
      case 'update_job_failed': {
        const [id, task_id, revision, lease_token, next_retry_at] = p;
        const row = data.jobs.get(id);
        if (!row || row.task_id !== task_id || row.revision !== revision ||
            !(row.status === 'queued' || (row.status === 'started' && row.lease_token === lease_token))) return [];
        Object.assign(row, {
          status: 'failed', revision: row.revision + 1, lease_token: null,
          next_retry_at, finished_at: new Date().toISOString(), updated_at: new Date().toISOString(),
        });
        return [clone(row)];
      }
      case 'retry_stage_job': {
        const [id, task_id, revision] = p;
        const row = data.jobs.get(id);
        if (!row || row.task_id !== task_id || row.revision !== revision || row.status !== 'failed') return [];
        if (row.next_retry_at && row.next_retry_at > new Date().toISOString()) return [];
        Object.assign(row, {
          status: 'queued', revision: row.revision + 1, task_revision: p[3], lease_token: null,
          next_retry_at: null, started_at: null, finished_at: null,
          updated_at: new Date().toISOString(),
        });
        return [clone(row)];
      }
      case 'update_task_after_stage': {
        const [task_id, session_id, state, next_card, task_revision] = p;
        const row = ownedTask(task_id, session_id);
        if (!row || row.revision !== task_revision) return [];
        Object.assign(row, { state, next_card, revision: row.revision + 1, updated_at: new Date().toISOString() });
        return [clone(row)];
      }
      case 'get_latest_terms_event': {
        const row = [...data.events.values()]
          .filter((event) => event.task_id === p[0] && ['terms_candidates', 'terms_candidates_unavailable'].includes(event.event_type))
          .sort((left, right) => right.id - left.id)[0];
        return row ? [clone(row)] : [];
      }
      case 'append_task_event': {
        const [task_id, event_type, event_key, payload] = p;
        if ([...data.events.values()].some((event) => event.event_key === event_key)) return [];
        const row = {
          id: data.events.size + 1, task_id, job_id: null, event_type, event_key,
          payload: JSON.parse(payload), created_at: new Date().toISOString(),
        };
        data.events.set(row.id, row);
        return [clone(row)];
      }
      case 'list_job_events': {
        return [...data.events.values()]
          .filter((event) => event.job_id === p[0])
          .sort((left, right) => left.id - right.id)
          .map(clone);
      }
      default:
        throw new Error(`unexpected fixed operation: ${operation}`);
    }
  }

  quotaUsed(sessionId) {
    return [...this.data.quotas.values()]
      .filter((row) => row.session_id === sessionId)
      .reduce((total, row) => total + row.used, 0);
  }
}

function harness() {
  let sequence = 0;
  let tick = 0;
  const database = new FakeDatabase();
  const store = createTaskStore({
    database,
    idFactory: () => `id-${++sequence}`,
    clock: () => new Date(Date.parse('2026-11-24T00:00:00.000Z') + tick++ * 1000),
  });
  return { database, store };
}

async function owner(store) {
  return store.createAnonymousSession({ clientIp: '203.0.113.10', userAgent: 'local-test' });
}

async function publishedSkill(store, id = 'skill-1') {
  return store.upsertSkillVersion({
    id,
    version: 1,
    parent_id: null,
    state: 'published',
    content: { cards: {} },
    content_hash: HASH,
    regression_report: { passed: true },
    created_at: '2026-11-24T00:00:00.000Z',
    published_at: '2026-11-24T00:00:00.000Z',
  });
}

async function create(store, sessionId, key = 'retry-key', extra = {}) {
  return store.createTask({
    sessionId,
    idempotencyKey: key,
    skillVersionId: 'skill-1',
    quota: QUOTA,
    ...extra,
  });
}

function code(error) {
  return error instanceof TaskStoreError ? error.code : undefined;
}

const artifact = (name = 'report.docx', size = 1024) => ({
  name,
  size_bytes: size,
  content_type: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  checksum_sha256: 'b'.repeat(64),
  metadata: { generator: 'local-fake' },
});

test('未验证真实 Provider 权限与原子性：Schema 仅作审核，假库仅验证固定契约', async () => {
  const schema = await readFile(join(ROOT, 'sites', 'schema.sql'), 'utf8');
  assert.match(schema, /review material only/i);
  assert.match(schema, /UNIQUE \(session_id, idempotency_key\)/);
  assert.match(schema, /sites_task_artifacts/);
  const { database } = harness();
  await assert.rejects(() => database.transaction((tx) => tx.query('SELECT * FROM sites_tasks', [])), /allowlist/);
});

test('all task reads and writes are isolated by owner; keys are owner-scoped', async () => {
  const { store } = harness();
  const first = await owner(store);
  const second = await owner(store);
  await publishedSkill(store);
  const a = await create(store, first.id, 'same-client-key');
  const b = await create(store, second.id, 'same-client-key');
  assert.notEqual(a.task.id, b.task.id);
  assert.equal(await store.getTask({ sessionId: first.id, taskId: b.task.id }), null);
  assert.deepEqual((await store.listTasks({ sessionId: first.id })).map((task) => task.id), [a.task.id]);
  await assert.rejects(
    () => store.updateTaskState({
      sessionId: first.id, taskId: b.task.id, expectedRevision: 1,
      state: 'done', nextCard: null,
    }),
    (error) => code(error) === 'task_not_found',
  );
  await assert.rejects(
    () => store.syncArtifacts({ sessionId: first.id, taskId: b.task.id, artifacts: [artifact()] }),
    (error) => code(error) === 'task_not_found',
  );
  await assert.rejects(
    () => store.listArtifacts({ sessionId: first.id, taskId: b.task.id }),
    (error) => code(error) === 'task_not_found',
  );
});

test('duplicate key returns the original task without charging or resetting old state', async () => {
  const { store, database } = harness();
  const session = await owner(store);
  await publishedSkill(store);
  const first = await create(store, session.id);
  const changed = await store.updateTaskState({
    sessionId: session.id, taskId: first.task.id, expectedRevision: 1,
    state: 'searching', nextCard: null,
  });
  assert.equal(changed.revision, 2);
  const replay = await create(store, session.id, 'retry-key', { state: 'done', nextCard: null });
  assert.equal(replay.replayed, true);
  assert.equal(replay.task.id, first.task.id);
  assert.equal(replay.task.state, 'searching');
  assert.equal(replay.task.revision, 2);
  assert.equal(database.quotaUsed(session.id), 1);
  assert.equal(database.data.tasks.size, 1);
});

test('concurrent same-key creates have one winner and exactly one quota charge', async () => {
  const { store, database } = harness();
  const session = await owner(store);
  await publishedSkill(store);
  const results = await Promise.all(Array.from({ length: 16 }, () => create(store, session.id, 'race-key')));
  assert.equal(new Set(results.map((result) => result.task.id)).size, 1);
  assert.equal(results.filter((result) => !result.replayed).length, 1);
  assert.equal(database.data.tasks.size, 1);
  assert.equal(database.quotaUsed(session.id), 1);
});

test('quota denial rolls back its task insert and concurrent winners never exceed the limit', async () => {
  const { store, database } = harness();
  const session = await owner(store);
  await publishedSkill(store);
  const results = await Promise.allSettled(Array.from({ length: 8 }, (_, index) => (
    create(store, session.id, `quota-${index}`, { quota: { limit: 3, window_seconds: 3600 } })
  )));
  assert.equal(results.filter((result) => result.status === 'fulfilled').length, 3);
  const denied = results.filter((result) => result.status === 'rejected');
  assert.equal(denied.length, 5);
  assert.ok(denied.every((result) => code(result.reason) === 'quota_exceeded'));
  assert.equal(database.data.tasks.size, 3);
  assert.equal(database.quotaUsed(session.id), 3);
});

test('stale revision cannot overwrite newer state', async () => {
  const { store } = harness();
  const session = await owner(store);
  await publishedSkill(store);
  const first = await create(store, session.id);
  await store.updateTaskState({
    sessionId: session.id, taskId: first.task.id, expectedRevision: 1,
    state: 'generating', nextCard: null,
  });
  await assert.rejects(
    () => store.updateTaskState({
      sessionId: session.id, taskId: first.task.id, expectedRevision: 1,
      state: 'error', nextCard: 'delivery',
    }),
    (error) => code(error) === 'revision_conflict',
  );
  const current = await store.getTask({ sessionId: session.id, taskId: first.task.id });
  assert.equal(current.state, 'generating');
  assert.equal(current.next_card, null);
  assert.equal(current.revision, 2);
});

test('artifact metadata is owner-scoped, validated, and upsert preserves creation time', async () => {
  const { store } = harness();
  const session = await owner(store);
  await publishedSkill(store);
  const created = await create(store, session.id);
  const saved = await store.syncArtifacts({
    sessionId: session.id, taskId: created.task.id, artifacts: [artifact()],
  });
  assert.equal(saved[0].object_path, `artifacts/${created.task.id}/report.docx`);
  const updated = await store.syncArtifacts({
    sessionId: session.id, taskId: created.task.id,
    artifacts: [{ ...artifact(), object_path: saved[0].object_path, size_bytes: 2048 }],
  });
  assert.equal(updated[0].created_at, saved[0].created_at);
  assert.equal(updated[0].size_bytes, 2048);
  assert.equal((await store.listArtifacts({ sessionId: session.id, taskId: created.task.id })).length, 1);
  await assert.rejects(
    () => store.syncArtifacts({
      sessionId: session.id, taskId: created.task.id,
      artifacts: [{ ...artifact(), object_path: 'artifacts/other-owner/report.docx' }],
    }),
    (error) => code(error) === 'invalid_artifact_path',
  );
  await assert.rejects(
    () => store.syncArtifacts({
      sessionId: session.id, taskId: created.task.id,
      artifacts: [artifact('../secret')],
    }),
    (error) => code(error) === 'invalid_artifact_name',
  );
});

test('worker surface rejects illegal access, arbitrary queries, public writes, and stale sync', async () => {
  const { store } = harness();
  const session = await owner(store);
  const other = await owner(store);
  await publishedSkill(store);
  const created = await create(store, session.id);
  const handler = createWorkerTaskStoreHandler({ store, workerToken: 'worker-test-secret' });
  const path = `/functions/v1/app/internal/task-store/tasks/${created.task.id}`;
  const request = (url, method = 'GET', token = 'worker-test-secret', ownerId = session.id, body) => (
    new Request(url, {
      method,
      headers: {
        'x-worker-token': token,
        'x-session-id': ownerId,
        ...(body ? { 'content-type': 'application/json' } : {}),
      },
      ...(body ? { body: JSON.stringify(body) } : {}),
    })
  );

  const denied = await handler(request(`https://site.example${path}`, 'GET', 'wrong'));
  assert.equal(denied.status, 403);
  assert.doesNotMatch(await denied.text(), /worker-test-secret/);
  const wrongOwner = await handler(request(`https://site.example${path}`, 'GET', undefined, other.id));
  assert.equal(wrongOwner.status, 404);
  const readable = await handler(request(`https://site.example${path}`));
  assert.equal(readable.status, 200);
  assert.equal((await readable.json()).task.id, created.task.id);

  const arbitrary = await handler(request(
    'https://site.example/functions/v1/app/internal/task-store/query', 'POST', undefined, session.id,
    { sql: 'SELECT * FROM sites_tasks' },
  ));
  assert.equal(arbitrary.status, 404);
  const publicWrite = await handler(request(
    `https://site.example/functions/v1/app/tasks/${created.task.id}`, 'PUT', undefined, session.id,
    { state: 'done' },
  ));
  assert.equal(publicWrite.status, 404);

  const stateBody = {
    session_id: session.id, expected_revision: 1, state: 'done', next_card: null,
  };
  const updated = await handler(request(
    `https://site.example${path}/state`, 'PUT', undefined, session.id, stateBody,
  ));
  assert.equal(updated.status, 200);
  assert.equal((await updated.json()).task.revision, 2);
  const stale = await handler(request(`https://site.example${path}/state`, 'PUT', undefined, session.id, stateBody));
  assert.equal(stale.status, 409);
  assert.equal((await store.getTask({ sessionId: session.id, taskId: created.task.id })).state, 'done');
});

test('Provider and transport failures produce safe errors without secrets, SQL, or local paths', async () => {
  const { store, database } = harness();
  const session = await owner(store);
  const other = await owner(store);
  await publishedSkill(store);
  const created = await create(store, session.id);
  const handler = createWorkerTaskStoreHandler({ store, workerToken: 'do-not-print-worker-secret' });
  database.failNext = new Error('password=do-not-print-db-secret; SQL SELECT * FROM sites_tasks; /Users/private/db');
  const response = await handler(new Request(
    `https://site.example/functions/v1/app/internal/task-store/tasks/${created.task.id}`,
    { headers: { 'x-worker-token': 'do-not-print-worker-secret', 'x-session-id': session.id } },
  ));
  assert.equal(response.status, 503);
  const text = await response.text();
  assert.deepEqual(JSON.parse(text), { error: 'task_store_unavailable' });
  for (const forbidden of ['do-not-print-worker-secret', 'do-not-print-db-secret', 'SELECT *', '/Users/', 'traceback']) {
    assert.equal(text.includes(forbidden), false);
  }
  database.failNext = new Error('sensitive Provider details');
  await assert.rejects(
    () => store.getTask({ sessionId: other.id, taskId: created.task.id }),
    (error) => code(error) === 'task_store_unavailable' && error.cause === undefined,
  );
});

test('worker session and task creation/list routes preserve idempotency and owner isolation', async () => {
  const { store, database } = harness();
  await publishedSkill(store);
  const handler = createWorkerTaskStoreHandler({ store, workerToken: 'worker-test-secret' });
  const call = (path, method = 'GET', body, ownerId = '') => handler(new Request(`https://site.example${path}`, {
    method,
    headers: {
      'x-worker-token': 'worker-test-secret',
      'x-session-id': ownerId,
      ...(body ? { 'content-type': 'application/json' } : {}),
    },
    ...(body ? { body: JSON.stringify(body) } : {}),
  }));

  const sessionResponse = await call('/functions/v1/app/internal/task-store/sessions', 'POST', {
    client_ip: '203.0.113.10', user_agent: 'route-test',
  });
  assert.equal(sessionResponse.status, 201);
  const session = await sessionResponse.json();
  const body = {
    session_id: session.id,
    idempotency_key: 'route-retry-key',
    skill_version_id: 'skill-1',
    quota: { limit: 20, window_seconds: 3600 },
  };
  const first = await call('/functions/v1/app/internal/task-store/tasks', 'POST', body);
  const replay = await call('/functions/v1/app/internal/task-store/tasks', 'POST', body);
  assert.equal(first.status, 201);
  assert.equal(replay.status, 200);
  const firstTask = (await first.json()).task;
  const replayedTask = (await replay.json()).task;
  assert.equal(firstTask.id, replayedTask.id);
  assert.equal(database.quotaUsed(session.id), 1);

  const owned = await call('/functions/v1/app/internal/task-store/tasks', 'GET', undefined, session.id);
  assert.deepEqual((await owned.json()).tasks.map((task) => task.id), [firstTask.id]);
  const other = await call('/functions/v1/app/internal/task-store/tasks', 'GET', undefined, 'other-owner');
  assert.deepEqual((await other.json()).tasks, []);
});

test('Python worker client creates sessions and idempotent tasks with bounded payloads', () => {
  const localVenv = join(ROOT, '.venv', 'bin', 'python');
  const python = existsSync(localVenv) ? localVenv : 'python3';
  const script = String.raw`
import json
import sys
sys.path.insert(0, sys.argv[1])
from app.sites_task_store import SitesTaskStoreClient

calls = []
def transport(url, options):
    calls.append((url, options))
    if url.endswith('/sessions'):
        return {'id': 'owner-1'}
    if url.endswith('/tasks'):
        if options['method'] == 'POST':
            return {'task': {'id': 'task-1'}, 'replayed': False}
        return {'tasks': [{'id': 'task-1'}]}
    raise AssertionError(url)

client = SitesTaskStoreClient('https://site.example', 'worker-secret', transport=transport)
client.create_anonymous_session('203.0.113.10', 'route-test')
first = client.create_task('owner-1', 'retry-key', 'skill-1', {'limit': 20, 'window_seconds': 3600})
replay = client.create_task('owner-1', 'retry-key', 'skill-1', {'limit': 20, 'window_seconds': 3600})
assert first['id'] == replay['id'] == 'task-1'
assert [task['id'] for task in client.list_tasks('owner-1')] == ['task-1']
paths = [url for url, options in calls]
assert paths == [
    'https://site.example/functions/v1/app/internal/task-store/sessions',
    'https://site.example/functions/v1/app/internal/task-store/tasks',
    'https://site.example/functions/v1/app/internal/task-store/tasks',
    'https://site.example/functions/v1/app/internal/task-store/tasks',
]
body = json.loads(calls[1][1]['body'])
assert body['session_id'] == 'owner-1'
assert body['idempotency_key'] == 'retry-key'
assert body['skill_version_id'] == 'skill-1'
print(json.dumps({'routes': len(calls), 'idempotent': True}))
`;
  const result = spawnSync(python, ['-c', script, join(ROOT, 'backend')], {
    encoding: 'utf8',
    env: {},
    timeout: 20_000,
  });
  assert.equal(result.status, 0, result.stderr || result.stdout);
  assert.deepEqual(JSON.parse(result.stdout), { routes: 4, idempotent: true });
});

test('Python worker client uses fixed paths and redacts custom transport failures', () => {
  const localVenv = join(ROOT, '.venv', 'bin', 'python');
  const python = existsSync(localVenv) ? localVenv : 'python3';
  const script = String.raw`
import json
import sys
sys.path.insert(0, sys.argv[1])
from app.sites_task_store import SitesTaskStoreClient, SitesTaskStoreError

secret = 'python-worker-secret'
calls = []
def transport(url, options):
    calls.append((url, options))
    if url.endswith('/state'):
        return {'task': {'id': 'task-1', 'state': 'done'}}
    if url.endswith('/artifacts'):
        return {'artifacts': []}
    if '/skill-versions/' in url:
        return {'skill_version': {'id': 'skill-1'}}
    return {'task': {'id': 'task-1'}}

client = SitesTaskStoreClient('https://site.example', secret, transport=transport)
client.get_task('task-1', 'owner-1')
client.sync_task_state('task-1', 'owner-1', 1, 'done')
client.list_artifacts('task-1', 'owner-1')
client.sync_artifacts('task-1', 'owner-1', [{'name': 'report.docx', 'size_bytes': 4}])
client.sync_skill_version({'id': 'skill-1', 'version': 1, 'state': 'published', 'content': {}, 'content_hash': 'a' * 64})
expected = [
    'https://site.example/functions/v1/app/internal/task-store/tasks/task-1',
    'https://site.example/functions/v1/app/internal/task-store/tasks/task-1/state',
    'https://site.example/functions/v1/app/internal/task-store/tasks/task-1/artifacts',
    'https://site.example/functions/v1/app/internal/task-store/tasks/task-1/artifacts',
    'https://site.example/functions/v1/app/internal/task-store/skill-versions/skill-1',
]
assert [url for url, options in calls] == expected
assert all(options['headers']['X-Worker-Token'] == secret for url, options in calls)
assert calls[0][1]['headers']['X-Session-Id'] == 'owner-1'
assert calls[1][1]['body'] is not None
before = len(calls)
try:
    client.get_task('../secret', 'owner-1')
    raise AssertionError('path traversal was accepted')
except ValueError:
    pass
assert len(calls) == before
assert secret not in repr(client)

def broken(url, options):
    raise RuntimeError('request failed with ' + secret + ' at /Users/private')
unsafe = SitesTaskStoreClient('https://site.example', secret, transport=broken)
try:
    unsafe.get_task('task-1', 'owner-1')
    raise AssertionError('broken transport unexpectedly succeeded')
except SitesTaskStoreError as error:
    assert str(error) == 'task_store_unavailable'
    assert secret not in str(error)
    assert '/Users/' not in str(error)
    assert error.__cause__ is None
print(json.dumps({'fixed_paths': len(calls), 'safe_error': True}))
`;
  const result = spawnSync(python, ['-c', script, join(ROOT, 'backend')], {
    encoding: 'utf8',
    env: {},
    timeout: 20_000,
  });
  assert.equal(result.status, 0, result.stderr || result.stdout);
  assert.deepEqual(JSON.parse(result.stdout), { fixed_paths: 5, safe_error: true });
});

test('public Function delegates internal task-store routes to the authorized worker handler', async () => {
  const { store, database } = harness();
  await publishedSkill(store);
  let handler;
  const realDeno = Object.getOwnPropertyDescriptor(globalThis, 'Deno');
  Object.defineProperty(globalThis, 'Deno', {
    configurable: true,
    value: {
      env: { get: (name) => name === 'WORKER_SHARED_SECRET' ? 'worker-test-secret' : undefined },
      serve: (callback) => { handler = callback; },
    },
  });
  globalThis.__LANDSCAPE_TASK_STORE__ = store;
  try {
    await import('./index.ts');
    const call = (path, method = 'GET', body, ownerId = '') => handler(new Request(`https://site.example${path}`, {
      method,
      headers: {
        'x-worker-token': 'worker-test-secret',
        'x-session-id': ownerId,
        ...(body ? { 'content-type': 'application/json' } : {}),
      },
      ...(body ? { body: JSON.stringify(body) } : {}),
    }));
    const sessionResponse = await call('/functions/v1/app/internal/task-store/sessions', 'POST', {
      client_ip: '203.0.113.10', user_agent: 'function-integration',
    });
    assert.equal(sessionResponse.status, 201);
    const session = await sessionResponse.json();
    const created = await call('/functions/v1/app/internal/task-store/tasks', 'POST', {
      session_id: session.id,
      idempotency_key: 'function-retry-key',
      skill_version_id: 'skill-1',
      quota: { limit: 20, window_seconds: 3600 },
    });
    const replay = await call('/functions/v1/app/internal/task-store/tasks', 'POST', {
      session_id: session.id,
      idempotency_key: 'function-retry-key',
      skill_version_id: 'skill-1',
      quota: { limit: 20, window_seconds: 3600 },
    });
    assert.equal(created.status, 201);
    assert.equal(replay.status, 200);
    assert.equal((await created.json()).task.id, (await replay.json()).task.id);
    assert.equal(database.quotaUsed(session.id), 1);
  } finally {
    delete globalThis.__LANDSCAPE_TASK_STORE__;
    if (realDeno === undefined) delete globalThis.Deno;
    else Object.defineProperty(globalThis, 'Deno', realDeno);
  }
});

test('worker session route preserves a supplied id and anonymous generation', async () => {
  const { store, database } = harness();
  const handler = createWorkerTaskStoreHandler({ store, workerToken: 'worker-test-secret' });
  const call = (body) => handler(new Request('https://site.example/functions/v1/app/internal/task-store/sessions', {
    method: 'POST',
    headers: { 'x-worker-token': 'worker-test-secret', 'content-type': 'application/json' },
    body: JSON.stringify(body),
  }));
  const wanted = 'wire-fixed-session-1';
  const fixed = await call({ client_ip: '203.0.113.10', user_agent: 'wire-test', id: wanted });
  assert.equal(fixed.status, 201);
  assert.equal((await fixed.json()).id, wanted);
  assert.equal(database.data.sessions.get(wanted).id, wanted);
  const first = await (await call({ client_ip: '', user_agent: '' })).json();
  const second = await (await call({ client_ip: '', user_agent: '' })).json();
  assert.match(first.id, /^[A-Za-z0-9-]{1,64}$/);
  assert.match(second.id, /^[A-Za-z0-9-]{1,64}$/);
  assert.notEqual(first.id, second.id);
});

test('worker session route rejects invalid ids and methods without inserts', async () => {
  const { store, database } = harness();
  const handler = createWorkerTaskStoreHandler({ store, workerToken: 'worker-test-secret' });
  const sessions = 'https://site.example/functions/v1/app/internal/task-store/sessions';
  for (const id of ['', 'has space', '../escape', 'x'.repeat(65), 123]) {
    const response = await handler(new Request(sessions, {
      method: 'POST',
      headers: { 'x-worker-token': 'worker-test-secret', 'content-type': 'application/json' },
      body: JSON.stringify({ client_ip: '', user_agent: '', id }),
    }));
    assert.equal(response.status, 422);
    assert.deepEqual(await response.json(), { error: 'invalid_session_id' });
  }
  assert.equal(database.data.sessions.size, 0);
  const wrongMethod = await handler(new Request(sessions, {
    headers: { 'x-worker-token': 'worker-test-secret' },
  }));
  assert.equal(wrongMethod.status, 405);
  assert.deepEqual(await wrongMethod.json(), { error: 'method_not_allowed' });
});

test('direction answer is authoritative with replay, conflict and stale CAS protection', async () => {
  const { store, database } = harness();
  const session = await owner(store);
  await publishedSkill(store);
  const created = await create(store, session.id);
  const taskId = created.task.id;
  const direction = '肝癌免疫治疗耐药机制的最新进展';
  const first = await store.submitDirectionAnswer({
    sessionId: session.id, taskId, expectedRevision: 1, value: direction,
  });
  assert.equal(first.changed, true);
  assert.equal(first.task.revision, 2);
  assert.equal(first.task.next_card, 'mode');
  assert.equal(first.task.answers.direction, direction);
  const replay = await store.submitDirectionAnswer({
    sessionId: session.id, taskId, expectedRevision: 2, value: direction,
  });
  assert.equal(replay.changed, false);
  assert.equal(replay.task.revision, 2);
  await assert.rejects(
    store.submitDirectionAnswer({ sessionId: session.id, taskId, expectedRevision: 1, value: '旧写入' }),
    (error) => code(error) === 'revision_conflict',
  );
  await assert.rejects(
    store.submitDirectionAnswer({ sessionId: session.id, taskId, expectedRevision: 2, value: '冲突方向' }),
    (error) => code(error) === 'answer_conflict',
  );
  const aggregate = await store.getTaskAggregate({ sessionId: session.id, taskId });
  assert.equal(aggregate.revision, 2);
  assert.equal(aggregate.answers.direction, direction);
  assert.equal(aggregate.next_card, 'mode');
  assert.equal(database.data.answers.size, 1);
});

test('direction answer rolls back when the task transition fails after insertion', async () => {
  const { store, database } = harness();
  const session = await owner(store);
  await publishedSkill(store);
  const created = await create(store, session.id);
  database.failNext = {
    operation: 'update_owned_task_state',
    error: new Error('injected transition failure'),
  };
  await assert.rejects(
    store.submitDirectionAnswer({
      sessionId: session.id,
      taskId: created.task.id,
      expectedRevision: 1,
      value: '不能留下半次提交',
    }),
    (error) => code(error) === 'task_store_unavailable',
  );
  const aggregate = await store.getTaskAggregate({ sessionId: session.id, taskId: created.task.id });
  assert.equal(aggregate.revision, 1);
  assert.equal(aggregate.next_card, 'direction');
  assert.deepEqual(aggregate.answers, {});
  assert.equal(database.data.answers.size, 0);
});

async function reachAdjustment(store, sessionId) {
  const created = await create(store, sessionId);
  const taskId = created.task.id;
  const terms = ['immunotherapy resistance'];
  const years = { choice: 'B' };
  await store.submitDirectionAnswer({
    sessionId, taskId, expectedRevision: 1, value: '肝癌免疫治疗耐药机制',
  });
  await store.submitModeAnswer({ sessionId, taskId, expectedRevision: 2, value: 'A' });
  await store.submitTermsAnswer({ sessionId, taskId, expectedRevision: 3, value: terms });
  await store.submitYearsAnswer({ sessionId, taskId, expectedRevision: 4, value: years });
  await store.updateTaskState({
    sessionId, taskId, expectedRevision: 5, state: 'adjusting', nextCard: 'adjustment',
  });
  return { taskId, terms, years, revision: 6 };
}

test('mode terms and years advance with contiguous revisions and safe replay', async () => {
  const { store } = harness();
  const session = await owner(store);
  await publishedSkill(store);
  const created = await create(store, session.id);
  const taskId = created.task.id;
  await store.submitDirectionAnswer({
    sessionId: session.id, taskId, expectedRevision: 1, value: '肝癌免疫治疗耐药机制',
  });
  const mode = await store.submitModeAnswer({
    sessionId: session.id, taskId, expectedRevision: 2, value: 'A',
  });
  assert.equal(mode.changed, true);
  assert.equal(mode.task.revision, 3);
  assert.equal(mode.task.next_card, 'terms');
  const modeReplay = await store.submitModeAnswer({
    sessionId: session.id, taskId, expectedRevision: 3, value: 'A',
  });
  assert.equal(modeReplay.changed, false);
  assert.equal(modeReplay.task.revision, 3);
  const terms = await store.submitTermsAnswer({
    sessionId: session.id, taskId, expectedRevision: 3, value: ['immunotherapy resistance'],
  });
  assert.equal(terms.task.revision, 4);
  assert.equal(terms.task.next_card, 'years');
  const years = await store.submitYearsAnswer({
    sessionId: session.id, taskId, expectedRevision: 4, value: { choice: 'B' },
  });
  assert.equal(years.task.revision, 5);
  assert.equal(years.task.state, 'searching');
  assert.equal(years.task.next_card, null);
  await assert.rejects(
    store.submitModeAnswer({ sessionId: session.id, taskId, expectedRevision: 2, value: 'B' }),
    (error) => code(error) === 'revision_conflict',
  );
  await assert.rejects(
    store.submitModeAnswer({ sessionId: session.id, taskId, expectedRevision: 5, value: 'B' }),
    (error) => code(error) === 'answer_conflict',
  );
  const aggregate = await store.getTaskAggregate({ sessionId: session.id, taskId });
  assert.equal(aggregate.revision, 5);
  assert.deepEqual(aggregate.answers.mode, { mode: 'A' });
  assert.deepEqual(aggregate.answers.terms, ['immunotherapy resistance']);
  assert.deepEqual(aggregate.answers.years, { choice: 'B' });
});

test('adjustment continue has veto and delivery enters generating with safe replay', async () => {
  const { store } = harness();
  const session = await owner(store);
  await publishedSkill(store);
  const { taskId } = await reachAdjustment(store, session.id);
  const continued = await store.submitAdjustmentAnswer({
    sessionId: session.id, taskId, expectedRevision: 6,
    value: { adjustment: ['terms', 'continue'] },
  });
  assert.equal(continued.changed, true);
  assert.equal(continued.task.revision, 7);
  assert.equal(continued.task.next_card, 'delivery');
  assert.deepEqual(continued.task.answers.adjustment, { adjustment: ['continue'] });
  const delivered = await store.submitDeliveryAnswer({
    sessionId: session.id, taskId, expectedRevision: 7, value: { form: 'B' },
  });
  assert.equal(delivered.changed, true);
  assert.equal(delivered.task.revision, 8);
  assert.equal(delivered.task.state, 'generating');
  assert.equal(delivered.task.next_card, null);
  const replay = await store.submitDeliveryAnswer({
    sessionId: session.id, taskId, expectedRevision: 8, value: { form: 'B' },
  });
  assert.equal(replay.changed, false);
  assert.equal(replay.task.revision, 8);
  await assert.rejects(
    store.submitDeliveryAnswer({
      sessionId: session.id, taskId, expectedRevision: 8, value: { form: 'A' },
    }),
    (error) => code(error) === 'answer_conflict',
  );
});

test('adjustment can reopen terms and same-value confirmation restarts search', async () => {
  const { store } = harness();
  const session = await owner(store);
  await publishedSkill(store);
  const { taskId, terms } = await reachAdjustment(store, session.id);
  const adjusted = await store.submitAdjustmentAnswer({
    sessionId: session.id, taskId, expectedRevision: 6, value: { adjustment: ['terms'] },
  });
  assert.equal(adjusted.task.revision, 7);
  assert.equal(adjusted.task.next_card, 'terms');
  const confirmedTerms = await store.submitTermsAnswer({
    sessionId: session.id, taskId, expectedRevision: 7, value: terms,
  });
  assert.equal(confirmedTerms.changed, true);
  assert.equal(confirmedTerms.task.revision, 8);
  assert.equal(confirmedTerms.task.state, 'searching');
  assert.equal(confirmedTerms.task.next_card, null);
  assert.deepEqual(confirmedTerms.task.answers.terms, terms);
});

test('a later adjustment can replace an earlier adjustment answer', async () => {
  const { store } = harness();
  const session = await owner(store);
  await publishedSkill(store);
  const { taskId } = await reachAdjustment(store, session.id);
  await store.submitAdjustmentAnswer({
    sessionId: session.id, taskId, expectedRevision: 6, value: { adjustment: ['terms'] },
  });
  await store.submitTermsAnswer({
    sessionId: session.id, taskId, expectedRevision: 7, value: ['new mechanism'],
  });
  await store.updateTaskState({
    sessionId: session.id, taskId, expectedRevision: 8,
    state: 'adjusting', nextCard: 'adjustment',
  });
  const continued = await store.submitAdjustmentAnswer({
    sessionId: session.id, taskId, expectedRevision: 9, value: { adjustment: ['continue'] },
  });
  assert.equal(continued.changed, true);
  assert.equal(continued.task.revision, 10);
  assert.equal(continued.task.next_card, 'delivery');
  assert.deepEqual(continued.task.answers.adjustment, { adjustment: ['continue'] });
});

test('multiple adjustments follow workflow order and skip unselected cards', async () => {
  const { store } = harness();
  const session = await owner(store);
  await publishedSkill(store);
  const { taskId, years } = await reachAdjustment(store, session.id);
  const adjusted = await store.submitAdjustmentAnswer({
    sessionId: session.id, taskId, expectedRevision: 6,
    value: { adjustment: ['years', 'mode'] },
  });
  assert.equal(adjusted.task.next_card, 'mode');
  assert.deepEqual(adjusted.task.answers.adjustment, { adjustment: ['mode', 'years'] });
  const mode = await store.submitModeAnswer({
    sessionId: session.id, taskId, expectedRevision: 7, value: 'A',
  });
  assert.equal(mode.changed, true);
  assert.equal(mode.task.revision, 8);
  assert.equal(mode.task.next_card, 'years');
  const confirmedYears = await store.submitYearsAnswer({
    sessionId: session.id, taskId, expectedRevision: 8, value: years,
  });
  assert.equal(confirmedYears.changed, true);
  assert.equal(confirmedYears.task.revision, 9);
  assert.equal(confirmedYears.task.state, 'searching');
  assert.equal(confirmedYears.task.next_card, null);
});

test('mode answer insertion rolls back if its task transition fails', async () => {
  const { store, database } = harness();
  const session = await owner(store);
  await publishedSkill(store);
  const created = await create(store, session.id);
  const taskId = created.task.id;
  await store.submitDirectionAnswer({
    sessionId: session.id, taskId, expectedRevision: 1, value: '肝癌免疫治疗耐药机制',
  });
  database.failNext = {
    operation: 'update_owned_task_state',
    error: new Error('injected mode transition failure'),
  };
  await assert.rejects(
    store.submitModeAnswer({ sessionId: session.id, taskId, expectedRevision: 2, value: 'A' }),
    (error) => code(error) === 'task_store_unavailable',
  );
  const aggregate = await store.getTaskAggregate({ sessionId: session.id, taskId });
  assert.equal(aggregate.revision, 2);
  assert.equal(aggregate.next_card, 'mode');
  assert.equal(aggregate.answers.mode, undefined);
});

test('adjusted answer update rolls back if its task transition fails', async () => {
  const { store, database } = harness();
  const session = await owner(store);
  await publishedSkill(store);
  const { taskId, terms } = await reachAdjustment(store, session.id);
  await store.submitAdjustmentAnswer({
    sessionId: session.id, taskId, expectedRevision: 6, value: { adjustment: ['terms'] },
  });
  database.failNext = {
    operation: 'update_owned_task_state',
    error: new Error('injected adjusted transition failure'),
  };
  await assert.rejects(
    store.submitTermsAnswer({
      sessionId: session.id, taskId, expectedRevision: 7, value: ['must roll back'],
    }),
    (error) => code(error) === 'task_store_unavailable',
  );
  const aggregate = await store.getTaskAggregate({ sessionId: session.id, taskId });
  assert.equal(aggregate.revision, 7);
  assert.equal(aggregate.next_card, 'terms');
  assert.deepEqual(aggregate.answers.terms, terms);
});

test('session records reject expired and revoked identities', async () => {
  const { store } = harness();
  const active = await store.createAnonymousSession({ id: 'active-session' });
  assert.equal((await store.getSessionRecord({ sessionId: active.id })).id, active.id);
  assert.ok(active.expires_at);
  await store.createAnonymousSession({ id: 'expired-session', expiresAt: '2020-01-01T00:00:00.000Z' });
  await assert.rejects(
    store.getSessionRecord({ sessionId: 'expired-session' }),
    (error) => code(error) === 'session_not_found',
  );
  await store.createAnonymousSession({ id: 'revoked-session', revokedAt: '2026-11-24T00:00:00.000Z' });
  await assert.rejects(
    store.getSessionRecord({ sessionId: 'revoked-session' }),
    (error) => code(error) === 'session_not_found',
  );
});

test('the slice selects the published skill version', async () => {
  const { store } = harness();
  await publishedSkill(store);
  const selected = await store.getPublishedSkillVersion();
  assert.equal(selected.id, 'skill-1');
  assert.equal(selected.state, 'published');
});

test('revoked and expired sessions cannot create tasks', async () => {
  const { store, database } = harness();
  const expired = await store.createAnonymousSession({ id: 'expired-create', expiresAt: '2020-01-01T00:00:00.000Z' });
  const revoked = await store.createAnonymousSession({ id: 'revoked-create', revokedAt: '2026-11-24T00:00:00.000Z' });
  await publishedSkill(store);
  for (const session of [expired, revoked]) {
    await assert.rejects(
      create(store, session.id),
      (error) => code(error) === 'session_not_found',
    );
  }
  assert.equal(database.data.tasks.size, 0);
  assert.equal(database.data.quotas.size, 0);
});

test('session read requires the owner header to match the path id', async () => {
  const { store } = harness();
  await store.createAnonymousSession({ id: 'owner-session' });
  await store.createAnonymousSession({ id: 'other-session' });
  const handler = createWorkerTaskStoreHandler({ store, workerToken: 'worker-test-secret' });
  const read = (pathId, ownerId) => handler(new Request(`https://site.example/functions/v1/app/internal/task-store/sessions/${pathId}`, {
    headers: { 'x-worker-token': 'worker-test-secret', 'x-session-id': ownerId },
  }));
  const wrong = await read('other-session', 'owner-session');
  assert.equal(wrong.status, 401);
  assert.deepEqual(await wrong.json(), { error: 'session_not_found' });
  const matching = await read('owner-session', 'owner-session');
  assert.equal(matching.status, 200);
  assert.equal((await matching.json()).id, 'owner-session');
});

test('worker routes cover every remaining confirmation card', async () => {
  const { store } = harness();
  const session = await owner(store);
  await publishedSkill(store);
  const created = await create(store, session.id);
  const taskId = created.task.id;
  const handler = createWorkerTaskStoreHandler({ store, workerToken: 'worker-test-secret' });
  const call = (suffix, body) => handler(new Request(
    `https://site.example/functions/v1/app/internal/task-store/tasks/${taskId}${suffix}`,
    {
      method: 'POST',
      headers: { 'x-worker-token': 'worker-test-secret', 'content-type': 'application/json' },
      body: JSON.stringify(body),
    },
  ));
  const answer = async (card, revision, value) => {
    const response = await call(`/answers/${card}`, {
      session_id: session.id, expected_revision: revision, value,
    });
    const text = await response.text();
    assert.equal(response.status, 200, text);
    return JSON.parse(text).task;
  };
  await answer('direction', 1, '肝癌免疫治疗耐药机制');
  await answer('mode', 2, 'A');
  await answer('terms', 3, ['immunotherapy resistance']);
  await answer('years', 4, { choice: 'B' });
  await store.updateTaskState({
    sessionId: session.id, taskId, expectedRevision: 5,
    state: 'adjusting', nextCard: 'adjustment',
  });
  await answer('adjustment', 6, { adjustment: ['continue'] });
  const delivered = await answer('delivery', 7, { form: 'B' });
  assert.equal(delivered.revision, 8);
  assert.equal(delivered.state, 'generating');
  const conflict = await call('/answers/mode', {
    session_id: session.id, expected_revision: 8, value: 'B',
  });
  assert.equal(conflict.status, 422);
  assert.deepEqual(await conflict.json(), { error: 'answer_conflict' });
  const stale = await call('/answers/mode', {
    session_id: session.id, expected_revision: 2, value: 'B',
  });
  assert.equal(stale.status, 409);
  assert.deepEqual(await stale.json(), { error: 'revision_conflict' });
  const unknown = await call('/answers/unknown', {
    session_id: session.id, expected_revision: 8, value: 'x',
  });
  assert.equal(unknown.status, 404);
});

test('Python worker client covers every remaining card route', () => {
  const localVenv = join(ROOT, '.venv', 'bin', 'python');
  const python = existsSync(localVenv) ? localVenv : 'python3';
  const script = String.raw`
import json
import sys
sys.path.insert(0, sys.argv[1])
from app.sites_task_store import SitesTaskStoreClient

calls = []
def transport(url, options):
    calls.append((url, options))
    return {'task': {'id': 'task-1'}, 'changed': True}

client = SitesTaskStoreClient('https://site.example', 'worker-secret', transport=transport)
client.answer_mode('task-1', 'owner-1', 2, 'A')
client.answer_terms('task-1', 'owner-1', 3, ['term one'])
client.answer_years('task-1', 'owner-1', 4, {'choice': 'B'})
client.answer_adjustment('task-1', 'owner-1', 6, {'adjustment': ['continue']})
client.answer_delivery('task-1', 'owner-1', 7, {'form': 'B'})
cards = ['mode', 'terms', 'years', 'adjustment', 'delivery']
assert [url.rsplit('/answers/', 1)[1] for url, options in calls] == cards
assert all(options['method'] == 'POST' for url, options in calls)
assert all(json.loads(options['body'])['session_id'] == 'owner-1' for url, options in calls)
print(json.dumps({'card_routes': len(cards)}))
`;
  const result = spawnSync(python, ['-c', script, join(ROOT, 'backend')], {
    encoding: 'utf8',
    env: {},
    timeout: 20_000,
  });
  assert.equal(result.status, 0, result.stderr || result.stdout);
  assert.deepEqual(JSON.parse(result.stdout), { card_routes: 5 });
});

test('stage enqueue start and complete are idempotent with atomic checkpoint', async () => {
  const { store, database } = harness();
  const session = await owner(store);
  await publishedSkill(store);
  const created = await create(store, session.id);
  const taskId = created.task.id;
  const inputHash = 'c'.repeat(64);
  const queued = await store.enqueueStage({
    sessionId: session.id, taskId, jobId: 'job-search', stage: 'search', inputHash,
    message: '等待检索',
  });
  assert.equal(queued.duplicate, false);
  assert.equal(queued.job.status, 'queued');
  assert.equal(queued.job.revision, 1);
  const replay = await store.enqueueStage({
    sessionId: session.id, taskId, jobId: 'another-job-id', stage: 'search', inputHash,
    message: '等待检索',
  });
  assert.equal(replay.duplicate, true);
  assert.equal(replay.job.id, 'job-search');

  const starts = await Promise.all([
    store.startStage({
      sessionId: session.id, taskId, jobId: 'job-search', expectedJobRevision: 1,
      leaseToken: 'lease-a', message: '开始检索',
    }),
    store.startStage({
      sessionId: session.id, taskId, jobId: 'job-search', expectedJobRevision: 1,
      leaseToken: 'lease-b', message: '开始检索',
    }),
  ]);
  assert.equal(starts.filter((result) => !result.duplicate).length, 1);
  assert.equal(starts.filter((result) => result.duplicate).length, 1);

  await assert.rejects(
    store.completeStage({
      sessionId: session.id, taskId, jobId: 'job-search', expectedJobRevision: 2,
      leaseToken: 'wrong-lease', state: 'dashboard_ready', nextCard: 'adjustment',
      message: '完成', checkpoint: { stage: 'search' },
    }),
    (error) => code(error) === 'revision_conflict',
  );
  const completed = await store.completeStage({
    sessionId: session.id, taskId, jobId: 'job-search', expectedJobRevision: 2,
    leaseToken: starts.find((result) => !result.duplicate).job.lease_token,
    state: 'dashboard_ready', nextCard: 'adjustment', message: '完成',
    checkpoint: { stage: 'search' },
  });
  assert.equal(completed.duplicate, false);
  assert.deepEqual(completed.checkpoint, { stage: 'search' });
  assert.equal(completed.task.state, 'dashboard_ready');
  assert.equal(completed.task.next_card, 'adjustment');
  const duplicate = await store.completeStage({
    sessionId: session.id, taskId, jobId: 'job-search', expectedJobRevision: 2,
    leaseToken: starts.find((result) => !result.duplicate).job.lease_token,
    state: 'dashboard_ready', nextCard: 'adjustment', message: '完成',
    checkpoint: { stage: 'search' },
  });
  assert.equal(duplicate.duplicate, true);
  assert.deepEqual(duplicate.checkpoint, { stage: 'search' });
  const current = await store.getStageJob({ sessionId: session.id, taskId, jobId: 'job-search' });
  assert.equal(current.job.status, 'completed');
  assert.equal(current.job.lease_token, null);
  assert.deepEqual(current.progress.checkpoint, { stage: 'search' });
  assert.deepEqual(current.events.map((event) => event.event_type), [
    'queued', 'started', 'checkpoint', 'completed',
  ]);
  assert.equal(database.data.jobs.size, 1);
});

test('stage completion rolls back every job progress event and task update on failure', async () => {
  const { store, database } = harness();
  const session = await owner(store);
  await publishedSkill(store);
  const created = await create(store, session.id);
  const taskId = created.task.id;
  await store.enqueueStage({
    sessionId: session.id, taskId, jobId: 'job-rollback', stage: 'search',
    inputHash: 'd'.repeat(64), message: '等待检索',
  });
  await store.startStage({
    sessionId: session.id, taskId, jobId: 'job-rollback', expectedJobRevision: 1,
    leaseToken: 'lease-rollback', message: '开始检索',
  });
  database.failNext = {
    operation: 'update_task_after_stage',
    error: new Error('injected task update failure'),
  };
  await assert.rejects(
    store.completeStage({
      sessionId: session.id, taskId, jobId: 'job-rollback', expectedJobRevision: 2,
      leaseToken: 'lease-rollback', state: 'dashboard_ready', nextCard: 'adjustment',
      message: '完成', checkpoint: { stage: 'search' },
    }),
    (error) => code(error) === 'task_store_unavailable',
  );
  const current = await store.getStageJob({ sessionId: session.id, taskId, jobId: 'job-rollback' });
  assert.equal(current.job.status, 'started');
  assert.equal(current.job.lease_token, 'lease-rollback');
  assert.equal(current.progress.checkpoint, null);
  assert.deepEqual(current.events.map((event) => event.event_type), ['queued', 'started']);
  assert.equal((await store.getTask({ sessionId: session.id, taskId })).revision, 1);
});

test('stage failure persists a safe retryable event and next retry time', async () => {
  const { store } = harness();
  const session = await owner(store);
  await publishedSkill(store);
  const created = await create(store, session.id);
  const taskId = created.task.id;
  await store.enqueueStage({
    sessionId: session.id, taskId, jobId: 'job-failure', stage: 'generate',
    inputHash: 'e'.repeat(64), message: '等待生成',
  });
  await store.startStage({
    sessionId: session.id, taskId, jobId: 'job-failure', expectedJobRevision: 1,
    leaseToken: 'lease-failure', message: '开始生成',
  });
  const failed = await store.failStage({
    sessionId: session.id, taskId, jobId: 'job-failure', expectedJobRevision: 2,
    leaseToken: 'lease-failure', eventType: 'rate_limited', message: '请求过于频繁',
    protectedTraceback: 'safe protected traceback', retryAfter: 60,
  });
  assert.equal(failed.job.status, 'failed');
  assert.ok(failed.job.next_retry_at);
  const current = await store.getStageJob({ sessionId: session.id, taskId, jobId: 'job-failure' });
  assert.equal(current.task.state, 'error');
  assert.equal(current.progress.checkpoint, null);
  assert.equal(current.progress.protected_traceback, 'safe protected traceback');
  assert.equal(current.events.at(-1).event_type, 'rate_limited');
  assert.equal(current.events.at(-1).payload.retry_after, 60);
});

test('stage retries are claimed once and exhaust at the configured attempt cap', async () => {
  const { store, database } = harness();
  const session = await owner(store);
  await publishedSkill(store);
  const created = await create(store, session.id);
  const taskId = created.task.id;
  await store.enqueueStage({
    sessionId: session.id, taskId, jobId: 'job-retry', stage: 'generate',
    inputHash: 'f'.repeat(64), message: '等待生成',
  });
  await store.startStage({
    sessionId: session.id, taskId, jobId: 'job-retry', expectedJobRevision: 1,
    leaseToken: 'lease-1', message: '开始生成',
  });
  await store.failStage({
    sessionId: session.id, taskId, jobId: 'job-retry', expectedJobRevision: 2,
    leaseToken: 'lease-1', eventType: 'rate_limited', message: '限流',
    protectedTraceback: null, retryAfter: 60,
  });
  database.data.jobs.get('job-retry').next_retry_at = '2999-01-01T00:00:00.000Z';
  await assert.rejects(
    store.retryStage({
      sessionId: session.id, taskId, jobId: 'job-retry', expectedJobRevision: 3,
      message: '等待重试', maxAttempts: 3,
    }),
    (error) => code(error) === 'retry_not_due',
  );

  let expected = 3;
  for (const lease of ['lease-2', 'lease-3']) {
    database.data.jobs.get('job-retry').next_retry_at = '2020-01-01T00:00:00.000Z';
    const retried = await store.retryStage({
      sessionId: session.id, taskId, jobId: 'job-retry', expectedJobRevision: expected,
      message: '等待重试', maxAttempts: 3,
    });
    assert.equal(retried.exhausted, false);
    assert.equal(retried.job.status, 'queued');
    await store.startStage({
      sessionId: session.id, taskId, jobId: 'job-retry', expectedJobRevision: expected + 1,
      leaseToken: lease, message: '开始生成',
    });
    await store.failStage({
      sessionId: session.id, taskId, jobId: 'job-retry', expectedJobRevision: expected + 2,
      leaseToken: lease, eventType: 'rate_limited', message: '限流',
      protectedTraceback: null, retryAfter: 60,
    });
    expected += 3;
  }

  database.data.jobs.get('job-retry').next_retry_at = '2020-01-01T00:00:00.000Z';
  const exhausted = await store.retryStage({
    sessionId: session.id, taskId, jobId: 'job-retry', expectedJobRevision: expected,
    message: '等待重试', maxAttempts: 3,
  });
  assert.equal(exhausted.exhausted, true);
  assert.equal(exhausted.job.status, 'failed');
  assert.equal(exhausted.task.state, 'error');
  const again = await store.retryStage({
    sessionId: session.id, taskId, jobId: 'job-retry', expectedJobRevision: expected,
    message: '等待重试', maxAttempts: 3,
  });
  assert.equal(again.exhausted, true);
  const current = await store.getStageJob({ sessionId: session.id, taskId, jobId: 'job-retry' });
  assert.equal(current.events.filter((event) => event.event_type === 'retry_exhausted').length, 1);
  assert.equal(current.events.filter((event) => event.event_type === 'retry_scheduled').length, 2);
});
