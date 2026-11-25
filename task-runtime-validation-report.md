# 最新配置真实运行时验收报告

日期：2026-11-24（Asia/Shanghai）

## 1. 验收对象与结论

- 来源目录：`/Users/crisprcas_9/WorkBuddy/2026-11-06-20-49-06/purpose-landscape-web`
- 实际验收工作区：`/Users/crisprcas_9/Documents/kimi/tasks/2026-11-24/09-42-52-a0586535/purpose-landscape-web`
- 原目录在验收期间被其他流程持续更新；已于 2026-11-24 09:58:54 CST 重同步，并在 10:15:08 CST 冻结最终业务与 worker 快照、重跑关键检查。
- 冻结时，`frontend/src`、`backend/app`、`sites/functions` 与来源目录一致；本次没有修改业务源码。冻结后来源目录的后续变化不属于本报告验收范围。
- 本机可执行的核心检查通过：真实 Web 健康检查、真实 Redis/RQ 入队执行、worker 阶段注册、SQLite、前端生产构建、PDF 渲染与中文 OCR。
- **Docker、Deno、容器内 Noto 字体和实际镜像内容没有完成运行时验证。** 当前主机没有 Docker 或 Deno，本报告不声称镜像构建、容器启动或 Deno Function 验收通过。
- 未部署、未创建云资源、未执行 `prepare_site` 或 `publish_site`。

## 2. 本次实际变更

1. `Dockerfile`
   - 将前端构建阶段的 `COPY frontend/ ./` 改为显式复制构建所需的 HTML、配置、`src` 和 `tests`。
   - 原因是原写法会把已有的 `frontend/.motion-preview.db` 带入中间构建阶段。
   - 保留 `npm ci`、`npm run build`、`ARG VITE_API_BASE_URL=/functions/v1/app`、最终 dist 复制、Noto/Cairo 等 Linux 依赖、`python worker.py` 兼容入口，以及先升级 `pip setuptools wheel` 再安装项目的顺序。
2. `backend/tests/test_deployment_config.py`
   - 新增静态保护：禁止宽泛的前端目录复制以及 `.env`、根目录 `test.db` 的 Docker 复制。
3. 新增部署验收辅助文件：
   - `backend/tests/runtime_acceptance.py`
   - `backend/tests/runtime_probe.py`
4. 新增本报告及验收日志。`docker-compose.yml`、`render.yaml`、`dev/import_map.json`、`dev/storage-stub.mjs` 保持同步后的最新内容，本次未另行修改。

## 3. 工具可用性与停止边界

实际检查记录：`dev/runtime-validation/toolchain.json`。

| 检查 | 实际结果 | 后续动作 |
|---|---|---|
| `docker compose config` | 退出 127，`No such file or directory: 'docker'` | 停止 Docker 部分；未执行构建和启动，不声称通过 |
| `deno run --allow-env --allow-net --import-map=dev/import_map.json sites/functions/index.ts` | 退出 127，找不到 Deno | 停止 Deno 运行时部分；仅做静态检查和 Node 逻辑测试 |
| Node | `v24.22.1` | 用于前端构建和 Function 本地逻辑测试 |
| npm | `11.12.1` | 用于 `npm ci`、构建和测试 |
| 项目 Python | `3.9.6` | 用于 Web、RQ、SQLite、PDF/OCR 验收 |
| Redis | `redislite` 提供的真实 Redis `6.2.14` | 用于真实 RQ 队列，不是 fakeredis |

因此，以下命令**没有成功执行，也没有被当作成功证据**：`docker compose build`、`docker compose up`、容器内 `fc-list`、容器内密钥/数据库扫描、Deno import map 实际解析。

## 4. 实际命令、日志与结果

### 4.1 部署配置静态回归

```bash
.venv/bin/python -m pytest backend/tests/test_deployment_config.py -q
```

结果：`12 passed in 0.02s`。日志：`dev/runtime-validation/deployment-tests.log`。

覆盖 Web/worker/Redis 配置分离、可选 `.env`、`python worker.py`、阶段注册、Linux 运行依赖、前端 dist、PDF/OCR/RQ 依赖、`setuptools`/`wheel` 构建声明、后端包发现、Sites Function 路由和存储桩边界。

### 4.2 Docker 前端阶段的等价输入构建

按修改后的 Dockerfile 显式复制清单，在 `dev/docker-frontend-stage` 建立干净阶段目录，然后执行：

```bash
npm ci
VITE_API_BASE_URL=/functions/v1/app npm run build
```

结果：

- 构建成功，`44 modules transformed`。
- 阶段 dist 与主前端生产 dist 完全一致。
- 排除依赖和 dist 后共检查 36 个阶段输入，没有 `.env*` 或数据库文件。

证据：

- `dev/runtime-validation/docker-frontend-stage.log`
- `dev/runtime-validation/docker-frontend-stage-results.json`

这证明精简后的复制清单足以完成前端构建，**不等价于 Docker 镜像构建成功**。

### 4.3 Web、真实 Redis、RQ worker 与 SQLite

```bash
.venv/bin/python backend/tests/runtime_acceptance.py
```

该脚本启动真实 Redis、Uvicorn 和原始的 `python worker.py` 入口，通过 RQ 的 `landscape` 队列执行部署探针，并在结束时关闭本次启动的进程。

实际结果：

```text
Redis PING: true
GET /api/health: HTTP 200
health body: {"status":"ok","database":"ok","worker":"ready"}
RQ job fbd26cb8-b06f-4738-8420-f01aed8c6418: finished
queue: landscape
worker 内 registered_stages: ["generate", "search"]
SQLite bytes: 110592
PRAGMA integrity_check: ok
artifact directory exists: true
passed: true
```

worker 日志包含：

```text
*** Listening on landscape...
landscape: backend.tests.runtime_probe.runtime_worker_probe()
Successfully completed ... job ...
landscape: Job OK
```

证据：

- `dev/runtime-validation/results.json`
- `dev/runtime-validation/web.log`
- `dev/runtime-validation/worker.log`
- 测试数据库仅位于 `dev/runtime-validation/data/tasks.db`，没有放入 Sites 发布候选目录。

### 4.4 前端 dist

主前端执行：

```bash
VITE_API_BASE_URL=/functions/v1/app npm run build
npm test
```

结果：

- 生产构建成功，TypeScript 检查通过。
- `7` 个测试文件、`22` 项测试全部通过。
- 产物：`dist/index.html`、`dist/assets/index-D6_JMkZa.js`、`dist/assets/index-vFCp4sQM.css`。
- dist 哈希清单：`dev/sites-validation/dist-manifest.json`。

### 4.5 PDF 渲染与真实 OCR

```bash
.venv/bin/python -m pytest backend/tests/test_fulltext.py -q
```

结果：`26 passed`。

另外实际生成一页扫描型 PDF，使用项目的 `pypdfium2` 渲染为 PNG，再运行 RapidOCR/ONNXRuntime。最终输出：

```text
研究图谱中文识别
Purpose Landscape OCR 2026
```

结果：英文和中文标记均识别成功，`passed: true`。

证据：

- `dev/runtime-validation/pdf-ocr.log`
- `dev/runtime-validation/pdf-ocr/results.json`
- 测试图像使用 macOS 的 Arial Unicode 字体；这不是 Noto 容器字体证据。

### 4.6 Sites Function 的本地逻辑检查

```bash
node --test sites/functions/*.test.mjs
```

结果：`17` 项通过、`0` 失败。覆盖会话转发、任务路由、二进制下载、Storage 字节往返、任务存储、幂等、owner 隔离和 Python worker 客户端。

这些测试不是 Deno 运行时验证；真实 Provider 权限、数据库原子性和 import map 解析仍未验证。没有创建 `sites/functions/_qoder`。

## 5. 要求逐项判定

| 要求 | 判定 | 证据与边界 |
|---|---|---|
| `docker compose config`、构建、启动 Web/worker/Redis | **未验证（环境阻塞）** | Docker 不存在，退出 127；未声称构建或启动通过 |
| `/api/health` | **本机通过** | HTTP 200，数据库与 Redis 状态正常；容器未验证 |
| 真实 RQ 入队执行 | **本机通过** | 真实 Redis 6.2.14、RQ `finished`；不是 fakeredis，未调用外部模型 |
| worker 启动注册 | **通过** | 执行队列任务的 worker 进程内返回 `generate`、`search` |
| 前端 dist | **通过** | 主构建与 Dockerfile 等价阶段构建均成功，dist 一致 |
| Noto 中文字体 | **容器内未验证** | Dockerfile 静态包含 `fonts-noto-cjk`；无 Docker，宿主也无 `fc-list` |
| PDF/OCR | **本机通过，容器未验证** | 26 项回归及真实中文 OCR 通过 |
| SQLite 数据目录 | **本机通过，部署环境未验证** | 本地目录和数据库创建成功、完整性 `ok`；Compose `/data` 仅静态核对 |
| 保留 `python worker.py` | **通过** | 实际以此入口启动 worker |
| 可选 `.env` | **静态通过** | Compose 两处均为 `path: .env`、`required: false`；未做 Compose 解析实测 |
| `setuptools`/`wheel` 构建依赖 | **静态通过，本机附加构建失败** | Dockerfile 和 pyproject 声明保留；详见下节 |
| 容器无真实密钥、`.env`、测试数据库 | **静态复制闭包通过，实际镜像未验证** | 未发现已知密钥模式或禁用文件；不能替代镜像内扫描 |

静态镜像复制闭包证据：`dev/runtime-validation/docker-static-results.json`。修改后的 Dockerfile 不再把前端测试数据库带入中间阶段；最终阶段的静态复制闭包中未发现 `.env*`、`.db`/`.sqlite*`、`node_modules`、`_qoder` 或已知密钥模式。

## 6. 失败项与未验证边界

1. **Docker 全部运行时项未验证**：没有 `docker compose config` 成功结果，没有镜像，没有容器日志，没有 Redis 7 容器实测。
2. **Deno Function 未验证**：`dev/import_map.json` 与 `dev/storage-stub.mjs` 只完成静态检查；Node 测试不能替代 Deno。
3. **Noto/Cairo Linux 运行时尚未验证**：宿主机直接 `import cairosvg` 退出 1，因为没有系统 Cairo；日志为 `dev/runtime-validation/host-cairo.log`。Dockerfile 安装了 `libcairo2`，但镜像内效果未知。
4. **附加本地 wheel 构建失败**：执行

   ```bash
   .venv/bin/python -m pip wheel --no-build-isolation --no-deps --no-cache-dir \
     --wheel-dir dev/runtime-validation/wheel .
   ```

   验收虚拟环境为 setuptools `58.0.4` 且未安装 wheel，日志最终为 `error: invalid command 'bdist_wheel'`。这不是 Docker 构建失败证据，也不能记为本地 wheel 构建通过。日志：`dev/runtime-validation/python-wheel.log`。
5. **Render 未部署**：`render.yaml` 仅静态检查；生产 SQLite 持久性、Web/worker 数据访问方式、密钥注入和持久存储均未做云端验证。
6. **完整业务阶段未执行**：RQ 探针证明真实队列和 worker 注册，不调用外部检索、模型或付费服务，也不声称完整研究生成流程已在 Docker 中跑通。
7. 验收期间来源目录发生过并发更新；本报告只对应上述工作区中最终同步并修改后的快照。

## 7. 清理与交付边界

- 本次启动的 Uvicorn、worker 和 Vite preview 均已停止；worker 正常退出，Web 由验收脚本发送 SIGTERM。
- 未停止来源目录中原本存在的其他服务。
- 未创建 `_qoder`，未部署，未创建云资源。
- 业务源码未改；允许范围外的依赖清单没有因本机环境问题而被修改。
