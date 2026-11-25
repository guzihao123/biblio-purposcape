"""Re-open browser-downloaded Office artifacts and verify real content."""
import json
from pathlib import Path
import re
import sys
from docx import Document
from pptx import Presentation


def paragraphs(document):
    text = [paragraph.text for paragraph in document.paragraphs]
    for table in document.tables:
        for row in table.rows:
            for cell in row.cells:
                text.extend(paragraph.text for paragraph in cell.paragraphs)
    return '\n'.join(text)


def slides(presentation):
    return ['\n'.join(shape.text for shape in slide.shapes if getattr(shape, 'has_text_frame', False)) for slide in presentation.slides]


def main():
    mode = sys.argv[1].upper()
    paths = [Path(item).resolve() for item in sys.argv[2:]]
    results = {'mode': mode, 'files': []}
    for path in paths:
        data = path.read_bytes()
        assert data.startswith(b'PK'), f'{path.name}: invalid ZIP/OOXML signature'
        assert len(data) > 1000, f'{path.name}: unexpectedly small'
        if path.suffix == '.docx':
            document = Document(path)
            text = paragraphs(document)
            assert len(document.paragraphs) > 10, 'Word body is empty or truncated'
            assert '肝细胞癌免疫治疗耐药' in text, 'Word direction is missing'
            assert '参考文献' in text, 'Word references heading is missing'
            assert re.search(r'\[\d+\]', text), 'Word citations are missing'
            assert '10.1126/sciadv.adv0558' in text, 'Word reference DOI is missing'
            if mode == 'C':
                assert '完整引言' in text and '独立文献综述' in text, 'C1+C2 combined Word sections missing'
            detail = {'paragraphs': len(document.paragraphs), 'references': len(re.findall(r'^\[\d+\]', text, re.M))}
        elif path.suffix == '.pptx':
            presentation = Presentation(path)
            pages = slides(presentation)
            text = '\n'.join(pages)
            assert len(pages) > 0, 'PPT has no slides'
            assert '参考文献' in text, 'PPT references are missing'
            assert '肝细胞癌' in text, 'PPT topic is missing'
            assert '10.1126/sciadv.adv0558' in text, 'PPT reference DOI is missing'
            if mode == 'D':
                assert 20 <= len(pages) <= 30, f'D PPT slide count out of contract: {len(pages)}'
                assert any('代表作精读' in page for page in pages), 'D reading slides missing'
            detail = {'slides': len(pages), 'nonempty_slide_texts': sum(bool(page.strip()) for page in pages)}
        else:
            raise AssertionError(f'Not an Office file: {path}')
        results['files'].append({'name': path.name, 'bytes': len(data), 'signature': data[:2].decode(), **detail})
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
