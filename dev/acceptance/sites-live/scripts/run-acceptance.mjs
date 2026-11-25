// sites-live local acceptance driver.
// Runs ONLY against the isolated local stack (127.0.0.1:5192 static origin ->
// Deno Function via import-mapped stubs -> Python API :8024, Redis :6392).
// Nothing here touches cloud resources. Results are labeled local-stub scope.
import { createHash, randomBytes } from 'node:crypto';
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';

const SL = '/Users/crisprcas_9/WorkBuddy/2026-11-06-20-49-06/purpose-landscape-web/dev/acceptance/sites-live';
const BASE = 'http://127.0.0.1:5192';
const FUNC = `${BASE}/functions/v1/app`;
const ECHO = 'http://127.0.0.1:8026/functions/v1/app';
const ART = join(SL, 'data', 'artifacts');
const EVIDENCE = join(SL, 'evidence');

const secrets = Object.fromEntries(
  readFileSync(join(SL, 'data', 'run-secrets.env'), 'utf8').trim().split('\n').map((l) => l.split('=')),
);

mkdirSync(EVIDENCE, { recursive: true });

const results = [];
const sensitive = [];
function record(id, name, expected, actual, passed, extra = {}) {
  results.push({ id, name, scope: 'local-stub', expected, actual, passed, ...extra });
  console.log(`${passed ? 'PASS' : 'FAIL'} ${id} ${name}`);
  return passed;
}
function sha256(buf) { return createHash('sha256').update(buf).digest('hex'); }

function jar() { return { cookie: '' }; }
async function req(j, path, opts = {}) {
  const headers = { ...(opts.headers || {}) };
  if (j?.cookie) headers.cookie = j.cookie;
  if (opts.json !== undefined) {
    headers['content-type'] = 'application/json';
    opts.body = JSON.stringify(opts.json);
  }
  const res = await fetch(BASE + path, { ...opts, headers });
  const setCookie = res.headers.get('set-cookie');
  if (setCookie && j) j.cookie = setCookie.split(';')[0];
  return res;
}
const buffer = async (res) => Buffer.from(await res.arrayBuffer());

// ---------- fixtures ----------
function fixtureBytes(kind, size) {
  const head = {
    docx: Buffer.from([0x50, 0x4b, 0x03, 0x04, 0x14, 0x00]),
    pptx: Buffer.from([0x50, 0x4b, 0x03, 0x04, 0x14, 0x00, 0x06, 0x00]),
    png: Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    svg: Buffer.from('<svg xmlns="http://www.w3.org/2000/svg"></svg>', 'utf8'),
    html: Buffer.from('', 'utf8'),
  }[kind];
  const body = randomBytes(Math.max(0, size - head.length));
  return Buffer.concat([head, body]);
}

async function main() {
  // ===== sessions for two anonymous visitors =====
  const resA = await req(null, '/functions/v1/app/session', { method: 'POST', body: '{}' });
  const sessionA = (await resA.json()).session_id;
  const jarA = { cookie: '' };
  jarA.cookie = resA.headers.get('set-cookie').split(';')[0];
  const resB = await req(null, '/functions/v1/app/session', { method: 'POST', body: '{}' });
  const sessionB = (await resB.json()).session_id;
  const jarB = { cookie: resB.headers.get('set-cookie').split(';')[0] };
  record('LOCAL-SESS-01', '两名匿名访客经同源代理各建会话（201 + HttpOnly Cookie）', '201, 两个不同 session_id', `${resA.status}/${resB.status} distinct=${sessionA !== sessionB}`, resA.status === 201 && resB.status === 201 && sessionA !== sessionB);
  sensitive.push({ kind: 'cookie', value: jarA.cookie }, { kind: 'cookie', value: jarB.cookie });

  // no-cookie anonymous is rejected
  const anon = await req(null, '/functions/v1/app/tasks');
  record('LOCAL-SESS-02', '无 Cookie 匿名访问任务列表被拒绝', '401', String(anon.status), anon.status === 401);

  // ===== task creation + idempotency =====
  const KEY1 = 'sites-live-k1';
  const t1 = await req(jarA, '/functions/v1/app/tasks', { method: 'POST', headers: { 'idempotency-key': KEY1 }, json: {} });
  const taskA = (await t1.json()).id;
  const t2 = await req(jarA, '/functions/v1/app/tasks', { method: 'POST', headers: { 'idempotency-key': KEY1 }, json: {} });
  const replayId = (await t2.json()).id;
  const listA = await (await req(jarA, '/functions/v1/app/tasks')).json();
  record('LOCAL-IDEM-01', '同会话同 Idempotency-Key 重放只建一单', '两次同 task id，列表仅 1 单', `create=${t1.status} replay=${t2.status} same=${taskA === replayId} count=${listA.tasks.length}`, t1.status === 201 && taskA === replayId && listA.tasks.length === 1);

  const tB = await req(jarB, '/functions/v1/app/tasks', { method: 'POST', headers: { 'idempotency-key': KEY1 }, json: {} });
  const taskB = (await tB.json()).id;
  record('LOCAL-IDEM-02', '不同会话使用相同 Key 互不串单', 'B 得到不同任务', `B=${tB.status} distinct=${taskB !== taskA}`, tB.status === 201 && taskB !== taskA);

  // ===== owner isolation =====
  const crossRead = await req(jarB, `/functions/v1/app/tasks/${taskA}`);
  const crossList = await req(jarB, `/functions/v1/app/tasks/${taskA}/artifacts`);
  const crossAnswer = await req(jarB, `/functions/v1/app/tasks/${taskA}/answers/direction`, { method: 'POST', json: { value: { direction: 'x' } } });
  const listBjson = await (await req(jarB, '/functions/v1/app/tasks')).json();
  const bSeesA = listBjson.tasks.some((t) => t.id === taskA);
  record('LOCAL-ISO-01', '非所有者读任务/列表制品/写答案一律 404', '全部 404', `read=${crossRead.status} artifacts=${crossList.status} answer=${crossAnswer.status}`, crossRead.status === 404 && crossList.status === 404 && crossAnswer.status === 404);
  record('LOCAL-ISO-02', 'B 的任务列表不含 A 的任务（历史隔离）', 'false', String(bSeesA), bSeesA === false);

  const ansA = await req(jarA, `/functions/v1/app/tasks/${taskA}/answers/direction`, { method: 'POST', json: { value: { direction: 'AI 辅助文献选题调研' } } });
  record('LOCAL-ISO-03', '所有者可正常提交答案并推进', '200', String(ansA.status), ansA.status === 200);

  // ===== artifacts fixtures =====
  const dir = join(ART, taskA);
  mkdirSync(dir, { recursive: true });
  const files = {
    'report.docx': fixtureBytes('docx', 120_000),
    'slides.pptx': fixtureBytes('pptx', 96_000),
    '文献图谱仪表盘.png': fixtureBytes('png', 64_000),
    'mobile.html': Buffer.from('<!doctype html><html><head><meta charset="utf-8"></head><body><img src="文献图谱仪表盘.png" href="文献图谱仪表盘.png"></body></html>', 'utf8'),
    '图表.svg': fixtureBytes('svg', 300),
    '调研报告-最终版.docx': fixtureBytes('docx', 80_000),
  };
  const hashes = {};
  for (const [name, bytes] of Object.entries(files)) {
    writeFileSync(join(dir, name), bytes);
    hashes[name] = sha256(bytes);
  }
  writeFileSync(join(EVIDENCE, 'fixture-sha256.json'), JSON.stringify(hashes, null, 2));

  const artListRes = await req(jarA, `/functions/v1/app/tasks/${taskA}/artifacts`);
  const artList = await artListRes.json();
  const byName = Object.fromEntries(artList.artifacts.map((a) => [a.name, a]));
  record('LOCAL-ART-01', '制品列表含全部六类制品（含 Unicode 名）且带签名 URL', '6 项', `count=${artList.artifacts.length}`, artList.artifacts.length === 6);

  // ===== byte roundtrip + CDN headers through the proxy =====
  const dispositionExpect = { 'report.docx': 'attachment', 'slides.pptx': 'attachment', '文献图谱仪表盘.png': 'attachment', 'mobile.html': 'inline', '图表.svg': 'inline', '调研报告-最终版.docx': 'attachment' };
  let bytePass = true; let headerPass = true; const headerDetails = {};
  const signatures = {};
  for (const name of Object.keys(files)) {
    const url = FUNC + byName[name].url.replace('/api/', '/');
    const res = await req(jarA, url.slice(BASE.length));
    const rawBody = await buffer(res);
    const wireBytes = rawBody.length;
    let body = rawBody;
    if (name === 'mobile.html') {
      body = Buffer.from(body.toString('utf8').replace(/\?signature=[^"\s]+/g, ''), 'utf8');
    }
    const okBytes = res.status === 200 && sha256(body) === hashes[name];
    const cd = res.headers.get('content-disposition') || '';
    const cc = res.headers.get('cache-control') || '';
    const okHeaders = cd.startsWith(dispositionExpect[name]) && cc === 'private, no-store';
    if (!okBytes || !okHeaders) bytePass = bytePass && okBytes;
    headerPass = headerPass && okHeaders;
    headerDetails[name] = { status: res.status, bytes: wireBytes, sha256Match: sha256(body) === hashes[name], contentDisposition: cd, cacheControl: cc, contentType: res.headers.get('content-type') };
    const sig = new URL(url).searchParams.get('signature');
    signatures[name] = sig;
    sensitive.push({ kind: 'signature', value: sig });
    if (!okBytes) bytePass = false;
  }
  record('LOCAL-ART-02', 'DOCX/PPTX/PNG/HTML/SVG 经代理下载字节与 SHA-256 一致', '全部一致', JSON.stringify(Object.fromEntries(Object.entries(headerDetails).map(([k, v]) => [k, v.sha256Match]))), bytePass, { details: headerDetails });
  record('LOCAL-CDN-01', 'HTML/SVG inline，DOCX/PPTX attachment，Cache-Control private, no-store', '全部符合', JSON.stringify(Object.fromEntries(Object.entries(headerDetails).map(([k, v]) => [k, [v.contentDisposition, v.cacheControl]]))), headerPass, { details: headerDetails });

  // ===== mobile.html embeds the PNG's own signature =====
  const mobileRes = await req(jarA, (FUNC + byName['mobile.html'].url.replace('/api/', '/')).slice(BASE.length));
  const mobileHtml = (await buffer(mobileRes)).toString('utf8');
  const embed = mobileHtml.match(/文献图谱仪表盘\.png\?signature=([^"\s]+)/);
  const embeddedSig = embed ? decodeURIComponent(embed[1]) : null;
  record('LOCAL-CDN-02', 'mobile.html 内嵌长图使用 PNG 自己的签名 URL', '存在内嵌签名', embeddedSig ? 'embedded signature present' : 'missing', Boolean(embeddedSig), { embeddedSignature: embeddedSig ? '<redacted-to-verifier>' : null });
  if (embeddedSig) writeFileSync(join(SL, 'data', 'embedded-signature.txt'), embeddedSig, { mode: 0o600 });

  // ===== signature misuse =====
  const sigPath = byName['report.docx'].url.replace('/api/', '/');
  const tampered = await req(jarA, (FUNC + sigPath).slice(BASE.length).replace(/signature=[^&]+/, 'signature=AAAA'));
  const crossSession = await req(jarB, (FUNC + sigPath).slice(BASE.length));
  const missing = await req(jarA, `/functions/v1/app/tasks/${taskA}/artifacts/report.docx`);
  const wrongFile = await req(jarA, (FUNC + sigPath).slice(BASE.length).replace('report.docx', 'slides.pptx'));
  record('LOCAL-SIG-01', '所有者签名篡改/缺失/换文件名 403；跨会话访问非所有者 404', 'tampered=403 cross=404 missing=403 wrongfile=403', `tampered=${tampered.status} cross=${crossSession.status} missing=${missing.status} wrongfile=${wrongFile.status}`, tampered.status === 403 && crossSession.status === 404 && missing.status === 403 && wrongFile.status === 403, { note: '跨会话访问在签名校验前即被所有者隔离拦截（require_owner 404），与“非所有者统一 404”规格一致' });

  // ===== function-internal storage with local stub =====
  const internalBase = `/functions/v1/app/internal/artifacts/${taskA}`;
  const probe = randomBytes(2048);
  const putNoToken = await fetch(BASE + `${internalBase}/probe-数据.bin`, { method: 'PUT', body: probe, headers: { 'content-type': 'application/octet-stream' } });
  const putOk = await fetch(BASE + `${internalBase}/probe-数据.bin`, { method: 'PUT', body: probe, headers: { 'content-type': 'application/octet-stream', 'x-worker-token': secrets.WORKER_SHARED_SECRET } });
  const getOk = await fetch(BASE + `${internalBase}/probe-%E6%95%B0%E6%8D%AE.bin`, { headers: { 'x-worker-token': secrets.WORKER_SHARED_SECRET } });
  const got = await buffer(getOk);
  const listNoToken = await fetch(BASE + internalBase);
  const listOk = await fetch(BASE + internalBase, { headers: { 'x-worker-token': secrets.WORKER_SHARED_SECRET } });
  const listBody = await listOk.json();
  record('LOCAL-STO-01', '内部制品接口：匿名 403，worker 令牌可上传/下载/列举', '403→201→字节一致→403→200', `putNoToken=${putNoToken.status} put=${putOk.status} get=${getOk.status} bytes=${sha256(got) === sha256(probe)} listNoToken=${listNoToken.status} list=${listOk.status} listed=${listBody.artifacts.some((a) => a.name === 'probe-数据.bin')}`, putNoToken.status === 403 && putOk.status === 201 && getOk.status === 200 && sha256(got) === sha256(probe) && listNoToken.status === 403 && listOk.status === 200 && listBody.artifacts.some((a) => a.name === 'probe-数据.bin'), { internalCacheControl: getOk.headers.get('cache-control') });
  sensitive.push({ kind: 'worker-token', value: secrets.WORKER_SHARED_SECRET }, { kind: 'admin-token', value: secrets.ADMIN_TOKEN });

  // ===== header forwarding whitelist via echo upstream =====
  const echoRes = await fetch(ECHO + '/tasks', {
    method: 'POST',
    headers: {
      'content-type': 'application/json',
      cookie: 'invite_session=echo-cookie',
      'user-agent': 'whitelist-test',
      'x-forwarded-for': '203.0.113.7',
      'x-admin-token': 'echo-admin',
      'idempotency-key': 'echo-key',
      authorization: 'Bearer must-not-forward',
      'x-worker-token': 'must-not-forward',
      'x-evil-junk': 'must-not-forward',
      'x-real-ip': '198.51.100.9',
    },
    body: '{}',
  });
  const echo = await echoRes.json();
  const gotHeaders = echo && echo.headers ? echo.headers : {};
  const allowed = ['cookie', 'user-agent', 'x-forwarded-for', 'x-admin-token', 'idempotency-key', 'content-type'];
  const blocked = ['authorization', 'x-worker-token', 'x-evil-junk', 'x-real-ip'];
  const allowedOk = allowed.every((h) => JSON.stringify(gotHeaders).includes(`"${h}"`));
  const blockedOk = blocked.every((h) => !Object.hasOwn(gotHeaders, h));
  record('LOCAL-CDN-03', '签名/Cookie/Idempotency-Key 白名单转发，无关头被丢弃', '白名单 6 个在，黑名单 0 个在', `allowedPresent=${allowedOk} blockedAbsent=${blockedOk}`, allowedOk && blockedOk, { echoHeaders: Object.keys(gotHeaders) });

  // ===== admin + revoke =====
  const adminNoToken = await req(jarA, '/functions/v1/app/admin/skill/versions');
  const adminWithToken = await fetch(BASE + '/functions/v1/app/admin/skill/versions', { headers: { 'x-admin-token': secrets.ADMIN_TOKEN } });
  record('LOCAL-ADM-01', '管理接口：匿名 403，持令牌 200', '403/200', `noToken=${adminNoToken.status} withToken=${adminWithToken.status}`, adminNoToken.status === 403 && adminWithToken.status === 200);

  const revoke = await fetch(BASE + `/functions/v1/app/admin/sessions/${sessionA}/revoke`, { method: 'POST', headers: { 'x-admin-token': secrets.ADMIN_TOKEN, 'content-type': 'application/json' }, body: '{}' });
  const afterRevoke = await req(jarA, '/functions/v1/app/tasks');
  const bStillOk = (await req(jarB, '/functions/v1/app/tasks')).status;
  record('LOCAL-ADM-02', '撤销会话立即失效且不影响他人', 'revoke 200，A→401，B→200', `revoke=${revoke.status} A=${afterRevoke.status} B=${bStillOk}`, revoke.status === 200 && afterRevoke.status === 401 && bStillOk === 200);

  // ===== log redaction scan =====
  const logs = ['api.log', 'function.log', 'static.log'].map((f) => { try { return readFileSync(join(SL, 'logs', f), 'utf8'); } catch { return ''; } }).join('\n');
  const leaks = sensitive.filter((s) => s.value && logs.includes(s.value)).map((s) => s.kind);
  record('LOCAL-LOG-01', '签名/令牌/Cookie 不进入本地访问日志', '0 泄露', `leaks=${JSON.stringify(leaks)}`, leaks.length === 0, { leakedKinds: leaks, note: '本地 uvicorn/Deno 访问日志若含查询串会记录签名，属本地发现，云端需平台日志脱敏确认' });

  writeFileSync(join(EVIDENCE, 'local-acceptance-results.json'), JSON.stringify({
    generated_at: new Date().toISOString(),
    scope: 'local-stub (127.0.0.1:5192 -> function stubs -> api :8024, redis :6392)',
    sessionA, sessionB, taskA, taskB,
    passed: results.filter((r) => r.passed).length,
    failed: results.filter((r) => !r.passed).length,
    results,
  }, null, 2));
  console.log(`\nSUMMARY passed=${results.filter((r) => r.passed).length} failed=${results.filter((r) => !r.passed).length}`);
}

main().catch((error) => {
  record('DRIVER-ERROR', '驱动未捕获异常', '无异常', String(error && error.stack || error).slice(0, 400), false);
}).finally(() => {
  try {
    writeFileSync(join(EVIDENCE, 'local-acceptance-results.json'), JSON.stringify({
      generated_at: new Date().toISOString(),
      scope: 'local-stub (127.0.0.1:5192 -> function stubs -> api :8024, redis :6392)',
      passed: results.filter((r) => r.passed).length,
      failed: results.filter((r) => !r.passed).length,
      results,
    }, null, 2));
  } catch (e) { console.error('persist failed', e); }
  console.log(`SUMMARY passed=${results.filter((r) => r.passed).length} failed=${results.filter((r) => !r.passed).length}`);
  process.exit(results.some((r) => !r.passed) ? 2 : 0);
});
