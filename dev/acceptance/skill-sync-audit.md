# Skill 同步差异审计（2026-11-25）

对比对象：`~/.qoder-cn/skills/purpose-landscape`（最新 Skill） vs `purpose-landscape-web` 实现。只读审计，不改代码。

## 一、已对齐（本轮修复或此前已实现）

| 区域 | 最新 Skill 要求 | 网页实现 | 证据 |
|---|---|---|---|
| 方向卡示例 | 四个固定交通管理工程主题 | 已改为交通四题，占位符同步 | `backend/app/task_presenters.py`、`backend/tests/test_task_api.py::test_direction_card_uses_fixed_traffic_examples` |
| 年限卡 | 2026-11-23 去推荐标记 | 已移除“（推荐）”，D 模式仍置顶 | `backend/app/task_presenters.py`、`test_task_presenters.py` |
| 交付卡字母 | 字母=位置，形态文案不变 | 按模式重排并按位置重标 A/B/C | 同上 |
| A 仅对话 | 七类×2 槽位、1500–4000 字、A_DIALOGUE 复核 | 七类常量、2 槽位校验、字数区间、模板与复核脚本均已具备 | `backend/app/writing.py`、`backend/app/delivery.py:15-21`、`skill_runtime/templates/A_对话选题骨架.md`、`skill_runtime/scripts/verify_delivery.py`（与 Skill 同哈希） |
| A 默认 | 3–5 方向、四维、空白证据行 | 已通过本地真实运行 9/9 复核 | `deliverables/local-e2e-20261125/verify_report.txt` |
| D PPT | 20–30 页、1/2/3/4/5/6/8 部分、精读 3–5、总结优先方向与下一步、资产清单、版式轮换 | 已实现并有 fixture 回归；趋势页存在 | `backend/app/delivery.py::_d_slides`、`verify_ppt_delivery.py`、`test_mode_delivery_regression.py` |
| Word/PPT 文件名 | A/C/E=综述初稿.docx；B=标书-文献综述分析.docx；D=调研报告.docx；PPT=<主题>组会汇报.pptx | 本轮已改为固定文件名（此前通用 report.docx/slides.pptx） | `backend/app/delivery.py:14-22,776-781`、前端下载标签 |
| 复核脚本 | 与 Skill 同步 | `verify_delivery.py` 与 Skill 逐字节一致 | sha256 `6dd22bb7c8bb` |

## 二、未对齐（按影响排序）

1. **C 模式两张固定卡未实现（高）**
   - Skill：先「C模式任务」单选（从零写引言/从零写文献综述/两个都选），再「本文信息」单选（跳过/已有初稿提供文件/现场口述），逐字文案与台账；调整卡重选 C 时也要重出这两张卡。
   - 网页：只有一张用途卡内含 `c_route` 下拉、`user_results` 文本框、`target_journal` 输入；没有独立两张卡、没有三种材料路径、调整重选 C 不会重出。
   - 影响：C 模式运行逻辑契约不一致；文件/口述材料入口缺失。需要新增卡状态与材料输入（文件上传或粘贴）。

2. **C2 构件渲染不完整（中）**
   - Skill：C2 需检索范围与策略、七维分类、综合分析、技术路线比较、六列比较表、五列空白表、未来方向、完整综述。
   - 网页：正文按最新模板与复核脚本生成（复核脚本与 Skill 同哈希），但 `components.md` 渲染器只输出分类框架/比较表/空白表，缺少检索策略、综合分析、技术路线比较、未来方向；C2 尚未做真实网页全流程跑通。
   - 影响：正文可能通过复核，但构件展示与 Skill 说明不一致；需一次真实 C2 运行验证。

3. **D 总结页缺少“最重要趋势 + 2–3 个讨论问题”显式行（低）**
   - Skill 文案要求总结页含 3 发现 + 最重要趋势 + 2–3 问题 + 优先方向 + 下一步 + 团队决策；网页总结页为 3 条进展 + 优先方向 + 下一步，问题在下一页，趋势有独立页。复核脚本不拦此项。

4. **PPT 生成器不是 Skill 的 `pptx_layouts.py` Deck（中）**
   - 网页使用自研版式引擎并跑 `check_layout_rotation.py`；未使用 Skill 指定的 13 版式族 Deck。功能与版式轮换门禁通过，但视觉规则与 Skill 不完全同源。

5. **B 模板一句措辞差异（低）**
   - 7 个模板中 6 个逐字节一致；`B_立项依据骨架.md` 网页版为“【资产 [n]】”，Skill 版为“【可借鉴的方法、变量体系、模型组件或评估设计 [n]】”，且网页版修改时间更晚。若要统一，需发布 Skill v2；当前有 22 个未完成任务会阻止运行期变更，需先做任务过期清理。

6. **E 模式自定义入口缺失（低）**
   - Skill 支持 E 其他（自由输入）；网页用途卡只有 A–D，无自定义输入。

## 三、建议顺序

1. 先部署当前代码（推送阻断解除后），用真实任务验证 A/A_DIALOGUE/D 与文件名。
2. 实现 C 两张固定卡与材料输入（需产品拍板：文件上传 vs 粘贴文本）。
3. 跑一次真实 C2，核对正文/构件与复核。
4. 任务过期清理 + Skill v2（B 模板）发布。
5. 可选：PPT 生成器对齐 `pptx_layouts.py`。
