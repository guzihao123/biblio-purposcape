# E 自定义入口与 B 项目主题候选（e-b-theme）

- 分支：`e-b-theme`（worktree：`/Users/crisprcas_9/WorkBuddy/2026-11-06-20-49-06/purpose-landscape-web-e-b-theme`）
- 基线：本地 `integration2` @ `36a7a7c`
- 范围：只改 E/B 入口及其测试；未改 C/D 业务逻辑，未部署、未 push，未改 Skill 发布规则与 `cards.yaml`。

## 1. 结论速览

| 项 | 状态 |
|---|---|
| E 用途卡自定义入口（前端 custom + 后端校验 + 检索/写作/交付 A） | 已完成 |
| E 交付 A 生成 Word（`综述初稿.docx`） | 已完成，真实 `DeliveryService` 验证通过 |
| B 项目主题候选（1–3 个 + 自定义 → 名称/目标/资助 → 术语卡） | 已完成 |
| B 候选后端生成（复用 Qwen/`CandidateService`） | 已完成，含降级为自定义的路径 |
| 新增 card/state、`cards.yaml` 版本变更 | 不需要，未改 |
| 测试 | 后端 507 passed；前端 29 passed；build 通过；浏览器验收 11 passed |
| 阻塞点 | 无代码级阻塞；真实 Qwen 与 sites/remote 线上路径未在本环境实测（未部署） |

## 2. 设计决策与影响面

### 2.1 E：复用“通用 custom 字段”，不新增卡

- `_mode_card()` 增加 `E 其他用途（自定义）` 选项，并挂载卡级 `custom`：
  - `custom.label = 自定义用途`、`required = true`；
  - `custom_for = ['E']`：只有选中 E 时才渲染该输入框，A–D 不受影响。
- 前端 `TaskWizard` 支持 `custom_for`：自定义文本作为 `mode` 答案的 `custom` 字段提交，**不替换**所选 E；direction/terms 的既有 custom 语义不变。
- 后端 `answer_validation` 的 `mode` 卡新增 `custom`、`theme` 两个字段；`mode=E` 必须带非空 `custom`（上限 2000 字）。
- `_mode()` 原本就返回大写值，E 无需改路由；真正缺失的是 `search.py` 的 `MODES` 白名单，已补 E（E 与 A 共用相关性排序）。
- 写作侧新增 `WritingTask.custom_purpose` 与 `E_CUSTOM_PURPOSE_RULE`，组件/正文两次模型调用都携带 `custom_purpose`；E 的组件 schema 改为 `markdown + evidence`，走 `_build_components` 的 markdown 分支。
- 交付侧沿用既有 `WORD_FILENAMES['E'] = 综述初稿.docx`、`WORD_RANGES['E'] = 1500-2500`，交付形式 A 生成 Word。

### 2.2 B：候选作为 mode 卡内的步骤，不新增 `b_theme/b_project`

选 B 后不再立刻显示项目字段，而是同一张 mode 卡内三步：

1. 选用途（A–E）；
2. B 专用“项目主题候选”步骤：后端生成 1–3 个候选（项目名称 + 目标 + 对象 + 方法 + 预期产出）+ 自定义输入；
3. B 专用“项目名称/目标/资助类别”步骤：用所选主题预填名称与目标，可修改；确认后一次性提交 `{mode:'B', project:{...}, theme:{...}}`，随后进入既有术语卡。

这样做的好处：

- **卡片顺序不变**：后端仍是 `direction → mode → terms → years → adjustment → delivery`，与 `cards.yaml.order` 完全一致；
- **不新增 `TaskState`/`CardId`**：`task_flow.CARD_TRANSITIONS`、sites 存储白名单、任务恢复/过期逻辑均不受影响；
- **不改发布规则**：`cards.yaml` 的 `mode.options` 本来就含 `E`，B 主题只是 mode 卡内部交互，不触发 Skill v2；审计时记录的 22 个未完成任务也不会因本次改动被触发；
- 与 C 模式“C模式任务 → 本文信息”两段式先例一致。

### 2.3 如果坚持新增 `b_theme/b_project`（未采用的最小方案与影响面）

仅作为备选记录，本次未实现：

- 新增 `TaskState.COLLECTING_THEME / COLLECTING_PROJECT`、`CardId.B_THEME / B_PROJECT`；
- `CARD_TRANSITIONS` 需为 mode→b_theme→b_project→terms 做值相关分支（现有静态表无法按 `mode=B` 分流），并同步 `JOB_KINDS`/恢复逻辑；
- `task_presenters.card_for` 增加两个 builder；B 主题候选需要持久化 `TaskEvent`，而 `sites_task_store.append_task_event` 目前只允许 `terms_candidates*`，需同步改 sites API；
- `cards.yaml.order` 必须插入两张卡并发布 Skill v2，受“无进行中任务”发布规则限制；
- 前端 `TaskCard`、TaskPage、TaskWizard 都要新增分支，回归面显著大于本方案。

影响面结论：该方案会把“入口交互”升级为“协议/版本变更”，与本次“不破坏已发布版本”的约束冲突，故未采用。

## 3. 实现明细

### 3.1 后端

- `app/search.py`：`MODES` 加 E；`SearchRequest`/`merge_records` 错误文案同步；`_selection_key` 中 E 与 A 共用相关性排序。
- `app/answer_validation.py`：mode 卡允许 `custom`、`theme`；E 必须自定义用途；theme 校验五字段 + 自定义补充，限制长度与未知键。
- `app/task_presenters.py`：mode 卡新增 E 选项、`custom`、`custom_for`；B 描述改为“先选项目主题”。
- `app/candidates.py`：新增 `generate_project_themes(direction)`，要求模型只产出 name/goal/object/method/expected_output，过滤缺失名称/目标与重复项，最多 3 个；不编造命中数。
- `app/main.py`：新增 `POST /api/tasks/{task_id}/b-theme-candidates`：
  - 需登录会话 + 任务归属校验；
  - 从本地 `TaskAnswer` 或 sites aggregate 读取 direction（无方向返回 409 `direction_required`）；
  - 走 `model` 限流（按方向摘要做 idempotency key）；
  - 模型失败/空结果返回 `{options: [], available: false, message}`，前端降级为自定义。
- `app/orchestration.py`：`_writing_task` 把 `theme` 并入 `project`，把 `custom` 传给 `custom_purpose`。
- `app/writing.py`：E 的 `COMPONENT_SCHEMAS`、`FORMAT_RULES`、`E_CUSTOM_PURPOSE_RULE`、`custom_purpose` 字段；B 组件增加“项目主题（用户选定）”段；B 生成规则要求研究内容/技术路线与 theme 对应。

### 3.2 前端与 sites 路由

- `sites/functions/index.ts`、`sites/cloud-function/index.ts`：sites 边缘路由新增 `POST /tasks/{id}/b-theme-candidates` 转发（否则部署到 sites 时该接口会被边缘 404）。
- `components/TaskWizard.tsx`：
  - `TaskCard` 新增 `custom_for`、`CustomTaskField.required`；
  - `ProjectThemeOption/ProjectThemeDetails` 类型；
  - B 三步状态机 `mode → theme → project`；主题候选加载中/失败/空态均有提示，可直接自定义；
  - E 的 custom 仅在选中 E 时显示，必填时禁用确认；
  - 新增 `loadProjectThemes` prop，与具体 API 解耦。
- `api.ts`：`getProjectThemeCandidates(taskId)`。
- `pages/TaskPage.tsx`：`useCallback` 稳定 loader，传入 TaskWizard。
- `components/OptionCard.tsx` + `styles/full-power.css`：多行中文 preview 使用可读样式（B 主题的对象/方法/产出）。
- E2E：新增 04B E 用例；04 改为主题候选 → 项目字段流程；同步修正既有过期断言（交付形式字母、年限“推荐”、方向示例、报告夹具文件名）。

## 4. 测试结果

### 4.1 后端

```bash
/Users/crisprcas_9/WorkBuddy/2026-11-06-20-49-06/purpose-landscape-web/.venv/bin/python \
  -m pytest backend/tests -q --basetemp=/tmp/ebtheme-final2
# 507 passed, 5 failed, 5 skipped
```

5 个失败均为本机 WorkBuddy 沙箱日志脱敏导致（RQ worker 日志中的 job id 被替换为 `[REDACTED_ENV]`，断言无法匹配），与本次改动无关；基线 `integration2` 同样是这组环境性失败（初次基线为 5 failed / 491 passed）。失败项：

- `test_recovery.py::test_uvicorn_access_and_exception_logs_redact_artifact_requests`
- `test_worker_e2e.py` 的 4 个 RQ worker 用例（c-pair word/ppt、a-dialogue、graph/sensitive 之一，随脱敏命中位置浮动）

本次新增/覆盖：

- `test_answer_validation.py`：E 必填/长度、theme 合法/非法、未知字段；
- `test_candidates.py`：主题候选去重、上限 3、空结果；
- `test_task_api.py`：B 候选接口（无方向 409、有方向返回）、E 无 custom 422 / 有 custom 进入 terms；
- `test_writing.py`：E 的 markdown 组件/正文文件、custom_purpose 进入两次模型 payload；B theme 渲染；
- `test_delivery.py`：E + 交付 A 真实生成 `综述初稿.docx` 并通过预置复核；
- `test_orchestration.py`：E 从 search 到 generate 的 custom_purpose/交付形式传递；B theme/custom 进入 WritingTask；
- `test_search.py`：E 模式 SearchRequest/merge_records。

### 4.2 前端

```bash
cd frontend && npx vitest run     # 29 passed
cd frontend && npm run build      # tsc --noEmit + vite build 通过
```

sites 边缘路由测试：

```bash
node --test sites/functions/routes.test.mjs      # 12 passed
node --test sites/functions/task_store.test.mjs  # 34 passed
```

浏览器验收（真实 FastAPI + 离线夹具）：

```bash
cd frontend && npx playwright test --config=playwright.config.ts
# 11 passed
```

覆盖 01 Skill 管理、02 A 全流程、03 图谱、04 B 主题候选、04B E 自定义、05 C 两卡、06 D、07 窄屏、08 reduced-motion/键盘、09 tabs、10 回执。

fixtures 已恢复：`git restore backend/tests/fixtures/worker/results`；提交前工作区不含测试产物、`.venv` 或 `node_modules` 软链。

## 5. 未完成 / 阻塞 / 风险

- **真实 Qwen 未调用**：本环境无 `QWEN_API_KEY`，主题候选与 E 正文均用夹具模型/离线模型验证；上线前需用真实方向跑一次 B 主题候选与 E 全链，核对候选质量与 E 的口吻。
- **sites/remote 路径未实测**：B 候选接口的远端方向读取走 `get_task_aggregate`，本地已做分支；未部署，未验证真实 sites 响应结构。
- **候选无持久化/缓存**：B 主题候选按请求生成，前端仅在当前卡片会话内缓存；刷新或重进会再次消耗一次 model 配额。若需跨刷新缓存，需新增 `TaskEvent` 并在 sites 事件白名单放行，属于后续版本变更。
- **E 的兼容性**：后端现在要求 `mode=E` 必须带 `custom`；旧客户端若直接提交 E 会得到 422（当前线上没有 E 入口，实际影响为零）。
- **B 主题质量依赖模型**：后端只做结构校验与去重，不判断主题科学性；无候选时用户可自定义，不会阻塞流程。
- **未改 C/D**：C1/C2、D 的写作/交付/验收逻辑未触碰；C/D 回归见 4.2 浏览器验收的 05/06 用例。

## 6. 改动文件

后端：

- `backend/app/search.py`
- `backend/app/answer_validation.py`
- `backend/app/task_presenters.py`
- `backend/app/candidates.py`
- `backend/app/main.py`
- `backend/app/orchestration.py`
- `backend/app/writing.py`
- `backend/tests/test_answer_validation.py`（新增）
- `backend/tests/test_candidates.py`
- `backend/tests/test_delivery.py`
- `backend/tests/test_orchestration.py`
- `backend/tests/test_search.py`
- `backend/tests/test_task_api.py`
- `backend/tests/test_task_presenters.py`
- `backend/tests/test_writing.py`

部署路由：

- `sites/functions/index.ts`
- `sites/cloud-function/index.ts`
- `sites/functions/routes.test.mjs`

前端：

- `frontend/src/components/TaskWizard.tsx`
- `frontend/src/components/OptionCard.tsx`
- `frontend/src/styles/full-power.css`
- `frontend/src/api.ts`
- `frontend/src/pages/TaskPage.tsx`
- `frontend/e2e/acceptance-helpers.ts`
- `frontend/e2e/acceptance_server.py`
- `frontend/e2e/task-browser-acceptance.spec.ts`
- `frontend/tests/AcceptanceIsolation.test.ts`
- `frontend/tests/FullFlow.test.tsx`
- `frontend/tests/TaskWizard.test.tsx`

未改：`cards.yaml`、`modes.yaml`、`skill_runtime/references/modes.md`、C/D 业务代码、Skill 发布规则、`render.yaml`/Docker 部署配置。sites 只补了边缘转发路由，未改任务存储协议。
