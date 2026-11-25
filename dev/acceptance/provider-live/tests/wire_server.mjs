// Offline acceptance wire server: real sites/functions/task_store.ts worker
// handler (createWorkerTaskStoreHandler + createTaskStore) served over real
// HTTP, backed by the fake adapter in fake_db.mjs. Used to exercise the real
// Python SitesTaskStoreClient over the real urllib transport. Not a real
// Provider: no PostgreSQL, no RLS, no cloud I/O.

import { createServer } from 'node:http';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { createTaskStore, createWorkerTaskStoreHandler } from '../../../../sites/functions/task_store.ts';
import { FakeDatabase } from './fake_db.mjs';

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = join(HERE, '..', '..', '..');

const host = process.env.OFFLINE_WIRE_HOST || '127.0.0.1';
const port = Number(process.env.OFFLINE_WIRE_PORT || 8021);
const workerToken = process.env.OFFLINE_WORKER_SECRET || 'offline-wire-test-secret';

export const database = new FakeDatabase();
let sequence = 0;
const store = createTaskStore({
  database,
  idFactory: () => `wire-${Date.now().toString(36)}-${(++sequence).toString(36)}`,
});
const handler = createWorkerTaskStoreHandler({ store, workerToken });

let httpRequestCount = 0;

const server = createServer(async (req, res) => {
  httpRequestCount += 1;
  // Offline-test-only read-only audit endpoints (never part of the fixed
  // worker surface): quota usage per session and request counters.
  const audit = new URL(req.url, `http://${host}:${port}`);
  if (audit.pathname === '/offline-control/quota') {
    res.writeHead(200, { 'content-type': 'application/json' });
    res.end(JSON.stringify({ used: database.quotaUsed(audit.searchParams.get('session_id') || '') }));
    return;
  }
  if (audit.pathname === '/offline-control/session') {
    const row = database.data.sessions.get(audit.searchParams.get('id') || '') || null;
    res.writeHead(200, { 'content-type': 'application/json' });
    res.end(JSON.stringify(row ? {
      id: row.id, client_ip: row.client_ip, user_agent: row.user_agent,
    } : null));
    return;
  }
  if (audit.pathname === '/offline-control/stats') {
    res.writeHead(200, { 'content-type': 'application/json' });
    res.end(JSON.stringify({ http_requests: httpRequestCount, queries: database.requestCount }));
    return;
  }
  const chunks = [];
  for await (const chunk of req) chunks.push(chunk);
  const body = chunks.length ? new Uint8Array(Buffer.concat(chunks)) : undefined;
  const headers = {};
  for (const [key, value] of Object.entries(req.headers)) {
    if (value !== undefined) headers[key] = Array.isArray(value) ? value.join(', ') : value;
  }
  const request = new Request(`http://${host}:${port}${req.url}`, {
    method: req.method,
    headers,
    ...(body ? { body } : {}),
  });
  try {
    const response = await handler(request);
    const text = await response.text();
    res.writeHead(response.status, Object.fromEntries(response.headers.entries()));
    res.end(text);
  } catch (error) {
    res.writeHead(500, { 'content-type': 'application/json' });
    res.end(JSON.stringify({ error: 'task_store_unavailable' }));
  }
});

server.listen(port, host, () => {
  process.stdout.write(`wire-server-ready ${host}:${port}\n`);
});

for (const signal of ['SIGTERM', 'SIGINT']) {
  process.on(signal, () => server.close(() => process.exit(0)));
}
