#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build_desktop_premium.py — 电脑端"满血版"仪表盘（深色科技风，单文件 HTML）。

- ECharts 内嵌（vendor/echarts.min.js），无需联网
- 动效全开、力导向网络、渐变/辉光/玻璃卡片视觉
- 六类图 + 双范围切换 + ⑤桑基图（无连线文字，点击结点/色带看详情）、⑦点击放大聚焦（仅选中项发光）并查看论文面板
- 数据接口同 build_dashboard.py（dashboard_data.json）

用法:
  python3 build_desktop_premium.py --data dashboard_data.json --out desktop.html
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_dashboard import echarts_scripts

TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="only light">
<title>__TOPIC__ · 满血版</title>
__ECHARTS__
<style>
:root{
  --site-bg:#070c16; --site-fg:#e2e8f0; --site-accent:#38bdf8; --site-on-accent:#04121f;
  --site-surface:rgba(17,26,45,.72); --site-muted:#8fa3bf; --site-border:rgba(148,163,184,.18);
  --site-font:'PingFang SC','Hiragino Sans GB','Microsoft YaHei',sans-serif;
  --site-radius:14px; --site-space:1; --site-type:1;
}
*{box-sizing:border-box}
html,body{margin:0;color:var(--site-fg);font-family:var(--site-font);
  background:
    radial-gradient(1200px 600px at 85% -10%, rgba(56,189,248,.16), transparent 60%),
    radial-gradient(900px 500px at 5% 10%, rgba(167,139,250,.12), transparent 55%),
    radial-gradient(1100px 700px at 50% 115%, rgba(52,211,153,.08), transparent 60%),
    var(--site-bg);
  background-attachment:fixed;}
body:before{content:'';position:fixed;inset:0;pointer-events:none;opacity:.35;
  background-image:linear-gradient(rgba(148,163,184,.05) 1px, transparent 1px),
                   linear-gradient(90deg, rgba(148,163,184,.05) 1px, transparent 1px);
  background-size:44px 44px;}
header{position:relative;padding:calc(34px * var(--site-space,1)) calc(36px * var(--site-space,1)) calc(18px * var(--site-space,1));}
.badge{display:inline-flex;align-items:center;gap:8px;font-size:12px;letter-spacing:.18em;color:#7dd3fc;
  text-transform:uppercase;border:1px solid rgba(125,211,252,.35);border-radius:999px;padding:4px 14px;
  background:rgba(56,189,248,.08)}
header h1{margin:14px 0 6px;font-size:calc(34px * var(--site-type,1));font-weight:800;letter-spacing:.5px;
  background:linear-gradient(92deg,#f8fbff 10%, #7dd3fc 50%, #a78bfa 90%);-webkit-background-clip:text;background-clip:text;color:transparent;}
header .sub{color:var(--site-muted);font-size:14px}
.kpis{display:flex;gap:14px;flex-wrap:wrap;margin-top:18px}
.kpi{background:var(--site-surface);border:1px solid var(--site-border);border-radius:var(--site-radius);
  padding:14px 20px;min-width:150px;backdrop-filter:blur(10px);box-shadow:0 10px 30px rgba(2,8,20,.45);
  position:relative;overflow:hidden}
.kpi:before{content:'';position:absolute;inset:0 auto auto 0;width:100%;height:2px;
  background:linear-gradient(90deg,#38bdf8,#a78bfa,transparent)}
.kpi b{display:block;font-size:24px;font-weight:800;color:#f8fbff}
.kpi span{color:var(--site-muted);font-size:12px}
.tabs{position:sticky;top:0;z-index:20;display:flex;gap:10px;align-items:center;flex-wrap:wrap;
  padding:12px calc(36px * var(--site-space,1));
  background:rgba(7,12,22,.78);backdrop-filter:blur(14px);border-bottom:1px solid var(--site-border)}
.tabs button{cursor:pointer;border-radius:999px;border:1px solid var(--site-border);background:rgba(30,41,59,.5);
  color:#cbd5e1;padding:7px 18px;font-size:14px;transition:all .2s}
.tabs button.on{background:linear-gradient(90deg,#0ea5e9,#6366f1);border-color:transparent;color:#fff;
  box-shadow:0 6px 20px rgba(56,189,248,.35)}
.tabs .note{color:var(--site-muted);font-size:12px;margin-left:8px}
main{padding:calc(22px * var(--site-space,1)) calc(36px * var(--site-space,1)) 50px;position:relative}
.card{background:var(--site-surface);border:1px solid var(--site-border);border-radius:var(--site-radius);
  margin-bottom:calc(20px * var(--site-space,1));backdrop-filter:blur(12px);box-shadow:0 14px 40px rgba(2,8,20,.5);
  overflow:hidden}
.card h2{display:flex;align-items:baseline;gap:10px;margin:0;padding:16px 22px 0;font-size:17px;color:#f1f5f9}
.card h2 small{color:var(--site-muted);font-size:12px;font-weight:400}
.card .desc{padding:6px 22px 0;color:#7c8db0;font-size:12px}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:calc(20px * var(--site-space,1))}
@media (max-width: 1100px){ .grid2{grid-template-columns:1fr} }
.chart{width:100%;height:430px}
.chart.tall{height:560px}
.flex{display:flex;gap:0}
.flex .chart{flex:1;min-width:0}
.panel{width:340px;border-left:1px solid var(--site-border);padding:14px 16px;font-size:13px;line-height:1.7;
  overflow-y:auto;max-height:560px;background:rgba(10,16,30,.55);color:#cbd5e1}
.panel h3{margin:0 0 8px;font-size:14px;color:#7dd3fc}
.panel .meta{color:var(--site-muted);font-size:12px}
.panel a{color:#7dd3fc;word-break:break-all}
.panel ul{margin:6px 0;padding-left:18px}
.toolbar{padding:8px 22px 0;display:flex;gap:8px;align-items:center;flex-wrap:wrap;font-size:13px;color:#94a3b8}
.toolbar button{cursor:pointer;border-radius:999px;border:1px solid var(--site-border);background:rgba(30,41,59,.45);
  color:#cbd5e1;padding:4px 14px;font-size:12px}
.toolbar button.on{background:rgba(56,189,248,.2);border-color:rgba(56,189,248,.5);color:#e0f2fe}
.zoomctl{display:inline-flex;align-items:center;border:1px solid var(--site-border);border-radius:999px;
  background:rgba(30,41,59,.45);overflow:hidden}
.zoomctl button{border:0;border-radius:0;background:transparent;color:#cbd5e1;padding:4px 10px;font-size:14px;line-height:1.1}
.zoomctl button:hover{background:rgba(56,189,248,.16);color:#e0f2fe}
.zoomctl .zoomCap{font-size:11px;color:#7c8db0;padding:0 2px 0 10px;white-space:nowrap}
.zoomctl .zoomVal{min-width:46px;text-align:center;font-size:11px;font-weight:600;color:#7dd3fc;
  font-variant-numeric:tabular-nums;padding:0 2px}
.empty{padding:50px;text-align:center;color:#64748b}
.summarycard{padding:18px 22px;font-size:14px;line-height:2;color:#cbd5e1}
.summarycard b{color:#e0f2fe}
@keyframes panelIn{0%{opacity:0;transform:translateX(30px) scale(.95);box-shadow:0 0 0 rgba(56,189,248,0)}55%{opacity:1;transform:translateX(-5px) scale(1.005);box-shadow:0 0 32px rgba(56,189,248,.5)}100%{opacity:1;transform:none;box-shadow:none}}
.panel{position:relative;overflow:hidden}
.panel.pulse{animation:panelIn .65s cubic-bezier(.22,1,.36,1)}
.panel.pulse:before{content:'';position:absolute;inset:0;pointer-events:none;background:linear-gradient(115deg,transparent 20%,rgba(125,211,252,.20) 45%,transparent 70%);transform:translateX(-130%);animation:panelSweep .85s ease .08s}
@keyframes panelSweep{to{transform:translateX(130%)}}
@keyframes hueIn{0%{color:#a78bfa;text-shadow:0 0 16px rgba(167,139,250,.95)}100%{color:#7dd3fc;text-shadow:none}}
.panel.pulse h3{animation:hueIn .75s ease}
@keyframes contentIn{0%{opacity:0;transform:translateY(10px);filter:blur(3px)}100%{opacity:1;transform:none;filter:none}}
.panel.pulse > div,.panel.pulse > ul{animation:contentIn .6s cubic-bezier(.22,1,.36,1) both}
@keyframes textIn{0%{opacity:0;transform:translateX(-8px)}100%{opacity:1;transform:none}}
.panel.pulse li{animation:textIn .5s both}
.panel.pulse li:nth-child(1){animation-delay:.06s}
.panel.pulse li:nth-child(2){animation-delay:.10s}
.panel.pulse li:nth-child(3){animation-delay:.14s}
.panel.pulse li:nth-child(4){animation-delay:.18s}
.panel.pulse li:nth-child(5){animation-delay:.22s}
.panel.pulse li:nth-child(6){animation-delay:.26s}
.panel.pulse li:nth-child(7){animation-delay:.30s}
.panel.pulse li:nth-child(8){animation-delay:.34s}
.panel.pulse li:nth-child(n+9){animation-delay:.38s}
.chart{position:relative}
/* 范围切换时的交叉淡入淡出：旧帧快照淡出 + 新帧淡入上浮（桑基图重排不再"硬切"） */
.chart .kgGhost{position:absolute;left:0;top:0;width:100%;height:100%;z-index:4;pointer-events:none;
  will-change:opacity,transform;animation:kgGhostOut .5s cubic-bezier(.4,0,.2,1) forwards}
@keyframes kgGhostOut{0%{opacity:1;transform:none}38%{opacity:.3}100%{opacity:0;transform:scale(1.016)}}
.chart.kgSwap canvas{animation:kgIn .56s cubic-bezier(.22,1,.36,1) both}
@keyframes kgIn{0%{opacity:.2;transform:translateY(8px) scale(.992)}60%{opacity:.92}100%{opacity:1;transform:none}}
.chart.replayflash:after{content:'';position:absolute;inset:0;pointer-events:none;border-radius:10px;background:radial-gradient(circle at 50% 40%,rgba(125,211,252,.18),transparent 62%);animation:chartFlash .9s ease}
@keyframes chartFlash{0%{opacity:0}30%{opacity:1}100%{opacity:0}}
.scopebar{position:sticky;top:0;z-index:20;display:flex;gap:10px;align-items:center;flex-wrap:wrap;
  padding:10px 14px;margin:0 0 calc(20px * var(--site-space,1));
  background:rgba(7,12,22,.86);border:1px solid var(--site-border);border-radius:var(--site-radius);backdrop-filter:blur(12px)}
.scopebar .note{color:var(--site-muted);font-size:12px;margin-left:6px}
.slideCtl{position:fixed;right:18px;bottom:18px;z-index:60;display:flex;align-items:center;gap:10px;
  padding:8px 10px;border:1px solid var(--site-border);border-radius:999px;background:rgba(7,12,22,.84);
  backdrop-filter:blur(14px);box-shadow:0 10px 30px rgba(2,8,20,.55);font-size:12px;color:var(--site-muted)}
.slideCtl button{cursor:pointer;border-radius:999px;border:1px solid var(--site-border);
  background:rgba(30,41,59,.5);color:#cbd5e1;padding:5px 12px;font-size:12px}
.slideCtl button.on{background:rgba(56,189,248,.2);border-color:rgba(56,189,248,.5);color:#e0f2fe}
.slideCtl .pos{min-width:44px;text-align:center;color:#7dd3fc;font-variant-numeric:tabular-nums}
.slideCtl .hint{color:var(--site-muted)}
.card{scroll-margin-top:96px}
@media (max-width:820px){
  .slideCtl{right:10px;bottom:10px;padding:6px 8px}
  .slideCtl .hint{display:none}
  header{padding:18px 16px 8px}
  header h1{font-size:calc(24px * var(--site-type,1))}
  .kpis{gap:10px}
  .kpi{min-width:44%;padding:12px 14px}
  main{padding:12px 10px 30px}
  .grid2{grid-template-columns:1fr}
  .flex{flex-direction:column}
  .flex .chart{flex:0 0 auto;width:100%}
  .panel{width:auto;max-height:300px;border-left:none;border-top:1px solid var(--site-border)}
  .card h2{flex-wrap:wrap;row-gap:4px}
  .toolbar{flex-wrap:wrap}
  .chart{height:360px}
  .chart.tall{height:460px}
  .toolbar button{padding:6px 14px;font-size:13px}
  .panel{max-height:280px}
  .kpi b{font-size:20px}
}
footer{color:#5b6b85;font-size:12px;text-align:center;padding:10px 0 40px;position:relative}
</style>
</head>
<body>
<header>
  <div class="badge">Literature Landscape · Full-Power Edition</div>
  <h1 id="pageTitle"></h1>
  <div class="sub" id="subLine"></div>
  <div class="kpis" id="kpis"></div>
</header>
<div class="tabs" id="tabs"></div>
<main>
  <div class="card"><h2>分布总览 <small>先总后分：先读文字结论，再看下方各图</small></h2>
    <div class="summarycard" id="summary"></div></div>
  <div class="card"><h2>总体趋势 <small>不限年限 · 全量命中聚合（固定口径，不随下方范围切换）</small></h2><div id="trend" class="chart"></div></div>
  <div class="card"><h2>比较分析 <small>不限年限 · 前 4 主题年度趋势（固定口径，不随下方范围切换）</small></h2><div id="compare" class="chart"></div></div>
  <div class="tabs scopebar" id="tabs"></div>
  <div class="card"><h2>主题分布 <small id="topicsScope"></small></h2>
    <div class="toolbar">图形：<button id="btnPie" class="on">饼图</button><button id="btnBar">柱图</button>
      <span style="margin-left:16px">显示数量：</span><button data-n="10">10</button><button data-n="20" class="on">20</button><button data-n="30">30</button><button data-n="40">40</button></div>
    <div id="topics" class="chart tall"></div></div>
  <div class="card"><h2>文章引用关系网络 <small id="netScope"></small></h2>
    <div class="desc">球越大=被引越多，大球带作者-年份标注；点结点查看论文详情与池内引文关系</div>
    <div class="toolbar"><button id="btnNetLabels">显示全部标注</button><button id="btnNetReset">重置视图</button><span class="zoomctl" title="点按手动缩放，不依赖手势"><span class="zoomCap">点按缩放</span><button class="zoomBtn" data-chart="network" data-step="-0.1" aria-label="缩小">−</button><b class="zoomVal" data-chart="network">100%</b><button class="zoomBtn" data-chart="network" data-step="0.1" aria-label="放大">＋</button></span><button class="roamToggle" data-chart="network">手势缩放：关</button></div>
    <div class="flex"><div id="network" class="chart tall"></div><div class="panel" id="netPanel"><h3>结点详情</h3>点击左侧网络中的结点查看。</div></div></div>
  <div class="card"><h2>因素 → 结局 影响关系图谱 <small id="kgScope"></small></h2>
    <div class="desc">左列=因素、右列=结局；有链式关系时自动加中间列（桑基图）；绿带=正向、红带=负向，带宽=支撑文献数；点击结点或色带看右侧论文详情（再点取消）</div>
    <div class="toolbar"><button id="btnKgReset">重置视图</button></div>
    <div class="flex"><div id="knowledge" class="chart tall"></div><div class="panel" id="kgPanel"><h3>关系详情</h3>点击左侧图谱中的结点或色带查看。</div></div></div>
  <div class="card"><h2>研究方法思维导图 <small id="mmScope"></small></h2>
    <div class="desc">方法 = 数据获取 × 分析技术（先立判定卡：研究主题/比较对象不计入）；名称后=篇数；点结点看论文</div>
    <div class="toolbar"><span class="zoomctl" title="点按手动缩放，不依赖手势"><span class="zoomCap">点按缩放</span><button class="zoomBtn" data-chart="methods" data-step="-0.1" aria-label="缩小">−</button><b class="zoomVal" data-chart="methods">100%</b><button class="zoomBtn" data-chart="methods" data-step="0.1" aria-label="放大">＋</button></span><button class="roamToggle" data-chart="methods">手势缩放：关</button><button id="btnMmReset">重置视图</button></div>
    <div class="flex"><div id="methods" class="chart tall"></div><div class="panel" id="mmPanel"><h3>方法论文</h3>点击左侧结点查看使用该方法的论文。</div></div></div>
  <div class="card"><h2>语义关系图谱 <small>支持 / 改进 / 冲突 / 差异；圆圈=检索池论文</small></h2>
    <div class="desc" id="relDesc">连线颜色=关系类型；点圆点或连线看论文与摘要证据；冲突/差异为分析判断。</div>
    <div class="toolbar" id="relLegend"></div>
    <div class="toolbar"><span class="zoomctl" title="点按手动缩放，不依赖手势"><span class="zoomCap">点按缩放</span><button class="zoomBtn" data-chart="relations" data-step="-0.1" aria-label="缩小">−</button><b class="zoomVal" data-chart="relations">100%</b><button class="zoomBtn" data-chart="relations" data-step="0.1" aria-label="放大">＋</button></span><button class="roamToggle" data-chart="relations">手势缩放：关</button><button id="btnRelReset">重置视图</button></div>
    <div class="flex"><div id="relations" class="chart tall"></div><div class="panel" id="relPanel"><h3>关系详情</h3>点击圆点或连线查看关系与摘要证据。</div></div></div>
</main>
<div class="slideCtl" id="slideCtl">
  <button id="btnSlide" class="on">幻灯片滚动：开</button>
  <span class="pos" id="slidePos">1 / 1</span>
  <span class="hint">滚轮一格切图；长图内自由滚动</span>
</div>
<footer id="foot"></footer>
<script>
const DATA = __DATA__;
const state = {scope:'all', pie:true, topn:20, netAllLabels:false, netFocus:null, kgFocus:null, kgEdge:null, mmFocus:null, relFocus:null, relEdge:null, roam:{network:false, knowledge:false, methods:false, relations:false}, zoom:{network:1, knowledge:1, methods:1, relations:1}};
function isNarrow(){ return window.innerWidth <= 820; }
function NA(v){ return isNarrow() ? Math.min(600, v) : v; }
function NB(v){ return isNarrow() ? Math.min(10, v) : v; }
const charts = {};
function syncZoom(id){
  document.querySelectorAll('.zoomVal[data-chart="'+id+'"]').forEach(function(el){
    el.textContent=Math.round((state.zoom[id]||1)*100)+'%';
  });
}
function zoomBy(id,delta){
  const next=Math.max(0.5,Math.min(3,Math.round(((state.zoom[id]||1)+delta)*10)/10));
  state.zoom[id]=next; syncZoom(id);
  if(id==='network') renderNetwork();
  else if(id==='knowledge') renderKnowledge();
  else if(id==='methods') renderMethods();
  else if(id==='relations') renderRelations();
}
const AX = {axisLine:{lineStyle:{color:'rgba(148,163,184,.35)'}}, axisLabel:{color:'#94a3b8'},
  splitLine:{lineStyle:{color:'rgba(148,163,184,.12)', type:'dashed'}}};
function mk(id){ if(!window.echarts) return null;
  const el=document.getElementById(id);
  if(el && el.querySelector('.empty')) el.innerHTML='';
  if(!charts[id]) charts[id] = echarts.init(el, null, {devicePixelRatio: Math.min(window.devicePixelRatio || 1, 2)});
  return charts[id]; }
function empty(id,msg){ const el=document.getElementById(id); el.innerHTML='<div class="empty">'+msg+'</div>'; if(charts[id]){charts[id].dispose(); delete charts[id];} }
function esc(s){ return String(s==null?'':s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }
function zh(x){ return x.name_zh || x.name; }
function biName(n,en){ return en && en!==n ? esc(n)+'（'+esc(en)+'）' : esc(n); }
function scope(){ return DATA.scopes[state.scope]; }
function paperList(arr){
  if(!arr || !arr.length) return '<div class="meta">无关联论文</div>';
  return '<ul>'+arr.map(x=>{
    if(typeof x==='string') return '<li>'+esc(x)+'</li>';
    return '<li>['+(x.ref==null?'-':x.ref)+'] '+esc(x.label||'')+(x.title?'：'+esc(x.title):'')+(x.url?' <a href="'+esc(x.url)+'" target="_blank">原文</a>':'')+'</li>';
  }).join('')+'</ul>';
}
function paperShort(x){
  if(typeof x==='string') return x;
  const lab=x.label||'', nm=lab.split(',')[0].trim(), m=lab.match(/\d{4}/);
  return '['+(x.ref==null?'-':x.ref)+'] '+nm+(m?' '+m[0]:'');
}
function shortNodeLabel(lab){
  lab=lab||'';
  const nm=lab.split(',')[0].trim(), m=lab.match(/\d{4}/);
  return nm+(m?' '+m[0]:'');
}
function edgePapersText(arr){
  const ls=(arr||[]).map(paperShort), out=[];
  for(let i=0;i<ls.length;i+=2){ out.push(ls.slice(i,i+2).join('、')); }
  return out.join('\n');
}
function pulsePanel(id){
  const el=document.getElementById(id); if(!el) return;
  el.classList.remove('pulse'); void el.offsetWidth; el.classList.add('pulse');
}
function flashChart(id){
  const el=document.getElementById(id); if(!el) return;
  el.classList.remove('replayflash'); void el.offsetWidth; el.classList.add('replayflash');
  setTimeout(function(){ el.classList.remove('replayflash'); }, 1000);
}
function motionOK(){ return !(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches); }
// 切换范围前先抓当前帧快照，重绘后作为"幽灵层"淡出，新图同时淡入，避免整块重排的硬切
function chartSnapshot(id){
  const inst=charts[id]; if(!inst||!motionOK()) return '';
  try{ return inst.getDataURL({type:'png',pixelRatio:1,backgroundColor:'transparent'})||''; }catch(e){ return ''; }
}
function chartCrossfade(id,url){
  const el=document.getElementById(id); if(!el||!url) return;
  el.querySelectorAll('.kgGhost').forEach(function(n){ n.remove(); });
  const token=el.__kgSeq=(el.__kgSeq||0)+1;
  const img=document.createElement('img');
  img.className='kgGhost'; img.alt=''; img.src=url;
  el.appendChild(img);
  el.classList.remove('kgSwap'); void el.offsetWidth; el.classList.add('kgSwap');
  const dropGhost=function(){ img.remove(); };
  img.addEventListener('animationend',dropGhost,{once:true});
  // 幽灵层先撤，新帧动画跑完再摘 class（中途摘会截断淡入）
  setTimeout(function(){ if(el.__kgSeq===token) el.classList.remove('kgSwap'); }, 700);
  setTimeout(dropGhost,950);
}

document.getElementById('pageTitle').textContent = DATA.topic || '文献图谱仪表盘';
document.getElementById('subLine').textContent = '数据：' + (DATA.sources||'') + ' ｜ 检索条件：' + (DATA.condition||'') + ' ｜ 生成日期：' + (DATA.generated_at||'');
(function(){
  const all = DATA.scopes.all || {};
  const tr = DATA.trend_all || [];
  let peak = null; tr.forEach(x => { if(!peak || x.count > peak.count) peak = x; });
  const chips = [
    ['总命中', (all.total_hits||0) + ' 篇'],
    ['池内论文', (all.pool_count||0) + ' 篇'],
    ['主题分组', ((all.topics||[]).length) + ' 类'],
    ['趋势峰值', peak ? (peak.year + '（' + peak.count + ' 篇）') : '-']
  ];
  document.getElementById('kpis').innerHTML = chips.map(c=>'<div class="kpi"><b>'+esc(c[1])+'</b><span>'+esc(c[0])+'</span></div>').join('');
})();
(function buildTabs(){
  const t=document.getElementById('tabs');
  Object.keys(DATA.scopes).forEach(k=>{
    const b=document.createElement('button'); b.textContent=DATA.scopes[k].label; b.dataset.scope=k;
    if(k===state.scope) b.classList.add('on');
    b.onclick=()=>{ state.scope=k; t.querySelectorAll('button').forEach(x=>x.classList.toggle('on',x.dataset.scope===k)); renderScope(); };
    t.appendChild(b);
  });
  const n=document.createElement('span'); n.className='note';
  n.textContent='以下四张图随范围联动：主题分布 / 引用网络 / 因素→结局图谱 / 方法导图；总体趋势与比较分析固定为不限年限。'; t.appendChild(n);
})();

function renderTrend(){
  const g=DATA.trend_all||[];
  if(!g.length){ empty('trend','无年度趋势数据'); return; }
  mk('trend').setOption({
    backgroundColor:'transparent',
    animationDuration:NA(1400), animationEasing:'cubicInOut',
    tooltip:{trigger:'axis', backgroundColor:'rgba(15,23,42,.92)', borderColor:'rgba(56,189,248,.4)', textStyle:{color:'#e2e8f0'}},
    grid:{left:60,right:30,top:30,bottom:36},
    xAxis:Object.assign({type:'category',data:g.map(x=>x.year),boundaryGap:false},AX),
    yAxis:Object.assign({type:'value',name:'发文量',nameTextStyle:{color:'#94a3b8'}},AX),
    series:[{type:'line',data:g.map(x=>x.count),smooth:true,symbol:'circle',symbolSize:7,
      lineStyle:{width:3,color:'#38bdf8',shadowColor:'rgba(56,189,248,.55)',shadowBlur:NB(16)},
      itemStyle:{color:'#7dd3fc',borderColor:'#0ea5e9',borderWidth:2},
      areaStyle:{color:new echarts.graphic.LinearGradient(0,0,0,1,[{offset:0,color:'rgba(56,189,248,.45)'},{offset:1,color:'rgba(56,189,248,0)'}])}},
      {type:'effectScatter',data:g.length?[[g[g.length-1].year,g[g.length-1].count]]:[],symbolSize:10,
        rippleEffect:{scale:4.5,brushType:'stroke'},itemStyle:{color:'#7dd3fc',shadowColor:'rgba(125,211,252,.8)',shadowBlur:NB(12)}}]
  },true);
}
function renderTopics(){
  const sc=scope();
  document.getElementById('topicsScope').textContent='范围：'+sc.label+'（命中 '+(sc.total_hits||0)+' 篇）';
  const g=(sc.topics||[]).slice(0,state.topn);
  if(!g.length){ empty('topics','该范围无主题分布数据'); return; }
  const total=g.reduce((s,x)=>s+x.count,0);
  const pal=['#38bdf8','#a78bfa','#34d399','#f59e0b','#f472b6','#60a5fa','#facc15','#2dd4bf','#fb7185','#818cf8','#4ade80','#e879f9'];
  const narrow=(document.getElementById('topics').clientWidth||900)<700;
  const pcx=narrow?'50%':'38%';
  const opt={backgroundColor:'transparent',
    animationDuration:NA(1200), animationEasing:state.pie?'elasticOut':'cubicOut',
    tooltip:{trigger:'item', backgroundColor:'rgba(15,23,42,.92)', borderColor:'rgba(56,189,248,.4)', textStyle:{color:'#e2e8f0'},
      formatter:p=>biName(p.name,p.data.en)+'：'+p.value+' 篇'},
    legend:narrow
      ?{type:'scroll',orient:'horizontal',left:'center',bottom:0,textStyle:{color:'#94a3b8',fontSize:11}}
      :{type:'scroll',orient:'vertical',right:8,top:16,bottom:16,textStyle:{color:'#94a3b8',fontSize:11}}};
  if(state.pie){
    const gradPairs=[['#7dd3fc','#0ea5e9'],['#fcd34d','#d97706'],['#6ee7b7','#059669'],['#c4b5fd','#7c3aed'],
      ['#fda4af','#e11d48'],['#fde68a','#b45309'],['#5eead4','#0d9488'],['#a5b4fc','#4f46e5'],
      ['#f9a8d4','#be185d'],['#bef264','#4d7c0f'],['#fdba74','#c2410c'],['#93c5fd','#1d4ed8']];
    const sliceColor=i=>new echarts.graphic.LinearGradient(0,0,0,1,[
      {offset:0,color:gradPairs[i%12][0]},{offset:1,color:gradPairs[i%12][1]}]);
    const topicsEl=document.getElementById('topics');
    const titleTop=Math.round((topicsEl.clientHeight||460)*(narrow?0.405:0.51)-14);
    opt.title={
      text:String(total),subtext:'篇命中',left:pcx,top:titleTop,padding:0,
      textAlign:'center',textVerticalAlign:'middle',itemGap:2,
      textStyle:{color:'#e0f2fe',fontSize:24,fontWeight:'bold',fontFamily:'PingFang SC, sans-serif',lineHeight:26},
      subtextStyle:{color:'#7c8db0',fontSize:12,fontFamily:'PingFang SC, sans-serif',lineHeight:14}};
    opt.series=[
      {type:'pie',radius:['34%','68%'],center:[pcx,narrow?'43%':'53.5%'],silent:true,z:1,
        label:{show:false},labelLine:{show:false},
        itemStyle:{borderWidth:0,opacity:.45},
        data:g.map(x=>({name:zh(x),value:x.count,itemStyle:{color:'rgba(8,15,30,.95)'}}))},
      {type:'pie',radius:['30%','64%'],center:[pcx,narrow?'40.5%':'51%'],z:2,
        animationType:'scale',animationDelay:(i)=>i*45,
        itemStyle:{borderColor:'#0b1220',borderWidth:2,shadowColor:'rgba(56,189,248,.4)',shadowBlur:NB(16)},
        label:{color:'#cbd5e1',formatter:p=>p.value+'（'+(Math.round(p.value/total*1000)/10)+'%）'},
        labelLine:{lineStyle:{color:'rgba(148,163,184,.4)'}},
        data:g.map((x,i)=>({name:zh(x),en:x.name,value:x.count,itemStyle:{color:sliceColor(i)}}))}];
  }else{
    opt.grid={left:8,right:70,top:10,bottom:10,containLabel:true};
    opt.xAxis=Object.assign({type:'value'},AX);
    opt.yAxis=Object.assign({type:'category',inverse:true,data:g.map(x=>zh(x)),axisLabel:{color:'#94a3b8',width:150,overflow:'truncate'}},{axisLine:{lineStyle:{color:'rgba(148,163,184,.35)'}}});
    opt.series=[{type:'bar',data:g.map((x,i)=>({value:x.count,itemStyle:{borderRadius:[0,8,8,0],
        color:new echarts.graphic.LinearGradient(0,0,1,0,[{offset:0,color:'rgba(56,189,248,.25)'},{offset:1,color:pal[i%pal.length]}])}})),
      animationDelay:(i)=>i*30,
      label:{show:true,position:'right',color:'#94a3b8'}}];
  }
  mk('topics').setOption(opt,true);
}
document.getElementById('btnPie').onclick=()=>{state.pie=true;document.getElementById('btnPie').classList.add('on');document.getElementById('btnBar').classList.remove('on');renderTopics();};
document.getElementById('btnBar').onclick=()=>{state.pie=false;document.getElementById('btnBar').classList.add('on');document.getElementById('btnPie').classList.remove('on');renderTopics();};
document.querySelectorAll('.toolbar button[data-n]').forEach(b=>b.onclick=()=>{
  state.topn=+b.dataset.n;
  document.querySelectorAll('.toolbar button[data-n]').forEach(x=>x.classList.toggle('on',x===b));
  renderTopics();});

function renderCompare(){
  const cs=DATA.compare||[];
  if(!cs.length){ empty('compare','无比较分析数据'); return; }
  const ys=new Set(); cs.forEach(c=>(c.series||[]).forEach(x=>ys.add(x.year)));
  const years=Array.from(ys).sort((a,b)=>a-b);
  const pal=['#38bdf8','#f59e0b','#34d399','#a78bfa'];
  mk('compare').setOption({
    backgroundColor:'transparent',
    animationDuration:NA(1400), animationEasing:'cubicInOut',
    tooltip:{trigger:'axis', backgroundColor:'rgba(15,23,42,.92)', borderColor:'rgba(56,189,248,.4)', textStyle:{color:'#e2e8f0'}},
    legend:{top:4,textStyle:{color:'#94a3b8'}},
    grid:{left:56,right:24,top:44,bottom:34},
    xAxis:Object.assign({type:'category',data:years,boundaryGap:false},AX),
    yAxis:Object.assign({type:'value',name:'发文量',nameTextStyle:{color:'#94a3b8'}},AX),
    series:cs.map((c,i)=>({name:c.name_zh||c.name,type:'line',smooth:true,symbol:'circle',symbolSize:5,
      lineStyle:{width:2.4,color:pal[i%4],shadowColor:pal[i%4],shadowBlur:8},
      itemStyle:{color:pal[i%4]},
      areaStyle:{opacity:.08,color:pal[i%4]},
      data:years.map(y=>{const hit=(c.series||[]).find(x=>x.year===y);return hit?hit.count:0;})}))
  },true);
}

const BLUE='#38bdf8', RED='#fb7185', AMBER='#fbbf24';
function prelayout(nodes, edges, w, h){
  const n=nodes.length,pos=[],idx={};
  for(let i=0;i<n;i++){idx[nodes[i].id]=i;const a=2*Math.PI*i/n;pos.push([w/2+(w/3)*Math.cos(a),h/2+(h/3)*Math.sin(a)]);}
  for(let it=0;it<150;it++){
    const disp=[];for(let i=0;i<n;i++)disp.push([0,0]);
    for(let i=0;i<n;i++)for(let j=i+1;j<n;j++){
      const dx=pos[i][0]-pos[j][0],dy=pos[i][1]-pos[j][1],d2=dx*dx+dy*dy+.01,d=Math.sqrt(d2);
      const f=Math.min(80,5200/d2),ux=dx/d,uy=dy/d;
      disp[i][0]+=ux*f;disp[i][1]+=uy*f;disp[j][0]-=ux*f;disp[j][1]-=uy*f;
    }
    (edges||[]).forEach(e=>{const a=idx[e.s],b=idx[e.t];if(a==null||b==null||a===b)return;
      const dx=pos[b][0]-pos[a][0],dy=pos[b][1]-pos[a][1],d=Math.sqrt(dx*dx+dy*dy)+.01,f=.03*(d-165),ux=dx/d,uy=dy/d;
      disp[a][0]+=ux*f;disp[a][1]+=uy*f;disp[b][0]-=ux*f;disp[b][1]-=uy*f;});
    const cool=Math.max(.03,.9-it*.007);
    for(let i=0;i<n;i++){
      disp[i][0]+=(w/2-pos[i][0])*.015;disp[i][1]+=(h/2-pos[i][1])*.015;
      const dl=Math.sqrt(disp[i][0]*disp[i][0]+disp[i][1]*disp[i][1])+.01;
      pos[i][0]=Math.min(w-90,Math.max(90,pos[i][0]+disp[i][0]/dl*Math.min(dl,18)*cool));
      pos[i][1]=Math.min(h-60,Math.max(60,pos[i][1]+disp[i][1]/dl*Math.min(dl,18)*cool));
    }
  }
  return pos;
}

function renderNetwork(){
  const sc=scope();
  document.getElementById('netScope').textContent='范围：'+sc.label+'（池内 '+(sc.pool_count||0)+' 篇）';
  const net=sc.network||{nodes:[],edges:[]};
  if(!net.nodes.length){ empty('network','该范围论文池为空'); return; }
  const labelTop=new Set([...net.nodes].sort((a,b)=>(b.cited||0)-(a.cited||0)).slice(0,12).map(n=>n.id));
  const pos=prelayout(net.nodes,net.edges,900,500);
  const netAdj={};
  net.edges.forEach(e=>{ (netAdj[e.s]=netAdj[e.s]||{})[e.t]=1; (netAdj[e.t]=netAdj[e.t]||{})[e.s]=1; });
  const draw=(colors,focusId)=>mk('network').setOption({
    backgroundColor:'transparent',
    tooltip:{backgroundColor:'rgba(15,23,42,.92)',borderColor:'rgba(56,189,248,.4)',textStyle:{color:'#e2e8f0'},
      formatter:p=>p.dataType==='node'?esc(p.data.label)+'（被引 '+(p.data.cited==null?'-':p.data.cited)+'）<br>'+esc(p.data.title):esc(p.data.sLabel||'')+' 引用 '+esc(p.data.tLabel||'')},
    series:[{type:'graph',layout:'none',roam:state.roam.network,draggable:state.roam.network,
      zoom:(focusId?1.25:1)*(state.zoom.network||1),scaleLimit:{min:0.5,max:3},
      animationDuration:NA(900), animationEasing:'elasticOut', animationDelay:(idx)=>100+idx*15,
      label:{show:true,fontSize:11,color:'#cbd5e1'},labelLayout:{hideOverlap:true},
      data:net.nodes.map((n,i)=>{
        const isF=!!focusId && n.id===focusId;
        const nb=!!focusId && !!(netAdj[focusId]||{})[n.id];
        let size=(10+8*Math.log(1+(n.cited||0)))*(net.nodes.length>24?0.75:1);
        if(isF) size*=1.9; else if(nb) size*=1.15;
        return Object.assign({},n,{x:pos[i][0],y:pos[i][1],symbolSize:size,
          label:{show:isF||nb||state.netAllLabels||labelTop.has(n.id),
            formatter:state.netAllLabels?shortNodeLabel(n.label):(n.label||''),
            fontSize:isF?14:(state.netAllLabels?9:11),fontWeight:isF?700:400,
            color:isF?'#f8fbff':'#cbd5e1'},
          itemStyle:{color:(colors&&colors[n.id])||BLUE,opacity:focusId?(isF?1:(nb?.95:.15)):1,
            shadowColor:'rgba(125,211,252,.95)',shadowBlur:isF?NB(32):0}});
      }),
      links:net.edges.map(e=>{
        const rel=!!focusId && (e.s===focusId||e.t===focusId);
        return Object.assign({},e,{source:e.s,target:e.t,
          lineStyle:{color:rel?'rgba(125,211,252,.9)':'rgba(148,163,184,.3)',width:rel?2.2:1.2,curveness:.08,
            opacity:focusId?(rel?1:.1):1}});
      }),
      emphasis:{focus:'adjacency',lineStyle:{width:2.4,color:'rgba(125,211,252,.8)'}}}]
  },true);
  draw(null, state.netFocus);
  const lblBtn=document.getElementById('btnNetLabels');
  lblBtn.classList.toggle('on',state.netAllLabels);
  lblBtn.textContent=state.netAllLabels?'仅大球标注':'显示全部标注';
  lblBtn.onclick=()=>{state.netAllLabels=!state.netAllLabels;renderNetwork();};
  const rstBtn=document.getElementById('btnNetReset');
  if(rstBtn) rstBtn.onclick=()=>{state.netFocus=null;state.zoom.network=1;syncZoom('network');renderNetwork();};
  const byId={};net.nodes.forEach(n=>byId[n.id]=n);
  charts['network'].off('click');
  charts['network'].on('click',p=>{
    if(p.dataType!=='node')return;
    const id=p.data.id,colors={};
    net.edges.forEach(e=>{if(e.t===id)colors[e.s]=RED;if(e.s===id)colors[e.t]=AMBER;});
    state.netFocus=(state.netFocus===id)?null:id;
    draw(colors, state.netFocus);
    const n=byId[id];
    const citing=net.edges.filter(e=>e.t===id).map(e=>byId[e.s]).filter(Boolean);
    const cited=net.edges.filter(e=>e.s===id).map(e=>byId[e.t]).filter(Boolean);
    document.getElementById('netPanel').innerHTML='<h3>'+esc(n.label)+'</h3><div>'+esc(n.title)+'</div>'+
      '<div class="meta">'+esc(n.authors||'')+' · '+(n.year||'?')+' · 被引 '+(n.cited==null?'-':n.cited)+'</div>'+
      (n.url?'<div><a href="'+esc(n.url)+'" target="_blank">原文 / 题录链接</a></div>':'')+
      (n.excerpt?'<div style="margin-top:6px">'+esc(n.excerpt)+'</div>':'')+
      '<div style="margin-top:8px;color:'+RED+'">引用了该结点（'+citing.length+'）：</div>'+paperList(citing)+
      '<div style="color:'+AMBER+'">被该结点引用（'+cited.length+'）：</div>'+paperList(cited);
    pulsePanel('netPanel');
  });
  if(!net.edges.length) document.getElementById('netPanel').innerHTML+='<div class="meta" style="margin-top:8px">池内互引较少，以孤立结点呈现（不补边）。</div>';
}

function renderKnowledge(){
  const sc=scope();
  // 只有"切换范围"才做交叉淡入淡出；点击聚焦/缩放/滚动重播保持即时响应
  const scopeChanged=renderKnowledge._scope!==undefined && renderKnowledge._scope!==state.scope;
  renderKnowledge._scope=state.scope;
  const prevShot=scopeChanged?chartSnapshot('knowledge'):'';
  if(scopeChanged){ state.kgFocus=null; state.kgEdge=null; }
  document.getElementById('kgScope').textContent='范围：'+sc.label;
  const kg=sc.knowledge||{nodes:[],edges:[]};
  if(!kg.nodes.length){ empty('knowledge','该范围未能凝练出可核验的影响关系（不硬造）'); chartCrossfade('knowledge',prevShot); return; }
  const krBtn=document.getElementById('btnKgReset');
  if(krBtn) krBtn.onclick=()=>{state.kgFocus=null;state.kgEdge=null;state.zoom.knowledge=1;syncZoom('knowledge');renderKnowledge();};
  const byId={};kg.nodes.forEach(n=>byId[n.id]=n);
  const factorMode=(kg.edges||[]).some(e=>e.polarity);
  if(factorMode){
    const kgFocus=state.kgFocus, kgSel=state.kgEdge;
    const kgAdj={};
    kg.edges.forEach(e=>{ (kgAdj[e.s]=kgAdj[e.s]||{})[e.t]=1; (kgAdj[e.t]=kgAdj[e.t]||{})[e.s]=1; });
    const byName={}; kg.nodes.forEach(n=>byName[n.name]=n);
    // 右侧留白按结局标签实际长度自适应（固定 330 会在结局名较短时留下大片空白）
    const maxOutLen=Math.max(6,...kg.nodes.filter(n=>n.type==='outcome').map(n=>String(n.name||'').length));
    const kgRight=isNarrow()?Math.min(150,24+maxOutLen*10):Math.min(280,30+maxOutLen*12);
    const kgEl=document.getElementById('knowledge');
    if(kgEl) kgEl.style.overflow='hidden';
    // 点击聚焦缩放特写：桑基不支持原生 zoom，用 canvas CSS transform 以点击点为原点缩放；取消/重置时还原
    const kgZoomTo=(p,z)=>{ const cv=kgEl&&kgEl.querySelector('canvas'); if(!cv) return;
      if(!p||p.offsetX==null||!(z>1)){ cv.style.transform=''; return; }
      cv.style.transition='transform .3s ease';
      cv.style.transformOrigin=Math.round(p.offsetX)+'px '+Math.round(p.offsetY)+'px';
      cv.style.transform='scale('+z+')'; };
    kgZoomTo(null);
    const links=kg.edges.map((e,ei)=>{
      const pos=e.polarity!=='neg';
      return {source:(byId[e.s]||{}).name||e.s,target:(byId[e.t]||{}).name||e.t,value:Math.max(1,e.support||1),
        eid:ei,polarity:e.polarity,effect:e.effect||'',support:e.support||0,
        papers:e.papers||[],disputed:!!e.disputed,
        lineStyle:{color:pos?'rgba(52,211,153,.42)':'rgba(251,113,133,.46)',opacity:1}};
    });
    links.forEach(l=>{
      const rel=!!kgFocus && (l.source===(byId[kgFocus]||{}).name||l.target===(byId[kgFocus]||{}).name);
      const isSel=!!kgSel && kgSel.i===l.eid;
      if(kgFocus) l.lineStyle.opacity=rel?1:.08;
      else if(kgSel) l.lineStyle.opacity=isSel?1:.06;
    });
    const nodes=kg.nodes.map(n=>{
      const isF=!!kgFocus && n.id===kgFocus;
      const nb=!!kgFocus && !!(kgAdj[kgFocus]||{})[n.id];
      const isEnd=!!kgSel && (n.id===kgSel.s||n.id===kgSel.t);
      const lit=isF||isEnd;
      let opacity=1;
      if(kgFocus) opacity=isF?1:(nb?.95:.16);
      else if(kgSel) opacity=isEnd?1:.18;
      // 注意：桑基结点对象不得带 id 字段——ECharts sankey 会把 id 当结点名（标签变 ID、连线按 name 匹配失败、布局塌缩到左上角）
      return {name:n.name,type:n.type,papers:n.papers||[],
        itemStyle:{color:n.type==='outcome'?'#f59e0b':BLUE,opacity:opacity,
          borderColor:lit?'#e0f2fe':'transparent',borderWidth:lit?2:0,
          shadowColor:n.type==='outcome'?'rgba(245,158,11,.95)':'rgba(125,211,252,.95)',
          shadowBlur:lit?NB(24):0},
        label:{color:lit?'#f8fbff':(opacity>.5?'#cbd5e1':'#55647c'),fontWeight:lit?700:500}};
    });
    mk('knowledge').setOption({
      backgroundColor:'transparent',
      tooltip:{backgroundColor:'rgba(15,23,42,.92)',borderColor:'rgba(56,189,248,.4)',textStyle:{color:'#e2e8f0'},
        formatter:p=>{ if(p.dataType==='node'){const n=byName[p.data.name]||{};return '<b>'+esc(n.name||'')+'</b>（'+(n.type==='outcome'?'结局':'因素')+'）<br>关联论文 '+((n.papers||[]).length)+' 篇';}
          const e=p.data||{};
          return esc(e.source||'')+' → '+esc(e.target||'')+'<br>'+(e.polarity==='neg'?'负向影响':'正向影响')+(e.effect?' · '+esc(e.effect):'')+' · 支撑 '+(e.support||0)+' 篇'+(e.disputed?'（争议）':'');}},
      series:[{type:'sankey',
        left:10,right:kgRight,top:14,bottom:14,
        nodeWidth:14,nodeGap:16,nodeAlign:'justify',layoutIterations:32,draggable:false,
        animationDuration:NA(720),animationEasing:'cubicOut',
        label:{position:'right',distance:6,align:'left',verticalAlign:'middle',fontSize:11,lineHeight:15,
          width:(isNarrow()?150:240),overflow:'break',color:'#cbd5e1',fontWeight:500},
        lineStyle:{curveness:.5},
        emphasis:{focus:'adjacency',lineStyle:{opacity:.85}},
        data:nodes,links:links}]
    },true);
    chartCrossfade('knowledge',prevShot);
    charts['knowledge'].off('click');
    charts['knowledge'].on('click',p=>{
      const panel=document.getElementById('kgPanel');
      if(p.dataType==='node'){
        const nid=(byName[p.data.name]||{}).id;
        const same=state.kgFocus===nid && !state.kgEdge;
        state.kgFocus=same?null:nid;
        state.kgEdge=null;
        renderKnowledge();
        kgZoomTo(p.event,same?1:1.5);
        const n=byId[nid]||{},rels=kg.edges.filter(e=>e.s===nid||e.t===nid);
        let html='<h3>'+(n.type==='outcome'?'结局':'因素')+'：'+esc(n.name)+'</h3><div>关联论文（'+(n.papers||[]).length+'）：</div>'+paperList(n.papers||[]);
        if(rels.length) html+='<div style="margin-top:8px">涉及关系：</div><ul>'+rels.map(e=>{
          const f=byId[e.s]||{},t=byId[e.t]||{};
          return '<li>'+esc(f.name||'')+' → '+esc(t.name||'')+'：'+(e.polarity==='neg'?'负向':'正向')+(e.effect?' · '+esc(e.effect):'')+' · '+(e.support||0)+' 篇'+(e.disputed?'（争议）':'')+'</li>';}).join('')+'</ul>';
        panel.innerHTML=html;
        pulsePanel('kgPanel');
      }else if(p.dataType==='edge'){
        const e=p.data||{};
        const same=state.kgEdge && state.kgEdge.i===e.eid;
        const sn=byName[e.source]||{},tn=byName[e.target]||{};
        state.kgEdge=same?null:{i:e.eid,s:sn.id,t:tn.id};
        state.kgFocus=null;
        renderKnowledge();
        kgZoomTo(p.event,same?1:1.3);
        panel.innerHTML='<h3>'+esc(e.source||'')+' → '+esc(e.target||'')+'</h3><div>'+(e.polarity==='neg'?'负向影响（因素越强，结局越轻）':'正向影响（因素越强，结局越重）')+
          (e.effect?' · 效应量 '+esc(e.effect):'')+' · 支撑 '+(e.support||0)+' 篇'+(e.disputed?'（存在争议）':'')+'</div>'+
          '<div style="margin-top:8px">支撑论文：</div>'+paperList(e.papers||[])+'<div class="meta">每票须能在 graph_evidence.md 挂到摘要原句。点击同一色带取消选中。</div>';
        pulsePanel('kgPanel');
      }
    });
    return;
  }
  // 旧版“结论对”
  const n0=kg.nodes.length,h=Math.max(340,130+n0*80);
  const kgFocus=state.kgFocus;
  const kgAdj={};
  kg.edges.forEach(e=>{ (kgAdj[e.s]=kgAdj[e.s]||{})[e.t]=1; (kgAdj[e.t]=kgAdj[e.t]||{})[e.s]=1; });
  const cpos=kg.nodes.map((n,i)=>{const a=2*Math.PI*i/n0-Math.PI/2;return [450+280*Math.cos(a),h/2+((h-130)/2*.8)*Math.sin(a)];});
  const links=[];
  kg.edges.forEach(e=>{
    if(e.support>0) links.push({source:e.s,target:e.t,name:'支持',
      lineStyle:{color:'#34d399',width:Math.min(12,1+e.support*1.6),curveness:.15,shadowColor:'rgba(52,211,153,.9)',shadowBlur:0},
      label:{show:true,fontSize:9,lineHeight:11,color:'#6ee7b7',
        formatter:'支持×'+e.support+((e.support_papers||[]).length?'\n'+edgePapersText(e.support_papers):'')},
      support_papers:e.support_papers||[],oppose_papers:e.oppose_papers||[],s:e.s,t:e.t});
    if(e.oppose>0) links.push({source:e.s,target:e.t,name:'不支持',
      lineStyle:{color:RED,width:Math.min(12,1+e.oppose*1.6),type:'dashed',curveness:-.15,shadowColor:'rgba(251,113,133,.9)',shadowBlur:0},
      label:{show:true,fontSize:9,lineHeight:11,color:'#fda4af',
        formatter:'不支持×'+e.oppose+((e.oppose_papers||[]).length?'\n'+edgePapersText(e.oppose_papers):'')},
      support_papers:e.support_papers||[],oppose_papers:e.oppose_papers||[],s:e.s,t:e.t});
  });
  mk('knowledge').setOption({
    backgroundColor:'transparent',
    tooltip:{backgroundColor:'rgba(15,23,42,.92)',borderColor:'rgba(56,189,248,.4)',textStyle:{color:'#e2e8f0'},
      formatter:p=>p.dataType==='node'?esc(p.data.claim)+'<br>支撑文章 '+(p.data.papers||[]).length+' 篇':
        esc((byId[p.data.s]||{}).claim||'')+' → '+esc((byId[p.data.t]||{}).claim||'')+'<br>'+p.data.name+'：'+(p.data.name==='支持'?p.data.support_papers.length:p.data.oppose_papers.length)+' 篇投票'},
    series:[{type:'graph',layout:'none',roam:state.roam.knowledge,draggable:state.roam.knowledge,
      zoom:(kgFocus?1.5:1)*(state.zoom.knowledge||1),scaleLimit:{min:0.5,max:3},
      animationDuration:NA(900), animationEasing:'elasticOut', animationDelay:(idx)=>100+idx*15,
      label:{show:true,fontSize:11,color:'#e2e8f0',width:150,overflow:'break'},
      edgeSymbol:['none','arrow'],edgeSymbolSize:8,
      data:kg.nodes.map((n,i)=>{
        const isF=!!kgFocus && n.id===kgFocus;
        const nb=!!kgFocus && !!(kgAdj[kgFocus]||{})[n.id];
        let size=18+Math.min(30,(n.papers||[]).length*4);
        if(isF) size*=1.6; else if(nb) size*=1.12;
        return Object.assign({},n,{x:cpos[i][0],y:cpos[i][1],symbolSize:size,
          label:{fontSize:isF?15:11,color:isF?'#f8fbff':'#e2e8f0',fontWeight:isF?700:400},
          itemStyle:{color:BLUE,opacity:kgFocus?(isF?1:(nb?.95:.16)):1,
            shadowColor:isF?'rgba(125,211,252,.95)':'rgba(56,189,248,.6)',shadowBlur:isF?NB(30):0}});
      }),
      links:links.map(l=>{
        const rel=!!kgFocus && (l.s===kgFocus||l.t===kgFocus);
        l.lineStyle.opacity=kgFocus?(rel?1:.1):1;
        return l;
      }),
      emphasis:{focus:'adjacency'}}]
  },true);
  chartCrossfade('knowledge',prevShot);
  charts['knowledge'].off('click');
  charts['knowledge'].on('click',p=>{
    const panel=document.getElementById('kgPanel');
    if(p.dataType==='node'){
      state.kgFocus=(state.kgFocus===p.data.id)?null:p.data.id;
      renderKnowledge();
      const n=byId[p.data.id];
      panel.innerHTML='<h3>核心结论</h3><div>'+esc(n.claim)+'</div><div style="margin-top:8px">支撑文章（'+(n.papers||[]).length+'）：</div>'+paperList(n.papers||[]);
      pulsePanel('kgPanel');
    }else if(p.dataType==='edge'){
      const e=p.data,papers=e.name==='支持'?e.support_papers:e.oppose_papers;
      panel.innerHTML='<h3>'+esc(e.name)+'关系 ×'+papers.length+'</h3><div>'+esc((byId[e.s]||{}).claim||'')+' → '+esc((byId[e.t]||{}).claim||'')+'</div><div style="margin-top:8px">投票文章：</div>'+paperList(papers)+'<div class="meta">每票须能在 graph_evidence.md 挂到摘要原句。</div>';
      pulsePanel('kgPanel');
    }
  });
}

function renderMethods(){
  const sc=scope();
  document.getElementById('mmScope').textContent='范围：'+sc.label;
  const mm=sc.methods;
  if(!mm||!(mm.children||[]).length){ empty('methods','该范围无方法归类数据'); return; }
  const mrBtn=document.getElementById('btnMmReset');
  if(mrBtn) mrBtn.onclick=()=>{state.mmFocus=null;state.zoom.methods=1;syncZoom('methods');renderMethods();};
  const mmEl=document.getElementById('methods');
  if(mmEl){
    let leafCount=0; const cnt=n=>{ if(!(n.children||[]).length) leafCount++; else (n.children||[]).forEach(cnt); };
    cnt(mm);
    mmEl.style.height=Math.max(640, leafCount*48+140)+'px';
    if(charts['methods']) charts['methods'].resize();
  }
  const focusName=state.mmFocus;
  const narrow=isNarrow();
  const walk=(n,depth)=>{
    const full=n.name+(n.count!=null?'（'+n.count+'篇）':'');
    const isF=!!focusName && full===focusName;
    const isLeaf=!(n.children||[]).length;
    return {name:full,papers:n.papers||[],children:(n.children||[]).map(c=>walk(c,(depth||0)+1)),
      symbolSize:isF?16:9,
      itemStyle:isF
        ?{color:'#7dd3fc',borderColor:'#e0f2fe',borderWidth:2,shadowColor:'rgba(125,211,252,.95)',shadowBlur:NB(26)}
        :{color:BLUE,borderColor:'#0ea5e9',borderWidth:1,shadowColor:'rgba(56,189,248,.5)',shadowBlur:0,opacity:focusName?.45:1},
      label:{position:'right',distance:8,align:'left',verticalAlign:'middle',
        fontSize:isF?14:(isLeaf?11:12),fontWeight:isF?700:(isLeaf?400:600),
        color:isF?'#f8fbff':(focusName?'#8fa3bf':(isLeaf?'#94a3b8':'#cbd5e1')),
        lineHeight:16,
        width:isLeaf?(narrow?170:330):(depth===0?(narrow?110:240):(narrow?120:220)),
        overflow:'break'}};
  };
  mk('methods').setOption({
    backgroundColor:'transparent',
    tooltip:{trigger:'item',backgroundColor:'rgba(15,23,42,.92)',borderColor:'rgba(56,189,248,.4)',textStyle:{color:'#e2e8f0'},
      formatter:p=>{const arr=(p.data.papers||[]).map(x=>typeof x==='string'?x:('['+(x.ref==null?'-':x.ref)+'] '+(x.label||'')));
        const nm=String(p.name||'').replace(/（\d+篇）$/,'');return arr.length?'<b>'+esc(nm)+'</b><br>'+arr.map(esc).join('<br>'):esc(nm);}},
    series:[{type:'tree',orient:'LR',roam:state.roam.methods,zoom:(state.zoom.methods||1),scaleLimit:{min:0.5,max:3},initialTreeDepth:2,symbol:'circle',symbolSize:9,
      right:(narrow?200:370),
      left:20,
      label:{position:'right',distance:8,align:'left',verticalAlign:'middle',fontSize:12,color:'#cbd5e1',fontWeight:600},
      lineStyle:{color:'rgba(148,163,184,.35)',width:1.5},
      itemStyle:{color:BLUE,borderColor:'#0ea5e9',borderWidth:1,
        shadowColor:'rgba(56,189,248,.5)',shadowBlur:0},
      expandAndCollapse:true,animationDuration:600,animationDurationUpdate:400,
      data:[walk(mm,0)]}]
  },true);
  charts['methods'].off('click');
  charts['methods'].on('click',p=>{
    const panel=document.getElementById('mmPanel'),d=p.data||{},papers=d.papers||[];
    const nm=String(d.name||'').replace(/（\d+篇）$/,'');
    const full=String(d.name||'');
    state.mmFocus=(state.mmFocus===full)?null:full;
    charts['methods'].dispatchAction({type:'hideTip'});
    renderMethods();
    panel.innerHTML='<h3>'+esc(nm)+'</h3>'+(papers.length?'<div>使用该方法的论文（'+papers.length+'）：</div>'+paperList(papers):'<div class="meta">该结点下无论文明细（展开子结点查看）。</div>');
    pulsePanel('mmPanel');
  });
}

function renderRelations(){
  const sc=scope();
  const rel=sc.relations||{};
  const nodes=(sc.network||{}).nodes||[];
  const types=rel.types||{};
  const edges=(rel.edges||[]).filter(e=>e&&e.s&&e.t);
  const desc=document.getElementById('relDesc');
  if(desc) desc.textContent='范围：'+sc.label+'（池内 '+nodes.length+' 篇）；连线颜色=关系类型；点击节点或连线放大聚焦，再点取消；面板显示摘要证据。';
  if(!nodes.length||!edges.length){ empty('relations','该范围暂无可核验的论文关系'); return; }
  const byId={}; nodes.forEach(n=>byId[n.id]=n);
  const deg={}; edges.forEach(e=>{deg[e.s]=(deg[e.s]||0)+1;deg[e.t]=(deg[e.t]||0)+1;});
  const top=new Set(nodes.filter(n=>deg[n.id]).sort((a,b)=>(deg[b.id]||0)-(deg[a.id]||0)||(b.cited||0)-(a.cited||0)).slice(0,12).map(n=>n.id));
  const pos=prelayout(nodes,edges,900,520);
  const pal={support:'#61d6a6',improve:'#63b3ff',conflict:'#ff7b7b',difference:'#b58cff'};
  const labelOf=id=>(byId[id]||{}).label||id;
  const focusId=state.relFocus, focusEdge=state.relEdge;
  // 聚焦特写：居中 + 按选中对象自适应倍率，保证选中结点/连线完整留在画布内（长边自动降倍）
  const posMap={}; nodes.forEach((n,i)=>posMap[n.id]=pos[i]);
  const rsXs=pos.map(p=>p[0]),rsYs=pos.map(p=>p[1]);
  const rsBoxW=(Math.max.apply(null,rsXs)-Math.min.apply(null,rsXs))||1,rsBoxH=(Math.max.apply(null,rsYs)-Math.min.apply(null,rsYs))||1;
  let relZoom=1,relCenter=null;
  if(focusId&&posMap[focusId]){ relZoom=1.5;relCenter=posMap[focusId]; }
  else if(focusEdge&&posMap[focusEdge.s]&&posMap[focusEdge.t]){
    const a=posMap[focusEdge.s],b=posMap[focusEdge.t];
    const fitZ=Math.min(rsBoxW/(Math.abs(a[0]-b[0])||1e-6),rsBoxH/(Math.abs(a[1]-b[1])||1e-6))*.86;
    relZoom=Math.max(.5,Math.min(1.3,fitZ));
    relCenter=[(a[0]+b[0])/2,(a[1]+b[1])/2];
  }
  const adj={};
  if(focusId){ edges.forEach(e=>{ if(e.s===focusId) adj[e.t]=1; if(e.t===focusId) adj[e.s]=1; }); }
  const legend=document.getElementById('relLegend');
  if(legend){
    const order=['support','improve','conflict','difference'];
    legend.innerHTML=order.filter(t=>types[t]).map(t=>{
      const cnt=edges.filter(e=>e.type===t).length;
      return '<span style="display:inline-flex;align-items:center;gap:6px;margin-right:14px"><i style="width:18px;height:3px;background:'+pal[t]+';display:inline-block;border-radius:2px"></i>'+esc(types[t].name||t)+' '+cnt+'</span>';
    }).join('');
  }
  const chart=mk('relations');
  chart.setOption({backgroundColor:'transparent',
    tooltip:{backgroundColor:'rgba(15,23,42,.92)',borderColor:'rgba(56,189,248,.4)',textStyle:{color:'#e2e8f0'},
      formatter:p=>{
        if(p.dataType==='node'){const n=byId[p.data.id]||{};return '<b>'+esc(n.label||'')+'</b><br>'+esc(n.title||'')+'<br>关系 '+(deg[n.id]||0)+' 条';}
        const e=p.data||{};return '<b>'+esc((types[e.type]||{}).name||e.type)+'</b><br>'+esc(labelOf(e.s))+' → '+esc(labelOf(e.t))+'<br>'+esc(e.reason||'')+'<br><span style="color:#9fb0cc">'+esc((e.quote||'').slice(0,120))+'</span>';
      }},
    series:[{type:'graph',layout:'none',roam:state.roam.relations,draggable:state.roam.relations,
      zoom:relZoom*(state.zoom.relations||1),scaleLimit:{min:0.5,max:3},
      center:relCenter,
      animationDuration:NA(900),animationEasing:'elasticOut',animationDelay:idx=>100+idx*12,
      label:{show:true,fontSize:10,color:'#cbd5e1'},labelLayout:{hideOverlap:true},
      edgeSymbol:['none','arrow'],edgeSymbolSize:6,
      data:nodes.map((n,i)=>{
        const d=deg[n.id]||0, isTop=top.has(n.id);
        const isF=!!focusId && n.id===focusId;
        const isEdgeEnd=!!focusEdge && (n.id===focusEdge.s||n.id===focusEdge.t);
        const isNb=!!focusId && !!adj[n.id];
        let size=7+Math.min(8,d*1.8);
        if(isF) size*=2.0; else if(isEdgeEnd) size*=1.6; else if(isNb) size*=1.2;
        let opacity=1;
        if(focusId) opacity=isF?1:(isNb?.95:.15);
        else if(focusEdge) opacity=isEdgeEnd?1:.18;
        const lit=isF||isEdgeEnd;
        return Object.assign({},n,{x:pos[i][0],y:pos[i][1],symbolSize:size,
          label:{show:isTop||isF||isNb||isEdgeEnd,formatter:n.label||'',fontSize:isF?12:(isEdgeEnd?10:9),color:isF?'#f8fbff':'#cbd5e1'},
          itemStyle:{color:d?'#63b3ff':'#8fa3bf',opacity:opacity,borderColor:lit?'#e0f2fe':'transparent',borderWidth:lit?2:0,
            shadowColor:'rgba(125,211,252,.95)',shadowBlur:lit?NB(30):0}});
      }),
      links:edges.map(e=>{
        const color=pal[e.type]||'#94a3b8';
        const isSel=!!focusEdge && e.s===focusEdge.s && e.t===focusEdge.t && e.type===focusEdge.type;
        const rel=!!focusId && (e.s===focusId||e.t===focusId);
        let opacity=.72, width=e.confidence==='high'?1.9:1.2;
        if(focusId){ opacity=rel?1:.1; width=rel?2.4:width; }
        else if(focusEdge){ opacity=isSel?1:.08; width=isSel?3.5:width; }
        return Object.assign({},e,{source:e.s,target:e.t,
          lineStyle:{color:color,width:width,curveness:.1,opacity:opacity,shadowColor:color,shadowBlur:isSel?NB(18):0}});
      }),
      emphasis:{focus:'adjacency',lineStyle:{width:3,color:'#e0f2fe'}}}]},true);
  chart.off('click');
  function selectEdge(e,same){
    state.relEdge=same?null:{s:e.s,t:e.t,type:e.type};
    state.relFocus=null;
    renderRelations();
    const panel=document.getElementById('relPanel');
    panel.innerHTML='<h3>'+esc((types[e.type]||{}).name||e.type)+'关系</h3><div>'+esc(labelOf(e.s))+' → '+esc(labelOf(e.t))+'</div><div style="margin-top:6px">'+esc(e.reason||'')+'</div><div style="margin-top:8px">摘要证据（[ref '+(e.evidence_ref||'-')+']）：</div><blockquote style="margin:6px 0;padding:8px 10px;border-left:2px solid '+(pal[e.type]||'#63b3ff')+';background:rgba(56,189,248,.06)">'+esc(e.quote||'')+'</blockquote>'+(e.basis_quote?'<div class="meta">目标侧依据 [ref '+(e.basis_ref||'-')+']：'+esc(e.basis_quote)+'</div>':'')+'<div class="meta">置信度：'+esc(e.confidence||'-')+'；冲突/差异为分析判断。点击同一连线取消聚焦。</div>';
    pulsePanel('relPanel');
  }
  chart.on('click',p=>{
    const panel=document.getElementById('relPanel');
    if(p.dataType==='node'){
      const id=p.data.id;
      const same=state.relFocus===id && !state.relEdge;
      state.relFocus=same?null:id;
      state.relEdge=null;
      renderRelations();
      const list=edges.filter(e=>e.s===id||e.t===id);
      panel.innerHTML='<h3>'+esc(labelOf(id))+'</h3><div>'+esc((byId[id]||{}).title||'')+'</div><div style="margin-top:8px">关系（'+list.length+'）：</div><ul>'+
        list.map(e=>'<li><span style="color:'+(pal[e.type]||'#94a3b8')+'">'+esc((types[e.type]||{}).name||e.type)+'</span> '+esc(labelOf(e.s===id?e.t:e.s))+'<div class="meta">'+esc(e.reason||'')+'</div></li>').join('')+'</ul><div class="meta">点击同一节点取消聚焦。</div>';
      pulsePanel('relPanel');
    }else if(p.dataType==='edge'){
      const e=p.data||{};
      const same=state.relEdge && state.relEdge.s===e.s && state.relEdge.t===e.t && state.relEdge.type===e.type;
      selectEdge(e,same);
    }
  });
  const zr=chart.getZr();
  const edgeFallback=ev=>{
    if(ev.target||ev.topTarget) return;
    const zrX=ev.offsetX, zrY=ev.offsetY;
    if(zrX==null||zrY==null) return;
    let d=null; try{ d=chart.convertFromPixel({seriesIndex:0},[zrX,zrY]); }catch(err){ return; }
    if(!d) return;
    let scale=1; try{ const p0=chart.convertToPixel({seriesIndex:0},[0,0]), p1=chart.convertToPixel({seriesIndex:0},[100,0]); scale=Math.abs((p1[0]-p0[0])/100)||1; }catch(err){}
    const tol=12/scale;
    let best=null;
    edges.forEach(e=>{
      const a=byId[e.s], b=byId[e.t]; if(!a||!b) return;
      const dx=b.x-a.x, dy=b.y-a.y, dist=Math.hypot(dx,dy)||1;
      const nx=-dy/dist, ny=dx/dist;
      const cx=(a.x+b.x)/2-nx*.1*dist, cy=(a.y+b.y)/2-ny*.1*dist;
      for(let t=0;t<=1.001;t+=.05){
        const u=1-t;
        const px=u*u*a.x+2*u*t*cx+t*t*b.x, py=u*u*a.y+2*u*t*cy+t*t*b.y;
        const dd=Math.hypot(px-d[0],py-d[1]);
        if(!best||dd<best.dd) best={dd,e};
      }
    });
    if(!best||best.dd>tol) return;
    const e=best.e;
    const same=state.relEdge && state.relEdge.s===e.s && state.relEdge.t===e.t && state.relEdge.type===e.type;
    selectEdge(e,same);
  };
  if(window.__relEdgeFallback){ try{ zr.off('click',window.__relEdgeFallback); }catch(err){} }
  window.__relEdgeFallback=edgeFallback;
  zr.on('click',edgeFallback);
  const rr=document.getElementById('btnRelReset');
  if(rr) rr.onclick=()=>{state.relFocus=null;state.relEdge=null;state.zoom.relations=1;syncZoom('relations');state.roam.relations=false;renderRelations();};
}

function renderSummary(){
  const parts=[];
  Object.keys(DATA.scopes).forEach(k=>{
    const sc=DATA.scopes[k],g=sc.topics||[];
    const sum=g.reduce((s,x)=>s+x.count,0);
    const pc=c=>sum?(Math.round(c/sum*1000)/10)+'%':'-';
    let s=k==='all'?'<b>不限年限</b>：总共检索到 '+(sc.total_hits||0)+' 篇文献。':'<b>'+esc(sc.label)+'</b>'+(sc.from_year?'（近 '+(new Date().getFullYear()-sc.from_year+1)+' 年）':'')+'：共 '+(sc.total_hits||0)+' 篇文献。';
    if(g.length){s+='主题命中中"'+esc(zh(g[0]))+'"占比最多（'+pc(g[0].count)+'）';if(g[1])s+='，其次"'+esc(zh(g[1]))+'"（'+pc(g[1].count)+'）';if(g[2])s+='、"'+esc(zh(g[2]))+'"（'+pc(g[2].count)+'）';s+='。';}
    parts.push('<p>'+s+'</p>');
  });
  const tr=DATA.trend_all||[];
  if(tr.length){const peak=tr.reduce((a,b)=>b.count>a.count?b:a);parts.push('<p><b>总体趋势</b>：发文量在 '+peak.year+' 年达到峰值（'+peak.count+' 篇）。</p>');}
  document.getElementById('summary').innerHTML=parts.join('');
}

function renderScope(){renderTopics();renderNetwork();renderKnowledge();renderMethods();renderRelations();}
renderTrend();renderCompare();renderScope();renderSummary();
setTimeout(function(){
  var ids=['trend','topics','compare','network','knowledge','methods'],fixed=false;
  ids.forEach(function(id){
    var el=document.getElementById(id);
    if(el && el.clientHeight < 40){ el.style.height = (id==='trend'||id==='compare') ? '420px' : '520px'; fixed=true; }
  });
  if(fixed){ Object.keys(charts).forEach(function(k){ if(charts[k]) charts[k].resize(); }); }
}, 600);
if(location.search.indexOf('debug=1')>=0){
  try{
    const dbg=document.createElement('div');
    dbg.style.cssText='position:fixed;left:8px;bottom:8px;z-index:99;background:rgba(0,0,0,.85);color:#7dd3fc;font-size:10px;padding:6px 8px;border-radius:6px;font-family:monospace;line-height:1.6;max-width:92vw';
    const cnt=()=>Object.keys(charts).filter(k=>charts[k]).length;
    const cv=()=>document.querySelectorAll('.chart canvas').length;
    const sv=()=>document.querySelectorAll('.chart svg').length;
    function sizes(){
      return ['trend','network','knowledge','methods'].map(function(id){
        var el=document.getElementById(id); if(!el) return id+':-';
        var c=el.querySelector('canvas')||el.querySelector('svg');
        return id+':h'+el.clientHeight+'/' + (c ? ((c.getAttribute('width')||'?')+'x'+(c.getAttribute('height')||'?')) : '无画布');
      }).join(' ');
    }
    function upd(){ dbg.textContent='debug: echarts='+(!!window.echarts)+' charts='+cnt()+' canvas='+cv()+' svg='+sv()+' | '+sizes()+' | 视口='+innerWidth+'x'+innerHeight+' dpr='+(window.devicePixelRatio||1); }
    upd(); document.body.appendChild(dbg); setTimeout(upd,1500); setTimeout(upd,3200);
  }catch(e){}
}
document.querySelectorAll('.roamToggle').forEach(function(b){
  b.onclick=function(){
    const id=b.getAttribute('data-chart');
    state.roam[id]=!state.roam[id];
    b.textContent='手势缩放：'+(state.roam[id]?'开':'关');
    b.classList.toggle('on',state.roam[id]);
    if(id==='network') renderNetwork();
    else if(id==='knowledge') renderKnowledge();
    else if(id==='methods') renderMethods();
    else if(id==='relations') renderRelations();
  };
});
document.querySelectorAll('.zoomBtn').forEach(function(b){
  b.onclick=function(){
    const id=b.getAttribute('data-chart');
    zoomBy(id, parseFloat(b.getAttribute('data-step'))||0);
  };
});
document.querySelectorAll('.zoomVal').forEach(function(el){ syncZoom(el.getAttribute('data-chart')); });
window.addEventListener('resize',()=>{Object.values(charts).forEach(c=>c.resize());renderTopics();});
(function setupReplay(){
  if(!('IntersectionObserver' in window)) return;
  if(isNarrow()) return;
  const bootedAt = Date.now();
  const lastPlay = {};
  const replay = {
    trend: renderTrend, compare: renderCompare, topics: renderTopics,
    network: renderNetwork, knowledge: renderKnowledge, methods: renderMethods, relations: renderRelations
  };
  const io = new IntersectionObserver(function(entries){
    entries.forEach(function(en){
      if(!en.isIntersecting || en.intersectionRatio < 0.3) return;
      const id = en.target.id;
      if(Date.now() - bootedAt < 1800) return;
      if(lastPlay[id] && Date.now() - lastPlay[id] < 1500) return;
      lastPlay[id] = Date.now();
      try {
        const inst = charts[id];
        if(inst && inst.clear){ inst.clear(); }
        if(replay[id]) replay[id]();
        flashChart(id);
      } catch(e){}
    });
  }, {threshold:[0.3]});
  Object.keys(replay).forEach(function(id){
    const el = document.getElementById(id);
    if(el) io.observe(el);
  });
})();
document.getElementById('foot').textContent='满血版 · 桌面与手机 Chrome 均可运行；若环境不支持，使用轻量版页面。';
(function setupSlide(){
  const cards = Array.from(document.querySelectorAll('main > .card'));
  if(!cards.length) return;
  const btn = document.getElementById('btnSlide');
  const pos = document.getElementById('slidePos');
  if(!btn || !pos) return;
  const reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  let on = true, lock = false, acc = 0;
  function pad(){
    const a = document.querySelector('.tabs');
    const b = document.querySelector('.scopebar');
    return Math.max(a ? a.offsetHeight : 0, b ? b.offsetHeight : 0, 0) + 18;
  }
  function indexNow(){
    const y = window.scrollY + pad() + 12;
    let idx = -1;
    cards.forEach(function(el, i){
      const top = el.getBoundingClientRect().top + window.scrollY;
      if(top <= y) idx = i;
    });
    return idx;
  }
  function updatePos(){
    pos.textContent = (Math.max(0, indexNow()) + 1) + ' / ' + cards.length;
  }
  function go(i){
    i = Math.max(0, Math.min(cards.length - 1, i));
    const top = cards[i].getBoundingClientRect().top + window.scrollY;
    window.scrollTo({top: Math.max(0, top - pad()), behavior: reduce ? 'auto' : 'smooth'});
    updatePos();
    lock = true;
    setTimeout(function(){ lock = false; }, 950);
  }
  function next(dir){
    if(lock) return false;
    const idx = indexNow();
    if(dir > 0){
      if(idx >= cards.length - 1) return false;
      const cur = cards[Math.max(0, idx)];
      const r = cur.getBoundingClientRect();
      if(r.bottom > window.innerHeight + 6) return false;
      go(idx < 0 ? 0 : idx + 1);
      return true;
    }
    if(idx <= 0) return false;
    const r = cards[idx].getBoundingClientRect();
    if(r.top < pad() - 6) return false;
    go(idx - 1);
    return true;
  }
  window.addEventListener('wheel', function(ev){
    if(!on) return;
    const el = ev.target instanceof Element ? ev.target : null;
    if(!el) return;
    if(ev.ctrlKey || ev.metaKey) return;
    if(el.closest('.panel') || el.closest('.slideCtl')) return;
    if(el.closest('button, a, input, textarea, select')) return;
    if(el.closest('.chart') && Object.keys(state.roam || {}).some(function(k){ return state.roam[k]; })) return;
    if(Math.abs(ev.deltaY) < Math.abs(ev.deltaX)) return;
    if(lock){ ev.preventDefault(); return; }
    acc += ev.deltaY;
    if(Math.abs(acc) < 30) return;
    const dir = acc > 0 ? 1 : -1;
    acc = 0;
    if(next(dir)) ev.preventDefault();
  }, {passive:false});
  window.addEventListener('keydown', function(ev){
    if(!on) return;
    const tag = (ev.target && ev.target.tagName || '').toLowerCase();
    if(tag === 'input' || tag === 'textarea' || (ev.target && ev.target.isContentEditable)) return;
    if(ev.key === 'PageDown' || ev.key === 'ArrowDown'){ if(next(1)) ev.preventDefault(); }
    if(ev.key === 'PageUp' || ev.key === 'ArrowUp'){ if(next(-1)) ev.preventDefault(); }
  });
  btn.onclick = function(){
    on = !on;
    btn.classList.toggle('on', on);
    btn.textContent = '幻灯片滚动：' + (on ? '开' : '关');
    if(!on){ lock = false; acc = 0; }
  };
  window.addEventListener('scroll', function(){ if(!lock) updatePos(); }, {passive:true});
  window.addEventListener('resize', updatePos);
  updatePos();
})();
</script>
</body>
</html>
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--data', required=True)
    ap.add_argument('--out', required=True)
    a = ap.parse_args()
    with open(a.data, encoding='utf-8') as f:
        data = json.load(f)
    payload = json.dumps(data, ensure_ascii=False).replace('</', '<\\/')
    page = (TEMPLATE.replace('__TOPIC__', str(data.get('topic', '文献图谱仪表盘')).replace('<', '&lt;'))
            .replace('__ECHARTS__', echarts_scripts())
            .replace('__DATA__', payload))
    with open(a.out, 'w', encoding='utf-8') as f:
        f.write(page)
    print('电脑端满血版已生成: %s (%d KB)' % (a.out, len(page) // 1024))


if __name__ == '__main__':
    main()