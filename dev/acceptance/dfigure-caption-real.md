# D 原图图注定位修复（2026-11-26）

真实样本：Nature Communications `10.1038/s41467-024-45712-2`（14 页 OA PDF）。

## 修复

- caption 正则支持 `Figure` / `Fig.` / 中文 `图`；
- 排除正文引用行：`Fig. 2b). Furthermore…`、`Fig. 4d, e).…` 等不再误判为图注；
- 图注页与图片跨页时，向相邻页查找最大图片 bbox；
- pdfium 未暴露图片对象时，用 PyMuPDF `get_image_bbox` 兜底并换算为 PDF 左下原点坐标。

## 结果

`_figures_from_pdf` 对真实 PDF：

| 图 | 名称 | 页码 | 尺寸 | 字节 |
|---|---|---|---:|---:|
| 1 | ref32_fig1_临床比较.png | 5 | 853×1148 | 506,943 |
| 2 | ref32_fig2_结果图.png | 7 | 887×1144 | 619,150 |
| 3 | ref32_fig3_机制模型.png | 9 | 828×1072 | 373,375 |
| 4 | ref32_fig4_结果图.png | 11 | 1016×1125 | 395,305 |

- 4/4 定位并裁切成功，0 failure；
- 图注文本来自真实论文，不再命中正文引用；
- 全量后端 630 passed / 5 skipped。

## 边界

- 该样本图注与图片跨页；已覆盖相邻页回退；
- 其他出版社（Elsevier/Wiley/Springer）版式仍需更多样本；未知版式失败时只记录 failure，不伪造图片。