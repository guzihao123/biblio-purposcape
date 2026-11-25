// Acceptance-only static origin server for the local Qoder Sites rehearsal.
// Serves frontend/dist with SPA fallback on 5192 and proxies
// /functions/v1/app/* to the local Deno Function origin (default 8025),
// mirroring the Qoder Sites same-origin static + Functions layout.
import { createServer } from 'node:http';
import { readFile } from 'node:fs/promises';
import { extname, join, normalize } from 'node:path';

const DIST = process.env.ACCEPTANCE_DIST
  || '/Users/crisprcas_9/WorkBuddy/2026-11-06-20-49-06/purpose-landscape-web/frontend/dist';
const PORT = Number(process.env.ACCEPTANCE_STATIC_PORT || 5192);
const FUNCTION_ORIGIN = process.env.ACCEPTANCE_FUNCTION_ORIGIN || 'http://127.0.0.1:8025';
const MARKER = '/functions/v1/app';

const MIME = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.png': 'image/png',
  '.json': 'application/json; charset=utf-8',
};

createServer(async (req, res) => {
  const url = new URL(req.url, 'http://127.0.0.1');
  if (url.pathname.startsWith(MARKER)) {
    try {
      const target = FUNCTION_ORIGIN + url.pathname + url.search;
      const headers = { ...req.headers };
      delete headers.host;
      delete headers.connection;
      const hasBody = req.method !== 'GET' && req.method !== 'HEAD';
      const upstream = await fetch(target, {
        method: req.method,
        headers,
        ...(hasBody ? { body: req, duplex: 'half' } : {}),
      });
      const outHeaders = {};
      upstream.headers.forEach((value, name) => {
        if (['content-type', 'cache-control', 'content-disposition', 'content-length', 'set-cookie', 'retry-after'].includes(name)) {
          outHeaders[name] = value;
        }
      });
      res.writeHead(upstream.status, outHeaders);
      const buffer = Buffer.from(await upstream.arrayBuffer());
      res.end(buffer);
    } catch (error) {
      res.writeHead(502, { 'content-type': 'application/json; charset=utf-8' });
      res.end(JSON.stringify({ error: 'function_upstream_unavailable' }));
    }
    return;
  }
  const pathname = decodeURIComponent(url.pathname);
  let filePath = normalize(join(DIST, pathname));
  if (!filePath.startsWith(normalize(DIST))) {
    res.writeHead(403).end('forbidden');
    return;
  }
  let body;
  try {
    body = await readFile(filePath);
  } catch {
    try {
      body = await readFile(join(DIST, 'index.html'));
      res.writeHead(200, { 'content-type': MIME['.html'], 'cache-control': 'no-store' });
      res.end(body);
      return;
    } catch {
      res.writeHead(404).end('not found');
      return;
    }
  }
  const mime = MIME[extname(filePath)] || 'application/octet-stream';
  res.writeHead(200, { 'content-type': mime, 'cache-control': 'no-store' });
  res.end(body);
}).listen(PORT, '127.0.0.1', () => {
  console.log(`acceptance static origin on http://127.0.0.1:${PORT} (functions -> ${FUNCTION_ORIGIN})`);
});
