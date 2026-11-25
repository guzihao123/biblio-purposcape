# B 模式 [M] 非论文材料接线（bmaterials）

分支：`bmaterials`（worktree：`/Users/crisprcas_9/WorkBuddy/2026-11-06-20-49-06/purpose-landscape-web-bmaterials`）
基线：`integration2` @ `bda382ff0282c320ea91f33105e33f493886f918`
范围：仅 B 模式 [M] 材料接线；未改 C/D 流程、未改前端 TaskWizard 结构、未部署、未 push。

## 改动文件

- `backend/app/task_presenters.py`
  - `_mode_card()` 的 `conditional_fields.B` 新增可选 textarea `policy_materials`，标签「政策/报告/统计材料（可粘贴全文或链接，可跳过）」；前端通用字段渲染原样复用。
- `backend/app/answer_validation.py`
  - mode 答案白名单加入 `policy_materials`，字符串上限 16,000 字符；超限/控制字符仍按 422 拒绝。
- `backend/app/policy_search.py`
  - 新增 `collect_b_materials()`：解析用户粘贴材料（多段以 `---` 分隔）、元数据行（标题/发布机构/文号/成文日期/链接/转载发布日期/原文链接/来源）与原文正文；三要素缺失即拒收，不补造元数据。
  - 用户明确给出的**单独官方链接**：未配置授权抓取器时直接记为覆盖边界，不发起网络请求；配置了 URL 定向 fetcher 时只抓该链接，仍无发现/全网检索。
  - 复用 `PolicyService`/`FullTextService`：纯文本逐字句摘录（带「文本 第 N 句」锚点）、HTML/docx/PDF/OCR 既有通道不变；`policy_docs/M1_…` 归档原件，追加写 `非论文材料清单.md`（标题/机构/文号/成文日期/链接/转载注明/逐字摘录/原件）。
  - gov.cn 转载粘贴文本标注「未联网核验转载关系」，保留官方原文链接与转载发布日期；不冒充已核验官方原文。`[M]` 仍 `included_in_n_pool=False`。
- `backend/app/writing.py`
  - `WritingTask.materials`；B 构件与正文 payload 均带 `materials`、`material_index`、`material_rules`，system prompt 追加 `B_MATERIAL_RULE`。
  - `_render_b()` 追加「非论文材料索引（[M] 与论文 [n] 分通道）」；正文必须写「（据材料 M1）」，编号须对应已接收材料；无材料时禁止写该引用。
  - `[M]` 不进入 `evidence_ledger.md`，`[n]` 台账、verify 与 renumber 正则未改。
- `backend/app/orchestration.py`
  - `generate_stage()` 在 B 写作前收集材料并挂到 `WritingTask`/`DeliveryTask`；需求对账新增材料交付项或无材料覆盖边界项；`checkpoint.materials` 报告接收数与拒收原因，拒收原因并入 warnings。
- `backend/app/delivery.py`
  - `DeliveryTask.material_listing` / `material_originals`；`deliver()` 将清单与平铺原件（`M1_…`）写入任务根目录并纳入 `artifacts`，符合 web 上传只同步顶层文件、文件名禁路径分隔符的约束。
- 测试
  - 新增 `backend/tests/test_bmaterials.py`：字段与白名单、粘贴文本/官方链接解析、转载注明、清单落盘、原件事归档、payload、[M] 引用校验、交付 artifacts、无材料边界、B 全流程编排。
  - `backend/tests/test_task_presenters.py`：B 卡字段断言更新为四字段（含可选材料 textarea）。

## 测试结果

定向套件（含四模式交付回归）：

```
PYTHONPATH=backend <主仓库>/.venv/bin/python -m pytest -q \
  backend/tests/test_bmaterials.py backend/tests/test_policy_search.py \
  backend/tests/test_writing.py backend/tests/test_task_presenters.py \
  backend/tests/test_orchestration.py backend/tests/test_delivery.py \
  backend/tests/test_mode_delivery_regression.py
90 passed in 7.26s
```

全量后端：

```
PYTHONPATH=backend <主仓库>/.venv/bin/python -m pytest -q backend/tests --basetemp=/tmp/bmaterials-pytest
502 passed, 5 skipped, 5 warnings in 30.46s
5 failed
```

5 项失败均为基线既有问题，已在未改动的 `integration2` 工作区用同一解释器逐一复现：`test_recovery.py::test_uvicorn_access_and_exception_logs_redact_artifact_requests`、`test_worker_e2e.py::test_c_pair_real_rq_worker_word_ppt_and_evidence`（两个参数）、`test_worker_e2e.py::test_a_dialogue_real_rq_worker_has_seven_categories_and_two_slots`、`test_worker_e2e.py::test_graph_renderer_failure_is_real_rq_and_task_error`。失败集中在 RQ worker 日志/任务断言，与本次 B 材料接线无关；按范围约束未修改。

测试会重写 `backend/tests/fixtures/worker/results/sensitive-error.json`，已执行 `git restore backend/tests/fixtures/worker/results`；提交前工作区仅含上列代码与测试改动及本报告。

## 关键验证输出

- 粘贴两段材料（含 gov.cn 转载段）得到 `[M1]`、`[M2]`，`included_in_n_pool=False`；摘录锚点为「文本 第1句/第2句」，逐字原文进入清单。
- 官方链接单独输入且无 fetcher：`items=[]`，拒收原因「未粘贴全文且未配置授权抓取器；未发起网络请求」，不生成清单。
- B 全流程编排：接收 2 条材料，任务目录出现 `非论文材料清单.md`、`M1_*.txt`、`M2_*.txt`；正文含「（据材料 M1）」；`evidence_ledger.md` 无 `M1`；`conformance.md` 含「[M] 材料 2 条」。
- 无材料分支：`checkpoint.materials = {'accepted': 0, 'rejected': []}`，无清单与原件 artifact，`conformance.md` 写明「未提供非论文材料」，正文无材料引用。

## 未做事项与遗留风险

- 未改前端与 e2e；`frontend/e2e/task-browser-acceptance.spec.ts` 既有字段断言在此前 `bcard-simplify` 报告中已标注过期，新增第四个字段后仍需单独更新。
- 用户粘贴的 gov.cn 转载材料按文本著录并注明「未联网核验转载关系」；若需升级为已核验转载件，仍需注入授权 fetcher 走 `PolicyService` 的原文核验分支。
- 政策三要素（发布机构、文号、成文日期）缺失时材料被拒收并给出原因，不自动补全、不编造；OCR 摘录仍须人工核对。
- 未提供材料时不生成清单/原件 artifact，正文出现「（据材料 M…）」会被写作门禁拒绝重试；这是设计上的覆盖边界而不是故障。
- 未部署、未 push；分支提交仅落在本地 `bmaterials`。
