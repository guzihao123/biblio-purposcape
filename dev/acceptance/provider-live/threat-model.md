# 威胁模型：主存储所有者隔离（离线草案，2026-11-24）

## 资产
- 匿名会话的身份与元数据（`sites_anonymous_sessions`）
- 任务记录与状态/revision（`sites_tasks`）
- 制品元数据（`sites_task_artifacts`；字节对象另属 Storage 方案）
- 配额窗口（`sites_task_quota_windows`）
- Skill 版本内容（`sites_skill_versions`）

## 信任边界与角色
1. **浏览器匿名用户**：持有 session_id（视为其身份凭证），只能读写自己的任务/制品。
2. **固定 worker（Python 后端，经共享秘密鉴权）**：代表具体会话执行固定操作集合；不得越权访问其他所有者数据。
3. **应用数据库角色（app_user）**：Fixed Function 连接数据库使用的角色；当前**无任何 RLS**，隔离完全依赖 `task_store.ts` 固定 SQL 的 `session_id = $n` 条件。
4. **迁移/管理角色**：执行 Schema 变更、Skill 发布；必须与应用角色分离。
5. **只读审计角色**：验收快照用途（PRE-04）。

## 威胁
| 编号 | 威胁 | 当前缓解 | 残余风险 |
| --- | --- | --- | --- |
| T1 | 跨所有者读取任务/制品（横向越权） | 固定 SQL 条件过滤（offline OFF-ID-02 已验证 404） | 任何绕过固定面的新查询路径（新 Function、迁移脚本、后台工具）无数据库层拦截 → 需 RLS 纵深 |
| T2 | 跨所有者写入状态/制品 | 同上 + revision CAS | 同上 |
| T3 | 配额窗口被跨会话篡改/窥探 | 固定 SQL 的 PK (session_id, window_start) + 条件 | 无 RLS 时旁路 UPDATE 可行 |
| T4 | 匿名用户调用 worker 能力 | worker token 鉴权（offline OFF-ID-03 已验证 403） | 与数据库层无关 |
| T5 | draft/archived Skill 被用于建单 | `get_published_skill` 检查 + 部分唯一索引 | 良好 |
| T6 | 应用凭据泄露后全表拖库 | 无（单角色 + 无 RLS = 一次泄露全部暴露） | RLS 将泄露 blast radius 限制到单会话行 |
| T7 | Provider 错误正文/连接串入日志 | 客户端/同步层安全异常（OFF-SEC-01） | 良好 |

## 结论
- 当前隔离是**单层**（固定 SQL 条件过滤）。T1–T3、T6 要求数据库层 RLS 或平台等效能力作为第二层；未落地前不得声称"RLS 已覆盖"。
- 草案见 `rls-policy-draft.sql`；执行前需平台确认角色划分与 FORCE RLS 行为（见草案未决问题 a–e）。
- 若平台提供等效隔离（如函数级权限、视图隔离、独立 per-session 连接角色），需真实证据并在验收报告中单独记录，不得以条件过滤冒充。
