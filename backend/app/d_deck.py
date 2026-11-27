"""D 组会汇报 PPT：参考版式（白底墨绿、栏目编号、结论式标题）生成器。

数据只取 task.components（progress/method_comparison/reading_cards/ranking/
discussion_questions/stats）、task.papers、task.search_log 与已采集图 bundle，
不新造文献事实；归纳判断统一标“分析”。
"""
import json
import math
import re
from pathlib import Path

from PIL import Image
from pptx import Presentation
from pptx.chart.data import ChartData
from pptx.dml.color import RGBColor
from pptx.enum.chart import XL_CHART_TYPE
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Inches, Pt

DEEP, PRIM, INK = '123F33', '2C6E5A', '12362C'
BODY, MUTED, LINE = '23342E', '6E8078', 'CBD9D2'
TINT, TINT2, WARM, WHITE = 'E9F1EC', 'F5F9F6', 'A2543C', 'FFFFFF'
FONT = 'PingFang SC'
FS_TITLE, FS_KICKER, FS_CARD, FS_BODY = 30, 22, 27, 22
FS_META, FS_TABLE, FS_HERO = 13.5, 16.5, 36


def C(hexv):
    return RGBColor.from_string(hexv)


def X(v):
    return Inches(v / 96)


def _clip(text, limit):
    text = re.sub(r'\s+', ' ', str(text or '')).strip()
    return text if len(text) <= limit else text[: limit - 1] + '…'


def _first_sentence(text, limit):
    text = re.sub(r'\s+', ' ', str(text or '')).strip()
    match = re.match(r'[^。！？!?]+[。！？!?]?', text)
    return _clip(match.group(0) if match else text, limit)


class DDeck:
    def __init__(self, task, references, figure_bundle, out_path):
        self.task = task
        self.components = task.components or {}
        self.papers = task.papers or []
        self.references = references or []
        self.bundle = figure_bundle
        self.out_path = Path(out_path)
        self.prs = Presentation()
        self.prs.slide_width, self.prs.slide_height = Inches(13.333333), Inches(7.5)
        self.blank = self.prs.slide_layouts[6]
        self.records = []
        self.manifest = []
        self.total = 0
        self.used = set()
        self.summary_pages = []

    # ---------- primitives ----------
    def text(self, slide, value, x, y, w, h, size=FS_BODY, color=BODY, bold=False,
             align=PP_ALIGN.LEFT, valign=MSO_ANCHOR.TOP, margin=0, line=1.12):
        box = slide.shapes.add_textbox(X(x), X(y), X(w), X(h))
        tf = box.text_frame
        tf.clear()
        tf.word_wrap = True
        tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = X(margin)
        tf.vertical_anchor = valign
        for i, item in enumerate(str(value).split('\n')):
            p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
            p.alignment = align
            p.line_spacing = line
            p.space_after = Pt(3)
            r = p.add_run()
            r.text = item
            r.font.name = FONT
            r.font.size = Pt(size)
            r.font.bold = bold
            r.font.color.rgb = C(color)
        return box

    def shape(self, slide, x, y, w, h, fill=WHITE, stroke=LINE, radius=True, width=0.8):
        shp = slide.shapes.add_shape(
            MSO_SHAPE.ROUNDED_RECTANGLE if radius else MSO_SHAPE.RECTANGLE,
            X(x), X(y), X(w), X(h),
        )
        shp.fill.solid()
        shp.fill.fore_color.rgb = C(fill)
        shp.line.color.rgb = C(stroke)
        shp.line.width = Pt(width)
        return shp

    def footer(self, slide, n):
        self.shape(slide, 72, 684, 1136, 1, LINE, LINE, False)
        self.text(slide, '来源：OpenAlex 聚合与池内摘要', 72, 690, 900, 20, FS_META, MUTED)
        self.text(slide, f'{n:02d} / {self.total:02d}', 1100, 690, 108, 20, FS_META, PRIM, True, PP_ALIGN.RIGHT)

    def page(self, title, section, kind):
        n = len(self.records) + 1
        slide = self.prs.slides.add_slide(self.blank)
        slide.background.fill.solid()
        slide.background.fill.fore_color.rgb = C(WHITE)
        self.records.append((n, title, section, kind))
        if n > 2:
            self.text(slide, section, 72, 24, 1060, 34, FS_KICKER, MUTED)
            self.text(slide, title, 72, 66, 1136, 66, FS_TITLE, INK, True)
            self.shape(slide, 72, 137, 52, 4, PRIM, PRIM, False)
            self.shape(slide, 138, 139, 1070, 1, LINE, LINE, False)
            self.footer(slide, n)
        return slide

    def card(self, slide, title, body, x, y, w, h, dark=False, size=FS_BODY):
        self.shape(slide, x, y, w, h, DEEP if dark else TINT, DEEP if dark else LINE)
        self.text(slide, title, x + 20, y + 14, w - 40, 40, FS_CARD, WHITE if dark else INK, True)
        self.text(slide, body, x + 20, y + 62, w - 40, h - 74, size, 'D9E8E1' if dark else BODY)

    def flow(self, slide, items, x, y, w, h, font_size=FS_BODY, arrow='→'):
        gap, aw = 16, 24
        bw = (w - (len(items) - 1) * (gap + aw)) / max(1, len(items))
        for i, item in enumerate(items):
            bx = x + i * (bw + gap + aw)
            self.shape(slide, bx, y, bw, h, TINT if i % 2 == 0 else TINT2, LINE)
            self.text(slide, item, bx + 8, y + 8, bw - 16, h - 16, font_size, INK, True,
                      PP_ALIGN.CENTER, MSO_ANCHOR.MIDDLE, line=1.05)
            if i < len(items) - 1:
                self.text(slide, arrow, bx + bw + 2, y + h / 2 - 20, aw + gap - 4, 40, FS_BODY, PRIM,
                          True, PP_ALIGN.CENTER)

    def picture(self, slide, image_path, x, y, w, h, caption=None):
        path = Path(image_path)
        self.shape(slide, x, y, w, h, WHITE, LINE)
        if path.is_file():
            with Image.open(path) as im:
                iw, ih = im.size
            scale = min((w - 18) / iw, (h - 46) / ih)
            pw, ph = iw * scale, ih * scale
            slide.shapes.add_picture(str(path), X(x + (w - pw) / 2), X(y + 8 + (h - 46 - ph) / 2),
                                     X(pw), X(ph))
        if caption:
            self.text(slide, caption, x + 12, y + h - 30, w - 24, 24, FS_META, MUTED)

    def table(self, slide, rows, x, y, w, h, widths=None, font=FS_TABLE, header=True):
        nr, nc = len(rows), len(rows[0])
        tbl = slide.shapes.add_table(nr, nc, X(x), X(y), X(w), X(h)).table
        if widths:
            for i, val in enumerate(widths):
                tbl.columns[i].width = X(val)
        for r in range(nr):
            for c in range(nc):
                cell = tbl.cell(r, c)
                cell.margin_left = cell.margin_right = X(6)
                cell.margin_top = cell.margin_bottom = X(3)
                cell.fill.solid()
                cell.fill.fore_color.rgb = C(DEEP if header and r == 0 else (TINT2 if r % 2 else WHITE))
                tf = cell.text_frame
                tf.clear()
                tf.word_wrap = True
                p = tf.paragraphs[0]
                p.line_spacing = 1.0
                run = p.add_run()
                run.text = str(rows[r][c])
                run.font.name = FONT
                run.font.size = Pt(font)
                run.font.bold = bool(header and r == 0) or c == 0
                run.font.color.rgb = C(WHITE if header and r == 0 else (INK if c == 0 else BODY))
        return tbl

    def chart_line(self, slide, groups, x, y, w, h):
        data = [
            g for g in groups
            if str(g.get('key') or g.get('name', '')).isdigit()
            and int(g.get('key') or g.get('name')) >= 2000
        ]
        if not data:
            return None
        cd = ChartData()
        cd.categories = [str(g.get('key') or g.get('name')) for g in data]
        cd.add_series('年度发文量', [g.get('count', 0) for g in data])
        chart = slide.shapes.add_chart(XL_CHART_TYPE.LINE, X(x), X(y), X(w), X(h), cd).chart
        chart.has_legend = False
        chart.value_axis.minimum_scale = 0
        chart.value_axis.has_major_gridlines = True
        chart.value_axis.tick_labels.font.size = Pt(FS_META)
        chart.value_axis.tick_labels.font.color.rgb = C(BODY)
        chart.category_axis.tick_labels.font.size = Pt(FS_META)
        chart.category_axis.tick_labels.font.color.rgb = C(BODY)
        series = chart.series[0]
        series.format.line.color.rgb = C(PRIM)
        series.format.line.width = Pt(2.5)
        return chart

    def chart_bar(self, slide, groups, x, y, w, h):
        groups = [g for g in groups if g.get('name')][:6]
        if not groups:
            return None
        cd = ChartData()
        cd.categories = [_clip(g['name'], 22) for g in reversed(groups)]
        cd.add_series('命中篇数', [g.get('count', 0) for g in reversed(groups)])
        chart = slide.shapes.add_chart(XL_CHART_TYPE.BAR_CLUSTERED, X(x), X(y), X(w), X(h), cd).chart
        chart.has_legend = False
        chart.value_axis.has_major_gridlines = True
        chart.value_axis.tick_labels.font.size = Pt(FS_META)
        chart.value_axis.tick_labels.font.color.rgb = C(BODY)
        chart.category_axis.tick_labels.font.size = Pt(FS_META)
        chart.category_axis.tick_labels.font.color.rgb = C(BODY)
        plot = chart.plots[0]
        plot.has_data_labels = True
        plot.data_labels.show_value = True
        plot.data_labels.font.size = Pt(FS_META)
        plot.data_labels.font.color.rgb = C(INK)
        chart.series[0].format.fill.solid()
        chart.series[0].format.fill.fore_color.rgb = C(PRIM)
        return chart

    # ---------- helpers ----------
    def stats(self):
        return self.components.get('stats') if isinstance(self.components.get('stats'), dict) else {}

    def reading_refs(self):
        return [int(c.get('ref') or 0) for c in self.components.get('reading_cards') or []]

    def ref_assets(self, ref):
        if self.bundle is None:
            return []
        return [a for a in self.bundle.by_ref(ref) if str(a.path) not in self.used]

    def ref_attempt(self, ref):
        if self.bundle is None:
            return {}
        return self.bundle.degraded_for_ref(ref) or {}

    def oa_url(self, ref):
        for paper in self.papers:
            if int(paper.get('ref_no') or 0) == int(ref):
                return paper.get('oa_url') or paper.get('pdf_url') or ''
        return ''

    def plan(self):
        counts = self.components
        progress = counts.get('progress') or []
        methods = counts.get('method_comparison') or []
        reading = counts.get('reading_cards') or []
        ref_pages = max(1, math.ceil(len(self.references) / 6)) if self.references else 1
        fixed = 1 + 1 + 1 + 1 + 1 + 1  # cover toc bg retrieval year topics
        progress_pages = len(progress) if progress else 3
        method_pages = 1 + (len(methods) if methods else 4) + 1
        reading_pages = len(reading) if reading else 5
        tail = 1 + 1 + 1 + 1  # gaps trends summary discussion
        total = fixed + progress_pages + method_pages + reading_pages + tail + ref_pages
        return total, {
            'progress': progress_pages, 'methods': method_pages,
            'reading': reading_pages, 'refs': ref_pages, 'fixed': fixed, 'tail': tail,
        }

    # ---------- pages ----------
    def cover(self):
        n = len(self.records) + 1
        slide = self.prs.slides.add_slide(self.blank)
        slide.background.fill.solid()
        slide.background.fill.fore_color.rgb = C(WHITE)
        self.records.append((n, self.task.direction, '封面', 'cover'))
        self.shape(slide, 792, 0, 488, 720, DEEP, DEEP, False)
        self.shape(slide, 72, 74, 64, 6, PRIM, PRIM, False)
        self.text(slide, _clip(self.task.direction, 48), 72, 112, 660, 150, FS_TITLE, INK, True)
        self.text(slide, '组会主题调研汇报', 72, 282, 650, 48, FS_BODY, MUTED)
        self.text(slide, '从文献全景、方法边界到优先方向的团队认知路径（分析）',
                  72, 342, 620, 116, FS_BODY, INK)
        reading = self.components.get('reading_cards') or []
        self.text(slide, f'第 1/2/3/4/5/6/8 部分 · {self.total} 页', 72, 604, 650, 34, FS_META, MUTED)
        stats = [
            (str(len(self.papers)), '篇论文池 · ' + str(len(self.components.get('progress') or [])) + ' 个方向'),
            (str(len(reading) or 0), '篇代表作精读'),
            ('2', '张真实聚合数据图表'),
        ]
        for i, (num, label) in enumerate(stats):
            self.text(slide, num, 858, 106 + i * 140, 300, 74, FS_HERO, WHITE, True)
            self.text(slide, label, 858, 176 + i * 140, 350, 32, FS_META, 'BFD6CC')
        self.text(slide, 'RESEARCH LANDSCAPE', 858, 630, 350, 26, FS_META, '7FA694')
        return slide

    def toc(self, ranges):
        slide = self.page('七部分构成从领域全景到团队决策的调研路径', '目录', 'toc')
        rows = [
            ('01', '研究背景与主题介绍', ranges['bg']),
            ('02', '文献检索策略与研究概况', ranges['retrieval']),
            ('03', '国内外研究进展', ranges['progress']),
            ('04', '核心方法与技术路线', ranges['methods']),
            ('05', '代表性论文深度解读', ranges['reading']),
            ('06', '研究不足与发展趋势', ranges['gaps']),
            ('08', '总结、优先方向与讨论', ranges['summary']),
        ]
        for i, (num, label, pages) in enumerate(rows):
            y = 112 + i * 68
            self.text(slide, num, 82, y, 60, 38, FS_CARD, PRIM, True)
            self.text(slide, label, 156, y + 2, 700, 36, FS_BODY, INK)
            self.text(slide, pages, 1000, y + 4, 170, 32, FS_META, MUTED, False, PP_ALIGN.RIGHT)
            self.shape(slide, 82, y + 50, 1088, 1, LINE, LINE, False)
        self.text(slide, f'不单设第七部分；优先方向与下一步建议纳入第八部分。参考文献：P{ranges["refs"]}',
                  82, 604, 1080, 34, FS_BODY, PRIM, True)
        return slide

    def background(self):
        comp = self.components
        progress = comp.get('progress') or []
        methods = comp.get('method_comparison') or []
        reading = comp.get('reading_cards') or []
        ranking = comp.get('ranking') or []
        first = ranking[0] if ranking else {}
        slide = self.page('研究方向需要从全景进展收敛到可执行的优先问题', '01 研究背景与主题介绍', 'steps')
        self.text(slide, '主题与研究链条（分析）', 82, 156, 500, 36, FS_BODY, PRIM, True)
        self.flow(slide, [
            '研究主题\n' + _clip(self.task.direction, 12),
            '方法路线\n' + _clip((methods[0].get('family') if methods else '方法族待定'), 12),
            '证据池\n' + str(len(self.papers)) + ' 篇·' + str(len(progress)) + ' 方向',
            '优先方向\n' + _clip(first.get('topic') or '待定', 12),
        ], 82, 204, 1116, 126, font_size=FS_BODY)
        self.card(slide, '概念与调研范围',
                  f'以“问题—方法—证据—决策”链组织调研；覆盖 {len(self.papers)} 篇、'
                  f'{len(progress)} 个方向、{len(methods)} 类方法、{len(reading)} 篇精读（分析）。',
                  82, 366, 548, 220)
        question = (reading[0].get('research_question') if reading else '') or \
                   _first_sentence(first.get('reason') or '', 80) or '核心科学问题待补充。'
        self.card(slide, '核心科学问题（来自精读与排序）', _clip(question, 90),
                  654, 366, 544, 220, True)
        self.manifest.append({'page': len(self.records), 'kind': 'diagram', 'name': '主题研究链条',
                              'degraded': False, 'reason': ''})
        return slide

    def retrieval(self):
        stats = self.stats()
        year = stats.get('year') or {}
        queries = year.get('queries') or []
        total_hits = year.get('total_hits')
        slide = self.page('实际检索与筛选边界决定证据池的可复核范围', '02 文献检索策略与研究概况', 'steps')
        self.flow(slide, [
            '数据源\nOpenAlex',
            '检索式\n' + str(len(queries)) + ' 组',
            '命中\n' + (f'{total_hits:,}' if isinstance(total_hits, int) else '未记录'),
            '纳入池\n' + str(len(self.papers)) + ' 篇',
        ], 82, 166, 1116, 118, font_size=FS_BODY)
        self.card(slide, '实际检索式与过滤条件',
                  '\n'.join('· ' + _clip(q, 40) for q in queries[:4]) or '检索式未记录。',
                  82, 318, 690, 268)
        self.card(slide, '筛选与最终数量',
                  f'写作池 {len(self.papers)} 篇\n'
                  f'方向 {len(self.components.get("progress") or [])} 个\n'
                  f'精读 {len(self.components.get("reading_cards") or [])} 篇\n'
                  '覆盖边界见 search_log（分析）',
                  796, 318, 402, 268, True)
        self.manifest.append({'page': len(self.records), 'kind': 'diagram', 'name': '检索筛选流程',
                              'degraded': False, 'reason': ''})
        return slide

    def year_page(self):
        stats = self.stats()
        groups = (stats.get('year') or {}).get('groups') or []
        slide = self.page('年度发文持续升温，近年增速明显抬升', '02 文献检索策略与研究概况', 'kpi')
        chart = self.chart_line(slide, groups, 64, 166, 790, 430)
        years = [
            g for g in groups
            if str(g.get('key') or g.get('name', '')).isdigit()
            and int(g.get('key') or g.get('name')) >= 2000
        ]
        latest = years[-1] if years else {}
        total_hits = (stats.get('year') or {}).get('total_hits')
        self.card(slide, str(latest.get('count', '—')),
                  f'{latest.get("key", "")} 年当前累计值\n并非完整年度\n\n'
                  f'全量命中 {total_hits:,}（统计口径）\n阶段判断（分析）：检索热度持续上升。'
                  if isinstance(total_hits, int) else
                  f'{latest.get("key", "")} 年当前累计值\n并非完整年度（分析）',
                  878, 178, 330, 398, True)
        self.text(slide, '数据：OpenAlex group_by=publication_year，本页为可编辑原生折线图',
                  72, 616, 1080, 28, FS_META, MUTED)
        if chart is not None:
            self.manifest.append({'page': len(self.records), 'kind': 'chart', 'name': '年度发表趋势'})
        return slide

    def topic_page(self):
        stats = self.stats()
        topics = ((stats.get('topics') or {}).get('all') or {}).get('groups') or []
        slide = self.page('主题分布呈现“主干明确、长尾分散”的池内结构', '02 文献检索策略与研究概况', 'asym')
        chart = self.chart_bar(slide, topics, 48, 164, 790, 438)
        top = topics[:3]
        denominator = sum(g.get('count', 0) for g in topics) or 1
        rows = [['主题', '占比｜篇数']]
        for g in top:
            rows.append([_clip(g.get('name'), 16), f"{g.get('count', 0) / denominator * 100:.1f}%｜{g.get('count', 0)}"])
        self.table(slide, rows, 856, 166, 352, 200, widths=[190, 162])
        self.table(slide, [['池内结构', '数量'],
                           ['写作池', f'{len(self.papers)} 篇'],
                           ['方向', f'{len(self.components.get("progress") or [])} 个'],
                           ['精读', f'{len(self.components.get("reading_cards") or [])} 篇']],
                   856, 392, 352, 210, widths=[190, 162])
        if chart is not None:
            self.manifest.append({'page': len(self.records), 'kind': 'chart', 'name': '研究主题分布'})
        return slide

    def progress_pages(self):
        rows = self.components.get('progress') or []
        for i, row in enumerate(rows, 1):
            title = _first_sentence(row.get('summary') or row.get('direction') or '研究方向', 34)
            slide = self.page(title, f'03 国内外研究进展 · 方向{"一二三四五六七"[min(i, 7) - 1]}', ('steps', 'asym', 'stacked')[(i - 1) % 3])
            refs = ''.join(f'[{r}]' for r in row.get('refs') or [])
            if i % 2:
                self.flow(slide, [
                    '方向\n' + _clip(row.get('direction'), 12),
                    '推进\n' + _clip(row.get('summary'), 16),
                    '证据\n' + (refs or '摘要证据'),
                ], 82, 180, 1116, 150, font_size=FS_BODY)
                self.card(slide, '主要进展（据摘要）', _clip(row.get('summary'), 84), 82, 372, 548, 210)
                self.card(slide, '对团队的含义（分析）',
                          '该方向的证据强度与缺口需结合方法页与精读页判断；未提供团队既有基础。',
                          654, 372, 544, 210, True)
            else:
                self.card(slide, '方向与主要进展', _clip(row.get('summary'), 84), 82, 166, 548, 300)
                self.card(slide, '代表作与边界', f'代表作 {refs or "见精读页"}（据摘要）\n'
                          '跨研究外推与数据可得性构成主要边界（分析）。',
                          654, 166, 544, 300, True)
                self.table(slide, [['字段', '内容'],
                                   ['研究方向', _clip(row.get('direction'), 18)],
                                   ['证据编号', refs or '—']],
                           82, 496, 1116, 150, widths=[220, 896])
            self.manifest.append({'page': len(self.records), 'kind': 'diagram', 'name': f'方向{i}进展',
                                  'degraded': False, 'reason': ''})

    def method_pages(self):
        methods = self.components.get('method_comparison') or []
        progress_count = len(self.components.get('progress') or [])
        overview_layout = 'asym' if progress_count and progress_count % 3 == 1 else 'steps'
        slide = self.page('没有单一方法能独立完成领域文献的结构化分析', '04 核心方法与技术路线', overview_layout)
        families = [m.get('family') or '方法族' for m in methods[:4]] or ['方法族待定']
        self.flow(slide, ['方法族\n' + _clip(f, 12) for f in families], 82, 174, 1116, 142, font_size=FS_BODY)
        self.card(slide, '路线总览（分析）',
                  f'共 {len(methods)} 类方法；按“数据获取—建模—验证”分层组合，避免单点替代。',
                  82, 354, 548, 206)
        self.card(slide, '比较口径', '以数据、技术、优势与局限四列对照；引用编号与正文一致（分析）。',
                  654, 354, 544, 206, True)
        self.manifest.append({'page': len(self.records), 'kind': 'diagram', 'name': '方法路线总览',
                              'degraded': False, 'reason': ''})
        for i, m in enumerate(methods, 1):
            title = f"{_clip(m.get('family') or '方法', 10)}：{_clip(m.get('technique') or '技术路线', 16)}"
            slide = self.page(title, f'04 核心方法与技术路线 · 方法{"①②③④⑤⑥"[min(i, 6) - 1]}',
                              ('steps', 'stacked', 'asym')[(i - 1) % 3])
            refs = ''.join(f'[{r}]' for r in m.get('refs') or [])
            self.flow(slide, [
                '技术\n' + _clip(m.get('technique'), 12),
                '数据\n' + _clip(m.get('data'), 12),
                '证据\n' + (refs or '摘要证据'),
            ], 82, 174, 1116, 142, font_size=FS_BODY)
            self.card(slide, '优势（据摘要）', _clip(m.get('strength'), 84), 82, 354, 548, 206)
            self.card(slide, '局限与适用边界（据摘要＋分析）', _clip(m.get('limitation'), 84),
                      654, 354, 544, 206, True)
            self.manifest.append({'page': len(self.records), 'kind': 'diagram', 'name': f'方法{i}路线',
                                  'degraded': False, 'reason': ''})
        slide = self.page('方法对比显示组合建模优于单点替代', '04 核心方法与技术路线 · 对比表', 'table')
        rows = [['方法族', '技术', '优势', '局限', '文献']]
        for m in methods[:5]:
            rows.append([_clip(m.get('family'), 8), _clip(m.get('technique'), 10),
                         _clip(m.get('strength'), 14), _clip(m.get('limitation'), 14),
                         ''.join(f'[{r}]' for r in m.get('refs') or '')])
        self.table(slide, rows, 60, 166, 1160, 470, widths=[150, 190, 300, 300, 100], font=FS_META)
        self.manifest.append({'page': len(self.records), 'kind': 'diagram', 'name': '方法对比表',
                              'degraded': False, 'reason': ''})

    def reading_pages(self):
        cards = self.components.get('reading_cards') or []
        for i, card in enumerate(cards, 1):
            ref = int(card.get('ref') or 0)
            title = f"[{ref}] {_clip(card.get('title') or '代表作精读', 26)}"
            has_asset = bool(self.ref_assets(ref))
            layout = ('figure', 'stacked', 'two_cards')[(i - 1) % 3] if has_asset else ('two_cards', 'stacked', 'asym')[(i - 1) % 3]
            slide = self.page(title, f'05 代表作精读 · [{ref}]', layout)
            fields = [
                ('题目', _clip(card.get('title'), 26)),
                ('研究问题', _clip(card.get('research_question'), 30)),
                ('数据', _clip(card.get('data'), 30)),
                ('方法', _clip(card.get('method'), 30)),
                ('主要发现', _clip(card.get('findings'), 30)),
                ('局限', _clip(card.get('limitations'), 30)),
                ('团队启发', _clip(card.get('team_relevance'), 30)),
                ('选篇理由', _clip(card.get('reason'), 30)),
                ('阅读深度', card.get('reading_depth') or '仅摘要'),
                ('证据', f'[{ref}]'),
            ]
            rows = [[fields[k][0], fields[k][1], fields[k + 1][0], fields[k + 1][1]] for k in range(0, 10, 2)]
            assets = self.ref_assets(ref)
            stacked = layout == 'stacked'
            if stacked:
                self.table(slide, rows, 72, 160, 1136, 252, widths=[110, 458, 110, 458], font=FS_META)
                img_box = (72, 428, 1136, 232)
            else:
                self.table(slide, rows, 72, 166, 620, 452, widths=[86, 224, 86, 224], font=FS_META)
                img_box = (716, 166, 492, 452)
            if assets:
                asset = assets[0]
                caption = f'[{ref}] {asset.fig_no}，原文 p{asset.original_page}，{asset.version}'
                self.picture(slide, asset.path, *img_box, caption)
                self.used.add(str(asset.path))
                try:
                    source = str(Path(asset.path).relative_to(self.out_path.parent))
                except ValueError:
                    source = str(asset.path)
                self.manifest.append({'page': len(self.records), 'kind': 'image', 'name': f'ref{ref} 原文图',
                                      'ref_no': ref, 'file': str(Path(asset.path).name),
                                      'source': source, 'figure_no': asset.fig_no,
                                      'original_page': asset.original_page, 'version': asset.version,
                                      'acquisition': asset.acquisition, 'caption': asset.caption,
                                      'degraded': False, 'reason': ''})
            else:
                x0, y0, w0, h0 = img_box
                self.shape(slide, x0, y0, w0, h0, TINT2, LINE)
                self.text(slide, f'[{ref}] 原文图未获取', x0 + 20, y0 + h0 / 2 - 60, w0 - 40, 40,
                          FS_BODY, MUTED, True, PP_ALIGN.CENTER)
                attempt = self.ref_attempt(ref)
                reason = '; '.join((attempt.get('failures') or [])[:2]) or '未取得 OA 原图'
                self.text(slide, f'OA：{self.oa_url(ref) or "未提供"}\n原因：{_clip(reason, 70)}',
                          x0 + 20, y0 + h0 / 2 - 12, w0 - 40, 120, FS_META, WARM)
                self.manifest.append({'page': len(self.records), 'kind': 'image', 'name': f'ref{ref} 原文图',
                                      'ref_no': ref, 'degraded': True, 'allow_degraded': True,
                                      'reason': _clip(reason, 160),
                                      'attempt_log': '; '.join((attempt.get('failures') or [])[:3]) or '已定位 OA 但未取得可用原图'})

    def gaps_page(self):
        methods = self.components.get('method_comparison') or []
        reading = self.components.get('reading_cards') or []
        ranking = self.components.get('ranking') or []
        slide = self.page('现有不足集中在方法边界、数据可得性与机制证据三类', '06 研究不足与发展趋势', 'table')
        rows = [['角度', '主要不足（分析）', '依据']]
        picks = [
            ('方法', (methods[0].get('limitation') if methods else ''), '方法对比'),
            ('数据', (reading[0].get('data') if reading else ''), f'[{reading[0].get("ref") if reading else "—"}]'),
            ('机制', (reading[0].get('limitations') if reading else ''), f'[{reading[0].get("ref") if reading else "—"}]'),
            ('应用', (ranking[0].get('risk') if ranking else ''), '排序风险'),
            ('理论', (reading[-1].get('limitations') if reading else ''), f'[{reading[-1].get("ref") if reading else "—"}]'),
        ]
        for angle, text, basis in picks:
            rows.append([angle, _clip(text or '池内证据未覆盖，需人工核对。', 34), basis])
        self.table(slide, rows, 60, 166, 1160, 440, widths=[110, 880, 170])
        self.text(slide, '说明：不足项均来自方法、精读与排序中的原文/分析字段，未新增文献外事实。',
                  72, 626, 1080, 26, FS_META, MUTED)
        self.manifest.append({'page': len(self.records), 'kind': 'diagram', 'name': '研究不足表',
                              'degraded': False, 'reason': ''})

    def trend_page(self):
        methods = self.components.get('method_comparison') or []
        reading = self.components.get('reading_cards') or []
        ranking = self.components.get('ranking') or []
        slide = self.page('研究前沿正转向组合方法与人机协同', '06 研究不足与发展趋势', 'steps')
        self.flow(slide, [
            '已较成熟\n' + _clip((methods[0].get('family') if methods else '方法'), 12),
            '仍有争议\n' + _clip((reading[0].get('limitations') if reading else '证据边界'), 12),
            '尚未充分\n' + _clip((ranking[0].get('risk') if ranking else '机制证据'), 12),
            '可能突破\n' + _clip((ranking[0].get('topic') if ranking else '组合路线'), 12),
        ], 82, 180, 1116, 150, font_size=FS_BODY)
        self.card(slide, '趋势判断（分析）',
                  '方法组合、可解释性与人机协同比单点技术更可能形成突破；需以团队数据条件验证。',
                  82, 372, 548, 210)
        self.card(slide, '对优先方向的含义（分析）',
                  _clip((ranking[0].get('reason') if ranking else '优先方向待补充。'), 110),
                  654, 372, 544, 210, True)
        self.manifest.append({'page': len(self.records), 'kind': 'diagram', 'name': '不足→潜在突破路径',
                              'degraded': False, 'reason': ''})

    def summary_page(self):
        reading = self.components.get('reading_cards') or []
        ranking = self.components.get('ranking') or []
        findings = [_clip(c.get('findings'), 48) for c in reading[:3]] or ['精读发现待补充。']
        slide = self.page('三项发现落到优先方向与下一步验证', '08 总结与讨论', 'summary')
        x = 82
        for i, finding in enumerate(findings):
            self.card(slide, f'发现 {i + 1}', finding, x + i * 380, 166, 360, 210)
        priority = ranking[0] if ranking else {}
        self.card(slide, '优先方向 1', f'{_clip(priority.get("topic"), 60)}\n理由：{_clip(priority.get("reason"), 70)}',
                  x, 404, 548, 180, True)
        second = ranking[1] if len(ranking) > 1 else {}
        self.card(slide, '优先方向 2', f'{_clip(second.get("topic"), 60)}\n风险：{_clip(second.get("risk"), 64)}',
                  x + 572, 404, 548, 180)
        self.text(slide, '下一步：按讨论问题拆解验证任务，优先核对数据可得性与机制证据（分析）。',
                  82, 600, 1080, 30, FS_BODY, PRIM, True)
        self.summary_pages = [len(self.records), len(self.records) + 1]
        self.manifest.append({'page': len(self.records), 'kind': 'diagram', 'name': '总结与优先方向',
                              'degraded': False, 'reason': ''})

    def discussion_page(self):
        questions = self.components.get('discussion_questions') or []
        slide = self.page('组会需要围绕数据条件与机制突破作出决策', '08 总结与讨论 · 团队讨论', 'numlist')
        for i, question in enumerate(questions[:6], 1):
            y = 176 + (i - 1) * 82
            self.shape(slide, 82, y, 44, 44, PRIM, PRIM)
            self.text(slide, str(i), 82, y + 4, 44, 36, FS_BODY, WHITE, True, PP_ALIGN.CENTER)
            self.text(slide, _clip(question, 54), 148, y + 2, 1040, 60, FS_BODY, INK)
            self.shape(slide, 82, y + 66, 1088, 1, LINE, LINE, False)
        self.manifest.append({'page': len(self.records), 'kind': 'diagram', 'name': '团队讨论问题',
                              'degraded': False, 'reason': ''})

    def reference_pages(self):
        entries = [r.get('text') if isinstance(r, dict) else str(r) for r in self.references]
        entries = [e for e in entries if e]
        if not entries:
            entries = ['参考文献未生成。']
        for page_index in range(0, len(entries), 6):
            chunk = entries[page_index: page_index + 6]
            slide = self.page(f'参考文献（{page_index // 6 + 1}/{math.ceil(len(entries) / 6)}）：编号与正文引用一致',
                              '参考文献', 'references')
            half = math.ceil(len(chunk) / 2)
            for column, items in enumerate((chunk[:half], chunk[half:])):
                x = 72 + column * 580
                for i, entry in enumerate(items):
                    self.text(slide, _clip(entry, 64), x, 166 + i * 92, 540, 84, FS_META, BODY, line=1.25)

    def write(self):
        total, plan = self.plan()
        self.total = total
        # 先算目录页码范围
        start = 3
        bg = f'P{start}'
        retrieval = f'P{start + 1}–{start + 3}'
        progress_start = start + 4
        progress_end = progress_start + plan['progress'] - 1
        methods_start = progress_end + 1
        methods_end = methods_start + plan['methods'] - 1
        reading_start = methods_end + 1
        reading_end = reading_start + plan['reading'] - 1
        gaps_start = reading_end + 1
        summary_start = gaps_start + 2
        refs_start = summary_start + 2
        ranges = {
            'bg': bg, 'retrieval': retrieval,
            'progress': f'P{progress_start}–{progress_end}',
            'methods': f'P{methods_start}–{methods_end}',
            'reading': f'P{reading_start}–{reading_end}',
            'gaps': f'P{gaps_start}–{gaps_start + 1}',
            'summary': f'P{summary_start}–{summary_start + 1}',
            'refs': f'P{refs_start}–P{refs_start + plan["refs"] - 1}',
        }
        self.cover()
        self.toc(ranges)
        self.background()
        self.retrieval()
        self.year_page()
        self.topic_page()
        self.progress_pages()
        self.method_pages()
        self.reading_pages()
        self.gaps_page()
        self.trend_page()
        self.summary_page()
        self.discussion_page()
        self.reference_pages()
        self.prs.save(str(self.out_path))
        return {'records': self.records, 'visuals': self.manifest, 'summary_pages': self.summary_pages}


def build(task, references, figure_bundle, out_path):
    return DDeck(task, references, figure_bundle, out_path).write()