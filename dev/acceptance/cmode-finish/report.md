# C 模式收尾验收报告

- 分支：`cmode-finish`
- Worktree：`/Users/crisprcas_9/WorkBuddy/2026-11-06-20-49-06/purpose-landscape-web-cmode-finish`
- 分支基点：本地 `integration2`（`bda382f`）；测试口径已对齐到最新 `integration2`（`36a7a7c`）
- 首轮代码提交：`744c021`；本轮文案与 KNOWN 校准：`38ab605`
- 范围：仅 C 模式收尾；未改 B/D 模式、未部署、未 push。

## 0. 四点确认

### 0.1 固定卡文案与材料门禁

- 标签、顺序与**说明**逐字对齐 `skill_runtime/references/modes.md` 的「固定卡 2 · 本文信息」：
  - `跳过，按通用口径写框架` — `不提供本文细节，只给框架与占位提示，并在交付中注明。`
  - `已有论文初稿，提供文件` — `用户提供论文文件或粘贴内容后，先提取研究目标、方法、数据与创新，再决定补检索。`
  - `现场口述研究问题与方法` — `用户直接说明研究问题、方法与创新，据此填写本文研究思路与贡献相关内容。`
- 首轮实现只对齐了标签，说明是改写版；本轮已改为逐字文案。后端 `task_presenters.py` 下发说明，前端 `TaskWizard.tsx` 以同文案常量兜底，前后端各有逐字断言。
- `upload`/`oral` 未填 `c_material` 时禁止确认：前端按钮禁用（`cInfoSelected`），后端返回 422（`c_material is required for upload or oral`）。
- `target_journal` 只作为该卡内的可选输入，不单独追问：全仓仅 `conditional_fields.C` 一处字段定义，测试断言其他模式字段中没有同名项。

### 0.2 路由、C2 边界与 skip 规则

- `_mode()` 直接读取 `c_route`；仅 `C1+C2` 进入 `_generate_c_pair`，单 C1/C2 只调用一次 `writing.produce` 并以该 mode 交付。回归测试断言单路由只生成所选模式，不产生未选子模块。
- C2 不写成讨论、不索要本文结果：`COMPONENT_SCHEMAS['C2']` 无本文结果/贡献字段；`C2_SKIP_RULE` 明写「C2 不要求本文结果」「不得写成 Discussion」；`C2_文献综述骨架.md` 同口径；C2 提纲标题无「讨论」节。新增测试锁定这四点。
- `skip`：`C1_SKIP_RULE` 要求研究空白根据池内文献逐行实写并附 `[n]`，只有「研究思路与方法」「研究贡献」两张段落卡和完整引言第 4/5 段允许占位；构件仍输出 Research Gap 分析表（测试断言「联合校准不足」等实写内容存在）。

### 0.3 写法参考卡降级

- `style_reference_card()` 有两条降级路径：同期刊范文少于 2 篇 → 写「降级原因」；命中不少于 2 篇但池内只有摘要、无 OA 全文 → 写「字段降级说明」，明确段数与职能、顺序过渡、引用密度三项无法判定。
- 两条路径都写明「按通用引言口径写」「不抄写任何单篇范文措辞」；无 OA 全文或仅摘要时必然降级，已写入第 3 节剩余风险第 2 条。

### 0.4 KNOWN 用例与基线口径

以下 6 项后端 `KNOWN` 用例与 1 项前端 `KNOWN` 用例不阻塞本分支验收；本地全量本轮实测为 5 项后端失败（第 6 项偶发通过）：

| # | 用例 | 本地现象 | 判定 |
|---|---|---|---|
| 1 | `backend/tests/test_recovery.py::test_uvicorn_access_and_exception_logs_redact_artifact_requests` | 失败；基线同样失败 | KNOWN-ENV：日志脱敏把路径/数字替换为 `[REDACTED_PATH]`/`[REDACTED_ENV]`，原字符串断言不匹配 |
| 2 | `backend/tests/test_worker_e2e.py::test_c_pair_real_rq_worker_word_ppt_and_evidence[c-pair-word-A]` | 失败；基线同样失败 | KNOWN-ENV：同上 |
| 3 | `backend/tests/test_worker_e2e.py::test_c_pair_real_rq_worker_word_ppt_and_evidence[c-pair-ppt-C]` | 失败；基线同样失败 | KNOWN-ENV：同上 |
| 4 | `backend/tests/test_worker_e2e.py::test_a_dialogue_real_rq_worker_has_seven_categories_and_two_slots` | 失败；基线同样失败 | KNOWN-ENV：同上 |
| 5 | `backend/tests/test_worker_e2e.py::test_graph_renderer_failure_is_real_rq_and_task_error` | 全量失败、单跑通过 | KNOWN-ENV：顺序相关，基线同样 |
| 6 | `backend/tests/test_worker_e2e.py::test_sensitive_failure_real_rq_logs_events_and_response_are_redacted` | 全量本轮偶发通过；基线全量失败 | KNOWN-ENV：脱敏断言偶发 |
| 7 | `frontend/tests/FullFlow.test.tsx > complete web flow > shows dashboard, honors original-plan continuation and opens the report with downloads` | 失败；基线同样失败 | KNOWN-BASELINE：报告页 `download-list` 为空，找不到「下载 Word 报告」链接 |

口径对齐：

- 基线 `integration2`（`36a7a7c`）本地全量：`501 = 490 passed + 6 failed + 5 skipped`。你侧 `496 passed / 5 skipped` 正好也是 501 条，即上述 6 项在你的环境全部通过，两边的 collected 总数一致。
- 本分支 `cmode-finish` 本地全量：`512 = 502 passed + 5 failed + 5 skipped`（本轮 6 项 KNOWN 中第 6 项偶发通过）。换算到你的环境为 `507 passed / 5 skipped`。
- 差值 `512 − 501 = +11`，全部是新增用例，无删除、无新增 skip：`test_cmode_finish.py` 8 项、`test_orchestration.py` 1 项、`test_task_flow.py` 1 项、`test_task_presenters.py` 1 项。

## 1. 改动摘要

### 1.1 C info 步改为三选一固定卡

- `backend/app/task_presenters.py`：`conditional_fields.C` 新增 `c_info_route` 单选固定卡，选项标签、顺序与说明逐字对齐 Skill：
  `skip`（跳过，按通用口径写框架）、`upload`（已有论文初稿，提供文件）、`oral`（现场口述研究问题与方法）；
  三项说明分别使用 Skill 原文，不再使用改写文案；新增 `c_material` textarea；`target_journal` 作为同一张卡的可选输入保留。
- `frontend/src/components/TaskWizard.tsx`：
  - C 模式第三阶段由自由文本改为三张固定卡，复用 `OptionCard`；
  - `upload`/`oral` 时显示材料 textarea，`oral` 时标签切换为「现场口述：研究问题与方法」；
  - `skip` 时隐藏材料输入、提交 `c_material: ''`；
  - 未选路线、或 `upload`/`oral` 未填材料时禁用确认；
  - payload 增加 `c_info_route`、`c_material`，与 `c_route`、`target_journal` 一起提交。
- 台账：
  - `backend/app/task_flow.py` 在首次提交 C 模式答案时写 `user_requirements_recorded` 事件，包含 `c_route`、`c_info_route`、`c_material`、`target_journal`；
  - `backend/app/orchestration.py` 在生成阶段落盘 `用户要求台账.md`（中文选项 + 原始材料），单 C 与 C1+C2 都会生成；C1+C2 合并时 checkpoint 记录 `requirements_ledger`。

### 1.2 后端接收与校验

- `backend/app/answer_validation.py`：
  - `mode` 答案允许 `c_info_route`、`c_material`；
  - `c_info_route` 仅允许 `skip/upload/oral`，且仅 C 模式可用；
  - `upload/oral` 必须带非空 `c_material`；
  - `c_material` 上限 16,000 字符。
- `backend/app/orchestration.py`：`_writing_task` 将 `c_material` 映射为写作任务材料，`skip` 显式清空；兼容旧 `user_results` 答案（无 `c_info_route` 时按是否有材料推断 `upload/skip`）。
- 仅生成实际选择的 C1/C2：沿用 `_mode()` 的 `c_route` 分支；C1+C2 才走 `_generate_c_pair`，单 C1/C2 走单模式生成。新增回归测试断言只产生所选模式并只交付该模式。

### 1.3 writing 三路径与 target_journal

- `backend/app/writing.py`：
  - 新增 `extract_user_material()`，从 `题目/研究问题/摘要/方法/结果/创新` 分段材料中提取 `研究问题/本文方法/预期创新`；未分段文本也会作为摘要兜底，不会丢材料。
  - C1/C2 组件与正文 payload 增加 `c_info_route`、`user_material`、`c_writing_rules`、`target_journal`、`style_reference_note`。
  - `skip`：提示只允许「研究思路与方法」「研究贡献」两张段落卡和完整引言第 4/5 段留占位；研究空白、文献比较、未来方向必须按池内文献实写并带 `[n]`。
  - `upload/oral`：提示把材料用于 C1 的 gap 回应与第 4/5 段；材料不作为外部文献证据、不产生 `[n]`；C2 只在未来方向呼应，不能进入比较表/空白表的证据列。
  - `target_journal`：C1 生成 `写法参考卡.md`；池内同期刊范文少于 2 篇时写「降级原因」，不少于 2 篇但只有摘要、无 OA 全文时写「字段降级说明」；两种情况都要求按通用口径写、不得抄范文。C1+C2 时根目录额外保留 `C1_写法参考卡.md`。
- 正文与组件共用同一 `style_reference_note` 与 `c_writing_rules`，避免构件与正文口径分叉。

### 1.4 C2 构件扩展

- `COMPONENT_SCHEMAS['C2']` 新增：
  - `scope`（研究主题与检索范围）
  - `keywords`（关键词体系）
  - `search_strategy`（实际数据库/检索式/追溯/筛选/系统综述与 PRISMA 声明）
  - `synthesis`（不同研究方向的综合分析）
  - `route_comparison`（主要技术路线比较）
  - `future_directions`（未来研究方向）
- `_render_c2()` 按「研究主题与检索范围 → 关键词和检索策略 → 文献分类框架 → 综合分析 → 技术路线比较 → 文献比较表 → 研究空白分析表 → 未来研究方向」渲染；缺新字段的旧夹具会从 `search_overview`、`comparison`、`gaps` 生成只含已核信息的兜底段落，不新增无证据 `[n]`。
- `_validate_component_shape()` 增加 C2 检查：`comparison`/`gaps` 必填；新字段若提供必须是列表，`synthesis/route_comparison/future_directions` 至少 2 项。

## 2. 测试结果

### 2.1 后端

工作目录：worktree 根目录；解释器：共享 venv `../purpose-landscape-web/.venv/bin/python`。

```text
pytest -q backend/tests --basetemp=.pytest-tmp-final-branch
# 512 = 502 passed + 5 failed + 5 skipped
```

本次不再用 `--deselect` 隐藏环境失败，原始结果直接保留；本轮 5 项失败与基线 6 项失败均落在第 0.4 节的 6 项 `KNOWN-ENV` 集合内，1 项前端失败标记为 `KNOWN-BASELINE`。为对齐口径，同一解释器在未改动的 `integration2`（`36a7a7c`）跑了全量：

```text
pytest -q backend/tests --basetemp=.pytest-tmp-final-base
# 501 = 490 passed + 6 failed + 5 skipped
```

两轮失败均落在同一个 6 项 `KNOWN` 集合内，均为日志脱敏/真实 RQ 断言；基线同样复现。换算你的环境，本分支为 `507 passed / 5 skipped`，较基线 496 增加 11 项新增测试。

新增/更新测试覆盖：

- `backend/tests/test_cmode_finish.py`：三路线校验与 payload、材料提取、skip 规则、upload 材料、target_journal 降级卡、C2 新旧构件章节、C2 非 Discussion 且不索要本文结果。
- `backend/tests/test_task_presenters.py`：C 卡三选项及其逐字说明、材料 textarea、目标期刊唯一入口。
- `backend/tests/test_task_flow.py`：C 答案台账事件。
- `backend/tests/test_orchestration.py`：单 C 只生成所选模式；C1+C2 复制 `C1_写法参考卡.md`。

### 2.2 前端

```text
npx tsc --noEmit
# 通过

npx vitest run tests/TaskWizard.test.tsx
# 8 passed（含三选项逐字说明、upload/oral 未填材料禁用确认）

npx playwright test --config=playwright.config.ts --grep "05 C" --reporter=line
# 1 passed (5.8s)
```

说明：e2e 05 原来第一步依赖验收服务预置的「肝癌免疫治疗耐药机制的最新进展」方向按钮，但该按钮在当前基线的验收夹具中不存在（未改动 `integration2` 同样失败）。本次将 05 改为在方向卡直接输入同一方向文本，使 C 模式用例不再依赖该预置按钮；其余用例未改。

前端全量 `npx vitest run` 结果：`27 passed, 1 failed`。失败项为 `tests/FullFlow.test.tsx > complete web flow > shows dashboard, honors original-plan continuation and opens the report with downloads` 的「下载 Word 报告」链接断言；已在未改动的 `integration2` 前端复现，属 `KNOWN-BASELINE`，与本分支无关。

### 2.3 fixtures

未修改 `backend/tests/fixtures/` 与 `fixtures/` 下的源夹具的最终内容。全量测试会改写 `backend/tests/fixtures/worker/results/sensitive-error.json`（已知副作用），提交前已 `git restore`；`git diff bda382f..HEAD -- fixtures backend/tests/fixtures` 为空。测试只写入 `tmp_path` 或测试输出目录。运行结束后已清理 `.pytest-tmp*`、`.venv`、`frontend/node_modules` 软链等临时物，`git status` 干净。

## 3. 剩余风险

1. **文件上传尚未实现**：`已有论文初稿，提供文件` 当前只有 textarea 粘贴入口，没有真正的文件选择/上传、解析 docx/PDF、材料版本记录。后端字段名保持 `upload`，后续接文件上传时不需要再改选项语义。
2. **写法参考卡可能降级**：当前检索池只有摘要与书目字段，没有开放全文。**无 OA 全文或仅有摘要时必须写明降级原因，并按通用口径写、不得抄写范文**：同期刊少于 2 篇写「降级原因」，不少于 2 篇但无全文写「字段降级说明」，两种卡都不会生成可模仿段落的完整写法参考。只有摘要时降级卡是预期行为，不是错误；若后续接入全文，才可能生成非降级卡。
3. **C2 新字段靠 schema 与重试约束**：`_validate_component_shape` 对旧夹具保持兼容，若模型完全不给新字段，不会硬失败，只会走兜底段落；要强制“必须生成新字段”需再收紧 schema 校验，但会影响旧夹具回归。
4. **target_journal 只服务 C1**：C2 不生成期刊写法参考卡；若后续要求 C2 也按目标期刊调整综述口径，需要扩展。
5. **远端 task store 路径**：本地任务会写 `user_requirements_recorded` 事件；远端权威存储路径只保证 `用户要求台账.md` 落盘，未单独写远端事件（远端答案本身已保存完整 `c_info_route/c_material/target_journal`）。
6. **e2e 仅跑 05 单例**：未跑完整浏览器验收套件；完整套件受基线方向夹具与其他历史用例影响，不作为本次 C 模式收尾门禁。

## 4. 主要文件

- `backend/app/task_presenters.py`
- `backend/app/answer_validation.py`
- `backend/app/task_flow.py`
- `backend/app/orchestration.py`
- `backend/app/writing.py`
- `backend/tests/test_cmode_finish.py`（新增）
- `backend/tests/test_task_presenters.py`
- `backend/tests/test_task_flow.py`
- `backend/tests/test_orchestration.py`
- `frontend/src/components/TaskWizard.tsx`
- `frontend/tests/TaskWizard.test.tsx`
- `frontend/e2e/task-browser-acceptance.spec.ts`
- `frontend/e2e/real-backend/helpers.ts`
- `dev/acceptance/competition-evidence/scripts/e2e/helpers.ts`
