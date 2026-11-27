#!/usr/bin/env python3
import argparse
import json
import re
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

NS = {
    'a': 'http://schemas.openxmlformats.org/drawingml/2006/main',
    'p': 'http://schemas.openxmlformats.org/presentationml/2006/main',
}


def slide_number(name):
    match = re.fullmatch(r'ppt/slides/slide(\d+)\.xml', name)
    return int(match.group(1)) if match else None


def load_deck(path):
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        slides = {}
        for name in names:
            number = slide_number(name)
            if number is None:
                continue
            root = ET.fromstring(z.read(name))
            slides[number] = {
                'text': ' '.join(root.itertext()),
                'pictures': len(root.findall('.//p:pic', NS)),
                'shapes': len(root.findall('.//p:sp', NS)),
            }
        charts = {}
        for number in slides:
            rels = f'ppt/slides/_rels/slide{number}.xml.rels'
            charts[number] = rels in names and b'/chart' in z.read(rels)
        media = [name for name in names if name.startswith('ppt/media/') and not name.endswith('/')]
    return slides, charts, media


def verify(pptx, manifest_path):
    slides, charts, media = load_deck(pptx)
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    failures = []
    passes = []
    degraded = []

    def check(ok, message):
        (passes if ok else failures).append(message)

    check(20 <= len(slides) <= 30, f'页数 20–30：实际 {len(slides)}')
    all_text = '\n'.join(item['text'] for _, item in sorted(slides.items()))
    for marker in ('研究背景', '文献检索', '研究进展', '核心方法', '代表作精读', '研究不足', '总结'):
        check(marker in all_text, f'结构内容：{marker}')
    check('潜在研究选题与推荐' not in all_text, '不单设第七部分“潜在研究选题与推荐”')
    check('参考文献' in all_text, '末尾包含完整参考文献')

    summary_pages = manifest.get('summary_pages', [])
    summary_text = '\n'.join(slides.get(n, {}).get('text', '') for n in summary_pages)
    check(bool(re.search(r'第\s*1\s*推荐|优先方向|优先推荐', summary_text)), '第八部分包含优先方向')
    check('下一步' in summary_text, '第八部分包含下一步研究建议')

    for visual in manifest.get('visuals', []):
        page = visual['page']
        kind = visual['kind']
        name = visual.get('name', f'P{page} {kind}')
        slide = slides.get(page)
        if not slide:
            failures.append(f'{name}：P{page} 不存在')
            continue
        if visual.get('degraded'):
            if not visual.get('allow_degraded'):
                failures.append(f'{name}：不允许降级')
            elif not visual.get('reason') or not visual.get('attempt_log'):
                failures.append(f'{name}：降级缺少原因或实际获取记录')
            else:
                degraded.append(f'{name}：已记录降级——{visual["reason"]}')
            continue
        source = visual.get('source')
        if source:
            source_path = Path(source)
            if not source_path.is_absolute():
                source_path = manifest_path.parent / source_path
            check(source_path.is_file(), f'{name}：源文件存在 {source}')
        if kind == 'image':
            check(slide['pictures'] >= 1, f'{name}：P{page} 实际嵌入图片')
        elif kind == 'chart':
            check(charts.get(page, False) or slide['pictures'] >= 1,
                  f'{name}：P{page} 实际嵌入图表或数据图')
            if '仪表盘' in slide['text'] and '完整' in slide['text'] and '见' in slide['text']:
                failures.append(f'{name}：P{page} 仍用“见仪表盘”代替本页图表')
        elif kind == 'diagram':
            check(slide['shapes'] >= visual.get('min_shapes', 4),
                  f'{name}：P{page} 包含框架/流程图形')
            for expected in visual.get('expected_text', []):
                check(expected in slide['text'], f'{name}：包含关键结点“{expected}”')
        else:
            failures.append(f'{name}：未知图表类型 {kind}')

    declared_media = [
        item for item in manifest.get('visuals', [])
        if item.get('kind') in {'image', 'chart'} and not item.get('degraded')
    ]
    check(bool(media) or any(charts.values()) or not declared_media,
          '全稿至少包含一个真实图片或图表对象')
    return passes, failures, degraded, len(media), sum(bool(x) for x in charts.values())


def main():
    parser = argparse.ArgumentParser(description='核验组会 PPT 的七部分内容、总结决策与真实图表对象')
    parser.add_argument('pptx')
    parser.add_argument('--manifest', required=True)
    parser.add_argument('--out')
    args = parser.parse_args()
    pptx = Path(args.pptx).resolve()
    manifest = Path(args.manifest).resolve()
    out = Path(args.out).resolve() if args.out else pptx.parent / 'verify_ppt_report.txt'
    try:
        passes, failures, degraded, media_count, chart_count = verify(pptx, manifest)
    except Exception as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        return 2
    lines = [
        'PPT 结构与图表验收',
        f'文件：{pptx}',
        f'图片资源：{media_count}；原生图表：{chart_count}',
        '',
    ]
    lines += [f'PASS {item}' for item in passes]
    lines += [f'DEGRADED {item}' for item in degraded]
    lines += [f'FAIL {item}' for item in failures]
    lines += ['', f'结果：{"PASS" if not failures else "FAIL"}（通过 {len(passes)}，降级 {len(degraded)}，失败 {len(failures)}）']
    out.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print('\n'.join(lines))
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
