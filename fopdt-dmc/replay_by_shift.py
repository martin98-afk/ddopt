# -*- coding: utf-8 -*-
"""按生产班次批量生成「趋势预测控制 vs 人工」对比图（每班次一份独立 HTML）。

方法继承 replay_trend_1014.py：
  · 真对象 = 保守 FOPDT 核 K=-0.151 ℃/(L/t)，τ=60min、θ=30min
  · 共同扰动法：人工与模型共用同一扰动 d[t]（从人工实测反解），
    两方差异只来自水率操作，保证对比公平
  · 人工方 = 实际水率轨迹；模型方 = 现役 TrendController（温度+斜率预测）

输出：<out>/班次_<起始时间>.html（每班次一份）+ <out>/index.html（汇总）

用法：
  python replay_by_shift.py                      # 工作区数据集
  python replay_by_shift.py --min 60             # 只处理 >=60min 的班次
  # 切到 D 盘标定集（8 班次，缓存必须隔离）
  python replay_by_shift.py --data-dir "D:/work/脱硫脱硝/data/脱硫脱硝消石灰制备数据" --cache-dir ".cache_calib" --out "班次对比_标定集"
"""
from __future__ import annotations

import argparse
import glob
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

from config import Tag
from ab_test import response_fast
from fopdt import step_coeffs
from trend import TrendController, slope_linfit

SP = 118.0          # T3 目标
CTRL = 5            # 控制周期（分钟），与人工操作频率对齐
T3_LO, T3_HI = 100.0, 130.0


# ---------------------------------------------------------------- 数据
def load_wide(data_dir=None, cache_dir=None):
    """读分钟网格宽表；data_dir/cache_dir 可显式指定（环境变量只在模块导入时生效）"""
    import data_loader as dl
    if data_dir:
        dl.DATA_DIR = data_dir
    if cache_dir:
        dl.CACHE_DIR = cache_dir
    return dl.build_wide(verbose=False)


def find_shifts(wt, min_len: int = 30):
    """按给水给料允许信号切分生产班次，返回 [(s, e)] 闭区间索引"""
    perm = wt.series(Tag.PERMIT)
    mask = perm > 0.5
    segs, s = [], None
    for i, v in enumerate(mask):
        if v and s is None:
            s = i
        elif not v and s is not None:
            segs.append((s, i - 1))
            s = None
    if s is not None:
        segs.append((s, len(mask) - 1))
    return [se for se in segs if se[1] - se[0] + 1 >= min_len]


# ---------------------------------------------------------------- 指标
def metrics(t3, ratio, lo=T3_LO, hi=T3_HI):
    v = np.asarray(t3, float)
    ok = ~np.isnan(v)
    v, r = v[ok], np.asarray(ratio, float)[ok]
    if v.size == 0:
        return dict(rate=0.0, std=0.0, moves=0, n=0, lo=0.0, hi=0.0)
    return dict(
        rate=float(np.mean((v >= lo) & (v <= hi)) * 100.0),
        std=float(np.std(v)),
        moves=int(np.sum(np.abs(np.diff(r)) >= 2.0)) if r.size > 1 else 0,
        n=int(v.size),
        lo=float(np.nanmin(r)) if r.size else 0.0,
        hi=float(np.nanmax(r)) if r.size else 0.0)


# ---------------------------------------------------------------- 单班次回放
def replay_shift(wt, s0, e0):
    """回放单个班次，返回 (t3_act, r_act, t3_tr, r_tr, m_act, m_tr)"""
    L = e0 - s0 + 1
    t3_all = wt.series(Tag.TEMP[2][0])      # T3-1：唯一干净的三级测点
    R = wt.series(Tag.RATIO_SD)

    # 水率序列（缺测保持前值）
    u_act = np.where(np.isnan(R), 0.0, R).astype(np.float64)
    for i in range(1, len(u_act)):
        if np.isnan(R[i]):
            u_act[i] = u_act[i - 1]

    # 真对象核：稳态增益可信，滞后/时间常数按现实节奏（30/60 min）
    G = step_coeffs(-0.151, 60.0, 30.0, 1.0, L + 61)

    v0 = t3_all[s0]
    base0 = float(v0) if not np.isnan(v0) else 118.0
    resp_act0 = response_fast(u_act, G, s0)

    # 共同扰动：人工实测 − 人工水率下的模型响应
    dv = np.full(L, np.nan)
    for idx, t in enumerate(range(s0, e0 + 1)):
        v = t3_all[t]
        if not np.isnan(v):
            dv[idx] = v - base0 - (response_fast(u_act, G, t) - resp_act0)
    for i in range(1, L):
        if np.isnan(dv[i]):
            dv[i] = dv[i - 1]
    for i in range(L - 2, -1, -1):
        if np.isnan(dv[i]):
            dv[i] = dv[i + 1]
    dv = np.nan_to_num(dv, nan=0.0)

    t3_act = t3_all[s0:e0 + 1].copy()
    ratio_act = u_act[s0:e0 + 1].copy()

    # 模型方：趋势预测控制器闭环
    cur = 600.0
    trend = TrendController(target=SP, u_init=cur)
    t3_tr = np.full(L, np.nan)
    ratio_tr = np.full(L, np.nan)
    hist = []
    u_work = u_act.copy()
    for i in range(L):
        t_end = s0 + i
        u_work[s0:t_end + 1] = cur
        v = base0 + (response_fast(u_work, G, t_end) - resp_act0) + dv[i]
        t3_tr[i] = v
        hist.append(v)
        if i % CTRL == 0:
            cur = trend.update(v, slope_linfit(hist[-15:]))
        ratio_tr[i] = cur

    m_act = metrics(t3_act, ratio_act)
    m_tr = metrics(t3_tr, ratio_tr)
    return t3_act, ratio_act, t3_tr, ratio_tr, m_act, m_tr


# ---------------------------------------------------------------- HTML
def _ln(a, nd=2):
    return [None if (v is None or v != v) else round(float(v), nd) for v in a]


def build_html(title, sub, times, t3_act, t3_tr, r_act, r_tr, m_act, m_tr):
    """生成单班次对比 HTML"""
    over_hi, over_lo, curk, cs = [], [], None, 0
    for i, v in enumerate(t3_act):
        kind = "hi" if (v == v and v > T3_HI) else \
            ("lo" if (v == v and v < T3_LO) else None)
        if kind != curk:
            if curk is not None:
                (over_hi if curk == "hi" else over_lo).append([cs, i - 1])
            curk, cs = kind, i
    if curk is not None:
        (over_hi if curk == "hi" else over_lo).append([cs, len(t3_act) - 1])

    def mk(pairs, color):
        return [[{"xAxis": int(a), "itemStyle": {"color": color}},
                 {"xAxis": int(b)}] for a, b in pairs]

    D = dict(t=list(times),
             t3_act=_ln(t3_act), t3_tr=_ln(t3_tr),
             r_act=_ln(r_act, 1), r_tr=_ln(r_tr, 1),
             over_hi=[[{"xAxis": int(a)}, {"xAxis": int(b)}] for a, b in over_hi],
             over_lo=[[{"xAxis": int(a)}, {"xAxis": int(b)}] for a, b in over_lo])

    tpl = """<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8">
<title>__TITLE__</title>
<script src="../../趋势分析/echarts.min.js"></script>
<style>body{font-family:'Microsoft YaHei',sans-serif;margin:16px;background:#fafafa}
#main{width:96vw;height:760px;background:#fff;border:1px solid #e0e0e0}
.note{color:#666;font-size:13px;line-height:1.7}
.kpi{display:flex;gap:28px;margin:10px 0 12px;font-size:14px}
.kpi div{background:#fff;border:1px solid #e0e0e0;padding:8px 14px;border-radius:4px}
.kpi b{font-size:18px;margin-left:6px}
.up{color:#1a9c6e}.down{color:#c0392b}</style></head>
<body>
<h3>__TITLE__</h3>
<div class="note">__SUB__</div>
<div class="kpi">
  <div>人工合格率<b>__R1__%</b></div>
  <div>模型合格率<b class="__CLS__">__R2__%</b></div>
  <div>提升<b class="__CLS__">__DR__ 个百分点</b></div>
  <div>T3 标准差 人工 __S1__ / 模型 __S2__</div>
  <div>水率动作 人工 __M1__ 次 / 模型 __M2__ 次</div>
</div>
<div id="main"></div>
<script>
var D = __DATA__;
function mk(pairs,color){return pairs.map(function(p){return [
  {xAxis:p[0].xAxis,itemStyle:{color:color}},
  {xAxis:p[1].xAxis,itemStyle:{color:color}}];});}
var chart = echarts.init(document.getElementById('main'));
chart.setOption({animation:false,
  axisPointer:{link:[{xAxisIndex:'all'}]},
  tooltip:{trigger:'axis'},
  legend:{top:10,data:[
    {name:'T3人工',itemStyle:{color:'#888'}},
    {name:'T3模型',itemStyle:{color:'#1a9c6e'}},
    {name:'水率人工',itemStyle:{color:'#888'}},
    {name:'水率模型',itemStyle:{color:'#1a9c6e'}}]},
  grid:[{left:70,right:40,top:60,height:'34%'},
        {left:70,right:40,top:'56%',height:'32%'}],
  xAxis:[{type:'category',data:D.t,gridIndex:0,axisLabel:{show:false}},
         {type:'category',data:D.t,gridIndex:1}],
  yAxis:[{name:'T3 ℃',gridIndex:0,min:40,max:180},
         {name:'水率 L/t',gridIndex:1,min:300,max:720}],
  series:[
    {name:'T3人工',type:'line',data:D.t3_act,xAxisIndex:0,yAxisIndex:0,symbol:'none',
     lineStyle:{color:'#888',width:1.2}},
    {name:'T3模型',type:'line',data:D.t3_tr,xAxisIndex:0,yAxisIndex:0,symbol:'none',
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
    {name:'水率模型',type:'line',data:D.r_tr,xAxisIndex:1,yAxisIndex:1,
     symbol:'none',lineStyle:{color:'#1a9c6e',width:2},step:'end'}
  ]
});
window.addEventListener('resize',function(){chart.resize();});
</script></body></html>
"""
    dr = m_tr["rate"] - m_act["rate"]
    cls = "up" if dr >= 0 else "down"
    return (tpl.replace("__TITLE__", title)
               .replace("__SUB__", sub)
               .replace("__DATA__", json.dumps(D, ensure_ascii=False))
               .replace("__R1__", "%.1f" % m_act["rate"])
               .replace("__R2__", "%.1f" % m_tr["rate"])
               .replace("__DR__", "%+.1f" % dr)
               .replace("__CLS__", cls)
               .replace("__S1__", "%.2f" % m_act["std"])
               .replace("__S2__", "%.2f" % m_tr["std"])
               .replace("__M1__", str(m_act["moves"]))
               .replace("__M2__", str(m_tr["moves"])))


def build_index(rows, subtitle=""):
    """班次汇总页"""
    items = "\n".join(
        '<tr><td><a href="%s">%s</a></td><td>%d</td><td>%d</td>'
        '<td>%.1f%%</td><td class="%s">%s</td><td>%.2f</td><td>%.2f</td></tr>' % (
            r["file"], r["label"], r["minutes"], r["over"],
            r["m_act"], "up" if r["dr"] >= 0 else "down",
            "%+.1f" % r["dr"], r["std_act"], r["std_tr"])
        for r in rows)
    return """<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8"><title>各生产班次对比汇总</title>
<style>body{font-family:'Microsoft YaHei',sans-serif;margin:20px;background:#fafafa}
table{border-collapse:collapse;background:#fff}
th,td{border:1px solid #ddd;padding:8px 14px;font-size:14px;text-align:center}
th{background:#f0f0f0}a{color:#1f6feb;text-decoration:none}
.up{color:#1a9c6e;font-weight:bold}.down{color:#c0392b;font-weight:bold}
.note{color:#666;font-size:13px;margin:12px 0}</style></head><body>
<h3>各生产班次 · 趋势预测控制 vs 人工</h3>
<div class="note">每个班次一份独立对比图。合格率 = T3 落在 100~130℃ 的时间占比；
方法 = 响应核推演 + 共同扰动法（两方共用同一扰动，差异只来自水率操作）。
%s</div>
<table><tr><th>班次</th><th>时长 min</th><th>人工>130℃ min</th>
<th>人工合格率</th><th>模型提升</th><th>人工σ</th><th>模型σ</th></tr>
%s</table></body></html>""" % (subtitle, items)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--min", type=int, default=30, help="最小时长（分钟）")
    ap.add_argument("--data-dir", default=None,
                    help="数据集目录（含 dbName_db101-*.zip）；缺省用工作区数据")
    ap.add_argument("--cache-dir", default=None,
                    help="缓存目录（不同数据集必须隔离）")
    ap.add_argument("--out", default=None, help="输出目录（默认 班次对比/）")
    a = ap.parse_args()

    if a.data_dir:
        os.environ["XSH_DATA_DIR"] = a.data_dir
    if a.cache_dir:
        os.environ["XSH_CACHE_DIR"] = a.cache_dir
    out_dir = a.out or os.path.join(_HERE, "班次对比")

    os.makedirs(out_dir, exist_ok=True)
    for f in glob.glob(os.path.join(out_dir, "*.html")):
        os.remove(f)        # 清旧产物，避免班次变化后残留

    wt = load_wide(a.data_dir, a.cache_dir)
    shifts = find_shifts(wt, min_len=a.min)
    if not shifts:
        print("没有满足时长要求的班次")
        return

    rows = []
    for k, (s0, e0) in enumerate(shifts, 1):
        L = e0 - s0 + 1
        stamp = _t.strftime("%m%d_%H%M", _t.localtime(wt.grid[s0]))
        label = "%s ~ %s" % (_t.strftime("%m-%d %H:%M", _t.localtime(wt.grid[s0])),
                             _t.strftime("%m-%d %H:%M", _t.localtime(wt.grid[e0])))
        times = [_t.strftime("%m-%d %H:%M", _t.localtime(wt.grid[i]))
                 for i in range(s0, e0 + 1)]

        (t3_act, r_act, t3_tr, r_tr, m_act, m_tr) = replay_shift(wt, s0, e0)
        over = int(np.nansum(np.asarray(t3_act, float) > T3_HI))
        dr = m_tr["rate"] - m_act["rate"]

        title = "班次 %d · %s" % (k, label)
        sub = ("段长 %d min，人工实测 T3>130℃ %d min。灰=人工实际；绿=趋势预测模型"
               "（当前温度+斜率预测未来 %.0fmin，提前干预，双向连续调节）。"
               "红背景=人工实测 T3>130℃，蓝背景=<100℃。" % (L, over, 15.0))
        html = build_html(title, sub, times, t3_act, t3_tr, r_act, r_tr,
                          m_act, m_tr)
        fname = "班次_%s.html" % stamp
        with open(os.path.join(out_dir, fname), "w", encoding="utf-8") as f:
            f.write(html)

        rows.append(dict(file=fname, label=label, minutes=L, over=over,
                         m_act=m_act["rate"], m_tr=m_tr["rate"], dr=dr,
                         std_act=m_act["std"], std_tr=m_tr["std"]))
        print("班次 %d  %s  %4d min  人工 %.1f%% → 模型 %.1f%%  (%+.1f)  → %s" % (
            k, label, L, m_act["rate"], m_tr["rate"], dr, fname))

    subtitle = "数据源：%s" % (a.data_dir or "工作区默认数据集")
    with open(os.path.join(out_dir, "index.html"), "w", encoding="utf-8") as f:
        f.write(build_index(rows, subtitle))
    print("\n共 %d 个班次，输出目录: %s" % (len(rows), out_dir))


if __name__ == "__main__":
    main()
