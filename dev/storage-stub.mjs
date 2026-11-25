// Development-only in-memory storage. Production supplies _qoder/storage.mjs.
const objects = new Map();

function asBytes(value) {
  if (value instanceof Uint8Array) return new Uint8Array(value);
  if (value instanceof ArrayBuffer) return new Uint8Array(value.slice(0));
  if (ArrayBuffer.isView(value)) {
    return new Uint8Array(value.buffer.slice(value.byteOffset, value.byteOffset + value.byteLength));
  }
  throw new TypeError('storage stub expects bytes');
}

export const storage = {
  async upload(path, body, options = {}) {
    const bytes = asBytes(body);
    objects.set(path, {
      bytes,
      contentType: options.contentType || 'application/octet-stream',
    });
    return { ok: true, name: path, size: bytes.byteLength };
  },

  async list(prefix, { limit = 1000, offset = 0 } = {}) {
    return Array.from(objects.keys())
      .filter((name) => name.startsWith(prefix))
      .sort()
      .slice(offset, offset + limit)
      .map((name) => ({
        name,
        size: objects.get(name).bytes.byteLength,
        metadata: { size: objects.get(name).bytes.byteLength },
      }));
  },

  async download(path) {
    const entry = objects.get(path);
    if (!entry) throw new Error(`object not found: ${path}`);
    return new Response(entry.bytes, {
      headers: { 'content-type': entry.contentType },
    });
  },
};
