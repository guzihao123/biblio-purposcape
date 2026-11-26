# D 原图链路本地冒烟（2026-11-26）

## 1. 结论

- **渲染/裁切工具链通过，真实 OA 下载未通过。**
- 本冒烟项可关闭：`pdf_figures.py info/render/crop` 在明确标注的合成 PDF 上通过，PNG 输出已验证并持久化。
- **真实 OA 下载未成功**：ref 1 出版社 PDF 直链返回 403；ref 4 PMC PDF 候选返回中转网页而非 PDF。
- **D 原图端到端仍为 blocked/未验证**：本轮使用合成 PDF，不能证明 Europe PMC/PMC/arXiv 的真实 PDF、图注定位和 PPT 嵌入可用。
- 未修改产品代码，未 push、部署或调用付费模型。

## 2. 论文选择与 OA 尝试

最终用于正式下载尝试的论文来自 `backend/tests/fixtures/modes/D/papers.json`：

| 项 | 值 |
|---|---|
| ref_no | 1 |
| 标题 | Sphingolipid synthesis in tumor-associated macrophages confers immunotherapy resistance in hepatocellular carcinoma |
| DOI | `10.1126/sciadv.adv0558` |
| fixture 内 OA 链接 | `https://www.science.org/doi/pdf/10.1126/sciadv.adv0558?download=true` |

`oa_pdf.py` 定位到上述出版社 OA PDF 直链（tier 1）和 Europe PMC 开放全文 XML。PDF 直链返回 **`HTTP Error 403: Forbidden`**，脚本未保存任何 PDF；随后按自身逻辑取得全文 XML 和补充材料包。没有尝试绕过付费墙或浏览器 proof-of-work。

选择过程中的其他观察：

- ref 4（eLife，DOI `10.7554/elife.95009`）首次尝试只解析到 DOI 落地页、Europe PMC XML 和需浏览器验证的 PMC PDF；落地页返回网页而非 PDF，脚本保存的是 XML，不是 PDF。
- ref 2、ref 3 的候选检查同样只有 DOI 落地页、Europe PMC XML 和 PMC PDF，没有出版社 PDF 直链。
- 因只有 ref 1 暴露出版社 OA PDF 直链，最终选择 ref 1 作为正式 OA 下载尝试对象。

### 2.1 ref 4 PMC PDF 追加尝试

fixture 内没有显式的 PMC 或 arXiv OA URL；ref 4 的 `oa_url` 是 DOI。通过 `oa_pdf.py` 重新解析后，得到明确 PMC PDF 候选：

`https://pmc.ncbi.nlm.nih.gov/articles/PMC11326777/pdf/elife-95009.pdf`

为避免 XML 候选优先返回，仅这一次 PDF 重试通过临时驱动调用 `oa_pdf.py` 的 `resolve`/`download`，过滤为 `kind=pdf` 且 `is_direct_pdf=true` 的候选；没有修改产品脚本，也没有处理 PMC proof-of-work。结果为**返回中转网页、未保存 PDF、退出码 3**，真实 OA 下载仍为 blocked。

- 临时驱动：`/tmp/dfigure-smoke/try_pmc_pdf.py`
- 候选快照：`/tmp/dfigure-smoke/oa-ref4-pmc/pmc_oa_candidates.json`
- 下载日志：`/tmp/dfigure-smoke/oa-ref4-pmc/pmc_download.log`

## 3. 环境与产物

| 项 | 值 |
|---|---|
| 仓库 | `/Users/crisprcas_9/WorkBuddy/2026-11-06-20-49-06/purpose-landscape-web` |
| Python | `/Library/Developer/CommandLineTools/usr/bin/python3` |
| PDF 后端 | PyMuPDF 1.26.5（MuPDF 1.26.10） |
| 冒烟输出目录 | `/tmp/dfigure-smoke/` |
| OA 候选结果 | `/tmp/dfigure-smoke/oa-ref1/oa_pdf_urls.json` |
| OA 下载日志 | `/tmp/dfigure-smoke/oa-ref1/oa_download.log` |
| 非 PDF 全文后备 | `/tmp/dfigure-smoke/oa-ref1/fulltext_ref1.xml` |
| 补充材料包 | `/tmp/dfigure-smoke/oa-ref1/supplementary_ref1.zip` |
| 合成 PDF 生成脚本 | `/tmp/dfigure-smoke/make_synthetic_pdf.py` |
| 合成 PDF | `/tmp/dfigure-smoke/synthetic-fallback.pdf` |
| 页数日志 | `/tmp/dfigure-smoke/info.log` |
| 持久化整页 PNG | `dev/acceptance/dfigure-smoke/page-1.png` |
| 持久化图区 PNG | `dev/acceptance/dfigure-smoke/figure-1-crop.png` |
| 临时整页 PNG | `/tmp/dfigure-smoke/page-1.png` |
| 临时图区 PNG | `/tmp/dfigure-smoke/figure-1-crop.png` |
| 裁切日志 | `/tmp/dfigure-smoke/crop.log` |
| PNG 校验日志 | `/tmp/dfigure-smoke/verify.log` |
| SHA-256 日志 | `/tmp/dfigure-smoke/sha256.log` |

合成 PDF 第 1 页明确写有 `SYNTHETIC FALLBACK - NOT THE OA ARTICLE`，不含真实论文图表。

## 4. 执行命令

以下命令均从仓库根目录执行。

### 4.1 OA 定位与下载

```bash
mkdir -p /tmp/dfigure-smoke/oa-ref1
python3 skill_runtime/scripts/oa_pdf.py \
  --papers backend/tests/fixtures/modes/D/papers.json \
  --ref-no 1 \
  --download /tmp/dfigure-smoke/oa-ref1 \
  --out /tmp/dfigure-smoke/oa-ref1/oa_pdf_urls.json \
  2>&1 | tee /tmp/dfigure-smoke/oa-ref1/oa_download.log
```

结果：PDF 直链 403；XML 与补充材料包取得成功；**无真实 PDF 落盘**。

### 4.2 ref 4 PMC PDF 追加尝试

```bash
mkdir -p /tmp/dfigure-smoke/oa-ref4-pmc
python3 /tmp/dfigure-smoke/try_pmc_pdf.py \
  2>&1 | tee /tmp/dfigure-smoke/oa-ref4-pmc/pmc_download.log
```

临时驱动使用 `oa_pdf.py` 的 `resolve`/`download`，只尝试解析结果中的直接 PDF 候选，不处理 proof-of-work。结果：PMC 链接返回中转网页，`downloaded_pdf=None`，退出码 3。

### 4.3 合成 PDF 降级

```bash
python3 /tmp/dfigure-smoke/make_synthetic_pdf.py
```

### 4.4 `info`、首页渲染与图区裁切

脚本页码为零基，`--page 0` 对应第 1 页。

```bash
python3 skill_runtime/scripts/pdf_figures.py \
  /tmp/dfigure-smoke/synthetic-fallback.pdf info \
  2>&1 | tee /tmp/dfigure-smoke/info.log

python3 skill_runtime/scripts/pdf_figures.py \
  /tmp/dfigure-smoke/synthetic-fallback.pdf render \
  --page 0 --scale 2 --out /tmp/dfigure-smoke/page-1.png \
  2>&1 | tee /tmp/dfigure-smoke/render.log

python3 skill_runtime/scripts/pdf_figures.py \
  /tmp/dfigure-smoke/synthetic-fallback.pdf crop \
  --page 0 --scale 2 --px 144,420,936,640 \
  --out /tmp/dfigure-smoke/figure-1-crop.png \
  2>&1 | tee /tmp/dfigure-smoke/crop.log
```

### 4.5 PNG 独立校验

```bash
python3 - <<'PY'
import json
from pathlib import Path
import fitz

expected = {
    "/tmp/dfigure-smoke/page-1.png": (1224, 1584),
    "/tmp/dfigure-smoke/figure-1-crop.png": (936, 640),
}
results = []
for name, size in expected.items():
    path = Path(name)
    data = path.read_bytes()
    assert data.startswith(b"\x89PNG\r\n\x1a\n"), f"not PNG: {path}"
    pix = fitz.Pixmap(str(path))
    assert (pix.width, pix.height) == size, (path, pix.width, pix.height, size)
    assert pix.n >= 3, f"unexpected channels: {pix.n}"
    assert min(pix.samples) != max(pix.samples), f"uniform/blank image: {path}"
    results.append({
        "path": str(path),
        "bytes": len(data),
        "width": pix.width,
        "height": pix.height,
        "channels": pix.n,
        "non_uniform": True,
        "status": "pass",
    })
print(json.dumps(results, indent=2))
PY
```

### 4.6 PNG 证据持久化

```bash
mkdir -p dev/acceptance/dfigure-smoke
cp /tmp/dfigure-smoke/page-1.png dev/acceptance/dfigure-smoke/page-1.png
cp /tmp/dfigure-smoke/figure-1-crop.png dev/acceptance/dfigure-smoke/figure-1-crop.png
shasum -a 256 \
  /tmp/dfigure-smoke/page-1.png dev/acceptance/dfigure-smoke/page-1.png \
  /tmp/dfigure-smoke/figure-1-crop.png dev/acceptance/dfigure-smoke/figure-1-crop.png \
  | tee /tmp/dfigure-smoke/sha256.log
cmp -s /tmp/dfigure-smoke/page-1.png dev/acceptance/dfigure-smoke/page-1.png
cmp -s /tmp/dfigure-smoke/figure-1-crop.png dev/acceptance/dfigure-smoke/figure-1-crop.png
```

## 5. 验证结果

| 检查 | 实际结果 | 状态 |
|---|---|---|
| OA PDF 定位 | 找到出版社 OA PDF 候选 | 成功 |
| OA PDF 下载（ref 1） | HTTP 403，无 PDF 落盘 | 失败 |
| PMC PDF 追加尝试（ref 4） | 返回中转网页，无 PDF 落盘，退出码 3 | 失败/blocked |
| 开放全文后备 | 取得 Europe PMC XML（161 KB） | 成功，但不是 PDF |
| 合成 PDF `info` | `pages=1`；第 1 页 `612x792 pt` | 通过 |
| 第 1 页 `render --scale 2` | `1224x1584`，45,665 字节 | 通过 |
| 图区 `crop --px 144,420,936,640` | `936x640`，11,991 字节 | 通过 |
| PNG 签名 | 两张均为有效 PNG 签名 | 通过 |
| PNG 解码 | PyMuPDF 可解码，3 通道 | 通过 |
| PNG 非空 | 文件大于 0，像素非纯色 | 通过 |
| PNG 尺寸 | 与页面/裁切坐标及 scale 计算值一致 | 通过 |
| 目视检查 | 整页与裁切图均显示合成折线图；裁切包含图区 | 通过 |

尺寸依据：合成页面为 `612x792 pt`，scale 2 得 `1224x1584 px`；裁切参数宽高为 `936x640 px`，实际输出一致。

持久化 PNG 校验：

| 文件 | 尺寸 | 字节数 | SHA-256 |
|---|---:|---:|---|
| `dev/acceptance/dfigure-smoke/page-1.png` | 1224×1584 | 45,665 | `38e1236fc3d58d8e6ec05e9936ab98a933db193d10ea38b7268ccb0b723efd3d` |
| `dev/acceptance/dfigure-smoke/figure-1-crop.png` | 936×640 | 11,991 | `5fc395df082324afcb781f57d17b164219d3f7567e34300af5270d95ae524b93` |

源文件与仓库内副本的 SHA-256 一致，`cmp -s` 均通过；即使 `/tmp` 清理，仓库内仍保留两份 PNG 证据。

## 6. 未覆盖边界

- **真实论文 PDF 的 `info/render/crop` 未覆盖**：ref 1 出版社直链 403、ref 4 PMC 候选返回中转网页，不能据此宣称真实原图提取成功。
- **Europe PMC/PMC/arXiv 的真实 PDF 可用性未证明**：Europe PMC XML 与补充材料包取得成功不等于 PDF 取得成功；fixture 没有显式 arXiv OA URL，本轮未取得 arXiv PDF。
- **图注定位与 PPT 嵌入未覆盖**：合成裁切不含真实图注定位、正文关联或 PPT 嵌入验证。
- 未尝试 PMC proof-of-work、机构订阅、浏览器登录或任何付费墙绕过。
- 未验证 PDFKit/Swift 回退；本次实际使用 PyMuPDF。
- 未验证多页论文的页数、跨页图、零基页码边界、超大 PDF 或损坏 PDF。
- 未验证 `text`、`images`、`xmltext`、补充材料包解析或真实图注/正文证据关联。
- 裁切坐标由合成图人工指定；未验证自动图区检测或真实复杂版面裁切质量。
- 未启动后端/前端生产链路，未验证模式 D 的端到端交付、任务状态或云侧产物；**D 原图端到端保持 blocked/未验证**。
