#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build_static_site.py — 生成"静态优先"仪表盘网页（仅用 Python 标准库）。

首屏直接内联全部图表 SVG（任何环境可见）；交互采用预渲染隐藏面板 + 点击切换 class。
总体趋势 / 比较分析 / 主题分布 三图额外挂载 ECharts 交互版（内联图表库，悬停提示、
饼柱切换、显示数量）；ECharts 不可用或渲染失败时自动保留静态图，不会空白。

用法:
  python3 build_static_site.py --data dashboard_data.json --out page.html \
      [--title 标题] [--long-image dashboard.png] [--intro 说明文字]
"""
import argparse
import json
import os
import sys
from urllib.parse import urlsplit

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from static_charts import build_static_interactive_page
from build_dashboard import echarts_scripts

def relative_artifact_url(value):
    parts = urlsplit(value)
    return os.path.basename(parts.path) + (f'?{parts.query}' if parts.query else '')


LIVE_JS = """<script>
(function(){
  if(!window.echarts || !window.__MDATA__){ return; }
  var D=window.__MDATA__;
  var AX={axisLine:{lineStyle:{color:'rgba(160,190,235,.45)'}},axisLabel:{color:'#9fb0cc',fontSize:10},splitLine:{lineStyle:{color:'rgba(120,170,255,.12)'}}};
  function zh(x){return x.name_zh||x.name;}
  function rendered(el){return el && el.querySelector && el.querySelector('canvas,svg');}
  function hide(el){if(el) el.style.display='none';}
  try{
    var te=document.getElementById('trend-live');
    if(te && D.trend && D.trend.length){
      te.style.display='block';
      var c=echarts.init(te,null,{renderer:'svg'});
      c.setOption({animation:false,tooltip:{trigger:'axis',backgroundColor:'rgba(12,18,34,.96)',borderColor:'rgba(120,170,255,.35)',textStyle:{color:'#eaf1ff'}},grid:{left:48,right:14,top:18,bottom:28},
        xAxis:Object.assign({type:'category',data:D.trend.map(function(x){return x.year;}),boundaryGap:false},AX),
        yAxis:Object.assign({type:'value'},AX),
        series:[{type:'line',data:D.trend.map(function(x){return x.count;}),smooth:true,symbolSize:5,
          lineStyle:{width:2,color:'#63b3ff'},itemStyle:{color:'#63b3ff'}}]},true);
      c.resize();
      if(rendered(te)){ hide(document.getElementById('trend-static'));
        requestAnimationFrame(function(){c.resize();});
        window.addEventListener('resize',function(){c.resize();}); }
      else { te.style.display='none'; }
    }
  }catch(e){}
  try{
    var ce=document.getElementById('compare-live');
    if(ce && D.compare && D.compare.length){
      ce.style.display='block';
      var c2=echarts.init(ce,null,{renderer:'svg'});
      var ys={};
      D.compare.forEach(function(s){(s.series||[]).forEach(function(p){ys[p.year]=1;});});
      var years=Object.keys(ys).map(Number).sort(function(a,b){return a-b;});
      var pal=['#63b3ff','#f0a35e','#61d6a6','#b58cff'];
      c2.setOption({animation:false,tooltip:{trigger:'axis',backgroundColor:'rgba(12,18,34,.96)',borderColor:'rgba(120,170,255,.35)',textStyle:{color:'#eaf1ff'}},legend:{top:0,textStyle:{fontSize:10,color:'#9fb0cc'}},
        grid:{left:48,right:14,top:32,bottom:28},
        xAxis:Object.assign({type:'category',data:years,boundaryGap:false},AX),
        yAxis:Object.assign({type:'value'},AX),
        series:D.compare.map(function(s,i){var m={};(s.series||[]).forEach(function(p){m[p.year]=p.count;});
          return {name:s.name_zh||s.name,type:'line',smooth:true,symbolSize:4,
            lineStyle:{width:2,color:pal[i%4]},itemStyle:{color:pal[i%4]},
            data:years.map(function(y){return m[y]||0;})};})},true);
      c2.resize();
      if(rendered(ce)){ hide(document.getElementById('compare-static'));
        requestAnimationFrame(function(){c2.resize();});
        window.addEventListener('resize',function(){c2.resize();}); }
      else { ce.style.display='none'; }
    }
  }catch(e){}
  Object.keys(D.scopes||{}).forEach(function(key){
    var sc=D.scopes[key],sec=document.getElementById('topics-'+key),
        le=document.getElementById('topics-live-'+key);
    if(!sec||!le||!(sc.topics||[]).length) return;
    try{
      var state={view:'pie',topn:20};
      le.style.display='block';
      var inst=echarts.init(le,null,{renderer:'svg'});
      var pal=['#63b3ff','#f0a35e','#61d6a6','#b58cff','#ff7b7b','#f4d35e','#4fd1d1','#8ea6ff','#ff8fc7','#9fd36a','#f0a35e','#5fa8ff'];
      function render(){
        var g=sc.topics.slice(0,state.topn),total=0,i;
        for(i=0;i<g.length;i++) total+=g[i].count||0;
        var opt={animation:false,tooltip:{trigger:'item',backgroundColor:'rgba(12,18,34,.96)',borderColor:'rgba(120,170,255,.35)',textStyle:{color:'#eaf1ff'}},legend:{type:'scroll',bottom:0,textStyle:{fontSize:10,color:'#9fb0cc'}}};
        if(state.view==='pie'){
          opt.series=[{type:'pie',radius:['24%','58%'],center:['50%','42%'],
            label:{fontSize:9,color:'#dbe7ff',formatter:function(p){return p.value+'('+(total?(Math.round(p.value/total*1000)/10):0)+'%)';}},
            data:g.map(function(x,i2){return {name:zh(x),value:x.count,itemStyle:{color:pal[i2%12]}};})}];
        }else{
          opt.grid={left:6,right:52,top:6,bottom:34,containLabel:true};
          opt.xAxis=Object.assign({type:'value'},AX);
          opt.yAxis={type:'category',inverse:true,data:g.map(zh),axisLabel:{color:'#8a94a9',fontSize:9}};
          opt.series=[{type:'bar',data:g.map(function(x,i2){return {value:x.count,itemStyle:{color:pal[i2%12]}};}),label:{show:true,position:'right',fontSize:9,color:'#9fb0cc'}}];
        }
        inst.setOption(opt,true);
      }
      render();
      inst.resize();
      if(rendered(le)){
        var statics=sec.querySelectorAll('.tv'),j;
        for(j=0;j<statics.length;j++){ statics[j].style.display='none'; }
        requestAnimationFrame(function(){inst.resize();});
        window.addEventListener('resize',function(){inst.resize();});
        sec.querySelectorAll('[data-view]').forEach(function(b){
          b.addEventListener('click',function(){ state.view=b.getAttribute('data-view'); render(); });
        });
        sec.querySelectorAll('[data-n]').forEach(function(b){
          b.addEventListener('click',function(){ state.topn=+b.getAttribute('data-n'); render(); });
        });
      } else { le.style.display='none'; }
    }catch(e){}
  });
})();
</script>"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--data', required=True, help='dashboard_data.json')
    ap.add_argument('--out', required=True, help='输出 HTML 路径')
    ap.add_argument('--title', default='文献图谱仪表盘')
    ap.add_argument('--long-image', default=None, help='长图文件名（与页面同目录）')
    ap.add_argument('--intro', default='')
    a = ap.parse_args()
    with open(a.data, encoding='utf-8') as f:
        data = json.load(f)
    long_image = relative_artifact_url(a.long_image) if a.long_image else None
    html = build_static_interactive_page(data, a.title, long_image=long_image,
                                         intro=a.intro, live_charts=True)
    mdata = {
        'trend': data.get('trend_all') or [],
        'compare': data.get('compare') or [],
        'scopes': {k: {'label': sc.get('label', ''), 'topics': sc.get('topics') or []}
                   for k, sc in (data.get('scopes') or {}).items()},
    }
    payload = json.dumps(mdata, ensure_ascii=False).replace('</', '<\\/')
    html = html.replace('</head>', echarts_scripts() + '\n</head>', 1)
    idx = html.rfind('</body>')
    if idx < 0:
        idx = len(html)
    inject = '<script>window.__MDATA__=' + payload + ';</script>\n' + LIVE_JS + '\n'
    html = html[:idx] + inject + html[idx:]
    with open(a.out, 'w', encoding='utf-8') as f:
        f.write(html)
    print('静态优先页已生成: %s (%d KB)' % (a.out, len(html) // 1024))


if __name__ == '__main__':
    main()