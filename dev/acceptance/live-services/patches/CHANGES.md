# 主线审查补丁清单（2026-11-24）

两个补丁彼此独立，均不改动主线文件（本轮零新增真实网络请求；千问保持 0 调用）。

## 补丁 1：retry_after_patch.diff

- **范围**：仅 `skill_runtime/scripts/search_papers.py` 的 `fetch()`。单 hunk（@@ -53,7 +53,14 @@），无其他检索逻辑调整。
- **内容**：429 时解析 `Retry-After` 头（数字秒）；缺失／非法／负数／HTTP-date 回退原固定退避 `10*(i+1)`；合法值封顶 60 秒（`min(int(ra), 60)`），Retry-After 是等待提示而非无限等待许可。
- **基线**：主线 `search_papers.py` sha256 `84fd64fc211a2db36eb3134c432bda8ece3eab681ed55b896bae75c98e23fd95`；函数 `fetch()` 位于第 41–57 行，被替换语句为第 56 行。
- **失败→通过证据**（进程级故障注入，受控本地端点，非 OpenAlex 真实响应）：
  - 修复前：`test_fault_injection_429_honors_retry_after` 失败（固定 10s/20s 退避，未读 Retry-After）；
  - 修复后：同测试通过（Retry-After:1 时按 1 秒退避，3 次尝试后成功）；
  - 封顶回归：补丁初版原样转发 `999999` → `test_fault_injection_429_retry_after_capped` 失败 → 加 60 秒封顶后通过；边界用例（缺失/`abc`/`-5`/HTTP-date/正常值）全部按预期回退或取值。
- **apply --check**：`git apply --check` 通过；`patch --dry-run -p1` 通过。应用方式：`patch -p1 < retry_after_patch.diff`（在 `skill_runtime/scripts/` 目录内）或 `git apply` 后重命名目标。

## 补丁 2：live_openalex_deterministic_test.patch

- **范围**：仅 `backend/tests/test_live_services.py`。11 hunks，不含 Retry-After 或任何生产检索代码。
- **内容**：旧 LIVE 测试的确定性过滤改写——
  - 查询串保持 `RETRACTED_QUERY` 原样，仅测试侧对 OpenAlex `filter` 参数追加 `is_retracted:true`（`_inject_retracted_filter`，已验证幂等），不触碰生产检索代码；
  - 撤稿场景 limit 1→2，断言同时覆盖撤稿原文研究（标题非 `retraction` 开头）与撤稿声明（标题 `retraction` 开头），且全部 `is_retracted is True`；
  - 原文与声明均验证：不入合并池、`is_retracted` 不泄漏进保留池、ref_no 稳定、检索日志计数（Returned count 4 与 2）；
  - 新增 `test_retraction_commentary_type_policy_offline`（离线、零网络）：锁定 2026-11-24 真实观察到的 Faculty Opinions 述评（W4213234079，type=peer-review）**不因标题关联撤稿原文而被判定撤稿**；其不入池是 `peer-review` 不在 article/review/preprint 池策略内的结果，测试注释明确禁止将其改写为撤稿判定；
  - 文件头注释保留原始失败说明：原测试错误假设 relevance 首条必为撤稿原文（2026-11-24 真实首条为非撤稿述评，测试失败）。
- **原始失败证据**：`openalex-live/live_acceptance_summary.json`（result=failed）、`openalex-live/retracted.json`（述评记录），未删除、未放宽既有断言。
- **基线**：主线 `test_live_services.py` sha256 `d0f63ab43d62bea2de5a31b9faa4626dbe374c4bbc0f131d4c5174b3ae0ee64a`。
- **apply --check**：`git apply --check` 通过；`patch --dry-run -p1` 通过。应用方式：`patch -p1 < live_openalex_deterministic_test.patch`（在 `backend/tests/` 目录内）。
- **默认离线回归**（LIVE 保持 opt-in，不因补丁审查自动联网）：`tests/test_live_services.py tests/test_search.py tests/test_rate_limit.py tests/test_policy_search.py` 共 **61 passed, 4 skipped**（3 个 LIVE opt-in 跳过 + 既有 1 跳过），见 `offline_regression.log`。

## 明确未夹带事项

- OpenAlex `meta.notice` 中 `api_key=YOUR_KEY` 为官方占位说明，按白名单保留，两个补丁均不含其清理。
- `search_log.md` 本地绝对路径继续标为边界，报告不宣称"完全脱敏"。
- 千问第二阶段未授权（0 调用）。

## 文件清单

- `retry_after_patch.diff` / `live_openalex_deterministic_test.patch`：两个补丁
- `baselines.sha256`：两个基线文件哈希（项目相对路径，已用 `shasum -a 256 -c` 从项目根复验通过）
- `pristine/search_papers.py` / `pristine/test_live_services.py`：基线副本（供主线核对）
- `offline_regression.log`：补丁后默认离线回归结果（61 passed, 4 skipped）
- `verify_round1_baseline_red.log` / `verify_round2_patched_green.log`：失败→通过两轮证据（2026-11-24 复验）

## 本轮（19:38 指令）独立复核记录

- 两个补丁均通过 `patch -p1 --dry-run` 与 `git apply --check`（主线文件与 pristine 副本各一次）。
- 失败→通过两轮证据为本地受控端点进程级故障注入（127.0.0.1 临时端口，零新增真实网络请求）：
  - Round 1（未打补丁基线）：`test_fault_injection_429_honors_retry_after`（固定 10s/20s 退避，elapsed 30.0s）与 `test_fault_injection_429_retry_after_edge_cases`（Retry-After:2 期望 [2] 实得 [10]）失败，其余 4 项通过；
  - Round 2（应用 retry_after_patch.diff 后）：6/6 通过；随后反向应用恢复主线文件，sha256 复验与基线一致。
- 测试补丁：临时应用后默认离线回归 61 passed, 4 skipped（RUN_LIVE_OPENALEX_ACCEPTANCE 未设置，LIVE 保持 opt-in），随后恢复主线测试文件，sha256 复验一致。
- 证据 Harness 修复：`openalex-live/test_live_openalex_acceptance.py` 原以 `parents[2]` 定位项目根，在本目录深度下解析失败（FileNotFoundError，6 项瞬时失败）；改为向上查找 `skill_runtime/scripts/search_papers.py` 的 `_project_root()`。仅测试脚手架改动，不影响任何主线文件与补丁内容。
- 原始失败证据核对：`openalex-live/retracted.json` 首条即为 W4213234079（Faculty Opinions recommendation，type=peer-review，is_retracted=False），与补丁头注释的假设说明一致。
- 千问保持 0 调用；OpenAlex `meta.notice` 的 `api_key=YOUR_KEY` 官方占位说明按白名单保留；`search_log.md` 本地绝对路径继续标为边界，不宣称完全脱敏。
