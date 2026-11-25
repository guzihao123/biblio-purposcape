# Qoder Sites 本地项目登记与发布包检查报告

日期：2026-11-24（Asia/Shanghai）

## 1. 结论与描述文件路径

- **`.qoder.site`：未生成，无描述文件路径。**
- 当前会话没有提供 `open_design_workbench` 工具，命令行也不存在该可执行程序。按照要求，没有手写描述文件绕过。
- 因此，首页、任务、图谱、报告、历史、管理页以及 appearance/radius/spacing/typography/motion 的**正式登记未完成**。
- 未执行 `prepare_site`、未执行 `publish_site`、未部署、未创建云资源，也未在发布目录创建 `_qoder`。
- 已完成可独立执行的生产构建、SPA 深链接、静态资源、Function 本地逻辑和发布候选边界检查。

验收工作区：

`/Users/crisprcas_9/Documents/kimi/tasks/2026-11-24/09-42-52-a0586535/purpose-landscape-web`

来源目录在验收期间被其他流程持续更新；已于 2026-11-24 09:58:54 CST 重同步，并在 10:15:08 CST 冻结最终业务与 worker 快照、重跑关键检查。冻结时业务源码与来源目录一致，本次未重做设计、未修改业务代码；冻结后来源目录的后续变化不属于本报告验收范围。

## 2. 页面与路由核对（供后续真实工具登记）

以下来源核对不是 `.qoder.site` 登记结果。

| 页面 | 当前实际入口/视图 | 核对结果 |
|---|---|---|
| 首页 | `/` | `App.tsx` 的默认路由；先显示公开入口，再进入任务流程 |
| 任务 | `/tasks/:id` | `readRoute()` 明确匹配，`TaskPage` 按任务状态显示对应步骤 |
| 图谱 | `DashboardPage`，位于任务状态 `dashboard_ready` / `adjusting` | 是任务页内的状态视图；没有独立、语义化的 dashboard 路由 |
| 报告 | `ReportPage`，位于任务状态 `done` | 是任务页内的状态视图；没有独立、语义化的 report 路由 |
| 历史 | `/history` | `readRoute()` 明确匹配 `HistoryPage` |
| 管理 | `/admin/skill` | `readRoute()` 明确匹配 `AdminSkillPage` |

`/tasks/:id/dashboard` 和 `/tasks/:id/report` 在生产预览中会由 SPA fallback 返回首页 HTML，但当前 `readRoute()` 只提取任务 ID、忽略后缀，不能据此声称存在两个独立页面路由。后续若工作台要求独立路由，需要先明确是否调整路由设计；本次遵守要求，没有修改业务源码。

## 3. 深色外观与 CSS 变量消费证据

生产 CSS 保留 `--site-bg: #070b16`，现有深色满血风未改。以下计数来自 `frontend/src/styles/*.css` 中的 `var(--...)` 实际引用，不把 `:root` 中单纯声明算作消费。

| 能力 | 已消费变量与次数 | 未消费的占位变量 |
|---|---|---|
| appearance | `--site-bg` 6、`--site-surface` 1、`--site-border` 8、`--site-text` 14、`--site-muted` 16、`--site-accent` 13、`--site-accent-2` 19 | 无 |
| radius | `--site-radius` 4 | 无 |
| spacing | `--site-grid` 2 | `--site-space` 0 |
| typography | `--site-font` 1 | `--site-type` 0 |
| motion | `--motion-page` 1、`--motion-focus` 3、`--motion-sweep` 4、`--motion-flash` 1、两个 motion easing 变量各 3/4 | `--site-motion` 0 |

结论：深色外观、radius、grid spacing、字体和 motion 都有实际消费证据；**不能把 `--site-space`、`--site-type`、`--site-motion` 写成已消费变量**。后续使用真实工作台登记时，spacing/typography/motion 应指向已消费的变量或先由设计 owner 明确处理这些未使用声明。

原始证据：`dev/sites-validation/release-boundary-results.json` 中的 `css_variable_consumption_counts`。

## 4. 生产构建与前端回归

实际执行：

```bash
npm ci --cache .npm-cache
VITE_API_BASE_URL=/functions/v1/app npm run build
npm test
```

结果：

- Vite 生产构建成功，TypeScript 检查通过，`44 modules transformed`。
- `7` 个测试文件、`22` 项测试全部通过。
- 主构建与按 Dockerfile 精简复制清单建立的干净阶段构建产物一致。

产物与 SHA-256：

| 文件 | 字节数 | SHA-256 |
|---|---:|---|
| `frontend/dist/index.html` | 613 | `587df724c91ac6eec1867ee0e06658ac1d1c684926b30587f240c814764cda4b` |
| `frontend/dist/assets/index-D6_JMkZa.js` | 246338 | `ec5db408d560b0e22157f6159c72d62a6177f7c8f8a8456323c1a8a514f630aa` |
| `frontend/dist/assets/index-vFCp4sQM.css` | 24856 | `38e5ae88765fc6cd8309f7563b8adcdf907d75076bca82b685894332cab64530` |

机器可读清单：`dev/sites-validation/dist-manifest.json`。

## 5. SPA 深链接刷新与静态资源

实际启动：

```bash
npm run preview -- --host 127.0.0.1 --port 4173 --strictPort
```

请求以下路径均返回 HTTP 200，且响应体与 `dist/index.html` 完全一致：

- `/`
- `/tasks/00000000-0000-4000-8000-000000000000`
- `/tasks/00000000-0000-4000-8000-000000000000/dashboard`
- `/tasks/00000000-0000-4000-8000-000000000000/report`
- `/history`
- `/admin/skill`

两个构建资源也均返回 HTTP 200：

- JS：`text/javascript`，246338 字节。
- CSS：`text/css`，24856 字节。

证据：`dev/sites-validation/preview-results.json` 和 `dev/sites-validation/preview.log`。

边界：这里验证的是生产静态壳和 SPA fallback，不代表匿名会话、任务数据、管理权限或报告内容已在 Qoder Sites 运行时完成端到端验证。预览服务已停止。

## 6. `/functions/v1/app` 与 Functions/Storage 边界

### 已完成的检查

- 生产 JS 包含 `/functions/v1/app` 入口标记。
- 生产 JS 不包含 `storage-stub` 或 `__LANDSCAPE_STORAGE__`，开发存储桩没有被打进浏览器包。
- `sites/functions/index.ts` 保持服务端动态导入 `./_qoder/storage.mjs`。
- `sites/functions/task_store.ts` 保持服务端动态导入 `./_qoder/database.mjs`。
- `sites/functions/_qoder` 不存在；没有伪造 Provider 文件。
- 执行 `node --test sites/functions/*.test.mjs`：`17` 项通过、`0` 失败，包括 Storage 字节往返、任务路由、owner 隔离、幂等和 worker 客户端检查。

### 未完成或不能解释为成功的检查

- 当前环境无 Deno，无法实际使用 `dev/import_map.json` 和 `dev/storage-stub.mjs` 启动 Function。
- 生产预览请求 `/functions/v1/app/health` 返回 HTTP 500。日志显示 Vite 将请求代理到 `/api/health`，连接 `127.0.0.1:8000` 被拒绝；**这不是 Qoder Function 执行结果**，不计为通过，也不据此判定 Function 业务失败。
- Node 测试使用本地替身，不验证真实 Provider 权限、云端数据库原子性或 Qoder Storage 服务。
- 官方 Functions/Storage 发布边界仍需在真实工作台和运行时可用后复验。

## 7. 发布候选内容检查

检查范围为 `frontend/dist` 和 `sites`，共 10 个文件。结果：

| 检查项 | 候选目录结果 |
|---|---|
| `.env*` | 未发现 |
| `node_modules` | 未发现 |
| `.db` / `.sqlite` / `.sqlite3` 测试数据库 | 未发现 |
| `_qoder` | 未发现 |
| 私钥、常见 API token、显式赋值密钥模式 | 未发现 |
| 浏览器包中的开发 Storage 桩 | 未发现 |

项目根目录已有的 `test.db`、前端已有的 `.motion-preview.db` 以及本次验收生成的 `dev/runtime-validation/data/tasks.db` 均不在上述候选范围。Dockerfile 的前端阶段也已改为显式输入，避免把 `.motion-preview.db` 带入中间构建阶段。

**这只是本地候选文件清单审计，不是官方发布包检查。** 由于 `open_design_workbench` 不可用且未运行 `prepare_site`，没有生成官方发布包，`official_qoder_package_generated=false`、`official_qoder_package_checked=false`。

证据：`dev/sites-validation/release-boundary-results.json`。

## 8. 额外依赖审计发现

`npm ci` 和 `npm audit --json` 报告 3 个开发依赖链漏洞：1 个 moderate、2 个 critical，位于 Vitest/Tinypool 相关链。审计元数据记录生产依赖 4 个、开发依赖 213 个。

证据：`dev/npm-audit.json`。本次允许修改范围不包括前端依赖清单，因此没有执行可能带来破坏性升级的 `npm audit fix --force`。

## 9. 未完成项清单

1. `open_design_workbench` 不可用，未生成真实 `.qoder.site`，六类页面和五类能力未正式登记。
2. 图谱和报告目前是任务路由内的状态视图，不是独立语义路由；未改业务代码。
3. `--site-space`、`--site-type`、`--site-motion` 没有被消费，不能作为已生效能力变量登记。
4. Deno import map、真实 Function、Provider 数据库与 Storage 未验证。
5. 官方发布包未生成，因此不能声称官方包已通过安全检查。
6. Qoder Sites 云端 SPA rewrite、Function 路由和实际权限未验证；本次未部署、未创建云资源。

## 10. 主要证据索引

- 构建与 dist：`dev/sites-validation/dist-manifest.json`
- 深链接与资源：`dev/sites-validation/preview-results.json`
- 预览代理日志：`dev/sites-validation/preview.log`
- 发布候选边界：`dev/sites-validation/release-boundary-results.json`
- Dockerfile 等价阶段构建：`dev/runtime-validation/docker-frontend-stage.log`
- 部署静态回归：`dev/runtime-validation/deployment-tests.log`
- 工具可用性：`dev/runtime-validation/toolchain.json`
- 依赖审计：`dev/npm-audit.json`
