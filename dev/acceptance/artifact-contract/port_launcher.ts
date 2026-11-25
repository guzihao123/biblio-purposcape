// Acceptance-only launcher: lets the checks bind a port other than 8000
// without touching sites/functions/index.ts.
//
// index.ts calls `Deno.serve(handler)` at module scope, and that default is
// hard-wired to 8000 (the PORT env var is NOT honoured — measured with Deno
// 2.9.8). This shim temporarily wraps Deno.serve so the default port can be
// redirected, then imports the real entrypoint unchanged.
//
//   ACCEPTANCE_PORT=8010 deno run --allow-net --allow-env \
//     --import-map=dev/acceptance/sites-live/stubs/import_map.json \
//     dev/acceptance/artifact-contract/port_launcher.ts
const port = Number(Deno.env.get('ACCEPTANCE_PORT') || 8000);
const originalServe = Deno.serve;

let overridden = false;
try {
  // @ts-ignore acceptance-only reassignment
  Deno.serve = ((first: unknown, second?: unknown) => {
    if (typeof first === 'function') {
      return originalServe({ port, hostname: '127.0.0.1' }, first as Deno.ServeHandler);
    }
    if (first && typeof first === 'object') {
      const options = first as Deno.ServeTcpOptions;
      return originalServe({ ...options, port }, second as Deno.ServeHandler);
    }
    return originalServe(first as Deno.ServeHandler, second as Deno.ServeHandler);
  }) as typeof Deno.serve;
  overridden = Deno.serve !== originalServe;
} catch (error) {
  console.error(`port_launcher: cannot override Deno.serve (${String(error)}); using 8000`);
}

if (overridden) console.error(`port_launcher: serving on 127.0.0.1:${port}`);

await import('../../../sites/functions/index.ts');
