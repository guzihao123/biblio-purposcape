# 生产容器与 Function 兼容性验证报告

验证日期：2026-11-24（Asia/Shanghai）

源项目：`/Users/crisprcas_9/WorkBuddy/2026-11-06-20-49-06/purpose-landscape-web`

实际工作副本：`/Users/crisprcas_9/Documents/kimi/tasks/2026-11-24/08-49-16-99dfc61c/purpose-landscape-web`

日志目录：`/Users/crisprcas_9/Documents/kimi/tasks/2026-11-24/08-49-16-99dfc61c/logs`

> 首轮修改在工作副本完成；随后经主线哈希预检，允许的配置修复、开发文件及本报告已增量同步到源项目。同步未使用 `--delete`，未覆盖其他主线文件。未部署、未创建云资源、未修改应用业务源码，也未创建 `sites/functions/_qoder`。

## 1. 总结论

**静态配置检查和当前环境可执行的回归测试通过；生产 Docker 镜像、Web/worker 容器启动及 Deno Function 运行时兼容性仍未验证，不能宣称生产容器验收通过。**

- Docker：命令缺失，未执行 `docker compose config`、镜像构建或容器启动。
- Deno：命令缺失，未执行 `deno check` 或 Deno 测试。
- Redis：本地服务端和 CLI 均缺失，未进行真实 Redis PING 或 RQ 队列收发。
- Node：v24.22.1，可执行 Function 现有兼容测试及开发存储桩测试。
- Python：使用复制到工作区的项目 `.venv`，Python 3.9.6、pytest 8.4.2、FastAPI 0.128.8、redis 6.4.0、RQ 2.8.0。
- 未安装 Docker、Deno、Redis 或额外项目依赖，未进行无限重试。

## 2. 实际修改

| 文件 | 最小修改 | 原因与边界 |
| --- | --- | --- |
| `render.yaml` | worker 的 `dockerCommand` 改为 `python worker.py` | 与 Compose 统一入口，确保启动 RQ 前执行 `register_stage_services()`；原 `python -m rq worker ...` 绕过该项目入口。 |
| `docker-compose.yml` | Web 和 worker 的 `.env` 改为可选 `env_file` | 干净副本只有 `.env.example`，避免本地 `.env` 缺失阻断 Compose 读取。`env_file.required` 需要支持该语法的 Compose 版本，具体版本兼容性未实测。 |
| `Dockerfile` | APT 增加 `fontconfig`、`libgomp1`；在项目依赖安装前显式升级 `pip setuptools wheel` | 补齐字体、OCR 运行库和 PEP 517 构建工具声明；仅降低 `bdist_wheel` 缺失的不确定性，不代表 Docker 构建已经通过。 |
| `backend/tests/test_deployment_config.py` | 部署回归由 6 项扩展为 10 项 | 新增 worker 入口、Compose 可选 env、构建工具安装顺序、Redis/RQ 依赖、静态产物复制、PDF/OCR 系统依赖、公开入口和导入映射检查。 |
| `dev/import_map.json` | 新增开发导入映射 | 将 `sites/functions/index.ts` 的 `./_qoder/storage.mjs` 解析目标映射到 `dev/storage-stub.mjs`。 |
| `dev/storage-stub.mjs` | 新增内存存储桩 | 仅用于开发检查，实现 `upload`、`list`、`download`，不连接云服务。 |
| `task-container-validation-report.md` | 新增本报告 | 保存命令、结果和边界。 |

`.env.example` 经检查无需修改，保持原样。其 `QWEN_API_KEY`、`SESSION_SECRET`、`ADMIN_TOKEN`、`QODER_SITES_ORIGIN`、`WORKER_SHARED_SECRET` 均为空，未发现真实密钥。

## 3. 配置检查结果

| 检查项 | 结果 | 证据与限制 |
| --- | --- | --- |
| Compose / Render YAML 可解析 | 通过（静态） | PyYAML 成功解析；服务为 `web`、`worker`、`redis`。 |
| Web 与 worker 分离 | 通过（静态） | Compose 两个服务分别构建；Render 分别为 `type: web` 和 `type: worker`。 |
| RQ 启动入口一致 | 通过（静态） | Compose 和 Render 均为 `python worker.py`；回归检查注册阶段服务后启动 `Worker`。 |
| Redis 配置 | 通过（静态） | Web/worker 均为 `redis://redis:6379/0`，Redis 使用 `redis:7-alpine`；未做真实连接。 |
| 前端静态文件链路 | 通过（静态） | Dockerfile 包含 `npm ci`、`npm run build` 和 `COPY --from=frontend .../dist ./frontend/dist`；未生成或检查真实 `dist/index.html`。 |
| 中文字体 | 通过（声明检查） | 包含 `fontconfig`、`fonts-noto-cjk`；未执行 Linux `fc-match :lang=zh-cn`。 |
| PDF / OCR | 通过（声明检查） | Python 依赖包含 `pypdfium2`、`rapidocr`、`onnxruntime`、`Pillow`、`cairosvg`；系统依赖包含 `libgl1`、`libglib2.0-0`、`libcairo2`、`libgomp1`；未做 Linux 导入、PDF 渲染或 OCR 推理。 |
| 公开入口 | 通过（静态） | `.env.example` 和 Dockerfile 默认 `VITE_API_BASE_URL=/functions/v1/app`，Function 路由 marker 未改变。 |
| Function Node 兼容行为 | 通过 | 5 项现有测试通过；覆盖会话转发、Cookie、回答路由、二进制下载和 worker 存储授权。不是 Deno 运行结果。 |
| 开发存储映射 | 通过（静态 + Node 桩） | 回归验证映射两端路径；`_qoder` 目录仍不存在。存储桩的上传、列表、下载及 4 字节内容往返通过。 |
| Deno 类型与导入映射 | 未验证 | Deno 缺失，不能声称 `deno check` 或 Deno 测试通过。 |
| 后端完整回归 | 通过 | 224 passed、1 skipped；跳过项为需 `RUN_LIVE_OPENALEX_SMOKE=1` 的 OpenAlex 联网冒烟测试。 |

## 4. 实际执行的命令与结果

为便于阅读，下文 `$ROOT` 代表实际工作副本，`$LOG` 代表上述日志目录；工具调用中使用的是对应的绝对路径。

### 4.1 环境探测

```bash
for tool in docker deno python3 rsync git; do
  if command -v "$tool" >/dev/null 2>&1; then
    "$tool" --version
  else
    echo "$tool: MISSING"
  fi
done
docker compose version

for tool in node npm redis-server redis-cli; do
  if command -v "$tool" >/dev/null 2>&1; then
    "$tool" --version
  else
    echo "$tool: MISSING"
  fi
done
```

关键输出：

```text
docker: MISSING
deno: MISSING
Python 3.12.16
git version 2.54.0 (Apple Git-157)
/bin/bash: docker: command not found
v24.22.1
11.12.1
redis-server: MISSING
redis-cli: MISSING
```

因此没有执行或伪造以下命令的结果：`docker compose config`、`docker compose build`、`docker compose up`、`deno check`、`deno test`。

### 4.2 修改前回归

在 `$ROOT` 执行：

```bash
node --test sites/functions/forward.test.mjs sites/functions/routes.test.mjs \
  2>&1 | tee "$LOG/function-node-before.log"

.venv/bin/python -m pytest -q backend/tests/test_deployment_config.py \
  2>&1 | tee "$LOG/deployment-tests-before.log"
```

结果：

```text
Function Node: tests 5, pass 5, fail 0
Deployment config: 6 passed in 0.02s
```

这些旧测试未覆盖本次发现的 worker 入口、可选 `.env` 和开发导入映射问题，因此修改前通过不代表配置完整。

### 4.3 修改后部署、YAML 与 Function 检查

在 `$ROOT` 执行：

```bash
.venv/bin/python -m pytest -q backend/tests/test_deployment_config.py \
  2>&1 | tee "$LOG/deployment-tests-after.log"

node --test sites/functions/forward.test.mjs sites/functions/routes.test.mjs \
  2>&1 | tee "$LOG/function-node-after.log"
```

结果：

```text
..........                                                               [100%]
10 passed in 0.03s

Function Node: tests 5, pass 5, fail 0
```

YAML 结构与入口检查：

```bash
.venv/bin/python -c "import pathlib,yaml; root=pathlib.Path('.'); compose=yaml.safe_load((root/'docker-compose.yml').read_text()); render=yaml.safe_load((root/'render.yaml').read_text()); assert compose['services']['web']['env_file']==[{'path':'.env','required':False}]; assert compose['services']['worker']['env_file']==[{'path':'.env','required':False}]; assert compose['services']['worker']['command']=='python worker.py'; services={s['name']:s for s in render['services']}; assert services['landscape-worker']['dockerCommand']=='python worker.py'; assert services['landscape-web']['healthCheckPath']=='/api/health'; print('compose_and_render_yaml: ok'); print('services:', ', '.join(compose['services'])); print('render_worker:', services['landscape-worker']['dockerCommand'])"
```

输出：

```text
compose_and_render_yaml: ok
services: web, worker, redis
render_worker: python worker.py
```

开发存储桩行为检查：

```bash
node --input-type=module -e 'import assert from "node:assert/strict"; import { storage } from "./dev/storage-stub.mjs"; const name = "artifacts/task-1/report.docx"; await storage.upload(name, new Uint8Array([80,75,3,4]), { contentType: "application/test" }); const entries = await storage.list("artifacts/task-1"); assert.equal(entries.length, 1); assert.equal(entries[0].metadata.size, 4); const response = await storage.download(name); assert.equal(response.headers.get("content-type"), "application/test"); assert.deepEqual(new Uint8Array(await response.arrayBuffer()), new Uint8Array([80,75,3,4])); console.log("storage stub round-trip: ok");'
```

输出：

```text
storage stub round-trip: ok
```

### 4.4 完整后端回归

```bash
.venv/bin/python -m pytest -q 2>&1 | tee "$LOG/backend-full-after.log"
```

输出：

```text
........................................................................ [ 32%]
........................................................................ [ 64%]
......................s................................................. [ 96%]
.........                                                                [100%]
224 passed, 1 skipped in 8.00s
```

跳过原因位于 `backend/tests/test_search.py`：真实 OpenAlex 冒烟测试默认关闭，离线测试不访问网络。

### 4.5 本地 Python 打包探针（无结论，不是镜像构建）

为检查 Dockerfile 中 `pip install .` 的目录发现风险，曾在日志目录的临时副本中执行：

```bash
.venv/bin/python -m pip wheel --no-deps --no-build-isolation --no-cache-dir \
  --wheel-dir "$LOG/wheel-before" "$LOG/package-check-before"

.venv/bin/python -m pip wheel --no-deps --no-build-isolation --no-cache-dir \
  --wheel-dir "$LOG/wheel-after" "$LOG/package-check-after"
```

两个探针均退出 1，关键日志为：

```text
error: invalid command 'bdist_wheel'
```

原因是项目旧虚拟环境缺少对应 wheel 构建命令；两次探针均未形成对 Docker `pip install .` 是否成功的有效结论。没有安装额外构建工具或继续重试，也没有因此修改打包顺序。完整输出见 `package-before.log` 和 `package-after.log`。**这些日志不是 Docker 构建日志，不能用作镜像成功或失败证据。**

## 5. 构建日志说明

本次没有生产镜像构建日志，因为 Docker 命令不存在。也没有 Web、worker、Redis 容器启动日志。

现有日志索引：

| 日志 | 内容 |
| --- | --- |
| `function-node-before.log` / `function-node-after.log` | 修改前后各 5 项 Function Node 测试。 |
| `deployment-tests-before.log` / `deployment-tests-after.log` | 修改前 6 项、修改后 10 项部署回归。 |
| `yaml-static-after.log` | Compose / Render YAML 静态断言。 |
| `storage-stub-node.log` | 开发存储桩字节往返。 |
| `backend-full-after.log` | 完整后端 224 项通过、1 项跳过。 |
| `package-before.log` / `package-after.log` | 无结论的本地打包探针，均因 `bdist_wheel` 缺失失败。 |
| `before-sha256.json` / `file-audit-before-cleanup.json` | 文件修改范围审计；测试缓存已在审计后清理。 |

## 6. 未验证边界与后续必做项

1. **Compose 实际解析**：需在支持 `env_file.required` 的 Docker Compose 版本执行 `docker compose config`；当前未验证该版本要求。
2. **镜像构建**：需实际构建 Web 和 worker 镜像，确认 `npm ci`、前端 TypeScript/Vite 构建、`pip install .`、APT 依赖安装全部成功。
3. **Web / worker 启动**：需实际启动 Redis、Web 和 worker，检查健康接口、进程存活、worker 注册及日志。
4. **Redis / RQ**：需真实 Redis PING、RQ 入队/消费和失败重试验证；fakeredis 单元测试不覆盖该边界。
5. **前端静态产物**：需确认 `/app/frontend/dist/index.html` 及引用资源存在，并验证实际托管链路可访问。
6. **中文字体**：需在 Linux 镜像执行 `fc-match :lang=zh-cn`，并生成含中文的实际交付物检查字体。
7. **PDF / OCR**：需在 Linux 镜像导入 `pypdfium2`、`rapidocr`、`onnxruntime`、`PIL`、`cairosvg`，并进行 PDF 页面渲染和扫描页 OCR 冒烟。
8. **Deno Function**：需执行 `deno check --import-map=dev/import_map.json sites/functions/index.ts`，并在目标 Deno 版本运行 Function 测试。Node 24 结果不能替代此步骤。
9. **生产存储适配器**：开发桩不验证 Qoder 生产 `_qoder/storage.mjs` 的真实接口或云端权限；发布包仍须由目标平台提供该适配器，不能在仓库伪造 `_qoder`。
10. **外部服务与公开地址**：未访问 OpenAlex、模型服务、Render 或 Qoder Sites，未验证真实公开 URL、环境变量和密钥注入。

## 7. 文件范围审计

修改前对 964 个文件建立 SHA-256 基线。测试后、清理缓存前的审计仅显示：

- 修改：`Dockerfile`、`docker-compose.yml`、`render.yaml`、`backend/tests/test_deployment_config.py`。
- 新增：`dev/import_map.json`、`dev/storage-stub.mjs`，以及 pytest 生成的 `.pytest_cache`。
- 删除：无。
- `.pytest_cache` 已清理；本报告为允许的最后一个新增文件。
- `.venv` 是从源项目复制的既有测试环境，不属于源码修改。
- `sites/functions/_qoder` 始终不存在。


## 8. 最终增量同步与构建工具补充

### 8.1 主线预检

同步前重新复制源项目的受控文件，并与首轮 SHA-256 基线比较。`Dockerfile`、`docker-compose.yml`、`render.yaml`、`.env.example`、`worker.py`、`backend/tests/test_deployment_config.py` 和 `sites/functions/index.ts` 均未发生主线变化，因此不需要三方合并。源项目最初不存在两个 `dev` 文件及本报告。

预检结果保存于 `sync-preflight.json`。同步只针对下文列出的文件，没有使用 `--delete`，没有覆盖其他业务或主线改动。

### 8.2 构建工具修复

`Dockerfile` 当前顺序为：

```dockerfile
RUN pip install --no-cache-dir --upgrade pip setuptools wheel
RUN pip install --no-cache-dir .
```

部署测试新增顺序断言，确保构建工具安装位于项目安装之前。该项只消除本地旧工具链暴露的构建不确定性；未执行 Docker 构建，不声称镜像构建通过。

实际执行：

```bash
.venv/bin/python -m pytest -q backend/tests/test_deployment_config.py \
  2>&1 | tee "$LOG/deployment-tests-sync.log"
```

结果：

```text
..........                                                               [100%]
10 passed in 0.07s
```

### 8.3 同步到源项目的最终文件清单

修改：

- `Dockerfile`
- `docker-compose.yml`
- `render.yaml`
- `backend/tests/test_deployment_config.py`

新增：

- `dev/import_map.json`
- `dev/storage-stub.mjs`
- `task-container-validation-report.md`

保持不变：

- `.env.example`
- `worker.py`（Render 与 Compose 均继续通过 `python worker.py` 使用其已保留的真实 RQ 启动逻辑）
- 所有应用业务源码及 `sites/functions/_qoder`（后者仍未创建）

前 6 个配置／开发文件同步后已回读到工作区，并与工作副本逐一进行 SHA-256 校验，全部一致。结果保存于 `sync-verification.json`；实际同步输出保存于 `incremental-sync.log`。本报告随后按同一路径单独同步。

### 8.4 最终边界

本次同步没有新增任何 Docker、Deno、Linux 容器、真实 Redis、字体、PDF/OCR 或 Function 导入映射运行时结果。所有相关验收仍按第 6 节留待具备对应环境后执行；未继续安装、重试、部署或创建云资源。
