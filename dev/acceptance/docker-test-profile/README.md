# Docker 离线测试环境（docker-test-profile）

独立、可复跑的离线验收环境。**不修改** 生产 `Dockerfile`、`docker-compose.yml`、生产源码或其他工地的 `test-results`，全部新增内容仅限本目录。

## 隔离保证

- 固定 Compose 项目名 `purpose-landscape-web-test`，卷为项目级 `test-data` / `test-redis`，绝不触碰生产 `landscape-data` / `landscape-redis`；
- Web 只发布在 **8034**（被占用时用 `PLW_TEST_HTTP_PORT=8035` 切换），不用生产 8000；
- 后端测试 **不设置** `RUN_LIVE_OPENALEX_ACCEPTANCE`、`RUN_LIVE_QWEN_ACCEPTANCE`、`QWEN_API_KEY` 等任何付费/在线变量；live 用例按设计自我跳过（不是删测试）；
- `PURPOSE_LANDSCAPE_HCC_FIXTURES=/app/fixtures/hcc-20261122`、`PYTHONPATH=/app/backend`；
- Function 测试在 **Node 22** 独立镜像运行（原生类型剥离，不需要 Deno）；
- 不执行真实 Provider 调用、PostgreSQL/RLS 迁移、云端部署；fake store／RLS 仅校验 `sites/schema.sql` 契约与固定操作白名单。

## 文件

| 文件 | 说明 |
| --- | --- |
| `Dockerfile.test` | 以生产镜像 `purpose-landscape-web-web:latest` 为基础，刷新 `backend/tests`，安装 `.[test]` 可选依赖 |
| `Dockerfile.node-test` | `node:22-bookworm-slim` + `python3`（仅 stdlib，供两个内嵌 Python 探针测试），复制 `sites/`、`backend/` 与 `dev/` 本地 stub（经命名构建上下文绕开生产 `.dockerignore` 对 `dev/` 的排除） |
| `compose.test.yaml` | redis / web / worker / backend-test / node-test 五个服务 |
| `run-tests.sh` | 一键复跑：构建 → 后端 pytest → Node 测试 → 起栈 → 静态入口与 worker 校验 → 写 `result.json` → `down -v` 清理 |
| `known-failures.json` | 已知环境依赖失败清单（测试照常运行、照常上报；仅用于结论分类） |
| `result.json` | 每次运行生成的实际结果（本文件由脚本产出） |
| `logs/` | 脱敏日志（脚本扫描疑似凭据模式） |

## 复跑

```bash
cd dev/acceptance/docker-test-profile
./run-tests.sh          # 完整跑一遍并清理
./run-tests.sh --keep   # 保留栈，便于手动 curl 8034 端口验证
```

或手动分步：

```bash
docker compose -f compose.test.yaml build
docker compose -f compose.test.yaml run --rm --no-deps backend-test
docker compose -f compose.test.yaml run --rm --no-deps node-test
docker compose -f compose.test.yaml up -d redis web worker
curl -i http://127.0.0.1:8034/            # 期望 200
curl -i http://127.0.0.1:8034/history     # 期望 200
curl -i http://127.0.0.1:8034/api/nope    # 期望 404
docker compose -f compose.test.yaml down -v
```

## 未验证边界

1. Live OpenAlex/Qwen 验收为 opt-in，本次未执行，其用例在无环境变量时按设计自我跳过（4 个 skipped）；
2. PostgreSQL 与 RLS 迁移未执行；fake store／RLS 前置契约仅审阅 `sites/schema.sql` 与固定操作白名单；
3. 未做云端部署、未发布 Qoder Sites、未发生任何付费调用；
4. worker 仅验证在**测试** Redis 中注册（`rq:worker:*` key），未向真实栈投递端到端任务（`test_worker_e2e` 已用 fakeredis 在容器内离线覆盖）；
5. 架构以容器内 `platform.machine()` 为准如实上报（本机为 arm64/aarch64），结果仅对该架构有效；
6. 2 个 rate_limit 用例为已知环境依赖失败（见 `known-failures.json`）：生产镜像内 Python 3.11.18 的 `ipaddress` 将 IPv4-mapped 地址压缩形式渲染为点分十进制（`::ffff:203.0.113.50`），与用例编写时 Python 3.9.6 的十六进制组渲染（`::ffff:cb00:7132`）不同。修复需改动测试或生产源码，超出本环境边界，测试照常运行并如实计入结果。
