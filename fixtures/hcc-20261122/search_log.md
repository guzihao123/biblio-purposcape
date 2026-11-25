# 检索与用户要求日志

mode: A
方向：肝癌免疫治疗耐药机制的最新进展
运行日期：2026-11-22
样板目标：作为网页版人工智能体第一版的端到端对照样板，重点验证流程与需求落实，不追求文献查全。
检索池：每个年限范围上限 50 篇；模式 A 写作池上限 50 篇。
来源边界：医学主题默认仅 OpenAlex；默认摘要级阅读；Crossref 用于著录核验，OA 全文仅在后续构件需要时定向获取。

## 用户要求台账

| 要求原文摘录 | 提出时点 | 应落实到哪个交付物/哪一节 | 状态 |
|---|---|---|---|
| “我到时候就选择确认点1的默认主题当研究主题来当样板好了” | 方向输入 | 全流程与所有交付物 | 已落实为“肝癌免疫治疗耐药机制的最新进展” |
| “A 选题立项前摸底” | 卡片 B·这次洞察的用途 | 检索策略、筛选、分析、正文结构与验收 | 已落实，已读取模式 A 模式卡 |
| “肝细胞癌×免疫治疗耐药（命中 1428，推荐）” | 卡片 C·候选术语多选 | 双范围检索、扩展检索、论文池与图谱 | 已选定；英文检索词为 hepatocellular carcinoma immunotherapy resistance |
| “A 近3年（最新前沿）” | 卡片 D·重点关注的时间范围 | 限定范围检索与双范围图谱 | 已落实为 `--from-year 2023`；不限范围不加起始年 |
| 前序讨论选择“模式 A＋交付形式 B”完整跑一次 | 样板流程讨论与确认点 4 | 对话要点、代表文献与落盘正文 | 已落实：模式 A 与交付形式 B 均由用户卡片确认 |
| “按原计划继续（进入交付形式选择）” | 检索后调整卡片 | 冻结术语、年限与用途 | 已落实，未重跑检索 |
| “B 仅对话中给要点和代表文献” | 确认点 4·交付形式 | 对话 5–8 条要点与 ≤10 篇代表文献；落盘正文与追溯文件 | 已选定，交付时落实 |
| 将本次运行作为“网页第一版的样板” | 样板流程讨论 | 输出目录、图谱、正文、日志与需求符合性对账 | 进行中 |

## 确认点记录

1. 方向：采用确认点 1 的第一个示例“肝癌免疫治疗耐药机制的最新进展”。
2. 用途：用户通过卡片选择“A 选题立项前摸底”；已加载 `references/modes.md` 模式 A。
3. 术语：用户通过卡片 C 选择“肝细胞癌×免疫治疗耐药”；英文检索词 `hepatocellular carcinoma immunotherapy resistance`，计数 1428。
4. 年限：用户通过卡片 D 选择“A 近3年（最新前沿）”；限定范围使用 `--from-year 2023`，不限范围恒不加 `--from-year`。
5. 检索后调整：用户选择“按原计划继续（进入交付形式选择）”；术语、年限与模式 A 冻结，不重跑检索。
6. 交付形式：用户通过确认点 4 选择“B 仅对话中给要点和代表文献”；此后不再提问，直接进入提纲、样章、写作与复核。

## 候选术语计数验证

计数口径：OpenAlex 标题+摘要匹配；只取命中总数，不下载或浏览这些论文。以下命令均实际执行于 2026-11-22。

| 英文候选术语 | 实际命令的查询部分 | 命中数 | 把握 |
|---|---|---:|---|
| hepatocellular carcinoma immunotherapy resistance | `--query "hepatocellular carcinoma immunotherapy resistance" --count-only` | 1428 | 高把握 |
| hepatocellular carcinoma immune checkpoint inhibitor resistance | `--query "hepatocellular carcinoma immune checkpoint inhibitor resistance" --count-only` | 881 | 高把握 |
| hepatocellular carcinoma tumor immune microenvironment | `--query "hepatocellular carcinoma tumor immune microenvironment" --count-only` | 5815 | 高把握 |
| hepatocellular carcinoma immunotherapy combination therapy | `--query "hepatocellular carcinoma immunotherapy combination therapy" --count-only` | 2085 | 高把握 |

命中数只证明该词有相关文献，不证明检索精准。

## 检索记录

### 来源分流与扩展

- 主题属于医学，按规则仅使用 OpenAlex；arXiv 偏理工，本轮不启用。英文主流程未触发 Crossref 补充检索；Semantic Scholar 为可选补充源，本轮未启用。
- 用户选定术语（直接检索，优先保留）：`hepatocellular carcinoma immunotherapy resistance`。
- 模式 A 一轮扩展（只作补充，不替换用户词）：`liver cancer immunotherapy resistance`（同义扩展）、`hepatocellular carcinoma immune evasion`（机制交叉扩展）。两个扩展词通过重复 `--query` 作 OR 合并，单独保存结果并记录。
- 经典补检索使用 `--sort citations`；最新补检索使用 `--from-year 2024 --sort recency`。

### 实际执行命令与取回情况

以下命令均使用技能脚本 `scripts/search_papers.py`，输出到本目录：

1. 不限范围·用户词：`openalex --query "hepatocellular carcinoma immunotherapy resistance" --limit 30 --sort relevance --out openalex_all_t1.json`。命中 1428，取回 30。
2. 限定范围·用户词：同上并加 `--from-year 2023`，输出 `openalex_lim_t1.json`。命中 1094，取回 30。
3. 不限范围·扩展词：`openalex --query "liver cancer immunotherapy resistance" --query "hepatocellular carcinoma immune evasion" --limit 30 --sort relevance --out openalex_all_ext.json`。合并命中 2736，取回 30。
4. 限定范围·扩展词：同上并加 `--from-year 2023`，输出 `openalex_lim_ext.json`。合并命中 1905，取回 30。
5. 经典补检索：`openalex --query "hepatocellular carcinoma immunotherapy resistance" --limit 30 --sort citations --out openalex_all_classic.json`。命中 1428，取回 30。
6. 最新补检索：`openalex --query "hepatocellular carcinoma immunotherapy resistance" --limit 30 --from-year 2024 --sort recency --out openalex_all_recent.json`。命中 919，取回 30。

### 合并、剔除与截断

- 六批共取回 180 条记录。按 DOI 或规范化标题去重，跨记录回填摘要、OA 链接、被引数与引用字段；同名不同年份记录按规范化标题合并。
- 撤稿、非论文条目（数据集/补充材料等）及无有效题录者先剔除，剔除明细存 `merge_excluded.json`；合并后不限范围候选 112 篇，2023 年起候选 78 篇。
- 通读候选题名与摘要后，另剔除 18 篇明显跑题文献：仅泛癌种、其他病种、结直肠癌肝转移、非免疫治疗或与耐药关系不足者。清单与理由存 `pool_selection.json`。
- 最终 `papers_all.json` 50 篇（2015–2026），`papers.json` 50 篇（2023–2026）。截断不是单纯按被引数：先相关性，再综合直接相关度、机制/方向代表性、经典与前沿覆盖、被引数和年份。候选序号仅内部使用；最终对外引用以各文件重新分配的 `ref_no` 为准。
- 两个最终池均无撤稿文献。
- 不限池无摘要：[14] Immunotherapies for hepatocellular carcinoma（2021，被引 2050）；[32] Immune checkpoint inhibitor resistance in hepatocellular carcinoma（2022，被引 207）。仅可进参考文献、全景树和清单。
- 限定池无摘要：[5] Mechanism of M2 type macrophage-derived extracellular vesicles regulating PD-L1 expression via the MISP/IQGAP1 axis in hepatocellular carcinoma immunotherapy resistance；[16] New perspectives in immunotherapy for hepatocellular carcinoma: Focusing on resistance mechanism, biomarker, and personalized treatment；[24] Combination immunotherapy for hepatocellular carcinoma（2023，被引 409）；[27] Endothelial DGKG promotes tumor angiogenesis and immune evasion in hepatocellular carcinoma（2023，被引 179）。仅可进参考文献、全景树和清单。

### 聚合统计

均只用用户选定术语，不把扩展词混入全量聚合口径；group_by 只取分组计数，不下载对应论文。

1. `--stats year --out stats_year.json`：总命中 1428，29 个年度分组。
2. `--stats topics --out stats_topics_all.json`：总命中 1428，200 个主题分组。
3. `--stats topics --from-year 2023 --out stats_topics_limited.json`：总命中 1094，200 个主题分组。
4. 前 4 主题年度序列：`T10158` → `stats_series_1.json`；`T10073` → `stats_series_2.json`；`T11313` → `stats_series_3.json`；`T11067` → `stats_series_4.json`。均不带 `--from-year`。

## 分堆与图谱分析记录

### 主题分堆（模式 A）

每篇按主要研究内容归入一个主题堆；该分类只用于研究进展，不复用为方法树分支。

#### 不限年限

- 临床耐药与治疗策略：9 篇。代表：[14] Immunotherapies for hepatocellular carcinoma；[15] Advances in immunotherapy for hepatocellular carcinoma
- 免疫微环境与细胞互作：15 篇。代表：[17] Cancer cell-derived exosomal circUHRF1 induces natural killer cell exhaustion and may cause resistance to anti-PD1 therapy in hepatocellular carcinoma；[18] CXCR4 inhibition in tumor microenvironment facilitates anti‐programmed death receptor‐1 immunotherapy in sorafenib‐treated hepatocellular carcinoma in mice
- 肿瘤细胞内在信号与表观调控：10 篇。代表：[16] β-Catenin Activation Promotes Immune Escape and Resistance to Anti–PD-1 Therapy in Hepatocellular Carcinoma；[21] Exosome-derived circCCAR1 promotes CD8 + T-cell dysfunction and anti-PD1 resistance in hepatocellular carcinoma
- 代谢重编程与细胞死亡：5 篇。代表：[30] Targeting SRSF10 might inhibit M2 macrophage polarization and potentiate anti‐PD‐1 therapy in hepatocellular carcinoma；[34] Mitochondrial TSPO Promotes Hepatocellular Carcinoma Progression through Ferroptosis Inhibition and Immune Evasion
- 肠道菌群与系统性因素：4 篇。代表：[8] Phocaeicola vulgatus induces immunotherapy resistance in hepatocellular carcinoma via reducing indoleacetic acid production；[9] Immunotherapy resistance in MASLD-related hepatocellular carcinoma: special immune microenvironment and gut microbiota
- 生物标志物、分型与空间多组学：7 篇。代表：[25] Inflamed and non-inflamed classes of HCC: a revised immunogenomic classification；[27] Immune Exclusion-Wnt/CTNNB1 Class Predicts Resistance to Immunotherapies in HCC

#### 2023年以来

- 临床耐药与治疗策略：7 篇。代表：[24] Combination immunotherapy for hepatocellular carcinoma；[6] Mechanisms of Resistance to Immunotherapy in Hepatocellular Carcinoma
- 免疫微环境与细胞互作：12 篇。代表：[23] Tumor microenvironment-mediated immune evasion in hepatocellular carcinoma；[27] Endothelial DGKG promotes tumor angiogenesis and immune evasion in hepatocellular carcinoma
- 肿瘤细胞内在信号与表观调控：12 篇。代表：[25] Exosome-derived circCCAR1 promotes CD8 + T-cell dysfunction and anti-PD1 resistance in hepatocellular carcinoma；[29] TP53/mTORC1-mediated bidirectional regulation of PD-L1 modulates immune evasion in hepatocellular carcinoma
- 代谢重编程与细胞死亡：9 篇。代表：[26] Targeting SRSF10 might inhibit M2 macrophage polarization and potentiate anti‐PD‐1 therapy in hepatocellular carcinoma；[28] Mitochondrial TSPO Promotes Hepatocellular Carcinoma Progression through Ferroptosis Inhibition and Immune Evasion
- 肠道菌群与系统性因素：5 篇。代表：[9] Phocaeicola vulgatus induces immunotherapy resistance in hepatocellular carcinoma via reducing indoleacetic acid production；[11] Immunotherapy resistance in MASLD-related hepatocellular carcinoma: special immune microenvironment and gut microbiota
- 生物标志物、分型与空间多组学：5 篇。代表：[31] The association between tumour heterogeneity and immune evasion mechanisms in hepatocellular carcinoma and its clinical implications；[41] Elevated MPP6 expression correlates with an unfavorable prognosis, angiogenesis and immune evasion in hepatocellular carcinoma

# 方法判定卡与逐篇归类表

## 方法判定卡

方法=论文如何获得数据+用什么技术测量或分析。一级必须是数据获取方法族，二级必须是可落到动作上的具体技术。

正例：①临床样本与治疗队列；②细胞与分子生物学实验；③动物模型与体内干预。

反例：①免疫微环境与细胞互作（研究主题）；②代谢重编程与细胞死亡（研究主题）；③生物标志物、分型与空间多组学（研究目标/主题混合，不能整体当作数据获取方法）。

自检：一级逐项回答“数据从哪来”；二级逐项回答“用了什么技术”。未把任何主题堆名作为方法分支；无摘要或摘要无方法信息者归“其他（未明确方法）”，不猜。

## 2023年以来逐篇归类表

| ref | 论文 | 一级：数据获取方法族 | 二级：具体技术 |
|---:|---|---|---|
| 1 | Sphingolipid synthesis in tumor-associated macrophages confers immunotherapy resistance in hepatocellular carcinoma | 细胞与分子生物学实验；动物模型与体内干预 | 分子互作与通路机制实验（Co-IP、ChIP、RNA-seq）；原位或移植瘤模型与免疫检查点联合干预 |
| 2 | Overcoming immunotherapy resistance in hepatocellular carcinoma by targeting myeloid IL-8/CXCR2 signaling | 单细胞与空间多组学；动物模型与体内干预 | 治疗前后活检单细胞RNA测序；原位或移植瘤模型与免疫检查点联合干预 |
| 3 | Lactylation-driven MVP upregulation boosts immunotherapy resistance by inhibiting PD-L1 degradation in hepatocellular carcinoma | 细胞与分子生物学实验；动物模型与体内干预 | 分子互作与通路机制实验（Co-IP、ChIP、RNA-seq）；原位或移植瘤模型与免疫检查点联合干预 |
| 4 | Exploring the role of the immune microenvironment in hepatocellular carcinoma: Implications for immunotherapy and drug resistance | 文献语料与证据综合 | 叙述性综述与机制证据归纳 |
| 5 | Mechanism of M2 type macrophage-derived extracellular vesicles regulating PD-L1 expression via the MISP/IQGAP1 axis in hepatocellular carcinoma immunotherapy resistance | 其他（未明确方法） | 摘要未提供方法细节 |
| 6 | Mechanisms of Resistance to Immunotherapy in Hepatocellular Carcinoma | 文献语料与证据综合 | 叙述性综述与机制证据归纳 |
| 7 | Next-Generation Immunotherapy for Hepatocellular Carcinoma: Mechanisms of Resistance and Novel Treatment Approaches | 文献语料与证据综合 | 叙述性综述与机制证据归纳 |
| 8 | POSTN + CAF-Derived Migrasomes Drive Hepatocellular Carcinoma Progression and Confer Resistance to Immunotherapy | 公共组学数据与二次分析；细胞与分子生物学实验 | TCGA、GEO、ICGC联合生物信息学分析；细胞功能与免疫表型实验（共培养、流式、qPCR、Western blot） |
| 9 | Phocaeicola vulgatus induces immunotherapy resistance in hepatocellular carcinoma via reducing indoleacetic acid production | 临床样本与治疗队列；动物模型与体内干预 | 粪便宏基因组或16S rRNA测序；粪菌移植与菌群定植实验 |
| 10 | Immunotherapy in hepatocellular carcinoma: an overview of immune checkpoint inhibitors, drug resistance, and adverse effects | 文献语料与证据综合 | 叙述性综述与机制证据归纳 |
| 11 | Immunotherapy resistance in MASLD-related hepatocellular carcinoma: special immune microenvironment and gut microbiota | 文献语料与证据综合 | 叙述性综述与机制证据归纳 |
| 12 | Spatial multi-omics and deep learning reveal fingerprints of immunotherapy response and resistance in hepatocellular carcinoma | 单细胞与空间多组学 | 空间转录组与空间蛋白组联合分析；可解释图神经网络疗效预测 |
| 13 | Unveiling the nexus of p53 and PD-L1: insights into immunotherapy resistance mechanisms in hepatocellular carcinoma | 文献语料与证据综合 | 叙述性综述与机制证据归纳 |
| 14 | Hypomethylation-enhanced CRTC2 expression drives malignant phenotypes and primary resistance to immunotherapy in hepatocellular carcinoma | 细胞与分子生物学实验；动物模型与体内干预 | 分子互作与通路机制实验（Co-IP、ChIP、RNA-seq）；原位或移植瘤模型与免疫检查点联合干预 |
| 15 | Drug resistance mechanisms of immunotherapy and translational strategies for reversing resistance for hepatocellular carcinoma: from bench to bedside | 文献语料与证据综合 | 叙述性综述与机制证据归纳 |
| 16 | New perspectives in immunotherapy for hepatocellular carcinoma: Focusing on resistance mechanism, biomarker, and personalized treatment | 其他（未明确方法） | 摘要未提供方法细节 |
| 17 | Impact of gut microbiome on immunotherapy resistance in hepatocellular carcinoma: a review article | 文献语料与证据综合 | 叙述性综述与机制证据归纳 |
| 18 | Bacteroidetes promote hepatocellular carcinoma progression and resistance to immunotherapy | 临床样本与治疗队列；动物模型与体内干预 | 粪便宏基因组或16S rRNA测序；粪菌移植与菌群定植实验 |
| 19 | [Research progress on poor response, resistance mechanisms, and influencing factors of immunotherapy for hepatocellular carcinoma]. | 文献语料与证据综合 | 叙述性综述与机制证据归纳 |
| 20 | Mitochondrial Quality Control and Metabolic Reprogramming in Hepatocellular Carcinoma: Implications for Immunotherapy and Treatment Resistance | 文献语料与证据综合 | 叙述性综述与机制证据归纳 |
| 21 | Acquired Genetic Variants, Not Tumor Mutation Burden, Drive Resistance to Immunotherapy in Hepatocellular Carcinoma | 临床样本与治疗队列 | 治疗前后ctDNA二代测序 |
| 22 | Overexpression of ORAOV1 and its association with immunotherapy resistance in hepatocellular carcinoma | 公共组学数据与二次分析；细胞与分子生物学实验 | TCGA、GEO、ICGC联合生物信息学分析；细胞功能与免疫表型实验（共培养、流式、qPCR、Western blot） |
| 23 | Tumor microenvironment-mediated immune evasion in hepatocellular carcinoma | 文献语料与证据综合 | 叙述性综述与机制证据归纳 |
| 24 | Combination immunotherapy for hepatocellular carcinoma | 其他（未明确方法） | 摘要未提供方法细节 |
| 25 | Exosome-derived circCCAR1 promotes CD8 + T-cell dysfunction and anti-PD1 resistance in hepatocellular carcinoma | 细胞与分子生物学实验；动物模型与体内干预 | 外泌体分离与非编码RNA互作实验；原位或移植瘤模型与免疫检查点联合干预 |
| 26 | Targeting SRSF10 might inhibit M2 macrophage polarization and potentiate anti‐PD‐1 therapy in hepatocellular carcinoma | 细胞与分子生物学实验；动物模型与体内干预 | 分子互作与通路机制实验（Co-IP、ChIP、RNA-seq）；原位或移植瘤模型与免疫检查点联合干预 |
| 27 | Endothelial DGKG promotes tumor angiogenesis and immune evasion in hepatocellular carcinoma | 其他（未明确方法） | 摘要未提供方法细节 |
| 28 | Mitochondrial TSPO Promotes Hepatocellular Carcinoma Progression through Ferroptosis Inhibition and Immune Evasion | 细胞与分子生物学实验；动物模型与体内干预 | 分子互作与通路机制实验（Co-IP、ChIP、RNA-seq）；原位或移植瘤模型与免疫检查点联合干预 |
| 29 | TP53/mTORC1-mediated bidirectional regulation of PD-L1 modulates immune evasion in hepatocellular carcinoma | 细胞与分子生物学实验；动物模型与体内干预 | 分子互作与通路机制实验（Co-IP、ChIP、RNA-seq）；原位或移植瘤模型与免疫检查点联合干预 |
| 30 | HERC2 promotes inflammation-driven cancer stemness and immune evasion in hepatocellular carcinoma by activating STAT3 pathway | 细胞与分子生物学实验；动物模型与体内干预 | 分子互作与通路机制实验（Co-IP、ChIP、RNA-seq）；基因工程或基因敲除动物模型 |
| 31 | The association between tumour heterogeneity and immune evasion mechanisms in hepatocellular carcinoma and its clinical implications | 文献语料与证据综合 | 叙述性综述与机制证据归纳 |
| 32 | HKDC1 promotes tumor immune evasion in hepatocellular carcinoma by coupling cytoskeleton to STAT1 activation and PD-L1 expression | 细胞与分子生物学实验；动物模型与体内干预 | 分子互作与通路机制实验（Co-IP、ChIP、RNA-seq）；原位或移植瘤模型与免疫检查点联合干预 |
| 33 | A RIPK3-independent role of MLKL in suppressing parthanatos promotes immune evasion in hepatocellular carcinoma | 细胞与分子生物学实验；动物模型与体内干预 | 分子互作与通路机制实验（Co-IP、ChIP、RNA-seq）；原位或移植瘤模型与免疫检查点联合干预 |
| 34 | Metabolic reprogramming in hepatocellular carcinoma: mechanisms of immune evasion and therapeutic implications | 文献语料与证据综合 | 叙述性综述与机制证据归纳 |
| 35 | Dual role of Nrf2 signaling in hepatocellular carcinoma: promoting development, immune evasion, and therapeutic challenges | 文献语料与证据综合 | 叙述性综述与机制证据归纳 |
| 36 | HMMR triggers immune evasion of hepatocellular carcinoma by inactivation of phagocyte killing | 细胞与分子生物学实验；动物模型与体内干预 | 细胞功能与免疫表型实验（共培养、流式、qPCR、Western blot）；基因工程或基因敲除动物模型 |
| 37 | RBM30 recruits DOT1L to activate STAT1 transcription and drive immune evasion in hepatocellular carcinoma | 细胞与分子生物学实验 | 分子互作与通路机制实验（Co-IP、ChIP、RNA-seq） |
| 38 | Targeting Gsk3a reverses immune evasion to enhance immunotherapy in hepatocellular carcinoma | 细胞与分子生物学实验；动物模型与体内干预 | CRISPR筛选或基因编辑功能验证；原位或移植瘤模型与免疫检查点联合干预 |
| 39 | RNA Methyltransferase FTSJ3 Regulates the Type I Interferon Pathway to Promote Hepatocellular Carcinoma Immune Evasion | 细胞与分子生物学实验；动物模型与体内干预 | 分子互作与通路机制实验（Co-IP、ChIP、RNA-seq）；原位或移植瘤模型与免疫检查点联合干预 |
| 40 | LncTUG1 promotes hepatocellular carcinoma immune evasion via upregulating PD-L1 expression | 公共组学数据与二次分析；细胞与分子生物学实验 | TCGA、GEO、ICGC联合生物信息学分析；细胞功能与免疫表型实验（共培养、流式、qPCR、Western blot） |
| 41 | Elevated MPP6 expression correlates with an unfavorable prognosis, angiogenesis and immune evasion in hepatocellular carcinoma | 公共组学数据与二次分析；临床样本与治疗队列 | TCGA、GEO、ICGC联合生物信息学分析；组织芯片、免疫组化与预后分析 |
| 42 | Chemoresistance and immune evasion in hepatocellular carcinoma: the role of miRNA-425-5p | 细胞与分子生物学实验；动物模型与体内干预 | 外泌体分离与非编码RNA互作实验；原位或移植瘤模型与免疫检查点联合干预 |
| 43 | Tissue-resident peripheral helper T cells foster hepatocellular carcinoma immune evasion by promoting regulatory B-cell expansion | 临床样本与治疗队列；细胞与分子生物学实验 | 临床组织流式细胞术与生存分析；细胞功能与免疫表型实验（共培养、流式、qPCR、Western blot） |
| 44 | Exosomal PD-L1 in hepatocellular carcinoma: Immune evasion mechanisms, diagnostic value, and strategies for therapeutic targeting | 文献语料与证据综合 | 叙述性综述与机制证据归纳 |
| 45 | Elemental selenium promotes PD-L1 lysosomal degradation to enhance antitumor immunotherapy | 细胞与分子生物学实验；动物模型与体内干预 | 分子互作与通路机制实验（Co-IP、ChIP、RNA-seq）；原位或移植瘤模型与免疫检查点联合干预 |
| 46 | Chronic Stress Associated Indoxyl Sulfate Upregulation Exhausts CD8 + T Cells to Decrease the Efficiency of Anti‐PD‐1 in Hepatocellular Carcinoma | 临床样本与治疗队列；动物模型与体内干预 | 治疗队列与临床样本关联分析；原位或移植瘤模型与免疫检查点联合干预 |
| 47 | Myeloid ecosystems in hepatocellular carcinoma: macrophage–neutrophil–MDSC crosstalk in immune escape and immunotherapy resistance | 文献语料与证据综合 | 叙述性综述与机制证据归纳 |
| 48 | ADISSP Drives Metabolic Reprogramming and Immune Suppression to Regulate Hepatocellular Carcinoma Progression and Immunotherapy Sensitivity | 细胞与分子生物学实验；动物模型与体内干预 | 分子互作与通路机制实验（Co-IP、ChIP、RNA-seq）；原位或移植瘤模型与免疫检查点联合干预 |
| 49 | Carbonic anhydrase 2 positive tumor-associated endothelial cells contribute to anti-PD-1 therapy resistance through TREM2⁺ macrophages in hepatocellular carcinoma | 单细胞与空间多组学；动物模型与体内干预 | 单细胞或单核RNA测序与细胞通讯分析；原位或移植瘤模型与免疫检查点联合干预 |
| 50 | PSAT1 integrates ferroptosis resistance and immune evasion to drive hepatocellular carcinoma progression | 细胞与分子生物学实验；动物模型与体内干预 | 分子互作与通路机制实验（Co-IP、ChIP、RNA-seq）；原位或移植瘤模型与免疫检查点联合干预 |

## 不限年限逐篇归类表

| ref | 论文 | 一级：数据获取方法族 | 二级：具体技术 |
|---:|---|---|---|
| 1 | Sphingolipid synthesis in tumor-associated macrophages confers immunotherapy resistance in hepatocellular carcinoma | 细胞与分子生物学实验；动物模型与体内干预 | 分子互作与通路机制实验（Co-IP、ChIP、RNA-seq）；原位或移植瘤模型与免疫检查点联合干预 |
| 2 | Overcoming immunotherapy resistance in hepatocellular carcinoma by targeting myeloid IL-8/CXCR2 signaling | 单细胞与空间多组学；动物模型与体内干预 | 治疗前后活检单细胞RNA测序；原位或移植瘤模型与免疫检查点联合干预 |
| 3 | Lactylation-driven MVP upregulation boosts immunotherapy resistance by inhibiting PD-L1 degradation in hepatocellular carcinoma | 细胞与分子生物学实验；动物模型与体内干预 | 分子互作与通路机制实验（Co-IP、ChIP、RNA-seq）；原位或移植瘤模型与免疫检查点联合干预 |
| 4 | Exploring the role of the immune microenvironment in hepatocellular carcinoma: Implications for immunotherapy and drug resistance | 文献语料与证据综合 | 叙述性综述与机制证据归纳 |
| 5 | Mechanisms of Resistance to Immunotherapy in Hepatocellular Carcinoma | 文献语料与证据综合 | 叙述性综述与机制证据归纳 |
| 6 | Next-Generation Immunotherapy for Hepatocellular Carcinoma: Mechanisms of Resistance and Novel Treatment Approaches | 文献语料与证据综合 | 叙述性综述与机制证据归纳 |
| 7 | POSTN + CAF-Derived Migrasomes Drive Hepatocellular Carcinoma Progression and Confer Resistance to Immunotherapy | 公共组学数据与二次分析；细胞与分子生物学实验 | TCGA、GEO、ICGC联合生物信息学分析；细胞功能与免疫表型实验（共培养、流式、qPCR、Western blot） |
| 8 | Phocaeicola vulgatus induces immunotherapy resistance in hepatocellular carcinoma via reducing indoleacetic acid production | 临床样本与治疗队列；动物模型与体内干预 | 粪便宏基因组或16S rRNA测序；粪菌移植与菌群定植实验 |
| 9 | Immunotherapy resistance in MASLD-related hepatocellular carcinoma: special immune microenvironment and gut microbiota | 文献语料与证据综合 | 叙述性综述与机制证据归纳 |
| 10 | Spatial multi-omics and deep learning reveal fingerprints of immunotherapy response and resistance in hepatocellular carcinoma | 单细胞与空间多组学 | 空间转录组与空间蛋白组联合分析；可解释图神经网络疗效预测 |
| 11 | Hypomethylation-enhanced CRTC2 expression drives malignant phenotypes and primary resistance to immunotherapy in hepatocellular carcinoma | 细胞与分子生物学实验；动物模型与体内干预 | 分子互作与通路机制实验（Co-IP、ChIP、RNA-seq）；原位或移植瘤模型与免疫检查点联合干预 |
| 12 | Bacteroidetes promote hepatocellular carcinoma progression and resistance to immunotherapy | 临床样本与治疗队列；动物模型与体内干预 | 粪便宏基因组或16S rRNA测序；粪菌移植与菌群定植实验 |
| 13 | Acquired Genetic Variants, Not Tumor Mutation Burden, Drive Resistance to Immunotherapy in Hepatocellular Carcinoma | 临床样本与治疗队列 | 治疗前后ctDNA二代测序 |
| 14 | Immunotherapies for hepatocellular carcinoma | 其他（未明确方法） | 摘要未提供方法细节 |
| 15 | Advances in immunotherapy for hepatocellular carcinoma | 文献语料与证据综合 | 叙述性综述与机制证据归纳 |
| 16 | β-Catenin Activation Promotes Immune Escape and Resistance to Anti–PD-1 Therapy in Hepatocellular Carcinoma | 细胞与分子生物学实验；动物模型与体内干预 | 分子互作与通路机制实验（Co-IP、ChIP、RNA-seq）；基因工程或基因敲除动物模型 |
| 17 | Cancer cell-derived exosomal circUHRF1 induces natural killer cell exhaustion and may cause resistance to anti-PD1 therapy in hepatocellular carcinoma | 细胞与分子生物学实验；临床样本与治疗队列 | 外泌体分离与非编码RNA互作实验；组织芯片、免疫组化与预后分析 |
| 18 | CXCR4 inhibition in tumor microenvironment facilitates anti‐programmed death receptor‐1 immunotherapy in sorafenib‐treated hepatocellular carcinoma in mice | 动物模型与体内干预 | 原位或移植瘤模型与免疫检查点联合干预 |
| 19 | Tumor microenvironment-mediated immune evasion in hepatocellular carcinoma | 文献语料与证据综合 | 叙述性综述与机制证据归纳 |
| 20 | The Current Landscape of Immune Checkpoint Blockade in Hepatocellular Carcinoma: A Review | 文献语料与证据综合 | 叙述性综述与机制证据归纳 |
| 21 | Exosome-derived circCCAR1 promotes CD8 + T-cell dysfunction and anti-PD1 resistance in hepatocellular carcinoma | 细胞与分子生物学实验；动物模型与体内干预 | 外泌体分离与非编码RNA互作实验；原位或移植瘤模型与免疫检查点联合干预 |
| 22 | The long noncoding RNA lnc-EGFR stimulates T-regulatory cells differentiation thus promoting hepatocellular carcinoma immune evasion | 细胞与分子生物学实验；动物模型与体内干预 | 细胞功能与免疫表型实验（共培养、流式、qPCR、Western blot）；原位或移植瘤模型与免疫检查点联合干预 |
| 23 | Tumor-derived exosomal HMGB1 fosters hepatocellular carcinoma immune evasion by promoting TIM-1+ regulatory B cell expansion | 临床样本与治疗队列；细胞与分子生物学实验 | 临床组织流式细胞术与生存分析；外泌体分离与非编码RNA互作实验 |
| 24 | Immunomodulatory TGF-β Signaling in Hepatocellular Carcinoma | 文献语料与证据综合 | 叙述性综述与机制证据归纳 |
| 25 | Inflamed and non-inflamed classes of HCC: a revised immunogenomic classification | 临床样本与治疗队列 | 免疫基因组分型与多队列验证 |
| 26 | PD-1/PD-L1 checkpoint inhibitors in advanced hepatocellular carcinoma immunotherapy | 文献语料与证据综合 | 叙述性综述与机制证据归纳 |
| 27 | Immune Exclusion-Wnt/CTNNB1 Class Predicts Resistance to Immunotherapies in HCC | 文献语料与证据综合 | 叙述性综述与机制证据归纳 |
| 28 | Immunotherapy of Hepatocellular Carcinoma: Facts and Hopes | 文献语料与证据综合 | 叙述性综述与机制证据归纳 |
| 29 | Dissecting spatial heterogeneity and the immune-evasion mechanism of CTCs by single-cell RNA-seq in hepatocellular carcinoma | 单细胞与空间多组学；细胞与分子生物学实验 | 单细胞或单核RNA测序与细胞通讯分析；分子互作与通路机制实验（Co-IP、ChIP、RNA-seq） |
| 30 | Targeting SRSF10 might inhibit M2 macrophage polarization and potentiate anti‐PD‐1 therapy in hepatocellular carcinoma | 细胞与分子生物学实验；动物模型与体内干预 | 分子互作与通路机制实验（Co-IP、ChIP、RNA-seq）；原位或移植瘤模型与免疫检查点联合干预 |
| 31 | Hepatoma-intrinsic CCRK inhibition diminishes myeloid-derived suppressor cell immunosuppression and enhances immune-checkpoint blockade efficacy | 临床样本与治疗队列；动物模型与体内干预 | 临床组织流式细胞术与生存分析；原位或移植瘤模型与免疫检查点联合干预 |
| 32 | Immune checkpoint inhibitor resistance in hepatocellular carcinoma | 其他（未明确方法） | 摘要未提供方法细节 |
| 33 | Strategies to Improve the Antitumor Effect of Immunotherapy for Hepatocellular Carcinoma | 文献语料与证据综合 | 叙述性综述与机制证据归纳 |
| 34 | Mitochondrial TSPO Promotes Hepatocellular Carcinoma Progression through Ferroptosis Inhibition and Immune Evasion | 细胞与分子生物学实验；动物模型与体内干预 | 分子互作与通路机制实验（Co-IP、ChIP、RNA-seq）；原位或移植瘤模型与免疫检查点联合干预 |
| 35 | TP53/mTORC1-mediated bidirectional regulation of PD-L1 modulates immune evasion in hepatocellular carcinoma | 细胞与分子生物学实验；动物模型与体内干预 | 分子互作与通路机制实验（Co-IP、ChIP、RNA-seq）；原位或移植瘤模型与免疫检查点联合干预 |
| 36 | The association between tumour heterogeneity and immune evasion mechanisms in hepatocellular carcinoma and its clinical implications | 文献语料与证据综合 | 叙述性综述与机制证据归纳 |
| 37 | MYC Overexpression Drives Immune Evasion in Hepatocellular Carcinoma That Is Reversible through Restoration of Proinflammatory Macrophages | 细胞与分子生物学实验；动物模型与体内干预 | 分子互作与通路机制实验（Co-IP、ChIP、RNA-seq）；原位或移植瘤模型与免疫检查点联合干预 |
| 38 | Trajectory of immune evasion and cancer progression in hepatocellular carcinoma | 临床样本与治疗队列；动物模型与体内干预 | 治疗队列与临床样本关联分析；基因工程或基因敲除动物模型 |
| 39 | HKDC1 promotes tumor immune evasion in hepatocellular carcinoma by coupling cytoskeleton to STAT1 activation and PD-L1 expression | 细胞与分子生物学实验；动物模型与体内干预 | 分子互作与通路机制实验（Co-IP、ChIP、RNA-seq）；原位或移植瘤模型与免疫检查点联合干预 |
| 40 | Metabolic reprogramming in hepatocellular carcinoma: mechanisms of immune evasion and therapeutic implications | 文献语料与证据综合 | 叙述性综述与机制证据归纳 |
| 41 | HMMR triggers immune evasion of hepatocellular carcinoma by inactivation of phagocyte killing | 细胞与分子生物学实验；动物模型与体内干预 | 细胞功能与免疫表型实验（共培养、流式、qPCR、Western blot）；基因工程或基因敲除动物模型 |
| 42 | RBM30 recruits DOT1L to activate STAT1 transcription and drive immune evasion in hepatocellular carcinoma | 细胞与分子生物学实验 | 分子互作与通路机制实验（Co-IP、ChIP、RNA-seq） |
| 43 | Targeting Gsk3a reverses immune evasion to enhance immunotherapy in hepatocellular carcinoma | 细胞与分子生物学实验；动物模型与体内干预 | CRISPR筛选或基因编辑功能验证；原位或移植瘤模型与免疫检查点联合干预 |
| 44 | RNA Methyltransferase FTSJ3 Regulates the Type I Interferon Pathway to Promote Hepatocellular Carcinoma Immune Evasion | 细胞与分子生物学实验；动物模型与体内干预 | 分子互作与通路机制实验（Co-IP、ChIP、RNA-seq）；原位或移植瘤模型与免疫检查点联合干预 |
| 45 | C-X-C chemokine receptor 2 (Cxcr2) promotes hepatocellular carcinoma immune evasion via regulating programmed death-ligand 1 (PD-L1) | 细胞与分子生物学实验；动物模型与体内干预 | CRISPR筛选或基因编辑功能验证；原位或移植瘤模型与免疫检查点联合干预 |
| 46 | Tissue-resident peripheral helper T cells foster hepatocellular carcinoma immune evasion by promoting regulatory B-cell expansion | 临床样本与治疗队列；细胞与分子生物学实验 | 临床组织流式细胞术与生存分析；细胞功能与免疫表型实验（共培养、流式、qPCR、Western blot） |
| 47 | Elemental selenium promotes PD-L1 lysosomal degradation to enhance antitumor immunotherapy | 细胞与分子生物学实验；动物模型与体内干预 | 分子互作与通路机制实验（Co-IP、ChIP、RNA-seq）；原位或移植瘤模型与免疫检查点联合干预 |
| 48 | Chronic Stress Associated Indoxyl Sulfate Upregulation Exhausts CD8 + T Cells to Decrease the Efficiency of Anti‐PD‐1 in Hepatocellular Carcinoma | 临床样本与治疗队列；动物模型与体内干预 | 治疗队列与临床样本关联分析；原位或移植瘤模型与免疫检查点联合干预 |
| 49 | Carbonic anhydrase 2 positive tumor-associated endothelial cells contribute to anti-PD-1 therapy resistance through TREM2⁺ macrophages in hepatocellular carcinoma | 单细胞与空间多组学；动物模型与体内干预 | 单细胞或单核RNA测序与细胞通讯分析；原位或移植瘤模型与免疫检查点联合干预 |
| 50 | PSAT1 integrates ferroptosis resistance and immune evasion to drive hepatocellular carcinoma progression | 细胞与分子生物学实验；动物模型与体内干预 | 分子互作与通路机制实验（Co-IP、ChIP、RNA-seq）；原位或移植瘤模型与免疫检查点联合干预 |

### 图谱真实性与浏览器实测

- 不限年限：池内论文 50；真实互引边 50；因素→结局边 29；语义关系边 13。
- 2023年以来：池内论文 50；真实互引边 34；因素→结局边 24；语义关系边 9。
- 引用边已逐条回对 `referenced_works`，未补边；因素投票见 `graph_evidence.md`，语义关系证据见 `relations_evidence.md`。
- 2026-11-22 浏览器实测：`index.html` 双入口可见；满血版范围切换正常；引用网络结点、因素结点、方法叶子、语义关系结点与连线均能打开论文/证据面板；未出现控制台错误。
- 轻量版首次实测发现长图 URL 误把绝对路径当文件名拼接，已改用同目录文件名重新生成并复验：PNG naturalWidth=1000、naturalHeight=8419，加载成功；当前页面无脚本错误。
- 流程问题清单另存 `process_issues.md`。

## 提纲、写作与交付复核

- 已先生成 `outline.md`（格局速览表、空白证据表、四张方向卡、完整第一方向卡样章），并在对话展示提纲链接与样章；未等待确认，按规则连续生成 `综述初稿.md`。
- 正文与台账生成后运行预置 `verify_delivery.py 综述初稿.md 1500-2500 --mode A`。首次仅模式形态失败：空白证据行格式与全景树缺项；补齐后重跑通过。参考文献元数据修订后再次重跑，最终全部 9 项无失败，正文 2466 CJK 字，详见 `verify_report.txt`。
- 首次 `verify_references.py` 在第 18 篇后的 DataCite 请求遇 TLS EOF，未生成报告；第二次原样重试完成 50 篇，报告为 `references_check.md`：通过 8、需人工核对 42、回填 44、撤稿/更正关联 2。
- 按核验结果回填 44 条卷期页；ref 26 刊名改为 Cancer Communications；ref 28、31、47、49 的姓名格式人工修正。ref 19 DOI 未收录、ref 47 年份 2026/2027 不一致，保留人工核对。ref 27 为 Erratum、ref 30 为 Correction，均非撤稿，已在交付说明披露。
- 最终需求对账见 `conformance.md`，网页逐步对照见 `web_sample_map.md`，流程问题见 `process_issues.md`。

