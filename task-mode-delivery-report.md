# 四模式真实离线交付回归与最小修复报告

## 1. 范围与约束

本次在原始项目最新主线的工作副本上完成最小修复，并已把授权文件同步回原始目录。保留主线新增的 D PPT 资产、主题命名、结构核验、版式核验及统计数据附加逻辑。

实际修改范围：

- `backend/app/writing.py`：台账引用列统一为裸编号。
- `backend/app/orchestration.py`：实现真实 C1+C2 衔接检查、重复段处理、根目录复核与合并门禁；保留主线 `stats.json` 附加逻辑。
- `backend/tests/test_writing.py`、`backend/tests/test_orchestration.py`：更新对应回归。
- `backend/tests/test_mode_delivery_regression.py`、`backend/tests/fixtures/modes/`：四模式真实离线 fixture 与专项回归。
- `task-mode-delivery-report.md`：本报告。

未修改 `delivery.py`、预置 `skill_runtime/scripts/verify_delivery.py`、D 的 PPT 资产/结构核验代码、`main.py`、`models.py`、`graphs.py`、前端源码或限流文件。未部署、未在线检索、未进行在线著录检查、未调用付费模型。

## 2. 真实 fixture 与证据边界

B、C1、C2、D 每套均包含 `papers.json`、`evidence.json`、`body_evidence.json`、`components.json`、`body.md`，共 20 个 fixture 文件。

四篇论文逐字段复用项目真实快照 `fixtures/hcc-20261122/papers.json` 的前四篇，测试回源比较题名、摘要、作者、年份、期刊、类型和撤稿字段：

1. `10.1126/sciadv.adv0558`：巨噬细胞鞘脂代谢与免疫治疗耐药。
2. `10.1016/j.ymthe.2025.02.002`：髓系 IL-8/CXCR2 与免疫治疗耐药。
3. `10.1136/jitc-2025-012230`：乳酸化、MVP 与 PD-L1 降解。
4. `10.7554/elife.95009`：肝细胞癌免疫微环境、免疫治疗与耐药综述。

每个模式有 15 条证据记录。`WritingService` 的摘要审计和独立 fixture 回源测试均要求 quote 逐字包含于对应真实摘要。模型只读取本地 fixture，著录检查器只核对本地必需字段、DOI 形式与撤稿标记。

## 3. 台账漏读修复

`WritingService` 原来把引用列写成 `| [1] |`，预置校验器只接收 `cells[1].isdigit()` 为真的 `| 1 |`，导致原始报告显示“台账: 0条”，C1/C2 进一步误报正文引用与台账为空。

本次只修改生产输出为裸编号，不修改预置校验器，也不保留 normalized-ledger 兼容复跑。`test_writing.py` 精确断言裸编号且禁止 `| [1] |`；四模式专项直接核验原始交付报告。

实测四模式原始报告均为：

- `台账: 15条`，不再是 0 条；
- `15/15 条摘要原句逐字命中`；
- 正文预置复核无 `[FAIL]`；
- B、C1、C2 的 `DeliveryResult.clean=True`；D 的总体状态另受第 7 节主线 PPT 结构缺陷影响，不能写成 clean。

## 4. C1+C2 真实衔接门禁

`orchestration.py` 现在执行以下实际检查，而不是写固定“衔接完成”字符串：

1. 按两种精确五列表头分别解析 C1、C2 的 Research Gap 表，要求两表均存在有效数据行，方向、空白点不得为空，引用不得缺失。
2. 以“归一化研究方向＋归一化现有不足＋排序后的引用集合”逐项比较两表。
3. 按空行分段、移除全部空白，检查长度至少 50 的非标题、非表格长段落交集。
4. 对重复段选择保留位置：本文定位内容优先留 C1，领域证据优先留 C2；另一处真实替换为“概括＋交叉指向”，随后重新检测重复。
5. 将两表明细、签名比对结果、原始重复数、保留/改写位置、处理后重复数、独立交付状态和根目录复核状态写入 `linkage_check.md`。
6. 在合并根目录分别运行原预置 C1、C2 校验；C2 同目录存在 C1，因此原预置衔接说明和零重复长段门禁也实际执行。
7. 只有独立交付、真实衔接检查、根目录 C1/C2 复核全部通过，才调用合并 `DeliveryService.deliver`。任一失败均返回 `combined_delivered=False`，不生成新的合并 Word/PPT。

### 有效路径实测

- C1、C2 两张 Gap 表均有“多机制对解”和“动态分层”两行，空白点与引用分别一致为 `[1][2][3]`、`[2]`。
- 原始归一化重复长段 0，处理后剩余 0。
- 两份根目录报告均为 15 条、15/15 摘要命中、无失败；C2 报告明确包含 `C1+C2 衔接与重复检查` 和 `C1+C2 无重复段落（实得 0 段）`。
- 合并报告为 30 条、30/30 摘要命中、无失败。
- 最终门禁为“通过，允许合并交付”，`checkpoint.clean=True`、`combined_delivered=True`。

### 异常与重复处理回归

- 故意把 C1 第一行引用从 `[1][2][3]` 改为 `[1][2]`：独立报告及根目录 C1/C2 报告仍可通过，但真实 Gap 比对失败，`linkage_check.md` 写明“未通过，禁止合并交付”；合并 `综述初稿.md`、`report.docx`、`slides.pptx` 均不存在。
- 在 C1/C2 注入仅空白和单换行不同的同一长段：识别原始重复 1 段；领域证据保留在 C2，C1 改为“概括：该领域证据段保留在 C2《文献综述》中；此处仅作交叉指向，不再重复铺陈。”；处理后重复 0，C2 原预置复核再次通过，合并 Office 可重开。

## 5. 字数、结构与 Office 实测

CJK 字数不含参考文献；C1/C2 同时列出预置校验器的“CJK 汉字＋英文词”口径。以下数字来自最终专项产物，Word/PPT 均由真实 `DeliveryService` 生成后用 `python-docx`、`python-pptx` 重新打开。

| 模式 | CJK 字数（要求） | 预置字数 | 原始台账/摘要 | Word 重开 | PPT 重开 | 交付状态 |
|---|---:|---:|---|---:|---:|---|
| B | 2808（2000–3000） | 2808 | 15 条，15/15 | 63 段 | 12 页 | clean |
| C1 | 1087（800–1200） | 1096 | 15 条，15/15 | 42 段 | 12 页 | clean |
| C2 | 1164（800–1200） | 1189 | 15 条，15/15 | 53 段 | 12 页 | clean |
| D | 4181（3000–6000） | 4181 | 15 条，15/15 | 96 段 | 24 页 | 总体非 clean，见第 7 节 |

结构回归仍覆盖：

- B：项目字段、刚性需求、可复用资产清单、不足—科学问题—研究内容对解表、三项研究内容、技术路线、可行性、预期成果和六段论证链。
- C1：五张段落卡、Research Gap 表、五段完整引言、第三段空白及引用、第四/五段研究思路与贡献；不混入 C2 完整综述。
- C2：检索范围、关键词、代表文献、七维分类、综合分析、技术路线、六列比较表、五列空白表、未来方向和完整综述；不合并成 Discussion。
- D：九段结构、方法对比、3 张精读页、阅读深度、选题排序和组会讨论问题；PPT 抽取文本预置复核为 2826 CJK，无文本核验失败。

C1+C2 有效合并正文为 2257 CJK，合并报告 30/30，Word 重开 90 段，PPT 重开 12 页。重复段处理用例的合并 Word 重开 92 段，PPT 重开 12 页。

## 6. D 的结构性编号 3

D 的最终原始报告只剩一个未绑定数字：

`3（句引[1, 2, 3]）未绑定台账原句——待人工确认是否结构性/标识符数字`

它来自组会讨论第 3 问“乳酸化—MVP—PD-L1 机制应在哪一层与髓系指标对解……”的题号，不是实验数值或新增论断。保留该问题、原报告警告及专项断言，不删除、不补假摘要证据、不改写成假通过。

## 7. 未解决的主线 D PPT 结构缺陷

最新主线新增的资产清单把首个“核心方法与技术路线”页声明为 `kind=diagram`、`min_shapes=4`，但该页实际使用 `layout=table`。表格主要位于 `p:graphicFrame`，预置结构脚本统计 `p:sp`，因此实际生成的表格页被判定缺少流程图形。

最终真实 fixture 的证据为：

- PPT 实际生成并重开 24 页，含 1 个原生图表；版式轮转 `layout_check.json.ok=True`。
- `verify_ppt_report.txt` 其余 21 项通过，唯一失败为 `FAIL 核心方法与技术路线：P11 包含框架/流程图形`，总结为 `结果：FAIL（通过 21，降级 0，失败 1）`。
- 全量后端既有测试的另一套 D fixture 在 P10 复现同类失败。
- `DeliveryResult.failures == ['PPT 结构或图表核验未通过']`，总体 `clean=False`。

该缺陷位于用户明确要求不要修改的 `delivery.py` 与 D PPT 资产/结构核验路径。本次只记录并用专项断言复现，没有修改业务实现或把失败改成通过。

## 8. 最终测试结果与同步状态

专项命令：

```bash
.venv/bin/python -m pytest -q backend/tests/test_mode_delivery_regression.py \
  --basetemp="/Users/crisprcas_9/Documents/kimi/tasks/2026-11-24/08-48-49-3e31124a/final-mode-artifacts"
```

结果：`11 passed in 1.75s`。其中包括四项真实来源回验、B/C1/C2/D 交付、有效 C1+C2、Gap 不一致阻断、归一化重复处理。D 用例通过表示上述结构缺陷被精确复现且其他证据/Office 断言通过，不表示 D 总交付 clean。

全量命令：

```bash
.venv/bin/python -m pytest -q backend/tests \
  --basetemp="/Users/crisprcas_9/Documents/kimi/tasks/2026-11-24/08-48-49-3e31124a/final-full-artifacts"
```

结果：`1 failed, 238 passed, 1 skipped in 12.08s`。唯一失败为既有 `test_d_ppt_has_twenty_to_thirty_slides_and_separate_text_verification`，原因是第 7 节的真实 `verify_ppt_report.txt` 非 PASS。唯一跳过为 `RUN_LIVE_OPENALEX_SMOKE` 控制的在线冒烟测试，离线约束下未启用。

授权代码、测试和 fixtures 已同步至 `/Users/crisprcas_9/WorkBuddy/2026-11-06-20-49-06/purpose-landscape-web`；最终测试在同步后的工作副本上运行。未同步临时测试产物、数据库、前端或禁止修改的文件。

## 9. 证据位置与剩余边界

- 有效 C1+C2 `linkage_check.md`：`/Users/crisprcas_9/Documents/kimi/tasks/2026-11-24/08-48-49-3e31124a/final-mode-artifacts/test_c1_c2_have_separate_repor0/c-pair-offline/linkage_check.md`。
- 重复处理 `linkage_check.md`：`/Users/crisprcas_9/Documents/kimi/tasks/2026-11-24/08-48-49-3e31124a/final-mode-artifacts/test_c_pair_normalized_duplica0/c-pair-offline/linkage_check.md`。
- Gap 不一致阻断 `linkage_check.md`：`/Users/crisprcas_9/Documents/kimi/tasks/2026-11-24/08-48-49-3e31124a/final-mode-artifacts/test_c_pair_gap_mismatch_block0/c-pair-offline/linkage_check.md`。
- D 结构核验：`/Users/crisprcas_9/Documents/kimi/tasks/2026-11-24/08-48-49-3e31124a/final-mode-artifacts/test_d_real_offline_delivery_a0/d-offline/verify_ppt_report.txt`。

所有精读仍为摘要级，未核对全文实验参数、样本量、图表和补充材料。离线著录检查不证明外部数据库当前状态。未验证真实模型服务质量、提示词泛化或在线检索覆盖率。除上述主线 D PPT 结构缺陷外，本次授权修复范围内没有新增未解决失败。
