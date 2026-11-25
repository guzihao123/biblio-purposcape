-- Qoder Sites task store: RLS policy DRAFT for Provider migration review.
-- 性质：离线草案，未经平台角色/所有权/FORCE RLS 行为确认，不得执行。
-- 目标：在固定 SQL 条件过滤之外提供数据库层隔离纵深；本草案假定存在
-- 两个数据库角色：app_user（Fixed Function 连接角色，按请求头中的
-- session_id 设定 LOCAL 变量）与迁移/管理角色（BYPASSRLS 或 OWNER）。
-- 前提未确认前，本文件不构成迁移授权。

BEGIN;

-- 1) 会话表：角色只能看到/操作其自身会话行。
ALTER TABLE sites_anonymous_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE sites_anonymous_sessions FORCE ROW LEVEL SECURITY;
CREATE POLICY sites_sessions_owner ON sites_anonymous_sessions
    USING (id = current_setting('app.session_id', true))
    WITH CHECK (id = current_setting('app.session_id', true));

-- 2) 任务表：行级可见性与写入都限定为所有者会话；worker 固定 SQL
--    已带 session_id 条件，策略与之同向，防任何旁路查询。
ALTER TABLE sites_tasks ENABLE ROW LEVEL SECURITY;
ALTER TABLE sites_tasks FORCE ROW LEVEL SECURITY;
CREATE POLICY sites_tasks_owner_select ON sites_tasks
    FOR SELECT USING (session_id = current_setting('app.session_id', true));
CREATE POLICY sites_tasks_owner_insert ON sites_tasks
    FOR INSERT WITH CHECK (session_id = current_setting('app.session_id', true));
CREATE POLICY sites_tasks_owner_update ON sites_tasks
    FOR UPDATE USING (session_id = current_setting('app.session_id', true))
    WITH CHECK (session_id = current_setting('app.session_id', true));

-- 3) 制品元数据：经由任务的所有者间接限定。
ALTER TABLE sites_task_artifacts ENABLE ROW LEVEL SECURITY;
ALTER TABLE sites_task_artifacts FORCE ROW LEVEL SECURITY;
CREATE POLICY sites_artifacts_owner_select ON sites_task_artifacts
    FOR SELECT USING (EXISTS (
        SELECT 1 FROM sites_tasks
        WHERE sites_tasks.id = task_id
          AND sites_tasks.session_id = current_setting('app.session_id', true)));
CREATE POLICY sites_artifacts_owner_modify ON sites_task_artifacts
    FOR ALL USING (EXISTS (
        SELECT 1 FROM sites_tasks
        WHERE sites_tasks.id = task_id
          AND sites_tasks.session_id = current_setting('app.session_id', true)))
    WITH CHECK (EXISTS (
        SELECT 1 FROM sites_tasks
        WHERE sites_tasks.id = task_id
          AND sites_tasks.session_id = current_setting('app.session_id', true)));

-- 4) 配额窗口：仅所有者会话可见/可扣。
ALTER TABLE sites_task_quota_windows ENABLE ROW LEVEL SECURITY;
ALTER TABLE sites_task_quota_windows FORCE ROW LEVEL SECURITY;
CREATE POLICY sites_quota_owner ON sites_task_quota_windows
    USING (session_id = current_setting('app.session_id', true))
    WITH CHECK (session_id = current_setting('app.session_id', true));

-- 5) Skill 版本：对外角色只读 published；写入仅迁移/管理角色（owner
--    或 BYPASSRLS），不在应用角色策略内放行。
ALTER TABLE sites_skill_versions ENABLE ROW LEVEL SECURITY;
ALTER TABLE sites_skill_versions FORCE ROW LEVEL SECURITY;
CREATE POLICY sites_skill_read_published ON sites_skill_versions
    FOR SELECT USING (state = 'published');

COMMIT;

-- 未决问题（执行前必须由平台/主线书面确认）：
--  a) Provider 是否允许 FORCE ROW LEVEL SECURITY（含表 owner）？
--  b) 数据库角色划分：app_user、迁移角色、只读审计角色分别是什么？
--  c) app.session_id 的注入方式（固定 Function 每个请求 SET LOCAL）？
--  d) worker 内部跨会话管理操作（如运营审计）走哪个角色？
--  e) 与既有 ON CONFLICT/条件更新并发语义的相互作用测试计划？
