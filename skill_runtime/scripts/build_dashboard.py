#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_dashboard.py — purpose-landscape 技能的图谱仪表盘渲染脚本（仅用 Python 标准库）

用法:
  python3 build_dashboard.py --data dashboard_data.json --out 文献图谱仪表盘.html

读 dashboard_data.json（接口约定见 references/visualizations.md），渲染单文件 ECharts
交互 HTML：总体趋势 / 主题分布(饼柱切换+显示数量) / 比较分析 / 引用网络(球径∝被引、
大球标注、点击红黄高亮) / 因素→结局影响关系图谱(球=因素/结局非文献、绿正红负、
边标注效应量与支撑篇数、点击回溯论文；兼容旧版"结论对"数据) / 研究方法思维导图
(篇数+点击回溯论文) / 语义关系图(点击回溯摘要证据)；年限 D 仅不限范围，其他年限
保留不限/限定年限双范围切换。
移动端/无脚本兜底：HTML 内嵌静态 SVG 与"文字版数据"（与图表同源），当宿主预览
不执行脚本或图表初始化失败时自动显示，图表可用时自动隐藏；并附移动端响应式布局
与强制浅色。数据全部内嵌，打开即用。ECharts 随页面内嵌（scripts/vendor/echarts.min.js），
无需联网、不受 CDN 拦截影响；vendor 缺失时明确失败，绝不回退 CDN。图表使用 SVG
渲染器，不依赖 Canvas/GPU。
"""
import argparse
import html as html_lib
import json
import os
import re
import shutil
import subprocess
import sys

try:
    from static_charts import build_static_charts, build_combined_svg
except Exception:
    build_static_charts = None
    build_combined_svg = None

TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="only light">
<title>文献图谱仪表盘 · __TOPIC__</title>
__ECHARTS_SCRIPTS__
<script>
window.__showStaticFallback = function(){ try{
  var fb = document.getElementById('staticFallback'); if(fb) fb.style.display = 'block';
  var els = document.querySelectorAll('.chartsec');
  for(var i = 0; i < els.length; i++){ els[i].style.display = 'none'; }
}catch(e){} };
window.addEventListener('error', function(){ window.__showStaticFallback(); });
</script>
<style>
  body{margin:0;background:#f5f7fa;font-family:"PingFang SC","Hiragino Sans GB","Microsoft YaHei",sans-serif;color:#333}
  header{background:#fff;padding:18px 28px;border-bottom:1px solid #e3e8ee}
  header h1{margin:0 0 6px;font-size:22px}
  .src{color:#e6a23c;font-size:13px;line-height:1.7}
  .tabs{position:sticky;top:0;z-index:9;background:#fff;padding:10px 28px;border-bottom:1px solid #e3e8ee;display:flex;gap:8px;align-items:center;flex-wrap:wrap}
  .tabs button{border:1px solid #cfd8e3;background:#fff;border-radius:4px;padding:6px 16px;font-size:14px;cursor:pointer}
  .tabs button.on{background:#1e88e7;border-color:#1e88e7;color:#fff}
  .tabs .note{color:#8a94a9;font-size:12px;margin-left:12px}
  section{background:#fff;margin:16px 28px;border:1px solid #e3e8ee;border-radius:6px;overflow:hidden}
  section h2{margin:0;padding:10px 16px;font-size:16px;background:#1e88e7;color:#fff}
  section h2 small{font-weight:normal;font-size:12px;opacity:.9;margin-left:10px}
  .desc{padding:8px 16px 0;font-size:13px;color:#e6a23c}
  .toolbar{padding:8px 16px 0;font-size:13px;color:#555;display:flex;gap:6px;align-items:center;flex-wrap:wrap}
  .toolbar button{border:1px solid #cfd8e3;background:#f2f6fc;border-radius:3px;padding:2px 10px;cursor:pointer;font-size:12px}
  .toolbar button.on{background:#d8d8d8;border-color:#999}
  .chart{width:100%;height:460px}
  .chart.tall{height:560px}
  .flex{display:flex}
  .flex .chart{flex:1;min-width:0}
  .panel{width:320px;border-left:1px solid #e3e8ee;padding:12px 14px;font-size:13px;line-height:1.65;overflow-y:auto;max-height:560px;background:#fbfcfe}
  .panel h3{margin:0 0 8px;font-size:14px;color:#1e88e7}
  .panel .meta{color:#8a94a9;font-size:12px}
  .panel a{color:#1e88e7;word-break:break-all}
  .panel ul{margin:6px 0;padding-left:18px}
  .empty{padding:60px 20px;text-align:center;color:#8a94a9;font-size:14px}
  footer{padding:10px 28px 26px;color:#8a94a9;font-size:12px}
  html{color-scheme:light}
  #staticFallback summary{cursor:pointer;color:#1e88e7;font-size:14px;margin:6px 0}
  #staticFallback table{border-collapse:collapse;width:100%;font-size:13px}
  #staticFallback th,#staticFallback td{border:1px solid #e3e8ee;padding:4px 8px;text-align:left;vertical-align:top}
  #staticFallback th{background:#f2f6fc}
  #staticFallback .meta{color:#8a94a9;font-size:12px}
  #staticFallback p{margin:6px 0}
  #staticFallback ul{margin:4px 0;padding-left:20px}
  @media (max-width: 760px){
    header{padding:14px 16px} header h1{font-size:18px}
    section{margin:10px 8px}
    .flex{flex-direction:column}
    .flex .panel{width:auto;max-height:260px;border-left:none;border-top:1px solid #e3e8ee}
    .chart{height:340px}.chart.tall{height:420px}
    .tabs{padding:8px 12px}
  }
</style>
</head>
<body>
<header>
  <h1>文献图谱仪表盘 · __TOPIC__</h1>
  <div class="src" id="srcLine"></div>
</header>
<div class="tabs" id="tabs"></div>

<noscript><style>#staticFallback{display:block!important}.chartsec{display:none!important}</style></noscript>
<section id="staticFallback" style="display:none">
  <h2>静态图表与文字版数据 <small>图表库未能加载或脚本未启用时自动显示（内联 SVG，无需联网）；图表可用时自动隐藏</small></h2>
  <div style="padding:10px 18px;font-size:13px;line-height:1.8">__STATIC__</div>
</section>

<section class="chartsec"><h2>分布总览 · 文字描述 <small>先总后分：先读总体结论，再看下方各图</small></h2>
  <div id="summary" style="padding:12px 18px;font-size:14px;line-height:2"></div></section>

<section class="chartsec"><h2>总体趋势分析 <small>范围：不限年限</small></h2>
  <div class="desc" id="trendNote"></div><div id="trend" class="chart"></div></section>

<section class="chartsec"><h2>主题分布 <small id="topicsScope"></small></h2>
  <div class="toolbar">图形：<button id="btnPie" class="on">饼图</button><button id="btnBar">柱图</button>
    <span style="margin-left:16px">显示数量：</span><button data-n="10">10</button><button data-n="20" class="on">20</button><button data-n="30">30</button><button data-n="40">40</button></div>
  <div id="topics" class="chart tall"></div></section>

<section class="chartsec"><h2>比较分析 <small>范围：不限年限 · 命中量前 4 主题的年度趋势</small></h2>
  <div id="compare" class="chart"></div></section>

<section class="chartsec"><h2>文章引用关系网络 <small id="netScope"></small></h2>
  <div class="desc">说明：球=一篇文献，球越大=被引越多（大球必带作者-年份标注，小球悬停查看、可一键显示全部标注）；点击结点查看详细信息；红色为引用了该结点的文章，黄色为被该结点引用的文章</div>
  <div class="toolbar"><button id="btnNetLabels">显示全部标注</button></div>
  <div class="flex"><div id="network" class="chart tall"></div><div class="panel" id="netPanel"><h3>结点详情</h3>点击左侧网络中的结点查看。</div></div></section>

<section class="chartsec"><h2>因素 → 结局 影响关系图谱 <small id="kgScope"></small></h2>
  <div class="desc">说明：球=研究中的因素/结局（不是文献！文献在点击后的清单里）；绿箭头=正向影响（加重/增强）、红箭头=负向影响（减轻/削弱），线越粗=支撑文献越多，箭头标注效应量与篇数；点击球或箭头查看支撑论文</div>
  <div class="flex"><div id="knowledge" class="chart tall"></div><div class="panel" id="kgPanel"><h3>关系详情</h3>点击左侧图谱中的结点或箭头查看。</div></div></section>

<section class="chartsec"><h2>研究方法思维导图 <small id="mmScope"></small></h2>
  <div class="desc">说明：方法 = 数据获取 × 分析技术（先立判定卡：研究主题、比较对象、变量处理步骤不计入，归“其他（未明确方法）”）；名称后数字=使用该方法的文献篇数；点击方法结点查看对应论文；滚轮缩放、拖拽平移</div>
  <div class="flex"><div id="methods" class="chart tall"></div><div class="panel" id="mmPanel"><h3>方法论文</h3>点击左侧结点查看使用该方法的论文。</div></div></section>

<section class="chartsec"><h2>语义关系图谱 <small id="relScope"></small></h2>
  <div class="desc">说明：圆圈=检索池论文；连线=支持/改进/冲突/差异；点击圆点或连线查看关系理由与双方摘要原句；空数据不补造语义边</div>
  <div class="flex"><div id="relations" class="chart tall"></div><div class="panel" id="relPanel"><h3>关系详情</h3>点击左侧图谱中的结点或连线查看摘要证据。</div></div></section>

<footer id="foot"></footer>
<script>
const DATA = __DATA__;
const state = {scope: 'all', pie: true, topn: 20, netAllLabels: false};
const HAS_ECHARTS = !!window.echarts;
const charts = {};
function mk(id){ if(!window.echarts) return null; if(!charts[id]) charts[id] = echarts.init(document.getElementById(id), null, {renderer: 'svg'}); return charts[id]; }
function empty(id, msg){ const el = document.getElementById(id); el.innerHTML = '<div class="empty">' + msg + '</div>'; if(charts[id]){ charts[id].dispose(); delete charts[id]; } }
function esc(s){ return String(s == null ? '' : s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }
function zh(x){ return x.name_zh || x.name; }
function biName(n, en){ return en && en !== n ? esc(n) + '（' + esc(en) + '）' : esc(n); }
function scope(){ return DATA.scopes[state.scope]; }
function paperItem(x, withLink){
  if(typeof x === 'string') return '<li>' + esc(x) + '</li>';
  const title = x.title ? '：' + esc(x.title) : '';
  const link = (withLink && x.url) ? ' <a href="' + esc(x.url) + '" target="_blank">原文/题录</a>' : '';
  return '<li>[' + (x.ref == null ? '-' : x.ref) + '] ' + esc(x.label || '') + title + link + '</li>';
}
function paperShort(x){
  if(typeof x === 'string') return x;
  const lab = x.label || '';
  const nm = lab.split(',')[0].trim();
  const m = lab.match(/\d{4}/);
  return '[' + (x.ref == null ? '-' : x.ref) + '] ' + nm + (m ? ' ' + m[0] : '');
}
function edgePapersText(arr){
  const ls = (arr || []).map(paperShort);
  const out = [];
  for(let i = 0; i < ls.length; i += 2){ out.push(ls.slice(i, i + 2).join('、')); }
  return out.join('\n');
}
function paperList(arr, withLink){
  if(!arr || !arr.length) return '<div class="meta">无关联论文</div>';
  return '<ul>' + arr.map(x => paperItem(x, withLink)).join('') + '</ul>';
}

document.getElementById('srcLine').innerHTML =
  '数据来源： 文献总数 ' + (DATA.scopes.all.total_hits || 0) + ' 篇（不限年限命中）；检索条件：' + esc(DATA.condition) +
  '；数据库：' + esc(DATA.sources) + '；生成日期：' + esc(DATA.generated_at);
document.getElementById('trendNote').textContent = '文献总数 ' + (DATA.scopes.all.total_hits || 0) + ' 篇；按发表年度统计（不限年限）。';
document.getElementById('foot').textContent = '本仪表盘由 purpose-landscape 技能生成；池内图（引用网络/因素→结局图谱/方法导图）基于 ≤50 篇论文池，主题分布与趋势基于 OpenAlex 全量命中聚合计数。' ;

(function buildTabs(){
  const t = document.getElementById('tabs');
  const keys = Object.keys(DATA.scopes);
  keys.forEach(k => {
    const b = document.createElement('button');
    b.textContent = DATA.scopes[k].label;
    b.dataset.scope = k;
    if(k === state.scope) b.classList.add('on');
    b.onclick = () => { state.scope = k;
      t.querySelectorAll('button').forEach(x => x.classList.toggle('on', x.dataset.scope === k));
      renderScope(); };
    t.appendChild(b);
  });
  const n = document.createElement('span');
  n.className = 'note';
  n.textContent = keys.length > 1 ? '切换范围影响：主题分布 / 引用网络 / 因素→结局图谱 / 方法导图；总体趋势与比较分析固定为不限年限。' : '用户选定不限年限，仅生成不限年限范围。';
  t.appendChild(n);
})();

function renderTrend(){
  const g = DATA.trend_all || [];
  if(!g.length){ empty('trend', '无年度趋势数据'); return; }
  mk('trend').setOption({
    animation: false,
    tooltip: {trigger: 'axis'},
    grid: {left: 60, right: 30, top: 40, bottom: 40},
    xAxis: {type: 'category', data: g.map(x => x.year), boundaryGap: false},
    yAxis: {type: 'value', name: '发文量（篇）'},
    series: [{name: '发表年度趋势', type: 'line', data: g.map(x => x.count), symbol: 'circle', symbolSize: 6, lineStyle: {color: '#1e88e7', width: 2}, itemStyle: {color: '#1e88e7'}}]
  }, true);
}

function renderTopics(){
  const sc = scope();
  document.getElementById('topicsScope').textContent = '范围：' + sc.label + '（命中 ' + (sc.total_hits || 0) + ' 篇）';
  const g = (sc.topics || []).slice(0, state.topn);
  if(!g.length){ empty('topics', '该范围无主题分布数据'); return; }
  const total = g.reduce((s, x) => s + x.count, 0);
  const opt = {
    animation: false,
    tooltip: {trigger: 'item', formatter: p => biName(p.name, p.data.en) + '：' + p.value + ' 篇'},
    legend: {type: 'scroll', orient: 'vertical', right: 10, top: 20, bottom: 20, textStyle: {fontSize: 12}},
    series: []
  };
  if(state.pie){
    opt.series = [{type: 'pie', radius: '68%', center: ['42%', '50%'],
      data: g.map(x => ({name: zh(x), en: x.name, value: x.count})),
      label: {formatter: p => p.value + '(' + (Math.round(p.value / total * 10000) / 100) + '%)'},
      labelLine: {length: 12, length2: 8}}];
  } else {
    opt.grid = {left: 60, right: 30, top: 30, bottom: 110};
    opt.xAxis = {type: 'category', data: g.map(x => zh(x)), axisLabel: {rotate: 45, fontSize: 11}};
    opt.yAxis = {type: 'value', name: '篇数'};
    opt.series = [{type: 'bar', data: g.map(x => ({name: zh(x), en: x.name, value: x.count})), itemStyle: {color: '#1e88e7'},
      label: {show: true, position: 'top', fontSize: 10}}];
  }
  mk('topics').setOption(opt, true);
}
document.getElementById('btnPie').onclick = () => { state.pie = true;
  document.getElementById('btnPie').classList.add('on'); document.getElementById('btnBar').classList.remove('on'); renderTopics(); };
document.getElementById('btnBar').onclick = () => { state.pie = false;
  document.getElementById('btnBar').classList.add('on'); document.getElementById('btnPie').classList.remove('on'); renderTopics(); };
document.querySelectorAll('.toolbar button[data-n]').forEach(b => b.onclick = () => {
  state.topn = +b.dataset.n;
  document.querySelectorAll('.toolbar button[data-n]').forEach(x => x.classList.toggle('on', x === b));
  renderTopics(); });

function renderCompare(){
  const cs = DATA.compare || [];
  if(!cs.length){ empty('compare', '无比较分析数据'); return; }
  const yearSet = new Set();
  cs.forEach(c => (c.series || []).forEach(x => yearSet.add(x.year)));
  const years = Array.from(yearSet).sort((a, b) => a - b);
  mk('compare').setOption({
    animation: false,
    tooltip: {trigger: 'axis', formatter: ps => {
      let s = ps[0].axisValue + ' 年';
      ps.forEach(p => { const c = cs[p.seriesIndex];
        s += '<br>' + p.marker + '主题"' + biName(zh(c), c.name) + '"：' + p.value + ' 篇'; });
      return s;
    }},
    legend: {top: 5, data: cs.map(c => '主题"' + zh(c) + '"趋势')},
    grid: {left: 60, right: 30, top: 40, bottom: 40},
    xAxis: {type: 'category', data: years, boundaryGap: false},
    yAxis: {type: 'value', name: '发文量（篇）'},
    series: cs.map(c => ({name: '主题"' + zh(c) + '"趋势', type: 'line', symbol: 'circle', symbolSize: 5,
      data: years.map(y => { const hit = c.series.find(x => x.year === y); return hit ? hit.count : 0; })}))
  }, true);
}

const NET_BLUE = '#4aa3df', NET_RED = '#e64545', NET_YELLOW = '#f4c20d';
function prelayout(nodes, edges, w, h){
  const n = nodes.length, pos = [], idx = {};
  for(let i = 0; i < n; i++){
    idx[nodes[i].id] = i;
    const a = 2 * Math.PI * i / n;
    pos.push([w / 2 + (w / 3) * Math.cos(a), h / 2 + (h / 3) * Math.sin(a)]);
  }
  for(let it = 0; it < 150; it++){
    const disp = [];
    for(let i = 0; i < n; i++) disp.push([0, 0]);
    for(let i = 0; i < n; i++) for(let j = i + 1; j < n; j++){
      const dx = pos[i][0] - pos[j][0], dy = pos[i][1] - pos[j][1];
      const d2 = dx * dx + dy * dy + 0.01, d = Math.sqrt(d2);
      const f = Math.min(40, 2200 / d2), ux = dx / d, uy = dy / d;
      disp[i][0] += ux * f; disp[i][1] += uy * f;
      disp[j][0] -= ux * f; disp[j][1] -= uy * f;
    }
    (edges || []).forEach(e => {
      const a = idx[e.s], b = idx[e.t];
      if(a == null || b == null || a === b) return;
      const dx = pos[b][0] - pos[a][0], dy = pos[b][1] - pos[a][1];
      const d = Math.sqrt(dx * dx + dy * dy) + 0.01, f = 0.02 * (d - 110);
      const ux = dx / d, uy = dy / d;
      disp[a][0] += ux * f; disp[a][1] += uy * f;
      disp[b][0] -= ux * f; disp[b][1] -= uy * f;
    });
    const cool = Math.max(0.03, 0.9 - it * 0.007);
    for(let i = 0; i < n; i++){
      disp[i][0] += (w / 2 - pos[i][0]) * 0.02;
      disp[i][1] += (h / 2 - pos[i][1]) * 0.02;
      const dl = Math.sqrt(disp[i][0] * disp[i][0] + disp[i][1] * disp[i][1]) + 0.01;
      pos[i][0] = Math.min(w - 70, Math.max(70, pos[i][0] + disp[i][0] / dl * Math.min(dl, 18) * cool));
      pos[i][1] = Math.min(h - 40, Math.max(36, pos[i][1] + disp[i][1] / dl * Math.min(dl, 18) * cool));
    }
  }
  return pos;
}
function factorPos(nodes){
  const factors = nodes.filter(n => n.type !== 'outcome');
  const outcomes = nodes.filter(n => n.type === 'outcome');
  const m = Math.max(factors.length, outcomes.length, 1);
  const h = Math.max(260, 54 * m + 70), step = (h - 90) / m;
  return nodes.map(n => {
    const arr = (n.type === 'outcome') ? outcomes : factors;
    const i = arr.indexOf(n);
    return [(n.type === 'outcome') ? 760 : 140, 50 + step * (i + 0.5)];
  });
}
function claimPos(nodes){
  const n = nodes.length, h = Math.max(340, 130 + n * 80), pos = [];
  for(let i = 0; i < n; i++){
    const a = 2 * Math.PI * i / n - Math.PI / 2;
    pos.push([450 + 280 * Math.cos(a), h / 2 + ((h - 130) / 2 * 0.8) * Math.sin(a)]);
  }
  return pos;
}
function renderNetwork(){
  const sc = scope();
  document.getElementById('netScope').textContent = '范围：' + sc.label + '（池内 ' + (sc.pool_count || 0) + ' 篇）';
  const net = sc.network || {nodes: [], edges: []};
  if(!net.nodes.length){ empty('network', '该范围论文池为空，无法生成引用网络'); return; }
  const labelTop = new Set([...net.nodes].sort((a, b) => (b.cited || 0) - (a.cited || 0)).slice(0, 12).map(n => n.id));
  const netPos = prelayout(net.nodes, net.edges, 900, 500);
  const draw = (colors) => mk('network').setOption({
    animation: false,
    tooltip: {formatter: p => p.dataType === 'node' ? esc(p.data.label) + '（被引 ' + (p.data.cited == null ? '-' : p.data.cited) + '）<br>' + esc(p.data.title) : esc(p.data.sLabel || '') + ' 引用 ' + esc(p.data.tLabel || '')},
    series: [{type: 'graph', layout: 'none', roam: true, draggable: true,
      animation: false,
      label: {show: true, fontSize: 10, color: '#555'},
      labelLayout: {hideOverlap: true},
      data: net.nodes.map((n, i) => Object.assign({}, n, {x: netPos[i][0], y: netPos[i][1],
        symbolSize: 10 + 8 * Math.log(1 + (n.cited || 0)),
        label: {show: state.netAllLabels || labelTop.has(n.id)},
        itemStyle: {color: (colors && colors[n.id]) || NET_BLUE}})),
      links: net.edges.map(e => Object.assign({}, e, {source: e.s, target: e.t, lineStyle: {color: '#bbb', width: 1, curveness: 0.08}})),
      emphasis: {focus: 'adjacency', lineStyle: {width: 2}}}]
  }, true);
  draw(null);
  document.getElementById('btnNetLabels').classList.toggle('on', state.netAllLabels);
  document.getElementById('btnNetLabels').onclick = () => { state.netAllLabels = !state.netAllLabels; renderNetwork(); };
  const byId = {}; net.nodes.forEach(n => byId[n.id] = n);
  charts['network'].off('click');
  charts['network'].on('click', p => {
    if(p.dataType !== 'node') return;
    const id = p.data.id;
    const colors = {};
    net.edges.forEach(e => { if(e.t === id) colors[e.s] = NET_RED; if(e.s === id) colors[e.t] = NET_YELLOW; });
    draw(colors);
    const n = byId[id];
    const citing = net.edges.filter(e => e.t === id).map(e => byId[e.s]).filter(Boolean);
    const cited = net.edges.filter(e => e.s === id).map(e => byId[e.t]).filter(Boolean);
    document.getElementById('netPanel').innerHTML =
      '<h3>' + esc(n.label) + '</h3>' +
      '<div>' + esc(n.title) + '</div>' +
      '<div class="meta">' + esc(n.authors || '') + ' · ' + (n.year || '?') + ' · ' + esc(n.venue || '') + ' · 被引 ' + (n.cited == null ? '-' : n.cited) + '</div>' +
      (n.url ? '<div><a href="' + esc(n.url) + '" target="_blank">原文 / 题录链接</a></div>' : '') +
      (n.excerpt ? '<div style="margin-top:6px">' + esc(n.excerpt) + '</div>' : '') +
      '<div style="margin-top:8px;color:' + NET_RED + '">引用了该结点（池内 ' + citing.length + '）：</div><ul>' +
      (citing.map(x => '<li>' + esc(x.label) + '</li>').join('') || '<li>无</li>') + '</ul>' +
      '<div style="color:#c79a00">被该结点引用（池内 ' + cited.length + '）：</div><ul>' +
      (cited.map(x => '<li>' + esc(x.label) + '</li>').join('') || '<li>无</li>') + '</ul>';
  });
  if(!net.edges.length) document.getElementById('netPanel').innerHTML += '<div class="meta" style="margin-top:8px">池内论文互引较少，网络以孤立结点呈现（真实数据，不补边）。</div>';
}

function renderKnowledge(){
  const sc = scope();
  document.getElementById('kgScope').textContent = '范围：' + sc.label;
  const kg = sc.knowledge || {nodes: [], edges: []};
  if(!kg.nodes.length){ empty('knowledge', '该范围未能凝练出可核验的“因素→结局”影响关系（证据不足，不硬造）'); return; }
  const byId = {}; kg.nodes.forEach(n => byId[n.id] = n);
  const factorMode = (kg.edges || []).some(e => e.polarity);
  if(factorMode){
    const links = [], pairCount = {};
    kg.edges.forEach(e => {
      const key = e.s + '|' + e.t;
      const idx = pairCount[key] || 0; pairCount[key] = idx + 1;
      const pos = e.polarity !== 'neg';
      links.push({
        source: e.s, target: e.t, polarity: e.polarity,
        effect: e.effect || '', support: e.support || 0,
        papers: e.papers || [], disputed: !!e.disputed,
        lineStyle: {color: pos ? '#2e9e5b' : '#d64545', width: Math.min(14, 1.5 + (e.support || 1) * 1.8), curveness: idx === 0 ? 0.08 : -0.12},
        label: {show: true, fontSize: 9, lineHeight: 11, color: pos ? '#2e9e5b' : '#d64545',
          formatter: ((e.effect ? e.effect + ' · ' : '') + (e.support || 0) + '篇' + (e.disputed ? '（争议）' : '')) +
            (e.papers && e.papers.length ? '\n' + edgePapersText(e.papers) : '')}
      });
    });
    const fpos = factorPos(kg.nodes);
    mk('knowledge').setOption({
      animation: false,
      tooltip: {formatter: p => {
        if(p.dataType === 'node'){ const n = byId[p.data.id] || {};
          return '<b>' + esc(n.name || '') + '</b>（' + (n.type === 'outcome' ? '结局' : '因素') + '）<br>关联论文 ' + ((n.papers || []).length) + ' 篇'; }
        const e = p.data; const f = byId[e.source] || {}; const t = byId[e.target] || {};
        return esc(f.name || '') + ' → ' + esc(t.name || '') + '<br>' + (e.polarity === 'neg' ? '负向影响（因素越强，结局越轻）' : '正向影响（因素越强，结局越重）') +
          (e.effect ? '<br>效应量：' + esc(e.effect) : '') + '<br>支撑 ' + (e.support || 0) + ' 篇' + (e.disputed ? '（存在争议）' : '');
      }},
      series: [{type: 'graph', layout: 'none', roam: true, draggable: true,
        animation: false,
        label: {show: true, fontSize: 12, color: '#333'},
        edgeSymbol: ['none', 'arrow'], edgeSymbolSize: 9,
        data: kg.nodes.map((n, i) => Object.assign({}, n, {x: fpos[i][0], y: fpos[i][1],
          symbol: n.type === 'outcome' ? 'diamond' : 'circle',
          symbolSize: n.type === 'outcome' ? 30 + Math.min(16, (n.papers || []).length * 2) : 16 + Math.min(14, (n.papers || []).length * 3),
          itemStyle: {color: n.type === 'outcome' ? '#e6802f' : '#1e88e7'}})),
        links: links,
        emphasis: {focus: 'adjacency'}}]
    }, true);
    charts['knowledge'].off('click');
    charts['knowledge'].on('click', p => {
      const panel = document.getElementById('kgPanel');
      if(p.dataType === 'node'){
        const n = byId[p.data.id] || {};
        const rels = kg.edges.filter(e => e.s === n.id || e.t === n.id);
        let html = '<h3>' + (n.type === 'outcome' ? '结局' : '因素') + '：' + esc(n.name) + '</h3>';
        html += '<div>关联论文（' + (n.papers || []).length + '）：</div>' + paperList(n.papers || [], true);
        if(rels.length){
          html += '<div style="margin-top:8px">涉及关系：</div><ul>' + rels.map(e => {
            const f = byId[e.s] || {}; const t = byId[e.t] || {};
            return '<li>' + esc(f.name || '') + ' → ' + esc(t.name || '') + '：' + (e.polarity === 'neg' ? '负向' : '正向') +
              (e.effect ? ' · ' + esc(e.effect) : '') + ' · ' + (e.support || 0) + ' 篇' + (e.disputed ? '（争议）' : '') + '</li>';
          }).join('') + '</ul>';
        }
        panel.innerHTML = html;
      } else if(p.dataType === 'edge'){
        const e = p.data; const f = byId[e.source] || {}; const t = byId[e.target] || {};
        panel.innerHTML = '<h3>' + esc(f.name || '') + ' → ' + esc(t.name || '') + '</h3>' +
          '<div>' + (e.polarity === 'neg' ? '负向影响（因素水平越高，结局越轻）' : '正向影响（因素水平越高，结局越重）') +
          (e.effect ? ' · 效应量 ' + esc(e.effect) : '') + ' · 支撑 ' + (e.support || 0) + ' 篇' + (e.disputed ? '（存在争议）' : '') + '</div>' +
          '<div style="margin-top:8px">支撑论文：</div>' + paperList(e.papers || [], true) +
          '<div style="margin-top:8px">摘要原句：</div>' + evidenceList(e.evidence || []) +
          '<div class="meta">每票均来自对应论文摘要，并同步写入 graph_evidence.md。</div>';
      }
    });
    return;
  }
  // ===== 旧版“结论对”数据兼容渲染（claim 模式） =====
  const links = [];
  kg.edges.forEach(e => {
    if(e.support > 0) links.push({source: e.s, target: e.t, name: '支持',
      lineStyle: {color: '#2e9e5b', width: Math.min(12, 1 + e.support * 1.6), curveness: 0.15},
      label: {show: true, fontSize: 9, lineHeight: 11, color: '#2e9e5b',
        formatter: '支持×' + e.support + ((e.support_papers || []).length ? '\n' + edgePapersText(e.support_papers) : '')},
      support_papers: e.support_papers || [], oppose_papers: e.oppose_papers || [], s: e.s, t: e.t});
    if(e.oppose > 0) links.push({source: e.s, target: e.t, name: '不支持',
      lineStyle: {color: '#d64545', width: Math.min(12, 1 + e.oppose * 1.6), type: 'dashed', curveness: -0.15},
      label: {show: true, fontSize: 9, lineHeight: 11, color: '#d64545',
        formatter: '不支持×' + e.oppose + ((e.oppose_papers || []).length ? '\n' + edgePapersText(e.oppose_papers) : '')},
      support_papers: e.support_papers || [], oppose_papers: e.oppose_papers || [], s: e.s, t: e.t});
  });
  const cpos = claimPos(kg.nodes);
  mk('knowledge').setOption({
    animation: false,
    tooltip: {formatter: p => p.dataType === 'node' ? esc(p.data.claim) + '<br>支撑文章 ' + (p.data.papers || []).length + ' 篇' :
      esc((byId[p.data.s] || {}).claim || '') + ' → ' + esc((byId[p.data.t] || {}).claim || '') + '<br>' + p.data.name + '：' + (p.data.name === '支持' ? p.data.support_papers.length : p.data.oppose_papers.length) + ' 篇投票'},
    series: [{type: 'graph', layout: 'none', roam: true, draggable: true,
      animation: false,
      label: {show: true, fontSize: 11, color: '#333', width: 150, overflow: 'break'},
      edgeSymbol: ['none', 'arrow'], edgeSymbolSize: 8,
      data: kg.nodes.map((n, i) => Object.assign({}, n, {x: cpos[i][0], y: cpos[i][1], symbolSize: 18 + Math.min(30, (n.papers || []).length * 4), itemStyle: {color: '#1e88e7'}})),
      links: links,
      emphasis: {focus: 'adjacency'}}]
  }, true);
  charts['knowledge'].off('click');
  charts['knowledge'].on('click', p => {
    const panel = document.getElementById('kgPanel');
    if(p.dataType === 'node'){
      const n = byId[p.data.id];
      panel.innerHTML = '<h3>核心结论</h3><div>' + esc(n.claim) + '</div>' +
        '<div style="margin-top:8px">支撑文章（' + (n.papers || []).length + '）：</div>' + paperList(n.papers || [], true);
    } else if(p.dataType === 'edge'){
      const e = p.data;
      const papers = e.name === '支持' ? e.support_papers : e.oppose_papers;
      panel.innerHTML = '<h3>' + esc(e.name) + '关系 ×' + papers.length + '</h3>' +
        '<div>' + esc((byId[e.s] || {}).claim || '') + ' → ' + esc((byId[e.t] || {}).claim || '') + '</div>' +
        '<div style="margin-top:8px">投票文章：</div>' + paperList(papers, true) +
        '<div class="meta">每票须能在 graph_evidence.md 挂到摘要原句。</div>';
    }
  });
}

function renderMethods(){
  const sc = scope();
  document.getElementById('mmScope').textContent = '范围：' + sc.label;
  const mm = sc.methods;
  if(!mm || !(mm.children || []).length){ empty('methods', '该范围无方法归类数据'); return; }
  const walk = n => ({name: n.name + (n.count != null ? '（' + n.count + '篇）' : ''),
    papers: n.papers || [], children: (n.children || []).map(walk)});
  // ECharts 5.5.1 在范围切换复用树图时可能残留失效边引用，重建实例以隔离旧状态。
  if(charts['methods']){ charts['methods'].dispose(); delete charts['methods']; }
  mk('methods').setOption({
    animation: false,
    tooltip: {trigger: 'item', formatter: p => {
      const arr = (p.data.papers || []).map(x => typeof x === 'string' ? x : ('[' + (x.ref == null ? '-' : x.ref) + '] ' + (x.label || '')));
      const nm = String(p.name || '').replace(/（\d+篇）$/, '');
      return arr.length ? '<b>' + esc(nm) + '</b><br>' + arr.map(esc).join('<br>') : esc(nm);
    }},
    series: [{type: 'tree', orient: 'LR', roam: true, initialTreeDepth: 2,
      animation: false, animationDurationUpdate: 0,
      symbol: 'circle', symbolSize: 9,
      label: {fontSize: 12, color: '#333'},
      leaves: {label: {fontSize: 11, color: '#666'}},
      lineStyle: {color: '#b9c6d8', width: 1.5},
      expandAndCollapse: true,
      data: [walk(mm)]}]
  }, true);
  charts['methods'].off('click');
  charts['methods'].on('click', p => {
    const panel = document.getElementById('mmPanel');
    const d = p.data || {};
    const papers = d.papers || [];
    const nm = String(d.name || '').replace(/（\d+篇）$/, '');
    panel.innerHTML = '<h3>' + esc(nm) + '</h3>' +
      (papers.length ? ('<div>使用该方法的论文（' + papers.length + '）：</div>' + paperList(papers, true))
        : '<div class="meta">该结点下无论文明细（内部结点，展开子结点查看）。</div>');
  });
}

function evidenceList(items){
  if(!items || !items.length) return '<div class="meta">无可用摘要证据</div>';
  return items.map(v => '<blockquote style="margin:6px 0;padding:7px 10px;border-left:2px solid #1e88e7;background:#f2f6fc">' +
    '<b>[ref ' + (v.ref_no == null ? (v.ref == null ? '-' : v.ref) : v.ref_no) + ']</b> ' + esc(v.quote || '') + '</blockquote>').join('');
}

function renderRelations(){
  const sc = scope();
  const rel = sc.relations || {};
  const nodes = (sc.network || {}).nodes || [];
  const edges = (rel.edges || []).filter(e => e && e.s && e.t);
  const types = rel.types || {};
  document.getElementById('relScope').textContent = '范围：' + sc.label + '（池内 ' + nodes.length + ' 篇）';
  if(!nodes.length || !edges.length){ empty('relations', rel.message || '该范围暂无可核验的论文关系（不补造语义边）'); return; }
  const byId = {}; nodes.forEach(n => byId[n.id] = n);
  const deg = {}; edges.forEach(e => { deg[e.s] = (deg[e.s] || 0) + 1; deg[e.t] = (deg[e.t] || 0) + 1; });
  const top = new Set(nodes.filter(n => deg[n.id]).sort((a, b) => (deg[b.id] || 0) - (deg[a.id] || 0) || (b.cited || 0) - (a.cited || 0)).slice(0, 12).map(n => n.id));
  const pos = prelayout(nodes, edges, 900, 500);
  const pal = {support:'#2e9e5b', improve:'#1e88e7', conflict:'#d64545', difference:'#8e67c7'};
  const labelOf = id => (byId[id] || {}).label || id;
  mk('relations').setOption({
    animation: false,
    tooltip: {formatter: p => {
      if(p.dataType === 'node'){ const n = byId[p.data.id] || {}; return esc(n.label || '') + '<br>' + esc(n.title || '') + '<br>关系 ' + (deg[n.id] || 0) + ' 条'; }
      const e = p.data || {}; return esc((types[e.type] || {}).name || e.type) + '<br>' + esc(labelOf(e.s)) + ' → ' + esc(labelOf(e.t)) + '<br>' + esc(e.reason || '');
    }},
    series: [{type:'graph', layout:'none', roam:true, draggable:true, animation:false,
      label:{show:true,fontSize:10,color:'#555'}, labelLayout:{hideOverlap:true},
      edgeSymbol:['none','arrow'], edgeSymbolSize:7,
      data:nodes.map((n, i) => Object.assign({}, n, {x:pos[i][0], y:pos[i][1],
        symbolSize:7 + Math.min(12, (deg[n.id] || 0) * 2),
        label:{show:top.has(n.id)}, itemStyle:{color:deg[n.id] ? '#4aa3df' : '#9aa7b8'}})),
      links:edges.map(e => Object.assign({}, e, {source:e.s, target:e.t,
        lineStyle:{color:pal[e.type] || '#999', width:e.confidence === 'high' ? 2 : 1.2, curveness:.1}})),
      emphasis:{focus:'adjacency', lineStyle:{width:3}}}]
  }, true);
  charts['relations'].off('click');
  charts['relations'].on('click', p => {
    const panel = document.getElementById('relPanel');
    if(p.dataType === 'node'){
      const id = p.data.id, list = edges.filter(e => e.s === id || e.t === id);
      panel.innerHTML = '<h3>' + esc(labelOf(id)) + '</h3><div>' + esc((byId[id] || {}).title || '') + '</div>' +
        '<div style="margin-top:8px">关系（' + list.length + '）：</div><ul>' + list.map(e =>
          '<li>' + esc((types[e.type] || {}).name || e.type) + '：' + esc(labelOf(e.s === id ? e.t : e.s)) +
          '<div class="meta">' + esc(e.reason || '') + '</div></li>').join('') + '</ul>';
    } else if(p.dataType === 'edge'){
      const e = p.data || {};
      panel.innerHTML = '<h3>' + esc((types[e.type] || {}).name || e.type) + '关系</h3>' +
        '<div>' + esc(labelOf(e.s)) + ' → ' + esc(labelOf(e.t)) + '</div>' +
        '<div style="margin-top:6px">' + esc(e.reason || '') + '</div>' +
        '<div style="margin-top:8px">摘要证据：</div>' + evidenceList(e.evidence || []) +
        '<div class="meta">置信度：' + esc(e.confidence || '-') + '；冲突/差异为分析判断。</div>';
    }
  });
}

function renderSummary(){
  const parts = [];
  Object.keys(DATA.scopes).forEach(k => {
    const sc = DATA.scopes[k];
    const t = sc.total_hits || 0;
    const g = sc.topics || [];
    const sum = g.reduce((s, x) => s + x.count, 0);
    const pc = c => sum ? (Math.round(c / sum * 1000) / 10) + '%' : '-';
    let s;
    if(k === 'all'){ s = '<b>不限年限</b>：总共检索到 ' + t + ' 篇文献。'; }
    else {
      const n = sc.from_year ? (new Date().getFullYear() - sc.from_year + 1) : null;
      s = '<b>' + esc(sc.label) + '</b>' + (n ? '（近 ' + n + ' 年）' : '') + '：共 ' + t + ' 篇文献。';
    }
    if(g.length){
      s += '主题命中中"' + esc(zh(g[0])) + '"占比最多（' + pc(g[0].count) + '）';
      if(g[1]) s += '，其次是"' + esc(zh(g[1])) + '"（' + pc(g[1].count) + '）';
      if(g[2]) s += '、"' + esc(zh(g[2])) + '"（' + pc(g[2].count) + '）';
      s += '。';
    } else { s += '无主题分布数据。'; }
    parts.push('<p>' + s + '</p>');
  });
  const tr = DATA.trend_all || [];
  if(tr.length){ const peak = tr.reduce((a, b) => b.count > a.count ? b : a);
    parts.push('<p><b>总体趋势</b>：发文量在 ' + peak.year + ' 年达到峰值（' + peak.count + ' 篇）。</p>'); }
  document.getElementById('summary').innerHTML = parts.join('');
}

function renderScope(){ if(!HAS_ECHARTS) return; renderTopics(); renderNetwork(); renderKnowledge(); renderMethods(); renderRelations(); }
function showStaticFallback(){ if(window.__showStaticFallback) window.__showStaticFallback(); }
if(HAS_ECHARTS){
  try { renderTrend(); renderCompare(); renderScope(); renderSummary(); }
  catch(err) { showStaticFallback(); }
} else { showStaticFallback(); }
window.addEventListener('resize', () => Object.values(charts).forEach(c => c.resize()));
</script>
</body>
</html>
"""


def build_static(data):
    """生成与图表同源的文字版数据（无脚本/图表库不可用时显示）。"""
    esc = lambda s: html_lib.escape(str(s if s is not None else ''))

    def zh(x):
        return x.get('name_zh') or x.get('name') or ''

    out = ['<p>（本段为文字版数据，与图表同源；在支持脚本且图表库可用的环境中会自动显示图表。）</p>']
    for k, sc in (data.get('scopes') or {}).items():
        g = sc.get('topics') or []
        total = sum(x.get('count', 0) for x in g)
        line = '<p><b>%s</b>：命中 %s 篇，论文池 %s 篇。' % (esc(sc.get('label', '')), sc.get('total_hits', 0), sc.get('pool_count', 0))
        if g:
            tops = '；'.join('%s %s 篇（%s%%）' % (esc(zh(x)), x.get('count', 0),
                                                    round(100.0 * x.get('count', 0) / total, 1) if total else 0) for x in g[:3])
            line += '主题占比前列：' + tops + '。'
        out.append(line + '</p>')
    tr = data.get('trend_all') or []
    if tr:
        peak = max(tr, key=lambda x: x.get('count', 0))
        out.append('<p><b>总体趋势</b>：峰值 %s 年（%s 篇）。</p>' % (esc(peak.get('year')), peak.get('count', 0)))
    for k, sc in (data.get('scopes') or {}).items():
        out.append('<h3 style="margin:14px 0 6px">%s · 明细</h3>' % esc(sc.get('label', '')))
        g = sc.get('topics') or []
        if g:
            rows = ''.join('<tr><td>%s</td><td>%s</td></tr>' % (esc(zh(x)), x.get('count', 0)) for x in g[:12])
            out.append('<details open><summary>主题分布（前 12）</summary><table><tr><th>主题</th><th>命中篇数</th></tr>%s</table></details>' % rows)
        net = sc.get('network') or {}
        nodes = sorted((net.get('nodes') or []), key=lambda n: -(n.get('cited') or 0))
        if nodes:
            rows = []
            for n in nodes[:20]:
                rows.append('<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>' % (
                    esc(n.get('label')), esc(n.get('title')),
                    n.get('cited') if n.get('cited') is not None else '-',
                    ('<a href="%s" target="_blank">链接</a>' % esc(n.get('url'))) if n.get('url') else '-'))
            out.append('<details><summary>引用网络（池内 %d 篇，按被引列前 20）</summary>'
                       '<table><tr><th>作者-年份</th><th>标题</th><th>被引</th><th>链接</th></tr>%s</table></details>'
                       % (len(nodes), ''.join(rows)))
        kg = sc.get('knowledge') or {}
        kn = kg.get('nodes') or []
        ke = kg.get('edges') or []
        if kn:
            factor_mode = any(e.get('polarity') for e in ke)
            if factor_mode:
                nm = {n.get('id'): n.get('name', '') for n in kn}
                lis = []
                for e in ke:
                    ps = '；'.join('[%s] %s' % (p.get('ref'), esc(p.get('label', ''))) for p in (e.get('papers') or [])[:8])
                    lis.append('<li>%s → %s：%s%s · 支撑 %s 篇%s<br><span class="meta">%s</span></li>' % (
                        esc(nm.get(e.get('s'), '')), esc(nm.get(e.get('t'), '')),
                        '正向' if e.get('polarity') != 'neg' else '负向',
                        ('（效应量 %s）' % esc(e.get('effect'))) if e.get('effect') else '',
                        e.get('support', 0), '（存在争议）' if e.get('disputed') else '', ps))
                out.append('<details open><summary>因素→结局影响关系（%d 条）</summary><ul>%s</ul></details>'
                           % (len(ke), ''.join(lis)))
            else:
                lis = []
                for n in kn:
                    ps = '；'.join('[%s] %s' % (p.get('ref'), esc(p.get('label', ''))) for p in (n.get('papers') or [])[:8])
                    lis.append('<li>%s<br><span class="meta">支撑：%s</span></li>' % (esc(n.get('claim', '')), ps))
                out.append('<details><summary>核心结论（旧版结论对）</summary><ul>%s</ul></details>' % ''.join(lis))
        mm = sc.get('methods')
        if mm:
            def walk(n):
                cnt = '（%s篇）' % n.get('count') if n.get('count') is not None else ''
                kids = ''.join(walk(c) for c in (n.get('children') or []))
                return '<li>%s%s%s</li>' % (esc(n.get('name', '')), esc(cnt), ('<ul>' + kids + '</ul>') if kids else '')
            out.append('<details><summary>研究方法（先定义后分类）</summary><ul>%s</ul></details>' % walk(mm))
    return '\n'.join(out)


def export_static_files(data, out_path):
    """随 HTML 导出静态图表长图（.svg + .png）：手机预览等不执行脚本的环境可直接打开图片看全部图。"""
    if not build_combined_svg:
        return
    try:
        svg = build_combined_svg(data)
    except Exception as e:
        print("静态长图 SVG 生成失败（不影响 HTML）: %s" % e)
        return
    if not svg:
        return
    base, _ = os.path.splitext(out_path)
    svg_path = base + '.svg'
    with open(svg_path, 'w', encoding='utf-8') as f:
        f.write(svg)
    print("静态图表长图（SVG）: %s" % svg_path)
    png_path = base + '.png'
    try:
        try:
            import cairosvg
            cairosvg.svg2png(url=os.path.abspath(svg_path), write_to=png_path)
        except Exception:
            ql = shutil.which('qlmanage')
            sips = shutil.which('sips')
            if sips:
                # sips 按 SVG 固有宽高比栅格化（长图首选）
                subprocess.run([sips, '-s', 'format', 'png', os.path.abspath(svg_path), '--out', png_path],
                               check=True, capture_output=True, timeout=90)
            elif ql:
                m = re.search(r'height="(\d+(?:\.\d+)?)"', svg[:400])
                long_side = int(max(1000, float(m.group(1)) if m else 2400))
                tmpdir = os.path.join(os.path.dirname(os.path.abspath(out_path)) or '.', '.ql_thumb')
                os.makedirs(tmpdir, exist_ok=True)
                subprocess.run([ql, '-t', '-s', str(long_side), '-o', tmpdir, os.path.abspath(svg_path)],
                               check=True, capture_output=True, timeout=90)
                gen = os.path.join(tmpdir, os.path.basename(svg_path) + '.png')
                if os.path.exists(gen):
                    shutil.move(gen, png_path)
                shutil.rmtree(tmpdir, ignore_errors=True)
        if os.path.exists(png_path):
            print("静态图表长图（PNG）: %s" % png_path)
        else:
            print("PNG 未生成（SVG 已生成，可直接用图片查看器打开）")
    except Exception as e:
        print("PNG 导出失败（SVG 已生成，可直接打开）: %s" % e)


def echarts_scripts():
    """内嵌本地 ECharts；vendor 缺失时明确失败，绝不回退到网络资源。"""
    vendor = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'vendor', 'echarts.min.js')
    if not os.path.exists(vendor):
        raise RuntimeError('ECharts vendor 文件缺失，无法生成离线仪表盘: %s' % vendor)
    try:
        with open(vendor, encoding='utf-8') as f:
            js = f.read().replace('</script', '<\\/script')
    except Exception as e:
        raise RuntimeError('ECharts vendor 文件读取失败: %s' % e) from e
    return '<script>/* ECharts 5.5.1 (inlined; offline only) */\n' + js + '\n</script>'


def main():
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("--data", required=True, help="dashboard_data.json（接口见 references/visualizations.md）")
    ap.add_argument("--out", required=True, help="输出 HTML 路径")
    a = ap.parse_args()
    try:
        with open(a.data, encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        print("读取数据失败: %s" % e)
        sys.exit(1)
    for key in ("topic", "scopes", "trend_all", "compare"):
        if key not in data:
            print("数据缺字段: %s（接口约定见 references/visualizations.md）" % key)
            sys.exit(1)
    if "all" not in data["scopes"]:
        print("scopes 必须含 all（不限年限）范围")
        sys.exit(1)
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    static_html = ''
    if build_static_charts:
        try:
            static_html = build_static_charts(data)
        except Exception as e:
            print("静态图表生成失败（已降级为文字版）: %s" % e)
    static_html += build_static(data)
    page = (TEMPLATE.replace("__TOPIC__", str(data["topic"]).replace("<", "&lt;"))
            .replace("__ECHARTS_SCRIPTS__", echarts_scripts())
            .replace("__STATIC__", static_html)
            .replace("__DATA__", payload))
    with open(a.out, "w", encoding="utf-8") as f:
        f.write(page)
    export_static_files(data, a.out)
    scopes = ", ".join("%s(%s)" % (k, v.get("label", "")) for k, v in data["scopes"].items())
    print("仪表盘已生成: %s" % a.out)
    print("范围: %s；图: 总体趋势/主题分布/比较分析/引用网络/因素→结局影响关系/方法思维导图/语义关系" % scopes)


if __name__ == "__main__":
    main()