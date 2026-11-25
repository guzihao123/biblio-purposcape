# EVIDENCE_INDEX — 本地候选比赛证据包

> **性质声明：这是本地候选比赛证据包，不是公开发布证明。** 全部证据产生于本机离线 Provider 验收环境，未创建云资源、未部署、未发布、未调用付费模型。

## 本轮真实执行证据（2026-11-24 20:33–20:37，Asia/Shanghai）

运行方式：真实 Chromium（Playwright 1.65.1 headless）+ 真实 FastAPI／SQLite／RQ worker／redislite Redis，第三方边界替换为项目离线 HCC 夹具（OpenAlex 快照、统计、模型、著录核验）。独立端口：API 8026／Skill 回归 API 8027／前端 5194／Skill 回归前端 5195／Redis 6394。运行目录 `run/`，结束后进程全部回收（端口已复核关闭）。

| 证据 | 位置 | 结果 |
|---|---|---|
| 汇总结果 | `result.json` | 5/5 测试通过，退出码 0 |
| UI 截图（37 张，含页面/视口/流程标注） | `screenshots/`，清单 `evidence/screenshots-manifest.json` | 1440×900 与 390×844 双视口 |
| 页面布局检查（33 次审计，含 iframe 图谱帧） | `evidence/*-layout.json`、`evidence/layout-summary.json` | 全部无横向溢出、无越界元素 |
| 网络/控制台错误记录（5 个测试） | `evidence/*-browser-events.json`、`evidence/browser-events-summary.json` | 0 console error / 0 pageerror / 0 requestfailed / 0 HTTP≥400 |
| 下载文件 SHA-256（6 个制品） | `evidence/download-sha256.json` | report.docx×2、PPT、dialogue.json、verify_report.txt、conformance.md |
| Office 复开校验 | `evidence/*-office-verification.json` | B/C Word 真实复开（90/63 段，含 DOI 10.1126/sciadv.adv0558）；D PPT 25 页（20–30 契约内） |
| 越权边界（他主 404/签名 403） | `evidence/*-owner-boundary.json` | 其他会话任务与签名 URL 均 404，伪签名 403 |
| 状态检查（SQLite integrity、RQ、制品目录） | `evidence/state-summary.json` | integrity ok，4 任务，Skill 版本 2（发布后回退） |
| Skill 真实回归（HCC 校验 + 动效 6 + 任务浏览器 10） | `evidence/skill-regression-report.json`、`evidence/skill-regression-summaries.json` | 全部 passed |
| 运行日志（redis/web/worker/frontend） | `evidence/runtime-*.log` | 独立目录，密钥已脱敏 |
| 敏感信息扫描 | `evidence/sensitive-scan.json` | 0 发现（无密钥、无 token、无真实用户数据） |
| Playwright 结构化结果 | `evidence/playwright-results.json` | expected 5 / unexpected 0 |

覆盖的页面流程（逐张标注见 `evidence/screenshots-manifest.json`）：

- **01 A 模式**：匿名入口（桌面+窄屏）→ 方向卡 → 用途确认卡（receipt）→ 术语确认卡 → 年限确认卡 → 检索进度（`当前阶段：search` 轮询）→ 图谱仪表盘（满血版 iframe）→ 轻量版（签名图加载、tab 键盘切换）→ 交付形式卡 → 对话要点下载（键盘触发）→ 研究历史 → 报告复访。全程键盘操作 + reduced-motion。
- **02 B 模式**：项目卡 → 重复提交去重（1 次提交）→ 真实 RQ 轮询 → 七类图谱满血版（趋势/比较/主题分布/引用网络/因素→结局/方法思维导图/语义关系，含图元点击证据面板）→ 限定/不限口径切换 → 轻量版面板交互 → 年限调整卡 → Word 报告、证据复核、需求对账下载。
- **03 C 模式**：三步固定卡 → C1+C2 衔接（combined_delivered）→ 合并 Word。
- **04 D 模式**：团队背景卡 → 检索 → 20–30 页 PPT 下载。
- **05 Skill 管理**：加载版本 → 创建草稿 → 真实回归（子套件跑在 8027/5195）→ 发布 → 回退 → 令牌不落 localStorage/sessionStorage。

## 可复跑命令

```bash
# 一键复跑（启动独立端口全套服务 + 5 项 Playwright 验收 + 状态检查 + 脱敏）
bash dev/acceptance/competition-evidence/scripts/run_all.sh

# 证据归集（哈希、清单、result.json）
.venv/bin/python dev/acceptance/competition-evidence/scripts/collect_evidence.py
```

运行器为 `dev/real_backend/runtime.py` 的副本（`scripts/run_runtime.py`），仅改端口与目录；未修改 `dev/real_backend/runtime.py` 及任何共享脚本。视口：桌面 1440×900、窄屏 390×844。

## 历史证据（仅作背景，不代表本轮）

- `dev/acceptance/sites-live/`、`dev/acceptance/provider-live/`、`dev/acceptance/live-services/`：此前站点点签、Provider 契约与线上服务验收记录。
- `frontend/e2e/real-backend-screenshots/`、`dev/real_backend/runtime/`：主线工地旧轮输出（8000/5175/6389 端口体系），端口与运行目录均不同于本轮。
- 根目录 `task-*.md` 报告：各阶段任务记录。

以上均未混入本轮结果；本轮证据全部来自 8026/8027/5194/5195/6394 端口体系与 `competition-evidence/run/` 目录。

## 未验证边界

- 真实 Provider：OpenAlex 实时检索、千问/付费模型未调用，仅离线确定性夹具。
- 云 Storage、公网部署、公开 URL：未创建、未验证；不存在第二份 .qoder.site。
- PowerPoint 桌面端视觉验收（LibreOffice/QuickLook 渲染闭环）仍未关闭，为已知遗留项。
- 动效验收经由 Skill 回归子套件（motion 8027 运行 ID）执行，主流程与动效使用独立数据库、trace 与报告目录。

## 主线后续补充（主线独立执行，不属于本轮证据）

> 以下两条为本任务结束后由主线另行执行/登记的补充信息，仅作索引登记，**不得混入本轮 5/5 测试结果、37 张截图清单或任何本轮原始证据**。

- **OpenAlex 补丁后 LIVE 测试（主线独立执行）**：2/2 通过，2 次 HTTP 均为 200，真实撤稿原文与声明均已剔除。此为真实 Provider 侧的独立补充证据，不改写本轮离线 Provider 边界结论。
- **PPT 视觉边界补充登记**：第 7 页图例存在轻微碰撞，已登记跟进项 `FOLLOWUP-P07-LEGEND`；因此不能表述为“PPT 视觉全部无问题”，桌面端视觉闭环仍为未验证/未闭环边界。
- 千问调用数仍为 0；真实云 Storage、公网部署、PowerPoint 桌面端继续保持未验证。
