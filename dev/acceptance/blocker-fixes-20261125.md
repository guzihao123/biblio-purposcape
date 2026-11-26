# 三个阻断项修复记录（2026-11-25）

> 证据补记：2026-11-26 00:22 GMT+8。本次只改文档，未 push、未部署；最新测试基线为 integration3 `0b83b2f` 的 739 passed / 5 skipped，公开入口来自现场只读 `curl`。A 模式新任务仍在检索/生成链路中，Word 尚未拿到，验收保持 blocked。

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
  - 模式化写作/分析池上限：A=20、B=30、C=20、D=20（提交 `d6f6c0c`；环境变量 `PAPER_LIMIT_<MODE>` 可调），图谱统计仍使用完整检索池。
- 结果：同一 A 任务线上检索从超时降到约 **3 分钟**（2026-11-25 22:03:51 searching → 22:06:52 dashboard_ready，181 秒）。该时间线来自本轮修复记录，本次未重跑线上任务。50 篇完整池下的模型耗时仍偏高，因此保留模式化上限作为默认；检索通过不等于 Word 下载通过。

## 3. 500/502/504 与任务冻结

- 已定位/修复：
  - Qwen `RateLimitError` 与 `InternalServerError` 原未纳入可重试异常，已加入 `retry_call` 的 transient 集合（提交 `f55ff2d`），并把非 thinking 调用重试提升到 4 次、1s 起、最大 8s。
  - 前端对任务创建、任务读取、答题、图谱、报告接口增加 502/503/504 与网络错误的有界重试（2 次，提交 `a101e5f`）。
  - 模式卡提交会同步生成候选术语，可能超过 Qoder 网关 50 秒上限，返回 502/504；后端实际已应用答案，验收脚本通过“等 25 秒查状态”继续，不再重复建单。
- 仍未闭合：
  - Render web 在滚动部署期间会短暂返回 502；部署窗口内启动的验收任务会冻结在 search/generate，属于进程重启而非业务异常。
  - 模式卡同步候选术语仍可能触发网关超时，需要后续改成异步准备或缩短生成时间。
  - 生产 web/worker 日志仍无法从当前环境导出，worker 重启/OOM 与冻结的精确对应关系未直接取证。

## 4. 最新验证基线

- 基线：**integration3 `0b83b2f`（5xx 回读修复）**；桌面描述修正提交 `64bf6ef` 不影响测试结果。
- 后端：622 passed / 5 skipped；前端单测：**41 passed**；Deno：65 passed；Playwright：11 passed。
- 合计：**739 passed / 5 skipped / 0 failed**。基于 `030a443` 的旧 738 条基线及前端 40 条结果已过期，以 `dev/acceptance/regression-20261126-post-api.md` 为准。
- 当前 Qoder 发布：action `0f3811c8`，入口资源 `index-Bxn32REQ.js` 200，描述文件提交 `64bf6ef`；`index-ByB3KEqp.js` 404 仅保留为历史记录。
- A 模式真实验收：此前一次检索约 3 分钟；**主线新任务仍在检索/生成链路中，尚未拿到 Word，Word 下载未通过，整体保持 blocked**。不得把检索 200/`dashboard_ready` 或 Playwright 的模拟下载用例写成真实 Word 下载已通过，等主线最终结果后再补记。

## 5. 最新回归与现场入口证据（2026-11-26 GMT+8）

最新回归统一引用 `dev/acceptance/regression-20261126-post-api.md`，基线 integration3 `0b83b2f`；旧 `030a443` 的 738 条结果不再作为当前基线。

| 范围 | 时间 | 命令 | 最新结果 | 证据 |
|---|---|---|---|---|
| 后端 | 最新记录 | `.venv/bin/python -m pytest backend/tests -q -p no:cacheprovider` | **622 passed / 5 skipped** | `dev/acceptance/regression-20261126-post-api.md` |
| 前端单测 | 最新记录 | `cd frontend && npm test` | **41 passed** | 同上 |
| Deno | 最新记录 | `deno test --allow-all --import-map=dev/import_map.json sites/functions/*.test.mjs` | **65 passed** | 同上 |
| Playwright | 最新记录 | `node node_modules/playwright/cli.js test --config=playwright.config.ts` | **11 passed** | 同上 |
| 合计 | 最新记录 | — | **739 passed / 5 skipped / 0 failed** | 同上 |
| Qoder 当前资源 | 00:22:42 | `curl -L --max-time 90 --retry 1 --retry-delay 5 -sS -w '\n__CURL__%{http_code} %{size_download}' https://purpose-landscape-w28zuuplkjz.qoder.zone/assets/index-Bxn32REQ.js` | **200**，260779 bytes；SHA-256 `37f1d5fc16605fd06332a12b0413f44d625eab162c72e4595bedb40669f2cbea` | 当前 action `0f3811c8`，描述提交 `64bf6ef`；`index-ByB3KEqp.js` 404 仅为历史记录 |
| Render 当前资源 | 00:22:36 | `curl -L --max-time 90 --retry 1 --retry-delay 5 -sS -w '\n__CURL__%{http_code} %{size_download}' https://biblio-purposcape.onrender.com/assets/index-PUNMBFkc.js` | **200**，260688 bytes；SHA-256 `51bb8816e32168013d650ac75a704d2fd88a83ea9b91892ce490726e0bbbe8dd` | 现场命令输出 |
| Render health | 00:22:36 | `curl -L --max-time 90 --retry 1 --retry-delay 5 -sS -w '\n__CURL__%{http_code} %{size_download}' https://biblio-purposcape.onrender.com/api/health` | **200**；`{"status":"ok","database":"ok","worker":"ready"}` | 现场命令输出 |

Playwright 的 02 A 主流程包含测试环境报告下载，但它不是生产 A 任务的 Word 下载证据；真实生成、`.docx` 下载、zip/`word/document.xml`/正文/参考文献校验仍缺。