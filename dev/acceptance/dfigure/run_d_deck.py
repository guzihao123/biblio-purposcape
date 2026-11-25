"""Regenerate the D deck with real OA figures for acceptance.

Usage (from the repo root, with the project test environment):

    PYTHONPATH=backend python dev/acceptance/dfigure/run_d_deck.py

The run reads one existing D-mode artifact, resolves OA full text, extracts
real figures, writes ``figures/`` + ``ppt_asset_manifest.json`` next to the
deck, and runs the delivery verifier.  No card/writing content is modified.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
RUN = HERE / "run"
ARTIFACT = ROOT / "dev" / "real_backend" / "runtime" / "artifacts" / "243c5966-71c9-406e-b386-d684ac706095"
ELIFE_PDF = "https://cdn.elifesciences.org/articles/95009/elife-95009-v1.pdf"

sys.path.insert(0, str(ROOT / "backend"))

from app.delivery import DeliveryTask, _ppt_filename, _reference_entries, _write_pptx  # noqa: E402
from app.fulltext import FullTextService  # noqa: E402
from app.ppt_figures import prepare_d_figures  # noqa: E402


def _load(name, kind="json"):
    path = ARTIFACT / name
    if kind == "json":
        return json.loads(path.read_text(encoding="utf-8"))
    return path.read_text(encoding="utf-8")


def _ensure_elife_pdf(service):
    cached = RUN / "oa_pdfs" / "source_ref4.pdf"
    if cached.is_file():
        return cached
    cached.parent.mkdir(parents=True, exist_ok=True)
    data, content_type = service.oa_module.http_binary(ELIFE_PDF, tries=2, timeout=90)
    data = service.oa_module.validate_pdf_bytes(data, content_type)
    cached.write_bytes(data)
    return cached


def main():
    RUN.mkdir(parents=True, exist_ok=True)
    papers_doc = _load("papers.json")
    papers = papers_doc["papers"]
    components = _load("components.md")
    references = _reference_entries(_load("references.md", "text"))
    direction = papers_doc.get("topic") or "肝细胞癌免疫治疗耐药机制"

    service = FullTextService(output_dir=RUN)
    _ensure_elife_pdf(service)

    bundle = prepare_d_figures(
        papers,
        components.get("reading_cards", []),
        RUN,
        service=service,
        include_supporting=True,
        max_refs=5,
    )

    task = DeliveryTask(
        id="dfigure-acceptance",
        mode="D",
        direction=direction,
        papers=papers,
        body="",
        evidence_ledger="",
        components=components,
        outline=_load("outline.md", "text") if (ARTIFACT / "outline.md").is_file() else "",
        delivery_form="C",
        requirements=[],
    )
    deck = RUN / _ppt_filename(direction)
    _write_pptx(task, "", references, deck, figure_loader=lambda *args, **kwargs: bundle)

    manifest = json.loads((RUN / "ppt_asset_manifest.json").read_text(encoding="utf-8"))
    images = [item for item in manifest["visuals"] if item.get("kind") == "image"]
    report = (RUN / "verify_ppt_report.txt").read_text(encoding="utf-8")
    print(f"assets={len(bundle.assets)} embedded_entries={len(images)} deck={deck.name}")
    for attempt in bundle.attempts:
        print(f"[{attempt['ref_no']}] {attempt['status']} | {attempt['version']} | {attempt.get('source_url')}")
    print(report.splitlines()[-1])
    print((RUN / "layout_check.json").read_text(encoding="utf-8")[:200])
    return 0 if "结果：PASS" in report else 1


if __name__ == "__main__":
    raise SystemExit(main())
