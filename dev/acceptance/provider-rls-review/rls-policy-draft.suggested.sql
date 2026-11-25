-- ============================================================================
-- PostgreSQL RLS 草案 · 独立复核建议补丁（suggested patch）
-- 复核日期：2026-11-24　复核人：独立安全复核（离线）
-- 性质：未执行／未验证。未经真实 Provider 授权，不得在生产或任何共享
--       环境执行。本文件不构成迁移授权。
-- 依据：对 rls-policy-draft.sql / threat-model.md / sites/schema.sql /
--       sites/functions/task_store.ts 的离线比对，及 PostgreSQL 官方文档
--       ddl-rowsecurity（current 版）。
-- 变更摘要（相对原草案）：
--   P0  新增 sites_task_answers 的 ENABLE + FORCE RLS 与所有者策略
--       （原草案整体遗漏该表；固定 SQL listTaskAnswers/insertTaskAnswer
--        本身不带 session_id 条件，是 T1 威胁下最薄弱的旁路面）。
--   P1  会话表拆分 INSERT 策略，修复"新建会话"与 WITH CHECK 的冲突
--       （原策略要求 id = current_setting('app.session_id')，而
--        createAnonymousSession 插入的恰是一个尚未成为当前上下文的新 id）。
--       首选方案：建单事务内先 set_config('app.session_id', 新 id, true)
--       再 INSERT；备选方案即本补丁中的 NULL 门 INSERT 策略。
--   P2  Skill 版本写入走第二 GUC 门（app.skill_admin）或独立角色
--       （app_admin），解决 worker 发布路径与单一 app_user 角色的冲突。
--   P3  文档化：撤销/过期会话在数据库层的策略选择（见文件末尾未决项）。
--   P4  文档化：FK/唯一约束检查绕过 RLS 的官方行为与"隐蔽信道"提示；
--       只读审计角色需 BYPASSRLS 或等效安排。
-- ============================================================================

BEGIN;

-- ── 0) sites_task_answers（新增；原草案遗漏，严重度 HIGH）──────────────
ALTER TABLE sites_task_answers ENABLE ROW LEVEL SECURITY;
ALTER TABLE sites_task_answers FORCE ROW LEVEL SECURITY;

CREATE POLICY sites_answers_owner_select ON sites_task_answers
    FOR SELECT USING (EXISTS (
        SELECT 1 FROM sites_tasks
        WHERE sites_tasks.id = task_id
          AND sites_tasks.session_id = current_setting('app.session_id', true)));

CREATE POLICY sites_answers_owner_modify ON sites_task_answers
    FOR ALL USING (EXISTS (
        SELECT 1 FROM sites_tasks
        WHERE sites_tasks.id = task_id
          AND sites_tasks.session_id = current_setting('app.session_id', true)))
    WITH CHECK (EXISTS (
        SELECT 1 FROM sites_tasks
        WHERE sites_tasks.id = task_id
          AND sites_tasks.session_id = current_setting('app.session_id', true)));

-- ── 1) 会话表：INSERT 策略与存量策略并存（P1 备选方案）─────────────────
-- 若采用首选方案（建单事务先 set_config 再 INSERT），本段可省略，
-- 但必须在 worker 代码中以注释+测试固定该次序。
CREATE POLICY sites_sessions_insert_new ON sites_anonymous_sessions
    FOR INSERT WITH CHECK (
        current_setting('app.session_id', true) IS NULL
        OR id = current_setting('app.session_id', true));
-- 说明：NULL 门意味着"请求上下文未绑定会话时允许创建任意新会话"。
-- 由于 app_user 仅被固定 Function 使用、且创建会话的 Function 不读取
-- 请求头 session_id，该放行面与既有固定面等价；但必须书面确认无其他
-- 以 app_user 连接的代码路径。

-- ── 2) Skill 版本：写入经第二 GUC 门（P2 方案 A）─────────────────────
-- 仅 skill 发布 Function 在同一事务内执行
--   SELECT set_config('app.skill_admin', 'on', true);
-- 匿名会话作用域的 Function 严禁设置该变量。
CREATE POLICY sites_skill_admin_write ON sites_skill_versions
    FOR ALL
    USING (current_setting('app.skill_admin', true) = 'on')
    WITH CHECK (current_setting('app.skill_admin', true) = 'on');
-- 方案 B（更稳妥，取决于平台能否建角色）：独立角色 app_admin（属表 owner
-- 组或持 BYPASSRLS）执行 upsertSkill；worker 匿名会话路径仍用 app_user。
-- 两案互斥，须平台书面选择；无论哪案，sites_skill_read_published 保持
-- 不变（published 只读面与 draft/publish/rollback 写面已分离）。

COMMIT;

-- ============================================================================
-- 必须在真实 Provider 授权后书面确认的未决项（复核新增）：
--  f) set_config/set LOCAL 是否被平台连接代理放行；连接池模式
--     （transaction pooling 下 SET LOCAL 随事务结束复位，安全；
--      session pooling 下若误用持久 SET 会造成跨请求会话串号）。
--  g) 撤销/过期的数据库层策略：是否在任务/制品/配额/答案策略的 USING 中
--     追加会话未撤销且未过期条件。追加会让"已过期会话的历史任务"同时
--     不可读（产品决策）；不追加则数据库层对被盗 session_id 不设防，
--     仅靠应用层 getSessionRecord（注意 createTask 当前用的是不带
--     撤销/过期检查的 getSession，见 result.json ISSUE-05）。
--  h) 只读审计角色（PRE-04）：FORCE RLS 同样作用于该角色，快照需
--     BYPASSRLS 或等效授权，须在平台侧登记。
--  i) 制品/答案策略中的 EXISTS 子查询在 READ COMMITTED 下的官方竞态
--     提示：被引用行的安全相关列（session_id）在本设计中不可变
--     （WITH CHECK 禁止改写、固定面无 UPDATE session_id 语句），残余
--     窗口可接受，但须载入测试计划。
-- ============================================================================
