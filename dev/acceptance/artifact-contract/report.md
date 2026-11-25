# 制品契约本地只读验收报告

> **状态说明**：首轮验收（27/32，5 项不一致）在 `artifact-contract` 分支完成，下文即该轮记录。`artifact-fixes` 分支修复后重跑同一套脚本为 **32/32 通过**，见本目录 `result.json`；5 项修复详见提交信息与 `backend/tests/test_sites_store_contract.py`、`sites/functions/artifact_contract.test.mjs`。

- 仓库：`purpose-landscape-web`，独立 worktree `purpose-landscape-web-artifact-contract`，分支 `artifact-contract`（基于 `main@83363f5`）。
- 范围：worker（Python `SitesStorageClient`）→ 站点函数（`sites/functions/index.ts`，Deno）→ web（前端 `artifactUrl`）。
- 只读：未改生产代码、未部署、未 push、未连线上 Qoder/Render。本目录以外没有任何改动。
- 时间：2026-11-25。环境：macOS / Deno 2.9.8 / Python 3.13.12。

## 结论

真实代码、真实客户端、真实 Deno 服务端跑通 32 项检查，**27 项通过、5 项不一致**。主链路（PUT 201 → 校验和 → 列表 → 下载字节一致 → 403/404/405/422 拒绝）在三种网关前缀下全部成立；问题集中在**错误码映射**和**列表前缀匹配**，均为小改动可修，不影响已有成功路径。

| 严重度 | 问题 | 位置 |
|---|---|---|
| 高 | 非 JSON 的网关错误页被客户端当成成功 | `backend/app/sites_store.py:63-75,94-99` |
| 中 | 列表前缀碰撞，`task-1` 列出 `task-10` 的文件名（且名字变形为 `/b.txt`） | `sites/functions/index.ts:213-218` |
| 中 | 不存在的制品/校验和返回 500 而非 404 | `sites/functions/index.ts:245,261` |
| 中 | 超过 50MB 的上传返回 500 而非 413 | `sites/functions/index.ts:227` |
| 低 | 任意路径只要内含 `/functions/v1/app` 就被剥离成内部路由 | `sites/functions/index.ts:48-50` |

## 复跑

```bash
cd <worktree>/dev/acceptance/artifact-contract
./start_and_check.sh              # 生产同款入口 index.ts 跑在 :8000，含 50MB 探针
SKIP_LARGE=1 ./start_and_check.sh # 跳过 50MB，约 3 秒
PORT=8012 ./start_and_check.sh    # 指定端口
ORIGIN=http://127.0.0.1:8000 ./start_and_check.sh  # 复用已在跑的服务，不再启停
```

脚本自起 Deno、等健康检查、跑完 `contract_checks.py` 和 `origin_probe.py`，`trap` 保证退出时杀掉自己起的 Deno（已实测无残留进程、8000 端口释放）。产物：`result.json`（逐项期望/实际）、`origin_probe.json`、`logs/deno-<port>.log`。

### 端口说明（8000 被占用）

`sites/functions/index.ts:195` 是 `Deno.serve(handler)`，默认端口写死 8000 —— **实测 `PORT` 环境变量无效**（Deno 2.9.8 仍监听 8000），`deno run` 也没有 `--port`。所以脚本走两条路：

- 8000 空闲：直接跑 `index.ts`，与线上一致；
- 8000 被占：自动顺延端口，改用本目录的 `port_launcher.ts` 包装 `Deno.serve` 注入端口后再 `import` 同一个 `index.ts`，**不修改生产代码**。已实测在 8001 上全套通过（除需跳过 50MB 的那一项）。

另有 macOS 细节：另一进程占 `127.0.0.1:8000` 时，Deno 绑 `0.0.0.0:8000` 仍可能成功，路由会变得不确定——所以脚本宁可换端口也不复用被占端口。

## 1. 三种前缀（curl + 原始 HTTP）

Deno 侧 `routeSuffix`（`index.ts:44-62`）先按最后一个 `/functions/v1/app` 截断，再循环剥离 `/app` 或 `/app-<hash>`：

| 请求路径 | 结果 |
|---|---|
| `/health` | 200 |
| `/functions/v1/app/health` | 200 |
| `/app/health` | 200 |
| `/app-abc123/health` | 200 |
| `/functions/v1/app/app-x9/health` | 200 |
| `/app-x9/functions/v1/app/health` | 200 |

制品内部路由在四种前缀组合下均返回 200 且字节一致：`/functions/v1/app/...`（PUT，201）、`/app/...`、`/app-a1b2c3/...`、`/functions/v1/app/app-<hash>/...`、`/app-<hash>/functions/v1/app/...`。校验和与列表同样跨前缀可用。

Python 客户端只用 `/functions/v1/app/...`（`sites_store.py:80,85,159`），所以线上若网关挂载在 `/app-<hash>/`，**由网关负责把该前缀映射到函数**；函数自身两种前缀都能吃，这一点已被实测覆盖。

## 2. 真实客户端回环（`SitesStorageClient`）

| 检查 | 结果 |
|---|---|
| `put_bytes` → `{'ok': True, 'name': ..., 'size': 44}` | 通过（原始 HTTP 确认状态码 201） |
| `get_bytes` 下载字节与上传一致，且内部校验 SHA-256 | 通过 |
| `list` 返回 `name`/`size` | 通过 |
| 中文文件名 `文献图谱仪表盘.png` 往返 | 通过（`quote(safe="")` 与 `decodeURIComponent` 对齐） |
| 错误 secret → `StorageError` | 通过（服务端 403 `worker_unauthorized`） |
| >50MB 客户端侧拦截 → `ValueError` | 通过（不发网络请求） |

注意：客户端丢弃了 HTTP 状态码（`_request` 只返回 body，`sites_store.py:70-75`），"201" 只能靠原始 HTTP 观测；这直接导致下面 F1。

## 3. 安全与边界

| 检查 | 实际 |
|---|---|
| 错误 token GET / 缺失 token PUT | 403 `worker_unauthorized` |
| `..%2Fsecret`、`%2e%2e%2fsecret`、`a%5Cb`、`%2E%2E` | 均 404（`decodeURIComponent` 后命中 `index.ts:178` 的过滤） |
| 65 字符 task id（超 `{1,64}`） | 404 |
| POST/DELETE 制品、PUT 校验和、POST 集合 | 405 |
| `X-Artifact-SHA256` 不匹配 | 422 `artifact_checksum_mismatch` |

## 4. Origin 头：实测与边界

用本地捕获服务器接住 `SitesStorageClient` 的真实 urllib 请求，抓到的头：

```
Origin: http://127.0.0.1:55614      <- 由 _call 的 setdefault 发出（sites_store.py:90）
X-Worker-Token: test-secret
Content-Type: application/octet-stream
X-Artifact-Sha256: ba9c736f...
```

- **Python 客户端确实发送 `Origin`**，值等于构造时的 `origin`；调用方显式传入的 `Origin` 会被保留（`setdefault` 语义，实测 `https://caller.example` 原样到达）。
- **站点函数本身完全不校验 Origin**：`sites/functions/index.ts` 全文只有 `apiOrigin()` 读 `PYTHON_API_ORIGIN`，没有任何 Origin 判断。用 `Origin: https://evil.example` 携带正确 token PUT，仍返回 **201**。
- 因此 **网关的 Origin 校验只能在线上验证**，本地无法覆盖。边界：若线上 `QODER_SITES_ORIGIN` 配成内部主机名而非站点对外域名，网关可能拒绝——这一点本次不验证。

## 5. 发现与最小修复建议（均未改生产代码）

### F1（高）非 JSON 的网关错误页被当成成功

`backend/app/sites_store.py:70-75` 只在 `content-type` 含 `application/json` 时解析并**丢弃状态码**，否则返回 `{'body':..., 'content_type':...}`；`:94-99` 的失败判定只能看 `ok`/`error`/`status` 三个键，此时三者都不存在，于是 `int(result.get('status', 200)) >= 400` 恒为假 → **403/502 的 HTML 错误页被判定为上传成功**。

实测：stub transport 返回 `<html>502 Bad Gateway</html>`，`put_bytes` 正常返回不抛错。

影响：worker 会认为远端已落盘，后续下载才发现缺失；生产网关（Render/Qoder）返回 HTML 错误页的路径真实存在。

最小修复：`_request` 把状态码带进结果，`:94-99` 现成逻辑即可生效。

```python
with urllib.request.urlopen(...) as response:
    body = response.read()
    status = response.status
    content_type = response.headers.get('content-type', '')
if options.get('response_mode') != 'bytes' and 'application/json' in content_type:
    return {'status': status, **json.loads(body.decode('utf-8'))}
return {'status': status, 'body': body, 'content_type': content_type}
```

### F2（中）列表前缀碰撞，跨任务泄漏文件名且名字变形

`index.ts:213` 用 `storage.list('artifacts/<taskId>')`，`:216` 用 `entry.name.slice(prefix.length + 1)` 取文件名。前缀是纯字符串匹配，`artifacts/task-1` 会命中 `artifacts/task-10/b.txt`，切片后得到 `/b.txt`。

实测：`list('task-1')` 返回 `['/b.txt', 'a.txt']`，期望 `['a.txt']`。

影响：`task-1` 能看到 `task-10` 的文件名（跨任务元数据泄漏），且返回的 `name` 形如 `/b.txt`，下游拿它拼下载路径会再次变形。

最小修复（`index.ts:212-218`）：

```ts
const entries = (await storage.list(prefix, { limit: 1000, offset: 0 }))
  .filter((entry) => entry.name.startsWith(`${prefix}/`));
```
`name` 的切片保持 `slice(prefix.length + 1)` 即可，过滤后不会再出现 `/b.txt` 这类变形。

### F3（中）不存在的制品/校验和返回 500 而非 404

`index.ts:245`、`:261` 直接 `await storage.download(...)`，未捕获。Deno 日志：

```
Error: object not found: artifacts/accept-task-01/does-not-exist.bin
    at Object.download (dev/acceptance/sites-live/stubs/storage-stub.mjs:39:23)
    at .../sites/functions/index.ts:245:34
```

实测两者均返回 500 `Internal Server Error`。`get_bytes` 会把校验和 500 转成 `ArtifactIntegrityError('remote artifact checksum is unavailable')`，语义上还算可接受；但制品 500 会让 worker 把"不存在"误判为"服务故障"，触发无谓重试。

最小修复：两处 `download` 包 `try/catch`，未命中返回 `json({ error: 'artifact_not_found' }, 404)`。

### F4（中）超过 50MB 上传返回 500 而非 4xx

`index.ts:227` 的 `await requestBody(request)` 未捕获 `RequestBodyTooLargeError`（`:125` 抛出），异常直接冒泡出 `Deno.serve`。Deno 日志：

```
RequestBodyTooLargeError: request_too_large
    at requestBody (.../index.ts:125:39)
    at .../index.ts:227:26
```

实测 50,000,001 字节 PUT → **500**。对比答案路由 `:288-292` 已有同样捕获并返回 413，说明这是漏写而非设计。

最小修复（与 `:288-292` 同构）：

```ts
let body: Uint8Array<ArrayBuffer>;
try {
  body = await requestBody(request);
} catch (error) {
  if (error instanceof RequestBodyTooLargeError) return json({ error: 'request_too_large' }, 413);
  throw error;
}
```

### F5（低）路径标记可出现在任意位置

`index.ts:48-50` 用 `lastIndexOf('/functions/v1/app')`，因此 `/evil/functions/v1/app/health` 也返回 200（实测），即任意前缀都能到达内部路由。内部路由仍需 `X-Worker-Token`，风险有限；但若网关将来对函数做 catch-all 路由，内部面会被放大。

最小修复：只接受"开头即标记"或已知前缀集合，其余 404：

```ts
if (path.startsWith('/functions/v1/app')) path = path.slice(marker.length) || '/';
```

## 6. 未覆盖 / 明确边界

| 项 | 状态 |
|---|---|
| 网关 Origin 校验、Qoder 平台鉴权 | **未验证**，只能线上；函数侧已确认不做校验 |
| 真实 Qoder storage 驱动 | 未验证，用 `dev/acceptance/sites-live/stubs/storage-stub.mjs`（内存实现，`download` 未命中抛错） |
| 真实平台 `list` 是否返回带前缀的 `name` | 未验证，同上 |
| 真实 50MB 上限拦截点（网关 vs 函数） | 本地只看到函数返回 500；线上可能被网关先拒 |
| web 端到站点的实际前缀 | 依赖 `VITE_API_BASE_URL`（`frontend/src/api.ts:66-71`），线上需确认配成 `/functions/v1/app`；`/api/...` 直连函数会 404（已实测） |
| TLS / Render / 网络抖动 | 未验证 |

## 7. 观察（非缺陷，供决策）

- `SitesStorageClient` 不暴露状态码，"必须 201" 无法在客户端断言；若后续要给 F1 补测试，需先让 `_request` 返回状态码。
- 函数不校验 `Origin`、只校验 `X-Worker-Token`，二者职责分离清晰；但客户端把 `Origin` 设为"自身 origin"，若该值与站点对外域名不一致，线上会被网关拒——建议在 `render.yaml`/部署说明里固化 `QODER_SITES_ORIGIN` 必须等于站点公开域名。
- `task_store.ts` 方向的路由（`/internal/task-store/*`）本次未纳入矩阵，属另一条契约。
