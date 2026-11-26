# 任务过期 CLI 离线演练

- 日期：2026-11-26
- 结论：**PASS**
- 演练入口：`app.task_expiry_cli`
- 显式阈值：`24` 小时
- 固定当前时间：`2026-11-26T00:00:00+00:00`
- 临时数据库：`/tmp/task-expiry-drill.46bv4l/drill.db`

## 安全边界

- 仅通过 `DATABASE_URL=sqlite:////tmp/task-expiry-drill.46bv4l/drill.db` 连接临时 SQLite。
- 未连接生产数据库，未修改真实任务，未部署。
- 本轮只证明 `task_expiry_cli` 的判定与无写入行为，不证明生产调度器、RQ/Redis、Supabase 连接或真实任务数据。
- `searching` 等 started 状态不在过期候选内；此类僵尸任务仍依赖 recovery 的 3600 秒机制，本轮不覆盖该机制。
- 为精确验证等号边界，临时包装器仅将 `app.task_expiry._utcnow` 固定到上述时间，并通过 `runpy.run_module('app.task_expiry_cli', run_name='__main__')` 执行 CLI 的 `__main__` 入口；未修改应用代码。
- 演练结束后删除临时数据库与脚本。

## 夹具

| 任务 ID | 初始状态 | updated_at（UTC） | 空闲时长 | 预期 |
|---|---|---|---:|---|
| `drill-collecting-mode-stale` | `collecting_mode` | 2026-11-24 23:00:00 | 25 小时 | 过期 |
| `drill-collecting-terms-boundary` | `collecting_terms` | 2026-11-25 00:00:00 | 24 小时整 | 过期 |
| `drill-collecting-years-fresh` | `collecting_years` | 2026-11-25 00:00:01 | 23:59:59 | 保留 |
| `drill-searching-stale` | `searching` | 2026-11-19 00:00:00 | 7 天 | 保留 |
| `drill-dashboard-ready-stale` | `dashboard_ready` | 2026-11-19 00:00:00 | 7 天 | 保留 |
| `drill-generating-stale` | `generating` | 2026-11-19 00:00:00 | 7 天 | 保留 |
| `drill-done-stale` | `done` | 2026-11-19 00:00:00 | 7 天 | 保留 |

## 执行与结果

### 1. Dry-run

执行 `--dry-run --hours 24`，CLI 返回：

- `count: 2`
- 候选仅为 `collecting_mode`（90,000 秒）与 `collecting_terms`（86,400 秒）。
- 数据库复核：7 条任务状态和 `updated_at` 均未变化，`task_events` 为 0，`task_jobs` 为 0。

### 2. 写入态过期

执行 `--hours 24`，CLI 返回 `count: 2`。数据库断言结果：

| 任务 | 最终状态 | task_expired 事件 |
|---|---|---:|
| `drill-collecting-mode-stale` | `error` | 1 |
| `drill-collecting-terms-boundary` | `error` | 1 |
| `drill-collecting-years-fresh` | `collecting_years` | 0 |
| `drill-searching-stale` | `searching` | 0 |
| `drill-dashboard-ready-stale` | `dashboard_ready` | 0 |
| `drill-generating-stale` | `generating` | 0 |
| `drill-done-stale` | `done` | 0 |

两条过期事件的 `event_type=task_expired`，并包含：

- `category=safety`
- `reason=inactive_collection_timeout`
- 正确的 `previous_state` 与 `state=error`
- `compute_charged=false`
- `data_deleted=false`

两条任务的 `updated_at` 均更新为固定当前时间；其余任务的 `updated_at` 保持不变。

### 3. 幂等复跑

相同数据库、固定时间和阈值再次执行写入态 CLI：

- `count: 0`
- `tasks: []`
- 总事件数仍为 2，未产生重复过期事件。

### 4. 阈值边界

- 空闲 `86,400` 秒：过期，说明边界为 `idle_seconds >= threshold_seconds`。
- 空闲 `86,399` 秒：保留。
- 空闲 `90,000` 秒：过期。
- 非收集态即使空闲 7 天也全部豁免。

## 回归验证

```text
env APP_ENV=development \
  DATABASE_URL=sqlite:////tmp/task-expiry-drill.46bv4l/drill.db \
  PYTHONPATH=backend \
  .venv/bin/python -m pytest backend/tests/test_task_expiry.py -q

........                                                                 [100%]
8 passed in 0.08s
```

## 非阻断观察

过期判定在空闲时长恰好等于阈值时生效，但事件 `detail` 文案使用“超过 24.0 小时阈值”。状态行为正确，建议后续将措辞改为“达到”以与包含等号的边界语义一致；本次演练未修改实现。

## 归档结论与真实清扫前置条件

本轮离线验收结论仅适用于上述临时 SQLite 与 `task_expiry_cli`：24 小时边界会过期，差 1 秒不误伤，活跃/完成态豁免，dry-run 零写入，重复扫描为 0，既有测试 8 passed。代码未改、未部署，可关闭本轮离线演练项。

- **真实清扫尚未执行**；当前不要连接生产数据库或部署。
- 本结论不证明生产调度器、RQ/Redis、Supabase 连接或真实任务数据，也不证明 recovery 对 started 僵尸任务的 3600 秒处理机制。
- 真实清扫由主线在 **A 验收通过且下一批部署之后**执行，不在本轮离线演练中提前进行。
- 后续顺序必须为 **dry-run → 单任务验证 → 正式清扫**：先核对候选清单，再仅对确认的单任务验证状态迁移与事件，最后执行正式清扫。
- 全程保留活跃任务；若 dry-run 或单任务验证发现活跃任务进入候选、状态不符或异常，应停止，不得继续正式清扫。
