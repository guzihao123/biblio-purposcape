# 安全与隔离复核报告

- 复核对象：`/Users/crisprcas_9/WorkBuddy/2026-11-06-20-49-06/purpose-landscape-web`
- 分支：`main`；复核方式：**只读代码审阅 + 运行现有测试**，未改生产代码、未部署、未连接生产 DB、未打印任何密钥值
- 复核时间：2026-11-25
- 阅读范围：`backend/app/{security,public_access,artifacts,sites_store,sites_task_store,task_store_sync,queueing,recovery,rate_limit,skill_versions,config,db,models,main}.py` 及对应测试

## 一、结论摘要

| 严重度 | 数量 | 摘要 |
|---|---|---|
| 高（High） | 1 | `SitesStorageClient` 的 Origin 前缀校验可被 `http://localhost.evil.*` / `http://127.0.0.1.evil.*` 绕过，导致 `X-Worker-Token` 以明文 HTTP 发往任意域名 |
| 低（Low） | 2 | 日志脱敏对"名称敏感的环境变量"过度替换，污染日志；`_sites_raise` 回显 `str(error)` 依赖调用方异常已安全化 |
| 信息/无问题 | 5 类 | 会话隔离、管理接口、制品签名/穿越/上限、限流与队列、生产配置守卫均有测试与代码证据支撑 |

测试汇总：`183 passed, 5 warnings in 7.26s`（16 个安全相关测试文件全量通过）。测试运行期间 `backend/tests/fixtures/worker/results/` 被用例改写，已按约定 `git restore`，复核结束工作区除本报告与一个并行任务目录外无改动。

---

## 二、发现项（按严重度排序）

### HIGH-01 · SitesStorageClient 的 Origin 前缀校验被绕过，Worker 共享密钥可泄露至任意域名

- **位置**：`backend/app/sites_store.py:49-55`（构造校验）、`backend/app/sites_store.py:82-99`（`_call` 注入 header）、`backend/app/sites_store.py:101-164`（`put_bytes`/`get_bytes`/`list` 发送请求）、`backend/app/artifacts.py:30-35`（由环境变量自动创建该客户端）
- **根因**：Origin 白名单用字符串 `startswith` 判断本地地址：

  ```python
  self.origin = origin.rstrip('/')
  if not self.origin.startswith('https://') and not self.origin.startswith(
      ('http://127.0.0.1', 'http://localhost')
  ):
      raise ValueError('Qoder Sites origin must use HTTPS')
  ```

  `startswith('http://localhost')` / `startswith('http://127.0.0.1')` 只匹配前缀，不做主机名边界判断。于是 `http://localhost.attacker.tld`、`http://127.0.0.1.attacker.tld` 这类**真实指向外部主机的域名**会被当作"本地 HTTP"放行。

- **复现（手工验证，未发包、未使用真实密钥）**：

  ```
  REJECTED  origin=http://site.example            （普通 HTTP 被正确拒绝）
  ACCEPTED  origin=http://127.0.0.1.evil.test     （应拒绝，实际放行）
  ACCEPTED  origin=http://localhost.evil.test     （应拒绝，实际放行）
  ACCEPTED  origin=http://127.0.0.1               （合法本地，放行正确）
  ACCEPTED  origin=https://site.example           （合法 HTTPS，放行正确）
  ```

- **影响**：`ArtifactStore.__init__`（`artifacts.py:30-35`）只要环境变量 `QODER_SITES_ORIGIN` 与 `WORKER_SHARED_SECRET` 同时非空，就会以此 origin 自动构造客户端。此后 `put_bytes`/`get_bytes`/`list`（`sites_store.py:106/118/130/154`）会把 `X-Worker-Token: self.shared_secret`（`sites_store.py:109/120/132/157`）连同 `Origin` header（`sites_store.py:85`）一起，以**明文 HTTP** 发送到被伪造的 origin。后果包括：
  1. Worker 共享密钥泄露给任意第三方，攻击者可据此伪造制品读写请求；
  2. 制品完整性校验形同虚设——`get_bytes` 下载内容与其 SHA-256 校验端点（`sites_store.py:130-148`）都由同一恶意 origin 提供，攻击者可同时返回匹配的内容与摘要。
- **对比佐证**：同一仓库的 `SitesTaskStoreClient.__init__`（`backend/app/sites_task_store.py:45-53`）用 `urlsplit(origin)` 解析并精确比较 `parsed.hostname in {'127.0.0.1','localhost'}`，对同样的 `http://127.0.0.1.evil.test`、`http://localhost.evil.test` 均**正确拒绝**。说明安全解析方式已存在，仅 `SitesStorageClient` 遗漏。
- **测试证据**：现有 `test_deployment_config.py:178-201` 的 `test_sites_storage_client_uploads_fixed_worker_paths_only` 仅断言 `http://site.example` 被拒，未覆盖 `localhost.*` / `127.0.0.1.*` 前缀绕过，故该缺陷未被测试捕获。其余 `test_sites_storage_client_*`（18 项）均通过，覆盖路径穿越、50 MB 上限、异常清洗，但不覆盖本项。
- **修复建议（本次不改代码）**：改用 `urlsplit` 精确解析 hostname，与 `SitesTaskStoreClient` 保持一致；仅当 `parsed.scheme == 'http' and parsed.hostname in {'127.0.0.1','localhost'}` 时才放行本地 HTTP，其余一律要求 `https`；并拒绝带 `username`/`password`/`query`/`fragment` 的 origin。补充上述两个绕过字符串的回归测试。

### LOW-01 · 日志脱敏对"名称敏感的环境变量"过度替换，污染访问日志

- **位置**：`backend/app/recovery.py:127-141`（`redact_sensitive_text` 的环境变量替换集合）
- **现象**：替换集合的纳入条件是 `len(item) >= 4 or re.search(r'token|secret|password|...|api[_-]?key|...', name)`（`recovery.py:130-137`）。只要**变量名**含敏感词，即使值很短（如值为 `"1"`）也会被纳入，随后被全局 `text.replace(item, '[REDACTED_ENV]')`（`recovery.py:139-140`）。宿主环境中 `CODEBUDDY_API_KEY_HELPER_DISABLED=1` 即命中，导致访问日志中的 `HTTP/1.1`、`127.0.0.1:12345` 里的数字 `1` 被替换为 `[REDACTED_ENV]`，破坏日志可读性并造成测试脆弱。
- **测试证据**：`backend/tests/test_recovery.py::test_uvicorn_access_and_exception_logs_redact_artifact_requests` 在本宿主环境下失败（`assert 'GET /api/health HTTP/1.1' in ...` 不成立）；用 `env -u CODEBUDDY_API_KEY_HELPER_DISABLED` 清理后，`test_recovery.py` 8/8 通过、合并安全集 183/183 通过。
- **定性**：这是**过度脱敏**，方向偏安全，不构成密钥/连接串泄露；影响限于日志可读性与测试稳定性。建议对纳入环境变量值设最小长度（如统一 `len(item) >= 4`），或仅替换完整 token 边界而非裸子串。

### LOW-02 · `_sites_raise` 将远端异常字符串回显到 HTTP detail，安全性依赖调用方异常已脱敏

- **位置**：`backend/app/main.py:65-74`、`backend/app/public_access.py:25-32`：

  ```python
  raise HTTPException(status_code=status,
                      detail={'code': code, 'message': str(error)}, headers=headers)
  ```

- **分析**：当前调用链上抛出的异常均为安全异常——`SitesTaskStoreError.__init__`（`sites_task_store.py:31-40`）与 `TaskStoreSyncError.__init__`（`task_store_sync.py:37-45`）都以**安全 code** 作为 `str()` 内容，且 `@_safe_errors`（`task_store_sync.py:55-72`）把任意底层异常归一为 `TaskStoreSyncError(code)`，因此现网不会泄露 Provider body 或连接串。`test_sites_task_store.py` 全套、`test_sites_mode_routes.py` 均通过，验证了 body 不被读取（`body.read_calls == 0`）、`__cause__/__context__` 为 `None`。
- **定性**：属纵深防御建议，非已确证泄露。建议改为直接回显白名单 `code` 对应的固定文案，避免未来新增未脱敏异常时把 `str(error)` 透出。

---

## 三、无问题项及验证方法（逐项）

### 3.1 匿名会话：Cookie 属性、TTL、撤销、owner 隔离 — 通过

| 检查点 | 结论 | 代码依据 | 验证方法/证据 |
|---|---|---|---|
| Cookie `HttpOnly`/`Secure`/`SameSite=lax` | 通过 | `security.py:38-44`、`public_access.py:60-66` | `test_sessions.py::test_invite_code_creates_http_only_session`、`test_public_access.py::test_public_session_requires_no_invite_code` 断言三个属性均存在 |
| 签名与伪造 | 通过 | `security.py:37,51` 用 `URLSafeSerializer(session_secret)`；`security.py:52-56` 捕获 `BadSignature/TypeError/ValueError` 且校验类型为 str | 同测试用错误 secret 反序列化抛 `BadSignature`；篡改 cookie 返回 401（`test_missing_and_tampered_sessions_are_rejected`） |
| TTL | 通过（设计选择） | `config.py:22` `session_ttl_seconds=604800`（7 天，且 `Field(gt=0)`）；`models.py:16-19,28-32` 服务端写入绝对 `expires_at`；`security.py:61-69` 每次请求校验过期并做时区归一 | `test_public_access.py::test_public_session_has_absolute_server_expiry` 验证 `expires_at` 落在创建时刻 + TTL 区间；`test_legacy_session_security_migration_*` 验证迁移可重复且不破坏数据。注意 Cookie 本身未设 `Max-Age/Expires`（浏览器会话级），但服务端绝对过期为准，属安全设计 |
| 撤销 | 通过 | `revoke_session` 持久化 `revoked_at` 且幂等（`security.py:73-80`）；`require_session` 校验 `revoked_at`（`security.py:58-59`） | `test_revoke_session_service_is_persistent_and_idempotent`、`test_admin_revoke_route_blocks_access_is_idempotent_and_preserves_other_sessions`：撤销后建任务/答卡/读报告/下载制品全部 401，其他会话不受影响 |
| owner 隔离（非所有者 404） | 通过 | `require_owner`（`security.py:83-86`）比较 `task.session_id != session.id` 抛 404；`_owned_task`（`main.py:88-100`）在所有读/答/制品/仪表盘/报告路由前调用 | `test_session_cannot_read_another_sessions_task`、`test_public_users_cannot_read_each_others_tasks` 断言 404 且响应与"不存在的任务"完全一致；`test_session_ownership_does_not_follow_proxy_ip` 验证所有权不随 `X-Forwarded-For` 变化。sites 模式下隔离由 `sync.get_task(session.id, task_id)` 承载，同样有测试覆盖 |

### 3.2 管理接口：ADMIN_TOKEN、错误响应、并发与唯一 published — 通过

| 检查点 | 结论 | 代码依据 | 验证方法/证据 |
|---|---|---|---|
| ADMIN_TOKEN 校验 | 通过 | `require_admin`（`security.py:89-91`）用 `hmac.compare_digest`，与会话密钥分离 | `test_admin_requires_the_separate_admin_token`（空/错误/会话密钥均 403）；`test_admin_draft_route_rejects_missing_token_and_accepts_separate_admin_token`（无 token 403、正确 token 201） |
| 常量时间比较 | 通过 | `security.py:90` | `test_admin_secret_uses_constant_time_comparison` 记录并断言只调用一次 `compare_digest` |
| 非 ASCII token 不触发 500 | 通过 | `security.py:90` 对 header 用 `latin-1` 编码、对配置用 `utf-8` 编码 | `test_non_ascii_admin_token_never_causes_500` 断言错误 token 返回 403、正确 token 返回 200 |
| 错误响应不泄露/不暴露资源存在性 | 通过 | `revoke_admin_session`（`main.py:587-594`）统一用 `require_admin`；`revoke_session` 对不存在 id 返回 404 | `test_admin_revoke_route_requires_admin_and_hides_session_existence`：对存在/不存在会话，非管理员一律 403；`test_admin_revoke_route_blocks_...` 断言响应与日志中均不含 admin token、cookie、签名、client_ip、user_agent |
| 发布/回滚并发与唯一约束 | 通过 | `SkillVersionService._serialized_write` 用 `BEGIN IMMEDIATE`(SQLite)/`LOCK TABLE ... SHARE ROW EXCLUSIVE`(PG)（`skill_versions.py:83-111`）；部分唯一索引 `uq_skill_one_published`（`models.py:117-125`） | 手工核验索引存在：`[('uq_skill_one_published', 1)]`。`test_concurrent_sibling_publish_has_one_winner_and_one_current_version`（1 胜 1 冲突、published 仅 1）；`test_concurrent_duplicate_transitions_drain_tasks_and_are_idempotent`；`test_concurrent_drafts_receive_distinct_version_numbers`；`test_api_style_task_pinning_and_publish_cannot_cross_the_drain_gap`。另 `test_publish_requires_a_passing_regression`、`test_active_task_blocks_publish_and_rollback_*`、`test_later_drafts_cannot_mutate_published_fields_or_original_audit` 覆盖发布前置与不可变性 |

### 3.3 制品：签名 URL、负载、路径穿越、大小上限、Origin/Token — 除 HIGH-01 外通过

| 检查点 | 结论 | 代码依据 | 验证方法/证据 |
|---|---|---|---|
| 签名 URL TTL | 通过 | `artifacts.py:37-38` `URLSafeTimedSerializer(salt='artifact-download-v1')`；`artifacts.py:118` `loads(signature, max_age=600)` | `test_expired_signature_is_rejected_before_remote_fallback` 用时间戳 0 造过期签名，断言 403 且**不触发远端访问** |
| 签名负载绑定 | 通过 | `artifacts.py:65-76` 负载含 `{task_id, filename, session_id}`；`artifacts.py:121` 严格整体相等比较；`main.py:400-409` 下载前先 `_owned_task` 再 `resolve` | `test_signed_parameter_tampering_is_rejected_before_storage` 参数化 wrong-task/wrong-filename/non-owner 三例全部 403、`remote.get_calls == []` |
| 路径穿越（含编码） | 通过 | `sites_store.py:26-45` `validate_filename` 5 轮 unquote 并拒绝 `.`/`..`/`Path(name)!=name`/`..`/`/`/`\\`/`\x00`；`sites_store.py:21-23` `validate_task_id` 限 `[A-Za-z0-9-]{1,64}`；`artifacts.py:47-63` `resolve(strict=True)` + `directory.parent==root`/`resolved.parent==directory` 校验 | `test_path_traversal_and_encoded_traversal_are_rejected_before_remote_fallback`（`../secret`、`..%2F`、`%2e%2e%2f`、`%252e...`、`..%5C`）；`test_task_id_traversal_is_rejected_before_local_or_remote_access`；`test_sites_storage_client_rejects_task_and_filename_traversal_before_transport` 断言请求未发出（`calls == []`） |
| 大小上限 | 通过 | `sites_store.py:10` `MAX_ARTIFACT_BYTES=50_000_000`；本地 `artifacts.py:60`、远端 `sites_store.py:104-105,127-128`、`artifacts.py:127` | `test_local_size_limit_includes_exact_50_mb_and_rejects_one_byte_over`、`test_remote_size_limit_...` 验证恰好 50 MB 通过、+1 字节 404 |
| 远端异常清洗 | 通过 | `sites_store.py:95-99` 统一抛 `StorageError('remote artifact request failed')`；`artifacts.py:124-138` 区分 `ArtifactIntegrityError`/`ValueError` 返回 404 | `test_remote_download_failures_are_generic_and_sanitized`、`test_sites_storage_client_sanitizes_transport_failures`、`test_sites_storage_client_rejects_non_numeric_status_without_echoing` 断言密钥/URL/路径不出现在异常中 |
| 下载响应头 | 通过 | `main.py:417-442` `Cache-Control: private, no-store` | 人工代码核验 + `test_deployment_config.py:142-149` 确认函数侧保留二进制下载头 |
| **Origin/Token 处理** | **未通过 → HIGH-01** | `sites_store.py:49-55` 前缀校验缺陷 | 见 HIGH-01；`X-Worker-Token` 仅出现在 header 而非 URL（`sites_store.py:109/120/132/157`）这一点本身通过，缺陷在 origin 放行逻辑 |

### 3.4 限流与队列：429、idempotency-key、重试与恢复、日志脱敏 — 通过

| 检查点 | 结论 | 代码依据 | 验证方法/证据 |
|---|---|---|---|
| 429 与限流原子性 | 通过 | `rate_limit.py:83-99` 默认规则；`rate_limit.py:312-356` Redis `WATCH/MULTI` 全维度原子扣减，超限 429 + `Retry-After`（`rate_limit.py:335-341`） | `test_anonymous_session_creation_is_limited_by_source_ip`、`test_session_denial_does_not_partially_charge_ip_or_other_sessions`、`test_fixed_window_boundary_and_retry_after_are_exact`、`test_task_rate_limit_returns_safe_429_and_retry_after`（HTTP 层断言 429/-header/detail） |
| 来源 IP 可信链 | 通过 | `rate_limit.py:147-172` 仅在 `TRUSTED_PROXY_IPS` 显式配置时采用转发头，否则用对端地址 | `test_forwarding_headers_are_ignored_at_http_boundary`、`test_multi_proxy_chain_skips_only_explicitly_trusted_nodes`、`test_forwarded_ip_is_used_only_through_explicitly_trusted_proxy_layers` |
| idempotency-key | 通过 | `rate_limit.py:119-127` 归一化（空/超长拒绝）；`rate_limit.py:240-251` 以 `session\x00id` 或 `ip\x00ip` 为作用域做 SHA-256，天然跨会话隔离；`main.py:162-217` 数据库唯一约束 `uq_tasks_session_idempotency_key`（`models.py:38-44`）兜底 | `test_idempotent_network_retry_does_not_charge_session_or_ip_twice`、`test_idempotency_replay_survives_window_boundary_without_new_charge`、`test_same_client_key_cannot_replay_another_sessions_quota`、`test_concurrent_api_retries_create_one_task_and_consume_quota_once`（8 并发只建 1 个任务、配额只扣一次）、`test_retry_after_restart_returns_database_task_without_quota_consumption` |
| 重试与恢复 | 通过 | `recovery.py:258-270` 仅重试瞬态错误+指数退避；`recovery.py:283-340` 有检查点则结算、无则转人工复核不重复执行付费调用；`recovery.py:343-396` 限 3 次、按 `retry_after` | `test_retry_call_retries_only_transient_errors_with_bounded_backoff`、`test_stale_checkpoint_is_settled_without_repeating_search`、`test_stale_started_without_checkpoint_requires_manual_review_instead_of_repeating_search`、`test_due_rate_limit_retry_is_requeued_once_with_delay_and_attempt_cap`；队列侧 `test_duplicate_completed/started_execution_does_not_call_service_twice` |
| 日志脱敏 | 通过（1 项受宿主环境影响，见 LOW-01） | `recovery.py:107-141` 综合脱敏（密钥赋值/SQL/provider body/URL 凭据/路径/环境变量）；`recovery.py:155-230` Worker 与 Uvicorn 日志过滤器；`queueing.py:27,50-57` 安装过滤器并在失败边界重写异常 | `test_sensitive_failure_is_fully_redacted_detached_and_retryable`（断言 token/password/secret/SQL/provider body/凭据 URL/Unix+Windows 路径/环境变量值均不出现在公开异常、事件与 traceback；同时保留 `Traceback`/`RuntimeError` 与安全标记）；`test_uvicorn_access_and_exception_logs_redact_artifact_requests`（清理干扰环境变量后通过）；`test_worker_e2e.py::test_sensitive_failure_real_rq_logs_events_and_response_are_redacted` 通过真实 RQ 验证 |
| Redis 不可用 | 通过（fail-closed） | `rate_limit.py:253-260,297-310`、`queueing.py:448-469` | `test_redis_unavailable_fails_closed_with_safe_retry_information`、`test_missing_redis_configuration_is_also_safe_unavailable`、`test_redis_unavailable_during_enqueue_never_leaves_false_queued_state` |

### 3.5 生产配置守卫：DATABASE_URL 前缀、密钥长度、seed 开关 — 通过

| 检查点 | 结论 | 代码依据 | 验证方法/证据 |
|---|---|---|---|
| 生产判定 | 通过 | `config.py:31-34`：`APP_ENV∈{prod,production}` 或 `RENDER=true` | `test_render_marker_enforces_production_guards`；`test_deployment_config.py:58-61` 断言 render.yaml 两处均为 production |
| DATABASE_URL 前缀 | 通过 | `config.py:45-47` 仅接受 `postgresql://`、`postgres://`、`postgresql+`；`db.py:15-20` 归一化为 `postgresql+psycopg` | 手工核验：`postgres://x`、`postgresql+psycopg://x` 被接受，`sqlite:///x.db` 被拒；`test_production_rejects_sqlite_and_missing_secrets_with_safe_error` 断言报错消息只含字段名、不含 URL/口令 |
| SESSION_SECRET / ADMIN_TOKEN 长度 | 通过 | `config.py:48-51` 要求 strip 后 UTF-8 字节数 ≥ 32 | `test_production_accepts_external_postgres_and_fixed_secrets`（恰好 32 通过）、`test_production_rejects_short_secrets`（短值被拒）；开发环境为进程内随机默认（`config.py:9-10,36-41`），`test_local_development_keeps_process_local_defaults` 验证 |
| seed 开关 | 通过 | `config.py:24` `seed_base_skill=False` 默认关闭；`db.py:128-129` 仅在显式开启时播种；`seed_base_skill` 有 `count()` 保护与 `IntegrityError` 回滚（`db.py:35-58`） | `test_seed_base_skill_publishes_once`（重复调用仍只 1 条、state=published）、`test_seed_base_skill_keeps_existing_version`（不覆盖已有版本） |
| 构建/环境样例不含真实密钥 | 通过 | — | `test_deployment_config.py:64-127` 断言 `.dockerignore` 排除 `.env`/`test.db`、Dockerfile 不 COPY 本地密钥与数据库、`.env.example` 中 `QWEN_API_KEY`/`SESSION_SECRET`/`ADMIN_TOKEN`/`WORKER_SHARED_SECRET` 均为空且无 `sk-`/`test-admin-token` |

---

## 四、复核方法说明与环境备注

1. **测试命令**（使用仓库自带 `.venv`，Python 3.9）：

   ```bash
   cd <repo>
   env -u CODEBUDDY_API_KEY_HELPER_DISABLED \
     .venv/bin/python -m pytest -q --basetemp=/tmp/sec-review-pytest-<ts> \
     backend/tests/test_sessions.py backend/tests/test_public_access.py \
     backend/tests/test_skill_versions.py backend/tests/test_remote_artifacts.py \
     backend/tests/test_rate_limit.py backend/tests/test_task_idempotency.py \
     backend/tests/test_queue_failures.py backend/tests/test_recovery.py \
     backend/tests/test_production_config.py backend/tests/test_deployment_config.py \
     backend/tests/test_sites_task_store.py backend/tests/test_seed_base_skill.py \
     backend/tests/test_sites_mode_routes.py backend/tests/test_sec01_answer_integrity.py \
     backend/tests/test_health.py backend/tests/test_worker_e2e.py
   # 结果：183 passed, 5 warnings
   ```

2. 首次运行时出现 1 例失败（`test_uvicorn_access_and_exception_logs_redact_artifact_requests`），根因为宿主环境变量 `CODEBUDDY_API_KEY_HELPER_DISABLED=1` 触发过度脱敏（LOW-01），清理后通过；合并运行时出现的 `tmp_path` 沙箱 `FileExistsError` 为本机沙箱对 `/tmp/pytest-of-*` 的 mkdir 冲突，通过 `--basetemp` 指定唯一目录规避，与产品无关。

3. `test_worker_e2e.py` 运行会改写 `backend/tests/fixtures/worker/results/*.json`，已 `git restore` 恢复并用 `shasum` 复核与测试前一致。

4. 手工验证均为**本地构造对象/纯计算**：Origin 绕过仅构造 `SitesStorageClient` 判断放行与否（未发起任何网络请求、未使用真实密钥）；唯一索引与 DATABASE_URL 前缀用内存 SQLite 与本地 `get_settings()` 校验（未连接生产 DB）。复核过程中未打印任何真实密钥、令牌或连接串值。

5. 复核结束时工作区：无 `backend/`、`app/` 生产代码改动；`fixtures/worker/results` 已恢复；本报告位于 `dev/acceptance/security-review/report.md`。另有并行任务生成的 `dev/acceptance/push-routes/` 目录，非本次复核产物，未改动。

---

## 修复记录（主线，2026-11-25）

- **HIGH-01 已修复**：`SitesStorageClient` 改为解析 origin，仅对精确的 `localhost` / `127.0.0.1` / `::1` 放行明文 HTTP，其余必须 HTTPS，并拒绝内嵌凭据。修复提交 `590e0ff`；回归测试 `test_sites_storage_client_rejects_lookalike_local_http_origins` 覆盖 `http://localhost.evil.test`、`http://127.0.0.1.evil.test`、普通 HTTP 外部域与内嵌凭据，均按预期拒绝；本地回环 HTTP 仍可用。
- LOW 级两项保留待评估（日志脱敏过度替换、`_sites_raise` 依赖调用方异常安全化），不阻塞发布。
