# -*- coding: utf-8 -*-
"""10-14 严重越线段 · 阶跃响应仿真温度下的理论水率控制对比。

与 replay_xsh_clean.py（实际温度回放）的区别：
  那里  温度 = 实际曲线（人工操作下的温度，水率效果不体现在图上）
  这里  温度 = 响应核推演（共同扰动法：d = 实际T3 − 核∘(实际水率)），
        控制器动作会真实改变仿真温度 → 看**理论闭环**下水率怎么走

三方：人工（实际水率轨迹）/ 现行规则控制器（含快通道）/ FOPDT+DMC。
对象：G_OLD 权威核（尾部稳态延伸）。

输出 fopdt-dmc/理论仿真回放.html + 终端指标。

用法：python replay_kernel_1014.py
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
from dmc import DMCController
import replay_xsh_clean as rx
from run_experiment import G_OLD, extend_kernel

T3_TAGS = Tag.TEMP[2]
SP = 118.0
CTRL = 10


def set_t3(table, i, v):
    for tag in T3_TAGS:
        table.d[tag][i] = v


def metrics(t3, ratio, lo=100.0, hi=130.0):
    v = np.asarray(t3, float)
    ok = ~np.isnan(v)
    v = v[ok]
    r = np.asarray(ratio, float)[ok]
    moves = int(np.sum(np.abs(np.diff(r)) >= 2.0)) if r.size > 1 else 0
    return dict(rate=float(np.mean((v >= lo) & (v <= hi)) * 100.0) if v.size else 0.0,
                std=float(np.std(v)) if v.size else 0.0,
                moves=moves, n=int(v.size), lo=float(np.nanmin(r)), hi=float(np.nanmax(r)))


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

    def over_score(se):
        s, e = se
        return float(np.nansum(t3_act[s:e + 1] > 130))

    segs = [se for se in zip(starts, ends) if se[1] - se[0] >= 300]
    s0, e0 = max(segs, key=over_score)
    L = e0 - s0 + 1
    print("段: %s ~ %s (%d min)  瞬时>130: %d min  峰: %.1f℃" % (
        times[s0], times[e0 - 1], L - 1,
        int(np.nansum(t3_act[s0:e0 + 1] > 130)), float(np.nanmax(t3_act[s0:e0 + 1]))))

    # 真对象：权威核 + 尾部稳态延伸（FIR 截断修复）
    span = max(e - s for s, e in segs)
    G = extend_kernel(G_OLD, span + 61)
    print("真对象 = G_OLD 延伸至 %d min，稳态增益 %+.4f ℃/(L/t)" % (len(G), G[-1]))

    # FOPDT 拟合（供 DMC）
    f = fit_fopdt_from_kernel(G_OLD, Ts=1.0)
    print("FOPDT 拟合: K=%+.4f τ=%.1f θ=%.0f R²=%.3f" % (
        f["K"], f["tau"], f["theta"], f["r2"]))

    # ---- 共同扰动 d（以实际轨迹提取，三方共用）----
    u_act = np.where(np.isnan(R), 0.0, R).astype(np.float64)
    for i in range(1, n):
        if np.isnan(R[i]):
            u_act[i] = u_act[i - 1]
    u_sim_base = u_act.copy()
    base0 = float(t3_act[s0])
    resp_act0 = response_fast(u_sim_base, G, s0)
    dv = np.full(L, np.nan)
    for idx, t in enumerate(range(s0, e0 + 1)):
        if not np.isnan(t3_act[t]):
            dv[idx] = t3_act[t] - base0 - (response_fast(u_sim_base, G, t) - resp_act0)
    for i in range(1, L):
        if np.isnan(dv[i]):
            dv[i] = dv[i - 1]
    for i in range(L - 2, -1, -1):
        if np.isnan(dv[i]):
            dv[i] = dv[i + 1]

    u_act_seg = u_act[s0:e0 + 1].copy()      # 人工水率（段内）

    def simulate(controller_kind):
        """闭环：温度=核推演+共同扰动。controller_kind: rule | dmc"""
        u_sim = u_act.copy()
        # 用 MiniTable（段内局部索引，温度可写）
        seg_data = {tag: arr[s0:e0 + 1].copy() for tag, arr in data.items()}
        from replay_xsh_clean import MiniTable
        table = MiniTable(seg_data, np.arange(L) * 60)
        sc = SignalConditioner(table, Config())
        ctrl = XshController(sc, Config()) if controller_kind == "rule" else None
        dmc = DMCController(K=f["K"], tau=f["tau"], theta=f["theta"], sp=SP,
                            lam=0.1, u_init=float(u_act[s0]) if u_act[s0] > 0 else 630.0) \
            if controller_kind == "dmc" else None

        cur = float(u_act[s0]) if u_act[s0] > 0 else 630.0
        t3_sim = np.full(L, np.nan)
        ratio = np.full(L, np.nan)
        for i in range(L):
            t = s0 + i
            cur = float(np.clip(cur, 540.0, 720.0))
            table.d[Tag.RATIO_SD][i] = cur
            table.d[Tag.RATIO_FK][i] = cur
            table.d[Tag.LIME][i] = 3.5
            u_sim[t] = cur
            v = base0 + (response_fast(u_sim, G, t) - resp_act0) + dv[i]
            t3_sim[i] = v
            set_t3(table, i, v)
            if i % CTRL == 0 and not np.isnan(v):
                if controller_kind == "rule":
                    out = ctrl.step(i)
                    cur = float(out.ratio_set)
                else:
                    cur = dmc.step(v)
            ratio[i] = cur
        return t3_sim, ratio

    print("\n闭环仿真中（规则 / DMC）……")
    t3_rule, ratio_rule = simulate("rule")
    t3_dmc, ratio_dmc = simulate("dmc")
    t3_act_seg = t3_act[s0:e0 + 1]

    m_act = metrics(t3_act_seg, u_act_seg)
    m_rule = metrics(t3_rule, ratio_rule)
    m_dmc = metrics(t3_dmc, ratio_dmc)
    print("\n%-10s %8s %8s %6s %10s %10s" % (
        "方案", "合格率%", "σ", "动次", "水率低", "水率高"))
    for name, m in (("人工", m_act), ("规则", m_rule), ("DMC", m_dmc)):
        print("%-10s %8.1f %8.2f %6d %10.0f %10.0f" % (
            name, m["rate"], m["std"], m["moves"], m["lo"], m["hi"]))

    # ---- HTML ----
    t_axis = [times[i] for i in range(s0, e0 + 1)]

    def Ln(a, nd=2):
        return [None if (v is None or v != v) else round(float(v), nd)
                for v in a]

    over_hi, over_lo, curk, cs = [], [], None, 0
    for i in range(L):
        v = t3_act[i]
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
             t3_act=Ln(t3_act_seg), t3_rule=Ln(t3_rule), t3_dmc=Ln(t3_dmc),
             r_act=Ln(u_act_seg, 1), r_rule=Ln(ratio_rule, 1), r_dmc=Ln(ratio_dmc, 1),
             over_hi=to_marker(over_hi), over_lo=to_marker(over_lo))

    tpl = """<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8">
<title>10-14 段 · 阶跃响应仿真温度 · 理论水率控制对比</title>
<script src="../趋势分析/echarts.min.js"></script>
<style>body{font-family:'Microsoft YaHei',sans-serif;margin:16px;background:#fafafa}
#main{width:96vw;height:760px;background:#fff;border:1px solid #e0e0e0}
.note{color:#666;font-size:13px;line-height:1.7}</style></head>
<body>
<h3>10-14 严重越线段 · 仿真温度闭环（温度=响应核推演+共同扰动）</h3>
<div class="note">灰色 = 人工实际；蓝 = 现行规则控制器（含快通道）；橙 = FOPDT+DMC。
此图温度随各方水率真实变化（理论闭环），与实际温度回放互补。</div>
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
  legend:{data:['T3人工','T3规则','T3DMC','水率人工','水率规则','水率DMC'],top:10},
  grid:[{left:70,right:40,top:60,height:'34%'},
        {left:70,right:40,top:'56%',height:'32%'}],
  xAxis:[{type:'category',data:D.t,gridIndex:0,axisLabel:{show:false}},
         {type:'category',data:D.t,gridIndex:1}],
  yAxis:[{name:'T3 ℃',gridIndex:0,min:60,max:180},
         {name:'水率 L/t',gridIndex:1,min:540,max:720}],
  series:[
    {name:'T3人工',type:'line',data:D.t3_act,xAxisIndex:0,yAxisIndex:0,symbol:'none',
     lineStyle:{color:'#888',width:1.2}},
    {name:'T3规则',type:'line',data:D.t3_rule,xAxisIndex:0,yAxisIndex:0,symbol:'none',
     lineStyle:{color:'#1f6feb',width:1.6}},
    {name:'T3DMC',type:'line',data:D.t3_dmc,xAxisIndex:0,yAxisIndex:0,symbol:'none',
     lineStyle:{color:'#d97706',width:1.6}},
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
    {name:'水率规则',type:'line',data:D.r_rule,xAxisIndex:1,yAxisIndex:1,
     symbol:'none',lineStyle:{color:'#1f6feb',width:2},step:'end'},
    {name:'水率DMC',type:'line',data:D.r_dmc,xAxisIndex:1,yAxisIndex:1,
     symbol:'none',lineStyle:{color:'#d97706',width:2},step:'end'}
  ]
});
window.addEventListener('resize',function(){chart.resize();});
</script></body></html>
"""
    html = tpl.replace("__DATA__", json.dumps(D, ensure_ascii=False))
    out = os.path.join(_HERE, "理论仿真回放.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)
    print("\n已生成:", out)


if __name__ == "__main__":
    main()
