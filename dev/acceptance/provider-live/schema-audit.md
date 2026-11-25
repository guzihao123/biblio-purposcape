# sites/schema.sql 离线审核证据（2026-11-24，未执行）

审核对象：`sites/schema.sql`（sha256:b7ad68cf…4b9fe）。本文件仅作审核记录，未在任何数据库上执行该 Schema。

## 1. 结构事实（与 task_store.ts 固定 SQL 逐条核对）

| 固定操作 | 依赖的 Schema 对象 | 审核结果 |
| --- | --- | --- |
| create_session / get_session | `sites_anonymous_sessions(id PK)` | 一致 |
| upsert_skill_version | `sites_skill_versions(id PK, version UNIQUE>0, state CHECK, content JSONB, content_hash)` + 部分唯一索引 `sites_one_published_skill`（仅一行 published） | 一致 |
| get_published_skill | 同上 state='published' | 一致 |
| find_task_by_key / insert_task(ON CONFLICT) | `sites_tasks` 的 `UNIQUE (session_id, idempotency_key)`（具名约束 uq_sites_tasks_session_idempotency_key） | 一致；唯一约束真实存在于 Schema |
| consume_quota | `sites_task_quota_windows PK (session_id, window_start)`，`used >= 0 CHECK` | 一致；同库配额使 insert+charge 单事务在 Schema 层面可行 |
| get_owned_task / list_owned_tasks / update_owned_task_state | `sites_tasks` + owner 索引 `(session_id, created_at DESC, id DESC)` | 一致 |
| upsert_owned_artifact / list_owned_artifacts | `sites_task_artifacts PK (task_id, name)`、`UNIQUE (task_id, object_path)`、`CHECK size_bytes >= 0` | 一致 |

## 2. RLS 审核结论

对 `sites/schema.sql`、`sites/`、`backend/app/sites_task_store.py`、`backend/app/task_store_sync.py` 全量检索
`ROW LEVEL SECURITY` / `rls` / `policy`：**零命中**。

- Schema 中没有 `ALTER TABLE … ENABLE/FORCE ROW LEVEL SECURITY`，没有任何 `CREATE POLICY`。
- 所有者隔离完全由 `task_store.ts` 的固定 SQL 中的 `session_id = $n` 条件实现，即 **API/适配器层条件过滤**，没有数据库层纵深防御。
- 因此验收口径“RLS 对应用角色确实生效，而不是只靠 API 条件过滤”**当前不被该 Schema 支持**；除非 Provider 平台在 Schema 之外另行下发 RLS（需平台书面说明），否则 LIVE 隔离场景只能降级为“固定 SQL 条件过滤级隔离”。

## 3. 事务能力审核结论（仅 Schema/代码层面）

- 建单事务在 `task_store.ts` 中只包含两个写入：`insert_task` 与 `consume_quota`（无第三个关联写入）。`consume_quota` 失败时抛错回滚两者——**LIVE-TX-02 的“关联写入”路径如实记录为：无该写入路径**。
- Schema 的 `ON CONFLICT (session_id, idempotency_key) DO NOTHING` + 失败后 `find_task_by_key` 读取胜者的设计，与并发唯一竞争语义自洽；但真实 PostgreSQL 的锁等待/死锁/隔离级别行为未经真实实例验证（见 result.json 未验证项）。
- `revision BIGINT CHECK (>0)` 与条件更新 `WHERE … AND revision = $5` 配合 `revision + 1`，CAS 语义在 Schema 层面成立；真实并发行为未验证。

## 4. 未执行声明

本次审核未创建任何云数据库、未执行任何迁移、未连接任何真实 Provider/PostgreSQL；`schema.sql` 文件头亦声明“DO NOT execute this file as a cloud migration”。
