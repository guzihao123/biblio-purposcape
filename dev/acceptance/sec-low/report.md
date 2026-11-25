# 安全 LOW 两项修复 + 前端基线恢复报告

- 仓库：`/Users/crisprcas_9/WorkBuddy/2026-11-06-20-49-06/purpose-landscape-web` 的独立 worktree
  `/Users/crisprcas_9/WorkBuddy/2026-11-06-20-49-06/purpose-landscape-web-sec-low`
- 分支：`sec-low`（基于 `main` @ `83363f5`）；代码提交 `fa08a97`
- 时间：2026-11-25
- 范围：只改 `recovery.py` 环境变量脱敏、`main.py` 的 `_sites_raise` 回显、`frontend/tests` 的 FullFlow mock；
  **未部署、未 push、未改 remote、未连接生产库、未打印任何真实密钥值**
- 环境：后端 `.venv`（Python 3.9.6，复用主仓库解释器）；Node v22.22.2 + 主仓库 `frontend/node_modules`

## 一、结论摘要

| 项 | 原状 | 现状 | 证据 |
|---|---|---|---|
| LOW-01 日志过度脱敏 | 环境变量值 ≥4 字符或名称含敏感词即被全局替换，日志与测试中的 `HTTP/1.1`、`127.0.0.1`、行号、`cat` 全被抹掉 | 只替换「名称像凭据且值不是开关/数字」或「值本身符合已知密钥形态」的环境值，变量名与正常诊断原样保留 | `test_recovery.py` +26 用例（判据矩阵）；5 个既有失败用例随之转绿 |
| LOW-02 `_sites_raise` 回显 | `message = str(error)`，安全性完全依赖调用方异常已脱敏 | code 走白名单，`message` 为 `异常类型: 脱敏文本`（≤300 字符），`Retry-After` 校验为有界整数 | 新增 `app/sites_errors.py` + 10 个断言；路由级用例断言 secret 不出现 |
| 前端基线 | `FullFlow` mock 用 `report.docx`，该文件名已不存在于任何交付模式，下载区渲染为空，26/27 | mock 改为 `综述初稿.docx`（`delivery.WORD_FILENAMES` 真实文件名），沿用 ReportPage 现有标签 `下载 Word 报告`，27/27 | `npx vitest run` → 27 passed |

后端全量（`backend/tests`，`--basetemp` 指定沙箱可用临时目录）：

| 时点 | 结果 |
|---|---|
| 基线 `83363f5`（未改代码） | 471 passed, **5 failed**, 4 skipped |
| 本次（`fa08a97` + 判据补测） | **528 passed, 0 failed**, 4 skipped（+52 新用例，+5 既有失败转绿） |

基线那 5 个失败全部是 LOW-01 的症状，不是既有环境噪声：

- `test_recovery.py::test_uvicorn_access_and_exception_logs_redact_artifact_requests`：
  `assert 'GET /api/health HTTP/1.1' in ...` 失败，实际输出为 `GET /api/health HTTP/[REDACTED_ENV].[REDACTED_ENV]`；
- `test_worker_e2e.py` 4 个用例：`assert all(job_id in log_text for job_id in job_ids)` 失败，job id 里的数字 `1` 被替换成
  `[REDACTED_ENV]`（如 `9f9[REDACTED_ENV]f83f-8924-...`）。

根因是宿主环境里的几个普通变量：`CODEBUDDY_API_KEY_HELPER_DISABLED=1`（名称含 `api_key` → 值 `1` 凭「名称敏感」
分支进入替换集合）、`PAGER=cat`（值长度 3，走的是 `len>=4` 之外的另一半条件）、`LOGNAME=root`（值长度 4，命中
`len>=4`）。三者分别抹掉了数字 `1`、单词 `cat` 与 `root`。

## 二、改动逐项

### LOW-01 · 环境变量脱敏只针对疑似凭据

- **位置**：`backend/app/recovery.py:63-84`（新增模式）、`recovery.py:129-147`（`_is_credential_env_value`）、
  `recovery.py:170-176`（替换集合）
- **根因**：旧纳入条件

  ```python
  if item and (len(item) >= 4 or re.search(r'token|secret|password|passwd|api[_-]?key|access[_-]?key|credential', name, re.I))
  ```

  是「值够长 **或** 名字敏感」，与「是密钥」没有关系。于是 `PAGER=cat`、`LOGNAME=root`、`SHLVL=1`、
  `CODEBUDDY_API_KEY_HELPER_DISABLED=1` 都会把裸子串全局替换掉，日志可读性被破坏，且替换是按值长度排序的
  全局 `str.replace`，连变量名、数字和单词内部的字符都会被切开。

- **改法**：把「是否替换」收敛为 `_is_credential_env_value(name, value)` 的单一判据，三级命中：

  1. 值的形态本身是密钥（`_CREDENTIAL_VALUE_RE`）：`sk-…` / `sk_live_…` / `ghp_…` / `github_pat_…` /
     `xox[abprs]-…` / `AKIA|ASIA…` / `AIza…` / JWT `eyJ….eyJ….`。这条与变量名无关，覆盖「名字看不出、值是真钥匙」；
  2. 名称像凭据（`api_key|access_key|secret|private_key|password|passwd|token|credential|auth_key|signing_key`）
     **且** 值不是开关/枚举/纯数字（`_ENV_NON_SECRET_VALUE_RE`）**且** 长度 ≥6；
  3. 名称以 `_KEY` 结尾时，额外要求值 ≥16 字符、无空白、字母数字混合。

  替换标记仍是 `[REDACTED_ENV]`，`_SENSITIVE_ASSIGNMENT_RE`（`token=…` 这类带标签的行内密钥）保持不变，
  因此变量名始终以标签形式留在日志里。

- **行为对照**（同一段文本，`environ` 为测试注入；实测 `old_redact` 与 `redact_sensitive_text` 输出）：

  | 输入片段 | 旧输出 | 新输出 |
  |---|---|---|
  | `127.0.0.1 - "GET /api/health HTTP/1.1"` | `[REDACTED_ENV]27.0.0.[REDACTED_ENV] - "…HTTP/[REDACTED_ENV].[REDACTED_ENV]"`（IP 与协议版本被打碎） | `127.0.0.1`、`HTTP/1.1` 原样保留（`/api/health` 仍按既有路径规则变 `[REDACTED_PATH]`；真实访问日志走 `_redact_access_target`，该路径保留） |
  | `line 1522` | `line [REDACTED_ENV]522` | `line 1522` |
  | `max_tokens=4096` | `max_tokens=[REDACTED_ENV]` | `max_tokens=4096` |
  | `catalog category root` | `catalog category [REDACTED_ENV]`（`root` 被替换） | 原样保留 |
  | `WORKER_SHARED_SECRET=fake-worker-secret-4f21` | `WORKER_SHARED_SECRET=[REDACTED_ENV]` | `WORKER_SHARED_SECRET=[REDACTED_ENV]`（值仍被替换，变量名保留） |
  | 无标签裸 `sk-live-3c9d…`（变量名 `SOME_PLAIN_SETTING`） | 被替换（因为 ≥4 字符） | 被替换（因为命中密钥形态） |

  说明：`WORKER_SHARED_SECRET=` 这种 SCREAMING_SNAKE 名称因 `_` 不是词边界，`_SENSITIVE_ASSIGNMENT_RE` 的
  `\b(?:…|secret|…)` 无法命中，值最终由环境值规则替换 —— 新旧都是 `[REDACTED_ENV]`，区别只在于**是否误伤其他文本**。

- **测试**：`backend/tests/test_recovery.py` 新增 7 个函数 / 26 个用例，逐条对齐判据：

  | 用例 | 覆盖 | 断言要点 |
  |---|---|---|
  | `test_flag_numeric_and_short_word_values_are_never_redacted`（10 组参数） | 值 `1`/`0`/`root`/`cat`/`true`/`false`/`4096`/`30000`/`development`/`utf-8`，变量名含 `api_key`/`secret`/`token` 等 | 输出与输入**逐字节相等**，且不含 `[REDACTED_ENV]` |
  | `test_known_credential_shapes_are_redacted_under_an_innocuous_name`（8 组参数） | `sk-`、`sk_live_`、`ghp_`、`github_pat_`、`xoxb-`、`AKIA`、`AIza`、JWT | 值为密钥形态即替换，变量名 `SOME_PLAIN_SETTING` 无提示；前后文 `upstream rejected` / `after 3 attempts` 保留 |
  | `test_credential_named_variables_with_real_values_are_redacted`（5 组参数） | `QWEN_API_KEY` / `SESSION_SECRET` / `ADMIN_TOKEN` / `WORKER_SHARED_SECRET` / `OPENAI_KEY`（后者走 `_KEY` 后缀分支） | 值消失、`NAME=` 保留 |
  | `test_worker_log_filter_drops_the_secret_before_any_handler_formats_it` | 真实 `logging.LogRecord` 经 `WorkerLogRedactionFilter` | 格式化后文本既无环境值密钥、也无 `api_key=` 内联密钥；`record.args == ()`、`exc_info is None` |
  | `test_env_redaction_keeps_configuration_values_and_names_intact` | 综合文本 | `127.0.0.1`、`HTTP/1.1`、`line 1522`、`max_tokens=4096`、`catalog category root`、`PAGER=cat` 均原样保留 |
  | `test_env_redaction_uses_value_shape_for_unlabelled_credentials` | 无标签裸 `sk-` | 替换且保留上下文（上表已有细节） |

### LOW-02 · `_sites_raise` 不再回显上游原文

- **位置**：`backend/app/sites_errors.py`（新增，63 行）、`backend/app/main.py:98-102`、
  `backend/app/public_access.py:25-29`、`backend/app/task_store_sync.py:12-26`
- **根因**：`detail={'code': code, 'message': str(error)}`。当前链路里 `TaskStoreSyncError` / `SitesTaskStoreError`
  的 `str()` 恰好就是安全 code，但这是**巧合**而非保证：`_safe_errors` 只包裹被装饰的方法，`ValueError`
  （参数校验）、`TypeError`、传输层异常、未来新增的未包裹调用都可能带着 provider body / SQL / 连接串直达客户端。
- **改法**：两处 `_sites_raise` 合并为同一实现 `sites_http_exception(error)`：

  - `code`：只接受 `SAFE_PROVIDER_CODES ∪ {'task_store_sync_failed'}`（`SAFE_PROVIDER_CODES` 由私有名提升为公开名，
    `_SAFE_PROVIDER_CODES` 别名保留以兼容原有私有调用点），其余一律回落 `task_store_unavailable`；
  - `message`：`'{类型名}: {redact_sensitive_text(str(error))}'` 截断到 300 字符 —— 保留异常类型与前缀（可诊断），
    去掉 `api_key=…`、`password=…`、SQL、URL userinfo、本地路径；
  - `Retry-After`：只接受 `1 ≤ int ≤ 999999999`，非 bool；字符串/负数/0/超大值直接丢弃（同时避免 header 注入面）。
  - `public_access.py` 的 `create_public_session` 是同一函数的拷贝（同一个缺陷），一并收敛，避免只修一半；
    `HTTPException` 因此在该文件不再使用，已从 import 中移除。

- **测试**：
  - `backend/tests/test_sites_errors.py`（新增 8 个函数 / 23 个用例）：白名单 code 保留状态码与 `Retry-After`；
    未知 code 回落；`'30'`/`True`/`0`/`-5`/`10**12`/`'1\r\nX-Injected: 1'` 六种非法 `Retry-After` 均不产生响应头；
    `token=`/`password=`/SQL/`/Users/` 全部消失且保留 `_UpstreamError: ` 前缀；超长消息截断到 300。
  - `backend/tests/test_sites_mode_routes.py` 新增 2 个路由级用例：
    - `test_sites_upstream_error_text_is_redacted_but_still_diagnosable`：让 `FakeSitesSync` 抛
      `RuntimeError('upstream 502 while calling https://sites.internal/api/v1/tasks (api_key=sk-live-…, password=…)')`，
      断言 503 / `code=task_store_unavailable` / 两个 secret 均不出现在 message / `RuntimeError` 与 `upstream 502` 保留；
    - `test_sites_error_code_outside_the_allow_list_is_not_echoed`：异常自带 `code='sk-live-…'` 时整段响应不含该字符串。
  - `backend/tests/test_sites_errors.py` 另加 3 个「不回归」用例（共 13 个用例）：
    - `test_every_client_visible_code_keeps_its_http_status`（11 组参数）：逐个钉住
      `session_not_found→401`、`task_not_found|job_not_found→404`、`skill_version_unavailable|revision_conflict|answer_conflict→409`、
      `quota_exceeded→429`、`invalid_provider_response|task_store_unavailable|worker_unauthorized|task_store_sync_failed→503`，
      且 `detail['code']` 与 `message` 原样等于传入 code —— 保证白名单没有把客户端在用的码改掉或降级；
    - `test_allow_list_covers_every_code_the_sync_layer_can_emit`：断言 `SAFE_PROVIDER_CODES ⊆ SAFE_CODES`
      且集合内每个 code 都能原样返回（防日后新增 provider code 时漏进白名单）；
    - `test_provider_local_codes_outside_the_allow_list_are_not_forwarded`：
      `worker_response_too_large` / `invalid_worker_response` 这类只存在于 `sites_task_store` 内部的码不外传。
  - `backend/tests/test_public_access.py` 新增 `test_session_creation_redacts_task_store_failures`：
    `POST /api/session` 注入一个抛 `RuntimeError('task store rejected the session (api_key=…, password=…)')` 的
    `_sites_sync`，断言 503、`code=task_store_unavailable`、两个 secret 不在 `response.text`、
    `RuntimeError` 与 `task store rejected the session` 保留 —— 这是 `public_access._sites_raise` 收敛后的端到端证据。

### 前端基线 · FullFlow 对齐真实交付文件名

- **位置**：`frontend/tests/FullFlow.test.tsx:170,190`
- **根因**：mock 的 `artifacts` 用了 `report.docx`，而 `ReportPage` 的 `downloadLabels`
  （`frontend/src/pages/ReportPage.tsx:6-13`）只认 `综述初稿.docx` / `标书-文献综述分析.docx` / `调研报告.docx` 等；
  后端 `delivery.WORD_FILENAMES` 中 A / A_DIALOGUE / C1 / C2 / E 模式的实际文件名也是 `综述初稿.docx`
  （`backend/app/delivery.py:15-21`）。文件名不匹配 → 下载区渲染为空 → `getByRole('link', …)` 找不到元素。
- **改法**：只改 mock 与 href 断言，不动组件与标签文案：

  ```diff
  - artifacts: [{ name: 'report.docx', url: '/signed/report.docx', size: 1000 }],
  + artifacts: [{ name: '综述初稿.docx', url: '/signed/draft.docx', size: 1000 }],
  - expect(…{ name: '下载 Word 报告' })).toHaveAttribute('href', '/signed/report.docx')
  + expect(…{ name: '下载 Word 报告' })).toHaveAttribute('href', '/signed/draft.docx')
  ```

- **测试**：`npx vitest run` → **27 passed (9 files)**；`npx tsc --noEmit`（`npm run build` 的类型检查段）与
  `npx vite build` 均通过（`dist/assets/index-*.js` 246.65 kB / gzip 77.20 kB，`dist/assets/index-*.css` 24.91 kB）。

## 三、测试与复现

### 3.1 后端

沙箱内 `pytest` 的 `pytest-of-<user>` 临时根目录创建会被拦截（`FileExistsError: mkdir .../pytest-of-root`），
表现为 41 个 collection/teardown 错误 —— 与代码无关，用 `--basetemp` 指定可写目录即可绕过：

```bash
cd /Users/crisprcas_9/WorkBuddy/2026-11-06-20-49-06/purpose-landscape-web-sec-low
/Users/crisprcas_9/WorkBuddy/2026-11-06-20-49-06/purpose-landscape-web/.venv/bin/python \
  -m pytest -q -p no:cacheprovider --basetemp=.pytest-tmp-final
# 528 passed, 4 skipped, 5 warnings in 43.74s
```

### 3.2 前端（node 不可用时的替代方式）

本机 node 可用（v22.22.2），worktree 不复制 `node_modules`，而是软链主仓库现有依赖：

```bash
cd .../purpose-landscape-web-sec-low/frontend
ln -s ../../purpose-landscape-web/frontend/node_modules node_modules
npx vitest run          # 27 passed
npx tsc --noEmit && npx vite build
unlink node_modules     # 验证完删除软链，保持工作区干净
```

node 不可用时用 Docker（同一份 `node_modules` 挂载，无需联网安装）：

```bash
cd .../purpose-landscape-web-sec-low
docker run --rm -v "$PWD/frontend":/app -w /app \
  -v "$PWD/../purpose-landscape-web/frontend/node_modules":/app/node_modules \
  node:22 sh -c 'npx vitest run && npx tsc --noEmit && npx vite build'
```

### 3.3 工作区卫生

`test_worker_e2e.py` 每次运行都会改写 `backend/tests/fixtures/worker/results/*.json`
（时间戳、PID、随机 job id、`log_text`）。这些文件只被写入、不被任何用例读取，属诊断快照。
每次跑完均 `git restore backend/tests/fixtures`，提交树中不含这些噪声（已核对 `git status` 干净）。

## 四、剩余风险

| # | 风险 | 影响 | 建议 |
|---|---|---|---|
| 1 | 脱敏仍是模式匹配：名字无提示、值既非已知前缀也不是字母数字混合的密钥（如 `FOO=<32位随机串>`），若以无标签形式出现在文本中仍可能残留 | 低（需要日志里裸奔高熵串且无 `key=`/`token=` 标签） | 保持 `*_API_KEY` / `*_SECRET` / `*_TOKEN` / `*_KEY` 命名约定；如需更强保证，可改为「不输出任何上游文本、只回固定文案」（安全评审 LOW-02 的严格方案，本次按任务要求保留可诊断信息） |
| 2 | `_sites_raise` 的 message 仍可能含上游**主机名** | 低（主机名非凭据；路径正则因 `(?<![\w:/])` 不切断 URL 内路径，故 `/v1/tasks` 这类片段会保留） | 若要求连端点拓扑也不外泄，切换为按 code 的固定文案 |
| 3 | 环境值替换是全局 `str.replace`，若凭据值恰好是常见英文单词（如 `SECRET_KEY=local`）仍会误伤该词 | 低 | 真实密钥不会取词典单词；不额外处理 |
| 4 | `FullFlow` 只覆盖 A 模式与单个下载项，`标书-文献综述分析.docx` / `调研报告.docx` 标签无前端用例 | 低（组件逻辑同源） | 补 C 模式 / E 模式的下载区断言（本次未扩范围） |
| 5 | `public_access.py` 的同类回显属本次顺带修复（同一缺陷模式），不在用户点名的两项之内 | 无功能风险，仅范围比点名略大 | 已在提交说明与本报告中标注，可单独 review |
| 6 | e2e 用例运行即改写 `backend/tests/fixtures/worker/results/` | 每次都要手动 `git restore`，易误提交 | 后续把这些产物移到 `tmp_path` 或加入 `.gitignore`（未改，避免扩大范围） |
| 7 | 本次**未部署、未 push**；`sec-low` 仅本地分支 | 生产行为未变 | 合并前在预发环境跑一次 `TASK_STORE_AUTHORITY=sites` 的真实链路 |

## 五、交付清单

| 文件 | 变更 |
|---|---|
| `backend/app/recovery.py` | +52/-9：新增 4 个模式与 `_is_credential_env_value`，替换集合改用该判据 |
| `backend/app/sites_errors.py` | 新增 63 行：code 白名单、`Retry-After` 校验、脱敏+截断 message、`sites_http_exception` |
| `backend/app/main.py` | `_sites_raise` 改为委托 `sites_http_exception` |
| `backend/app/public_access.py` | 同上（同一缺陷的拷贝），移除未使用的 `HTTPException` |
| `backend/app/task_store_sync.py` | `SAFE_PROVIDER_CODES` 提升为公开名，保留 `_SAFE_PROVIDER_CODES` 别名 |
| `backend/tests/test_recovery.py` | +26 用例（脱敏判据矩阵 + 日志过滤器端到端） |
| `backend/tests/test_sites_errors.py` | 新增 8 个函数 / 23 个用例（含 code→status 全量钉桩） |
| `backend/tests/test_sites_mode_routes.py` | +2 路由级用例（含 secret 的异常被脱敏） |
| `backend/tests/test_public_access.py` | +1 端到端用例（`/api/session` 失败路径脱敏） |
| `frontend/tests/FullFlow.test.tsx` | mock 与 href 断言改为 `综述初稿.docx` |

提交：`fa08a97`（9 files, +272/−29，应用层与首轮测试）、`270ff6e`/`c943e52`（本报告）、
`0415ca4`（3 个测试文件，判据矩阵与 code 契约钉桩）。

## 六、分支状态与后续 rebase 预期（供主线验收参考）

- `sec-low` 仅本地分支，**无 upstream、未 push、未合并**；相对 `main` @ `83363f5` 为线性提交，工作区干净。
- 已核对与两条后续要 rebase 的分支的文件交集（`git diff --name-only main...<branch>`）：

  | 分支 | 与本分支的交集 | 具体位置 | 预期 |
  |---|---|---|---|
  | `task-expiry` | `backend/app/recovery.py` | 其对端为 `import` 行（~21）与 `run_recovery_cycle`/`schedule_due_retries`（~396-423）；本分支在 63-84、129-147、170-176 | **无重叠 hunk，自动合并** |
  | `progress-ux` | `backend/app/recovery.py`、`frontend/tests/FullFlow.test.tsx` | recovery 的对端在 `recover_interrupted_tasks`（~311-325）与 `schedule_due_retries`（~384-390）；FullFlow 的对端在 117/137（新增 progressbar 断言），本分支在 167-190 | **无重叠 hunk，自动合并**（同文件不同 hunk，间隔 >3 行上下文） |

- 唯一需要人工确认的是**语义**而非文本：`task-expiry` 改的是恢复调度的会话工厂，本分支改的是同一文件顶部的
  脱敏判据，互不影响；`progress-ux` 在 FullFlow 里加的是进度条断言，本分支改的是报告下载区 mock，也互不影响。
- 若 rebase 后 `test_recovery.py` 出现 import 冲突：本分支没有新增 import（`logging` 在该文件顶部原本就存在，
  `WorkerLogRedactionFilter` 在用例内部按现有风格 `from app.recovery import …`），取任一侧的 import 块均可。
