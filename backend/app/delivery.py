import json
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from app.writing import BODY_FILES


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_ROOT = PROJECT_ROOT / 'skill_runtime' / 'scripts'
WORD_FILENAMES = {
    'A': '综述初稿.docx',
    'A_DIALOGUE': '综述初稿.docx',
    'B': '标书-文献综述分析.docx',
    'C1': '综述初稿.docx',
    'C2': '综述初稿.docx',
    'D': '调研报告.docx',
    'E': '综述初稿.docx',
}

WORD_RANGES = {
    'A': '1500-2500',
    'A_DIALOGUE': '1500-4000',
    'B': '2000-3000',
    'C1': '800-1200',
    'C2': '800-1200',
    'D': '3000-6000',
    'E': '1500-2500',
}


@dataclass
class DeliveryTask:
    id: str
    mode: str
    direction: str
    papers: list
    body: str
    evidence_ledger: str
    components: dict = field(default_factory=dict)
    outline: str = ''
    sample: str = ''
    delivery_form: str = 'ALL'
    requirements: list = field(default_factory=list)
    search_log: str = ''


@dataclass
class DeliveryResult:
    artifacts: dict
    clean: bool
    failures: list
    warnings: list = field(default_factory=list)
    dialogue: dict = None

    def __getitem__(self, key):
        return self.artifacts[key]

    def __contains__(self, key):
        return key in self.artifacts

    def get(self, key, default=None):
        return self.artifacts.get(key, default)


def _pending_runs(paragraph, text, office):
    parts = re.split(r'(【待核实】[^。！？\n]*[。！？]?)', text)
    for part in parts:
        if not part:
            continue
        run = paragraph.add_run() if office == 'pptx' else paragraph.add_run(part)
        if office == 'pptx':
            run.text = part
        if '【待核实】' not in part:
            continue
        if office == 'docx':
            from docx.enum.text import WD_COLOR_INDEX
            run.font.highlight_color = WD_COLOR_INDEX.YELLOW
        else:
            from pptx.dml.color import RGBColor
            run.font.bold = True
            run.font.color.rgb = RGBColor(0xFF, 0xB4, 0xC2)


def _write_docx(task, body, path):
    from docx import Document
    from docx.shared import Pt

    document = Document()
    document.add_heading(task.direction, 0)
    for raw in body.splitlines():
        line = raw.strip()
        if not line or line.startswith('|---'):
            continue
        heading = re.match(r'^(#{1,4})\s+(.+)', line)
        if heading:
            paragraph = document.add_heading('', level=min(len(heading.group(1)), 3))
            _pending_runs(paragraph, heading.group(2), 'docx')
        elif line.startswith('- '):
            paragraph = document.add_paragraph(style='List Bullet')
            _pending_runs(paragraph, line[2:], 'docx')
        elif line.startswith('|') and line.endswith('|'):
            paragraph = document.add_paragraph()
            _pending_runs(paragraph, line.strip('|').replace('|', '｜'), 'docx')
        else:
            paragraph = document.add_paragraph()
            _pending_runs(paragraph, line, 'docx')
        for run in paragraph.runs:
            if run.font.size is None:
                run.font.size = Pt(10.5)
    document.save(path)


def _slide_lines(items, limit=7):
    lines = []
    for item in items:
        for line in str(item).splitlines():
            cleaned = line.strip()
            if cleaned:
                lines.append(cleaned)
    return [lines[index:index + limit] for index in range(0, len(lines), limit)] or [[]]


LEGEND_ENTRY_BUDGET_EM = 8.0
_LEGIN_LATIN_EM = 0.56
_LEGIN_SPACE_EM = 0.4


def _legend_label_em_width(label):
    """Estimate single-line legend text width in CJK em units at the legend font size."""
    width = 0.0
    for char in label:
        if (
            '一' <= char <= '鿿'
            or '　' <= char <= '〿'
            or '＀' <= char <= '￯'
        ):
            width += 1.0
        elif char == ' ':
            width += _LEGIN_SPACE_EM
        else:
            width += _LEGIN_LATIN_EM
    return width


def _wrap_legend_label(label):
    """Wrap an over-wide legend label onto two lines at a latin/CJK space boundary.

    Both WPS and LibreOffice pack bottom-legend entries with tight fixed gaps;
    entries wider than LEGEND_ENTRY_BUDGET_EM collide with the neighbouring
    swatch (FOLLOWUP-P07-LEGEND). A newline inside the category value is
    honoured as a line break by both engines, in the legend and data labels.
    """
    label = str(label)
    if _legend_label_em_width(label) <= LEGEND_ENTRY_BUDGET_EM:
        return label
    head, separator, tail = label.partition(' ')
    if (
        separator
        and tail
        and _legend_label_em_width(head) <= LEGEND_ENTRY_BUDGET_EM
        and _legend_label_em_width(tail) <= LEGEND_ENTRY_BUDGET_EM
    ):
        return f'{head}\n{tail}'
    return label


def _add_flow_nodes(slide, lines):
    from pptx.dml.color import RGBColor
    from pptx.enum.shapes import MSO_CONNECTOR, MSO_SHAPE
    from pptx.util import Inches, Pt

    nodes = lines[:4] if len(lines) >= 4 else ['研究对象', '方法', '证据', '决策']
    for index, text in enumerate(nodes):
        left = 0.68 + index * 3.0
        node = slide.shapes.add_shape(
            MSO_SHAPE.ROUNDED_RECTANGLE,
            Inches(left), Inches(2.05), Inches(2.55), Inches(1.15),
        )
        node.text_frame.text = text
        node.text_frame.word_wrap = True
        for paragraph in node.text_frame.paragraphs:
            for run in paragraph.runs:
                run.font.size = Pt(12)
                run.font.color.rgb = RGBColor(0x7E, 0xF0, 0xC8)
        if index < len(nodes) - 1:
            connector = slide.shapes.add_connector(
                MSO_CONNECTOR.STRAIGHT,
                Inches(left + 2.55), Inches(2.62),
                Inches(left + 3.0), Inches(2.62),
            )
            connector.line.color.rgb = RGBColor(0x63, 0xB3, 0xFF)
            connector.line.width = Pt(1.5)


def _add_ppt_slide(prs, title, lines, layout='stacked', variant=None, chart_spec=None):
    from pptx.chart.data import ChartData
    from pptx.dml.color import RGBColor
    from pptx.enum.chart import XL_CHART_TYPE
    from pptx.util import Inches, Pt

    variant = variant or {}
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    background = slide.background.fill
    background.solid()
    background.fore_color.rgb = RGBColor(0x07, 0x0B, 0x16)
    title_box = slide.shapes.add_textbox(Inches(0.65), Inches(0.42), Inches(12), Inches(0.72))
    title_paragraph = title_box.text_frame.paragraphs[0]
    title_run = title_paragraph.add_run()
    title_run.text = title
    title_run.font.size = Pt(30)
    title_run.font.bold = True
    title_run.font.color.rgb = RGBColor(0xEA, 0xF1, 0xFF)
    accent = slide.shapes.add_shape(1, Inches(0.68), Inches(1.18), Inches(1.1), Inches(0.035))
    accent.fill.solid()
    accent.fill.fore_color.rgb = RGBColor(0x7E, 0xF0, 0xC8)
    accent.line.fill.background()

    if layout == 'flow_diagram':
        _add_flow_nodes(slide, lines)
        if title == '研究背景与科学问题':
            for index, line in enumerate(lines[1:]):
                note = slide.shapes.add_textbox(
                    Inches(0.75), Inches(3.45 + index * 0.55), Inches(11.8), Inches(0.5),
                )
                run = note.text_frame.paragraphs[0].add_run()
                run.text = line
                run.font.size = Pt(14)
                run.font.color.rgb = RGBColor(0x9F, 0xB0, 0xCC)
    elif chart_spec:
        from pptx.enum.chart import XL_DATA_LABEL_POSITION, XL_LEGEND_POSITION

        data = ChartData()
        data.categories = [_wrap_legend_label(category) for category in chart_spec['categories']]
        for series in chart_spec['series']:
            data.add_series(series['name'], series['values'])
        chart_type = XL_CHART_TYPE.LINE if chart_spec.get('type') == 'line' else XL_CHART_TYPE.PIE
        chart = slide.shapes.add_chart(chart_type, Inches(0.8), Inches(1.48), Inches(11.6), Inches(5.2), data).chart
        chart.has_legend = True
        chart.legend.position = XL_LEGEND_POSITION.BOTTOM
        chart.legend.include_in_layout = False
        chart.legend.font.size = Pt(12)
        plot = chart.plots[0]
        plot.has_data_labels = True
        labels = plot.data_labels
        labels.show_category_name = True
        labels.show_value = True
        labels.show_legend_key = False
        labels.show_percentage = False
        labels.position = (
            XL_DATA_LABEL_POSITION.ABOVE if chart_spec.get('type') == 'line'
            else XL_DATA_LABEL_POSITION.OUTSIDE_END
        )
        labels.font.size = Pt(11)
    elif layout == 'table':
        rows = [line.split('｜') for line in lines]
        table = slide.shapes.add_table(len(rows) + 1, 6, Inches(0.55), Inches(1.45), Inches(12.2), Inches(4.9)).table
        headers = ['方法族', '技术', '数据', '优势', '局限', '文献']
        for column, header in enumerate(headers):
            table.cell(0, column).text = header
        for row_index, values in enumerate(rows, 1):
            for column in range(6):
                table.cell(row_index, column).text = values[column] if column < len(values) else ''
        for row in table.rows:
            for cell in row.cells:
                for paragraph in cell.text_frame.paragraphs:
                    for run in paragraph.runs:
                        run.font.size = Pt(11)
        from pptx.enum.shapes import MSO_CONNECTOR, MSO_SHAPE
        for index, label in enumerate(('输入', '方法', '验证', '输出')):
            node = slide.shapes.add_shape(
                MSO_SHAPE.ROUNDED_RECTANGLE,
                Inches(0.68 + index * 3.0),
                Inches(6.35),
                Inches(2.55),
                Inches(0.46),
            )
            node.text_frame.text = label
            node.text_frame.paragraphs[0].runs[0].font.size = Pt(12)
            node.text_frame.paragraphs[0].runs[0].font.color.rgb = RGBColor(0x7E, 0xF0, 0xC8)
            if index < 3:
                left = 0.68 + index * 3.0
                connector = slide.shapes.add_connector(
                    MSO_CONNECTOR.STRAIGHT,
                    Inches(left + 2.55), Inches(6.58),
                    Inches(left + 3.0), Inches(6.58),
                )
                connector.line.color.rgb = RGBColor(0x63, 0xB3, 0xFF)
                connector.line.width = Pt(1.5)
    else:
        if layout in {'split_list', 'reading', 'references'}:
            columns = 2
        elif layout == 'summary':
            columns = 3
        else:
            columns = 1
        grouped = [lines[index::columns] for index in range(columns)]
        for column, column_lines in enumerate(grouped):
            if layout == 'asym':
                left = variant.get('side') == 'right'
                x = 6.3 if left else 0.72
                width = 5.9
            elif columns > 1:
                x = 0.55 + column * (12.2 / columns)
                width = 11.7 / columns
            else:
                x = 0.72
                width = 11.8
            body_box = slide.shapes.add_textbox(Inches(x), Inches(1.45), Inches(width), Inches(5.45))
            frame = body_box.text_frame
            frame.word_wrap = True
            frame.clear()
            for index, line in enumerate(column_lines):
                paragraph = frame.paragraphs[0] if index == 0 else frame.add_paragraph()
                paragraph.space_after = Pt(12 if len(column_lines) <= 8 else 4)
                text = f'{index + 1:02d}  {line}' if layout in {'flow', 'toc'} else line
                _pending_runs(paragraph, text, 'pptx')
                for run in paragraph.runs:
                    run.font.size = Pt(17 if len(column_lines) <= 6 else 14 if len(column_lines) <= 9 else 9)
                    if '【待核实】' not in run.text:
                        run.font.color.rgb = RGBColor(0xD8, 0xE5, 0xFA)
    number = slide.shapes.add_textbox(Inches(12.2), Inches(7.05), Inches(0.6), Inches(0.25))
    number.text_frame.text = str(len(prs.slides))
    number.text_frame.paragraphs[0].runs[0].font.size = Pt(9)
    number.text_frame.paragraphs[0].runs[0].font.color.rgb = RGBColor(0x9F, 0xB0, 0xCC)
    return slide


def _reference_entries(reference_markdown):
    entries = []
    for line in reference_markdown.splitlines():
        match = re.match(r'^\[(\d+)\]\s+(.+)', line.strip())
        if match:
            entries.append({'ref_no': int(match.group(1)), 'text': line.strip()})
    return entries


def _compress_slides(slides, limit):
    if len(slides) <= limit:
        return slides
    if limit <= 1:
        return [('综合研究要点', [line for _, lines in slides for line in lines])]
    kept = slides[:limit - 1]
    merged = []
    for title, lines in slides[limit - 1:]:
        merged.append(title)
        merged.extend(lines)
    kept.append(('综合研究要点', merged))
    return kept


def _generic_slides(task, body, references):
    slides = [
        (task.direction, [f'模式 {task.mode}｜文献证据调研交付']),
        ('内容提纲', task.outline.splitlines()[:7] or ['按模式构件组织内容']),
    ]
    component_lines = []
    for key, value in task.components.items():
        if isinstance(value, list):
            component_lines.append(f'{key}：{len(value)} 项')
        elif isinstance(value, dict):
            component_lines.append(f'{key}：' + '、'.join(f'{k}={v}' for k, v in value.items()))
        else:
            component_lines.append(f'{key}：{value}')
    slides.append(('模式构件', component_lines[:7] or ['构件已写入 components.md']))
    if task.sample:
        slides.append(('样章', task.sample.splitlines()[:7]))
    paragraphs = []
    for line in body.split('## 参考文献')[0].splitlines():
        cleaned = re.sub(r'^#{1,4}\s+', '', line.strip())
        if cleaned:
            paragraphs.append(cleaned)
    for index, paragraph in enumerate(paragraphs, 1):
        slides.append((f'正文要点 {index}', [paragraph]))
    slides.append(('证据与复核', ['论断、引用编号与摘要原句见 evidence_ledger.md。', '详细复核结果见 verify_report.txt 与 conformance.md。']))
    reference_slides = [
        ('参考文献' if index == 0 else f'参考文献（续{index + 1}）', chunk)
        for index, chunk in enumerate(_slide_lines([item['text'] for item in references], limit=12))
    ]
    available = max(1, 12 - len(reference_slides))
    return _compress_slides(slides, available) + reference_slides


def _d_chart_slides(components):
    stats = components.get('stats', {})
    year = stats.get('year', {})
    year_groups = year.get('groups', []) if isinstance(year, dict) else []
    charts = []
    if year_groups:
        charts.append({
            'title': '年度趋势（真实聚合）',
            'lines': ['来源：OpenAlex 年度聚合；当前年可能仍在累积。'],
            'layout': 'chart',
            'chart': {
                'type': 'line',
                'categories': [str(group.get('name', group.get('year'))) for group in year_groups],
                'series': [{'name': '文献数', 'values': [group.get('count', 0) for group in year_groups]}],
            },
        })
    topics = stats.get('topics', {}).get('all', {}) if isinstance(stats.get('topics'), dict) else {}
    topic_groups = topics.get('groups', [])[:6]
    if topic_groups:
        charts.append({
            'title': '主题分布（真实聚合）',
            'lines': ['来源：OpenAlex 主题聚合；前 6 个主题。'],
            'layout': 'chart',
            'chart': {
                'type': 'pie',
                'categories': [str(group.get('name_zh') or group.get('name')) for group in topic_groups],
                'series': [{'name': '文献数', 'values': [group.get('count', 0) for group in topic_groups]}],
            },
        })
    if not charts:
        counts = {}
        for row in components.get('method_comparison', []):
            counts[row['family']] = counts.get(row['family'], 0) + 1
        if counts:
            charts.append({
                'title': '方法族分布（池内）',
                'lines': ['来源：写作池方法对比记录；按数据获取方法族计数。'],
                'layout': 'chart',
                'chart': {
                    'type': 'pie',
                    'categories': list(counts),
                    'series': [{'name': '论文数', 'values': list(counts.values())}],
                },
            })
    if not charts:
        raise ValueError('D PPT requires real year, topic, or method chart data')
    return charts


def _compress_d_specs(slides, limit):
    if len(slides) <= limit:
        return slides
    chart_slides = [slide for slide in slides if slide.get('chart')]
    others = [slide for slide in slides if not slide.get('chart')]
    if limit <= len(chart_slides):
        return chart_slides
    merged_lines = []
    for slide in others[max(0, limit - len(chart_slides) - 1):]:
        merged_lines.append(slide['title'])
        merged_lines.extend(slide['lines'])
    kept = others[:max(0, limit - len(chart_slides) - 1)]
    kept.append({'title': '综合研究要点', 'lines': merged_lines, 'layout': 'stacked'})
    return sorted(chart_slides + kept, key=lambda slide: slide.get('n', 0))


def _d_slides(task, references):
    components = task.components
    overview = components.get('search_overview', {})
    slides = [
        {'title': task.direction, 'lines': ['组会主题调研｜真实文献与证据复核'], 'layout': 'cover'},
        {'title': '汇报结构', 'lines': ['研究背景', '文献检索', '研究进展', '核心方法', '代表作精读', '研究不足与趋势', '总结与讨论', '参考文献'], 'layout': 'toc'},
        {'title': '研究背景与科学问题', 'lines': [f'研究对象：{task.direction}', '作用链条：研究问题→方法→证据→决策', '结局：形成可复核的团队研究路径（分析）'], 'layout': 'flow_diagram', 'variant': {'side': 'left'}},
        {'title': '文献检索策略', 'lines': ['数据库：' + '、'.join(overview.get('databases', [])), '检索式：' + '；'.join(overview.get('queries', []))], 'layout': 'flow'},
        {'title': '文献检索概况', 'lines': [f"写作池：{overview.get('pool_count', 0)} 篇", '检索与筛选边界详见 search_log.md。'], 'layout': 'kpi'},
    ]
    slides.extend(_d_chart_slides(components))
    for index, row in enumerate(components.get('progress', [])):
        slides.append({'title': f"研究进展｜{row['direction']}", 'lines': [row['summary']], 'layout': 'stacked' if index % 2 == 0 else 'asym', 'variant': {'side': 'right' if index % 2 else 'left'}})
    methods = components.get('method_comparison', [])
    for index, chunk in enumerate(_slide_lines([
        f"{row['family']}｜{row['technique']}｜{row['data']}｜{row['strength']}｜{row['limitation']}｜{''.join(f'[{ref}]' for ref in row['refs'])}"
        for row in methods
    ], limit=2)):
        slides.append({'title': '核心方法与技术路线', 'lines': chunk, 'layout': ('table', 'asym', 'split_list')[index % 3], 'variant': {'side': 'right' if index % 2 else 'left'}})
    reading_layouts = ('reading', 'split_list', 'stacked', 'asym')
    for index, card in enumerate(components.get('reading_cards', [])):
        layout = reading_layouts[index % len(reading_layouts)]
        slides.append({'title': f"代表作精读 [{card['ref']}]｜方法与数据", 'lines': [
            card['title'],
            f"研究问题：{card['research_question']}",
            f"数据：{card['data']}",
            f"方法：{card['method']}",
            f"阅读深度：{card['reading_depth']}",
        ], 'layout': layout, 'variant': {'side': 'right' if index % 2 else 'left'}})
        slides.append({'title': f"代表作精读 [{card['ref']}]｜发现与启发", 'lines': [
            f"主要发现：{card['findings']}",
            f"局限：{card['limitations']}",
            f"对团队研究的启发：{card['team_relevance']}",
            f"选篇理由：{card['reason']}",
        ], 'layout': layout, 'variant': {'side': 'left' if index % 2 else 'right'}})
    for chunk in _slide_lines(components.get('limitations', []), limit=3):
        slides.append({'title': '研究不足｜五个角度', 'lines': chunk, 'layout': 'split_list'})
    slides.append({'title': '发展趋势｜不足→潜在突破', 'lines': components.get('trends', ['趋势证据不足，未作确定判断。']) + ['现有不足→潜在突破（分析）'], 'layout': 'flow_diagram'})
    for index, slide in enumerate(slides, 1):
        slide['n'] = index

    ranking = components.get('ranking', [])
    if ranking:
        priority = f"优先方向：{ranking[0]['topic']}（分析）"
        next_step = f"下一步研究建议：先核对{ranking[0].get('risk', '数据与可行性')}，再确定验证方案。"
    else:
        priority = '优先方向：先在组会确认数据可得性与非重复问题（分析）'
        next_step = '下一步研究建议：先完成数据与团队基础核验，再确定验证方案。'
    summary = [
        {'title': '总结与下一步建议', 'lines': [row['summary'] for row in components.get('progress', [])][:3] + [priority, next_step], 'layout': 'summary'},
        {'title': '团队讨论与决策', 'lines': components.get('discussion_questions', []) + ['还需要补哪些证据？', '下一步由谁复核哪些数据？'], 'layout': 'split_list'},
    ]
    reference_slides = []
    for index, chunk in enumerate(_slide_lines([item['text'] for item in references], limit=10)):
        reference_slides.append({'title': '参考文献' if index == 0 else f'参考文献（续{index + 1}）', 'lines': chunk, 'layout': 'references' if index % 2 == 0 else 'split_list'})
    core = _compress_d_specs(slides, 30 - len(summary) - len(reference_slides))
    for index, slide in enumerate(core + summary + reference_slides, 1):
        slide['n'] = index
    return core + summary + reference_slides


def _ppt_asset_manifest(slides):
    visuals = []
    for slide in slides:
        page = slide['n']
        if slide.get('chart'):
            visuals.append({'page': page, 'kind': 'chart', 'name': slide['title'], 'expected_text': [slide['title']]})
    for title, expected in (
        ('研究背景与科学问题', ['研究对象', '作用链条']),
        ('核心方法与技术路线', ['核心方法']),
        ('发展趋势｜不足→潜在突破', ['不足', '突破']),
    ):
        page = next((slide['n'] for slide in slides if slide['title'] == title), None)
        if page:
            visuals.append({'page': page, 'kind': 'diagram', 'name': title, 'expected_text': expected, 'min_shapes': 4})
    return {
        'summary_pages': [slide['n'] for slide in slides if slide['title'] in {'总结与下一步建议', '团队讨论与决策'}],
        'visuals': visuals,
    }


def _ppt_filename(direction):
    topic = re.sub(r'[\s/\\:*?"<>|]+', '', direction)[:24] or '主题'
    return f'{topic}组会汇报.pptx'


def _set_cjk_theme(path):
    import zipfile

    with zipfile.ZipFile(path) as source:
        entries = [(item, source.read(item.filename)) for item in source.infolist()]
    temporary = path.with_suffix('.tmp.pptx')
    with zipfile.ZipFile(temporary, 'w') as target:
        for item, data in entries:
            if item.filename == 'ppt/theme/theme1.xml':
                data = data.replace(
                    b'<a:ea typeface=""/>',
                    b'<a:ea typeface="Noto Sans CJK SC"/>',
                )
            target.writestr(item, data)
    temporary.replace(path)


def _write_pptx(task, body, references, path):
    from pptx import Presentation
    from pptx.util import Inches

    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)
    if task.mode == 'D':
        slides = _d_slides(task, references)
        for slide in slides:
            _add_ppt_slide(prs, slide['title'], slide['lines'], slide.get('layout', 'stacked'), slide.get('variant'), slide.get('chart'))
    else:
        slides = _generic_slides(task, body, references)
        for title, lines in slides:
            _add_ppt_slide(prs, title, lines)
    prs.save(path)
    _set_cjk_theme(path)
    if task.mode != 'D':
        return {'artifacts': {}, 'failures': []}

    task_dir = path.parent
    manifest = _ppt_asset_manifest(slides)
    manifest_path = task_dir / 'ppt_asset_manifest.json'
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    layout_manifest = {
        'pages': [
            {'n': slide['n'], 'title': slide['title'], 'layout': slide.get('layout', 'stacked'), 'variant': slide.get('variant', {})}
            for slide in slides
        ]
    }
    layout_path = task_dir / 'layout_manifest.json'
    layout_path.write_text(json.dumps(layout_manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    verify_report = task_dir / 'verify_ppt_report.txt'
    layout_report = task_dir / 'layout_check.json'
    structure = subprocess.run(
        [sys.executable, str(SCRIPT_ROOT / 'verify_ppt_delivery.py'), str(path), '--manifest', str(manifest_path), '--out', str(verify_report)],
        capture_output=True,
        text=True,
        timeout=120,
    )
    layout = subprocess.run(
        [sys.executable, str(SCRIPT_ROOT / 'check_layout_rotation.py'), str(layout_path), '--json', str(layout_report)],
        capture_output=True,
        text=True,
        timeout=120,
    )
    failures = []
    if structure.returncode != 0:
        failures.append('PPT 结构或图表核验未通过')
    if layout.returncode != 0:
        failures.append('PPT 版式轮转核验未通过')
    return {
        'artifacts': {
            'ppt_asset_manifest.json': manifest_path,
            'layout_manifest.json': layout_path,
            'verify_ppt_report.txt': verify_report,
            'layout_check.json': layout_report,
        },
        'failures': failures,
    }


class DeliveryService:
    def __init__(self, workspace_root, verification_runner=None, reference_checker=None):
        self.workspace_root = Path(workspace_root)
        self.verification_runner = verification_runner or self._run_preset_verifier
        self.reference_checker = reference_checker or self._run_reference_checker

    def _run_preset_verifier(self, task, body_path, report_name):
        report_path = body_path.parent / report_name
        standard_report = body_path.parent / 'verify_report.txt'
        previous = standard_report.read_text(encoding='utf-8') if report_name != 'verify_report.txt' and standard_report.exists() else None
        verifier_copy = body_path.parent / 'verify_delivery.py'
        shutil.copyfile(SCRIPT_ROOT / 'verify_delivery.py', verifier_copy)
        command = [sys.executable, str(verifier_copy), body_path.name]
        if report_name == 'verify_report_ppt.txt':
            command.append('2000-4000')
        else:
            command.append(WORD_RANGES.get(task.mode, '1500-2500'))
            if task.mode in {'A', 'A_DIALOGUE', 'B', 'C1', 'C2', 'D'}:
                command.extend(['--mode', task.mode])
        completed = subprocess.run(command, cwd=body_path.parent, capture_output=True, text=True, timeout=120)
        generated = standard_report.read_text(encoding='utf-8') if standard_report.exists() else completed.stdout + completed.stderr
        report_path.write_text(generated, encoding='utf-8')
        if previous is not None:
            standard_report.write_text(previous, encoding='utf-8')
        failures = [line.strip() for line in generated.splitlines() if line.startswith('[FAIL]')]
        if completed.returncode not in {0, 1} and not failures:
            failures = [f'verifier exited with {completed.returncode}']
        warnings = [line.strip() for line in generated.splitlines() if line.startswith('  [') and '待人工' in generated]
        return {
            'clean': completed.returncode == 0,
            'failures': failures,
            'warnings': warnings,
            'report': generated,
        }

    def _run_reference_checker(self, papers_path, output_path):
        try:
            completed = subprocess.run(
                [sys.executable, str(SCRIPT_ROOT / 'verify_references.py'), str(papers_path), '--out', str(output_path)],
                capture_output=True,
                text=True,
                timeout=180,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            issue = f'著录核验网络或执行失败：{type(error).__name__}'
            Path(output_path).write_text(f'# 著录核验\n\n{issue}，未完成在线核验。\n', encoding='utf-8')
            return {'clean': False, 'issues': [issue]}
        report = Path(output_path).read_text(encoding='utf-8') if Path(output_path).exists() else completed.stdout + completed.stderr
        if not Path(output_path).exists():
            Path(output_path).write_text(report, encoding='utf-8')
        issues = []
        if completed.returncode != 0:
            issues.append(f'著录核验执行失败（退出码 {completed.returncode}）')
        for line in report.splitlines():
            if any(marker in line for marker in ('维持需人工核对', '均未收录', '不一致', '需人工判定', '网络失败')):
                issues.append(line.strip())
        return {'clean': not issues, 'issues': issues}

    def _renumber_citations(self, task, body_path):
        if task.mode not in {'B', 'C1', 'C2', 'E'}:
            return None
        completed = subprocess.run(
            [sys.executable, str(SCRIPT_ROOT / 'renumber_citations.py'), body_path.name],
            cwd=body_path.parent,
            capture_output=True,
            text=True,
            timeout=60,
        )
        if completed.returncode != 0:
            return '引用编号重排失败：' + (completed.stderr or completed.stdout).strip()[-500:]
        return body_path.parent / 'citation_map.json'

    def _format_references(self, task_dir):
        completed = subprocess.run(
            [sys.executable, str(SCRIPT_ROOT / 'format_references.py'), 'papers.json', '--out', 'references.md'],
            cwd=task_dir,
            capture_output=True,
            text=True,
            timeout=60,
        )
        if completed.returncode != 0:
            raise RuntimeError('GB/T reference formatting failed')
        return (task_dir / 'references.md').read_text(encoding='utf-8')

    def _dialogue(self, task, body, references):
        points = []
        for line in body.split('## 参考文献')[0].splitlines():
            cleaned = line.strip().lstrip('-').strip()
            if cleaned and (re.search(r'\[\d+\]', cleaned) or '【待核实】' in cleaned):
                points.append(cleaned)
            if len(points) == 8:
                break
        payload = {
            'mode': task.mode,
            'direction': task.direction,
            'key_points': points,
            'references': references[:10],
        }
        if task.mode == 'A_DIALOGUE':
            payload.update({
                'topic_groups': task.components.get('topic_groups', []),
                'overall_first': task.components.get('overall_first', {}),
                'body': body,
            })
        return payload

    def deliver(self, task):
        task_dir = self.workspace_root / task.id
        task_dir.mkdir(parents=True, exist_ok=True)
        (task_dir / 'papers.json').write_text(json.dumps({
            'topic': task.direction,
            'count': len(task.papers),
            'papers': task.papers,
        }, ensure_ascii=False, indent=2), encoding='utf-8')
        (task_dir / 'evidence_ledger.md').write_text(task.evidence_ledger, encoding='utf-8')
        (task_dir / 'components.md').write_text(json.dumps(task.components, ensure_ascii=False, indent=2), encoding='utf-8')
        (task_dir / 'outline.md').write_text(task.outline, encoding='utf-8')
        (task_dir / 'sample.md').write_text(task.sample, encoding='utf-8')
        if task.search_log:
            (task_dir / 'search_log.md').write_text(task.search_log, encoding='utf-8')

        reference_markdown = self._format_references(task_dir)
        references = _reference_entries(reference_markdown)
        body_without_refs = task.body.split('## 参考文献')[0].rstrip()
        body = body_without_refs + '\n\n## 参考文献\n\n' + '\n'.join(item['text'] for item in references) + '\n'
        body_path = task_dir / BODY_FILES.get(task.mode, '综述初稿.md')
        body_path.write_text(body, encoding='utf-8')
        citation_map = self._renumber_citations(task, body_path)
        if isinstance(citation_map, str):
            verification = {
                'clean': False,
                'failures': [citation_map],
                'warnings': [],
                'report': citation_map,
            }
            (task_dir / 'verify_report.txt').write_text(citation_map + '\n', encoding='utf-8')
        else:
            verification = self.verification_runner(task, body_path, 'verify_report.txt')
            body = body_path.read_text(encoding='utf-8')
        reference_result = self.reference_checker(task_dir / 'papers.json', task_dir / 'references_check.md')
        artifacts = {
            BODY_FILES.get(task.mode, '综述初稿.md'): body_path,
            'papers.json': task_dir / 'papers.json',
            'evidence_ledger.md': task_dir / 'evidence_ledger.md',
            'verify_report.txt': task_dir / 'verify_report.txt',
            'references.md': task_dir / 'references.md',
            'references_check.md': task_dir / 'references_check.md',
        }
        failures = list(verification.get('failures') or [])
        if citation_map is not None and not isinstance(citation_map, str):
            artifacts['citation_map.json'] = citation_map
        if not verification.get('clean') and not failures:
            failures.append('证据复核未通过，未返回失败明细')
        warnings = list(verification.get('warnings') or [])
        failures.extend(reference_result.get('issues') or [])
        dialogue = None
        form = task.delivery_form.upper()

        if form in {'A', 'ALL'}:
            word_name = WORD_FILENAMES.get(task.mode, '综述初稿.docx')
            report_path = task_dir / word_name
            _write_docx(task, body, report_path)
            artifacts[word_name] = report_path
        if form in {'C', 'ALL'}:
            slides_path = task_dir / _ppt_filename(task.direction)
            ppt_result = _write_pptx(task, body, references, slides_path)
            artifacts[slides_path.name] = slides_path
            artifacts.update(ppt_result['artifacts'])
            failures.extend(ppt_result['failures'])
            if task.mode == 'D':
                extracted = task_dir / '汇报文本.md'
                completed = subprocess.run(
                    [sys.executable, str(SCRIPT_ROOT / 'pptx_to_text.py'), str(slides_path), '--out', str(extracted)],
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
                if completed.returncode != 0:
                    failures.append('PPT 文本抽取或参考文献页识别失败')
                else:
                    if 'extractor=python-pptx-fallback' in completed.stdout:
                        warnings.append('slidep 调用失败，PPT 文本抽取已使用 python-pptx 离线备用解析')
                    ppt_verification = self.verification_runner(task, extracted, 'verify_report_ppt.txt')
                    ppt_failures = list(ppt_verification.get('failures') or [])
                    if not ppt_verification.get('clean') and not ppt_failures:
                        ppt_failures.append('PPT 证据复核未通过，未返回失败明细')
                    failures.extend(ppt_failures)
                    warnings.extend(ppt_verification.get('warnings') or [])
                artifacts['汇报文本.md'] = extracted
                artifacts['verify_report_ppt.txt'] = task_dir / 'verify_report_ppt.txt'
        if form in {'B', 'ALL'}:
            dialogue = self._dialogue(task, body, references)
            dialogue_path = task_dir / 'dialogue.json'
            dialogue_path.write_text(json.dumps(dialogue, ensure_ascii=False, indent=2), encoding='utf-8')
            artifacts['dialogue.json'] = dialogue_path

        requirements = list(task.requirements)
        for requirement in requirements:
            if not requirement.get('passed', False):
                failures.append(f"未落实要求：{requirement.get('requirement', '')}")
        conformance = [
            '# 需求符合性对账', '',
            '| 要求 | 落实位置 | 结果 | 原因与补救 |',
            '|---|---|---|---|',
        ]
        for requirement in requirements:
            conformance.append(
                f"| {requirement.get('requirement', '')} | {requirement.get('location', '')} | {'通过' if requirement.get('passed') else '未通过'} | {requirement.get('reason', '')} |"
            )
        conformance.extend(['', '## 证据复核', ''])
        conformance.append('通过：预置复核未报告失败。' if verification.get('clean') else '未通过：' + '；'.join(verification.get('failures') or []))
        conformance.extend(['', '## 著录核验', ''])
        if reference_result.get('clean'):
            conformance.append('通过：著录核验未报告未解决项。')
        else:
            conformance.extend(f'- 未通过：{issue}' for issue in reference_result.get('issues') or [])
        if warnings:
            conformance.extend(['', '## 待人工确认', ''] + [f'- {warning}' for warning in warnings])
        conformance_path = task_dir / 'conformance.md'
        conformance_path.write_text('\n'.join(conformance) + '\n', encoding='utf-8')
        artifacts['conformance.md'] = conformance_path
        clean = not failures and all(requirement.get('passed', False) for requirement in requirements)
        return DeliveryResult(
            artifacts=artifacts,
            clean=clean,
            failures=failures,
            warnings=warnings,
            dialogue=dialogue,
        )
