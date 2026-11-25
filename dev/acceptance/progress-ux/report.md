# 任务细粒度进度展示 · 验收报告（progress-ux）

- 分支：`progress-ux`（基于 `main@f782b63`，本地与 `origin/main` 内容一致）
- worktree：`/Users/crisprcas_9/WorkBuddy/2026-11-06-20-49-06/purpose-landscape-web-progress-ux`
- 日期：2026-11-25
- 目标：仅增加 search/generate 的阶段进度展示（阶段名 + 百分比/进度条），不改动检索与写作业务逻辑
- 交付状态：**本地分支提交；未合并、未 push、未部署**

## 一、结论摘要

| 项目 | 结论 |
|---|---|
| 阶段进度 | 检索 7 个阶段、生成 6 个阶段，全部通过注入的 reporter 写入 `TaskProgress.message` / `percent` |
| 数据契约 | `TaskProgress.percent` 新增；现有库走幂等 ALTER，全新库由模型建列；local/sites 两条 API payload 均暴露 `percent` |
| 注入方式 | worker 注入 reporter（`stage_reporting` 上下文）；stage service 仍是二位置参数，二参 fake 全部兼容 |
| UI | 任务页沿用 2s 轮询，新增阶段名 + 百分比 + `role="progressbar"`；原 message 与 `当前阶段：...` 文案保留 |
| 失败/脱敏 | 未改失败路径；reporter 自身异常被吞掉，自由文本经 `redact_sensitive_text`，长度上限 500 |
| 测试 | 新增 14 项，全量 backend **489 passed / 4 skipped**；前端 `npm run build` 通过 |
| 已知限制 | sites 权威模式无增量上报端点，细粒度阶段降级为 no-op（见第七节） |

## 二、阶段与 percent 映射

检索（`search`）：

| 阶段名 | 打点位置 | message | percent |
|---|---|---|---|
| 检索 | `Orchestrator.search_stage` 检索调用前 | 正在检索与整理论文池 | 10 |
| 分析·分类 | `analyze()` 中 `classify` 前（首次调用） | 正在分析论文：分类 | 25 |
| 分析·因素 | `analyze()` 中 `extract_factor_votes` 前 | 正在分析论文：因素抽取 | 35 |
| 分析·关系 | `analyze()` 中 `extract_relations` 前 | 正在分析论文：关系抽取 | 45 |
| 统计 | `stats_runner` 调用前 | 正在统计年度与主题分布 | 60 |
| 图谱 | `graph_builder` 调用前 | 正在生成七类图谱 | 80 |
| 上传 | `_sync_artifacts` 调用前 | 正在上传检索产物 | 95 |

生成（`generate`）：

| 阶段名 | 打点位置 | message | percent |
|---|---|---|---|
| 构件 | `WritingService.produce_components` 入口 | 正在生成构件 | 15 |
| 提纲样章 | `WritingService.produce_outline_and_sample` 入口 | 正在生成提纲与样章 | 35 |
| 正文 | `WritingService.write_body` 入口 | 正在生成正文 | 55 |
| 复核 | `DeliveryService.deliver` 预置复核前 | 正在复核交付内容 | 70 |
| Office | `DeliveryService.deliver` DOCX/PPTX 生成前 | 正在生成 Office 交付文件 | 85 |
| 上传 | `Orchestrator` 三条 `_sync_artifacts` 路径前（含 C1+C2 门禁失败分支） | 正在上传交付产物 | 95 |

`queued`/`started` 重置为 0，`_write_finalization` 写 100；分析双 scope 只在首次调用上报，避免来回跳阶段。阶段表集中在 `backend/app/progress_reporter.py:PHASES`。

## 三、改动范围

| 文件 | 改动 |
|---|---|
| `backend/app/progress_reporter.py`（新增） | `StageReporter` 协议、`NullReporter`、`TaskProgressReporter`、`stage_reporting` 上下文、`report_phase`/`report_stage_phase`、阶段白名单 |
| `backend/app/models.py` | `TaskProgress.percent`（`Integer`, `default=0`, `server_default='0'`） |
| `backend/app/db.py` | `initialize_database` 内幂等 `ALTER TABLE task_progress ADD COLUMN percent INTEGER DEFAULT 0` + NULL 回填 |
| `backend/app/queueing.py` | 入队/启动 percent=0、完成 percent=100；`run_stage` 注入 reporter，不传新参数给 service |
| `backend/app/remote_stage.py` | sites 模式显式注入 `NullReporter`（无 provider 增量端点） |
| `backend/app/orchestration.py` | 检索 7 处、生成上传 3 处打点；`analyze` 内部三阶段打点 |
| `backend/app/writing.py` / `delivery.py` | 构件/提纲样章/正文/复核/Office 各 1 行打点，无返回值或产物改动 |
| `backend/app/task_presenters.py` | `task_payload` 与 `remote_task_payload` 均输出 `progress.percent` |
| `backend/app/recovery.py` | 检查点恢复=100、中断/重试=0，避免陈旧百分比残留 |
| `frontend/src/api.ts` | `TaskProgress.percent?: number \| null`（兼容旧 payload） |
| `frontend/src/pages/TaskPage.tsx` | 阶段名 + 百分比 + 进度条；保留原 h1、`当前阶段：...` 与 2s 轮询 |
| `frontend/src/styles/app.css` | `.task-progress*` 样式，含 reduced-motion 处理 |
| 测试 | 新增 3 个文件共 14 项；`test_task_api.py` 的 FakeQueue 写 percent 并在 GET 断言 |
| 本报告 | `dev/acceptance/progress-ux/report.md` |

## 四、关键设计

1. **注入而非耦合**：reporter 由 worker 通过 `stage_reporting(...)` 注入；`report_phase` 从上下文取当前 reporter，没有 reporter 时是 no-op。stage service 签名保持 `service(task, stage_input)`，测试里大量二参 fake 不受影响。
2. **只写两个字段**：reporter 只更新 `message`/`percent`；`stage`/`input_hash`/`checkpoint` 仍归队列生命周期所有，`_duplicate_checkpoint` 的幂等判定不变。
3. **短会话提交**：`TaskProgressReporter` 每次用独立短 session 写库并 commit，2s 轮询能立即看到；上报异常一律吞掉，不会让付费阶段失败。
4. **安全**：阶段文案全部来自白名单表；若调用方传自由文本，先 `redact_sensitive_text` 再截断到 500 字符。失败仍由 `_record_failure` 写 `SAFE_FAILURE_MESSAGE`，原始异常只进 `protected_traceback`。
5. **迁移**：先 `create_all` 再用 inspector 判断列是否存在，缺列才 ALTER；`percent` 为 NULL 的旧行回填 0，重复执行不漂移。

## 五、测试

新增测试文件：

| 文件 | 项数 | 覆盖 |
|---|---|---|
| `backend/tests/test_task_progress.py` | 7 | 阶段表完整性、reporter 写入且不碰生命周期字段、不创建幽灵行、percent 钳制与消息脱敏、上报失败吞掉、run_stage 注入与完成 100%、失败安全消息 |
| `backend/tests/test_task_progress_migration.py` | 3 | 旧表幂等 ALTER 且保留原行、新库模型建列、NULL 回填 |
| `backend/tests/test_task_progress_payload.py` | 4 | local/remote payload 的 percent 输出与旧数据默认值 |

命令与结果：

```bash
# 聚焦测试：27 passed
env -u CODEBUDDY_API_KEY_HELPER_DISABLED TMPDIR="$T" \
  .venv/bin/python -m pytest -q \
  backend/tests/test_task_progress.py \
  backend/tests/test_task_progress_migration.py \
  backend/tests/test_task_progress_payload.py \
  backend/tests/test_task_api.py

# 全量 backend：489 passed, 4 skipped, 5 warnings in 42.40s
env -u CODEBUDDY_API_KEY_HELPER_DISABLED TMPDIR="$T" \
  .venv/bin/python -m pytest -q

# 前端 build：tsc --noEmit && vite build，通过（803ms）
cd frontend && npm run build

# 前端单测（附加验证）：26 passed / 1 failed（基线问题，见第六节）
cd frontend && npm test
```

说明：`env -u CODEBUDDY_API_KEY_HELPER_DISABLED` 与独立 `TMPDIR` 用于规避宿主环境变量过度脱敏和 `/tmp/pytest-of-*` 目录冲突；5 条 warning 来自 rq 的 `job.exc_info` DeprecationWarning，与本次改动无关。

## 六、fixtures 恢复与工作区状态

- 全量 backend 测试会改写 `backend/tests/fixtures/worker/results/*.json`（5 个文件），已执行 `git restore backend/tests/fixtures/worker/results` 并用 `git status` 复核：`backend/tests/fixtures` 与 `fixtures/hcc-20261122` 均无改动。
- 前端 `node_modules` 为指向主仓已安装目录的临时符号链接，提交前移除；`frontend/dist` 已被 `.gitignore` 忽略。
- 前端单测 1 项失败：`FullFlow.test.tsx` 第二例的 mock artifact 名为 `report.docx`，而 `ReportPage` 的 `downloadLabels` 只识别 `综述初稿.docx` 等名称，因此断言 `下载 Word 报告` 失败。该用例与 `ReportPage.tsx` 均未被本次改动触碰（`git diff` 为空），属既有基线问题，未在本分支修复。

## 七、剩余风险 / 已知限制

1. **sites 权威模式不显示细粒度阶段**：provider 只有 enqueue/start/complete/fail/retry 五个生命周期动作，`sites_task_progress` 无 `percent` 列，也没有增量上报端点。本分支在该模式下注入 `NullReporter`，只保留原生命周期 message，API 返回 `percent: 0`。若要覆盖 sites，需要另做 provider schema + dispatch 改动，超出「只做进度展示、不部署」范围。
2. **阶段百分比为静态映射**：按调用进度递增，不按耗时或论文数动态计算；这是展示层口径，不影响结果正确性。
3. **未跑 e2e / 未做线上验收**：按要求不部署、不 push；E2E 中 `当前阶段：search/generate` 与 message 文案均保留，预期不受影响，但未在本分支实测。
4. **C1+C2 分支阶段会重复推进**：两路写作/复核各打点一次，最终上传按分支分别打点；UI 只取最新值，不会回退。

## 八、约束遵守情况

- 未修改检索、分析、写作、交付的业务结果：`orchestration.analyze` 仅把两处表达式提取为局部变量，产物与返回值不变。
- 未改失败与脱敏路径：`SAFE_FAILURE_MESSAGE`、`protected_traceback`、`redact_sensitive_text` 的既有调用不变。
- 未新增 UI 轮询方式：仍为 `TaskPage` 的 2s `getTask` 轮询。
- 未合并、未 push、未部署。
