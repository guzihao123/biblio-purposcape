import { createPlatformTaskStore, createWorkerTaskStoreHandler } from './task_store.ts';

type TaskStoreHandler = ReturnType<typeof createWorkerTaskStoreHandler>;
type PlatformTaskStore = Awaited<ReturnType<typeof createPlatformTaskStore>>;

interface StorageEntry {
  name: string;
  size?: number;
  metadata?: { size?: number };
}

interface StorageDriver {
  upload(path: string, body: Uint8Array, options: { contentType: string; upsert: boolean }): Promise<unknown>;
  list(prefix: string, options?: { limit?: number; offset?: number }): Promise<StorageEntry[]>;
  download(path: string): Promise<Response>;
}

declare global {
  var __LANDSCAPE_TASK_STORE__: PlatformTaskStore | undefined;
  var __LANDSCAPE_STORAGE__: StorageDriver | undefined;
}

const JSON_HEADERS = { 'content-type': 'application/json; charset=utf-8' };
const MAX_BODY_BYTES = 50_000_000;
const MAX_ANSWER_BODY_BYTES = 64 * 1024;
let taskStoreHandler: TaskStoreHandler | undefined;

async function handleTaskStore(request: Request): Promise<Response> {
  if (!taskStoreHandler) {
    const store = globalThis.__LANDSCAPE_TASK_STORE__ || await createPlatformTaskStore();
    taskStoreHandler = createWorkerTaskStoreHandler({ store });
  }
  return taskStoreHandler(request);
}

function json(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), { status, headers: JSON_HEADERS });
}

function apiOrigin() {
  return (Deno.env.get('PYTHON_API_ORIGIN') || '').replace(/\/+$/, '');
}

function routeSuffix(url: URL): string {
  const marker = '/functions/v1/app';
  const index = url.pathname.indexOf(marker);
  if (index >= 0) {
    const suffix = url.pathname.slice(index + marker.length) || '/';
    if (suffix !== '/') return suffix;
  }
  const action = url.searchParams.get('action') || 'health';
  if (action === 'session') return '/session';
  if (action === 'task') return `/tasks/${url.searchParams.get('id') || ''}`;
  return '/health';
}

function limitedStream(
  stream: ReadableStream<Uint8Array> | null,
): ReadableStream<Uint8Array> | null {
  if (!stream) return null;
  let received = 0;
  return stream.pipeThrough(new TransformStream<Uint8Array, Uint8Array>({
    transform(chunk, controller) {
      received += chunk.byteLength;
      if (received > MAX_BODY_BYTES) controller.error(new Error('upstream_response_too_large'));
      else controller.enqueue(chunk);
    },
  }));
}

interface ForwardInit {
  method?: string;
  body?: BodyInit;
  headers?: Record<string, string>;
}

async function forward(path: string, init: ForwardInit = {}): Promise<Response> {
  const origin = apiOrigin();
  if (!origin) return json({ error: 'python_api_not_configured' }, 503);
  const headers: Record<string, string> = {};
  for (const name of ['cookie', 'user-agent', 'x-forwarded-for', 'x-admin-token']) {
    if (init.headers && Object.hasOwn(init.headers, name)) headers[name] = init.headers[name] || '';
  }
  const idempotencyKey = init.headers?.['idempotency-key'];
  if (idempotencyKey !== undefined && idempotencyKey !== null) {
    headers['idempotency-key'] = idempotencyKey;
  }
  if (init.body !== undefined) headers['content-type'] = init.headers?.['content-type'] || 'application/json';
  const response = await fetch(`${origin}${path}`, {
    method: init.method || 'GET',
    body: init.body,
    redirect: 'error',
    headers,
  });
  const declaredBytes = Number(response.headers.get('content-length') || 0);
  if (declaredBytes > MAX_BODY_BYTES) return json({ error: 'upstream_response_too_large' }, 502);
  const responseHeaders = new Headers({
    'content-type': response.headers.get('content-type') || 'application/octet-stream',
    'cache-control': response.headers.get('cache-control') || 'no-store',
  });
  const setCookie = response.headers.get('set-cookie');
  if (setCookie) responseHeaders.set('set-cookie', setCookie);
  const disposition = response.headers.get('content-disposition');
  if (disposition) responseHeaders.set('content-disposition', disposition);
  return new Response(limitedStream(response.body), {
    status: response.status,
    headers: responseHeaders,
  });
}

class RequestBodyTooLargeError extends Error {}

async function requestBody(
  request: Request,
  maxBytes = MAX_BODY_BYTES,
): Promise<Uint8Array<ArrayBuffer>> {
  const declaredBytes = Number(request.headers.get('content-length') || 0);
  if (declaredBytes > maxBytes) throw new RequestBodyTooLargeError('request_too_large');
  const bytes = new Uint8Array(await request.arrayBuffer());
  if (bytes.byteLength > maxBytes) throw new RequestBodyTooLargeError('request_too_large');
  return bytes;
}

function forwardedInit(request: Request, method: string, body?: BodyInit): ForwardInit {
  const headers: Record<string, string> = {
    cookie: request.headers.get('cookie') || '',
    'user-agent': request.headers.get('user-agent') || '',
    'x-forwarded-for': request.headers.get('x-forwarded-for') || request.headers.get('x-real-ip') || '',
    'x-admin-token': request.headers.get('x-admin-token') || '',
    'content-type': request.headers.get('content-type') || 'application/json',
  };
  const idempotencyKey = request.headers.get('idempotency-key');
  // Keep absence intact so old clients retain the API's key-generation behavior.
  if (idempotencyKey !== null) headers['idempotency-key'] = idempotencyKey;
  return { method, body, headers };
}

async function digest(value: string | Uint8Array<ArrayBuffer>): Promise<string> {
  const input = typeof value === 'string' ? new TextEncoder().encode(value) : value;
  const bytes = await crypto.subtle.digest('SHA-256', input);
  return Array.from(new Uint8Array(bytes), (byte) => byte.toString(16).padStart(2, '0')).join('');
}

async function workerAuthorized(request: Request): Promise<boolean> {
  const expected = await digest(Deno.env.get('WORKER_SHARED_SECRET') || '');
  const supplied = await digest(request.headers.get('x-worker-token') || '');
  if (expected.length !== supplied.length || !expected) return false;
  let difference = 0;
  for (let index = 0; index < expected.length; index += 1) {
    difference |= expected.charCodeAt(index) ^ supplied.charCodeAt(index);
  }
  return difference === 0 && Boolean(Deno.env.get('WORKER_SHARED_SECRET'));
}

async function storageDriver(): Promise<StorageDriver> {
  if (globalThis.__LANDSCAPE_STORAGE__) return globalThis.__LANDSCAPE_STORAGE__;
  return (await import('./_qoder/storage.mjs')).storage;
}

function internalArtifactPath(
  path: string,
): { taskId: string; filename: string; objectPath: string } | null {
  const match = path.match(/^\/internal\/artifacts\/([A-Za-z0-9-]{1,64})\/([^/]+)$/);
  if (!match) return null;
  let filename: string;
  try {
    filename = decodeURIComponent(match[2]);
  } catch {
    return null;
  }
  if (!filename || filename.includes('..') || filename.includes('/') || filename.includes('\\')) return null;
  return { taskId: match[1], filename, objectPath: `artifacts/${match[1]}/${filename}` };
}

function internalChecksumPath(path: string): string | null {
  const match = path.match(/^\/internal\/artifact-checksums\/([A-Za-z0-9-]{1,64})\/([^/]+)$/);
  if (!match) return null;
  let filename: string;
  try {
    filename = decodeURIComponent(match[2]);
  } catch {
    return null;
  }
  if (!filename || filename.includes('..') || filename.includes('/') || filename.includes('\\')) return null;
  return `artifact-checksums/${match[1]}/${filename}`;
}

Deno.serve(async (request) => {
  const url = new URL(request.url);
  const path = routeSuffix(url);
  const method = request.method;

  if (method === 'GET' && path === '/health') {
    return json({ status: 'ok', python_api_configured: Boolean(apiOrigin()) });
  }

  const collection = path.match(/^\/internal\/artifacts\/([A-Za-z0-9-]{1,64})$/);
  if (path.startsWith('/internal/task-store/')) {
    return handleTaskStore(request);
  }
  if (collection) {
    if (!await workerAuthorized(request)) return json({ error: 'worker_unauthorized' }, 403);
    if (method !== 'GET') return json({ error: 'method_not_allowed' }, 405);
    const storage = await storageDriver();
    const prefix = `artifacts/${collection[1]}`;
    const entries = await storage.list(prefix, { limit: 1000, offset: 0 });
    return json({
      artifacts: entries.map((entry) => ({
        name: entry.name.slice(prefix.length + 1),
        size: entry.metadata?.size ?? entry.size ?? 0,
      })),
    });
  }

  const internal = internalArtifactPath(path);
  if (internal) {
    if (!await workerAuthorized(request)) return json({ error: 'worker_unauthorized' }, 403);
    const storage = await storageDriver();
    if (method === 'PUT') {
      const body = await requestBody(request);
      const checksum = await digest(body);
      const suppliedChecksum = request.headers.get('x-artifact-sha256');
      if (suppliedChecksum && suppliedChecksum !== checksum) {
        return json({ error: 'artifact_checksum_mismatch' }, 422);
      }
      await storage.upload(
        `artifact-checksums/${internal.taskId}/${internal.filename}`,
        new TextEncoder().encode(checksum),
        { contentType: 'text/plain; charset=utf-8', upsert: true },
      );
      await storage.upload(internal.objectPath, body, {
        contentType: request.headers.get('content-type') || 'application/octet-stream',
        upsert: true,
      });
      return json({ ok: true, name: internal.filename, size: body.byteLength }, 201);
    }
    if (method === 'GET') {
      const file = await storage.download(internal.objectPath);
      return new Response(file.body, {
        headers: {
          'content-type': file.headers.get('content-type') || 'application/octet-stream',
          'cache-control': 'private, no-store',
        },
      });
    }
    return json({ error: 'method_not_allowed' }, 405);
  }

  const checksumPath = internalChecksumPath(path);
  if (checksumPath) {
    if (!await workerAuthorized(request)) return json({ error: 'worker_unauthorized' }, 403);
    if (method !== 'GET') return json({ error: 'method_not_allowed' }, 405);
    const storage = await storageDriver();
    const file = await storage.download(checksumPath);
    return new Response(file.body, {
      headers: {
        'content-type': 'text/plain; charset=utf-8',
        'cache-control': 'private, no-store',
      },
    });
  }

  if (method === 'POST' && path === '/session') {
    return forward('/api/session', forwardedInit(request, 'POST', '{}'));
  }
  if (path === '/tasks' && (method === 'GET' || method === 'POST')) {
    const body = method === 'POST' ? '{}' : undefined;
    return forward('/api/tasks', forwardedInit(request, method, body));
  }

  let match = path.match(/^\/tasks\/([0-9a-f-]{36})$/i);
  if (method === 'GET' && match) {
    return forward(`/api/tasks/${match[1]}`, forwardedInit(request, 'GET'));
  }

  match = path.match(/^\/tasks\/([0-9a-f-]{36})\/answers\/(direction|mode|terms|years|adjustment|delivery)$/i);
  if (method === 'POST' && match) {
    let body: Uint8Array<ArrayBuffer>;
    try {
      body = await requestBody(request, MAX_ANSWER_BODY_BYTES);
    } catch (error) {
      if (error instanceof RequestBodyTooLargeError) {
        return json({ error: 'answer_body_too_large' }, 413);
      }
      throw error;
    }
    return forward(`/api/tasks/${match[1]}/answers/${match[2]}`, forwardedInit(request, 'POST', body));
  }

  match = path.match(/^\/tasks\/([0-9a-f-]{36})\/dashboard$/i);
  if (method === 'GET' && match) {
    return forward(`/api/tasks/${match[1]}/dashboard`, forwardedInit(request, 'GET'));
  }
  match = path.match(/^\/tasks\/([0-9a-f-]{36})\/report$/i);
  if (method === 'GET' && match) {
    return forward(`/api/tasks/${match[1]}/report`, forwardedInit(request, 'GET'));
  }
  match = path.match(/^\/tasks\/([0-9a-f-]{36})\/artifacts$/i);
  if (method === 'GET' && match) {
    return forward(`/api/tasks/${match[1]}/artifacts`, forwardedInit(request, 'GET'));
  }

  match = path.match(/^\/tasks\/([0-9a-f-]{36})\/artifacts\/([^/]+)$/i);
  if (method === 'GET' && match) {
    return forward(`/api/tasks/${match[1]}/artifacts/${match[2]}${url.search}`, forwardedInit(request, 'GET'));
  }

  if (path === '/admin/skill/versions' && method === 'GET') {
    return forward('/api/admin/skill/versions', forwardedInit(request, 'GET'));
  }
  if (path === '/admin/skill/drafts' && method === 'POST') {
    return forward('/api/admin/skill/drafts', forwardedInit(request, 'POST', await requestBody(request)));
  }
  match = path.match(/^\/admin\/skill\/versions\/([0-9a-f-]{36})\/(regression|publish|rollback)$/i);
  if (method === 'POST' && match) {
    return forward(`/api/admin/skill/versions/${match[1]}/${match[2]}`, forwardedInit(request, 'POST', '{}'));
  }

  match = path.match(/^\/admin\/sessions\/([0-9a-f-]{36})\/revoke$/i);
  if (method === 'POST' && match) {
    return forward(`/api/admin/sessions/${match[1]}/revoke`, {
      method: 'POST',
      body: '{}',
      headers: { 'x-admin-token': request.headers.get('x-admin-token') || '' },
    });
  }

  return json({ error: 'not_found' }, 404);
});
