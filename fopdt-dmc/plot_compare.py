# -*- coding: utf-8 -*-
"""三方水率控制曲线对比图（人工 / 现行规则 / FOPDT+DMC）。

回答一个问题：T3 温度超标（>130℃）时段，三种方法各自怎么调水率。

输出 fopdt-dmc/对比曲线.html：
  上图  T3 三方轨迹 + 100/130 工艺带 + 超标时段背景块
  下图  水率三方轨迹 + 动作点标记
  echarts 引用 ../趋势分析/echarts.min.js

用法：python plot_compare.py
"""
from __future__ import annotations

import json
import os
import sys
import time as _t

import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
_MODEL = os.path.join(_HERE, "..", "模型")
for p in (_HERE, _MODEL):
    if p not in sys.path:
        sys.path.insert(0, p)

from data_loader import build_wide
from config import Tag, Config
from ab_test import identify_kernel
from run_experiment import G_OLD, T3_TAGS, run_shift_rule, run_shift_dmc, \
    extend_kernel


def main():
    wt = build_wide(verbose=False)
    R = wt.series(Tag.RATIO_SD)
    T3 = np.nanmean([wt.series(t) for t in T3_TAGS], axis=0)
    perm = wt.series(Tag.PERMIT) > 0.5
    d = np.diff(perm.astype(np.int8))
    starts = list(np.where(d == 1)[0] + 1)
    ends = list(np.where(d == -1)[0] + 1)
    if perm[0]:
        starts.insert(0, 0)
    if perm[-1]:
        ends.append(perm.size)
    segs = [(s, e) for s, e in zip(starts, ends) if e - s >= 150]
    if not segs:
        print("无生产班次")
        return
    s0, e0 = segs[0]      # 最长班次（10-19 16:34，568 min）

    # FOPDT 拟合（同 run_experiment 口径）：核需尾部稳态延伸，
    # 否则 61 分钟 FIR 截断会把稳态效应洗掉（不同策略 T3 虚假重合）
    from fopdt import fit_fopdt_from_kernel
    span = e0 - s0
    G = extend_kernel(G_OLD, span + 61)
    f = fit_fopdt_from_kernel(G, Ts=1.0)

    cfg = Config()
    r_rule = run_shift_rule(wt, cfg, s0, e0, G, T3, R)
    r_dmc = run_shift_dmc(wt, s0, e0, G, T3, R, f["K"], f["tau"],
                          f["theta"], lam=0.1)

    n = e0 - s0 + 1
    t_axis = [_t.strftime("%H:%M", _t.localtime(wt.grid[i]))
              for i in range(s0, e0 + 1)]
    t3_act = [None if np.isnan(v) else round(float(v), 2)
              for v in T3[s0:e0 + 1]]
    series = {
        "t3_rule": [None if np.isnan(v) else round(float(v), 2)
                    for v in r_rule["t3_sim"]],
        "t3_dmc": [None if np.isnan(v) else round(float(v), 2)
                   for v in r_dmc["t3_sim"]],
        "ratio_act": [None if v is None or np.isnan(v) else round(float(v), 1)
                      for v in R[s0:e0 + 1]],
        "ratio_rule": [None if np.isnan(v) else round(float(v), 1)
                       for v in r_rule["ratio_sim"]],
        "ratio_dmc": [None if np.isnan(v) else round(float(v), 1)
                      for v in r_dmc["ratio_sim"]],
    }

    # 超标时段（按人工实际 T3，连续段合并）
    over_hi, over_lo, cur = [], [], None
    for i in range(n):
        v = t3_act[i]
        if v is not None and v > 130:
            kind = "hi"
        elif v is not None and v < 100:
            kind = "lo"
        else:
            kind = None
        if kind != cur:
            if cur is not None:
                (over_hi if cur == "hi" else over_lo).append([cur_start, i - 1])
            cur, cur_start = kind, i
    if cur is not None:
        (over_hi if cur == "hi" else over_lo).append([cur_start, n - 1])

    def to_marker(pairs):
        return [[{"xAxis": a}, {"xAxis": b}] for a, b in pairs]

    actions = {}
    for key, arr in (("rule", series["ratio_rule"]), ("dmc", series["ratio_dmc"])):
        pts = []
        for i in range(1, n):
            if arr[i] is not None and arr[i - 1] is not None \
                    and abs(arr[i] - arr[i - 1]) >= 2.0:
                pts.append({"xAxis": i, "yAxis": arr[i]})
        actions[key] = pts

    D = dict(t=t_axis, t3_act=t3_act, over_hi=to_marker(over_hi),
             over_lo=to_marker(over_lo), actions=actions, **series)

    tpl = """<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<title>三方水率控制曲线对比</title>
<script src="../趋势分析/echarts.min.js"></script>
<style>
body{font-family:'Microsoft YaHei',sans-serif;margin:16px;background:#fafafa}
h3{margin:8px 0 4px}
#main{width:96vw;height:760px;background:#fff;border:1px solid #e0e0e0}
.note{color:#666;font-size:13px;line-height:1.7;max-width:96vw}
.legend b{margin-right:18px}
.c1{color:#888}.c2{color:#1f6feb}.c3{color:#d97706}
</style>
</head>
<body>
<h3>三方水率控制曲线对比（班次 10-19 16:34 起，568 min，共同扰动）</h3>
<div class="note legend">
<span class="c1">━ 人工（实际）</span><b/>
<span class="c2">━ 现行规则控制器</span><b/>
<span class="c3">━ FOPDT+DMC</span>
&nbsp;|&nbsp; 红背景 = 人工 T3&gt;130℃ 时段，蓝背景 = &lt;100℃ 时段；
下图 ● = 该方动作点（水率变化 ≥2 L/t）。上图虚线为 T3 守护带 100/130℃。
</div>
<div id="main"></div>
<script>
var D = __DATA__;
var mk = function(pairs,color){return pairs.map(function(p){
  return [{xAxis:p[0].xAxis,itemStyle:{color:color}},
          {xAxis:p[1].xAxis,itemStyle:{color:color}}];});};
var actSym = function(pts,color){return pts.map(function(p){
  return {coord:[p.xAxis,p.yAxis],symbol:'circle',symbolSize:9,
          itemStyle:{color:color},label:{show:false}};});};
var chart = echarts.init(document.getElementById('main'));
chart.setOption({
  animation:false,
  axisPointer:{link:[{xAxisIndex:'all'}]},
  tooltip:{trigger:'axis'},
  legend:{data:['T3人工','T3规则','T3DMC','水率人工','水率规则','水率DMC'],
          top:28},
  grid:[{left:70,right:40,top:80,height:'34%'},
        {left:70,right:40,top:'56%',height:'32%'}],
  xAxis:[
    {type:'category',data:D.t,gridIndex:0,axisLabel:{show:false}},
    {type:'category',data:D.t,gridIndex:1}],
  yAxis:[
    {name:'T3 ℃',gridIndex:0,min:80,max:170},
    {name:'水率 L/t',gridIndex:1,min:540,max:720}],
  series:[
    {name:'T3人工',type:'line',data:D.t3_act,xAxisIndex:0,yAxisIndex:0,
     symbol:'none',lineStyle:{color:'#888',width:1.2}},
    {name:'T3规则',type:'line',data:D.t3_rule,xAxisIndex:0,yAxisIndex:0,
     symbol:'none',lineStyle:{color:'#1f6feb',width:1.6}},
    {name:'T3DMC',type:'line',data:D.t3_dmc,xAxisIndex:0,yAxisIndex:0,
     symbol:'none',lineStyle:{color:'#d97706',width:1.6}},
    {name:'带130',type:'line',xAxisIndex:0,yAxisIndex:0,markLine:{silent:true,
      symbol:'none',label:{formatter:'130℃',position:'insideEndTop'},
      lineStyle:{color:'#c0392b',type:'dashed'},
      data:[{yAxis:130}]},data:[]},
    {name:'带100',type:'line',xAxisIndex:0,yAxisIndex:0,markLine:{silent:true,
      symbol:'none',label:{formatter:'100℃',position:'insideEndBottom'},
      lineStyle:{color:'#2471a3',type:'dashed'},
      data:[{yAxis:100}]},data:[]},
    {name:'超标背景',type:'line',xAxisIndex:0,yAxisIndex:0,data:[],
     markArea:{silent:true,
       data:mk(D.over_hi,'rgba(192,57,43,0.10)')
           .concat(mk(D.over_lo,'rgba(36,113,163,0.10)'))}},
    {name:'水率人工',type:'line',data:D.ratio_act,xAxisIndex:1,yAxisIndex:1,
     symbol:'none',lineStyle:{color:'#888',width:1.2}},
    {name:'水率规则',type:'line',data:D.ratio_rule,xAxisIndex:1,yAxisIndex:1,
     symbol:'none',lineStyle:{color:'#1f6feb',width:1.8},
     markPoint:{silent:true,
       data:actSym(D.actions.rule,'#1f6feb')}},
    {name:'水率DMC',type:'line',data:D.ratio_dmc,xAxisIndex:1,yAxisIndex:1,
     symbol:'none',lineStyle:{color:'#d97706',width:1.8},
     markPoint:{silent:true,
       data:actSym(D.actions.dmc,'#d97706')}}
  ]
});
window.addEventListener('resize',function(){chart.resize();});
</script>
</body>
</html>
"""
    html = tpl.replace("__DATA__", json.dumps(D, ensure_ascii=False))
    out = os.path.join(_HERE, "对比曲线.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)
    print("已生成:", out)

    # 终端摘要：超标时段各方的动作
    print("\n超标时段（人工 T3）三方动作摘要：")
    for a, b in over_hi + over_lo:
        seg = "高温" if a in [x[0] for x in over_hi] else "低温"
        for name, arr in (("人工", series["ratio_act"]),
                          ("规则", series["ratio_rule"]),
                          ("DMC", series["ratio_dmc"])):
            seg_v = [v for v in arr[a:b + 1] if v is not None]
            if len(seg_v) >= 2:
                print("  [%s %s..%s] %s: %.0f -> %.0f (Δ%+.0f)" % (
                    seg, t_axis[a], t_axis[b], name, seg_v[0], seg_v[-1],
                    seg_v[-1] - seg_v[0]))


if __name__ == "__main__":
    main()
