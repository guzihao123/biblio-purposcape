# C 模式 C2 正文结构不合格修复报告（site23-c2-structure，2026-11-26）

## 1. 背景与验收口径

C6 线上验收失败（`/private/tmp/bcd-live-C6-20261126/artifacts/verify_report.txt`）：

- ⑤字数 FAIL：正文 CJK 汉字+英文词 = 1331，超出 800–1200 上限；
- ⑧模式形态（--mode C2）FAIL：缺独立综述构件「研究主题与检索范围」「关键词和检索策略」「代表性文献清单」「文献分类框架」「完整综述文本」，文献分类框架内缺全部七维（理论基础/研究对象/研究问题/技术方法/数据与实验/研究结论/研究局限），缺六列文献比较表与五列研究空白分析表。

机械口径以 `skill_runtime/scripts/verify_delivery.py --mode C2` 为准。

## 2. 根因

1. **提纲标题与验收口径冲突（提示词层）**：`backend/app/writing.py` 的 `OUTLINE_HEADINGS['C2']` 使用旧节名（「研究范围与检索策略」「分类框架」「未来方向」「完整综述」），而正文写作模型拿到的提纲来自该常量；`skill_runtime/templates/C2_文献综述骨架.md` 与 verify 的 ⑧ 检查使用另一套精确节名（「研究主题与检索范围」…「完整综述文本」）。模型按提纲写，产出与骨架、verify 三方口径不一致 → 节名整体错位。
2. **正文生成后无任何确定性结构校验/修复（机制层）**：`write_body` 只校验引文覆盖与材料引用，C2_BODY_RULE（提交 65dae84）只是系统提示词，模型不守约时（C6 即如此，且走了证据修复早退路径）不合格正文原样落盘。
3. **C6 的构件数据本身退化**：`components.md`（component JSON）中 `comparison`/`gaps` 行的 `evidence` 全部缺失，`_validate_component_shape` 对 C2 只查行数不查每行证据，退化构件被放行，导致五列空白表的「文献证据」列无从附着池内 [n]。

结论：仅改提示词无法解决（C6 已带 C2_BODY_RULE 仍失败），必须生成后确定性校验 + 构件驱动的确定性兜底重建。

## 3. 改动（均在 worktree 分支 `site23-c2-structure`，未部署）

`backend/app/writing.py`：

1. `OUTLINE_HEADINGS['C2']` 改为与 `C2_文献综述骨架.md` 完全一致的 12 个精确节名（「研究主题与检索范围」…「完整综述文本」「衔接与重复检查」），消除提纲-模板-verify 三方口径冲突。
2. 新增 C2 结构口径模块（镜像 verify_delivery.py ⑧/⑤ 机械检查）：
   - `_c2_word_count`：与 verify ⑤同口径（不含参考文献，CJK 汉字+英文词）；
   - `_c2_body_shape_errors(text, check_count=True)`：六大独立构件、七维位于「文献分类框架」节内、综合分析/技术路线比较/现有研究不足、完整综述文本实质引用且纳入研究空白、六列比较表精确表头+完整数据行、五列空白表精确表头+完整数据行+[n] 证据、禁 Discussion/禁要求本文结果、字数 800–1200；
   - `_c2_has_filled_table` / `_c2_named_section`：与 verify 同算法。
3. `write_body` 三条返回路径（正常路径、证据修复路径、引用修复路径）在标注「据摘要」后对 model-backed C2 正文跑结构校验，不合格抛 `WritingInputError` 触发重试。
4. 重试穷尽后确定性兜底 `_rebuild_c2_body`：用 `_render_c2_body_in_range` 从 `component_data`（已证据审计）重建正文，档位式收紧行数/单元格截断长度（`_C2_TRIM_PROFILES`，按标注后字数测量，6 档），绝不删章节/表头规避；重建文本再经结构校验、引文覆盖校验、材料引用校验，并记录 `c2_body_rebuilt` 事件。内容为构件字段与 search_overview 的确定性重排，不新增任何文献事实。
5. `_validate_component_shape` 的 C2 分支新增：comparison/gaps 每行必须带 evidence refs（与 COMPONENT_SCHEMAS 的 evidence 要求一致），退化构件在构件阶段即被拒并重试。
6. 兜底重建前用 `_strip_unsupported_citations` 剔除重建文本中无台账覆盖的 [n]（不虚构台账条目）。

`backend/tests/test_c2_body_structure.py`（新增回归）：

- fake model 返回「节名错位、无七维、无两张强制表、1331 字」的 C6 式正文 → 断言产出不再是原文、重试 2 次、`c2_body_rebuilt` 事件、结构错误为空、字数 ≤1200（修复前该正文会原样通过，测试红→绿）；
- 结构齐全但 1597 字正文 → 断言压回 800–1200；
- 合规正文 → 断言原样透传、无重建事件（防“永远重建”退化）；
- 提纲节名与模板/verify 口径一致。

`backend/tests/test_cmode_finish.py`：第 147 行断言随新提纲口径更新（`衔接与重复检查` 收尾、含 `完整综述文本`），语义加强未削弱。

## 4. 测试结果（项目 .venv，Python 3.9.6）

- `backend/tests/test_c2_body_structure.py`：4 passed；
- 相关文件（test_writing / test_cmode_finish / test_delivery 等）：全量 `backend/tests` **661 passed, 5 skipped**（两次全量运行结果一致）；
- 测试运行产生的 `backend/tests/fixtures/worker/results/*.json` 变更已按任务要求 `git checkout` 还原。

## 5. C6 产物离线复现（未调用真实模型/线上接口）

复现脚本 `/private/tmp/c2-offline-repro-20261126/repro.py`，验证材料全部来自 C6 artifacts 与仓库内真实脚本：

- **场景 1（事故复现）**：原样 C6 `C2_文献综述.md` + papers.json + evidence_ledger.md 跑 `verify_delivery.py C2_文献综述.md 800-1200 --mode C2` → exit 1，⑤字数=1331 FAIL、⑧模式形态 FAIL（缺五大构件/七维/两表），与 C6 线上报告一致（⑥ citation_map.json 缺失系 artifacts 目录未保留该文件，属复现环境差异，C6 当时已通过）。
- **场景 2（退化构件被新校验拒绝）**：C6 components.json 的 comparison 行无 evidence refs → `_validate_component_shape` 抛 `mode C2 comparison row 1 requires evidence refs`。
- **场景 3（台账回填后重建并通过）**：按「台账原句最长连续词片段（≥4 词）出现在行文本内」的确定性规则，用 evidence_ledger.md 给 C6 gaps 回填引用（[15]/[5]/[20]，均有台账原句逐字支撑，无虚构）→ `_render_c2_body_in_range` 重建 → 拼接参考文献 → `renumber_citations.py` → `verify_delivery.py --mode C2` → **exit 0，全部 9 项 PASS，⑤字数=1102**，六构件/七维/两表齐全，空白表保留 2 行带 [n] 证据。
- **边界说明**：C6 components.json 的 classification 含 `[3, 19]` 这类多引用括注，verify 与重建管线只认单 `[n]` 形态，重建正文保留了括注原文（不删信息）；台账回填规则是离线构造验证材料用的确定性匹配，线上管线由构件形状校验保证每行自带证据，不需要该回填。

## 6. 仍需主线程部署后处理的事项

1. 主线程合并本分支并部署后端后，用真实模型重跑一个 C 模式任务（或重跑 C7 全链路），确认线上 C2 正文：节名口径一致、结构校验触发正常、`c2_body_rebuilt` 事件可观测；
2. C6 的历史产物不会因本修复自动变好——若需重新交付 C6，须重跑 C2 生成（新代码下构件退化会被拒并重试，不会再静默放行）；
3. 兜底重建是「结构正确但文笔模板化」的下限产物：正常路径仍优先采用模型正文（合规即透传），重建比例应在 C7 复跑时通过事件日志复核；
4. 字数下限 800 依赖池内证据量：退化小池（证据不足以支撑 800 字）时兜底只能保证结构与「不超 1200」，不虚构凑字，此时该次生成会以错误上抛而非交付不合格正文。

## 7. 风险

- 重建正文为确定性模板文风，若线上频繁触发兜底，说明提示词/模型仍不稳定，应另行治理（本修复保证的是「不合格不交付」）；
- `_C2_TRIM_PROFILES` 的档位按当前构件字段长度校准，若构件字段平均长度显著增长，最末档仍可能超 1200——此时重建返回 None、任务报错而非假 PASS，风险可控；
- 结构校验镜像了 verify 当前口径，verify ⑧ 口径若再变更需同步 `_c2_body_shape_errors`。

## 8. C7 上线复核清单（B6 终态、合并 8c29eb6 + b0d59d9 并部署后执行）

1. **C7 命令**：`run_bcd_acceptance.py C --form A --c-route C2 --live`，使用新输出目录，不得覆盖 C6 产物目录。
2. **verify 必查**：在新目录跑 `verify_delivery.py C2_文献综述.md 800-1200 --mode C2`，确认八项报告中 ①–⑧ **全部 PASS**；重点复核 ⑤字数落在 800–1200；⑧ 中六大独立综述构件、七维分类（位于「文献分类框架」节内）、六列文献比较表、五列研究空白分析表（含池内 [n] 证据）齐全。
3. **`c2_body_rebuilt` 事件必查**：检索任务事件日志——
   - 若存在该事件：记录触发原因（payload.reason）与本次 C7 的重建比例（重建次数 / C2 任务数），并**人工抽查重建正文的文风与事实表述**；
   - 若不存在：说明模型正文一次通过结构校验，记录为「模型直出合格」。
4. **判定口径**：即使 verify 全部 PASS，只要触发了兜底重建，本次 C7 只能判「结构合格、文风待人工复核」，不得直接判内容质量通过；未触发重建且 verify 全 PASS 才可判「结构与机械口径通过」。
5. **C6 历史产物说明（保留）**：C6 的历史产物不会因本修复自动变好——不重跑就不会变好；如需重新交付 C6，必须用部署后的新代码重跑 C2 生成（构件退化会被拒并重试，不再静默放行）。
