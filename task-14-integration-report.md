# Task 14：限流接线、持久幂等与真实并发验证报告

## 执行与同步范围

本轮先在工作区副本上增量实现，再通过逐文件补丁同步到原始应用目录：

`/Users/crisprcas_9/WorkBuddy/2026-11-06-20-49-06/purpose-landscape-web`

已有文件均以补丁合入，没有整文件覆盖；新增文件直接复制。同步后的 13 个功能与测试文件已和工作副本逐一进行字节比较，结果一致。

未修改 `graphs.py`、`orchestration.py`、`test_graphs.py` 或 `test_orchestration.py`。主线已有的图谱制品、图谱断言修复、窄屏动效、Skill 版本、动态确认卡、候选术语、C1+C2、制品下载和远程 Storage 逻辑均保留。

未部署、未创建云资源、未调用付费模型。测试使用 SQLite、fakeredis 和本地测试替身；前端构建仅为本地验证。

## 实际改动文件

### 后端实现

- `backend/app/rate_limit.py`（新增）
  - Redis 固定窗口、会话/IP 双维度原子扣减、幂等重放、429/503 安全结果和 `Retry-After`。
  - 可信代理解析及共享 HTTP/worker 依赖。
- `backend/app/queueing.py`
  - 入队异常、未知 stage、检查点失败和重复执行边界。
  - `search` 在真实服务前扣减 `retrieval` 与 `model`；`generate` 扣减 `model`。
  - worker 限流失败写入 `rate_limited` 事件、安全消息、重试动作和 `retry_after`，不执行付费/远程服务。
- `backend/app/public_access.py`
  - 会话写库和 Cookie 签发前执行 IP 限流，持久化服务端解析后的来源 IP。
- `backend/app/main.py`
  - 任务创建接入 `Idempotency-Key`、限流、版本固定和唯一竞争恢复。
  - 候选术语生成在真实模型/OpenAlex 调用前执行模型与检索限流。
  - 入队失败转换为安全 503 和 `Retry-After`，不暴露内部异常。
- `backend/app/models.py`
  - `Task` 新增可空 `idempotency_key`。
  - 新增 `(session_id, idempotency_key)` 唯一约束；保留 `skill_version_id`、`created_at`、`updated_at` 和既有关系。
- `backend/app/db.py`
  - 增加旧库列升级、空字符串归一化为 NULL 和唯一索引迁移。

### 前端

- `frontend/src/api.ts`
  - `createTask(idempotencyKey)` 发送 `Idempotency-Key` 请求头。
- `frontend/src/App.tsx`
  - 创建请求生成 UUID key；失败后同组件内重试保留 key，成功后清除。
  - 用户明确点击“新建研究”生成新 key，因此相同空请求体也可合法创建新任务。

### 测试

- 新增 `backend/tests/conftest.py`：为真实路由/worker 接线注入隔离的 fakeredis，不依赖本机 Redis。
- 新增 `backend/tests/test_rate_limit.py`：原子配额、窗口、幂等、可信代理、Redis 故障和安全输出。
- 新增 `backend/tests/test_queue_failures.py`：入队、未知 stage、执行/检查点失败、重复执行及 worker 配额。
- 新增 `backend/tests/test_task_idempotency.py`：真实 API 并发、重启重试、空 body 新任务、会话隔离、429 和旧库迁移。
- 增量补充 `backend/tests/test_task_api.py`：候选模型超限返回真实路由 429，且不会调用模型。

### 报告

- 新增 `task-14-integration-report.md`。

## HTTP 与 worker 接线行为

### 会话和任务

- `POST /api/session`：限流失败时不创建会话记录、不签发 Cookie；超限返回 429 和秒级 `Retry-After`。
- `POST /api/tasks`：按会话和当前来源 IP 限流；相同 key 的已有任务在配额检查前直接返回，避免重启或 Redis 记录过期后的重复扣额。
- 候选术语：只有需要实际生成候选时才扣模型/检索配额，命中既有候选事件不会重复扣额。

### 来源 IP

默认只信任 socket peer，直接忽略访客的 `X-Forwarded-For`。只有将代理 IP/CIDR 配置到 `TRUSTED_PROXY_IPS`（逗号分隔）后，才处理来自这些代理的 `X-Forwarded-For`，并从右向左跳过受信代理层。非法转发头回退到 socket peer。

代理自身仍必须正确清理或追加客户端转发头；应用不会信任来自未配置直连访客的该头。

### worker

- `search`：检索和模型各一个阶段配额单位。
- `generate`：模型一个阶段配额单位。
- 幂等键使用 `task_id:stage:input_hash`，已完成的 RQ 重复投递在配额检查前返回原检查点。
- 多操作阶段若后续操作超限，已成功的先前操作在重试时通过幂等记录重放，不会重复扣减。
- worker 没有 HTTP 响应；其限流结果以安全 `StageExecutionError`、`rate_limited` 事件和 `retry_after` 表示。自动延迟重投仍需 RQ 调度策略配合。

## 持久幂等与并发竞争

任务创建顺序如下：

1. 读取并规范化客户端 key；空 key 或超过 255 字符返回 422。
2. 先查询同一会话、同一 key 的任务；存在则直接返回任务 A，不扣配额。
3. 使用相同 key 消费限流配额；Redis 幂等记录使并发或网络重放只扣一次。
4. 读取当前 published Skill 版本，创建任务 A 并固定 `skill_version_id`。
5. 并发唯一竞争时捕获 `IntegrityError`，回滚当前事务，再查询并返回已存在任务 A。

数据库唯一性不依赖请求体或内容哈希。不同 key 的相同 `{}` 请求体会创建不同任务；不同会话使用相同 key 互不影响。

为兼容旧 API 客户端，缺少请求头时服务端生成随机 key。**没有 key 的重试无法提供幂等保证**，新前端始终发送 key。

## 数据库迁移 SQL

迁移在 `backend/app/db.py` 的 `initialize_database()` 中执行；本轮未新增独立迁移文件。

```sql
ALTER TABLE tasks ADD COLUMN idempotency_key VARCHAR(255);
UPDATE tasks SET idempotency_key = NULL WHERE idempotency_key = '';
CREATE UNIQUE INDEX IF NOT EXISTS uq_tasks_session_idempotency_key
ON tasks (session_id, idempotency_key);
```

仅在列缺失时执行 `ALTER TABLE`。NULL 不重复参与唯一约束，因此多个旧任务的 NULL 保持兼容；部分升级产生的空字符串转换为 NULL，避免唯一索引冲突。既有版本和时间戳字段不归一化、不重建、不清空。

迁移测试使用一个含版本和时间戳的旧表、一个 NULL key 和一个空字符串 key，验证升级后两行均保留、版本和时间戳不变、key 均为 NULL 且唯一索引存在。

## 原始目录验证结果

### 8 路真实 API 并发

执行目录：原始应用根目录。

```bash
./.venv/bin/python -m pytest backend/tests/test_task_idempotency.py::test_concurrent_api_retries_create_one_task_and_consume_quota_once -q
```

实际输出：

```text
.                                                                        [100%]
1 passed in 0.12s
```

该测试使用文件 SQLite、每请求独立数据库会话和 8 个线程，从 API 层发送相同 Cookie 和相同 key，并断言：

- 8 个响应均返回同一个任务 A。
- 数据库只有 1 条任务记录。
- 所有响应固定到同一个 published Skill 版本，版本表未新增记录。
- 会话/IP 两个 Redis 计数器均只有 1。

### 全量后端回归

```bash
./.venv/bin/python -m pytest backend/tests -q
```

实际输出：

```text
........................................................................ [ 32%]
........................................................................ [ 65%]
..................s..................................................... [ 97%]
.....                                                                    [100%]
220 passed, 1 skipped in 10.31s
```

跳过项仍为默认关闭的实时 OpenAlex 冒烟测试，未启用网络实时测试。主线修复后的图谱测试包含在本次全量回归中并全部通过，本轮未修改其实现或测试。

### 前端回归与本地构建

```bash
npm test -- --run && npm run build
```

实际结果：

```text
Test Files  7 passed (7)
Tests       22 passed (22)
tsc --noEmit 通过
vite build 成功，44 modules transformed
```

## 剩余边界

1. **Redis 与数据库不是分布式原子事务**：首次请求可能在限流成功后遇到数据库故障，从而占用一次配额；同 key 重试不会重复扣额，但需要监控并设置合理配额。
2. **自动 worker 重试尚未配置**：`retry_after` 已持久化，RQ 的延迟重投、最大重试次数和陈旧 `started` 恢复仍需调度/恢复任务。SIGKILL 或宿主机故障不等同于已捕获异常。
3. **前端整页刷新后的 key 保留**：当前 key 保存在组件 ref，网络失败后的同组件重试会复用；若要求整页刷新后继续同一未决请求，应把未决 key 和任务 ID 进一步持久化到 sessionStorage。
4. **代理拓扑需生产核对**：必须配置准确的 `TRUSTED_PROXY_IPS`，并确认受信代理会清理伪造头，不能把配置本身当作代理正确性的证明。
5. **配额默认值需容量评估**：上线前应结合真实匿名流量、模型成本和检索供应商限制调整规则、幂等 TTL、监控与告警。
6. **生产数据库迁移演练**：当前验证覆盖 SQLite；正式 PostgreSQL 环境应在备份后验证并发创建索引策略和迁移耗时，本报告不代表已执行生产迁移。
