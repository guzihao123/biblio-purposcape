# 检索源路由验收报告（search-routing 分支）

## 分支状态

- 分支 `search-routing` 保留在独立 worktree；**未合并、未部署、未改主线代码**。
- 主线正在稳定生产（模型超时兜底 + 线上验收），本分支只保留检索层与对应测试/验收材料。
- 测试运行期间被改写的 fixtures 已 `git restore`；两个 worktree 均无残留 fixture 改动。

## 改动范围

只改检索层及其测试，不动前端、卡片、写作与交付流程。

- `backend/app/search.py`
  - `SearchRequest` 新增 `direction`（方向原文）与 `semantic_scholar`（默认 `False`）。
  - 新增 `plan_sources()` / `SourcePlan`：OpenAlex 恒为基础源；出现计算机/工程/AI（含 `AI`、`LLM`、`机器学习`、`机器人`、`算法` 等中英文标记）加 arXiv；**仅当选定的 terms/extensions 含中文字符**才加 Crossref（方向为中文但术语为英文仍跳过 Crossref）；Semantic Scholar 仅显式 opt-in。
  - `SearchService.run()` 按 `openalex → arxiv → crossref → semantic_scholar` 顺序逐源、逐范围、逐术语串行检索；每源独立 raw JSON。OpenAlex 失败仍中止；arXiv/Crossref/S2 失败写 `search_log.md`（`Status: degraded` + `Reason`）并继续，不阻塞基础池。
  - 超时按脚本约定：OpenAlex 120s / arXiv 180s / Crossref 180s / S2 300s（脚本内 socket 30s、429 退避封顶 60s，arXiv 可能两次请求）；显式 `timeout` 或 `source_timeouts` 可整体/逐源覆盖。速率与退避沿用 `search_papers.py`，不并发打源。
  - 多源结果复用 `merge_records()`：DOI / 规范化标题去重、字段回填、OpenAlex 优先；每范围仍 ≤50 篇。保留 `source`、`_origins`，新增公开 `retrieval_sources`，并在 `search_log.md` 用同名字段镜像。
  - CLI 增加 `--direction` / `--semantic-scholar`，打印实际路由与降级信息。
- `backend/app/orchestration.py`：search_stage 把用户方向传给 `SearchRequest`，供主题分流使用（唯一一处流程侧改动）。
- `backend/tests/test_search.py`：新增 4 个路由决策单测、3 个 fake 检索器回归（arXiv/AI、Crossref/中文、次源失败降级）、1 个 `retrieval_sources` 日志/池一致性测试、1 个 opt-in 真实多源 smoke。
- `dev/acceptance/search-routing/`：本报告与两条真实 smoke 的日志目录。
- 未修改 `skill_runtime/scripts/search_papers.py`、前端、卡片、写作、交付代码。

## 字段一致性与编号规则（已确认）

- `papers.json` / `papers_all.json` 中每篇论文都有 `retrieval_sources` 数组（如 `["openalex", "arxiv"]`）。
- `search_log.md` 中：
  - 每次源检索条目写入 `- retrieval_sources: ["openalex"]`（失败降级为 `[]`）；
  - 每个 scope 合并后追加 `## <时间戳> | <scope> | retrieval_sources` 小节，写入
    `- retrieval_sources: [{"ref_no": 1, "retrieval_sources": [...], "doi": ..., "title": ...}]`。
  - 字段名与池文件完全一致，且是该 scope 池内 `papers` 的逐篇镜像；新测试 `test_retrieval_sources_field_matches_between_search_log_and_pools` 直接断言两者相等。
- `ref_no` 规则与 `main` 相同：本分支未改动 `_selection_key()` 与 `merge_records()` 的选择/编号代码，仍是先按 mode 的稳定排序键排序、截断到 limit，再 `enumerate(..., 1)` 连续编号；`candidate_id` 等旧编号字段被剔除。既有测试 `test_ref_numbers_are_deterministic_and_never_reuse_candidate_ids` 的正反序断言继续通过。两条真实 smoke 的池编号分别为 `[1,2]` 与 `[1]`。

## 测试

| 项目 | 命令 | 结果 |
| --- | --- | --- |
| 检索离线回归 | `pytest backend/tests/test_search.py -q` | 33 passed, 2 skipped |
| 真实多源 smoke | `RUN_LIVE_SEARCH_ROUTING_SMOKE=1 pytest backend/tests/test_search.py::test_live_multi_source_routing_smoke -q` | 1 passed |
| 全量 | `pytest backend/tests -q` | 471 passed, 5 skipped, 5 failed（见下：均为已知沙箱问题） |

### 已知失败：沙箱日志脱敏，不计入本分支回归

全量测试里的 5 个失败来自同一类既有问题：当前沙箱把日志中的数字/十六进制片段替换成 `[REDACTED_ENV]`，使 worker/access 日志断言找不到原始 UUID、job id 或 `1.1`。与检索路由、合并、降级代码无因果关系。

首次全量运行的 5 个失败用例名：

1. `backend/tests/test_recovery.py::test_uvicorn_access_and_exception_logs_redact_artifact_requests`
2. `backend/tests/test_worker_e2e.py::test_c_pair_real_rq_worker_word_ppt_and_evidence[c-pair-word-A]`
3. `backend/tests/test_worker_e2e.py::test_c_pair_real_rq_worker_word_ppt_and_evidence[c-pair-ppt-C]`
4. `backend/tests/test_worker_e2e.py::test_graph_renderer_failure_is_real_rq_and_task_error`
5. `backend/tests/test_worker_e2e.py::test_sensitive_failure_real_rq_logs_events_and_response_are_redacted`

在未修改的 `main` worktree 用同一解释器复现（命令在 `/Users/crisprcas_9/WorkBuddy/2026-11-06-20-49-06/purpose-landscape-web` 执行）：

```bash
/Users/crisprcas_9/WorkBuddy/2026-11-06-20-49-06/purpose-landscape-web/.venv/bin/python -m pytest \
  backend/tests/test_recovery.py::test_uvicorn_access_and_exception_logs_redact_artifact_requests \
  'backend/tests/test_worker_e2e.py::test_c_pair_real_rq_worker_word_ppt_and_evidence[c-pair-word-A]' \
  'backend/tests/test_worker_e2e.py::test_c_pair_real_rq_worker_word_ppt_and_evidence[c-pair-ppt-C]' \
  backend/tests/test_worker_e2e.py::test_graph_renderer_failure_is_real_rq_and_task_error \
  backend/tests/test_worker_e2e.py::test_sensitive_failure_real_rq_logs_events_and_response_are_redacted \
  -q --basetemp=.pytest_tmp/main-five
```

输出（末尾）：

```text
FAILED backend/tests/test_recovery.py::test_uvicorn_access_and_exception_logs_redact_artifact_requests
FAILED backend/tests/test_worker_e2e.py::test_c_pair_real_rq_worker_word_ppt_and_evidence[c-pair-word-A]
FAILED backend/tests/test_worker_e2e.py::test_c_pair_real_rq_worker_word_ppt_and_evidence[c-pair-ppt-C]
FAILED backend/tests/test_worker_e2e.py::test_graph_renderer_failure_is_real_rq_and_task_error
FAILED backend/tests/test_worker_e2e.py::test_sensitive_failure_real_rq_logs_events_and_response_are_redacted
5 failed in 2.35s
```

关键断言片段（同一输出）：

```text
E  assert 'GET /api/health HTTP/1.1' in '... "GET /api/health HTTP/[REDACTED_ENV].[REDACTED_ENV]" 200 OK\n'
E  assert False  # worker 日志里 job_id 被脱敏，all(job_id in log_text) 失败
```

最后一次全量运行中，第 5 个失败轮换为 `test_a_dialogue_real_rq_worker_has_seven_categories_and_two_slots`（`test_graph_renderer_failure_is_real_rq_and_task_error` 该次通过）。同样在 `main` 复现该组 5 个用例，输出为 `4 failed, 1 passed in 3.01s`；重复单独跑 graph 用例 5 次得到 `1 passed, 4 failed`，说明该失败随随机 UUID 是否触发脱敏而漂移，进一步确认是环境既有问题。结论：把这 5 个失败标为**已知（KNOWN）**，不计入本分支回归；本分支检索相关用例全部通过。

## 真实 smoke 结果

两条 smoke 都用 `--limit` 小值真实联网执行，日志与原始 JSON 已持久化在分支内：

1. 中文词路由（OpenAlex + Crossref，limit=2，term=`课后服务`，direction=`教育研究`，`--from-year 2023`）：
   - 日志：`dev/acceptance/search-routing/smoke-logs/chinese-openalex-crossref/search_log.md`
   - 合并池：`dev/acceptance/search-routing/smoke-logs/chinese-openalex-crossref/papers.json`、`papers_all.json`
   - 路由 `['openalex', 'crossref']`、无降级；limited 命中 OpenAlex 251 / Crossref 28148，各返回 2 篇；合并池 `count=2`、`ref_no=[1,2]`、DOI 唯一，来源标签 `crossref` 与 `retrieval_sources` 均保留。
2. 英文词 AI 方向路由（OpenAlex + arXiv，limit=1，direction=`人工智能`，query=`graph neural network`）：
   - 日志：`dev/acceptance/search-routing/smoke-logs/ai-openalex-arxiv/search_log.md`
   - 合并池：`dev/acceptance/search-routing/smoke-logs/ai-openalex-arxiv/papers.json`、`papers_all.json`
   - 路由 `['openalex', 'arxiv']`（术语英文，Crossref 按规则跳过）；命中 OpenAlex 96644 / arXiv 12580，各返回 1 篇，raw `source` 正确；合并池 `count=1`、`ref_no=[1]`、无降级。

## 剩余风险

- Crossref 为词袋检索、命中数虚高；严格的术语字面相关性过滤可能剔除多词查询的全部结果，中文场景建议用 1 个核心词或检查 `search_log.md` 后再调整术语。
- arXiv 脚本接受但不应用 `--from-year`，年份截断由池级过滤兜底；arXiv/Crossref/S2 记录没有 `institutions/countries`，机构与国别统计仍只覆盖 OpenAlex 论文。
- Semantic Scholar 已实现 opt-in 与同等降级，但因限流未做真实 smoke；其记录无 `referenced_works`，不参与引用建边。
- 主题判断是确定性关键词/中文字符规则，不是学科分类器；跨学科方向（如“医学教育中的大模型”）会加 arXiv，marker 需按实际术语表调整。
- 上述 worker/日志脱敏失败会在当前沙箱中继续出现，需在普通 CI 环境复核；它们不影响检索池产物，且已在 `main` 复现。
