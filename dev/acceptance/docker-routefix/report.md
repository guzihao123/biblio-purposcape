# routefix 生产镜像验收报告

- 验收时间：2026-11-25 12:52–13:03（GMT+8）
- 仓库：`/Users/crisprcas_9/WorkBuddy/2026-11-06-20-49-06/purpose-landscape-web`
- 范围：只读源码核验；未修改仓库源码、未 `docker push`、未部署、未改 `render.yaml`
- 目标镜像：`biblio-purposcape:routefix`

## 1. 构建成功与镜像大小

初始状态：`docker image inspect biblio-purposcape:routefix` 返回 `No such image`；主线后台日志 `/tmp/pl-docker-build.log` 与本次直接构建均停在 `RUN pip install --no-cache-dir --upgrade pip setuptools wheel`，宿主机 `curl https://pypi.org/simple/wheel/` 返回 502，根因是代理拦截 PyPI，不是代码问题。

环境绕行（**未改仓库文件**）：在仓库外建立 `/tmp/pl-routefix-dockerfile/Dockerfile`，内容与仓库 `Dockerfile` 完全一致，仅增加一行 `ARG PIP_INDEX_URL`；把本机 localhost 代理映射为 `host.docker.internal` 后以 build-arg 传入，镜像源用腾讯云 PyPI 镜像。代理值不写入日志与本报告。

```
MAPPED_HTTP=$(printf '%s' "$HTTP_PROXY" | sed -E 's#(https?://)([^/@]+@)?(127\.0\.0\.1|localhost):([0-9]+)#\1\2host.docker.internal:\4#')
MAPPED_HTTPS=$(printf '%s' "$HTTPS_PROXY" | sed -E 's#(https?://)([^/@]+@)?(127\.0\.0\.1|localhost):([0-9]+)#\1\2host.docker.internal:\4#')
docker build -f /tmp/pl-routefix-dockerfile/Dockerfile \
  --build-arg PIP_INDEX_URL=https://mirrors.cloud.tencent.com/pypi/simple/ \
  --build-arg HTTP_PROXY="$MAPPED_HTTP" --build-arg HTTPS_PROXY="$MAPPED_HTTPS" \
  --build-arg http_proxy="$MAPPED_HTTP" --build-arg https_proxy="$MAPPED_HTTPS" \
  --build-arg NO_PROXY="$NO_PROXY" --build-arg no_proxy="$no_proxy" \
  -t biblio-purposcape:routefix .
```

关键输出：`BUILD_EXIT=0`、`#25 naming to docker.io/library/biblio-purposcape:routefix`、`Successfully installed ... purpose-landscape-web-0.1.0`。日志：`/tmp/pl-routefix-verify-build.log`。

```
ID=sha256:f7f521667307e8806d7c6423b827e82b3c273cf0fc6bd6b31d760e9db0eacb5e
SizeBytes=1327240384  (1.33 GB)
Created=2026-11-25T05:01:25.850497047Z  Architecture=arm64
```

对照：`biblio-purposcape:deploy-check` 1.33 GB、`purpose-landscape-web-web:acceptance-20261125` 1.31 GB，大小合理。镜像 `Config.Env` 仅有 PATH / LANG / Python 基础变量 / PYTHONPATH / PIP 超时重试项，未残留代理或镜像源凭据。

## 2. skill_runtime 文件与配置读取

```
docker run --rm --entrypoint sh biblio-purposcape:routefix -c \
  'ls -ld /app/skill_runtime/versions/base /app/skill_runtime/templates; \
   find /app/skill_runtime/versions/base -maxdepth 1 -type f | sort; \
   find /app/skill_runtime/templates -maxdepth 1 -type f | wc -l'
docker run --rm -e APP_ENV=development --entrypoint python biblio-purposcape:routefix \
  -c 'from app.skill_versions import load_base_config; print(sorted(load_base_config()))'
```

输出：两个目录均存在；base 下为 `cards.yaml`、`modes.yaml`、`visual.json`；templates 下 7 个骨架文件；`load_base_config()` 返回 `['cards', 'modes', 'templates', 'visual']`。**通过**，无缺文件。

## 3. 空 SQLite 生产补种幂等

`SEED_BASE_SKILL=true` 是 `render.yaml` 中的生产开关；配合 `APP_ENV=development` 可走默认 sqlite 且不触发生产配置强校验。数据库使用容器内全新 `/tmp/pl_seed_verify.db`，未连线上库。

```
docker run --rm -e APP_ENV=development -e SEED_BASE_SKILL=true \
  -e DATABASE_URL=sqlite:////tmp/pl_seed_verify.db --entrypoint python \
  biblio-purposcape:routefix -c 'from app.db import engine, initialize_database; \
  from app.models import SkillVersion; from sqlalchemy.orm import Session; \
  initialize_database(); initialize_database(); db=Session(engine); \
  rows=db.query(SkillVersion).all(); \
  print("rows=", len(rows)); \
  print("version_state_pairs=", [(r.version, r.state) for r in rows]); \
  print("published_count=", sum(1 for r in rows if r.state=="published")); \
  print("content_keys=", sorted(rows[0].content) if rows else None); db.close()'
```

输出：

```
rows= 1
version_state_pairs= [(1, 'published')]
published_count= 1
content_keys= ['cards', 'modes', 'templates', 'visual']
```

连续两次 `initialize_database()` 后仅 1 条 v1 published，第二次未新增。**通过**。

## 4. 容器启动、健康检查与前端首页

```
docker run -d --name pl-routefix-verify-20261125 -p 18080:8000 \
  -e APP_ENV=development biblio-purposcape:routefix
curl -sS --max-time 8 --retry 10 --retry-delay 1 --retry-all-errors \
  -o /tmp/pl_health.json -w 'HTTP=%{http_code}\n' http://127.0.0.1:18080/api/health
curl -sS --max-time 8 -D /tmp/pl_index.headers -o /tmp/pl_index.html \
  -w 'HTTP=%{http_code}\n' http://127.0.0.1:18080/
```

- 首次 curl 在容器启动瞬间返回 `Recv failure: Connection reset by peer`，非启动失败；日志随后显示 `Application startup complete` / `Uvicorn running on http://0.0.0.0:8000`，改用 `--retry-all-errors` 重试即成功。镜像内无预置 `/app/test.db`，默认 sqlite 为启动时新建。
- `/api/health`：`HTTP=200`，响应 `{"status":"ok","database":"ok","worker":"unavailable"}`（未接 Redis，符合本用例范围）。
- `GET /`：`HTTP=200`，`content-type: text/html; charset=utf-8`，`content-length: 613`，标题 `<title>研究图谱 · 私密邀请</title>`；返回体 sha256 `61bb2d2b…703934` 与镜像内 `/app/frontend/dist/index.html` 完全一致。**通过**。

## 5. 密钥与副作用约束

- 镜像 `Config.Env` 无密钥类变量，镜像内无 `/app/.env`；运行容器仅注入 `APP_ENV=development`，未注入模型密钥；补种用例只注入 `SEED_BASE_SKILL` 与本地 sqlite URL。
- 对构建日志、健康检查响应、首页响应与头部的 `sk-` / 密钥赋值 / Bearer 模式扫描结果为空；未连接线上数据库。
- 未执行 `docker push`；`render.yaml` 未改动；自建容器 `pl-routefix-verify-20261125` 已 `docker rm -f` 清理；用户既有镜像全部保留，既有 3 个容器未触碰。

## 6. 结论与剩余风险

结论：5 项验收全部通过；镜像可启动、健康检查与前端路由正常、技能配置可读、空库补种幂等；未发现缺文件或真实启动失败。

剩余风险：

1. **构建可复现性**：本机代理拦截 PyPI，仓库原样 `docker build` 与主线后台构建均会卡在 pip 步骤；本次靠仓库外临时 Dockerfile + 镜像源完成。最小修复建议：在 `Dockerfile` 中把 `PIP_INDEX_URL` 声明为可选 `ARG`（默认值保持官方源），或在构建环境统一配置可达镜像源。Render 侧网络未验证。
2. **提交快照不固定**：验收期间主线从 `6e03da2` 推进到 `4f74301`（新增 `c12958b`、`f22b043`、`4f74301`），且工作树存在未提交改动；构建上下文在 12:56 读取，无法把镜像逐位归因到某个 commit。建议主线稳定后以固定 `git rev-parse HEAD` 重建并复跑本报告。
3. **架构覆盖**：本机为 arm64，仅验证 arm64 镜像；amd64 产物未覆盖。
4. **worker=unavailable**：验收容器未接 Redis，健康接口仍返回 200/database=ok；若生产要求 worker ready，需另行接入 Redis 验证。
