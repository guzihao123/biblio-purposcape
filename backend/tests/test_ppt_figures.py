import io
import json
import zipfile
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw

from app.delivery import DeliveryTask, _reference_entries, _write_pptx
from app.ppt_figures import (
    FigureAsset,
    FigureBundle,
    _figure_caption_from_lines,
    _figures_from_pdf,
    prepare_d_figures,
)


def _fake_png(path, color="lightblue"):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (400, 300), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((10, 10, 390, 290), outline="black", width=4)
    draw.ellipse((100, 80, 300, 220), fill=color)
    draw.text((150, 140), "FAKE FIG", fill="black")
    image.save(path, format="PNG")
    return path


def _jpeg_bytes(color="lightblue"):
    image = Image.new("RGB", (400, 300), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((10, 10, 390, 290), outline="black", width=4)
    draw.ellipse((100, 80, 300, 220), fill=color)
    draw.text((150, 140), "FAKE FIG", fill="black")
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=90)
    return buffer.getvalue()


def _escape_pdf_text(text):
    return str(text).replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


def _write_pdf(path, objects):
    output = bytearray(b"%PDF-1.4\n")
    offsets = {}
    for number in sorted(objects):
        offsets[number] = len(output)
        output += f"{number} 0 obj\n".encode() + objects[number] + b"\nendobj\n"
    xref = len(output)
    output += f"xref\n0 {len(objects) + 1}\n".encode() + b"0000000000 65535 f \n"
    for number in sorted(objects):
        output += f"{offsets[number]:010d} 00000 n \n".encode()
    output += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref}\n%%EOF\n"
    ).encode()
    path.write_bytes(output)
    return path


def _synthetic_pdf(path, body_references=(), figures=None, extra_text=(), extra_objects=None):
    """Build a one-page PDF with searchable captions and image objects.

    ``figures`` is a list of dicts with ``x0, y0, width, height, caption`` in
    PDF points (y from bottom).  ``extra_text`` entries are ``(text, x, y)``
    tuples (e.g. a right-column body block).  ``extra_objects`` maps object
    numbers to raw PDF object bodies.  Defaults preserve the original single
    centred figure used by the earlier tests.
    """

    jpeg = _jpeg_bytes()
    figures = list(figures or [{"x0": 100, "y0": 400, "width": 400, "height": 300,
                                "caption": "Figure 1. Synthetic caption"}])
    xobjects = " ".join(f"/Im{index} {4 + index} 0 R" for index in range(len(figures)))
    objects = {
        1: b"<< /Type /Catalog /Pages 2 0 R >>",
        2: b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        3: (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /XObject << " + xobjects.encode() + b" >> /Font << /F1 5 0 R >> >> "
            b"/Contents 6 0 R >>"
        ),
        5: b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    }
    for index in range(len(figures)):
        objects[4 + index] = (
            b"<< /Type /XObject /Subtype /Image /Width 400 /Height 300 "
            b"/ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode /Length "
            + str(len(jpeg)).encode()
            + b" >>\nstream\n"
            + jpeg
            + b"\nendstream"
        )

    content = b""
    for offset, text in enumerate(body_references):
        content += (
            f"BT /F1 10 Tf 100 {500 - offset * 20} Td ({_escape_pdf_text(text)}) Tj ET\n".encode()
        )
    for index, figure in enumerate(figures):
        content += (
            f"q {figure['width']} 0 0 {figure['height']} {figure['x0']} {figure['y0']} cm "
            f"/Im{index} Do Q\n".encode()
        )
        content += (
            f"BT /F1 14 Tf {figure['x0']} {figure['y0'] - 24} Td "
            f"({_escape_pdf_text(figure['caption'])}) Tj ET\n".encode()
        )
    for text, x, y in extra_text:
        content += f"BT /F1 11 Tf {x} {y} Td ({_escape_pdf_text(text)}) Tj ET\n".encode()
    objects[6] = b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content + b"\nendstream"
    if extra_objects:
        objects.update(extra_objects)
    return _write_pdf(path, objects)


def test_pdf_crop_writes_named_png_and_records_original_page(tmp_path):
    pdf = _synthetic_pdf(tmp_path / "synthetic.pdf")
    assets, failures = _figures_from_pdf(pdf, 7, tmp_path / "figures")

    assert failures == []
    assert len(assets) == 1
    asset = assets[0]
    assert asset.path.name == "ref7_fig1_结果图.png"
    assert asset.original_page == "1"
    assert asset.caption.startswith("Figure 1.")
    assert asset.path.read_bytes().startswith(b"\x89PNG")
    with Image.open(asset.path) as image:
        assert image.width > 200 and image.height > 200


def test_caption_guard_skips_body_reference_lines(tmp_path):
    pdf = _synthetic_pdf(
        tmp_path / "synthetic.pdf",
        body_references=(
            "Fig. 2b). Furthermore, the trend continued in later cohorts.",
            "Fig. 4d, e). The panels show the same pattern.",
        ),
    )

    assets, failures = _figures_from_pdf(pdf, 7, tmp_path / "figures")

    assert failures == []
    assert [asset.fig_no for asset in assets] == ["1"]
    assert assets[0].caption.startswith("Figure 1.")


def test_two_captions_on_one_page_produce_two_figures(tmp_path):
    """Same-page figures must be cropped per caption, not only the first one."""

    figures = [
        {"x0": 90, "y0": 500, "width": 200, "height": 150,
         "caption": "Figure 1. Upper conceptual framework for the study."},
        {"x0": 90, "y0": 180, "width": 200, "height": 150,
         "caption": "Figure 2. Lower results of the same experiment."},
    ]
    pdf = _synthetic_pdf(tmp_path / "two_figs.pdf", figures=figures)

    assets, failures = _figures_from_pdf(pdf, 7, tmp_path / "figures")

    assert failures == []
    assert [asset.fig_no for asset in assets] == ["1", "2"]
    assert all(asset.original_page == "1" for asset in assets)
    assert all(asset.crop_mode == "column_aware" for asset in assets)
    assert len({asset.path for asset in assets}) == 2
    for asset in assets:
        assert asset.caption.startswith(f"Figure {asset.fig_no}.")
        assert asset.path.read_bytes().startswith(b"\x89PNG")


def test_right_column_body_text_is_excluded_from_left_figure_crop(tmp_path):
    """A two-column page must not sweep the right column into the left figure."""

    figures = [
        {"x0": 60, "y0": 430, "width": 220, "height": 200,
         "caption": "Figure 3. Left column artwork for the vulnerability model."},
    ]
    right_column = [
        ("allocate population data at the building level, assuming a uniform", 320, 610),
        ("total population is then distributed among statistical units; it is", 320, 590),
        ("used to estimate the exposure of buildings to the flood hazard.", 320, 570),
        ("3.1.3 Hazard", 320, 540),
        ("In this study, we consider urban pluvial flooding as the hazard.", 320, 510),
        ("We define water level thresholds based on existing regulations.", 320, 490),
        ("The following paragraphs contain no figure caption at all.", 320, 470),
    ]
    pdf = _synthetic_pdf(tmp_path / "two_columns.pdf", figures=figures, extra_text=right_column)

    assets, failures = _figures_from_pdf(pdf, 7, tmp_path / "figures")

    assert failures == []
    assert [asset.fig_no for asset in assets] == ["3"]
    asset = assets[0]
    assert asset.crop_mode == "column_aware"
    graphic_box = asset.crop_meta["graphic_box"]
    # The crop is bounded by the left-column image (x0..x0+width), never the
    # full page width (612 pt) that would include the right-column paragraph.
    assert graphic_box[0] < 100 and graphic_box[2] < 300
    assert graphic_box[2] - graphic_box[0] <= 230
    with Image.open(asset.path) as image:
        assert image.width < 600  # full page at scale 2 is 1224 px


def test_caption_continuation_and_table_header_are_not_treated_as_captions(tmp_path):
    """A table header must not be absorbed into a figure caption."""

    assert _figure_caption_from_lines(
        ["Figure 4. Real caption about the model.",
         "Study Used dataset Crash type Records no Analysis period in years",
         "More genuine caption text."],
        0,
    ) == "Figure 4. Real caption about the model."

    figures = [
        {"x0": 90, "y0": 500, "width": 200, "height": 150,
         "caption": "Figure 4. Real caption about the model."},
    ]
    pdf = _synthetic_pdf(
        tmp_path / "table_header.pdf",
        figures=figures,
        extra_text=[
            ("Study Used dataset Crash type Records no", 90, 466),
            ("Table 1 (continued)", 90, 700),
        ],
    )

    assets, failures = _figures_from_pdf(pdf, 7, tmp_path / "figures")

    assert failures == []
    assert [asset.fig_no for asset in assets] == ["4"]
    assert "Crash type" not in assets[0].caption
    assert "Table 1" not in assets[0].caption


def test_prepare_degrades_without_oa_hint_without_network(tmp_path):
    papers = [{"ref_no": 1, "title": "No OA metadata"}]
    bundle = prepare_d_figures(papers, [{"ref": 1}], tmp_path, include_supporting=False)

    assert bundle.assets == []
    assert bundle.attempts[0]["status"] == "未尝试（无 OA 线索）"
    assert (tmp_path / "figure_acquisition_log.md").is_file()


@dataclass
class _Result:
    source_path: object
    source_url: str = ""
    version: str = "正式版"
    depth: str = "已读全文"
    failures: list = None

    def __post_init__(self):
        if self.failures is None:
            self.failures = []


class _FakeOaModule:
    def __init__(self, payload):
        self.payload = payload

    def http_binary(self, url, tries=3, timeout=60):
        return self.payload, "application/zip"


class _FakeService:
    def __init__(self, result, payload):
        self.result = result
        self.oa_module = _FakeOaModule(payload)

    def read_for_components(self, paper, purpose):
        return self.result


def test_jats_package_extracts_real_image_and_manifest_fields(tmp_path):
    figure_dir = tmp_path / "figures"
    figure_dir.mkdir()
    jpeg_path = _fake_png(tmp_path / "gr1.png")
    xml_path = tmp_path / "fulltext_ref1.xml"
    xml_path.write_text(
        """<article xmlns:xlink="http://www.w3.org/1999/xlink">
        <front><article-meta><article-id pub-id-type="pmcid">PMC12345</article-id></article-meta></front>
        <body><fig><label>Figure 1</label>
        <caption><p>Study design and workflow of the cohort.</p></caption>
        <graphic xlink:href="gr1.jpg"/></fig></body></article>""",
        encoding="utf-8",
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as package:
        package.writestr("gr1.jpg", jpeg_path.read_bytes())
    service = _FakeService(
        _Result(source_path=xml_path, source_url="https://example.org/fulltext.xml"),
        buffer.getvalue(),
    )

    bundle = prepare_d_figures(
        [{"ref_no": 1, "title": "JATS paper", "oa_url": "https://example.org/paper"}],
        [{"ref": 1}],
        tmp_path,
        service=service,
        include_supporting=False,
    )

    assert len(bundle.assets) == 1
    asset = bundle.assets[0]
    assert asset.path.name == "ref1_fig1_研究设计.png"
    assert asset.original_page == "【待核实】"
    assert asset.source_url == "https://example.org/paper"
    assert "supplementaryFiles#gr1.jpg" in asset.asset_url
    entry = asset.manifest_entry(16, tmp_path)
    assert entry["source"] == "figures/ref1_fig1_研究设计.png"
    assert entry["page"] == 16
    assert entry["figure_no"] == "Fig.1"
    assert entry["version"] == "正式版"
    assert "JATS" in entry["acquisition"]


def _make_d_task(tmp_path):
    components = {
        "search_overview": {"databases": ["OpenAlex"], "queries": ["urban flooding"], "pool_count": 2},
        "progress": [
            {"direction": "损失评估", "summary": "校准模型降低误差 [1]"},
            {"direction": "暴露调查", "summary": "调查描述恢复差异 [2]"},
            {"direction": "联合校准", "summary": "互补线索（分析）"},
        ],
        "method_comparison": [
            {"family": "计算建模", "technique": "校准", "data": "未说明", "strength": "误差", "limitation": "联动", "refs": [1]},
            {"family": "调查", "technique": "问卷", "data": "三地区", "strength": "恢复", "limitation": "联动", "refs": [2]},
        ],
        "reading_cards": [
            {"ref": 1, "title": "Paper one", "reason": "代表", "research_question": "问题", "data": "数据", "method": "方法", "findings": "发现", "limitations": "局限", "team_relevance": "启发", "reading_depth": "仅摘要"},
            {"ref": 2, "title": "Paper two", "reason": "代表", "research_question": "问题", "data": "数据", "method": "方法", "findings": "发现", "limitations": "局限", "team_relevance": "启发", "reading_depth": "仅摘要"},
            {"ref": 3, "title": "Paper three", "reason": "代表", "research_question": "问题", "data": "数据", "method": "方法", "findings": "发现", "limitations": "局限", "team_relevance": "启发", "reading_depth": "仅摘要"},
        ],
        "limitations": ["数据口径", "方法联动", "外部验证", "全文深度", "团队基础"],
        "trends": ["联合校准值得验证（分析）"],
        "discussion_questions": ["需要哪些数据？", "团队能否复用？"],
        "stats": {
            "year": {"groups": [{"name": "2024", "count": 2}]},
            "topics": {"all": {"groups": [{"name": "topic", "count": 2}]}},
        },
    }
    return DeliveryTask(
        id="d-figure-test",
        mode="D",
        direction="城市内涝与地下车库韧性",
        papers=[{"ref_no": index, "title": f"Paper {index}", "authors": ["A"], "year": 2024, "venue": "V", "type": "article"} for index in (1, 2, 3)],
        body="",
        evidence_ledger="",
        components=components,
        outline="",
        delivery_form="C",
        requirements=[],
    )


def test_deck_embeds_image_and_manifest_records_source(tmp_path):
    asset = _fake_png(tmp_path / "figures" / "ref1_fig1_研究设计.png")
    bundle = FigureBundle(
        assets=[
            FigureAsset(1, "1", "研究设计", asset, "Study design.", "测试图", "https://example.org/a.pdf", "正式版", "3", "OA PDF 裁切", "method"),
            FigureAsset(2, "1", "机制模型", _fake_png(tmp_path / "figures" / "ref2_fig1_机制模型.png"), "Mechanism.", "测试图", "https://example.org/b.pdf", "正式版", "4", "OA PDF 裁切", "architecture"),
        ],
        attempts=[],
    )
    task = _make_d_task(tmp_path)
    deck_path = tmp_path / "deck.pptx"
    references = _reference_entries("[1] Ref one.\n[2] Ref two.\n[3] Ref three.")

    _write_pptx(task, "", references, deck_path, figure_loader=lambda *args, **kwargs: bundle)

    manifest = json.loads((tmp_path / "ppt_asset_manifest.json").read_text(encoding="utf-8"))
    image_entries = [visual for visual in manifest["visuals"] if visual.get("kind") == "image" and not visual.get("degraded")]
    assert image_entries
    assert image_entries[0]["source"].startswith("figures/ref")
    assert image_entries[0]["original_page"] in {"3", "4"}
    assert image_entries[0]["version"] == "正式版"
    assert image_entries[0]["acquisition"] == "OA PDF 裁切"
    report = (tmp_path / "verify_ppt_report.txt").read_text(encoding="utf-8")
    assert "结果：PASS" in report
    assert "实际嵌入图片" in report

    from pptx import Presentation

    presentation = Presentation(deck_path)
    assert any(
        shape.shape_type == 13
        for slide in presentation.slides
        for shape in slide.shapes
    )
