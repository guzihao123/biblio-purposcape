// Acceptance-only TCP -> unix-socket relay so the Deno Function can listen on
// a loopback-only unix socket while the static origin proxies to TCP 8025.
import { connect, createServer } from 'node:net';

const LISTEN_PORT = Number(process.env.RELAY_PORT || 8025);
const TARGET_SOCK = process.env.RELAY_TARGET || '/tmp/sites-live-function.sock';

createServer((client) => {
  const remote = connect(TARGET_SOCK, () => {
    client.pipe(remote);
    remote.pipe(client);
  });
  remote.on('error', () => client.destroy());
  client.on('error', () => remote.destroy());
}).listen(LISTEN_PORT, '127.0.0.1', () => {
  console.log(`relay listening on 127.0.0.1:${LISTEN_PORT} -> ${TARGET_SOCK}`);
});
