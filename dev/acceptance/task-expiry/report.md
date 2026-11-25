# 长时间无活动任务自动过期 · 验收报告

- 分支：`task-expiry`（独立 worktree `../purpose-landscape-web-task-expiry`，基线 `main@4ea3af2`）
- 日期：2026-11-25
- 目标：清理长期停留在 collecting 态、导致 `SkillVersionService._assert_no_active_tasks()` 永远失败的僵尸任务；不改前端，不改 Skill 发布逻辑。
- 交付状态：**分支保留、未合并、未部署**；本 worktree 未连接生产库，也未执行正式清理。合并后由主线在 Render 上先 dry-run、核对清单，再决定是否正式执行；worktree 保持打开等待合并评审。

## 一、规则

| 项目 | 口径 |
|---|---|
| 过期对象 | `tasks.state ∈ {collecting_mode, collecting_terms, collecting_years}`（仅等待用户确认的三种状态） |
| 判定条件 | `now - tasks.updated_at >= N 小时`，`N` 默认 24，由环境变量 `TASK_EXPIRY_HOURS` 配置（正数；在 `task_expiry.configured_idle_hours()` 读取，不改共享 Settings 模型） |
| 动作 | `state = 'error'`（沿用既有错误态，前端零改动）；`next_card`、答案、进度、制品、历史事件全部保留，不删除任何数据 |
| 审计 | 每个任务写一条 `TaskEvent`：`event_type='task_expired'`，`payload.category='safety'`、`reason='inactive_collection_timeout'`、`detail`（原状态/闲置秒数/阈值）、`previous_state/state`、`marker='expired'`、`updated_at/expired_at`、`compute_charged=false`、`data_deleted=false` |
| 算力 | 不调用检索/模型，不写限流消费，不入队、不重试（`compute_charged=false` 为审计标记，代码路径中无相关调用） |
| 幂等 | `error` 不在候选状态内；写库用带 `state = 原值` 条件的 UPDATE，重复扫描返回 `[]`，不会重复写事件；并发中刚被用户答完的任务不会被覆盖 |
| 豁免 | `searching/generating/verifying/dashboard_ready/adjusting/delivery_confirmed/done/error` 全部不动；`updated_at IS NULL` 跳过（不误判）；SQLite 旧无时区时间按 UTC 处理 |
| 阈值来源 | 调度与 CLI 默认读 `TASK_EXPIRY_HOURS`；CLI 可用 `--hours` 覆盖，仅影响本次扫描，不改环境 |

实现文件（本次代码改动仅此四项）：`backend/app/task_expiry.py`（核心逻辑、常量与阈值读取）、`backend/app/recovery.py`（周期调度接线）、`backend/app/task_expiry_cli.py`（手动 CLI）、`backend/tests/test_task_expiry.py`（对应测试）。本报告是交付物，不是生产代码改动；未改 `config.py`、前端或 Skill 发布逻辑。

## 二、调度与命令

Worker 启动的 `start_recovery_scheduler()` 每 60 秒调用一次 `run_recovery_cycle()`；现已在返回结构中增加 `expired` 字段，`local` 与 `sites` 两种 `task_store_authority` 下都会先跑一次过期扫描，再执行原有的中断恢复/重试逻辑。`run_recovery_cycle()` 新增可选 `session_factory` 参数便于隔离测试。

从仓库根目录执行（解释器需装齐项目依赖，本仓验证用 `../purpose-landscape-web/.venv/bin/python`）：

```bash
# 1) 先列清单（只读，不写库）
PYTHONPATH=backend python -m app.task_expiry_cli --dry-run

# 2) 临时用 6 小时阈值预览
PYTHONPATH=backend python -m app.task_expiry_cli --hours 6 --dry-run

# 3) 确认清单（应包含 22 个 collecting_* 任务）后正式执行
PYTHONPATH=backend python -m app.task_expiry_cli

# 4) 再跑一次确认幂等：count=0
PYTHONPATH=backend python -m app.task_expiry_cli --dry-run

# 5) 核对该任务不再计入 active（应返回 0）
SELECT COUNT(*) FROM tasks
WHERE state IN ('collecting_mode','collecting_terms','collecting_years',
                'searching','dashboard_ready','adjusting','delivery_confirmed',
                'generating','verifying');
```

输出为 JSON：`{dry_run, threshold_hours, eligible_states, count, tasks:[{task_id, session_id, previous_state, state, updated_at, idle_seconds, idle_hours, reason, detail, event_type, dry_run}]}`。命令行不打印密钥类信息；数据库地址沿用 `DATABASE_URL` 配置。

## 三、22 条 dry-run 清单摘要

**来源边界**：本 worktree 未连接生产库，也没有执行过生产 dry-run/正式清理。状态分布来自仓库既有审计记录 `dev/acceptance/skill-sync-deep-audit.md:71`（“线上当前 22 个未完成任务：18 collecting_mode、4 collecting_terms”）。`最老 updated_at` 与“是否包含近 24h 活跃任务”无法从本地证据取得，**留空待主线在 Render 上 dry-run 后回填**，禁止用本地/模拟数据冒充生产清单。

| 摘要项 | 值 | 证据状态 |
|---|---|---|
| 候选总数 | 22 | 既有审计文档（待 dry-run 复核 `count`） |
| `collecting_mode` | 18 | 既有审计文档 |
| `collecting_terms` | 4 | 既有审计文档 |
| `collecting_years` | 0 | 既有审计文档未列出该状态 |
| 最老 `updated_at` | **待主线 dry-run 回填** | 本地无生产数据，未连接生产库 |
| 近 24 小时活跃任务（`idle_seconds < 86400`） | **待主线 dry-run 回填**；按规则应无（阈值 24h，未达标者不会出现在清单中） | 同上 |
| `search` / `generating` 等状态 | 不进入清单，逻辑上零影响 | `EXPIRABLE_TASK_STATES` 仅三种 collecting 态；回归测试用一个 5 天前更新的 `searching`、一个 `generating` 等状态验证其保持原状 |
| Sites 远端任务 | **明确不在本次范围** | 远端任务由 Sites 任务存储托管；远端事件接口只接受术语候选事件，本次不调用远端任务/事件写入 |

主线在 Render 上先执行只读 dry-run 并生成摘要（不执行第 3 步正式命令）：

```bash
PYTHONPATH=backend python -m app.task_expiry_cli --dry-run > /tmp/task-expiry-dryrun.json
python - <<'PY'
import collections, json
tasks = json.load(open('/tmp/task-expiry-dryrun.json'))['tasks']
print('count =', len(tasks))
print('states =', dict(collections.Counter(t['previous_state'] for t in tasks)))
print('oldest_updated_at =', min((t['updated_at'] for t in tasks), default=None))
print('recent_24h =', sum(t['idle_seconds'] < 86400 for t in tasks))
print('ids =', [t['task_id'] for t in tasks])
PY
```

回填判定：`count=22`、`states={'collecting_mode':18,'collecting_terms':4}`、`recent_24h=0`；`oldest_updated_at` 仅记录事实。若 `count` 或状态分布不符，先停止，不要执行正式清理。

## 四、测试

- 新增 `backend/tests/test_task_expiry.py`，8 项：三种 collecting 态过期及安全事件/原因/数据保留/无算力副作用、未过期与非候选状态（含 `searching`/`generating`）全部豁免、dry-run 只读、重复执行幂等、自定义阈值与旧 naive 时间戳、默认阈值取 `TASK_EXPIRY_HOURS` 环境变量（含非法值拒绝）、recovery cycle 在两种 store 模式下均调用过期逻辑、CLI dry-run 参数透传。
- 全量 `backend/tests`（仓库根执行）：基线 `468 passed, 4 skipped` → 改动后 **`476 passed, 4 skipped`**（新增 8 项全通过，5 条既有 rq DeprecationWarning 与基线一致）。
- 命令：
  ```bash
  T=$(mktemp -d "${TMPDIR:-/tmp}/expiry-tests.XXXXXX")
  env -u CODEBUDDY_API_KEY_HELPER_DISABLED TMPDIR="$T" \
    /Users/crisprcas_9/WorkBuddy/2026-11-06-20-49-06/purpose-landscape-web/.venv/bin/python -m pytest -q
  ```
  （宿主 `CODEBUDDY_API_KEY_HELPER_DISABLED=1` 会触发既有的日志脱敏用例误报；沙箱下需每次使用全新 `TMPDIR`。两者均为环境事项，与本次改动无关。）
- CLI 冒烟：临时 SQLite 库插入 1 个 126 小时未活动的 `collecting_terms` 任务，`--dry-run --hours 1` 列出 1 条且状态未变；正式执行后 `state=error` 且有唯一 `task_expired/inactive_collection_timeout` 事件。
- 测试运行会改写 `backend/tests/fixtures/worker/results/*.json`，已 `git restore` 恢复；`.pytest-tmp` 临时目录已清理。无数据库 schema 迁移、无前端与 Skill 发布代码改动。

## 五、线上适用说明

1. 发布前在**生产同一数据库**先跑 `--dry-run`，核对任务 ID/状态/闲置时长与预期 22 条一致；`--dry-run` 全程只读。
2. 正式扫描只改状态并追加事件，属于可审计的软过期：原任务记录、答案和制品仍可查，必要时可由管理员按 ID 回填状态；不存在级联删除风险。
3. Skill 发布计数取本地 `tasks` 表（`SkillVersionService._assert_no_active_tasks()`），本逻辑在 `local` 与 `sites` 两种授权模式下都会清理本地计数，因此 22 条僵尸任务过期后即可按原流程发布新版 Skill，发布校验代码本身未改。
4. `sites` 授权模式下远端任务由 Sites 任务存储托管，远端事件接口仅接受术语候选事件，**本次不修改远端任务或远端事件**；本变更只负责解除本地 active 计数阻塞。若线上判定需要远端任务也同步过期，需在 Sites 存储侧另行支持该状态迁移。
5. 定时执行依赖 worker 进程中的 recovery 调度线程；若线上只跑 API 不跑 worker，请按手动命令执行（可放在一次性运维任务中）。默认 24 小时阈值可按业务等待周期调整，调整后立即对下一次扫描生效，无需重启发布逻辑。
