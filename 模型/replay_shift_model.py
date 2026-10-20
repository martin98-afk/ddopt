# -*- coding: utf-8 -*-
"""
标定集班次对比 · 实际模型闭环回放（趋势控制）

与 fopdt-dmc/replay_by_shift.py 的区别：
  那个脚本用自带的简化仿真（自己写 TrendController 调用 + 手写 FOPDT 核），
  不读 config.py，也不经 controller.py。
  本脚本直接跑**现役生产代码**：
      XshController(cfg) + SignalConditioner + 真实 per-tick 决策，
      温度控制走 trend.py，电流规则走 controller._curr_rule_logic。
  唯一被仿真替代的是「温度对水率的响应」——用单调 FOPDT 核 + 共同扰动法推演，
  与 A/B 方法一致，保证人工与模型面对完全相同的扰动。

数据源：D:/work/脱硫脱硝/data/脱硫脱硝消石灰制备数据（标定集，8 班次）
缓存  ：模型/.cache_calib（与工作区数据集隔离）
输出  ：模型/班次对比_标定集/（每班次一份 HTML + index.html）

用法：
  python replay_shift_model.py
  python replay_shift_model.py --min 60 --step 10
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
import time as _t

import numpy as np

BASE = os.path.dirname(os.path.abspath(__file__))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

import data_loader  # noqa: E402

DATA_DIR = r"D:/work/脱硫脱硝/data/脱硫脱硝消石灰制备数据"
CACHE_DIR = os.path.join(BASE, ".cache_calib")

from config import Config, Tag          # noqa: E402
from controller import XshController    # noqa: E402
from signal_conditioning import SignalConditioner  # noqa: E402

SP = 118.0
CTRL = 10               # 控制周期（分钟），与生产默认一致
T3_LO, T3_HI = 100.0, 130.0
KERNEL_LEN = 61


# ============================================================ 仿真宽表
class SimTable:
    """可写宽表：T3 三测点 / 水率设定 / 生石灰流量可覆盖，其余读真实值"""

    def __init__(self, wt):
        self.wt = wt
        self.grid = wt.grid
        self._ov = {}
        for nm in list(Tag.TEMP[2]) + [Tag.RATIO_SD, Tag.RATIO_FK, Tag.LIME]:
            self._ov[nm] = wt.series(nm).copy()

    def set_t3(self, i, v):
        for nm in Tag.TEMP[2]:
            self._ov[nm][i] = v

    def set_ratio(self, i, v):
        self._ov[Tag.RATIO_SD][i] = v
        self._ov[Tag.RATIO_FK][i] = v

    def set_lime(self, i, v):
        self._ov[Tag.LIME][i] = v

    def series(self, name):
        if name in self._ov:
            return self._ov[name]
        return self.wt.series(name)

    def __contains__(self, name):
        return True


def response_fast(u, G, t):
    """Σ g[k]·Δu[t-k]：向量化冲激响应点积"""
    K = len(G)
    if t + 1 < K:
        du = np.diff(u[:t + 1])
        return float(np.dot(G[:du.size][::-1], du))
    du = np.diff(u[t - K + 1:t + 1])
    return float(np.dot(G[:du.size][::-1], du))


# 对象核：单调滞后负响应 FOPDT（K=−0.151 ℃/(L/t)、τ=60min、θ=30min）。
# 为什么不用实测辨识核 G_OLD：它的前段正峰（+0.4675 ℃/(L/t) @5min）已被
# 验证为操作员反馈伪影（滞合互相关 lag=−5 corr=+0.44，T3 先升→操作员后加水）。
# 拿伪影峰做覆盖式闭环推演，水率从 300 抬到 690（Δu=+390）会让 T3 凭空
# 跳 +182℃，图上表现为开头冲上 155、掉出 <80 的剧烈振荡，纯属模型失真。
# 单调核不含正峰，滞后段不起作用，不会造出这种假振荡。
K_TAIL = -0.151
TAU = 60.0
THETA = 30.0


def fopdt_kernel(n=KERNEL_LEN, K=K_TAIL, tau=TAU, theta=THETA):
    """FOPDT 单调阶跃响应核：K·(1 − e^(−(t−θ)/τ))，θ 前为 0，无正峰"""
    t = np.arange(n, dtype=float)
    g = np.zeros(n)
    m = t >= theta
    g[m] = K * (1.0 - np.exp(-(t[m] - theta) / tau))
    return g


def extend_kernel(G, total_min):
    """尾部用稳态增益延伸到 total_min+1 长。

    必须延伸：FIR 核若不延伸，阶跃的稳态效应会在核尾之后被洗掉
    （水率差 40 L/t 的稳态温差 +6℃ 凭空消失），
    不同水率策略的 T3 轨迹会在稳态段虚假重合。
    """
    G = np.asarray(G, float)
    if total_min + 1 <= len(G):
        return G[:total_min + 1]
    return np.concatenate([G, np.full(total_min + 1 - len(G), G[-1])])


def ffill(arr):
    out = arr.astype(np.float64, copy=True)
    for i in range(1, out.size):
        if np.isnan(out[i]):
            out[i] = out[i - 1]
    return out


def find_shifts(wt, min_len=30):
    perm = wt.series(Tag.PERMIT) > 0.5
    segs, s = [], None
    for i, v in enumerate(perm):
        if v and s is None:
            s = i
        elif not v and s is not None:
            segs.append((s, i - 1))
            s = None
    if s is not None:
        segs.append((s, perm.size - 1))
    return [se for se in segs if se[1] - se[0] + 1 >= min_len]


def metrics(t3, ratio):
    v = np.asarray(t3, float)
    r = np.asarray(ratio, float)
    ok = ~np.isnan(v)
    v2, r2 = v[ok], r[ok]
    if v2.size == 0:
        return dict(rate=0.0, std=0.0, moves=0, n=0,
                    above=0.0, below=0.0, r_lo=0.0, r_hi=0.0)
    return dict(
        rate=float(np.mean((v2 >= T3_LO) & (v2 <= T3_HI)) * 100.0),
        std=float(np.std(v2)),
        moves=int(np.sum(np.abs(np.diff(r2)) >= 2.0)) if r2.size > 1 else 0,
        n=int(v2.size),
        above=float(np.mean(v2 > T3_HI) * 100.0),
        below=float(np.mean(v2 < T3_LO) * 100.0),
        r_lo=float(np.nanmin(r2)), r_hi=float(np.nanmax(r2)))


# ============================================================ 单班次回放
def replay_shift(wt, s0, e0, G, T3, R, curr_x=18.0):
    """跑真实控制器；温度用单调 FOPDT 核 + 共同扰动推演"""
    n = wt.grid.size
    L = e0 - s0 + 1

    u_act_full = ffill(np.where(np.isnan(R), 0.0, R))
    base0 = T3[s0] if not np.isnan(T3[s0]) else SP
    resp_act0 = response_fast(u_act_full, G, s0)

    # 共同扰动：人工实测 − 人工水率下的模型响应
    d = np.full(L, np.nan)
    for idx, t in enumerate(range(s0, e0 + 1)):
        if np.isnan(T3[t]):
            continue
        d[idx] = T3[t] - base0 - (response_fast(u_act_full, G, t) - resp_act0)
    d = ffill(d)
    for i in range(L - 2, -1, -1):
        if np.isnan(d[i]):
            d[i] = d[i + 1]
    d = np.nan_to_num(d, nan=0.0)

    cfg = Config()
    cfg.set_curr1_high(curr_x)
    sim = SimTable(wt)
    sc = SignalConditioner(sim, cfg)
    ctrl = XshController(sc, cfg)

    u_sim = u_act_full.copy()
    t3_sim = np.full(L, np.nan)
    ratio_sim = np.full(L, np.nan)
    lime_sim = np.full(L, np.nan)

    # 起手用现场实际设定值 / 实测给料，让模型从现场状态接管
    r0 = R[s0]
    cur_ratio = float(r0) if (r0 == r0 and r0 > 0) else cfg.control.ratio_init
    lime0 = np.nanmean(wt.series(Tag.LIME)[s0:s0 + 10])
    cur_lime = float(lime0) if (lime0 == lime0 and lime0 > 0) \
        else cfg.control.lime_field_sp

    acts = []
    last_dec_idx = -10 ** 6
    last_sig = None
    for t in range(s0, e0 + 1):
        sim.set_ratio(t, cur_ratio)
        sim.set_lime(t, cur_lime)
        # 覆盖式：把整段历史水率视为当前值（与 fopdt-dmc/replay_by_shift.py、
        # ab_test.py 同口径）。原理由：因果叠加式（只写当前点）会把每次
        # 10min 的水率抖动累加成对象响应滞后段上的叠加，仿真自激振荡，
        # 所有班次降到 13~35%（实测同班次 87%，因果式 13.6%），
        # 失去对比意义。
        u_sim[s0:t + 1] = cur_ratio

        v = base0 + (response_fast(u_sim, G, t) - resp_act0) + d[t - s0]
        if not np.isnan(v):
            sim.set_t3(t, v)
            t3_sim[t - s0] = v
        ratio_sim[t - s0] = cur_ratio
        lime_sim[t - s0] = cur_lime

        if (t - s0) % CTRL == 0:
            out = ctrl.step(t)
            cur_ratio = float(out.ratio_set)
            cur_lime = float(out.lime_set)
            sig = (out.action.value, round(cur_ratio, 1), round(cur_lime, 2))
            if sig != last_sig:
                acts.append(dict(t=t - s0, action=out.action.value,
                                 ratio=round(cur_ratio, 1),
                                 lime=round(cur_lime, 2),
                                 reason=out.reason))
                last_sig = sig
            last_dec_idx = t

    return dict(
        t3_act=T3[s0:e0 + 1].copy(),
        t3_sim=t3_sim,
        ratio_act=R[s0:e0 + 1].copy(),
        ratio_sim=ratio_sim,
        lime_act=wt.series(Tag.LIME)[s0:e0 + 1].copy(),
        lime_sim=lime_sim,
        acts=acts,
        u_init=u_act_full[s0],
        lime_init=cur_lime,
    )


# ============================================================ HTML
def _ln(a, nd=2):
    return [None if (v is None or v != v) else round(float(v), nd) for v in a]


TPL = """<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8">
<title>__TITLE__</title>
<script src="../../趋势分析/echarts.min.js"></script>
<style>
body{font-family:'Microsoft YaHei',sans-serif;margin:16px;background:#fafafa}
#main{width:96vw;height:760px;background:#fff;border:1px solid #e0e0e0}
.note{color:#666;font-size:13px;margin:10px 0;line-height:1.7}
.kpi{display:flex;gap:16px;flex-wrap:wrap;margin:12px 0}
.card{background:#fff;border:1px solid #e0e0e0;border-radius:8px;
      padding:10px 16px;min-width:120px}
.card b{display:block;font-size:20px;margin-top:4px}
.up{color:#1a9c6e}.down{color:#c0392b}
table{border-collapse:collapse;background:#fff;margin:8px 0}
th,td{border:1px solid #ddd;padding:6px 10px;font-size:13px;text-align:center}
th{background:#f0f0f0}
</style></head><body>
<h3>__TITLE__</h3>
<div class="note">__SUB__</div>
<div class="kpi">
  <div class="card">人工合格率<b>__R1__%</b></div>
  <div class="card">模型合格率<b>__R2__%</b></div>
  <div class="card">提升<b class="__CLS__">__DR__</b></div>
  <div class="card">人工σ<b>__S1__</b></div>
  <div class="card">模型σ<b>__S2__</b></div>
  <div class="card">水率动作数<b>__M1__ / __M2__</b></div>
</div>
<div id="main"></div>
<script>
var D = __DATA__;
var chart = echarts.init(document.getElementById('main'));
function mk(ranges,color){return (ranges||[]).map(function(pr){
  return [{xAxis:pr[0].xAxis,itemStyle:{color:color}},
          {xAxis:pr[1].xAxis}];});}
chart.setOption({
  animation:false,
  tooltip:{trigger:'axis'},
  legend:{data:['T3人工','T3模型','水率人工','水率模型'],top:4},
  axisPointer:{link:[{xAxisIndex:'all'}]},
  grid:[{left:60,right:40,top:44,height:'48%'},
        {left:60,right:40,top:'62%',height:'26%'}],
  xAxis:[{type:'category',data:D.times,gridIndex:0,axisLabel:{show:false}},
         {type:'category',data:D.times,gridIndex:1,axisLabel:{fontSize:10}}],
  yAxis:[{type:'value',name:'T3 ℃',gridIndex:0,min:80,max:160},
         {type:'value',name:'水率 L/t',gridIndex:1,min:450,max:720}],
  series:[
    {name:'T3人工',type:'line',data:D.t3_act,symbol:'none',
     lineStyle:{color:'#888',width:1.4},
     markArea:{silent:true,data:[].concat(
        mk(D.over_hi,'rgba(192,57,43,0.10)'),
        mk(D.over_lo,'rgba(36,113,163,0.08)'))}},
    {name:'T3模型',type:'line',data:D.t3_sim,symbol:'none',
     lineStyle:{color:'#1a9c6e',width:2.2}},
    {name:'水率人工',type:'line',data:D.r_act,xAxisIndex:1,yAxisIndex:1,
     symbol:'none',lineStyle:{color:'#888',width:1.4}},
    {name:'水率模型',type:'line',data:D.r_sim,xAxisIndex:1,yAxisIndex:1,
     symbol:'none',step:'end',lineStyle:{color:'#1a9c6e',width:2}}
  ]
});
window.addEventListener('resize',function(){chart.resize();});
</script>
</body></html>
"""


def build_html(title, sub, times, r, m_act, m_sim):
    def spans(vals, pred):
        out, cur, cs = [], None, 0
        for i, v in enumerate(vals):
            k = pred(v)
            if k != cur:
                if cur:
                    out.append([cs, i - 1])
                cur, cs = k, i
        if cur:
            out.append([cs, len(vals) - 1])
        return [[{"xAxis": int(a)}, {"xAxis": int(b)}] for a, b in out]

    D = dict(times=times,
             t3_act=_ln(r["t3_act"], 1), t3_sim=_ln(r["t3_sim"], 1),
             r_act=_ln(r["ratio_act"], 0), r_sim=_ln(r["ratio_sim"], 0),
             over_hi=spans(r["t3_act"], lambda v: v == v and v > T3_HI),
             over_lo=spans(r["t3_act"], lambda v: v == v and v < T3_LO))
    dr = m_sim["rate"] - m_act["rate"]
    return (TPL.replace("__TITLE__", title)
               .replace("__SUB__", sub)
               .replace("__DATA__", json.dumps(D, ensure_ascii=False))
               .replace("__R1__", "%.1f" % m_act["rate"])
               .replace("__R2__", "%.1f" % m_sim["rate"])
               .replace("__DR__", "%+.1f" % dr)
               .replace("__CLS__", "up" if dr >= 0 else "down")
               .replace("__S1__", "%.2f" % m_act["std"])
               .replace("__S2__", "%.2f" % m_sim["std"])
               .replace("__M1__", str(m_act["moves"]))
               .replace("__M2__", str(m_sim["moves"])))


def build_index(rows, subtitle):
    items = "\n".join(
        '<tr><td><a href="%s">%s</a></td><td>%d</td><td>%.1f%%</td>'
        '<td>%.1f%%</td><td class="%s">%s</td><td>%.2f</td><td>%.2f</td>'
        '<td>%.1f%%</td><td>%.1f%%</td><td>%.0f~%.0f</td></tr>' % (
            r["file"], r["label"], r["minutes"],
            r["m_act"]["rate"], r["m_sim"]["rate"],
            "up" if r["dr"] >= 0 else "down", "%+.1f" % r["dr"],
            r["m_act"]["std"], r["m_sim"]["std"],
            r["m_act"]["above"], r["m_sim"]["above"],
            r["m_sim"]["r_lo"], r["m_sim"]["r_hi"])
        for r in rows)
    n = len(rows)
    dr = sum(r["dr"] * r["minutes"] for r in rows) / max(
        1, sum(r["minutes"] for r in rows))
    return """<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8"><title>标定集班次对比 · 实际模型</title>
<style>body{font-family:'Microsoft YaHei',sans-serif;margin:20px;background:#fafafa}
table{border-collapse:collapse;background:#fff}
th,td{border:1px solid #ddd;padding:8px 12px;font-size:13px;text-align:center}
th{background:#f0f0f0}a{color:#1f6feb;text-decoration:none}
.up{color:#1a9c6e;font-weight:bold}.down{color:#c0392b;font-weight:bold}
.note{color:#666;font-size:13px;margin:12px 0;line-height:1.7}</style></head><body>
<h3>标定集 · 实际模型（趋势控制）vs 人工</h3>
<div class="note">
每个班次一份独立对比图。合格率 = T3 落在 100~130℃ 的时间占比。<br>
模型方 = <b>现役生产代码</b>（XshController + trend.TrendController + 电流规则），
控制周期 %d min；温度响应用单调 FOPDT 核（K=−0.151 ℃/(L/t)、τ=60min、θ=30min，
无前段正峰）
+ 共同扰动法推演，两方共用同一扰动，差异只来自水率操作。
温度推演采「覆盖式」（整段历史水率视为当前值），与 模型/ab_test.py、
fopdt-dmc/replay_by_shift.py 同口径；因果叠加式在 10min 控制周期下会自激振荡。<br>
%s<br>
加权平均提升（按时长）：<b>%+.1f 个百分点</b>，共 %d 个班次。
</div>
<table>
<tr><th>班次</th><th>时长</th><th>人工合格</th><th>模型合格</th><th>提升</th>
<th>人工σ</th><th>模型σ</th><th>人工>130</th><th>模型>130</th><th>模型水率范围</th></tr>
%s
</table></body></html>""" % (CTRL, subtitle, dr, n, items)


# ============================================================ main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--min", type=int, default=30, help="最小时长（分钟）")
    ap.add_argument("--out", default=os.path.join(BASE, "班次对比_标定集"))
    a = ap.parse_args()

    data_loader.DATA_DIR = DATA_DIR
    data_loader.CACHE_DIR = CACHE_DIR
    os.makedirs(CACHE_DIR, exist_ok=True)
    os.makedirs(a.out, exist_ok=True)
    for f in glob.glob(os.path.join(a.out, "*.html")):
        os.remove(f)

    t0 = _t.time()
    wt = data_loader.build_wide(verbose=False)
    R = wt.series(Tag.RATIO_SD)
    # T3 口径与既有 班次对比_标定集 一致：只用 T3-1（唯一干净的三级测点），
    # 保证本表可与 fopdt-dmc/replay_by_shift.py 的产物逐行对照。
    T3 = wt.series(Tag.TEMP[2][0])
    shifts = find_shifts(wt, a.min)

    kmax = max([e0 - s0 + 1 for s0, e0 in shifts] or [0]) + KERNEL_LEN
    G = extend_kernel(fopdt_kernel(max(kmax, 400)), max(kmax, 400))
    print("=" * 88)
    print("标定集班次对比 · 实际模型闭环（趋势控制 + 电流规则）")
    print("=" * 88)
    print("数据源: %s" % DATA_DIR)
    print("响应核: 单调 FOPDT K=%.3f ℃/(L/t) τ=%.0fmin θ=%.0fmin（无正峰）" % (
        G[-1], TAU, THETA))
    print("班次  : %d 个（>=%d min）" % (len(shifts), a.min))
    print("-" * 88)
    print("%-20s %5s | %8s %8s %8s | %8s %8s %8s" % (
        "班次", "时长", "人工合格", "人工σ", "人工>130",
        "模型合格", "模型σ", "模型>130"))

    rows = []
    for k, (s0, e0) in enumerate(shifts, 1):
        L = e0 - s0 + 1
        stamp = _t.strftime("%m%d_%H%M", _t.localtime(wt.grid[s0]))
        label = "%s ~ %s" % (
            _t.strftime("%m-%d %H:%M", _t.localtime(wt.grid[s0])),
            _t.strftime("%m-%d %H:%M", _t.localtime(wt.grid[e0])))
        times = [_t.strftime("%m-%d %H:%M", _t.localtime(wt.grid[i]))
                 for i in range(s0, e0 + 1)]

        r = replay_shift(wt, s0, e0, G, T3, R)
        m_act = metrics(r["t3_act"], r["ratio_act"])
        m_sim = metrics(r["t3_sim"], r["ratio_sim"])
        dr = m_sim["rate"] - m_act["rate"]

        title = "班次 %d · %s" % (k, label)
        sub = ("段长 %d min。灰=人工实际，绿=现役模型（趋势控制 + 电流规则，"
               "控制周期 %d min）。红背景=人工 T3>130℃，蓝背景=<100℃。"
               "起手水率 %.0f L/t。" % (L, CTRL, r["u_init"]))
        html = build_html(title, sub, times, r, m_act, m_sim)
        fname = "班次_%s.html" % stamp
        with open(os.path.join(a.out, fname), "w", encoding="utf-8") as f:
            f.write(html)

        rows.append(dict(file=fname, label=label, minutes=L,
                         m_act=m_act, m_sim=m_sim, dr=dr))
        print("%-20s %5d | %7.1f%% %8.2f %7.1f%% | %7.1f%% %8.2f %7.1f%%  %+.1f" % (
            label, L, m_act["rate"], m_act["std"], m_act["above"],
            m_sim["rate"], m_sim["std"], m_sim["above"], dr))

    subtitle = "数据源：%s<br>缓存：%s" % (DATA_DIR, CACHE_DIR)
    with open(os.path.join(a.out, "index.html"), "w", encoding="utf-8") as f:
        f.write(build_index(rows, subtitle))

    tot = sum(r["minutes"] for r in rows)
    wa = sum(r["m_act"]["rate"] * r["minutes"] for r in rows) / max(1, tot)
    ws = sum(r["m_sim"]["rate"] * r["minutes"] for r in rows) / max(1, tot)
    print("-" * 88)
    print("加权平均：人工 %.1f%%  →  模型 %.1f%%   (%+.1f 个百分点)" % (
        wa, ws, ws - wa))
    print("共 %d 班次，输出目录: %s   用时 %.1fs" % (
        len(rows), a.out, _t.time() - t0))


if __name__ == "__main__":
    main()
