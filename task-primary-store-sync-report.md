# Qoder Sites Python 主存储同步层及假 Provider 验收报告

## 1. 交付范围与边界

本轮仅新增 3 个文件：

1. `backend/app/task_store_sync.py`：同步接口、身份校验、revision 冲突处理与错误脱敏。
2. `backend/tests/test_task_store_sync.py`：内存假 Provider 及验收测试。
3. `task-primary-store-sync-report.md`：本报告。

未修改 `main.py`、`public_access.py`、`orchestration.py`、`models.py`、`sites_task_store.py`、Function 或前端；未接入主路由或 worker；未执行云端迁移、真实网络请求或 Provider 写入。

**真实 Provider 权限与事务原子性：未验证。** 本轮结果只证明 Python 同步层与内存假客户端之间的契约，不证明线上权限、唯一约束、并发事务、配额回滚或 Provider 故障语义已经成立。

## 2. Python 接口

同步层通过构造函数注入既有 `SitesTaskStoreClient` 兼容客户端，不自行读取凭据或建立网络连接：

```python
TaskStoreSync(client)
```

| 接口 | 行为 |
| --- | --- |
| `sync_session(session_id, client_ip='', user_agent='')` | 创建指定 ID 的远端匿名会话；返回值必须与请求的 `session_id` 完全一致 |
| `sync_skill_version(version)` | 同步既有客户端允许审阅的 Skill 字段；核对返回的 `id`，并核对请求中存在的 `version`、`state`、`content_hash` |
| `create_task(session_id, task_id, idempotency_key, skill_version_id, quota, state='collecting_mode', next_card='direction')` | 同步会话、任务、幂等键、Skill 版本和初始状态；新建时核对全部身份字段 |
| `sync_task_state(session_id, task_id, state, next_card=None)` | 先调用 `get_task` 读取远端 revision，再以该 revision 执行一次条件状态写入 |
| `sync_artifacts(session_id, task_id, artifacts)` | 只同步制品元数据；核对任务归属、文件名、大小、Content-Type、SHA-256 和 JSON 元数据 |

异常接口：

- `TaskStoreSyncError`：只携带固定安全代码，默认 `task_store_sync_failed`。
- `TaskStoreRevisionConflict`：`TaskStoreSyncError` 子类，固定代码 `revision_conflict`。

### 2.1 幂等与配额

`create_task` 不增加第二层配额计数，也不在重试前另建任务。假 Provider 按 `(session_id, idempotency_key)` 返回原任务，并且只在实际新建时扣减一次配额。

重复 key 的返回以远端原记录为准：重试携带的候选 `task_id`、初始状态或其他 Skill 版本不会重置原任务。同步层仍校验原记录的所有者会话和幂等键，避免接受串会话响应。

### 2.2 状态冲突

每次状态同步严格采用以下顺序：

1. `get_task(task_id, session_id)` 读取所有者任务和当前 revision。
2. 校验返回的 `session_id`、`task_id` 和 revision。
3. `sync_task_state(..., expected_revision=刚读取的 revision)` 执行一次条件写入。
4. 核对返回状态和 `revision + 1`。

若读取后发生并发更新，则抛出 `TaskStoreRevisionConflict`，不自动重试、不强制覆盖。是否协调新状态必须由上层业务决定。

### 2.3 错误脱敏

所有公开同步方法统一捕获客户端异常，仅映射白名单中的固定代码；其他异常一律变成 `task_store_sync_failed`。错误消息、参数和表示形式不包含原始异常文本，也不保留异常链。

测试注入的原始异常同时包含 token、SQL、Provider 响应正文和本地路径；会话、Skill、建单、状态读取、状态写入和制品同步六个边界均验证这些内容不会出现在抛出的错误或格式化异常信息中。

## 3. 假 Provider 验收覆盖

| 场景 | 验证结果 |
| --- | --- |
| 会话与 Skill | 保留同一 `session_id`、Skill ID、版本号、发布状态和内容哈希 |
| 建单 | 同步同一任务 ID、所有者、幂等键、Skill 版本、初始状态及下一卡片；配额计数为 1 |
| 重复 key | 返回已推进的原任务，不新建记录、不重置状态、不再次扣配额 |
| 最新 revision | 本地观测过期时仍先读取远端 revision 7，并以 7 条件写入到 8 |
| 状态冲突 | 读取后模拟远端并发完成；旧状态写入被拒绝，远端 `done` 和 revision 2 保持不变，写入只尝试一次 |
| 制品同步 | 核对任务作用域及完整元数据；对象路径固定为 `artifacts/task-1/report.docx` |
| 同步失败 | 六个公开调用边界均只暴露安全固定代码，敏感片段全部不出现 |

## 4. 实际测试输出

### 4.1 编译与新增验收

命令：

```bash
.venv/bin/python -m py_compile \
  backend/app/task_store_sync.py backend/tests/test_task_store_sync.py
.venv/bin/python -m pytest backend/tests/test_task_store_sync.py -q
```

实际输出：

```text
............                                                             [100%]
12 passed in 0.03s
```

`py_compile` 成功且无额外输出。

### 4.2 相关既有回归

命令：

```bash
.venv/bin/python -m pytest \
  backend/tests/test_task_store_sync.py \
  backend/tests/test_task_idempotency.py \
  backend/tests/test_remote_artifacts.py \
  backend/tests/test_deployment_config.py -q
```

实际输出：

```text
.................................                                        [100%]
33 passed in 0.28s
```

其中新增 12 项，相关既有 21 项，全部通过。

## 5. 主线实际接线点（本轮未接线）

| 现有位置 | 后续接入动作 |
| --- | --- |
| `backend/app/public_access.py:create_public_session` | 在现有会话创建与 Cookie 签发流程中调用 `sync_session`，确保 Python Cookie 对应同一远端 `session_id`；保留现有 IP 级会话限流 |
| `backend/app/main.py:create_task` | 将 SQLAlchemy 新建主记录切换为 `create_task`，从已验证会话取所有者、从当前 published Skill 取版本；重复 key 直接采用远端返回，不再执行一次本地建单配额扣减 |
| `backend/app/skill_versions.py:SkillVersionService.publish / rollback` | 在本地发布或回滚事务成功后同步对应 Skill 版本；若远端失败需要明确的重试与对账策略，不能伪称双库事务 |
| `backend/app/queueing.py:run_stage` | 阶段产生 `result_state` 后调用 `sync_task_state`；遇到 `revision_conflict` 必须重新读取并业务协调，不能直接覆盖 |
| `backend/app/orchestration.py:Orchestrator._sync_artifacts` | 现有对象字节上传成功后调用 `sync_artifacts`；需要把任务的 `session_id` 传入该流程，并生成大小、类型、SHA-256 与元数据 |

主线切换时必须避免 Python 与 Qoder 同时作为建单和配额的权威写入源。既有 `TaskAnswer`、`TaskEvent`、`TaskProgress`、RQ 状态和本地制品字节不在本轮迁移范围内。

## 6. 已观察到的接线前置条件

1. 既有 Python 客户端会把指定会话 ID 放在会话请求的 `id` 字段，但当前 `sites/functions/task_store.ts` worker handler 未把该字段传给 `createAnonymousSession`。因此，真实接线前必须让服务端明确支持保留该 ID；否则 `sync_session` 会以 `invalid_provider_response` 拒绝不同 ID，而不会静默接受分叉会话。
2. 既有 `SitesTaskStoreClient` 会把 urllib 的 HTTP 错误统一转换为 `task_store_unavailable`。若主线需要在线上区分 HTTP 409 `revision_conflict`，必须在固定 worker 传输边界保留这个安全代码；本层不会解析 Provider 响应正文，也不会放宽脱敏边界。
3. 上述两项均未在本轮修改。假客户端直接实现安全冲突代码和指定会话 ID 契约，因此测试不能替代真实 HTTP／Provider 验证。

## 7. 上线前仍需验证

- 真实 Provider 的服务端角色权限、RLS、匿名角色隔离和令牌轮换。
- `(session_id, idempotency_key)` 唯一竞争、同 key 高并发、配额只扣一次及拒绝后的回滚。
- 多语句事务原子性与隔离级别；若平台不具备事务保证，不能宣称建单和配额已原子完成。
- 过期 revision、非所有者读取、制品 upsert、安全 HTTP 错误映射和敏感日志检查。
- 云端迁移必须由主线另行审核与执行，本轮未执行任何迁移。

## 8. 结论

同步层和假 Provider 验收已完成，新增及相关回归测试均通过；主路由、worker、前端和云端数据保持未接线、未迁移状态。当前成果可作为后续主线接入的独立模块，但不能据此宣称真实 Provider 权限或事务原子性已经验证。
