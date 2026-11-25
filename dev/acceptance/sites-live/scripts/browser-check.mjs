// Real-browser local rehearsal: two fresh anonymous contexts (A desktop,
// B narrow) against the isolated local origin. Golden flow, narrow screen,
// cross-user 404, and an in-browser artifact download byte check.
import { createHash, randomBytes } from 'node:crypto';
import { mkdirSync, writeFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { join } from 'node:path';

const require = createRequire('/Users/crisprcas_9/WorkBuddy/2026-11-06-20-49-06/purpose-landscape-web/frontend/package.json');
const { chromium } = require('playwright');

const SL = '/Users/crisprcas_9/WorkBuddy/2026-11-06-20-49-06/purpose-landscape-web/dev/acceptance/sites-live';
const BASE = 'http://127.0.0.1:5192';
const SHOTS = join(SL, 'screenshots');
mkdirSync(SHOTS, { recursive: true });

const results = [];
function record(id, name, expected, actual, passed, extra = {}) {
  results.push({ id, name, scope: 'local-browser', expected, actual, passed, ...extra });
  console.log(`${passed ? 'PASS' : 'FAIL'} ${id}`);
}

async function main() {
  const browser = await chromium.launch();

  // ---- Visitor A: desktop golden flow ----
  const ctxA = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const pageA = await ctxA.newPage();
  await pageA.goto(BASE + '/', { waitUntil: 'networkidle' });
  const inviteVisible = await pageA.getByRole('button', { name: '开始研究' }).isVisible();
  await pageA.screenshot({ path: join(SHOTS, 'a1-invite-desktop.png'), fullPage: true });
  await pageA.getByRole('button', { name: '开始研究' }).click();
  await pageA.waitForURL(/\/tasks\/[0-9a-f-]{36}/, { timeout: 15000 });
  const taskUrlA = pageA.url();
  const taskIdA = taskUrlA.match(/\/tasks\/([0-9a-f-]{36})/)[1];
  await pageA.waitForLoadState('networkidle');
  await pageA.screenshot({ path: join(SHOTS, 'a2-task-desktop.png'), fullPage: true });
  record('LOCAL-BRW-01', '访客 A 桌面黄金流程：公开入口→建会话→自动进入任务流程', 'InvitePage→/tasks/<uuid>', taskUrlA, inviteVisible && /\/tasks\/[0-9a-f-]{36}/.test(taskUrlA));

  await pageA.getByRole('button', { name: '研究历史' }).click();
  await pageA.waitForURL(/\/history/);
  await pageA.waitForSelector('.history-item', { timeout: 10000 });
  const historyBody = await pageA.textContent('body');
  await pageA.screenshot({ path: join(SHOTS, 'a3-history-desktop.png'), fullPage: true });
  record('LOCAL-BRW-02', '访客 A 研究历史只包含自己的任务', '包含 taskIdA', `contains=${historyBody.includes(taskIdA.slice(0, 8))}`, historyBody.includes(taskIdA.slice(0, 8)), { url: '/history' });

  // Give A's task an artifact, then download it inside the browser.
  const artDir = join(SL, 'data', 'artifacts', taskIdA);
  mkdirSync(artDir, { recursive: true });
  const docx = Buffer.concat([Buffer.from([0x50, 0x4b, 0x03, 0x04]), randomBytes(48_000)]);
  writeFileSync(join(artDir, 'report.docx'), docx);
  const listRes = await pageA.request.get(`${BASE}/functions/v1/app/tasks/${taskIdA}/artifacts`);
  const list = await listRes.json();
  const artUrl = list.artifacts.find((a) => a.name === 'report.docx').url.replace(/^\/api\//, '/functions/v1/app/');
  const dl = await pageA.request.get(BASE + artUrl);
  const dlBytes = Buffer.from(await dl.body());
  record('LOCAL-BRW-03', '浏览器内携带 HttpOnly Cookie 下载制品字节一致', '200 + sha256 一致', `status=${dl.status()} bytes=${dlBytes.length}`, dl.status() === 200 && createHash('sha256').update(dlBytes).digest('hex') === createHash('sha256').update(docx).digest('hex'), { contentDisposition: dl.headers()['content-disposition'], cacheControl: dl.headers()['cache-control'] });

  // ---- Visitor B: narrow screen, fresh context ----
  const ctxB = await browser.newContext({ viewport: { width: 390, height: 844 } });
  const pageB = await ctxB.newPage();
  await pageB.goto(BASE + '/', { waitUntil: 'networkidle' });
  await pageB.screenshot({ path: join(SHOTS, 'b1-invite-narrow.png'), fullPage: true });
  await pageB.getByRole('button', { name: '开始研究' }).click();
  await pageB.waitForURL(/\/tasks\/[0-9a-f-]{36}/, { timeout: 15000 });
  await pageB.waitForLoadState('networkidle');
  await pageB.screenshot({ path: join(SHOTS, 'b2-task-narrow.png'), fullPage: true });
  const bUrl = pageB.url();
  record('LOCAL-BRW-04', '访客 B 窄屏独立上下文黄金流程', 'InvitePage→/tasks/<uuid>', bUrl, /\/tasks\/[0-9a-f-]{36}/.test(bUrl) && bUrl !== taskUrlA);

  // ---- B history shows only B's task ----
  const bTaskId = bUrl.match(/\/tasks\/([0-9a-f-]{36})/)[1];
  await pageB.getByRole('button', { name: '研究历史' }).click();
  await pageB.waitForURL(/\/history/);
  await pageB.waitForSelector('.history-item', { timeout: 10000 });
  const bHistory = await pageB.textContent('body');
  record('LOCAL-BRW-05', 'B 研究历史不含 A 的任务', 'false', `aInB=${bHistory.includes(taskIdA.slice(0, 8))} bInB=${bHistory.includes(bTaskId.slice(0, 8))}`, !bHistory.includes(taskIdA.slice(0, 8)) && bHistory.includes(bTaskId.slice(0, 8)));

  // ---- B opens A's task deep link: must be isolated ----
  await pageB.goto(taskUrlA, { waitUntil: 'networkidle' });
  await pageB.waitForTimeout(500);
  const bBody = await pageB.textContent('body');
  await pageB.screenshot({ path: join(SHOTS, 'b3-cross-task-narrow.png'), fullPage: true });
  const blocked = bBody.includes('任务暂时无法打开') || !(await pageB.locator('text=研究方向').count());
  record('LOCAL-BRW-06', 'B 深链访问 A 的任务被隔离（无内容泄露）', '无法打开提示/无任务内容', bBody.slice(0, 60).replace(/\s+/g, ' '), blocked);

  await browser.close();
  writeFileSync(join(SL, 'evidence', 'browser-check-results.json'), JSON.stringify({
    generated_at: new Date().toISOString(),
    scope: 'local-browser (two fresh contexts against http://127.0.0.1:5192)',
    taskIdA,
    passed: results.filter((r) => r.passed).length,
    failed: results.filter((r) => !r.passed).length,
    results,
  }, null, 2));
  console.log(`SUMMARY passed=${results.filter((r) => r.passed).length} failed=${results.filter((r) => !r.passed).length}`);
  process.exit(results.some((r) => !r.passed) ? 2 : 0);
}

main().catch((error) => {
  console.error('BROWSER CHECK ERROR', error);
  process.exit(1);
});
