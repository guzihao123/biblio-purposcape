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
