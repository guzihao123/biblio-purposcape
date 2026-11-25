# Task 15 · 线上验收报告（2026-11-25）

> 范围：只整理文档。本次未改代码、未推送、未部署、未改云配置、未创建云资源、未读取或打印密钥。
> 证据口径：凡仓库内或本地运行目录有文件的，写明路径；只有任务背景口述、仓库内无对应文件的，一律标 **未验证**。提交状态快照取 2026-11-25 12:58；其后出现的改动不属本次文档作者，推送前请以实时 `git status` / `git log` 为准。

## 1. 拓扑与现状

| 层 | 组件 | 可证信息 | 证据 |
|---|---|---|---|
| Web | Render `biblio-purposcape`（Docker，free） | `render.yaml` 定义 web 服务名、free plan、`healthCheckPath: /api/health`；公开地址 `https://biblio-purposcape.onrender.com` 见任务背景，仓库内无该字符串 → 地址本身 **未验证** | `render.yaml:2-7` |
| Worker | Render `landscape-worker`（Docker，starter） | `render.yaml` 定义 worker、`dockerCommand: python worker.py`、starter plan | `render.yaml:37-42` |
| Queue | Render `landscape-redis`（free） | web/worker 的 `REDIS_URL` 均 `fromService` 指向该服务 | `render.yaml:14-17,48-51,70-73` |
| DB | Supabase PostgreSQL pooler | 生产 `DATABASE_URL` 必须 `postgresql*` 前缀且 `sync: false`；实际连接串不在仓库 | `backend/app/config.py:35-42`、`render.yaml:11-12,46-47` |
| Model | 阿里云 Tokenplan `qwen3.7-plus`（OpenAI 兼容） | `QWEN_BASE_URL` / `QWEN_MODEL` 在 `render.yaml` 固化；模型名亦见任务背景 | `render.yaml:20-23,55-58` |
| 前端/函数 | Qoder Sites 站点 + 同源 Functions | 站点配置含 `siteId` / `deploymentId` / `actionId`；公开地址 `https://purpose-landscape-w28zuuplkjz.qoder.zone` 见任务背景，仓库内无该字符串 → **未验证**。网关会把 `/functions/v1/app/*` 改写成 `/app/*` | `.文献选题摸底智能体.qoder.site`、`sites/functions/index.ts:42-55`、`sites/README.md` |
| 制品 | Worker/RQ 生成，经函数或 Render 下载 | 本地同代码已产出 `report.docx` 及复核文件；跨容器同步线上结果 **未验证** | `/tmp/pl-stage-run/artifacts/local-thinking-off-stage/` |

## 2. 已验证清单（文件为证）

| 项 | 结论 | 证据文件 | 关键数字/说明 |
|---|---|---|---|
| 远端基线 | 已验证 | `git log`、`git status -sb` | `origin/main = ebd9534` |
| 用户所列三条提交 | 已验证 | `git log --oneline` | `0670de6`（10:33）、`7bd3abd`（11:56）、`6e03da2`（12:36），提交说明与补丁一一对应 |
| 补丁落盘 | 已验证 | `deliverables/deploy-patches/0001~0003-*.patch` | 三个补丁头分别为上述三个 commit SHA |
| 首次启动补种 Skill | 已验证（代码层） | `0670de6`、`backend/app/config.py:26`、`backend/app/db.py:125-129`、`render.yaml:34-35` | `SEED_BASE_SKILL` 开启后在 `initialize_database` 幂等补种 published base Skill；线上是否生效 **未验证** |
| 关闭结构化思考 | 已验证（代码层） | `7bd3abd`、`backend/app/qwen.py:43-52` | 默认 `thinking=False`；提交说明记录 strict JSON 提取约 9 倍延迟、5 次分析 340s→56s |
| 写作侧重新开启思考 | 已验证（代码层） | `6e03da2`、`backend/app/orchestration.py:276-283`、`backend/app/qwen.py` | 写作工厂把 `ChatModel` 重建为 `thinking=True`，与检索/分析侧分工明确 |
| 函数双前缀路由 + Origin | 已验证（代码层） | `6e03da2`、`sites/functions/index.ts:42-55`、`backend/app/sites_store.py:80-90` | 同时识别 `/functions/v1/app` 与 `/app`；服务端调用补 `Origin` 头 |
| 本地检索阶段 | 已验证 | `/tmp/pl-stage-run/run.log`（12:04:22） | `ELAPSED 265.6s`；limited/unlimited 各 20 篇；`graph_artifacts=6`；`dashboard_ready`；消息称「七类图谱」已生成 |
| 本地生成阶段（最新一次） | 已验证 | `/tmp/pl-stage-run/generate.log`（12:52:00） | `ELAPSED 602.2s`，`state=done`，产出 `report.docx`；`clean=false`，15 条 DOI/著录人工核对项 |
| 用户口述「生成约 297s」 | **未验证** | 无对应日志；当前最新 generate.log 为 602.2s | 不以口述覆盖最新文件 |
| 交付前复核 | 已验证 | `/tmp/pl-stage-run/artifacts/local-thinking-off-stage/verify_report.txt`（12:51:37） | 9 项全 PASS；20 篇池、28 条台账、CJK 2148/1500-2500、正文引用 14 编号；1 个数字（20，句引 [9]）待人工确认 |
| 需求对账 | 已验证 | 同目录 `conformance.md` | 3 项要求通过；13 条著录「未通过」＝10 条 DOI 缺失/非法 + 3 条作者名不一致 |
| 著录核验 | 已验证 | 同目录 `references_check.md`（12:51） | 7 篇核验通过、13 篇需人工核对、0 撤稿/更正、10 篇可回填卷期页 |
| 主线离线验收 | 已验证（离线） | `dev/acceptance/mainline-20261125-result.json` | pytest 448 passed / 4 skipped；函数 50 pass；制品契约 94 pass；模型失败契约 31 pass；容器 `/api/health`、`/`、`/history` 均 200；同时列明 Render/Qoder 真实部署 **未验证** |
| 线上 `/api/health` 200、建单 201、方向/用途/术语/年限四卡 200 | **未验证** | 任务背景口述；仓库内无请求日志或截图 | 本次未联网复测 |
| 线上检索约 1 小时被恢复机制判中断 | **未验证** | 任务背景口述；仓库内无任务状态/日志 | 与 7bd3abd 的根因分析一致，但缺文件证据 |
| Qoder `/functions/v1/app/health` 持续 404、日志 04:16 后无新请求、冻结 ZIP 含新代码 | **未验证** | 任务背景口述；仓库内无函数日志或平台导出 | 平台是否切换运行时无法从仓库判定 |
| github.com 网络阻断 | **未验证** | 任务背景口述；本次未执行推送测试 | 仅据此准备三条推送路径 |

## 3. 根因与修复

1. **建单 409**：空的 `skill_versions` 表导致任务创建失败。修复 `0670de6`：新增 `SEED_BASE_SKILL` 开关（render.yaml web 已开启），启动初始化时幂等补种一版 published base Skill，不动已有版本。
2. **检索阶段被判中断**：结构化 JSON 调用开启 thinking 后延迟约 9 倍，线上约 1 小时触发恢复机制。修复 `7bd3abd`：analysis/Qwen 默认 `enable_thinking=False`，异常形状重试一次并降级空列表，避免整阶段失败；提交说明实测 5 次分析 340s→56s。
3. **写作证据链不稳 + 函数网关不兼容**：写作构件输出无机器可读 schema、异常输出无重试；网关改写 `/app` 前缀且服务端调用缺 `Origin` 导致制品同步被拒。修复 `6e03da2`：schema/重试/长度与空白表规则、双前缀识别、补 `Origin`，写作侧保留 thinking 以保证逐字证据。
4. **Qoder 函数 404（未闭合）**：重发后 `/functions/v1/app/health` 仍 404，怀疑平台未切换到新运行时；**根因未验证**。仓库可见的部署记录确有变化（`6e03da2` 中 `actionId=ff941e18...`；并发提交 `4f74301` 记录 `actionId=4bc33037...`），但这只能证明有重发记录，不能证明运行时内容。

> 核对期间的并发变更：`c12958b`（12:53:30，正文长度/空白行规则）、`f22b043`（12:54:31，重复 `/app` 前缀剥离）与 `4f74301`（12:56:59，Qoder Sites 发布绑定）在本次核对期间被提交，本地 HEAD 由 `6e03da2` 前进到 `4f74301`，`origin/main..main = 6`。这三条**不是**本次文档作者改动，也未纳入用户所述三条补丁清单（补丁目录同期出现 `0004~0006`）。12:59 复核时工作区又出现 `.文献选题摸底智能体.qoder.site` 与 `sites/functions/index.ts` 的未提交改动，同样不是本次文档作者改动；推送前需实时确认是否一并带上。

## 4. 影响面与风险

- 未推送/未重新部署前，生产实际运行版本 **未验证**；不能假定三条修复已在线上生效。
- 若补种未生效，建单仍可能 409；若 thinking 仍开启，检索仍可能超时并被恢复机制判中断。
- Qoder 函数 404 使跨容器制品同步不可用；公开入口应先以 Render 地址承载（见 `deliverables/DEPLOY.md`）。
- 交付物仍有人为核对项：13 篇著录需人工核对、1 个数字待判定；本地最新生成 `clean=false`，不可当作“全绿”交付。
- 清单中的 linux/amd64 构建、真实 Qoder Storage 上传下载、RQ 全量迁移、Skill 发布并发等仍属 `dev/acceptance/mainline-20261125-result.json` 列出的未验证项。
- 本次只写文档；未执行 `git push`、Render 重新部署、Qoder 重发或云配置变更。

---

## 主线进展（2026-11-25 17:25 GMT+8）

- 已用 GitHub API 推送 20 个提交（远端 `abf2b9e`），Render 重新部署；方向卡交通四题线上已验证。
- Qoder 函数根因修复：网关路径为 `/app-<部署哈希>/`；health 200、session 201、制品路由 403 鉴权正常。
- 制品链路：新增 web 受保护内部上传端点（`/api/internal/artifacts/...`），worker 直接上传到 web；线上检索 31–34 秒完成，22 个制品可下载。
- 稳定性热修：Supabase 会话池（5432）、阶段收尾换连接重试、RQ 队列切到 `landscape-v2`、写作请求按次 600 秒超时（此前复用分析客户端 90 秒导致 thinking 必超时）。
- 集成：`integration2` = 最新 main + B 卡简化 + 检索源路由 + 任务过期，后端 496 passed、站点函数 57 passed。
- 最终验收任务 `ef805526` 正在生成 Word；另有旧任务 `ab4ddaaa` 仍占用旧 generation，不阻塞。
- 待办：合并 integration2 → 推送部署 → B 模式线上验收 → 任务过期清理 → Skill v2（B 模板）；四个并行工地（C 收尾 / B [M] / D 原图 / 进度 UX）已给提示词。

---

## 2026-11-25 晚间进展

> 本节只追加晚间收尾证据，不改写上文历史结论。会话起点为 `integration3@26bc850`；执行期间观察到其他主线并发前进到 `d6f6c0c`，其中包含 `e-b-theme` 合并及分析/写作耗时修复。本会话没有执行这些合并，也没有把它们冒充本会话产出。

### 1. UI D visual polish 与公开入口

| 项 | 状态 | 证据 |
|---|---|---|
| 本地 D visual polish 提交 | **已验证（提交层）** | `git show --no-patch --format='%H %s' d29203e d1fdf73 03e9646`：本地 `d29203eb201b28629e89c1282545c32160fcffec`（merge）、`d1fdf730bc7138c36ed46efe6622bef529ca6945`（部署补丁）；远端重复补丁为 `03e9646b9a81ab305db3f7044e51a5c50f591251` |
| Render 首页 | **已验证（HTTP 层）** | `curl -L --max-time 90 ... https://biblio-purposcape.onrender.com/` → `200`，响应存 `/tmp/render-home-20261125.html` |
| Render health | **已验证（HTTP/JSON 层）** | `curl ... https://biblio-purposcape.onrender.com/api/health` → `200`；`/tmp/render-health-20261125.json` 为 `{"status":"ok","database":"ok","worker":"ready"}` |
| Qoder 首页 | **已验证（HTTP 层）** | `curl ... https://purpose-landscape-w28zuuplkjz.qoder.zone/` → `200`，HTML 存 `/tmp/qoder-home-20261125.html`；HTMLParser 提取到 `/assets/index-ByB3KEqp.js` |
| Qoder 入口资源 `index-ByB3KEqp.js` | **未验证（资源不可取）** | 对首页提取出的精确地址 `https://purpose-landscape-w28zuuplkjz.qoder.zone/assets/index-ByB3KEqp.js` 执行 GET → `404`、`size_download=0`；空响应存 `/tmp/qoder-index-ByB3KEqp-20261125.js` |
| UI D visual polish 线上视觉 | **历史资源 404，当前 Qoder 资源已复验 200** | 本地/远端部署补丁提交存在；归档时 Qoder 首页引用的 `index-ByB3KEqp.js` 返回 404，本会话未做浏览器视觉复验。2026-11-25 23:52 GMT+8 更正复验：Qoder 当前首页引用 `index-Bxn32REQ.js`，直接 GET 返回 200；Render 当前资源 `index-PUNMBFkc.js` 因 TLS 中断未取得现场成功响应，详见文末更正段 |

### 2. 制品链路

- **已验证（历史记录）**：上文 17:25 节已记录线上制品可下载；本会话不重新编造或复制计数。
- **本会话未复验**：未重新列出线上制品、未重新下载、未重算签名校验和。后续复验应同时记录制品清单条目、每个下载响应的 HTTP 状态与 SHA-256，并将结果落到独立日志；不能用 17:25 的结论替代新一次复验。

### 3. 测试与挂死修复

| 范围 | 数字/结论 | 证据 |
|---|---|---|
| mainline 离线验收 | **448 passed / 4 skipped** | `dev/acceptance/mainline-20261125-result.json` |
| integration3 合并 dfigure 前 | **599 passed / 5 skipped** | 任务说明提供的历史快照；本会话未找到对应独立日志，未重新跑旧基线全套件 |
| Deno 历史快照 | **64 passed** | 任务说明提供的历史快照；当前分支因并发新增 B 主题候选路由测试，本轮实际为 65 passed |
| Deno 本轮 | **65 passed / 0 failed** | `PATH="$HOME/.deno/bin:$PATH" deno test --allow-all --import-map=dev/import_map.json sites/functions/task_store.test.mjs sites/functions/routes.test.mjs sites/functions/forward.test.mjs sites/functions/artifact_contract.test.mjs`；日志 `/tmp/deno_full_20261125.log` |
| Deno 类型检查 | **通过** | `deno check --import-map=dev/import_map.json sites/functions/index.ts sites/functions/task_store.ts`；日志 `/tmp/deno_check_20261125.log` |
| dfigure 离线回归 | **4 passed in 0.81s** | `.venv/bin/python -m pytest backend/tests/test_ppt_figures.py -q -p no:cacheprovider`；日志 `/tmp/pytest_dfigure_20261125.log` |
| 挂死复现 | **超时 exit=124** | 起点 `26bc850` 执行指定全量命令，日志 `/tmp/pytest_full.log`；最后完成到 `test_c2_real_offline_delivery_is_not_discussion`，下一项 D 离线交付未完成 |
| 根因 | **D 离线回归漏传 figure loader，默认触发真实 OA 取图** | `dfigure` 后 `DeliveryService` 默认使用 `prepare_d_figures`；旧 `test_mode_delivery_regression.py` 未注入离线 loader。并发提交 `a101e5f` 已补 `offline_figure_loader` 及显式注入 |
| 回归守卫 | **旧基线失败、当前通过** | 新守卫在 `26bc850` 临时归档上 `1 failed in 0.32s`（`/tmp/pytest_d_guard_red.log`）；当前分支 `1 passed in 0.50s`（`/tmp/pytest_d_guard_green.log`）；提交 `ec14abf` |
| 最终全量 pytest | **622 passed / 5 skipped / 5 warnings in 21.44s，exit=0** | `timeout 420 .venv/bin/python -m pytest backend/tests -v -p no:cacheprovider`；日志 `/tmp/pytest_full_final_20261125.log` |

> 最终 622 passed 是在并发合入 `e-b-theme` 和其他主线修复后的当前分支上取得，不能与 dfigure 合并前的 599 passed 直接当作同一基线比较。

### 4. 会话安全边界

- **本会话未推送、未部署、未改云配置。**
- 未执行 B/C/D/E 线上任务验收；只对任务 2 明确要求的公开首页、health 和入口资源做只读 GET。
- 未读取、打印或写入 token/cookie/密钥；未 force push，未使用 `--delete`，未删除用户数据。

### 5. 历史/当前更正（2026-11-25 23:52 GMT+8）

- 更正时间由 `date -Iseconds` 现场记录为 `2026-11-25T23:52:11+08:00`。
- **历史**：归档时 Qoder 首页引用 `/assets/index-ByB3KEqp.js`，对该地址执行 GET 返回 `404`、`size_download=0`；原证据保留在上方表格及 `/tmp/qoder-index-ByB3KEqp-20261125.js`，不改写。
- **当前 Qoder**：`curl -L --max-time 90 --retry 1 --retry-delay 5 -sS https://purpose-landscape-w28zuuplkjz.qoder.zone/` 返回 `200`，HTML 存 `/tmp/qoder-home-correction-20261125.html`；HTMLParser 提取到当前入口 `/assets/index-Bxn32REQ.js`。随后执行 `curl -L --max-time 90 --retry 1 --retry-delay 5 -sS https://purpose-landscape-w28zuuplkjz.qoder.zone/assets/index-Bxn32REQ.js`，返回 `http_code=200`、`size_download=260779`，资源存 `/tmp/qoder-index-Bxn32REQ-20261125.js`，SHA-256 为 `37f1d5fc16605fd06332a12b0413f44d625eab162c72e4595bedb40669f2cbea`。据此将 UI D visual polish 结论更正为：**历史资源 404，当前资源已复验 200**；按主线说明，UI 已随 `integration3` 发布。
- **当前 Render**：主线说明当前入口资源为 `index-PUNMBFkc.js`。本次对 Render 首页重试两次、对 `https://biblio-purposcape.onrender.com/assets/index-PUNMBFkc.js` 直接 GET 一次，均在本机 TLS 握手阶段失败（`curl: (35) LibreSSL SSL_connect: SSL_ERROR_SYSCALL`、`http_code=000`），因此 Render 当前资源本轮**未现场复验**，不以主线说明替代成功响应。
- 本次更正只做公开资源只读复验与报告追加；未 push、未部署、未改产品代码，未修改 `push-state.json`，未读取临时 token。
