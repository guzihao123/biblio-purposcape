# 网页版 Skill 与最新 Skill 深度差异审计（2026-11-25）

对比：`~/.qoder-cn/skills/purpose-landscape`（最新 Skill） vs `purpose-landscape-web`（网页实现）。
方法：脚本/模板逐字节哈希、SKILL.md 与 references/modes.md 逐条对照、后端流程阅读、现有测试核对。只读审计。

## 0. 结论摘要

- 网页的 **Skill 版本内容本身是最新的**：线上 SkillVersion v1 的内容哈希 = 仓库 `load_base_config()` 哈希（`2c11601f…`）。
- 用户感觉到的“旧版行为”主要来自 **线上仍跑旧代码**；本轮已修一批代码级差异（见 §1）。
- 仍有 7 类实质性差异，集中在 **C 模式两卡流程、检索源路由、B 政策材料、C 目标期刊、D 原始图、E 入口、PPT 生成器**。

## 1. 本轮已同步/已修复

| 项 | 最新 Skill | 网页处理 | 证据 |
|---|---|---|---|
| 方向卡示例 | 固定交通四题 | 已替换并加回归 | `backend/app/task_presenters.py`、`test_task_api.py` |
| 年限卡 | 去推荐标记 | 已移除，D 仍置顶 | `test_task_presenters.py` |
| 交付卡字母 | 字母=位置 | 已按位置重排重标 | 同上 |
| Word 文件名 | A/C/E=综述初稿；B=标书-文献综述分析；D=调研报告 | 已按模式输出 | `backend/app/delivery.py:14-22`、`ad1e334` |
| PPT 文件名 | `<主题>组会汇报.pptx` | 所有模式统一 | 同上 |
| 交付对账 | 必须披露待人工确认数字与著录核对 | 已解析 ④ 段并披露；著录问题带 `[ref N]` | `76c0eb7`、`test_delivery.py` |
| Word 题名 | 不应 Title/Heading1 重复 | 已跳过重复 H1 | `76c0eb7` |
| Origin 校验 | 精确 host | 已改为 urlsplit 精确匹配 | `590e0ff` |
| 复核脚本 | 与 Skill 同步 | `verify_delivery.py`、`verify_ppt_delivery.py` 逐字节一致 | sha256 对比 |

## 2. 模板与脚本差异

- 模板：7 个中 6 个逐字节一致；`B_立项依据骨架.md` 有措辞差异（网页版“【资产 [n]】”，Skill 版“【可借鉴的方法、变量体系、模型组件或评估设计 [n]】”，网页版 mtime 更晚）。
- 脚本：`verify_delivery.py`、`verify_ppt_delivery.py` **相同**；`search_papers.py` 功能集相同（OpenAlex/arXiv/Crossref/S2 均存在）但实现有差异；`renumber_citations.py`、`format_references.py`、`pptx_to_text.py` 实现不同（需逐项回归）。
- 网页缺失 Skill 脚本：`pptx_layouts.py`、`pdf_figures.py`、`ocr_image.swift`、`pdf_render(.swift)`。网页用自研 PPT 版式引擎与 `FullTextService` 代替，功能不等价（见 §3）。

## 3. 未对齐项（按影响排序）

### 3.1 检索源路由缺失（高）
- Skill：按主题分流——教育/医学/社科只用 OpenAlex；计算机/工程/AI 加 arXiv；中文词/题录用 Crossref；S2 可选补充。
- 网页：`SearchService` 只调用 `search_papers.py openalex`（`backend/app/search.py:408`），arXiv/Crossref/S2 虽在脚本里但流程从未调用；候选术语计数也走 OpenAlex。
- 影响：CS/工程/AI 主题漏掉 arXiv 前沿；中文主题覆盖弱。

### 3.2 C 模式两张固定卡缺失（高）
- Skill：先「C模式任务」单选（从零写引言 / 从零写文献综述 / 两个都选），再「本文信息」单选（跳过 / 已有初稿提供文件 / 现场口述），逐字文案、记台账；调整卡重选 C 时必须重出两卡。
- 网页：仅一张用途卡内含 `c_route` 下拉 + `user_results` 文本框 + `target_journal`；无独立两卡、无三种材料路径、调整重选 C 不会重出。
- 影响：C 运行逻辑契约不一致；文件/口述材料入口缺失。

### 3.3 C 目标期刊被收集但未使用（中高）
- Skill：目标期刊仅用户主动提供时用于学科定位与引言写法参考卡。
- 网页：`target_journal` 只在 `writing.py` 数据类里存在，组件与正文 payload 均未携带（grep 仅 1 处），也未生成写法参考卡。

### 3.4 C2 构件渲染不完整（中）
- Skill：C2 必须有检索范围与策略、七维分类、综合分析、技术路线比较、六列比较表、五列空白表、未来方向、完整综述。
- 网页：正文模板与复核脚本已是最新（复核脚本同哈希），但 `_render_c2` 只渲染分类框架/比较表/空白表；检索策略、综合分析、技术路线比较、未来方向未进 `components.md`；尚无真实 C2 网页全流程跑通。

### 3.5 B 模式政策材料 [M] 通道未接线（中）
- Skill：B 可接收/检索政策、报告、统计，走独立 `[M]` 通道并存 `policy_docs/` 与 `非论文材料清单.md`。
- 网页：`policy_search.py`、`FullTextService` 存在且有单测，但 `main.py`/`orchestration.py`/`task_flow.py` 均未调用（grep 无引用）；B 流程不会收集或引用 [M] 材料。

### 3.6 D PPT 原始图与资产清单不达标（中）
- Skill：D PPT 需年度趋势、主题分布、概念框架、方法关系/技术路线、模型架构/输入输出、方法对比、突破路径与精读原图，均要有实际来源与获取记录，禁止“完整图见仪表盘”。
- 网页：只嵌入年度趋势/主题分布两个统计图 + 文字/图形页；`_ppt_asset_manifest` 仅登记 chart/diagram，无原始论文图；`pdf_figures.py` 未集成。
- 影响：D PPT 满足机器门禁，但不满足 Skill 的“真实原图”要求。

### 3.7 E 模式入口缺失（低中）
- Skill：E 其他（自由输入）可用。
- 网页：用途卡只有 A–D，无自定义输入；前端通用 custom 渲染存在但模式卡未提供。

### 3.8 PPT 生成器与版式族体系不同源（中）
- Skill：必须用 `pptx_layouts.py` 的 Deck（13 版式族）并跑 `check_layout_rotation.py`。
- 网页：自研 `_add_ppt_slide` 版式引擎 + `layout_manifest.json` + 同一轮换脚本；门禁可过，但视觉规范/版式族与 Skill 不完全一致。

### 3.9 B 模板差异与 Skill v2 阻塞（低）
- 网页 B 模板与 Skill 文件夹一句措辞不同；要统一需发布 Skill v2。
- 线上当前 22 个未完成任务（18 collecting_mode、4 collecting_terms），`SkillVersionService` 规则要求无进行中任务；且没有任务过期清理，v2 发布会一直被拒。

### 3.10 其他小项
- D 总结页缺“最重要趋势 + 2–3 个问题”的显式行（趋势有独立页，机器门禁不拦）。
- `renumber_citations.py` / `format_references.py` / `pptx_to_text.py` 与 Skill 实现不同，需回归确认 B/C 引用重排与 PPT 抽文字段一致。
- 前端下载标签已更新，但 Qoder 站点仍是旧构建，需重新构建发布后才显示新文件名。

## 4. 建议顺序

1. **先部署当前代码**（推送/Render），验证 A/A_DIALOGUE/D 与固定文件名。
2. **C 两卡流程 + 材料输入**（需产品拍板：文件上传 vs 粘贴文本），同步 `target_journal` 的使用与写法参考卡。
3. **检索源路由**：SearchService 按主题加 arXiv/Crossref（S2 可选）。
4. **B [M] 接线**：把 PolicyService/FullTextService 接入 B 流程与交付清单。
5. **C2 构件补全 + 真实 C2 跑通**。
6. **D 原图获取 + 资产清单**（接入 pdf_figures.py / OA 全文）。
7. **任务过期清理 → Skill v2（B 模板）**；E 自定义入口、PPT 版式族对齐可随后。
