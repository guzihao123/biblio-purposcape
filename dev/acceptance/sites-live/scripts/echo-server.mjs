// Acceptance-only echo upstream used to verify the Function's request-header
// forwarding whitelist. It returns the header names/values it received so the
// driver can assert that only cookie, user-agent, x-forwarded-for,
// x-admin-token, idempotency-key and content-type are forwarded.
import { createServer } from 'node:http';

const PORT = Number(process.env.ECHO_PORT || 8030);

createServer((req, res) => {
  const chunks = [];
  req.on('data', (chunk) => chunks.push(chunk));
  req.on('end', () => {
    res.writeHead(200, { 'content-type': 'application/json; charset=utf-8', 'cache-control': 'private, no-store' });
    res.end(JSON.stringify({
      method: req.method,
      url: req.url,
      headers: req.headers,
      bodyBytes: Buffer.concat(chunks).length,
    }));
  });
}).listen(PORT, '127.0.0.1', () => {
  console.log(`acceptance echo upstream on http://127.0.0.1:${PORT}`);
});
