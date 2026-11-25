# PPT 最终视觉复核记录（D 模式独立验收）

- 日期：2026-11-24
- 验收对象：`dev/ppt-validation/wps-current/肝细胞癌免疫治疗耐药机制组会汇报.pptx`（25 页）
- 证据：`wps-current/rendered/page-01..25.png`（用户 WPS 导出 PDF 的栅格）、`libreoffice-fontconfig/rendered/page-01..25.png`
- 方法：25 页 × 2 引擎全部逐页打开目视检查；第 7 页图例区、第 13 页密文区做了原生分辨率放大复核。结论不依赖 validation.json / OCR / 旧报告。

## 真实视觉通过项
- 全部 25 页在两引擎下均无缺字、无方框、无乱码。
- 标题、正文、表格、流程节点无溢出、无裁切、无重叠。
- 第 6 页折线图数据完整（2024:1 → 2025:3）；第 7 页饼图 4 个分类与数值完整；图例齐全。
- 第 3 / 12 / 22 页流程节点与连接线完整。
- 第 12 页 6 列表格在页面范围内。
- 第 25 页参考文献 4 条完整含 DOI。
- 页码 1–25 全部正确，页面比例统一 16:9。

## 兼容性问题（分引擎记录）
1. 第 7 页（已登记，保留）：WPS 不显示单独系列名“文献数”，分类与数值完整；LibreOffice 将其显示为图表标题。非新缺陷。
2. 第 6 页（本次新记录，引擎差异）：LibreOffice 在折线图上方渲染“文献数”图表标题，WPS 无标题；数据一致。
3. 第 7 页（本次新记录，轻微视觉）：底部图例项间距过密，“IL-8/CXCR2 动态分层”文字与相邻图例色块相碰、略有裁切；两引擎一致，内容完整。标注截图：`annotated-p07-legend.png`。
4. 第 9–25 页文字页（装饰性差异）：LibreOffice（fontconfig）在西文 token 两侧增加空隙，与 WPS 排版略不同，无内容影响。
5. 第 22 页“趋势／趋勢”为已裁定 OCR 简繁误识别，目视确认原文“发展趋势”完整，非缺陷。

## 跟进项
- **FOLLOWUP-P07-LEGEND**（轻微／排版打磨项，不影响文献内容与数据判读）：第 7 页底部图例项间距过密，“IL-8/CXCR2 动态分层”文字与相邻图例色块相碰并略被裁切（WPS 与 LibreOffice 渲染均可见）。证据：`annotated-p07-legend.png` 及两个引擎的 `page-07.png`。建议：增加底部图例区域高度与列间距，必要时将长标签换行，避免色块侵入文字。本验收不自行修改 PPT 或主线代码，由主线统一修复后重新导出并复核两个引擎。

## PowerPoint 未验证项（环境阻塞）
本机未安装 Microsoft PowerPoint（`/Applications` 仅 wpsoffice.app）。按要求未擅自安装软件，动画、切换、演讲者视图、备注一律记为“环境阻塞／未验证”，未以 WPS 冒充 PowerPoint。

## 结论
**accepted_with_compatibility_notes_and_minor_layout_followup**：25 页内容完整性真实视觉检查通过，无内容失败页；存在 1 项轻微版式跟进项 FOLLOWUP-P07-LEGEND；兼容性记录如上；PowerPoint 桌面行为未验证。

## 边界声明
- 检查基于两套 PDF 栅格证据，未重新打开 WPS 编辑视图截图。
- 未修改 PPT 源文件、backend/app/delivery.py、任何现有测试或既有证据；所有新增内容仅位于 `dev/acceptance/ppt-visual-final/`。
- 逐页结论见同目录 `result.json`。
