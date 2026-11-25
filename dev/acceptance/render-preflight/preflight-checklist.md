# Render 部署前检查清单（可复核）

检查日期：2026-11-24（Asia/Shanghai）
项目：`/Users/crisprcas_9/WorkBuddy/2026-11-06-20-49-06/purpose-landscape-web`
边界：未创建 Render 服务、未执行云端迁移、未部署、未调用付费模型、未修改生产源码或 Render 配置。
结论：**NOT_DEPLOYABLE（7 项阻断，详见 result.json）**

## 一、架构分离

| # | 检查项 | 结果 | 复核方式 |
|---|--------|------|----------|
| 1.1 | render.yaml 含 web / worker / redis 三服务 | ✅ | 服务类型分别为 `web`、`worker`、`redis` |
| 1.2 | docker-compose 服务划分与 Render 一致 | ✅ | web、worker、redis 三服务；均依赖 redis |
| 1.3 | worker 启动命令统一为 `python worker.py` | ✅ | render `dockerCommand` 与 compose `command` 一致 |
| 1.4 | worker.py 先注册 stage 服务与恢复调度器再消费队列 | ✅ | `register_stage_services()` → `start_recovery_scheduler()` → `ProtectedWorker.work()` |
| 1.5 | Redis 连接串自动注入（fromService） | ✅ | web/worker 的 `REDIS_URL` 均引用 `landscape-redis` |

## 二、健康检查与入口

| # | 检查项 | 结果 | 复核方式 |
|---|--------|------|----------|
| 2.1 | healthCheckPath `/api/health` 与实现一致 | ✅ | `main.py health()` 查库 + `worker_status()`（真实 Redis PING） |
| 2.2 | 容器监听 `${PORT:-8000}` | ✅ | Dockerfile CMD；EXPOSE 8000 |
| 2.3 | API 未知路径返回 404 JSON 而非 SPA 回退 | ✅ | `serve_frontend` 对 `api/` 前缀显式 404 |
| 2.4 | SPA 静态文件路径逃逸防护 | ✅ | `resolve()` 后 `relative_to(dist)` 校验 |
| 2.5 | **生产前端 API 基址正确** | ❌ **阻断 B-01** | 前端烘焙 `VITE_API_BASE_URL=/functions/v1/app`，容器实际在 `/api`；生产调用会拿到 index.html（200）→ `response.json()` 崩溃。修复：Dockerfile ARG 默认改 `/api` |

## 三、持久化与数据

| # | 检查项 | 结果 | 复核方式 |
|---|--------|------|----------|
| 3.1 | **ARTIFACT_ROOT 持久化** | ❌ **阻断 B-02** | `/var/data/artifacts` 无 Render Disk 挂载；web/worker 文件系统不共享，worker 产出工件 web 端必然 404。需挂盘或走 `QODER_SITES_ORIGIN` 远端回源 |
| 3.2 | **DATABASE_URL 来源** | ❌ **阻断 B-03** | `sync: false` 且无 Postgres 服务；漏配回落 `sqlite:///./test.db` → 双容器数据分叉、重启全丢 |
| 3.3 | 会话/密钥稳定性 | ⚠️ 条件通过 | `SESSION_SECRET`、`ADMIN_TOKEN` 漏配则每次启动随机生成（全员掉线 / admin 不可用）。必须创建服务时显式设置 |
| 3.4 | 限流存储 | ✅ | Redis 原子固定窗口，非进程内存 |
| 3.5 | 会话 Cookie 属性 | ✅ | httponly + secure + samesite=lax；同源部署无需 CORS |

## 四、配置完整性（render.yaml ↔ .env.example ↔ 代码读取点）

| 变量 | 声明 | 代码读取 | 状态 |
|------|------|----------|------|
| DATABASE_URL | sync:false | config.py | ❌ 必填，见 B-03 |
| REDIS_URL | fromService ✅ | config.py / worker.py | ✅ |
| QWEN_API_KEY / BASE_URL / MODEL | sync:false / 固定值 | qwen.py（仅环境变量） | ⚠️ 必填（付费模型，本轮未调用） |
| SESSION_SECRET | sync:false | security.py / artifacts.py 签名 | ❌ 必填，见 B-04 |
| ADMIN_TOKEN | sync:false | security.py `require_admin` | ❌ 必填，见 B-04 |
| QODER_SITES_ORIGIN | sync:false | orchestration.py / artifacts.py | ❌ 必填，否则工件不可达（B-02） |
| WORKER_SHARED_SECRET | sync:false | 同上（SitesStorageClient 鉴权） | ❌ 必填 |
| ARTIFACT_ROOT | /var/data/artifacts | artifacts.py / orchestration.py | ❌ 无挂载（B-02） |
| VITE_API_BASE_URL | 仅 Docker ARG | api.ts 构建期固化 | ❌ 烘焙值错误（B-01） |
| INVITE_CODE_HASH | 无 | config.py（当前无路由使用） | ➖ 无影响，测试明确断言其不出现于 .env.example |
| ALLOWED_ORIGINS / PYTHON_API_ORIGIN | .env.example 有 | 代码未读取 | ➖ 死配置 |
| Redis `ipAllowList: []` | render.yaml | — | ⚠️ 对公网开放，建议收紧或确认平台内网隔离语义 |

## 五、构建与依赖（部署条件）

| # | 检查项 | 结果 | 复核方式 |
|---|--------|------|----------|
| 5.1 | **linux/amd64 镜像构建** | ❌ **阻断 B-05** | 3 次尝试全部失败于 Docker Hub 元数据解析（ENVIRONMENT-BLOCKED），无成功构建日志；Dockerfile 本身无需修改 |
| 5.2 | 前端构建链（npm ci / tsc / vite） | ⚠️ 未验证 | package-lock.json 存在且被 COPY；无镜像内构建证据 |
| 5.3 | Python 依赖（onnxruntime、pypdfium2、rapidocr 等） | ⚠️ 声明齐全，未验证 | pyproject.toml + 先升 pip/setuptools/wheel 再 `pip install .` |
| 5.4 | Noto CJK / fontconfig / libgl1 / libgomp1 等系统依赖 | ⚠️ 声明齐全，未验证 | apt 段完整；未在 Linux 执行 `fc-match :lang=zh-cn` |
| 5.5 | PPT / PDF / OCR 运行时冒烟 | ⚠️ 未验证 | 依赖齐全但无镜像内导入/渲染证据 |
| 5.6 | .dockerignore | ✅ | 排除 .env、.venv、test.db、dev/、node_modules 等 |
| 5.7 | 多阶段构建与 dist 复制 | ✅（静态） | `COPY --from=frontend /app/frontend/dist ./frontend/dist`，WORKDIR /app 与 `frontend_dist` 默认相对路径一致 |
| 5.8 | Compose `env_file.required: false` 语法 | ⚠️ | 需较新 Compose 版本，未实测 |

## 六、发布阻断汇总（不得以上线掩盖）

| 编号 | 阻断 | 级别 |
|------|------|------|
| B-01 | 前端 API 基址烘焙为 /functions/v1/app，生产调用静默全灭 | critical |
| B-02 | 工件目录无 Disk、web/worker 不共享 → 工件 404 | critical |
| B-03 | DATABASE_URL 漏配回落 SQLite → 数据分叉与丢失 | critical |
| B-04 | SESSION_SECRET / ADMIN_TOKEN 漏配随机轮换 | high |
| B-05 | amd64 镜像从未构建成功（网络阻塞，无证据链） | high |
| B-06 | 主存储（Sites 远端）未全量接线，仅假 Provider 契约 | high |
| B-07 | 真实 Provider / RLS 未验收；RLS 草案 HIGH 缺口（answers 表无 RLS 等） | high |

## 七、回滚准备核对

- [ ] 首次 apply 蓝图前确认使用独立/staging 服务名，不与线上 Qoder Sites 入口发生域名切换
- [ ] Postgres 选型 + 首写前快照；`initialize_database()` 增量 ALTER 在 Postgres 实测
- [ ] SESSION_SECRET / ADMIN_TOKEN 首设即离线存档，轮换预案含旧值保留窗口
- [ ] 远端工件回源（QODER_SITES_ORIGIN）行为实测：本地优先、远端兜底的 resolve 顺序
- [ ] Skill 版本回滚端点依赖 ADMIN_TOKEN 生效后才能作为回滚手段
- [ ] 历史镜像留存策略（当前无任何已构建镜像可回滚）

## 八、未验证边界（移交后续授权执行）

镜像内启动与健康接口实测、中文字体实测、PPTX/PDF/OCR 冒烟、真实 Redis/RQ 消费、密钥注入与公网行为、付费模型调用、Deno Function、真实 Provider 权限/事务/RLS 行为矩阵、云 Storage 字节级验收、Compose 版本兼容性。

---

复核入口：所有结论均可在 `result.json` 的 `evidence_index` 列出的文件与行号处逐一回验。
