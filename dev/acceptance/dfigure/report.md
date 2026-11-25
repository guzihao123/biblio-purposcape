# D PPT 原图与资产清单验收报告（分支 `dfigure`）

- 工作树：`purpose-landscape-web-dfigure`，分支 `dfigure`，基线 `integration2`
- 范围：只做 D 模式真实论文图获取、入页、资产清单与验证；**未改卡片/写作内容、未改 D 页序、未部署、未 push**
- 结论：4 篇 D 文献（3 篇精读 + 1 篇综述支撑）共取得 **24 张真实原图**，其中 **11 张已嵌入 D 稿 11 个页面**；`verify_ppt_delivery` 为 **PASS（通过 45 / 降级 0 / 失败 0）**，25 页页序与原 `layout_manifest.json` 完全一致

## 1. 代码接入

| 文件 | 变更 |
|---|---|
| `skill_runtime/scripts/pdf_figures.py` | 从 Skill 原样纳入运行时；提供 `info / render / crop`，PDFKit(Swift) 优先，PyMuPDF 回退 |
| `skill_runtime/scripts/pdf_render.swift` | PDFKit 渲染后端源码；首次使用时由 `pdf_figures.py` 编译出 `pdf_render`（编译产物已加入 `.gitignore`） |
| `backend/app/ppt_figures.py` | 新增：OA 定位、PDF 裁切、Europe PMC JATS 图像包回退、角色分类、命名、清单、入页编排、获取日志 |
| `backend/app/delivery.py` | `_write_pptx` 接收 `figure_loader`；D 页在原有版式内嵌图、图注、降级说明；窄栏字号自适应；清单扩展 |
| `backend/tests/test_ppt_figures.py` | 合成小 PDF、假图、JATS ZIP、离线降级、清单字段、实际嵌图测试 |
| `.gitignore` | 忽略 `pdf_render` 编译产物、验收运行目录的 PPTX 与缓存 XML |

获取链路：

1. `FullTextService.read_for_components(paper, purpose="D_READING_CARD")` 调 `oa_pdf.resolve`，按候选顺序尝试 PDF / Europe PMC XML；
2. 得到 PDF → `pdf_figures.py crop` 按“页顶到图注上沿”渲染裁切（保留图题和全部 panel，不裁掉表头）；
3. PDF 被 403/反爬拦截 → 读取 JATS XML 的 `<fig>` 图号/图注/`xlink:href`，从 `europepmc/webservices/rest/{PMCID}/supplementaryFiles` 图像包取原始 JPG/PNG；
4. 两者都失败 → 页面保留 OA 链接 + 文字描述 + `【待核实】`，写入日志，不重绘、不生成占位图。

命名统一为 `figures/ref<n>_fig<k>_<角色>.png`；角色取 `概念框架 / 研究设计 / 机制模型 / 临床比较 / 治疗验证 / 结果图`。

## 2. 真实获取记录（2026-11-25）

| ref | 文献 | OA 定位过程 | 最终来源 | 版本 | 图数 |
|---|---|---|---|---|---|
| [1] | Sphingolipid synthesis in TAMs confers immunotherapy resistance in HCC（Sci Adv 2025） | `science.org` PDF 直链 **403 Forbidden**；Europe PMC `PMC12094245` XML 首次实时下载成功（18:04），后续请求遇 **503**，复跑使用已校验缓存 XML | JATS XML + supplementaryFiles 图像包 | 正式版 | 8 |
| [2] | Overcoming immunotherapy resistance in HCC by targeting myeloid IL-8/CXCR2（Mol Ther 2025） | DOI 落地页不是 PDF；Europe PMC `PMC11997504` XML 一次 503 后重试成功 | JATS XML + supplementaryFiles 图像包 | 正式版 | 6 |
| [3] | Lactylation-driven MVP upregulation boosts immunotherapy resistance（JITC 2025） | DOI 直链 **403 Forbidden**；Europe PMC `PMC12458742` XML 可用 | JATS XML + supplementaryFiles 图像包 | 正式版 | 8 |
| [4] | Exploring the role of the immune microenvironment in HCC（eLife 2024） | `cdn.elifesciences.org/articles/95009/elife-95009-v1.pdf` 可下载；用 `pdf_figures.py` 裁切 | 本地 OA PDF 渲染裁切 | 正式版 | 2 |

- 资产合计：**24 张 PNG，10.2 MB**，宽度 686–1073 px；全部来自 OA 原始图像或 OA PDF 渲染，无重绘、无网络图片占位。
- 逐篇明细（含每张图的图号、图注、获取方式）：`dev/acceptance/dfigure/run/figure_acquisition_log.md`。
- 页码：仅 [4] 可从 OA PDF 核实，Fig.1 = **p3**、Fig.2 = **p11**；[1]–[3] 的出版社 PDF 均被拦截，JATS 包不含页码，因此统一写 `p【待核实】`，不猜测。

## 3. 入页映射（D 稿 25 页，页序未变）

| 页 | 页面标题 | 嵌入图 | 标注 |
|---|---|---|---|
| P3 | 研究背景与科学问题（概念框架） | `ref4_fig1_概念框架.png` | [4] Fig.1，原文 p3，正式版 OA 版本 |
| P8 | 研究进展｜免疫微环境与耐药总览 | `ref4_fig2_临床比较.png`（BCLC 分期与 ICI 临床试验对照表） | [4] Fig.2，原文 p11，正式版 OA 版本 |
| P11 | 研究进展｜乳酸化与 PD-L1 稳定性（模型架构） | `ref3_fig3_机制模型.png` | [3] Fig.3，原文 p【待核实】，正式版 OA 版本 |
| P13 | 核心方法与技术路线（技术路线/方法关系） | `ref2_fig1_研究设计.png`（含 cohort 研究设计 panel） | [2] Fig.1，原文 p【待核实】，正式版 OA 版本 |
| P14 | 代表作精读 [1]｜方法与数据 | `ref1_fig1_结果图.png` | [1] Fig.1，原文 p【待核实】，正式版 OA 版本 |
| P15 | 代表作精读 [1]｜发现与启发 | `ref1_fig2_机制模型.png` | [1] Fig.2，原文 p【待核实】，正式版 OA 版本 |
| P16 | 代表作精读 [2]｜方法与数据 | `ref2_fig2_结果图.png` | [2] Fig.2，原文 p【待核实】，正式版 OA 版本 |
| P17 | 代表作精读 [2]｜发现与启发 | `ref2_fig3_机制模型.png` | [2] Fig.3，原文 p【待核实】，正式版 OA 版本 |
| P18 | 代表作精读 [3]｜方法与数据 | `ref3_fig1_临床比较.png` | [3] Fig.1，原文 p【待核实】，正式版 OA 版本 |
| P19 | 代表作精读 [3]｜发现与启发 | `ref3_fig2_治疗验证.png` | [3] Fig.2，原文 p【待核实】，正式版 OA 版本 |
| P22 | 发展趋势｜不足→潜在突破（突破路径） | `ref3_fig8_治疗验证.png` | [3] Fig.8，原文 p【待核实】，正式版 OA 版本 |

- **方法对比**：P12 仍使用 D 稿原有的六列方法对比表（方法族/技术/数据/优势/局限/文献），这是该页的对比载体；未把不匹配的机制图硬塞进表格版式。原始“临床比较”图分别落在 P8（试验分期表）与 P18（乳酸化-疗效/生存曲线）。
- **精读原图**：3 篇精读各 2 页，每页 1 张原图；`ref1/ref2/ref3` 各取得 8/6/8 张，优先取“结果/机制”角色，未重复用图。
- 所有图片均在原版式的图片框内等比缩放并居中，图注统一 11 pt；有图页的正文栏自动从双栏改为单栏并按字符量降字号（16/14/12/10 pt），程序化检查无图片-文字重叠、无越界。

## 4. 资产清单扩展

`run/ppt_asset_manifest.json` 的每个 `kind=image` 条目新增/包含：

| 字段 | 含义 |
|---|---|
| `source` | 仓库相对路径 `figures/ref<n>_fig<k>_<角色>.png` |
| `figure_no` / `original_page` | `Fig.k` / 原文页码（无法核实则 `【待核实】`） |
| `version` | 正式版 / 预印本等 |
| `acquisition` | OA PDF 裁切，或 JATS 图像包（含 PDF 被拦截说明） |
| `oa_url` | DOI / OA 落地页 |
| `asset_url` | JATS 图像包内精确成员 URL（PDF 裁切无此字段） |
| `caption` / `description` / `slot` | 原文图注、获取说明、入页角色 |

顶层另增 `figure_acquisition[]`：逐篇记录 OA 链接、实际来源 URL、版本、阅读深度、状态、图数、失败原因。降级条目沿用 `degraded/allow_degraded/reason/attempt_log/oa_url/description`，校验器可直接识别。

## 5. 降级项与未决

1. **页码待核实（[1]–[3] 共 22 张）**：出版社 PDF 为 403/反爬，PMC PDF 链接返回中转页；JATS 图像包不提供页码。已写 `p【待核实】` 并保留 DOI/PMC 链接，不猜测页码。
2. **[1] 与 [2] 的 Europe PMC 503**：均发生在实时 XML 请求，重试/缓存后取得全文；最终 24 张图全部落盘，最终清单 **降级 0 项**。
3. **方法对比页无原始图**：该页是生成式六列表格，保持原版式；相关原始对比图已入 P8/P18。
4. **角色分类为启发式**：按图注首句和面板标记判定“概念/方法/机制/临床/治疗”，本批 24 张经人工抽查（ref4 Fig.1、ref4 Fig.2、ref2 Fig.1、ref3 Fig.1 等）无错位；换主题数据仍建议人工复核后再定稿。
5. 未做真实 PPT 渲染截图（本机无 LibreOffice，WPS 自动化需辅助功能授权）；已用 `python-pptx` 做边界/重叠/字号/页序检查，并用 `verify_ppt_delivery.py` 做结构核验。

## 6. 验证与复现

```bash
cd purpose-landscape-web-dfigure
PYTHONPATH=backend <venv>/bin/python -m pytest -q backend/tests/test_ppt_figures.py backend/tests/test_delivery.py
# 18 passed
PYTHONPATH=backend <venv>/bin/python dev/acceptance/dfigure/run_d_deck.py
# assets=24 embedded_entries=11
# 结果：PASS（通过 45，降级 0，失败 0）
```

- 交付稿：`dev/acceptance/dfigure/run/肝细胞癌免疫治疗耐药机制组会汇报.pptx`（4.7 MB，本地生成，未入库）
- 清单/日志/校验：同目录 `ppt_asset_manifest.json`、`figure_acquisition_log.md`、`verify_ppt_report.txt`、`layout_check.json`、`layout_manifest.json`
- `run/figures/`（24 张原图）、`run/oa_pdfs/`、`run/fulltext_ref*.xml` 与 PPTX 按 `.gitignore` 留在本地运行目录，不入库；重新运行 `run_d_deck.py` 可复现
- 页序核对：与 `dev/real_backend/runtime/artifacts/243c5966-.../layout_manifest.json` 逐页标题比较，25/25 一致
- 复跑时若 `fulltext_ref*.xml` / `oa_pdfs/source_ref4.pdf` 已存在会直接复用；缺失时重新走 OA 定位（需网络）
- 合成 PDF 与假图只用于 `pytest` 临时目录验证裁切/嵌入/清单逻辑，不进入交付稿；交付稿 11 张图均来自上述 OA 原图
