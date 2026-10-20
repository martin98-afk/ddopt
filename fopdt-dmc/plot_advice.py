# -*- coding: utf-8 -*-
"""规则控制器 · 闭环回放（下控语义）。

与顾问模式的区别：下控后现场水率就是模型上一次推送值——
水率基准**自持**（不跟随人工数据）；温度按用户要求用实际曲线。

每 10 分钟一拍：控制器读实际温度 + 自持水率 → 推送新水率 →
下一拍现场即该值。

输出 fopdt-dmc/规则响应回放.html + 终端动作清单。

用法：python plot_advice.py
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
from signal_conditioning import SignalConditioner
from controller import XshController
from ab_test import SimTable

T3_TAGS = Tag.TEMP[2]


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
    segs = [(s, e) for s, e in zip(starts, ends) if e - s >= 30]
    if not segs:
        print("无生产班次")
        return
    # 选「瞬时超 130 分钟数」最多的段 = 越线最明显、最能看响应的窗口
    def over_score(se):
        s, e = se
        seg = T3[s:e + 1]
        return float(np.nansum(seg > 130))
    s0, e0 = max(segs, key=over_score)

    cfg = Config()
    sim = SimTable(wt)          # 温度等全部读实际值；水率被逐拍覆盖为推送值
    sc = SignalConditioner(sim, cfg)
    ctrl = XshController(sc, cfg)

    cur = float(R[s0]) if not np.isnan(R[s0]) and R[s0] > 0 else 630.0
    rec = []
    push = np.full(e0 - s0 + 1, np.nan)   # 模型推送水率轨迹（自持）
    for t in range(s0, e0 + 1):
        sim.set_ratio(t, cur)      # 下控后现场水率 = 上一次推送值
        push[t - s0] = cur
        if (t - s0) % 10 == 0:
            out = ctrl.step(t)     # 读实际温度（不推演）+ 自持水率
            cur = float(out.ratio_set)
            rec.append((t, float(out.temp3), float(out.ratio_set),
                        out.action.value, out.reason))

    print("\n推送动作清单（模型自持轨迹上的动作拍）：")
    print("%-8s %7s %8s | %s" % ("时刻", "T3评估", "推送水率", "动作/理由"))
    prev = None
    for (t, tv, r_rec, act, reason) in rec:
        if prev is not None and abs(r_rec - prev) >= 2.0:
            ts = _t.strftime("%H:%M", _t.localtime(wt.grid[t]))
            tv_s = "%.1f" % tv if tv == tv else "nan"
            print("%-8s %7s %8.0f | %s (%.0f→%.0f)" % (
                ts, tv_s, r_rec, act, prev, r_rec))
        prev = r_rec
    print("共 %d 拍，水率范围 %.0f~%.0f" % (len(rec), np.nanmin(push),
                                             np.nanmax(push)))

    # ---- HTML ----
    n = e0 - s0 + 1
    t_axis = [_t.strftime("%H:%M", _t.localtime(wt.grid[i]))
              for i in range(s0, e0 + 1)]
    t3_act = [None if np.isnan(v) else round(float(v), 2)
              for v in T3[s0:e0 + 1]]
    ratio_act = [None if np.isnan(v) else round(float(v), 1) for v in R[s0:e0 + 1]]
    ratio_rec = [None if np.isnan(v) else round(float(v), 1) for v in push]

    over_hi, over_lo, cur, cs = [], [], None, 0
    for i in range(n):
        v = t3_act[i]
        kind = "hi" if (v is not None and v > 130) else \
            ("lo" if (v is not None and v < 100) else None)
        if kind != cur:
            if cur is not None:
                (over_hi if cur == "hi" else over_lo).append([cs, i - 1])
            cur, cs = kind, i
    if cur is not None:
        (over_hi if cur == "hi" else over_lo).append([cs, n - 1])

    def to_marker(pairs):
        return [[{"xAxis": int(a)}, {"xAxis": int(b)}] for a, b in pairs]

    D = dict(t=t_axis, t3=t3_act, ratio_act=ratio_act, ratio_rec=ratio_rec,
             over_hi=to_marker(over_hi), over_lo=to_marker(over_lo))

    tpl = """<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8">
<title>规则控制器 · 实际生产回放（顾问模式）</title>
<script src="../趋势分析/echarts.min.js"></script>
<style>body{font-family:'Microsoft YaHei',sans-serif;margin:16px;background:#fafafa}
#main{width:96vw;height:760px;background:#fff;border:1px solid #e0e0e0}
.note{color:#666;font-size:13px;line-height:1.7}</style></head>
<body>
<h3>规则控制器 · 闭环回放（下控语义：现场水率=上一次推送值，温度=实际曲线）</h3>
<div class="note">蓝线 = 模型推送水率（自持轨迹）；灰线 = 实际人工水率（仅对照，闭环后不存在）。
红背景 = 实际 T3&gt;130℃，蓝背景 = &lt;100℃。温度用实际曲线。</div>
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
  legend:{data:['T3实际','人工水率(对照)','模型推送水率'],top:10},
  grid:[{left:70,right:40,top:60,height:'34%'},
        {left:70,right:40,top:'56%',height:'32%'}],
  xAxis:[{type:'category',data:D.t,gridIndex:0,axisLabel:{show:false}},
         {type:'category',data:D.t,gridIndex:1}],
  yAxis:[{name:'T3 ℃',gridIndex:0,min:70,max:170},
         {name:'水率 L/t',gridIndex:1,min:540,max:720}],
  series:[
    {name:'T3实际',type:'line',data:D.t3,xAxisIndex:0,yAxisIndex:0,symbol:'none',
     lineStyle:{color:'#555',width:1.4}},
    {name:'带130',type:'line',xAxisIndex:0,yAxisIndex:0,data:[],
     markLine:{silent:true,symbol:'none',label:{formatter:'130℃',position:'insideEndTop'},
       lineStyle:{color:'#c0392b',type:'dashed'},data:[{yAxis:130}]}},
    {name:'带100',type:'line',xAxisIndex:0,yAxisIndex:0,data:[],
     markLine:{silent:true,symbol:'none',label:{formatter:'100℃',position:'insideEndBottom'},
       lineStyle:{color:'#2471a3',type:'dashed'},data:[{yAxis:100}]}},
    {name:'超标背景',type:'line',xAxisIndex:0,yAxisIndex:0,data:[],
     markArea:{silent:true,data:mk(D.over_hi,'rgba(192,57,43,0.10)')
       .concat(mk(D.over_lo,'rgba(36,113,163,0.10)'))}},
    {name:'人工水率(对照)',type:'line',data:D.ratio_act,xAxisIndex:1,yAxisIndex:1,
     symbol:'none',lineStyle:{color:'#888',width:1.4}},
    {name:'模型推送水率',type:'line',data:D.ratio_rec,xAxisIndex:1,yAxisIndex:1,
     symbol:'none',lineStyle:{color:'#1f6feb',width:2},step:'end'}
  ]
});
window.addEventListener('resize',function(){chart.resize();});
</script></body></html>
"""
    html = tpl.replace("__DATA__", json.dumps(D, ensure_ascii=False))
    out = os.path.join(_HERE, "规则响应回放.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)
    print("\n已生成:", out)


if __name__ == "__main__":
    main()
