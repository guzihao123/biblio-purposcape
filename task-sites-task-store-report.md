# Qoder Sites 任务主存储适配层交付报告

## 1. 交付范围与边界

本轮只新增以下 5 个文件：

1. `sites/functions/task_store.ts`：Function 服务端任务存储、固定 SQL、配额事务、制品元数据和 worker 路由。
2. `sites/functions/task_store.test.mjs`：本地假数据库、并发测试、安全测试和 Python 伪传输测试。
3. `sites/schema.sql`：PostgreSQL 审核材料。
4. `backend/app/sites_task_store.py`：Python 固定 worker 路径客户端。
5. `task-sites-task-store-report.md`：本报告。

未修改 `main.py`、`models.py`、`public_access.py`、`queueing.py`、`sites/functions/index.ts` 或前端。未部署、未创建数据库、未执行云端迁移，也未把 `schema.sql` 交给任何 Provider 执行。

**验证边界：未验证真实 Provider 权限与原子性。** 当前测试只验证本地假数据库与伪传输上的固定契约。真实 Provider 的适配器导出形状、角色权限、RLS、事务隔离、唯一冲突等待和回滚行为仍须主线在审核后的测试环境验证。

## 2. 数据模型与 Schema

完整 DDL 位于 `sites/schema.sql`，包括：

| 表 | 主要内容 | 关键约束 |
| --- | --- | --- |
| `sites_anonymous_sessions` | 匿名会话 ID、客户端 IP、User-Agent、创建与最后访问时间 | 会话 ID 主键 |
| `sites_skill_versions` | 版本号、父版本、状态、内容、内容哈希、回归报告、发布时间 | 版本号唯一；部分唯一索引保证最多一个 `published` |
| `sites_tasks` | 所有者 `session_id`、任务状态、下一卡片、Skill 版本、幂等键、乐观锁 `revision`、时间戳 | `(session_id, idempotency_key)` 唯一；Skill 版本 `ON DELETE RESTRICT` |
| `sites_task_artifacts` | 文件名、对象路径、字节数、Content-Type、SHA-256、JSON 元数据、时间戳 | `(task_id, name)` 主键；`(task_id, object_path)` 唯一；任务删除级联 |
| `sites_task_quota_windows` | 会话、固定窗口起点、已用配额、时间戳 | `(session_id, window_start)` 主键；非负用量 |

任务状态与现有 `TaskState` 对齐：`collecting_mode`、`collecting_terms`、`collecting_years`、`searching`、`dashboard_ready`、`adjusting`、`delivery_confirmed`、`generating`、`verifying`、`done`、`error`。

所有任务外键都落到匿名会话所有者。任务读取、列表、状态更新和制品元数据操作都在同一条固定语句中校验所有者，或者先在相同事务中取得所有者任务。

### 幂等与配额语义

`createTask` 在同一个数据库事务中执行：

1. 按当前 `session_id + idempotency_key` 查询原任务；存在则直接返回，不检查新配额，也不重置旧状态。
2. 校验匿名会话和已发布 Skill 版本。
3. 使用 `INSERT ... ON CONFLICT (session_id, idempotency_key) DO NOTHING` 竞争建单。
4. 只有实际插入任务的请求执行固定窗口配额更新；竞争失败者读取并返回胜者的原任务。
5. 配额拒绝会抛出安全错误并回滚本事务中的新任务，避免留下“未计费任务”。

配额表目前只承载 Qoder 主存储中的会话级 `task_create` 固定窗口。现有 IP 级限制、模型与检索配额仍由主线保留和统一接入，不应因本适配层而被移除。

### 状态与制品保留

- 重复幂等请求返回数据库中的当前任务，不会用初始状态覆盖已经推进的状态。
- 状态同步必须提供 `expected_revision`；只有所有者匹配且版本一致时才更新并把 `revision + 1`。
- 过期 worker 同步返回 `revision_conflict`，不能覆盖较新的状态。
- 制品字节仍走现有对象存储；本层只保存元数据。对象路径被固定为 `artifacts/{task_id}/{name}`，拒绝跨任务路径和路径穿越。
- 同名制品 upsert 保留 `created_at`，更新元数据与 `updated_at`。

## 3. Function 接口

### 3.1 平台数据库适配契约

```ts
createTaskStore({ database, clock?, idFactory? })
createPlatformTaskStore(options?)
```

生产加载器动态引用 Qoder 生成的 `./_qoder/database.mjs`，预期其导出 `database`。注入适配器必须满足：

```ts
database.transaction(async (tx) => {
  const result = await tx.query(固定SQL, 绑定参数);
  return result; // 查询方法返回 { rows }
})
```

所有 SQL 都是模块内的静态常量，值通过位置参数绑定。没有公开 `query(sql)`、`execute(sql)`、通用筛选器或任意表名参数。`schema.sql` 不在运行时加载。

**主线必须确认真实 `_qoder/database.mjs` 的导出和上述事务契约；如果平台形状不同，只应调整平台适配边界，不能把任意 SQL 能力暴露到请求层。**

### 3.2 所有者作用域方法

| 接口 | 用途 | 返回或错误 |
| --- | --- | --- |
| `createAnonymousSession({ clientIp?, userAgent? })` | 创建匿名会话 | 会话记录 |
| `getAnonymousSession(sessionId)` | 校验会话是否存在 | 会话或 `null` |
| `upsertSkillVersion(value)` | 受信服务端同步 Skill 版本 | 版本记录；不能作为浏览器公开路由 |
| `createTask({ sessionId, idempotencyKey, skillVersionId, quota, ... })` | 幂等建单与单次配额扣减 | `{ task, replayed }` |
| `getTask({ sessionId, taskId })` | 所有者单任务读取 | 任务或 `null` |
| `listTasks({ sessionId, limit?, offset? })` | 所有者任务列表，最大 100 条 | 当前所有者任务数组 |
| `updateTaskState({ sessionId, taskId, expectedRevision, state, nextCard })` | 带乐观锁的状态同步 | 新任务状态；`task_not_found` 或 `revision_conflict` |
| `listArtifacts({ sessionId, taskId })` | 所有者制品元数据列表 | 数组；非所有者与不存在均为 `task_not_found` |
| `syncArtifacts({ sessionId, taskId, artifacts })` | 所有者制品元数据 upsert | 保存后的元数据数组 |

浏览器公开路由必须由服务端从**已验证的 HttpOnly 会话 Cookie**得到 `sessionId`，不能接受浏览器在 JSON 中声明所有者。`upsertSkillVersion` 和 worker handler 只能挂在受信服务端路径。

### 3.3 固定 worker HTTP 表面

```ts
createWorkerTaskStoreHandler({ store, workerToken? })
```

`workerToken` 缺省时从服务端 `WORKER_SHARED_SECRET` 读取。鉴权使用 SHA-256 后的常量时间比较，不记录令牌。所有响应 `Cache-Control: no-store`。

| 方法与固定路径 | 额外鉴权／输入 | 用途 |
| --- | --- | --- |
| `GET /functions/v1/app/internal/task-store/tasks/{taskId}` | `X-Worker-Token`、`X-Session-Id` | 读取一个所有者任务 |
| `PUT /functions/v1/app/internal/task-store/tasks/{taskId}/state` | 令牌；JSON 含 `session_id`、`expected_revision`、`state`、`next_card` | 乐观锁状态同步 |
| `GET /functions/v1/app/internal/task-store/tasks/{taskId}/artifacts` | 令牌、`X-Session-Id` | 读取所有者制品元数据 |
| `PUT /functions/v1/app/internal/task-store/tasks/{taskId}/artifacts` | 令牌；JSON 含 `session_id`、`artifacts` | 同步所有者制品元数据 |
| `PUT /functions/v1/app/internal/task-store/skill-versions/{versionId}` | 令牌；固定 Skill 字段，路径与 body ID 必须一致 | 同步 Skill 版本 |

其他路径返回 `not_found`，不支持 `/query`、任意 SQL、跨所有者列表或公开任务写入。worker 请求体上限 2 MB，单制品元数据声明上限 50 MB，单任务最多 1000 个制品。

安全错误只返回固定代码，例如 `worker_unauthorized`、`task_not_found`、`revision_conflict`、`quota_exceeded` 和 `task_store_unavailable`。Provider 原始错误不会作为 HTTP 响应或异常 `cause` 向外传递。

## 4. Python worker 接口

`backend/app/sites_task_store.py` 提供：

```python
SitesTaskStoreClient(origin, shared_secret, transport=None, timeout=30)
SitesTaskStoreClient.from_environment(...)
```

生产环境变量沿用现有 `QODER_SITES_ORIGIN` 和 `WORKER_SHARED_SECRET`。远端必须是 HTTPS，仅允许本地开发使用 `localhost`／`127.0.0.1` 的 HTTP。

| 方法 | 固定 worker 操作 |
| --- | --- |
| `get_task(task_id, session_id)` | 所有者单任务读取 |
| `sync_task_state(task_id, session_id, expected_revision, state, next_card=None)` | 带版本的状态同步 |
| `list_artifacts(task_id, session_id)` | 所有者制品元数据读取 |
| `sync_artifacts(task_id, session_id, artifacts)` | 所有者制品元数据同步 |
| `sync_skill_version(version)` | 固定字段 Skill 版本同步 |

客户端没有接收 URL 路径、SQL、通用查询或任务列表过滤条件的公开方法。任务读取也必须显式提供所有者会话。`X-Worker-Token` 只加入请求头，不进入 URL、响应、日志或异常文本；`repr(client)` 仅显示 `[redacted]`。urllib 和自定义 transport 的原始错误统一转换为不保留异常链的 `SitesTaskStoreError('task_store_unavailable')`。

## 5. 测试输出

### 5.1 新增本地契约测试

命令：

```bash
node --test sites/functions/task_store.test.mjs
```

最终输出：

```text
✔ 未验证真实 Provider 权限与原子性：Schema 仅作审核，假库仅验证固定契约
✔ all task reads and writes are isolated by owner; keys are owner-scoped
✔ duplicate key returns the original task without charging or resetting old state
✔ concurrent same-key creates have one winner and exactly one quota charge
✔ quota denial rolls back its task insert and concurrent winners never exceed the limit
✔ stale revision cannot overwrite newer state
✔ artifact metadata is owner-scoped, validated, and upsert preserves creation time
✔ worker surface rejects illegal access, arbitrary queries, public writes, and stale sync
✔ Provider and transport failures produce safe errors without secrets, SQL, or local paths
✔ Python worker client uses fixed paths and redacts custom transport failures
ℹ tests 10
ℹ suites 0
ℹ pass 10
ℹ fail 0
ℹ cancelled 0
ℹ skipped 0
ℹ todo 0
ℹ duration_ms 206.513875
```

测试中的假数据库序列化事务、模拟唯一冲突与配额更新，并对固定 operation allowlist 之外的 SQL 直接报错。Python 测试通过 `spawnSync` 调用真实新客户端，但网络层是本地伪传输，不会访问远端。

### 5.2 既有 Function 回归

命令：

```bash
node --test sites/functions/*.test.mjs
```

结果：`tests 15`、`pass 15`、`fail 0`。既有 5 项路由／存储测试与新增 10 项全部通过。

### 5.3 既有 Python 相关回归

命令：

```bash
.venv/bin/python -m py_compile backend/app/sites_task_store.py
.venv/bin/python -m pytest \
  backend/tests/test_task_idempotency.py \
  backend/tests/test_remote_artifacts.py \
  backend/tests/test_deployment_config.py -q
```

结果：

```text
...............                                                          [100%]
15 passed in 0.95s
```

## 6. 主线实际接线点

以下均为现有文件中的接入位置，本轮没有修改这些文件：

### 6.1 `sites/functions/index.ts`

1. 在模块加载处引入 `createPlatformTaskStore` 和 `createWorkerTaskStoreHandler`，在服务端初始化 store。
2. 在现有内部制品路由（当前 `/internal/artifacts` 匹配附近）之前，把 `/internal/task-store/...` 请求交给固定 worker handler。其他请求继续原有路由。
3. 将 `POST /session` 的主存储切换为 `createAnonymousSession`；Cookie 仍必须由服务端签名并设置 `HttpOnly`、`Secure`、`SameSite=Lax`。不要把签名密钥下发前端。
4. 将公开 `POST /tasks` 接到 `createTask`：从已验证 Cookie 取所有者，从 `Idempotency-Key` 取键，从服务端配置取配额与当前 published Skill 版本。
5. 将公开 `GET /tasks`、`GET /tasks/{id}` 和制品列表接到所有者作用域方法。非所有者保持现有 404 语义。
6. 浏览器直接调用现有 Python 写任务转发应由主线在切换时移除；不能同时保留两个可分配任务 ID 的主写入源。

### 6.2 `backend/app/public_access.py` 与 `backend/app/main.py`

- `create_public_session` 当前仍写 SQLAlchemy `invite_sessions`。主线需要决定由 Function 直接创建会话后如何保持现有 Cookie 验证，避免 Python 与 Qoder 各自生成一套不相交的会话主记录。
- `create_task`、`_task_with_idempotency_key`、`list_tasks`、`read_task` 是当前 SQLAlchemy 主存储点。主线切换时应以 Qoder 任务记录为准，避免双库同时承担创建与配额权威。
- 现有 IP 级会话／建单限制与模型、检索限制仍需保留，并明确它们与 Qoder 会话级建单窗口的先后和失败补偿策略。

### 6.3 `backend/app/queueing.py` 与 `worker.py`

- 在 worker 初始化时通过 `SitesTaskStoreClient.from_environment()` 创建客户端并注入阶段服务。
- `run_stage` 开始阶段前用 `get_task(task_id, session_id)` 获取所有者任务与 `revision`。
- 阶段完成或失败时用读到的 revision 调用 `sync_task_state`；遇到 `revision_conflict` 必须重新读取并协调，不能强制覆盖。
- 现有 `TaskAnswer`、`TaskEvent`、`TaskProgress` 和 RQ job 状态仍在 Python 模型中。本轮没有定义它们的云迁移；完全移除 Python 数据库前，主线必须另行设计这些数据的存储与一致性。

### 6.4 Skill 与制品

- 在现有 Skill 发布／回滚流程完成后，用 `sync_skill_version` 同步对应版本；建单只接受 Qoder 中 `published` 的版本，任务永久保留原 `skill_version_id`。
- 现有 `SitesStorageClient` 继续上传和读取对象字节。上传成功后，用 `sync_artifacts` 写入名称、大小、类型、校验和与对象路径元数据；不要把字节塞进 JSON 或数据库。
- 现有签名下载 URL 的生成仍由服务端负责，数据库中的对象路径不能直接变成公开未授权 URL。

### 6.5 Schema 与 Provider 权限

- 由主线通过 Qoder 审核迁移流程人工应用 `sites/schema.sql`，不要在 Function cold start、Python worker 或测试中自动执行。
- Provider 角色应只允许服务端适配器访问这些表；浏览器匿名角色不应具有直接 `INSERT`、`UPDATE`、`DELETE` 或跨所有者 `SELECT` 能力。
- 上线前必须用真实 Provider 重跑：同 key 高并发、配额拒绝回滚、不同所有者同 key、过期 revision、非所有者制品读取、错误脱敏和令牌轮换。
- 如果真实适配器不保证多语句事务，不能宣称已满足建单与配额原子性；应先补齐平台事务能力或数据库原子存储过程，再继续接入。

## 7. 当前结论

适配层、审核 Schema、Python 固定 worker 客户端和本地测试已经齐备，现有主线文件保持原样。可以把本交付作为主线统一接入的独立模块，但不能把本地假库结果解释为真实 Provider 已验证，也不能在未完成上述接线与真实环境测试前宣称 Qoder 已成为线上主存储。
