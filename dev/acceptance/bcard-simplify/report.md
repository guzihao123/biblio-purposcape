# B 卡输入对齐 Skill（bcard-simplify）

分支：`bcard-simplify`（worktree：`/Users/crisprcas_9/WorkBuddy/2026-11-06-20-49-06/purpose-landscape-web-bcard-simplify`）
基线：`main` @ `2d8cf06`
范围：仅后端 B 模式输入与写作兜底；未改前端逻辑、卡片顺序、校验、search/delivery 文件名。

## 改动文件

- `backend/app/task_presenters.py`
  - `_mode_card()` 的 `conditional_fields.B` 仅保留 `name`（必填）、`goal`（必填）、`funding`（可跳过）；移除 `research_contents`、`technical_route`、`feasibility`、`expected_outcomes`。
- `backend/app/orchestration.py`
  - `_writing_task()` 对缺失字段补安全默认：`research_contents=[]`、`technical_route=''`、`feasibility=''`、`expected_outcomes=''`、`funding='未指定'`，避免下游 `KeyError`；字符串形态的 `research_contents` 仍按原逻辑拆分。
- `backend/app/writing.py`
  - 新增 `B_SYSTEM_GENERATED_PLACEHOLDER`：`（由系统根据项目主题与文献生成，见正文）`。
  - 新增 `B_PROJECT_GENERATION_RULE`：用户只给名称/目标/资助类别，研究内容（3–4 项）、技术路线、可行性、预期成果必须基于主题+论文池生成，不得留空或只写占位；正文必须保留这些章节。
  - `_render_b()` 对四个字段缺失/空白/非列表输入不再报错，渲染占位而不是伪造内容；字符串形态按行/分号拆分。
  - 组件与正文的模型 payload（B 模式）新增 `project_generation_rules`，并将同一规则追加到 system prompt。
- `backend/tests/test_task_presenters.py`
  - 新增 `test_b_mode_card_only_asks_for_name_goal_and_optional_funding`。
- `backend/tests/test_writing.py`
  - 新增 `test_b_minimal_project_generates_components_and_body_without_key_error`。
  - 新增 `test_b_render_uses_placeholder_for_missing_or_empty_project_fields`。
  - 新增 `test_b_full_project_still_renders_user_supplied_plan_fields`（旧全字段 project 仍通过）。
  - 新增 `test_b_model_payloads_require_system_generated_plan_sections`（组件/正文 payload 均带明确生成指令）。

## 测试结果

指定套件：

```
pytest backend/tests/test_task_api.py backend/tests/test_task_presenters.py \
       backend/tests/test_writing.py backend/tests/test_mode_delivery_regression.py \
       backend/tests/test_orchestration.py -q
63 passed
```

全量后端：

```
pytest backend/tests -q
477 passed, 4 skipped, 5 warnings
```

测试会重写 `backend/tests/fixtures/worker/results/*.json`，已按要求 `git restore backend/tests/fixtures/worker/results`，提交前工作区只含上列代码与测试改动。

## B 最小输入验证输出

用真实 `Orchestrator._writing_task` 接收仅含 `name`/`goal` 的 project（`funding` 缺省），再以 B fixture 构件走 `WritingService.produce`：

```
project defaults: {'name': '肝细胞癌耐药联合验证', 'goal': '形成分层验证方案', 'funding': '未指定',
                   'research_contents': [], 'technical_route': '', 'feasibility': '',
                   'expected_outcomes': ''}
placeholder count in components: 4
components has 研究内容与技术路线: True
body headings: ['## 项目名称与目标', '## 研究背景与刚性需求', '## 国内外研究进展',
                '## 已有研究对本项目技术路线的支撑', '## 关键不足', '## 拟解决的关键科学问题',
                '## 研究内容', '## 不足↔科学问题↔研究内容一一对解表', '## 技术路线',
                '## 创新点与已有工作差异表', '## 可行性', '## 预期成果', '## 六段论证链']
body files: ['components.md', 'evidence_ledger.md', 'outline.md', 'sample.md', '综述初稿.md']
body chars: 3868
```

结论：最小 project 不抛 `KeyError`，构件与正文均生成，正文仍含研究内容/技术路线/可行性/预期成果章节。

## 未做事项与遗留风险

- 未实现“项目主题候选卡”；B 模式仍由用户输入项目名称与目标。
- `backend/app/answer_validation.py` 未改动（按约束不改校验），仍接受旧的四个字段；旧客户端提交全字段可继续工作。
- `frontend/e2e/task-browser-acceptance.spec.ts` 仍断言旧的四字段（233–236 行）；按约束未改前端，该 e2e 需后续单独更新，否则会失败。
- 组件 schema 未新增研究内容/技术路线等结构化字段，生成依赖 payload 指令与模板；实际模型输出质量需在线样例复核。