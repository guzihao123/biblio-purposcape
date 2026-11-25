# D 原图真实 OA PDF 冒烟（2026-11-26）

- 论文：ref 32，Nature Communications，DOI `10.1038/s41467-024-45712-2`
- URL：`https://www.nature.com/articles/s41467-024-45712-2.pdf`（开放获取，未绕过付费墙）
- 工具：`skill_runtime/scripts/pdf_figures.py`，后端 PyMuPDF

## 结果

- 下载：HTTP 200，5,904,658 bytes，PDF 头 `%PDF`，SHA-256 `1d4d7930f12eb5ae93a7118ebc7021df7d818f7ea8a8f09191df9e2605448766`
- `info`：14 页，页面 595×790 pt
- `render --page 1 --scale 1.5`：893×1187 PNG，401,326 bytes，SHA-256 `ce6c28721581f6f2a820d06c7cd11cf45202a0ce21c0cb81e98227594ab31bf8`
- `crop --page 2 --scale 2 --px 100,150,700,700`：700×700 PNG，192,574 bytes，SHA-256 `5a62883730c6fde21c7cb76eb4ed44a76319573af331e40b2f79cae420687694`
- `images --min-size 300`：提取 5 张真实图（jpeg/png），含 2104×2378、1819×2417 等尺寸

## 边界

- ref 1 Science PDF 仍为 403，本报告改用 ref 32 Nature OA PDF；
- 已证明真实 OA 下载、渲染、裁切与内嵌位图提取；
- 尚未执行“图注定位 → 嵌入 PPT → 出处/版本标注”的完整交付链路，D 原图端到端仍不宣称通过。