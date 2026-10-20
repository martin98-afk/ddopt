# -*- coding: utf-8 -*-
"""规则控制器 · 长时段严重越线回放（xsh_clean_10s.csv 的 10-14 班次）。

数据：D:/work/脱硫脱硝/data/xsh_clean_10s.csv（10 秒粒度全测点）
段  ：10-14 22:16 起 552 min，瞬时 T3>130 达 222 min，峰 161.1℃
语义：温度 = 实际曲线（不推演）；水率 = 模型推送自持轨迹（下控语义）

输出 fopdt-dmc/长时段越线回放.html + 终端逐拍动作清单。

用法：python replay_xsh_clean.py
"""
from __future__ import annotations

import csv
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

SRC = r"D:\work\脱硫脱硝\data\xsh_clean_10s.csv"
OUT = os.path.join(_HERE, "长时段越线回放.html")

# 列名 → 宽表 Tag 映射
COL_MAP = {
    "R_sp": Tag.RATIO_SD,
    "R_fb": Tag.RATIO_FK,
    "Fs": Tag.LIME,
    "Fw": Tag.WATER,
    "I1": Tag.CURR1,
    "permit": Tag.PERMIT,
    "fan_exh": Tag.EXHAUST_FAN,
}
for j in range(3):
    for k in range(3):
        COL_MAP["T%d_%d" % (j + 1, k + 1)] = Tag.TEMP[j][k]


def load_and_resample():
    """读 10s csv → 1 分钟均值 → {Tag: array}, T3聚合, 起止时间戳"""
    buf = {name: [] for name in COL_MAP}
    buf["__t3__"] = []
    times = []
    with open(SRC, encoding="utf-8", errors="replace") as f:
        r = csv.reader(f)
        head = next(r)
        idx = {c: head.index(c) for c in head if c in COL_MAP or c == "T3"}
        cur_min = None
        acc = {name: [] for name in list(COL_MAP) + ["__t3__"]}
        for row in r:
            if not row or not row[0]:
                continue
            minute = row[0][:16]        # 精确到分钟
            if minute != cur_min:
                if cur_min is not None:
                    for k, vals in acc.items():
                        vals = [v for v in vals if v is not None]
                        buf[k].append(float(np.mean(vals)) if vals else np.nan)
                    times.append(cur_min)
                cur_min = minute
                acc = {k: [] for k in acc}
            for c, gi in idx.items():
                v = row[gi].strip()
                key = "__t3__" if c == "T3" else c
                acc[key].append(float(v) if v else None)
    for k, vals in acc.items():
        vals = [v for v in vals if v is not None]
        buf[k].append(float(np.mean(vals)) if vals else np.nan)
    times.append(cur_min)

    n = len(times)
    data = {}
    for name, tag in COL_MAP.items():
        arr = np.array(buf[name], float)
        arr[np.isinf(arr)] = np.nan
        data[tag] = arr
    t3 = np.array(buf["__t3__"], float)
    grid = np.arange(n) * 60          # 分钟索引 × 60（controller 索引自洽即可）
    return data, t3, grid, times, n


class MiniTable:
    """轻量宽表：SignalConditioner 需要的最小接口"""

    def __init__(self, data, grid):
        self.d = data
        self.grid = grid

    def series(self, name):
        return self.d.get(name, np.full(len(self.grid), np.nan))

    def __contains__(self, name):
        return True


def main():
    data, t3_act, grid, times, n = load_and_resample()

    # 生产段识别：permit>0.5（与既有口径一致）
    permit = data[Tag.PERMIT]
    prod = permit > 0.5
    dd = np.diff(prod.astype(np.int8))
    starts = list(np.where(dd == 1)[0] + 1)
    ends = list(np.where(dd == -1)[0] + 1)
    if prod[0]:
        starts.insert(0, 0)
    if prod[-1]:
        ends.append(n)

    def score(se):
        s, e = se
        return float(np.nansum(t3_act[s:e + 1] > 130))

    segs = [se for se in zip(starts, ends) if se[1] - se[0] >= 300]
    if not segs:
        print("无 ≥300min 生产段")
        return
    s0, e0 = max(segs, key=score)
    seg = t3_act[s0:e0 + 1]
    print("段: %s ~ %s (%d min)  瞬时>130: %d min  峰: %.1f℃  起点 T3: %.1f℃" % (
        times[s0], times[e0 - 1], e0 - s0, int(np.nansum(seg > 130)),
        float(np.nanmax(seg)), float(seg[0])))

    # ---- 闭环回放：温度=实际，水率=自持推送 ----
    # 只切出本段构造 MiniTable：写入/读取统一用段内局部索引，
    # 避免“全局写、局部读”的索引错位（曾致回放跑到错误时段）
    seg_data = {tag: arr[s0:e0 + 1].copy() for tag, arr in data.items()}
    table = MiniTable(seg_data, grid[s0:e0 + 1] - grid[s0])
    cfg = Config()
    sc = SignalConditioner(table, cfg)
    ctrl = XshController(sc, cfg)

    cur = float(data[Tag.RATIO_SD][s0]) if not np.isnan(data[Tag.RATIO_SD][s0]) \
        and data[Tag.RATIO_SD][s0] > 0 else 630.0
    push = np.full(e0 - s0 + 1, np.nan)
    rec = []
    CTRL = int(cfg.control.control_interval_min)
    for t in range(s0, e0 + 1):
        i = t - s0
        table.d[Tag.RATIO_SD][i] = cur
        table.d[Tag.RATIO_FK][i] = cur
        table.d[Tag.LIME][i] = 3.5        # 下料量视为恒定（无其历史联动）
        push[i] = cur
        if i % CTRL == 0:
            out = ctrl.step(i)
            cur = float(out.ratio_set)
            tv = float(out.temp3) if out.temp3 == out.temp3 else None
            rec.append((i, tv, cur, out.action.value, out.reason))

    print("\n逐拍动作（水率变化 ≥2 L/t 的拍）：")
    print("%-8s %8s %8s | %s" % ("分钟", "T3评估", "推送", "动作/理由"))
    prev = None
    for (tt, tv, rr, act, reason) in rec:
        if prev is not None and abs(rr - prev) >= 2.0:
            tv_s = "%.1f" % tv if tv is not None else "nan"
            print("%-8s %8s %8.0f | %s (%.0f→%.0f)" % (
                tt, tv_s, rr, act, prev, rr))
        prev = rr
    moved = sum(1 for a, b in zip(push[:-1], push[1:]) if abs((b or 0) - (a or 0)) >= 2)
    ok = float(np.mean((seg >= 100) & (seg <= 130)) * 100)
    print("共 %d 拍，水率动作 %d 次，范围 %.0f~%.0f L/t；本段实际 T3 合格率 %.1f%%" % (
        len(rec), moved, np.nanmin(push), np.nanmax(push), ok))

    # ---- HTML ----
    t_axis = [times[i] for i in range(s0, e0 + 1)]
    t3_list = [None if np.isnan(v) else round(float(v), 2) for v in seg]
    push_list = [round(float(v), 1) for v in push]

    over_hi, over_lo, curk, cs = [], [], None, 0
    for i in range(len(seg)):
        v = seg[i]
        kind = "hi" if (v == v and v > 130) else \
            ("lo" if (v == v and v < 100) else None)
        if kind != curk:
            if curk is not None:
                (over_hi if curk == "hi" else over_lo).append([cs, i - 1])
            curk, cs = kind, i
    if curk is not None:
        (over_hi if curk == "hi" else over_lo).append([cs, len(seg) - 1])

    def to_marker(pairs):
        return [[{"xAxis": int(a)}, {"xAxis": int(b)}] for a, b in pairs]

    D = dict(t=t_axis, t3=t3_list, push=push_list,
             over_hi=to_marker(over_hi), over_lo=to_marker(over_lo))

    tpl = """<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8">
<title>规则控制器 · 长时段严重越线回放</title>
<script src="../趋势分析/echarts.min.js"></script>
<style>body{font-family:'Microsoft YaHei',sans-serif;margin:16px;background:#fafafa}
#main{width:96vw;height:760px;background:#fff;border:1px solid #e0e0e0}
.note{color:#666;font-size:13px;line-height:1.7}</style></head>
<body>
<h3>规则控制器 · 长时段严重越线回放（10-14 班次 552 min，T3&gt;130 达 222 min，峰 161℃）</h3>
<div class="note">温度 = 实际曲线；蓝线 = 模型推送水率（下控自持语义）。
红背景 = 实际 T3&gt;130℃，蓝背景 = &lt;100℃。快通道：瞬时&gt;135 当拍触发、豁免节拍、按偏差比例步长。</div>
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
  legend:{data:['T3实际','模型推送水率'],top:10},
  grid:[{left:70,right:40,top:60,height:'34%'},
        {left:70,right:40,top:'56%',height:'32%'}],
  xAxis:[{type:'category',data:D.t,gridIndex:0,axisLabel:{show:false}},
         {type:'category',data:D.t,gridIndex:1}],
  yAxis:[{name:'T3 ℃',gridIndex:0,min:60,max:180},
         {name:'水率 L/t',gridIndex:1,min:540,max:720}],
  series:[
    {name:'T3实际',type:'line',data:D.t3,xAxisIndex:0,yAxisIndex:0,symbol:'none',
     lineStyle:{color:'#555',width:1.2}},
    {name:'带130',type:'line',xAxisIndex:0,yAxisIndex:0,data:[],
     markLine:{silent:true,symbol:'none',label:{formatter:'130℃',position:'insideEndTop'},
       lineStyle:{color:'#c0392b',type:'dashed'},data:[{yAxis:130}]}},
    {name:'带100',type:'line',xAxisIndex:0,yAxisIndex:0,data:[],
     markLine:{silent:true,symbol:'none',label:{formatter:'100℃',position:'insideEndBottom'},
       lineStyle:{color:'#2471a3',type:'dashed'},data:[{yAxis:100}]}},
    {name:'超标背景',type:'line',xAxisIndex:0,yAxisIndex:0,data:[],
     markArea:{silent:true,data:mk(D.over_hi,'rgba(192,57,43,0.10)')
       .concat(mk(D.over_lo,'rgba(36,113,163,0.10)'))}},
    {name:'模型推送水率',type:'line',data:D.push,xAxisIndex:1,yAxisIndex:1,
     symbol:'none',lineStyle:{color:'#1f6feb',width:2},step:'end'}
  ]
});
window.addEventListener('resize',function(){chart.resize();});
</script></body></html>
"""
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(tpl.replace("__DATA__", json.dumps(D, ensure_ascii=False)))
    print("\n已生成:", OUT)


if __name__ == "__main__":
    main()
