from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import onnxruntime
import pypdfium2 as pdfium
from PIL import ImageStat
from pptx import Presentation
from rapidocr import RapidOCR  # noqa: F401


VALIDATION = Path('/validation')
PPTX = VALIDATION / 'wps-current' / '肝细胞癌免疫治疗耐药机制组会汇报.pptx'
PDF = VALIDATION / 'libreoffice-fontconfig' / '肝细胞癌免疫治疗耐药机制组会汇报.pdf'
OUTPUT = Path('/tmp/container-smoke')


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def main():
    OUTPUT.mkdir(exist_ok=True)
    font = subprocess.run(['fc-match', 'Noto Sans CJK SC'], capture_output=True, text=True, check=True).stdout
    require('Noto Sans CJK SC' in font, font)

    presentation = Presentation(PPTX)
    require(len(presentation.slides) == 25, 'PPTX page count mismatch')
    extracted = OUTPUT / '汇报文本.md'
    completed = subprocess.run(
        [
            sys.executable,
            '/app/skill_runtime/scripts/pptx_to_text.py',
            str(PPTX),
            '--slidep', '/bin/false',
            '--out', str(extracted),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    require(completed.returncode == 0, completed.stderr or completed.stdout)
    require('extractor=python-pptx-fallback' in completed.stdout, completed.stdout)
    text = extracted.read_text(encoding='utf-8')
    require('## 参考文献' in text, 'Reference section missing')
    require('研究背景与科学问题' in text, 'Chinese slide text missing')

    document = pdfium.PdfDocument(str(PDF))
    require(len(document) == 25, 'PDF page count mismatch')
    image = document[6].render(scale=1.0).to_pil().convert('L')
    require(ImageStat.Stat(image).stddev[0] > 3, 'PDF chart page is blank')

    print(json.dumps({
        'python': sys.version.split()[0],
        'fontconfig': font.strip(),
        'pptx_pages': len(presentation.slides),
        'pdf_pages': len(document),
        'pdf_chart_stddev': round(ImageStat.Stat(image).stddev[0], 3),
        'extractor': 'python-pptx-fallback',
        'onnxruntime_device': onnxruntime.get_device(),
        'rapidocr_import': True,
        'checks': 'passed',
    }, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
