# -*- coding: utf-8 -*-
"""predict_min=8 vs 15 的闭环曲线对比。

改参数的依据与验证结果都在这里，跑完直接出曲线数据。

运行：python 前瞻对比.py
"""
from __future__ import annotations

import json
import os
import sys

import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
_MODEL_DIR = os.path.join(os.path.dirname(_HERE), "模型")
for _p in (_HERE, _MODEL_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

os.environ.setdefault(
    "XSH_DATA_DIR",
    r"D:\work\梅钢脱硫脱硝\data\脱硫脱硝消石灰制备数据")

from config import Tag                                       # noqa: E402
from controller import XshController                         # noqa: E402
from signal_conditioning import SignalConditioner            # noqa: E402
from data_loader import build_wide                           # noqa: E402
from trend import TrendController                            # noqa: E402

import 标定参数 as P                                           # noqa: E402
from controller_ppi import make_config                       # noqa: E402
import 重标定对比 as R                                          # noqa: E402

PLANT = dict(K=-0.151, tau=60.0, theta=30.0)
KLEN = 601


def run(wt, s, e, predict_min, Gex, dt=10.0):
    L = e - s
    t3m = np.nanmean(np.vstack([wt.series(t) for t in Tag.TEMP[2]]),
                     axis=0)[s:e]
    u_act = R.ffill(wt.series(Tag.RATIO_SD)[s:e])
    base0 = t3m[0] if not np.isnan(t3m[0]) else P.TARGET_T3
    resp0 = R.response(u_act, Gex, 0)
    d = np.full(L, np.nan)
    for t in range(L):
        if not np.isnan(t3m[t]):
            d[t] = t3m[t] - base0 - (R.response(u_act, Gex, t) - resp0)
    d = R.ffill(d)
    for i in range(L - 2, -1, -1):
        if np.isnan(d[i]):
            d[i] = d[i + 1]
    d = np.nan_to_num(d, nan=0.0)

    cfg = make_config()
    cfg.control.control_interval_min = dt
    cfg.control.gap_tolerance = dt
    sim = R.SimTable(wt)
    sc = SignalConditioner(sim, cfg)
    ctrl = XshController(sc, cfg)
    # 必须用现役的 trend_kp=2.0（不是预测PI 的 P.KP=3.0）
    ctrl._trend = TrendController(
        target=cfg.safety.temp3_target,
        kp=cfg.control.trend_kp,
        predict_min=predict_min,
        dead=cfg.control.trend_dead,
        dead_slope=cfg.control.trend_dead_slope,
        step_max=cfg.control.trend_step_max,
        step_fast=cfg.control.trend_step_fast,
        fast_hi=cfg.control.temp3_fast_high,
        fast_lo=cfg.control.temp3_fast_low,
        u_lo=max(cfg.safety.ratio_safe_min, cfg.control.trend_ratio_lo),
        u_hi=cfg.control.ratio_op_max,
        u_init=cfg.control.ratio_init)

    u_sim = u_act.copy()
    cur = float(u_act[0]) if u_act[0] > 0 else P.RATIO_INIT
    lime0 = np.nanmean(wt.series(Tag.LIME)[s:s + 10])
    curl = float(lime0) if lime0 == lime0 else P.LIME_SP
    t3 = np.full(L, np.nan)
    rat = np.full(L, np.nan)
    for t in range(L):
        sim.set_ratio(s + t, cur)
        sim.set_lime(s + t, curl)
        u_sim[t] = cur
        v = base0 + (R.response(u_sim, Gex, t) - resp0) + d[t]
        if not np.isnan(v):
            sim.set_t3(s + t, v)
            t3[t] = v
        rat[t] = cur
        if t % int(dt) == 0:
            o = ctrl.step(s + t)
            cur = float(o.ratio_set)
            curl = float(o.lime_set)
    return t3, rat, t3m


def band(v):
    x = v[~np.isnan(v)]
    return round(float(np.mean((x >= 100) & (x <= 130)) * 100), 1) \
        if x.size else 0.0


def main():
    wt = build_wide(verbose=False)
    segs = R.segments(wt)
    maxlen = max(e - s for s, e in segs)
    Gex = R.extend(R.fopdt_kernel(K=PLANT["K"], tau=PLANT["tau"],
                                  theta=PLANT["theta"]), maxlen + KLEN)

    print("=" * 88)
    print("predict_min = 8  vs  15  闭环对比")
    print("对象 K=%.3f τ=%.0f θ=%.0f   周期 10 min" % (
        PLANT["K"], PLANT["tau"], PLANT["theta"]))
    print("=" * 88)

    out = []
    tot8 = tot15 = totn = 0
    for s, e in segs:
        t8, r8, tm = run(wt, s, e, 8.0, Gex)
        t15, r15, _ = run(wt, s, e, 15.0, Gex)
        L = e - s
        idxs = sorted(set(list(range(0, L, 10)) + [L - 1]))
        times = [wt.time_full(s + i)[5:] for i in idxs]

        def pk(a, n=1):
            return [None if (x is None or x != x) else round(float(x), n)
                    for x in a[idxs]]

        b8, b15 = band(t8), band(t15)
        n8 = int(np.count_nonzero(~np.isnan(t8)))
        tot8 += b8 * n8
        tot15 += b15 * n8
        totn += n8
        item = dict(name=wt.time_full(s), times=times,
                    t3_act=pk(tm),
                    rat_act=pk(R.ffill(wt.series(Tag.RATIO_SD)[s:e])),
                    v8=dict(t3=pk(t8), rat=pk(r8), band=b8),
                    v15=dict(t3=pk(t15), rat=pk(r15), band=b15))
        out.append(item)
        print()
        print("班次 %s" % wt.time_full(s))
        print("  人工实测      %.1f%%" % band(tm[idxs]))
        print("  predict_min=8   %.1f%%  行程 %.0f" % (b8, np.abs(np.diff(r8[~np.isnan(t8)])).sum()))
        print("  predict_min=15  %.1f%%  行程 %.0f" % (b15, np.abs(np.diff(r15[~np.isnan(t15)])).sum()))

    print()
    print("=" * 88)
    print("加权：predict_min=8  %.1f%%   |   predict_min=15  %.1f%%   |  差 %+.1f pp"
          % (tot8 / totn, tot15 / totn, (tot8 - tot15) / totn))
    print("=" * 88)

    with open(os.path.join(_HERE, "前瞻曲线.json"), "w",
              encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False)
    print("已写入 前瞻曲线.json")


if __name__ == "__main__":
    main()
