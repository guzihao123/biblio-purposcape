# -*- coding: utf-8 -*-
"""静态 SVG 图表生成（build_dashboard.py 的移动端/无脚本兜底）。
纯 Python 标准库、零依赖；把六类图预渲染成内联 SVG，嵌入 HTML 的 staticFallback 区块，
使不执行 JavaScript、无法加载 CDN 的查看环境（如手机文件预览）也能看到真实图形。
"""
import math
import re
from html import escape

FONT = "'PingFang SC','Hiragino Sans GB','Microsoft YaHei',sans-serif"
BLUE = '#63b3ff'
GREEN = '#61d6a6'
RED = '#ff7b7b'
ORANGE = '#f0a35e'
GRAY = '#9fb0cc'
LINE = 'rgba(120,170,255,0.16)'


def esc(s):
    return escape(str(s if s is not None else ''))


def svg(w, h, body):
    return ('<svg viewBox="0 0 %d %d" xmlns="http://www.w3.org/2000/svg" role="img" '
            'style="width:100%%;height:auto;background:#0b1020;border:1px solid rgba(120,170,255,.18);border-radius:12px;'
            'margin:8px 0;font-family:%s">%s</svg>' % (w, h, FONT, body))


def t(x, y, s, size=12, fill='#dbe7ff', anchor='start', weight='normal'):
    return ('<text x="%.1f" y="%.1f" font-size="%s" fill="%s" text-anchor="%s" '
            'font-weight="%s">%s</text>' % (x, y, size, fill, anchor, weight, esc(s)))


def h3(title, note=''):
    return ('<h4 style="margin:16px 0 4px">%s%s</h4>'
            % (esc(title), ('　<span class="meta">%s</span>' % esc(note)) if note else ''))


def nice_ticks(vmax, n=4):
    if vmax <= 0:
        return [0, 1]
    step = max(1, int(math.ceil(vmax / float(n))))
    mag = 10 ** int(math.floor(math.log10(step)))
    for m in (1, 2, 5, 10):
        if step <= m * mag:
            step = m * mag
            break
    ticks, v = [], 0
    while v <= vmax or len(ticks) < 2:
        ticks.append(v)
        v += step
        if len(ticks) > 12:
            break
    return ticks


def line_chart(series, years, w=960, h=280):
    if not series or not years:
        return ''
    pad_l, pad_r, pad_t, pad_b = 56, 16, 30, 34
    vmax = max([c for s in series for c in s['map'].values()] or [0])
    ticks = nice_ticks(vmax)
    top = max(ticks[-1], 1)
    x0, x1 = years[0], years[-1]

    def X(y):
        return pad_l + (w - pad_l - pad_r) * ((y - x0) / float(max(1, x1 - x0)))

    def Y(v):
        return h - pad_b - (h - pad_t - pad_b) * (v / float(top))

    body = []
    for tv in ticks:
        body.append('<line x1="%d" y1="%.1f" x2="%d" y2="%.1f" stroke="%s" stroke-width="1"/>'
                    % (pad_l, Y(tv), w - pad_r, Y(tv), LINE))
        body.append(t(pad_l - 6, Y(tv) + 4, str(tv), 11, GRAY, 'end'))
    if len(years) > 1:
        step = max(1, len(years) // 8)
        for i, y in enumerate(years):
            if i % step == 0 or i == len(years) - 1:
                body.append(t(X(y), h - pad_b + 16, str(y), 11, GRAY, 'middle'))
    for si, s in enumerate(series):
        pts = ' '.join('%.1f,%.1f' % (X(y), Y(s['map'].get(y, 0))) for y in years)
        body.append('<polyline points="%s" fill="none" stroke="%s" stroke-width="2"/>' % (pts, s['color']))
        body.append('<rect x="%d" y="8" width="10" height="10" fill="%s"/>' % (pad_l + si * 200, s['color']))
        body.append(t(pad_l + si * 200 + 14, 17, s['name'], 12))
    return svg(w, h, ''.join(body))


def bar_chart(items, w=960, bar_h=24, gap=8):
    n = len(items)
    if not n:
        return ''
    h = 16 + n * (bar_h + gap)
    vmax = max([v for _, v in items] or [1])
    bar_max = w - 380
    body = []
    for i, (label, val) in enumerate(items):
        y = 12 + i * (bar_h + gap)
        cut = label if len(label) <= 26 else label[:25] + '…'
        body.append(t(8, y + bar_h - 8, cut, 12))
        bw = 1 if vmax == 0 else max(1, bar_max * val / float(vmax))
        body.append('<rect x="348" y="%d" width="%.1f" height="%d" fill="%s" fill-opacity="0.85"/>'
                    % (y, bw, bar_h, BLUE))
        body.append(t(352 + bw, y + bar_h - 8, str(val), 12))
    return svg(w, max(60, h), ''.join(body))


def network_svg(nodes, edges, w=960, h=520, panel_prefix=None):
    n = len(nodes)
    if not n:
        return ''
    idx = {nd['id']: i for i, nd in enumerate(nodes)}
    scale = 0.75 if n > 24 else 1.0
    rad = [(10 + 8 * math.log(1 + (nd.get('cited') or 0))) * scale for nd in nodes]
    pos = []
    for i in range(n):
        a = 2 * math.pi * i / n
        pos.append([w / 2 + (w / 3) * math.cos(a), h / 2 + (h / 3) * math.sin(a)])
    for it in range(120):
        disp = [[0.0, 0.0] for _ in range(n)]
        for i in range(n):
            for j in range(i + 1, n):
                dx = pos[i][0] - pos[j][0]
                dy = pos[i][1] - pos[j][1]
                d2 = dx * dx + dy * dy + 0.01
                d = math.sqrt(d2)
                f = min(80.0, 5200.0 / d2)
                ux, uy = dx / d, dy / d
                disp[i][0] += ux * f
                disp[i][1] += uy * f
                disp[j][0] -= ux * f
                disp[j][1] -= uy * f
        for e in edges:
            a, b = idx.get(e.get('s')), idx.get(e.get('t'))
            if a is None or b is None or a == b:
                continue
            dx = pos[b][0] - pos[a][0]
            dy = pos[b][1] - pos[a][1]
            d = math.sqrt(dx * dx + dy * dy) + 0.01
            f = 0.03 * (d - 165)
            ux, uy = dx / d, dy / d
            disp[a][0] += ux * f
            disp[a][1] += uy * f
            disp[b][0] -= ux * f
            disp[b][1] -= uy * f
        for i in range(n):
            disp[i][0] += (w / 2 - pos[i][0]) * 0.015
            disp[i][1] += (h / 2 - pos[i][1]) * 0.015
        cool = max(0.03, 0.9 - it * 0.007)
        for i in range(n):
            dx, dy = disp[i]
            dl = math.sqrt(dx * dx + dy * dy) + 0.01
            pos[i][0] = min(w - 90, max(90, pos[i][0] + dx / dl * min(dl, 18) * cool))
            pos[i][1] = min(h - 60, max(60, pos[i][1] + dy / dl * min(dl, 18) * cool))
    body = []
    for e in edges:
        a, b = idx.get(e.get('s')), idx.get(e.get('t'))
        if a is None or b is None:
            continue
        body.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="rgba(160,190,235,.28)" stroke-width="1"/>'
                    % (pos[a][0], pos[a][1], pos[b][0], pos[b][1]))
    order = sorted(range(n), key=lambda i: -(nodes[i].get('cited') or 0))
    labeled = set(order[:12])
    for i, nd in enumerate(nodes):
        x, y = pos[i]
        panel_attr = (' data-panel="%s%s" style="cursor:pointer"' % (panel_prefix, nd.get('id'))) if panel_prefix else ''
        body.append('<g%s>' % panel_attr)
        body.append('<circle cx="%.1f" cy="%.1f" r="%.1f" fill="%s" fill-opacity="0.9" stroke="#0b1020"/>'
                    % (x, y, rad[i], BLUE))
        if i in labeled:
            body.append(t(x, y - rad[i] - 5, nd.get('label', ''), 11, '#dbe7ff', 'middle'))
        body.append('</g>')
    return svg(w, h, ''.join(body))


def factor_graph(nodes, edges, w=960, panel_prefix=None):
    """桑基式静态图（与满血版同构）：自动分层（因素列→中间列→结局列），色带=关系、带宽∝篇数；
    连线上不显示文字（点击看面板）；右侧留白按结局标签实际长度自适应。"""
    if not nodes:
        return ''
    by_id = {n['id']: n for n in nodes if n.get('id') is not None}
    ids = [n['id'] for n in nodes if n.get('id') is not None]
    if not ids:
        return ''
    es = [(ei, e) for ei, e in enumerate(edges) if e.get('s') in by_id and e.get('t') in by_id]
    depth = {i: 0 for i in ids}
    for _ in range(len(ids) + 1):
        changed = False
        for _, e in es:
            d = depth.get(e['s'], 0) + 1
            if d <= len(ids) and depth.get(e['t'], 0) < d:
                depth[e['t']] = d
                changed = True
        if not changed:
            break
    maxd = max(depth.values()) if depth else 0
    val = {i: 0 for i in ids}
    for _, e in es:
        v = max(1, e.get('support') or 1)
        val[e['s']] += v
        val[e['t']] += v
    out_names = [str(n.get('name') or '') for n in nodes if n.get('type') == 'outcome'] or \
                [str(n.get('name') or '') for n in nodes]
    right = 24 + max(6, max(len(s) for s in out_names)) * 12
    left, bar_w, gap, unit = 14, 12, 16, 7.0

    def bar_h(i):
        return min(150.0, max(12.0, (val.get(i) or 1) * unit))

    counts = [sum(1 for i in ids if depth[i] == d) for d in range(maxd + 1)]
    col_totals = [sum(bar_h(i) for i in ids if depth[i] == d) + gap * max(0, counts[d] - 1)
                  for d in range(maxd + 1)]
    h = max(300.0, (max(col_totals) if col_totals else 0) + 70)
    col_w = (w - left - right - 16) / max(1, maxd)
    pos = {}
    for d in range(maxd + 1):
        col = [i for i in ids if depth[i] == d]
        total = sum(bar_h(i) for i in col) + gap * max(0, len(col) - 1)
        y = max(34.0, (h - total) / 2.0)
        x = left + col_w * d
        for i in col:
            pos[i] = (x, y, bar_h(i))
            y += bar_h(i) + gap
    out_slot = {i: pos[i][1] for i in pos}
    in_slot = {i: pos[i][1] for i in pos}

    def slot_unit(i):
        v = val.get(i) or 1
        return pos[i][2] / v if v else 0.0

    bands, nodes_svg = [], []
    for ei, e in es:
        src, tgt = e['s'], e['t']
        v = max(1, e.get('support') or 1)
        x1, y1, h1 = pos[src]
        x2, y2, h2 = pos[tgt]
        y1s = out_slot[src]; out_slot[src] = y1s + v * slot_unit(src)
        y2s = in_slot[tgt]; in_slot[tgt] = y2s + v * slot_unit(tgt)
        y1e = max(y1s + 1.5, min(out_slot[src], y1 + h1))
        y2e = max(y2s + 1.5, min(in_slot[tgt], y2 + h2))
        x1b, x2b = x1 + bar_w, x2
        mx = (x1b + x2b) / 2.0
        color = GREEN if e.get('polarity') != 'neg' else RED
        extra = (' data-panel="%se%d" style="cursor:pointer"' % (panel_prefix, ei)) if panel_prefix else ''
        d = ('M%.1f,%.1f C%.1f,%.1f %.1f,%.1f %.1f,%.1f L%.1f,%.1f C%.1f,%.1f %.1f,%.1f %.1f,%.1f Z'
             % (x1b, y1s, mx, y1s, mx, y2s, x2b, y2s,
                x2b, y2e, mx, y2e, mx, y1e, x1b, y1e))
        bands.append('<path d="%s" fill="%s" fill-opacity="0.36" stroke="none"%s/>' % (d, color, extra))
    for n in nodes:
        i = n.get('id')
        if i not in pos:
            continue
        x, y, bh = pos[i]
        color = ORANGE if n.get('type') == 'outcome' else BLUE
        panel_attr = (' data-panel="%sn%s" style="cursor:pointer"' % (panel_prefix, i)) if panel_prefix else ''
        nodes_svg.append('<g%s><rect x="%.1f" y="%.1f" width="%d" height="%.1f" rx="2" fill="%s"/>%s</g>'
                         % (panel_attr, x, y, bar_w, bh, color,
                            t(x + bar_w + 8, y + bh / 2 + 4, n.get('name', ''), 12, '#dbe7ff', 'start')))
    body = ''.join(bands) + ''.join(nodes_svg)
    body += t(left + 2, 16, '因素', 12, GRAY)
    body += t(w - right + 2, 16, '结局', 12, GRAY)
    return svg(w, h, body)


def method_tree(root, w=960, panel_prefix=None):
    ypos = {}
    order = []

    def assign(n):
        kids = n.get('children') or []
        if not kids:
            y = 34 + len(order) * 30
            order.append(n)
            ypos[id(n)] = y
            return y
        ys = [assign(c) for c in kids]
        y = sum(ys) / len(ys)
        ypos[id(n)] = y
        return y

    assign(root)
    h = 34 + max(1, len(order)) * 30 + 12
    maxd = [0]

    def depth_of(n, d):
        maxd[0] = max(maxd[0], d)
        for c in n.get('children') or []:
            depth_of(c, d + 1)
    depth_of(root, 0)
    colw = (w - 60) / max(1, maxd[0] + 1)

    def label_of(n):
        cnt = n.get('count')
        return n.get('name', '') + (('（%s篇）' % cnt) if cnt is not None else '')

    body = []
    counter = [0]

    def draw(n, depth):
        x = 24 + depth * colw
        y = ypos[id(n)]
        for c in n.get('children') or []:
            cx = 24 + (depth + 1) * colw
            cy = ypos[id(c)]
            body.append('<path d="M%.1f,%.1f C%.1f,%.1f %.1f,%.1f %.1f,%.1f" fill="none" '
                        'stroke="rgba(160,190,235,.28)" stroke-width="1.2"/>'
                        % (x + 8, y, x + colw * 0.45, y, cx - colw * 0.45, cy, cx - 10, cy))
        panel_attr = ''
        if panel_prefix:
            panel_attr = ' data-panel="%s%d" style="cursor:pointer"' % (panel_prefix, counter[0])
        body.append('<g%s>' % panel_attr)
        body.append('<circle cx="%.1f" cy="%.1f" r="5" fill="#9fb0cc"/>' % (x, y))
        body.append(t(x + 10, y + 4, label_of(n), 12))
        body.append('</g>')
        counter[0] += 1
        for c in n.get('children') or []:
            draw(c, depth + 1)
    draw(root, 0)
    return svg(w, h, ''.join(body))


def _yr(v):
    try:
        return int(v)
    except Exception:
        return v


def empty_chart(message, w=960, h=120):
    """空数据仍保留图区，只显示状态，不绘制任何结点或边。"""
    return svg(w, h, t(w / 2, h / 2 + 4, message or '暂无数据', 14, GRAY, 'middle'))


def _charts(data):
    """收集七类图（含显式空态），供 HTML 兜底与长图导出复用。"""
    items = []
    tr = data.get('trend_all') or []
    if tr:
        years = [_yr(x['year']) for x in tr]
        chart = line_chart([{'name': '发表年度趋势', 'color': BLUE,
                             'map': {_yr(x['year']): x['count'] for x in tr}}], years)
    else:
        chart = empty_chart(data.get('trend_message') or '暂无全量年度聚合统计')
    items.append(('总体趋势', '不限年限 · 全量命中聚合', chart))
    cs = data.get('compare') or []
    if cs:
        colors = ['#63b3ff', '#f0a35e', '#61d6a6', '#b58cff']
        years = sorted({_yr(x['year']) for c in cs for x in (c.get('series') or [])})
        series = [{'name': c.get('name_zh') or c.get('name', ''), 'color': colors[i % 4],
                   'map': {_yr(x['year']): x['count'] for x in (c.get('series') or [])}}
                  for i, c in enumerate(cs)]
        chart = line_chart(series, years)
    else:
        chart = empty_chart(data.get('compare_message') or '暂无主题年度序列聚合统计')
    items.append(('比较分析', '不限年限 · 前 4 主题年度趋势', chart))
    for k, sc in (data.get('scopes') or {}).items():
        label = sc.get('label', '')
        tp = (sc.get('topics') or [])[:12]
        if tp:
            pairs = [((x.get('name_zh') or x.get('name', '')), x.get('count', 0)) for x in tp]
            items.append(('主题分布（饼图）· %s' % label, '前 12 主题（占比）', pie_chart(pairs)))
            items.append(('主题分布（柱图）· %s' % label, '前 12 主题（命中篇数）', bar_chart(pairs)))
        else:
            items.append(('主题分布 · %s' % label, '全量命中聚合',
                          empty_chart(sc.get('topics_message') or '该范围暂无主题分布数据')))
        net = sc.get('network') or {}
        if net.get('nodes'):
            chart = network_svg(net.get('nodes') or [], net.get('edges') or [])
            note = '球越大=被引越多；大球带作者-年份标注'
            if not net.get('edges'):
                note += '；池内暂无真实互引（不补边）'
        else:
            chart = empty_chart(net.get('message') or '该范围暂无论文数据')
            note = '空数据不绘制结点或引用边'
        items.append(('引用网络 · %s' % label, note, chart))
        kg = sc.get('knowledge') or {}
        kn = kg.get('nodes') or []
        ke = kg.get('edges') or []
        if kn and any(e.get('polarity') for e in ke):
            chart = factor_graph(kn, ke)
            note = '左=因素、右=结局；绿=正向、红=负向，带宽=篇数'
        elif kn:
            chart = claim_graph(kn, ke)
            note = '旧版结论对；仅绘制有投票的关系'
        else:
            chart = empty_chart(kg.get('message') or '暂无可核验的因素→结局关系')
            note = '证据不足，不硬造因素或语义边'
        items.append(('因素 → 结局 影响关系 · %s' % label, note, chart))
        mm = sc.get('methods')
        if mm and (mm.get('children') or []):
            chart = method_tree(mm)
        else:
            chart = empty_chart((mm or {}).get('message') or '暂无可核验的研究方法归类')
        items.append(('研究方法 · %s' % label, '先定义后分类；名称后=使用该方法的篇数', chart))
        rel = sc.get('relations') or {}
        if rel.get('edges') and net.get('nodes'):
            chart = relation_network_svg(net.get('nodes') or [], rel)
            note = '圆圈=检索池论文；连线=支持/改进/冲突/差异'
        else:
            chart = empty_chart(rel.get('message') or '暂无可核验的论文关系')
            note = '空数据不绘制语义边'
        items.append(('语义关系图谱 · %s' % label, note, chart))
    return items


def build_static_charts(data):
    """把仪表盘数据预渲染为内联 SVG 图表 HTML（供无脚本/无 CDN 环境显示）。"""
    return ''.join(h3(title, note) + chart for title, note, chart in _charts(data))


def build_combined_svg(data, width=1000):
    """把全部图表纵向拼成一张独立 SVG 长图（可直接作为图片文件打开，无需脚本/联网）。"""
    items = _charts(data)
    if not items:
        return None
    parts = []
    y = 12.0
    for title, note, svg_html in items:
        m = re.match(r'<svg viewBox="0 0 (\d+(?:\.\d+)?) (\d+(?:\.\d+)?)"', svg_html)
        if not m:
            continue
        w0, h0 = float(m.group(1)), float(m.group(2))
        body_start = svg_html.index('>', m.end() - 1) + 1
        body = svg_html[body_start:svg_html.rindex('</svg>')]
        scale = width / w0
        h1 = h0 * scale
        parts.append(t(20, y + 20, title, 16, '#eaf1ff', weight='bold'))
        if note:
            parts.append(t(20, y + 38, note, 11, GRAY))
        parts.append('<g transform="translate(0,%.1f) scale(%.5f)">%s</g>' % (y + 50, scale, body))
        y += 50 + h1 + 20
    total_h = y + 6
    head = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %d %.0f" width="%d" height="%.0f" '
            'font-family="%s"><rect x="0" y="0" width="%d" height="%.0f" fill="#0b1020"/>'
            % (width, total_h, width, total_h, FONT, width, total_h))
    return head + ''.join(parts) + '</svg>'

def _paper_ul(items):
    if not items:
        return '<div class="meta">无</div>'
    lis = []
    for p in items:
        if isinstance(p, dict):
            ref = p.get('ref')
            s = ('[%s] ' % ref if ref is not None else '') + esc(p.get('label', ''))
            t = p.get('title') or ''
            u = p.get('url') or ''
            if t:
                s += '：' + esc(t)
            if u:
                s += ' <a href="' + esc(u) + '" target="_blank">原文</a>'
            lis.append('<li>' + s + '</li>')
        else:
            lis.append('<li>' + esc(str(p)) + '</li>')
    return '<ul>' + ''.join(lis) + '</ul>'


def _evidence_html(items):
    if not items:
        return '<div class="meta">无可用摘要证据</div>'
    out = []
    for item in items:
        ref = item.get('ref_no', item.get('ref')) if isinstance(item, dict) else None
        quote = item.get('quote', '') if isinstance(item, dict) else str(item)
        out.append('<blockquote style="margin:6px 0;padding:7px 10px;border-left:2px solid #63b3ff;background:rgba(99,179,255,.06)">'
                   '<b>[ref ' + esc(ref if ref is not None else '-') + ']</b> ' + esc(quote) + '</blockquote>')
    return ''.join(out)


def _short_paper(p):
    if isinstance(p, str):
        return p
    lab = p.get('label') or ''
    nm = lab.split(',')[0].strip()
    m = re.search(r'\d{4}', lab)
    ref = p.get('ref')
    return '[%s] %s%s' % (ref if ref is not None else '-', nm, (' ' + m.group(0)) if m else '')


SITE_CSS = """
:root{
  --site-bg:#070b16; --site-fg:#eaf1ff; --site-accent:#63b3ff; --site-on-accent:#ffffff;
  --site-surface:rgba(18,26,45,.86); --site-muted:#9fb0cc; --site-border:rgba(120,170,255,.22);
  --site-font:'PingFang SC','Hiragino Sans GB','Microsoft YaHei',sans-serif;
  --site-radius:16px; --site-space:1; --site-type:1;
}
*{box-sizing:border-box}
html,body{margin:0;background:
  radial-gradient(900px 520px at 12% 0%, rgba(64,120,255,.18), transparent 60%),
  radial-gradient(800px 500px at 88% 8%, rgba(60,240,190,.10), transparent 60%),
  var(--site-bg);color:var(--site-fg);font-family:var(--site-font)}
header{background:linear-gradient(180deg,rgba(18,26,45,.94),rgba(10,16,30,.86));border-bottom:1px solid var(--site-border);padding:calc(22px * var(--site-space,1)) calc(28px * var(--site-space,1))}
header h1{margin:0 0 6px;font-size:calc(22px * var(--site-type,1));letter-spacing:.01em}
header .src{color:var(--site-muted);font-size:12px;line-height:1.7}
main{max-width:1180px;margin:0 auto;padding:calc(20px * var(--site-space,1)) calc(24px * var(--site-space,1))}
section{background:linear-gradient(180deg,rgba(22,32,56,.92),rgba(12,18,34,.92));border:1px solid var(--site-border);border-radius:var(--site-radius);margin:0 0 calc(18px * var(--site-space,1));overflow:hidden;box-shadow:0 18px 50px rgba(0,0,0,.24), inset 0 1px 0 rgba(255,255,255,.04)}
section h2{margin:0;padding:calc(12px * var(--site-space,1)) calc(18px * var(--site-space,1));font-size:calc(16px * var(--site-type,1));background:linear-gradient(90deg,rgba(30,136,231,.92),rgba(64,200,255,.62));color:var(--site-on-accent)}
section h2 small{font-weight:normal;font-size:12px;opacity:.9;margin-left:8px}
.chartwrap{padding:calc(10px * var(--site-space,1)) calc(16px * var(--site-space,1))}
.chart-hint{color:var(--site-muted);font-size:12px;padding:0 calc(16px * var(--site-space,1)) 8px}
.ipanel{display:none;border-top:1px solid var(--site-border);background:rgba(10,16,30,.92);padding:12px 16px;font-size:13px;line-height:1.8}
.ipanel.on{display:block}
.ipanel ul{margin:4px 0;padding-left:20px}
.ipanel .meta{color:var(--site-muted);font-size:12px}
.ipanel a{color:var(--site-accent)}
img.longshot{width:100%;height:auto;border:1px solid var(--site-border);border-radius:var(--site-radius);background:#0b1020}
.livechart{width:100%;height:clamp(260px,26vw,380px);display:none}
.tv{display:none}
.tv.on{display:block}
.tvtool{padding:calc(8px * var(--site-space,1)) calc(16px * var(--site-space,1)) 0;display:flex;gap:8px;flex-wrap:wrap}
.tvtool button{cursor:pointer;border:1px solid var(--site-border);background:rgba(255,255,255,.04);color:var(--site-fg);border-radius:999px;padding:5px 14px;font-size:12px}
.tvtool button.on{background:var(--site-accent);border-color:var(--site-accent);color:var(--site-on-accent)}
footer{color:var(--site-muted);font-size:12px;text-align:center;padding:calc(10px * var(--site-space,1)) 0 calc(24px * var(--site-space,1))}
@media (max-width:900px){main{padding:14px}.livechart{height:280px}}
@media (max-width:520px){main{padding:10px}.livechart{height:240px}section h2{padding:10px 14px}.chartwrap{padding:8px 10px}}
"""

SITE_JS = """<script>
document.addEventListener('click', function(ev){
  var el = ev.target, t = null;
  while(el && el !== document){
    if(el.getAttribute && el.getAttribute('data-panel')){ t = el; break; }
    el = el.parentNode;
  }
  if(!t) return;
  var id = t.getAttribute('data-panel');
  var box = document.getElementById(id);
  if(!box) return;
  var on = document.querySelectorAll('.ipanel.on');
  for(var i = 0; i < on.length; i++){ if(on[i] !== box){ on[i].className = on[i].className.replace(/\\bon\\b/g, '').replace(/\\s+/g, ' '); } }
  if(box.className.indexOf('on') < 0){ box.className += ' on'; }
  if(box.scrollIntoView){ try{ box.scrollIntoView({block: 'nearest'}); }catch(e){ box.scrollIntoView(); } }
});
document.addEventListener('click', function(ev){
  var el = ev.target, t = null;
  while(el && el !== document){ if(el.getAttribute && el.getAttribute('data-tv')){ t = el; break; } el = el.parentNode; }
  if(!t) return;
  var sec = document.getElementById(t.getAttribute('data-tv'));
  if(!sec) return;
  var view = t.getAttribute('data-view');
  var views = sec.querySelectorAll('.tv');
  for(var i = 0; i < views.length; i++){ views[i].className = views[i].className.replace(/\\bon\\b/g, '').replace(/\\s+/g, ' '); }
  var target = sec.querySelector('.tv-' + view);
  if(target && target.className.indexOf('on') < 0){ target.className += ' on'; }
  var btns = sec.querySelectorAll('[data-tv]');
  for(var j = 0; j < btns.length; j++){
    if(btns[j].getAttribute('data-view') === view){ if(btns[j].className.indexOf('on') < 0) btns[j].className += ' on'; }
    else { btns[j].className = btns[j].className.replace(/\\bon\\b/g, '').replace(/\\s+/g, ' '); }
  }
});
</script>"""


def relation_network_svg(nodes, relations, w=960, h=620, panel_prefix=None):
    """语义关系图谱（静态版）：节点=池内论文；边=支持/改进/冲突/差异。"""
    types = relations.get('types') or {}
    edges = relations.get('edges') or []
    if not nodes or not edges:
        return ''
    idx = {n.get('id'): i for i, n in enumerate(nodes)}
    edges = [e for e in edges if e.get('s') in idx and e.get('t') in idx]
    if not edges:
        return ''
    deg = {}
    for e in edges:
        deg[e['s']] = deg.get(e['s'], 0) + 1
        deg[e['t']] = deg.get(e['t'], 0) + 1
    cx, cy = w / 2.0, h / 2.0 + 18
    rx, ry = w * 0.36, h * 0.34
    pos = {}
    for i, n in enumerate(nodes):
        ang = 2 * math.pi * i / len(nodes) - math.pi / 2
        pos[n['id']] = (cx + rx * math.cos(ang), cy + ry * math.sin(ang))
    body = []
    order = ['support', 'improve', 'conflict', 'difference']
    lx, ly = 24, 22
    for tp in order:
        if tp not in types:
            continue
        color = types[tp].get('color') or GRAY
        name = types[tp].get('name') or tp
        cnt = sum(1 for e in edges if e.get('type') == tp)
        body.append('<line x1="%d" y1="%d" x2="%d" y2="%d" stroke="%s" stroke-width="3"/>'
                    % (lx, ly, lx + 22, ly, color))
        body.append(t(lx + 28, ly + 4, '%s %d' % (name, cnt), 11, '#dbe7ff'))
        lx += 126
    for ei, e in enumerate(edges):
        x1, y1 = pos[e['s']]
        x2, y2 = pos[e['t']]
        color = (types.get(e.get('type')) or {}).get('color') or GRAY
        mx, my = (x1 + x2) / 2.0, (y1 + y2) / 2.0
        dx, dy = x2 - x1, y2 - y1
        qx, qy = mx - dy * 0.08, my + dx * 0.08
        width = 1.8 if e.get('confidence') == 'high' else 1.2
        extra = (' data-panel="%se%d" style="cursor:pointer"' % (panel_prefix, ei)) if panel_prefix else ''
        body.append('<path d="M%.1f,%.1f Q%.1f,%.1f %.1f,%.1f" fill="none" stroke="%s" '
                    'stroke-width="%.1f" opacity="0.62"%s/>' % (x1, y1, qx, qy, x2, y2, color, width, extra))
    top_ids = {n['id'] for n in sorted(nodes, key=lambda x: (-deg.get(x['id'], 0), -(x.get('cited') or 0)))[:12]}
    for n in nodes:
        x, y = pos[n['id']]
        d = deg.get(n['id'], 0)
        r = 4.5 + min(3.5, d * 0.7)
        extra = (' data-panel="%sn%s" style="cursor:pointer"' % (panel_prefix, n.get('id'))) if panel_prefix else ''
        body.append('<g%s><title>%s</title>' % (extra, esc((n.get('label') or '') + ' · ' + (n.get('title') or '') + ' · 关系 %d 条' % d)))
        body.append('<circle cx="%.1f" cy="%.1f" r="%.1f" fill="%s" fill-opacity="0.92" stroke="#0b1020"/>'
                    % (x, y, r, '#63b3ff' if d else '#9fb0cc'))
        body.append('</g>')
        if n['id'] in top_ids:
            label = n.get('label') or ''
            anchor = 'end' if x > w - 150 else 'start'
            tx = x - 9 if anchor == 'end' else x + 9
            body.append(t(tx, y + 3, label, 9, '#c7d6ee', anchor))
    body.append(t(24, h - 14, '圆圈=检索池论文；连线=语义关系；支持/改进/冲突/差异按颜色区分；冲突/差异为分析判断。', 10, GRAY))
    return svg(w, h, ''.join(body))


def build_static_interactive_page(data, title, long_image=None, intro='', live_charts=False):
    """生成"静态优先"整页：全部图表为首屏内联 SVG（无脚本也可见）；
    交互采用预渲染隐藏面板 + 点击切换 class 的轻量脚本（不插入新节点、不依赖图表库）。"""
    secs = []
    long_sec = ''
    if long_image:
        long_sec = ('<section><h2>仪表盘长图 <small>不依赖脚本与网络；点图可看完整长图</small></h2>'
                    '<div class="chartwrap"><a href="' + esc(long_image) + '" target="_blank">'
                    '<img class="longshot" src="' + esc(long_image) + '" alt="dashboard long image"></a></div></section>')
    tr = data.get('trend_all') or []
    if tr:
        years = [_yr(x['year']) for x in tr]
        svg = line_chart([{'name': '发表年度趋势', 'color': BLUE,
                           'map': {_yr(x['year']): x['count'] for x in tr}}], years)
        if live_charts:
            secs.append('<section id="trend-sec"><h2>总体趋势 <small>不限年限 · 全量命中聚合</small></h2>'
                        '<div id="trend-live" class="livechart"></div>'
                        '<div class="chartwrap" id="trend-static">' + svg + '</div></section>')
        else:
            secs.append('<section><h2>总体趋势 <small>不限年限 · 全量命中聚合</small></h2>'
                        '<div class="chartwrap">' + svg + '</div></section>')
    else:
        secs.append(_section('总体趋势', '不限年限 · 全量命中聚合',
                             empty_chart(data.get('trend_message') or '暂无全量年度聚合统计'), [], hint='空数据不绘制趋势'))
    cs = data.get('compare') or []
    if cs:
        colors = ['#63b3ff', '#f0a35e', '#61d6a6', '#b58cff']
        years = sorted({_yr(x['year']) for c in cs for x in (c.get('series') or [])})
        series = [{'name': c.get('name_zh') or c.get('name', ''), 'color': colors[i % 4],
                   'map': {_yr(x['year']): x['count'] for x in (c.get('series') or [])}}
                  for i, c in enumerate(cs)]
        svg = line_chart(series, years)
        if live_charts:
            secs.append('<section id="compare-sec"><h2>比较分析 <small>不限年限 · 前 4 主题年度趋势</small></h2>'
                        '<div id="compare-live" class="livechart"></div>'
                        '<div class="chartwrap" id="compare-static">' + svg + '</div></section>')
        else:
            secs.append('<section><h2>比较分析 <small>不限年限 · 前 4 主题年度趋势</small></h2>'
                        '<div class="chartwrap">' + svg + '</div></section>')
    else:
        secs.append(_section('比较分析', '不限年限 · 前 4 主题年度趋势',
                             empty_chart(data.get('compare_message') or '暂无主题年度序列聚合统计'), [], hint='空数据不绘制比较序列'))
    for scope_key, sc in (data.get('scopes') or {}).items():
        label = sc.get('label', '')
        prefix = str(scope_key) + '-'
        tp = (sc.get('topics') or [])[:12]
        if tp:
            pairs = [((x.get('name_zh') or x.get('name', '')), x.get('count', 0)) for x in tp]
            sec_id = 'topics-' + str(scope_key)
            if live_charts:
                secs.append('<section id="' + sec_id + '"><h2>主题分布 · ' + esc(label) +
                            ' <small>前 12 主题（可交互）</small></h2>'
                            '<div class="tvtool"><button data-tv="' + sec_id + '" data-view="pie" class="on">饼图</button>'
                            '<button data-tv="' + sec_id + '" data-view="bar">柱图</button>'
                            '<span style="margin-left:10px">显示数量：</span>'
                            '<button data-n="10">10</button><button data-n="20" class="on">20</button>'
                            '<button data-n="30">30</button><button data-n="40">40</button></div>'
                            '<div id="topics-live-' + str(scope_key) + '" class="livechart"></div>'
                            '<div class="chartwrap tv tv-pie on">' + pie_chart(pairs) + '</div>'
                            '<div class="chartwrap tv tv-bar">' + bar_chart(pairs) + '</div></section>')
            else:
                secs.append('<section id="' + sec_id + '"><h2>主题分布 · ' + esc(label) +
                            ' <small>前 12 主题（命中篇数）</small></h2>'
                            '<div class="tvtool"><button data-tv="' + sec_id + '" data-view="pie" class="on">饼图</button>'
                            '<button data-tv="' + sec_id + '" data-view="bar">柱图</button></div>'
                            '<div class="chartwrap tv tv-pie on">' + pie_chart(pairs) + '</div>'
                            '<div class="chartwrap tv tv-bar">' + bar_chart(pairs) + '</div></section>')
        else:
            secs.append(_section('主题分布 · ' + label, '全量命中聚合',
                                 empty_chart(sc.get('topics_message') or '该范围暂无主题分布数据'), [], hint='空数据不绘制主题分布'))
        net = sc.get('network') or {}
        nodes = net.get('nodes') or []
        edges = net.get('edges') or []
        if nodes:
            svg = network_svg(nodes, edges, panel_prefix=prefix + 'net-')
            byid = {n.get('id'): n for n in nodes}
            panels = []
            for n in nodes:
                citing = [byid[e.get('s')] for e in edges if e.get('t') == n.get('id') and e.get('s') in byid]
                cited = [byid[e.get('t')] for e in edges if e.get('s') == n.get('id') and e.get('t') in byid]
                html = ('<b>' + esc(n.get('label', '')) + '</b><div>' + esc(n.get('title', '')) + '</div>'
                        '<div class="meta">' + esc(n.get('authors') or '') + ' · ' + esc(n.get('year') or '?') +
                        ' · 被引 ' + (str(n.get('cited')) if n.get('cited') is not None else '-') + '</div>')
                if n.get('url'):
                    html += '<div><a href="' + esc(n.get('url')) + '" target="_blank">原文 / 题录链接</a></div>'
                if n.get('excerpt'):
                    html += '<div>' + esc(n.get('excerpt')) + '</div>'
                html += '<div style="margin-top:6px">引用了该结点（池内 ' + str(len(citing)) + '）：</div>' + _paper_ul(citing)
                html += '<div>被该结点引用（池内 ' + str(len(cited)) + '）：</div>' + _paper_ul(cited)
                panels.append((prefix + 'net-' + str(n.get('id')), html))
            note = '球越大=被引越多；点圆球看论文详情'
            if not edges:
                note += '；池内暂无真实互引（不补边）'
            secs.append(_section('引用网络 · ' + label, note, svg, panels))
        else:
            secs.append(_section('引用网络 · ' + label, '空数据不绘制结点或引用边',
                                 empty_chart(net.get('message') or '该范围暂无论文数据'), [], hint='该范围暂无论文数据'))
        kg = sc.get('knowledge') or {}
        kn = kg.get('nodes') or []
        ke = kg.get('edges') or []
        if kn and any(e.get('polarity') for e in ke):
            svg = factor_graph(kn, ke, panel_prefix=prefix + 'kg-')
            byid = {n.get('id'): n for n in kn}
            panels = []
            for ei, e in enumerate(ke):
                f = byid.get(e.get('s'), {})
                t = byid.get(e.get('t'), {})
                html = ('<b>' + esc(f.get('name', '')) + ' → ' + esc(t.get('name', '')) + '</b><div>' +
                        ('负向影响（因素越强，结局越轻）' if e.get('polarity') == 'neg' else '正向影响（因素越强，结局越重）') +
                        (' · 效应量 ' + esc(e['effect']) if e.get('effect') else '') +
                        ' · 支撑 ' + str(e.get('support') or 0) + ' 篇' + ('（存在争议）' if e.get('disputed') else '') + '</div>')
                html += '<div style="margin-top:6px">支撑论文：</div>' + _paper_ul(e.get('papers') or [])
                html += '<div style="margin-top:6px">摘要原句：</div>' + _evidence_html(e.get('evidence') or [])
                panels.append((prefix + 'kg-e%d' % ei, html))
            for n in kn:
                rels = [e for e in ke if e.get('s') == n.get('id') or e.get('t') == n.get('id')]
                html = ('<b>' + ('结局' if n.get('type') == 'outcome' else '因素') + '：' + esc(n.get('name', '')) + '</b>')
                html += '<div style="margin-top:6px">关联论文：</div>' + _paper_ul(n.get('papers') or [])
                if rels:
                    html += '<div>涉及关系：' + '；'.join(
                        esc((byid.get(x.get('s'), {})).get('name', '')) + ' → ' + esc((byid.get(x.get('t'), {})).get('name', '')) +
                        ('（负向）' if x.get('polarity') == 'neg' else '（正向）') + ' ' + str(x.get('support') or 0) + '篇'
                        for x in rels) + '</div>'
                panels.append((prefix + 'kg-n' + str(n.get('id')), html))
            secs.append(_section('因素 → 结局 影响关系 · ' + label, '左=因素、右=结局（链式自动加中间列）；绿=正向、红=负向，带宽=篇数；点击结点/色带看支撑论文',
                                 svg, panels))
        elif kn:
            svg = claim_graph(kn, ke, panel_prefix=prefix + 'cl-')
            id2claim = {n.get('id'): n for n in kn}
            panels = []
            for i, n in enumerate(kn):
                html = '<b>核心结论：' + esc(n.get('claim', '')) + '</b>'
                html += '<div style="margin-top:6px">支撑该结论的论文：</div>' + _paper_ul(n.get('papers') or [])
                panels.append((prefix + 'cl-cn%d' % i, html))
            for ei, e in enumerate(ke):
                for kind, cnt, label_cn in (('support', e.get('support') or 0, '支持'),
                                            ('oppose', e.get('oppose') or 0, '不支持')):
                    if not cnt:
                        continue
                    a = id2claim.get(e.get('s'), {}).get('claim', '')
                    b = id2claim.get(e.get('t'), {}).get('claim', '')
                    papers = e.get('support_papers') if kind == 'support' else e.get('oppose_papers')
                    html = ('<b>' + label_cn + '关系 ×' + str(cnt) + '</b><div>' + esc(a) + ' → ' + esc(b) + '</div>'
                            '<div style="margin-top:6px">投票论文：</div>' + _paper_ul(papers or []))
                    panels.append((prefix + 'cl-ce%d-%s' % (ei, kind), html))
            secs.append(_section('结论支持 / 不支持知识图谱 · ' + label,
                                 '绿实线=支持、红虚线=不支持；线越粗=票数越多；点球或线看论文',
                                 svg, panels))
        else:
            secs.append(_section('因素 → 结局 影响关系 · ' + label, '证据不足，不硬造因素边',
                                 empty_chart(kg.get('message') or '暂无可核验的因素→结局关系'), [], hint='暂无可核验的因素→结局关系'))
        mm = sc.get('methods')
        if mm and (mm.get('children') or []):
            svg = method_tree(mm, panel_prefix=prefix + 'mm-')
            seq = []
            def walk(n):
                seq.append(n)
                for c in n.get('children') or []:
                    walk(c)
            walk(mm)
            panels = []
            for i, n in enumerate(seq):
                kids = n.get('children') or []
                if n.get('papers'):
                    cnt = n.get('count')
                    html = ('<b>' + esc(n.get('name', '')) + ('（%s篇）' % cnt if cnt is not None else '') + '</b>'
                            '<div style="margin-top:6px">使用该方法/属于该方向的论文：</div>' + _paper_ul(n.get('papers') or []))
                elif kids:
                    lis = ''.join('<li>' + esc(c.get('name', '')) +
                                  (('（%s篇）' % c.get('count')) if c.get('count') is not None else '') + '</li>'
                                  for c in kids)
                    html = ('<b>' + esc(n.get('name', '')) + '</b>'
                            '<div style="margin-top:6px">包含的子类：</div><ul>' + lis + '</ul>')
                else:
                    html = '<b>' + esc(n.get('name', '')) + '</b><div class="meta">无明细</div>'
                panels.append((prefix + 'mm-%d' % i, html))
            secs.append(_section('研究方法 · ' + label, '方法=数据获取×分析技术；点圆球或方法名看论文/子类',
                                 svg, panels))
        else:
            secs.append(_section('研究方法 · ' + label, '先定义后分类',
                                 empty_chart((mm or {}).get('message') or '暂无可核验的研究方法归类'), [], hint='暂无可核验的研究方法归类'))
        rel = sc.get('relations') or {}
        rel_edges = rel.get('edges') or []
        rsvg = relation_network_svg(nodes, rel, panel_prefix=prefix + 'rel-') if rel_edges and nodes else ''
        if rsvg:
            byid = {n.get('id'): n for n in nodes}
            types = rel.get('types') or {}
            panels = []
            for ei, e in enumerate(rel_edges):
                source = byid.get(e.get('s'), {})
                target = byid.get(e.get('t'), {})
                relation_name = (types.get(e.get('type')) or {}).get('name') or e.get('type') or ''
                html = ('<b>' + esc(relation_name) + '关系</b><div>' + esc(source.get('label', '')) + ' → ' +
                        esc(target.get('label', '')) + '</div><div>' + esc(e.get('reason', '')) + '</div>')
                html += '<div style="margin-top:6px">双方摘要原句：</div>' + _evidence_html(e.get('evidence') or [])
                html += '<div class="meta">置信度：' + esc(e.get('confidence') or '-') + '；冲突/差异为分析判断。</div>'
                panels.append((prefix + 'rel-e%d' % ei, html))
            for n in nodes:
                related = [e for e in rel_edges if e.get('s') == n.get('id') or e.get('t') == n.get('id')]
                html = '<b>' + esc(n.get('label', '')) + '</b><div>' + esc(n.get('title', '')) + '</div>'
                html += '<div style="margin-top:6px">关系 ' + str(len(related)) + ' 条；点击连线查看双方摘要原句。</div>'
                panels.append((prefix + 'rel-n' + str(n.get('id')), html))
            secs.append(_section(
                '语义关系图谱 · ' + label,
                '圆圈=检索池论文；连线=支持/改进/冲突/差异；点击结点或连线看证据',
                rsvg, panels,
                hint='冲突/差异为分析判断；每条边均可回溯双方摘要原句'))
        else:
            secs.append(_section('语义关系图谱 · ' + label, '空数据不绘制语义边',
                                 empty_chart(rel.get('message') or '暂无可核验的论文关系'), [], hint='暂无可核验的论文关系'))
    if long_sec:
        secs.append(long_sec)
    body = ('<!DOCTYPE html>\n<html lang="zh-CN">\n<head>\n<meta charset="UTF-8">\n'
            '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
            '<meta name="color-scheme" content="dark">\n'
            '<title>' + esc(title) + '</title>\n<style>' + SITE_CSS + '</style>\n</head>\n<body>\n'
            '<header><h1>' + esc(title) + '</h1><div class="src">' + esc(intro) + '</div></header>\n'
            '<main>\n' + '\n'.join(secs) + '\n</main>\n<footer>静态图表 + 轻量交互：不依赖图表库与外部网络；点圆球/箭头/方法结点可查看论文清单。</footer>\n'
            + SITE_JS + '\n</body>\n</html>')
    return body


def _section(title, note, svg, panels, hint='点选图中的圆球 / 箭头 / 结点，查看对应论文清单'):
    panel_html = '\n'.join('<div class="ipanel" id="' + pid + '">' + html + '</div>' for pid, html in panels)
    return ('<section><h2>' + esc(title) + ' <small>' + esc(note) + '</small></h2>'
            '<div class="chartwrap">' + svg + '</div>'
            '<div class="chart-hint">' + esc(hint) + '</div>'
            + panel_html + '</section>')


def claim_graph(nodes, edges, w=960, panel_prefix=None):
    """旧版"结论对"知识图谱的静态渲染：结论=球，绿实线=支持×N、红虚线=不支持×N。"""
    n = len(nodes)
    if not n:
        return ''
    h = max(340, 130 + n * 80)
    labels = [(nd.get('claim') or '') for nd in nodes]
    pos = []
    for i in range(n):
        a = 2 * math.pi * i / n - math.pi / 2
        pos.append((w / 2 + (w * 0.30) * math.cos(a), h / 2 + ((h - 130) / 2 * 0.80) * math.sin(a)))
    ididx = {nd.get('id'): i for i, nd in enumerate(nodes)}
    body = ['<defs>'
            '<marker id="ar-g" markerWidth="10" markerHeight="8" refX="9" refY="4" orient="auto">'
            '<path d="M0,0 L10,4 L0,8 z" fill="%s"/></marker>'
            '<marker id="ar-r" markerWidth="10" markerHeight="8" refX="9" refY="4" orient="auto">'
            '<path d="M0,0 L10,4 L0,8 z" fill="%s"/></marker>'
            '</defs>' % (GREEN, RED)]
    for ei, e in enumerate(edges):
        si = ididx.get(e.get('s'))
        ti = ididx.get(e.get('t'))
        if si is None or ti is None:
            continue
        x1, y1 = pos[si]
        x2, y2 = pos[ti]
        dx, dy = x2 - x1, y2 - y1
        for kind, cnt, color, dash, curve in (('support', e.get('support') or 0, GREEN, '', 0.20),
                                              ('oppose', e.get('oppose') or 0, RED, ' stroke-dasharray="6 4"', -0.20)):
            if not cnt:
                continue
            cxm = (x1 + x2) / 2 - dy * curve
            cym = (y1 + y2) / 2 + dx * curve
            extra = (' data-panel="%sce%d-%s" style="cursor:pointer"' % (panel_prefix, ei, kind)) if panel_prefix else ''
            body.append('<path d="M%.1f,%.1f Q%.1f,%.1f %.1f,%.1f" fill="none" stroke="%s" '
                        'stroke-width="%.1f"%s%s marker-end="url(#%s)"/>'
                        % (x1, y1, cxm, cym, x2, y2, color, min(8.0, 1.2 + cnt * 1.5), dash, extra,
                           'ar-g' if kind == 'support' else 'ar-r'))
            papers = (e.get('support_papers') if kind == 'support' else e.get('oppose_papers')) or []
            shorts = [_short_paper(p) for p in papers]
            lines = ['、'.join(shorts[i:i + 2]) for i in range(0, len(shorts), 2)]
            mx0 = (x1 + 2 * cxm + x2) / 4
            my0 = (y1 + 2 * cym + y2) / 4 - 6 - 10 * len(lines)
            body.append(t(mx0, my0, ('支持×%d' if kind == 'support' else '不支持×%d') % cnt, 9, color, 'middle'))
            for k, ln in enumerate(lines):
                body.append(t(mx0, my0 + 10 * (k + 1), ln, 9, color, 'middle'))
    for i, nd in enumerate(nodes):
        x, y = pos[i]
        extra = (' data-panel="%scn%d" style="cursor:pointer"' % (panel_prefix, i)) if panel_prefix else ''
        body.append('<circle cx="%.1f" cy="%.1f" r="14" fill="%s"%s/>' % (x, y, BLUE, extra))
        s = labels[i]
        cut = s if len(s) <= 10 else s[:10] + '…'
        body.append(t(x, y + 30, cut, 11, '#dbe7ff', 'middle'))
        if len(s) > 10:
            cut2 = s[10:21] + ('…' if len(s) > 21 else '')
            body.append(t(x, y + 44, cut2, 11, '#dbe7ff', 'middle'))
    body.append(t(20, 22, '绿实线=支持（×N=票数）', 11, GREEN))
    body.append(t(20, 38, '红虚线=不支持（×N=票数）', 11, RED))
    return svg(w, h, ''.join(body))


def pie_chart(items, w=960, size=300):
    """静态饼图：左侧扇形 + 右侧图例（名称/篇数/占比）。"""
    items = [(label, val) for label, val in items if val and val > 0]
    if not items:
        return ''
    total = sum(v for _, v in items)
    h = max(size + 24, 26 * len(items) + 30)
    cx, cy, r = size * 0.5 + 10, h / 2, size * 0.44
    palette = ['#63b3ff', '#f0a35e', '#61d6a6', '#b58cff', '#ff7b7b', '#f4d35e',
               '#4fd1d1', '#8ea6ff', '#ff8fc7', '#9fd36a', '#f0a35e', '#5fa8ff']
    body = []
    ang = -math.pi / 2
    for i, (label, val) in enumerate(items):
        frac = val / float(total)
        a2 = ang + 2 * math.pi * frac
        color = palette[i % len(palette)]
        if frac > 0.9995:
            body.append('<circle cx="%.1f" cy="%.1f" r="%.1f" fill="%s" stroke="#0b1020" stroke-width="2"/>' % (cx, cy, r, color))
        else:
            x1 = cx + r * math.cos(ang)
            y1 = cy + r * math.sin(ang)
            x2 = cx + r * math.cos(a2)
            y2 = cy + r * math.sin(a2)
            large = 1 if frac > 0.5 else 0
            body.append('<path d="M%.1f,%.1f L%.1f,%.1f A%.1f,%.1f 0 %d 1 %.1f,%.1f Z" fill="%s" stroke="#0b1020" stroke-width="2"/>'
                        % (cx, cy, x1, y1, r, r, large, x2, y2, color))
        ang = a2
    lx = cx + r + 30
    for i, (label, val) in enumerate(items):
        y = 24 + i * 24
        pct = round(100.0 * val / total, 1)
        cut = label if len(label) <= 22 else label[:21] + '…'
        body.append('<rect x="%.1f" y="%d" width="12" height="12" fill="%s"/>' % (lx, y - 10, palette[i % len(palette)]))
        body.append(t(lx + 18, y, '%s：%s 篇（%.1f%%）' % (cut, val, pct), 12))
    return svg(w, h, ''.join(body))
