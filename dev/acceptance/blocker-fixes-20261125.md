# 三个阻断项修复记录（2026-11-25）

> 证据补记：2026-11-26 00:07–00:09 GMT+8。本次只改文档，未 push、未部署；测试数字来自本轮回归日志，公开入口来自现场只读 `curl`。A 模式仅检索阶段通过，生成与 Word 下载仍未完成验收。

## 1. 后端全量测试挂死

- 根因：`test_ppt_visual_integrity.py` 的 D 交付夹具调用真实 `prepare_d_figures`，fixture 带 Science OA PDF 链接，测试进入网络下载。
- 修复：`backend/tests/test_mode_delivery_regression.py` 增加测试专用 `offline_figure_loader`，`deliver_mode` 默认使用离线空图集，不再访问网络；`test_ppt_figures.py` 的单测本身正常（4 passed / 0.85s）。
- 结果：后端全量 **622 passed / 5 skipped**；2026-11-26 00:06:47–00:07:14 GMT+8 回归为 622 passed / 5 skipped、5 warnings、25.48s、exit 0，不再挂死。修复提交 `ec14abf`；日志 `dev/acceptance/regression-20261126/backend.log`。

## 2. 检索阶段 1800 秒超时

- 根因：50 篇论文的分析为顺序模型调用；原实现 classify 13 次 + factors 13 次 + relations 33 次，共 59 次调用；线上单次调用偏慢，整体超过 30 分钟验收预算，任务停在 searching。
- 修复（提交 `a101e5f`，2026-11-25 21:46:44 GMT+8）：
  - 默认 batch_size 4 → 10；
  - 跨批候选关系从“每对一次调用”改为每组最多 5 对一次调用；
  - 增加 `ANALYSIS_BUDGET_SECONDS`（默认 900s）与调用间隙截止检查；
  - 分析并发默认 1（`ANALYSIS_CONCURRENCY`），避免触发供应商限流；
  - 模式化写作/分析池上限：A=20、B=30、C=20、D=20（环境变量 `PAPER_LIMIT_<MODE>` 可调），图谱统计仍使用完整检索池。
- 结果：同一 A 任务线上检索从超时降到约 **3 分钟**（22:03:51 searching → 22:06:52 dashboard_ready）。50 篇完整池下的模型耗时仍偏高，因此保留模式化上限作为默认。

## 3. 500/502/504 与任务冻结

- 已定位/修复：
  - Qwen `RateLimitError` 与 `InternalServerError` 原未纳入可重试异常，已加入 `retry_call` 的 transient 集合，并把非 thinking 调用重试提升到 4 次、1s 起、最大 8s。
  - 前端对任务创建、任务读取、答题、图谱、报告接口增加 502/503/504 与网络错误的有界重试（2 次）。
  - 模式卡提交会同步生成候选术语，可能超过 Qoder 网关 50 秒上限，返回 502/504；后端实际已应用答案，验收脚本通过“等 25 秒查状态”继续，不再重复建单。
- 仍未闭合：
  - Render web 在滚动部署期间会短暂返回 502；部署窗口内启动的验收任务会冻结在 search/generate，属于进程重启而非业务异常。
  - 模式卡同步候选术语仍可能触发网关超时，需要后续改成异步准备或缩短生成时间。
  - 生产 web/worker 日志仍无法从当前环境导出，worker 重启/OOM 与冻结的精确对应关系未直接取证。

## 4. 验证基线

- 后端：622 passed / 5 skipped。
- 前端单测：40 passed。
- Deno 站点函数：65 passed。
- Playwright 主流程：11 passed（含修复后的 02 A 主流程、07 窄屏、08 reduced-motion）。
- 已部署：GitHub main `03eb120`；Qoder 站点上一版为 integration3 前端包。
- A 模式真实验收：检索已通过一次（约 3 分钟）；生成与 Word 下载尚待部署稳定后复验。