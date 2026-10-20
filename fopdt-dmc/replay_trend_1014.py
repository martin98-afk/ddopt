# -*- coding: utf-8 -*-
"""10-14 严重越线段 · 趋势预测控制 vs 旧守护带规则 vs 人工。

温度 = 响应核推演（共同扰动法，理论闭环），温度随各方水率真实变化。
两方：
  人工      实际水率轨迹
  新趋势    trend_controller.TrendController（模仿人工：当前温度+斜率
            预测未来温度，提前干预，双向连续调节，不设死区锁死）

输出 fopdt-dmc/趋势控制对比.html + 终端指标。

用法：python replay_trend_1014.py
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

from config import Tag, Config
from signal_conditioning import SignalConditioner
from controller import XshController
from ab_test import response_fast
from fopdt import fit_fopdt_from_kernel
import replay_xsh_clean as rx
from run_experiment import G_OLD, extend_kernel
from trend_controller import TrendController, slope_linfit

T3_TAGS = Tag.TEMP[2]
SP = 118.0
CTRL = 5   # 与人工操作频率对齐（人工约 6min/次）


def metrics(t3, ratio, lo=100.0, hi=130.0):
    v = np.asarray(t3, float)
    ok = ~np.isnan(v)
    v = v[ok]
    r = np.asarray(ratio, float)[ok]
    moves = int(np.sum(np.abs(np.diff(r)) >= 2.0)) if r.size > 1 else 0
    return dict(rate=float(np.mean((v >= lo) & (v <= hi)) * 100.0) if v.size else 0.0,
                std=float(np.std(v)) if v.size else 0.0,
                moves=moves, n=int(v.size),
                lo=float(np.nanmin(r)), hi=float(np.nanmax(r)))


def main():
    data, t3_act, grid, times, n = rx.load_and_resample()
    R = data[Tag.RATIO_SD].copy()
    perm = data[Tag.PERMIT]
    prod = perm > 0.5
    dd = np.diff(prod.astype(np.int8))
    starts = list(np.where(dd == 1)[0] + 1)
    ends = list(np.where(dd == -1)[0] + 1)
    if prod[0]:
        starts.insert(0, 0)
    if prod[-1]:
        ends.append(n)

    def over_count(se):
        s, e = se
        return float(np.nansum(t3_act[s:e + 1] > 130))

    segs = [se for se in zip(starts, ends) if se[1] - se[0] >= 300]
    s0, e0 = max(segs, key=over_count)
    L = e0 - s0 + 1
    t3_act_seg = t3_act[s0:e0 + 1]
    u_act_seg = np.where(np.isnan(R[s0:e0 + 1]), np.nan, R[s0:e0 + 1])
    print("段: %s ~ %s (%d min)  瞬时>130: %d min  峰: %.1f℃  合格率: %.1f%%" % (
        times[s0], times[e0 - 1], L - 1, int(np.nansum(t3_act_seg > 130)),
        float(np.nanmax(t3_act_seg)),
        float(np.mean((t3_act_seg >= 100) & (t3_act_seg <= 130)) * 100)))

    # 真对象：保守 FOPDT 核。伪影核的瞬时形状（5min 见效）已确认不可信，
    # 只保留可信的稳态增益 -0.151，滞后/时间常数按现实节奏取
    # θ=30min（输运+反应滞后）、τ=60min——加水后 30min 才开始见效
    from fopdt import step_coeffs as _sc
    span = max(e - s for s, e in segs)
    G = _sc(-0.151, 60.0, 30.0, 1.0, span + 61)
    print("真对象 = 保守FOPDT核 K=-0.151 τ=60 θ=30（延伸至 %d min）" % len(G))

    # ---- 共同扰动 d ----
    u_act = np.where(np.isnan(R), 0.0, R).astype(np.float64)
    for i in range(1, n):
        if np.isnan(R[i]):
            u_act[i] = u_act[i - 1]
    base0 = float(t3_act[s0])
    resp_act0 = response_fast(u_act, G, s0)
    dv = np.full(L, np.nan)
    for idx, t in enumerate(range(s0, e0 + 1)):
        if not np.isnan(t3_act[t]):
            dv[idx] = t3_act[t] - base0 - (response_fast(u_act, G, t) - resp_act0)
    for i in range(1, L):
        if np.isnan(dv[i]):
            dv[i] = dv[i - 1]
    for i in range(L - 2, -1, -1):
        if np.isnan(dv[i]):
            dv[i] = dv[i + 1]

    u_act_seg = u_act[s0:e0 + 1].copy()

    # ---- 闭环 B：新趋势控制器 ----
    cur = 600.0   # 预制设定值起步（不从人工实际数据起步）
    trend = TrendController(target=SP, u_init=cur)
    t3_trend = np.full(L, np.nan)
    ratio_trend = np.full(L, np.nan)
    hist = []
    for i in range(L):
        v = base0 + (response_fast(_u_full(u_act, cur, s0, i), G, s0 + i) - resp_act0) + dv[i]
        t3_trend[i] = v
        hist.append(v)
        slope = slope_linfit(hist[-15:])
        if i % CTRL == 0 and v == v:
            cur = trend.update(v, slope)
        ratio_trend[i] = cur

    m_act = metrics(t3_act_seg, u_act_seg)
    m_tr = metrics(t3_trend, ratio_trend)
    print("\n%-8s %8s %8s %6s %9s %9s" % (
        "方案", "合格率%", "σ", "动次", "水率低", "水率高"))
    for name, m in (("人工", m_act), ("新趋势", m_tr)):
        print("%-8s %8.1f %8.2f %6d %9.0f %9.0f" % (
            name, m["rate"], m["std"], m["moves"], m["lo"], m["hi"]))

    # ---- HTML ----
    def Ln(a, nd=2):
        return [None if (v is None or v != v) else round(float(v), nd) for v in a]

    t_axis = [times[i] for i in range(s0, e0 + 1)]
    over_hi, over_lo, curk, cs = [], [], None, 0
    for i in range(L):
        v = t3_act_seg[i]
        kind = "hi" if (v == v and v > 130) else \
            ("lo" if (v == v and v < 100) else None)
        if kind != curk:
            if curk is not None:
                (over_hi if curk == "hi" else over_lo).append([cs, i - 1])
            curk, cs = kind, i
    if curk is not None:
        (over_hi if curk == "hi" else over_lo).append([cs, L - 1])

    def to_marker(pairs):
        return [[{"xAxis": int(a)}, {"xAxis": int(b)}] for a, b in pairs]

    D = dict(t=t_axis,
             t3_act=Ln(t3_act_seg), t3_tr=Ln(t3_trend),
             r_act=Ln(u_act_seg, 1), r_tr=Ln(ratio_trend, 1),
             over_hi=to_marker(over_hi), over_lo=to_marker(over_lo))

    tpl = """<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8">
<title>10-14 段 · 趋势预测控制 vs 旧守护带规则 vs 人工</title>
<script src="../趋势分析/echarts.min.js"></script>
<style>body{font-family:'Microsoft YaHei',sans-serif;margin:16px;background:#fafafa}
#main{width:96vw;height:760px;background:#fff;border:1px solid #e0e0e0}
.note{color:#666;font-size:13px;line-height:1.7}</style></head>
<body>
<h3>10-14 严重越线段 · 趋势预测控制对比（温度=响应核推演+共同扰动）</h3>
<div class="note">灰 = 人工实际；蓝 = 旧守护带规则（对照）；绿 = 新趋势预测控制器
（按当前温度+斜率预测未来 15min，提前干预，双向连续调节）。
红背景 = 实际 T3&gt;130℃，蓝背景 = &lt;100℃。温度随各方水率真实变化。</div>
<div id="main"></div>
<script>
var D = __DATA__;
var mk = function(pairs,color){return pairs.map(function(p){
  return [{xAxis:p[0].xAxis,itemStyle:{color:color}},
          {xAxis:p[1].xAxis,itemStyle:{color:color}}];});};
var chart = echarts.init(document.getElementById('main'));
chart.setOption({animation:false,
  axisPointer:{link:[{xAxisIndex:'all'}]},
  tooltip:{trigger:'axis'},
  legend:{data:['T3人工','T3新趋势','水率人工','水率新趋势'],top:10},
  grid:[{left:70,right:40,top:60,height:'34%'},
        {left:70,right:40,top:'56%',height:'32%'}],
  xAxis:[{type:'category',data:D.t,gridIndex:0,axisLabel:{show:false}},
         {type:'category',data:D.t,gridIndex:1}],
  yAxis:[{name:'T3 ℃',gridIndex:0,min:40,max:180},
         {name:'水率 L/t',gridIndex:1,min:300,max:720}],
  series:[
    {name:'T3人工',type:'line',data:D.t3_act,xAxisIndex:0,yAxisIndex:0,symbol:'none',
     lineStyle:{color:'#888',width:1.2}},
    {name:'T3新趋势',type:'line',data:D.t3_tr,xAxisIndex:0,yAxisIndex:0,symbol:'none',
     lineStyle:{color:'#1a9c6e',width:1.8}},
    {name:'带130',type:'line',xAxisIndex:0,yAxisIndex:0,data:[],
     markLine:{silent:true,symbol:'none',label:{formatter:'130℃',position:'insideEndTop'},
       lineStyle:{color:'#c0392b',type:'dashed'},data:[{yAxis:130}]}},
    {name:'带100',type:'line',xAxisIndex:0,yAxisIndex:0,data:[],
     markLine:{silent:true,symbol:'none',label:{formatter:'100℃',position:'insideEndBottom'},
       lineStyle:{color:'#2471a3',type:'dashed'},data:[{yAxis:100}]}},
    {name:'超标背景',type:'line',xAxisIndex:0,yAxisIndex:0,data:[],
     markArea:{silent:true,data:mk(D.over_hi,'rgba(192,57,43,0.08)')
       .concat(mk(D.over_lo,'rgba(36,113,163,0.08)'))}},
    {name:'水率人工',type:'line',data:D.r_act,xAxisIndex:1,yAxisIndex:1,
     symbol:'none',lineStyle:{color:'#888',width:1.4}},
    {name:'水率新趋势',type:'line',data:D.r_tr,xAxisIndex:1,yAxisIndex:1,
     symbol:'none',lineStyle:{color:'#1a9c6e',width:2},step:'end'}
  ]
});
window.addEventListener('resize',function(){chart.resize();});
</script></body></html>
"""
    html = tpl.replace("__DATA__", json.dumps(D, ensure_ascii=False))
    out = os.path.join(_HERE, "趋势控制对比.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)
    print("\n已生成:", out)


# ---- 工具：构造"截至 i 时刻已被控制器覆盖"的全长水率序列 ----
def _u_full(u_act, cur, s0, i):
    """复制实际轨迹，把 [s0..s0+i] 段替换为控制器当前水率"""
    u = u_act.copy()
    t_end = s0 + i
    u[s0:t_end + 1] = cur
    return u


def set_t3(table, i, v):
    for tag in T3_TAGS:
        table.d[tag][i] = v


if __name__ == "__main__":
    main()
