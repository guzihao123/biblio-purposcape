# purpose-landscape-web 本地全量回归（2026-11-26）

## 1. 结论

- **回归结果：通过。** 最新主线本地回归为 **739 passed / 5 skipped / 0 failed**；本文原始执行快照为 **738 passed / 5 skipped / 0 failed**，四项退出码均为 0。
- **失败项：无。**
- **当前 A 验收：仍为 blocked。** 检索超时已转为历史问题并复验通过；当前剩余阻塞为 **5xx 收尾 + 生成/Word 未验**。本地回归通过不能替代线上 A 验收。

## 2. 基线与执行环境

| 项 | 值 |
|---|---|
| 主仓库 | `/Users/crisprcas_9/WorkBuddy/2026-11-06-20-49-06/purpose-landscape-web` |
| 回归 worktree | `/private/tmp/purpose-landscape-web-regression-20261126` |
| worktree 状态 | detached HEAD |
| 原始执行快照 | `integration3@030a44376c89c06c8509450774af50adfaebc11b` |
| 本单闭环基线 | `integration3@87de16da5f85fb7e1af48405d3bf4b3973144f3a`；测试代码对应 `0b83b2f`，`87de16d` 仅追加阻断修复记录 |
| 后续提交 | `0b83b2f73130e5f9b5f1f758ecb28542613351d7`（5xx 后答案状态回读）、`87de16da5f85fb7e1af48405d3bf4b3973144f3a`（阻断修复记录）；提交时间均为 2026-11-26 00:11:52（GMT+8） |
| 原始执行时间 | 2026-11-26 00:06:47–00:08:39（GMT+8） |
| 依赖方式 | 复用主仓库 `.venv` 与 `frontend/node_modules` 的符号链接；未安装或升级依赖 |
| 源码边界 | 原始执行未包含当时未提交的 `frontend/src/api.ts`、`frontend/tests/ApiRetry.test.ts`；相关改动随后由 `0b83b2f` 提交，并纳入最新主线基线 |

## 3. 回归明细

### 3.1 最新主线基线

2026-11-26 00:11:52 两个后续提交落地后的主线回归记录为：Backend **622 passed / 5 skipped**、Frontend **41 passed**、Deno **65 passed**、Playwright **11 passed**，合计 **739 passed / 5 skipped / 0 failed**，全绿。证据：`dev/acceptance/regression-20261126-post-api.md:1-14`。本次仅更正报告基线，未重跑测试。

前端第 41 个用例对应 `0b83b2f` 的 `frontend/tests/ApiRetry.test.ts:32-54`；阻断修复与验证基线记录见 `87de16d` 的 `dev/acceptance/blocker-fixes-20261125.md`。

### 3.2 本文原始执行日志快照

以下为 `030a443` 上实际执行并留档的结果；前端日志中的 40 passed 是原始快照，不用来冒充最新主线的 41 passed。

| 套件 | 通过 | 跳过 | 失败 | 退出码 | 耗时 | 日志 |
|---|---:|---:|---:|---:|---:|---|
| Backend / pytest | 622 | 5 | 0 | 0 | 27.066s | `dev/acceptance/regression-20261126/backend.log` |
| Frontend / Vitest | 40 | 0 | 0 | 0 | 3.853s | `dev/acceptance/regression-20261126/frontend.log` |
| Deno / Sites Functions | 65 | 0 | 0 | 0 | 0.904s | `dev/acceptance/regression-20261126/deno.log` |
| Playwright / Chromium | 11 | 0 | 0 | 0 | 53.279s | `dev/acceptance/regression-20261126/playwright.log` |
| **合计** | **738** | **5** | **0** | **0** | **85.102s** | 同上 |

### 执行命令

```text
.venv/bin/python -m pytest backend/tests -q -p no:cacheprovider
cd frontend && PATH=/tmp/node22/bin:$PATH npm test
~/.deno/bin/deno test --allow-all --import-map=dev/import_map.json sites/functions/*.test.mjs
cd frontend && PATH=/tmp/node22/bin:$PATH node node_modules/playwright/cli.js test --config=playwright.config.ts
```

## 4. 非失败告警

- Backend：5 条 `rq.job.exc_info` `DeprecationWarning`，不影响测试结果。
- Frontend / Playwright：Node 输出 `UNDICI-EHPA` 实验性代理告警，不影响测试结果。
- Deno：缺失制品与校验和用例按预期输出 404 错误日志，对应用例均通过。

## 5. 失败项与工作区副作用

- **测试失败项：无。**
- 后端测试在隔离 worktree 内重写了以下 5 个 worker fixture 结果文件；未修改主仓库源码，也未修复或还原这些测试产物：
  - `backend/tests/fixtures/worker/results/a-dialogue.json`
  - `backend/tests/fixtures/worker/results/c-pair-ppt.json`
  - `backend/tests/fixtures/worker/results/c-pair-word.json`
  - `backend/tests/fixtures/worker/results/graph-error.json`
  - `backend/tests/fixtures/worker/results/sensitive-error.json`
- worktree 另有两个未跟踪依赖符号链接：`.venv`、`frontend/node_modules`。
- 原始执行时主仓库的 `frontend/src/api.ts`、`frontend/tests/ApiRetry.test.ts` 未提交改动未纳入 worktree；二者随后由 `0b83b2f` 提交。本次基线更正只更新本报告，未改产品代码。

## 6. 对当前 A 验收的影响

**A 仍为 blocked；历史检索超时已修复并复验，当前剩余阻塞为“5xx 收尾 + 生成/Word 未验”。**

- **历史问题：检索超时。** 2026-11-25 18:58–20:54（GMT+8），两个 A 任务在检索阶段等待 1800 秒后超时并最终转为 `error`，无仪表盘数据、无 Word。该时间线保留在 `dev/acceptance/live-a-20261125.md:5-10,65-80,154-177`，仅作为历史问题，不再作为当前阻塞描述。
- **已修复并复验：检索约 3 分钟通过。** 2026-11-25 22:03:51 `searching` → 22:06:52 `dashboard_ready`，约 181 秒进入调整卡阶段。证据：`dev/acceptance/blocker-fixes-20261125.md:11-20`、`dev/acceptance/live-a-20261125.md:252-260`。
- **当前剩余阻塞一：5xx 收尾。** 截至 2026-11-26 00:11:52 后的最新主线交接，模式卡仍偶发 502/504，但答案实际已生效。`0b83b2f` 已加入“5xx 后回读任务状态”的恢复逻辑，见 `frontend/src/api.ts:122-140`、`frontend/tests/ApiRetry.test.ts:32-54`；网关超时边界与未闭合项见 `dev/acceptance/blocker-fixes-20261125.md:22-31`。5xx 尚未完全关闭。
- **当前剩余阻塞二：生成/Word 未验。** 最新主线交接显示生成正文仍在进行，尚未拿到 Word。仓库内暂无这次生产任务生成中的独立状态快照，因此不补造任务 ID、状态时间或产物路径；既有“未拿到 Word”的边界见 `dev/acceptance/live-a-20261125.md:256-260`。

本地回归工单可关；A 验收工单保持 **blocked**。后续只需继续 5xx 收尾，并等待本次生成完成、下载 Word 后复核 zip、`word/document.xml`、正文与参考文献；不得以本地全绿或 Playwright 的测试环境下载替代生产 Word 验收。

## 7. 操作边界

- 未修改产品代码。
- 未修复任何失败项（本次无失败项）。
- 未提交、未推送、未部署、未修改云配置。
