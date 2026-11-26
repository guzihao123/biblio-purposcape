# D 原图 PPT 嵌入验证（2026-11-26）

- 真实来源：ref 32，Nature Communications，DOI `10.1038/s41467-024-45712-2`
- 图片：`/tmp/dfigure-real/images/p5_x129.jpeg`（1,751×2,426，来自真实 OA PDF 内嵌位图）
- 组装：`app.delivery._write_pptx` + `FigureBundle`，D 交付夹具，PPT 21-page 形态
- 输出：`/tmp/dfigure-real/ppt/deck.pptx`

## 结果

- 文件大小 284,299 bytes，可被 `zipfile` 打开；
- `ppt/media/image1.jpg` 存在（1 张真实图片）；
- `ppt_asset_manifest.json` 有 1 条 image 记录，`version=正式版`、`acquisition=OA PDF 图片提取`；
- `verify_ppt_report.txt`：`结果：PASS`。

## 边界

- 本验证使用真实图像 + 现有 D 排版/清单逻辑，证明「真实图 → PPT 媒体 → manifest / verify」链路可用；
- manifest 的 `source` 在本次测试脚本中指向本地临时文件；正式任务应由 `prepare_d_figures` 写入 `figures/ref*_fig*` 相对路径；
- 图注自动定位仍依赖真实 PDF 文本/图区，本次未覆盖所有出版社版式；公开链路仍不宣称 100% 覆盖。