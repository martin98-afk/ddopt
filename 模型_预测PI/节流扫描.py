# -*- coding: utf-8 -*-
"""扫描节流时长 throttle_min（外部 10 秒调用，按真实时间节流）。

用可控时钟模拟时间流逝，不必真等几小时。

关键：service.on_tick 用 time.time() 判断，扫描时 patch 掉即可。
节流期内不推数据、不算，所以每个节流值对应一套独立的缓冲与状态。

闭环：T3 由响应核推演（水率改变温度），能真实反映节流对控制效果的影响。

运行：python 节流扫描.py
"""
from __future__ import annotations

import os
import sys
import time as _t

import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
_MODEL_DIR = os.path.join(os.path.dirname(_HERE), "模型")
for _p in (_HERE, _MODEL_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

os.environ.setdefault(
    "XSH_DATA_DIR",
    r"D:\work\梅钢脱硫脱硝\data\脱硫脱硝消石灰制备数据")

from config import Tag, Config                               # noqa: E402
from controller import Phase                                 # noqa: E402
from service import XshService, SnapshotAdapter              # noqa: E402
from data_loader import build_wide                           # noqa: E402

import 标定参数 as P                                           # noqa: E402
import 重标定对比 as R                                          # noqa: E402

PLANT = dict(K=-0.151, tau=60.0, theta=30.0)
KLEN = 601
CALL_SEC = 10.0
CALLS_PER_MIN = int(60.0 / CALL_SEC)


class Clock:
    """可控时钟：替换 time.time，模拟时间流逝"""

    def __init__(self, t0=1_700_000_000.0):
        self.t = t0

    def time(self):
        return self.t

    def advance(self, sec):
        self.t += sec


def snap_of(v, u=600.0):
    s = {"permit": 1.0, "curr1": 12.5, "lime_flow": 3.5,
         "water_flow": 2200.0, "bin_level": 5.0, "lime_bin": 5.0,
         "water_tank": 4.0, "exhaust_fan": 1.0,
         "ratio_set": u, "lime_set": 3.5}
    for j in range(3):
        for k in range(3):
            s["temp%d_%d" % (j + 1, k + 1)] = v
    return s


def run_seg(wt, s, e, throttle, Gex, clk, direct=False):
    """direct=True：时钟按 10 分钟推进、每 10 分钟调一次（对照基准）"""
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

    cfg = Config()
    cfg.control.control_interval_min = 10.0
    cfg.control.gap_tolerance = 10.0
    cfg.control.throttle_min = 0.0 if direct else throttle
    cfg.set_curr1_high(P.CURR1_HIGH)
    cfg.control.ratio_init = float(u_act[0]) if u_act[0] > 0 else \
        P.RATIO_INIT

    svc = XshService(cfg)
    u_sim = u_act.copy()
    cur = float(u_act[0]) if u_act[0] > 0 else P.RATIO_INIT
    t3 = np.full(L, np.nan)
    rat = np.full(L, np.nan)

    if direct:
        for t in range(L):
            # 水率在整个 10 分钟区间保持上次下发值（真实行为），
            # 不能只在 t%10==0 写，否则其余分钟会残留 u_act 的原值。
            u_sim[t] = cur
            v = base0 + (R.response(u_sim, Gex, t) - resp0) + d[t]
            if not np.isnan(v):
                t3[t] = v
            rat[t] = cur
            if t % 10 == 0:
                clk.advance(600.0)
                o = svc.on_tick(snap_of(v if not np.isnan(v) else
                                        P.TARGET_T3, cur),
                                phase=Phase.STEADY)
                cur = float(o.ratio_set)
    else:
        for t in range(L):
            u_sim[t] = cur
            v = base0 + (R.response(u_sim, Gex, t) - resp0) + d[t]
            if not np.isnan(v):
                t3[t] = v
            rat[t] = cur
            snap = snap_of(v if not np.isnan(v) else P.TARGET_T3, cur)
            for _ in range(CALLS_PER_MIN):
                clk.advance(CALL_SEC)
                o = svc.on_tick(snap, phase=Phase.STEADY)
            cur = float(o.ratio_set)
    return t3, rat


def band(v):
    x = v[~np.isnan(v)]
    return round(float(np.mean((x >= P.T3_LOW) & (x <= P.T3_HIGH)) * 100), 1) \
        if x.size else 0.0


def main():
    wt = build_wide(verbose=False)
    segs = R.segments(wt)
    maxlen = max(e - s for s, e in segs)
    Gex = R.extend(R.fopdt_kernel(K=PLANT["K"], tau=PLANT["tau"],
                                  theta=PLANT["theta"]), maxlen + KLEN)

    orig_time = _t.time
    clk = Clock()

    print("=" * 96)
    print("节流扫描：外部每 %.0f 秒调用，按真实时间节流" % CALL_SEC)
    print("对象 K=%.3f τ=%.0f θ=%.0f   predict_min=%s" % (
        PLANT["K"], PLANT["tau"], PLANT["theta"],
        Config().control.trend_predict_min))
    print("=" * 96)
    print()
    print("  %-12s %10s %10s %10s %8s %8s" % (
        "节流(min)", "加权合格", "总行程", "下发次数", "顶界", "vs基准"))

    try:
        _t.time = clk.time
        rows = []
        for thr in (0.0, 1.0, 2.0, 3.0, 5.0, 8.0, 10.0, 15.0, 20.0, 30.0):
            clk.__init__()
            tot = []
            travel = 0
            nupd = 0
            at_hi = []
            detail = []
            for s, e in segs:
                t3, rat = run_seg(wt, s, e, thr, Gex, clk)
                v = t3[~np.isnan(t3)]
                n = v.size
                tot.append((band(t3), n))
                r = rat[~np.isnan(t3)]
                dd = np.abs(np.diff(r))
                travel += dd.sum()
                nupd += int(np.sum(dd > 1e-9))
                at_hi.append((100.0 * np.mean((r >= P.RATIO_HI - 1e-6) |
                                              (r <= P.RATIO_LO + 1e-6)), n))
                detail.append((wt.time_full(s)[5:10], band(t3)))
            w = sum(a * b for a, b in tot) / sum(b for _, b in tot)
            ah = sum(a * b for a, b in at_hi) / sum(b for _, b in at_hi)
            rows.append((thr, w, travel, nupd, ah, detail))
            print("  %-12.0f %9.1f%% %10.0f %10d %7.0f%%"
                  % (thr, w, travel, nupd, ah))

        # 基准：直接 10 分钟调用
        clk.__init__()
        tot = []
        travel0 = 0
        detail0 = []
        for s, e in segs:
            t3, rat = run_seg(wt, s, e, 0.0, Gex, clk, direct=True)
            v = t3[~np.isnan(t3)]
            tot.append((band(t3), v.size))
            travel0 += np.abs(np.diff(rat[~np.isnan(t3)])).sum()
            detail0.append((wt.time_full(s)[5:10], band(t3)))
        w0 = sum(a * b for a, b in tot) / sum(b for _, b in tot)
    finally:
        _t.time = orig_time

    print("  %-12s %9.1f%% %10.0f" % ("基准10min", w0, travel0))

    print()
    print("=" * 96)
    print("分班次明细")
    print("=" * 96)
    print("  %-12s %s" % ("节流", "  ".join(x[0] for x in rows[0][5])))
    for thr, w, tr, nu, ah, detail in rows:
        print("  %-12.0f %s" % (thr, "  ".join("%.0f%%" % x[1]
                                               for x in detail)))
    print("  %-12s %s" % ("基准10min", "  ".join("%.0f%%" % x[1]
                                                  for x in detail0)))

    print()
    print("=" * 96)
    print("相对基准的差异")
    print("=" * 96)
    print("  %-12s %10s %10s" % ("节流", "合格差", "行程比"))
    for thr, w, tr, nu, ah, _ in rows:
        print("  %-12.0f %+9.1fpp %9.2fx"
              % (thr, w - w0, tr / max(travel0, 1e-9)))

    best = max(rows, key=lambda r: r[1])
    print()
    print("最好：节流 %.0f min -> %.1f%%（基准 %.1f%%，%+.1fpp）"
          % (best[0], best[1], w0, best[1] - w0))


if __name__ == "__main__":
    main()
