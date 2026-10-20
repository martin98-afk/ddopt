# -*- coding: utf-8 -*-
"""Dahlin（大林）算法 vs 现役斜率规则，同数据闭环对比。

Dahlin 算法（1968，IBM）针对纯滞后对象的直接综合法：
  期望闭环 Φ(z) = (1-a_r)·z^{-N-1} / (1 - a_r·z^{-1})
  对象     G(z) = K(1-a1)·z^{-N-1} / (1 - a1·z^{-1}),  a1=e^{-Ts/τ}, N=θ/Ts
  控制器   D(z) = Φ / [G(1-Φ)]
差分方程：
  u(k) = a_r·u(k-1) + (1-a_r)·u(k-N-1) + C·[e(k) - a1·e(k-1)]
  C = (1-a_r) / [K(1-a1)],  a_r = e^{-Ts/λ}
λ 是期望闭环时间常数，唯一的调节参数（越大越慢越稳）。

已验证：无扰动时收敛到目标且无超调（Dahlin 的设计目标就是无超调）。

注意振铃（ringing）：λ 过小会让 u 在采样点间振荡，文献明确提到。
本脚本会统计动作幅度，用来发现振铃。

运行：python Dahlin对比.py
"""
from __future__ import annotations

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

import 标定参数 as P                                           # noqa: E402
from controller_ppi import make_config                       # noqa: E402
from 重标定对比 import (fopdt_kernel, extend, response, ffill,   # noqa: E402
                     SimTable, segments, run_shift, band)

KLEN = 601

# 用作"真对象"的核（占位值）
PLANT = dict(K=-0.151, tau=60.0, theta=30.0)


class DahlinStub:
    """Dahlin 控制器，接口对齐 TrendController"""

    def __init__(self, K, tau, theta, dt, lam, target=118.0,
                 u_lo=500.0, u_hi=690.0, u_init=600.0):
        self.a1 = float(np.exp(-dt / max(tau, 1e-9)))
        self.ar = float(np.exp(-dt / max(lam, 1e-9)))
        self.N = max(0, int(round(theta / dt)))
        self.C = (1.0 - self.ar) / (K * (1.0 - self.a1))
        self.target = float(target)
        self.u_lo, self.u_hi = float(u_lo), float(u_hi)
        self.u = float(np.clip(u_init, u_lo, u_hi))
        self.u_hist = [self.u] * (self.N + 2)
        self.e_hist = [0.0] * (self.N + 2)
        self.last_reason = ""
        self.steps = 0

    def reset(self, u_init=None):
        if u_init is not None:
            self.u = float(np.clip(u_init, self.u_lo, self.u_hi))
        self.u_hist = [self.u] * (self.N + 2)
        self.e_hist = [0.0] * (self.N + 2)
        self.steps = 0

    def sync(self, u):
        self.u = float(np.clip(u, self.u_lo, self.u_hi))

    def update(self, t3_now, slope=0.0):
        if not np.isfinite(t3_now):
            return self.u
        e = self.target - t3_now          # 温度高 -> e<0
        u = (self.ar * self.u_hist[-1]
             + (1.0 - self.ar) * self.u_hist[-(self.N + 1)]
             + self.C * (e - self.a1 * self.e_hist[-1]))
        u = float(np.clip(u, self.u_lo, self.u_hi))
        self.u_hist.append(u)
        self.e_hist.append(e)
        self.last_reason = ("Dahlin e=%.1f N=%d -> %.0f" % (e, self.N, u))
        self.u = u
        self.steps += 1
        return u


def attach_dahlin(ctrl, cfg, kernel, lam, cap=25.0):
    dt = cfg.control.control_interval_min
    stub = DahlinStub(kernel["K"], kernel["tau"], kernel["theta"], dt, lam,
                      target=P.TARGET_T3, u_lo=P.RATIO_LO, u_hi=P.RATIO_HI,
                      u_init=cfg.control.ratio_init)
    ctrl._trend = stub
    prev = {"u": None}
    orig = ctrl.step

    def step(i, phase=None, data_idx=None):
        out = orig(i, phase, data_idx)
        u = float(out.ratio_set)
        if prev["u"] is not None:
            du = u - prev["u"]
            if abs(du) > cap:
                u = prev["u"] + (cap if du > 0 else -cap)
        u = float(min(max(u, P.RATIO_LO), P.RATIO_HI))
        out.ratio_set = u
        stub.sync(u)
        prev["u"] = u
        return out

    ctrl.step = step
    return stub


def run_dahlin(wt, s, e, kernel, lam, Gex, cap=25.0):
    L = e - s
    dt = P.CONTROL_INTERVAL_MIN
    t3_meas = np.nanmean(np.vstack([wt.series(t) for t in Tag.TEMP[2]]),
                         axis=0)[s:e]
    R = ffill(wt.series(Tag.RATIO_SD)[s:e])
    base0 = t3_meas[0] if not np.isnan(t3_meas[0]) else P.TARGET_T3
    u_act = ffill(R)
    resp0 = response(u_act, Gex, 0)
    d = np.full(L, np.nan)
    for t in range(L):
        if not np.isnan(t3_meas[t]):
            d[t] = t3_meas[t] - base0 - (response(u_act, Gex, t) - resp0)
    d = ffill(d)
    for i in range(L - 2, -1, -1):
        if np.isnan(d[i]):
            d[i] = d[i + 1]
    d = np.nan_to_num(d, nan=0.0)

    cfg = make_config()
    sim = SimTable(wt)
    sc = SignalConditioner(sim, cfg)
    ctrl = XshController(sc, cfg)
    attach_dahlin(ctrl, cfg, kernel, lam, cap)

    u_sim = u_act.copy()
    cur_r = float(u_act[0]) if u_act[0] > 0 else P.RATIO_INIT
    lime0 = np.nanmean(wt.series(Tag.LIME)[s:s + 10])
    cur_l = float(lime0) if (lime0 == lime0 and lime0 > 0) else P.LIME_SP
    t3 = np.full(L, np.nan)
    rat = np.full(L, np.nan)
    step = max(1, int(round(dt)))
    for t in range(L):
        sim.set_ratio(s + t, cur_r)
        sim.set_lime(s + t, cur_l)
        u_sim[t] = cur_r
        v = base0 + (response(u_sim, Gex, t) - resp0) + d[t]
        if not np.isnan(v):
            sim.set_t3(s + t, v)
            t3[t] = v
        rat[t] = cur_r
        if t % step == 0:
            o = ctrl.step(s + t)
            cur_r = float(o.ratio_set)
            cur_l = float(o.lime_set)
    return t3, rat, t3_meas


def main():
    wt = build_wide(verbose=False)
    segs = segments(wt)
    maxlen = max(e - s for s, e in segs)
    Gex = extend(fopdt_kernel(K=PLANT["K"], tau=PLANT["tau"],
                              theta=PLANT["theta"]), maxlen + KLEN)

    print("=" * 94)
    print("Dahlin（大林）算法 vs 现役斜率规则")
    print("真对象 K=%.3f τ=%.0f θ=%.0f   周期 %.0f min"
          % (PLANT["K"], PLANT["tau"], PLANT["theta"], P.CONTROL_INTERVAL_MIN))
    print("=" * 94)

    # 基线：斜率规则
    print()
    print("【基线：斜率规则】")
    tb = []
    for s, e in segs:
        t3, rat, _ = run_shift(wt, s, e, "trend", PLANT, PLANT, Gex)
        v = t3[~np.isnan(t3)]
        tb.append((band(t3), v.size))
        print("  %s  %.1f%%  std %.1f  行程 %.0f"
              % (wt.time_full(s)[:16], band(t3), v.std(),
                 np.abs(np.diff(rat)).sum()))
    base_trend = sum(a * b for a, b in tb) / sum(b for _, b in tb)
    print("  加权：%.1f%%" % base_trend)

    print()
    print("【Dahlin：λ 扫描】λ 越大越慢越稳，λ 过小会振铃")
    print("  %-10s %10s %10s %12s %10s" % (
        "λ (min)", "加权合格", "行程", "单拍P99", "顶界"))
    rows = []
    for lam in (5.0, 15.0, 30.0, 60.0, 120.0):
        tb = []
        tot_travel = 0
        all_d = []
        at_hi = []
        detail = []
        for s, e in segs:
            t3, rat, _ = run_dahlin(wt, s, e, PLANT, lam, Gex)
            v = t3[~np.isnan(t3)]
            tb.append((band(t3), v.size))
            dd = np.abs(np.diff(rat))
            tot_travel += dd.sum()
            all_d.append(dd)
            at_hi.append((np.mean((rat >= P.RATIO_HI - 1e-6) |
                                  (rat <= P.RATIO_LO + 1e-6)), v.size))
            detail.append((wt.time_full(s)[5:10], band(t3), v.std()))
        w = sum(a * b for a, b in tb) / sum(b for _, b in tb)
        p99 = float(np.percentile(np.concatenate(all_d), 99)) \
            if all_d else 0.0
        ah = sum(a * b for a, b in at_hi) / sum(b for _, b in at_hi)
        rows.append((lam, w, tot_travel, p99, ah, detail))
        print("  %-10.0f %9.1f%% %10.0f %12.1f %9.0f%%"
              % (lam, w, tot_travel, p99, ah))

    print()
    print("=" * 94)
    print("分班次明细")
    print("=" * 94)
    print("  %-10s %s" % ("λ", "  ".join("%s %s" % (
        x[0], "%.0f%%" % x[1]) for x in rows[0][5])))
    for lam, w, tr, p99, ah, detail in rows:
        print("  λ=%-7.0f %s" % (lam, "  ".join(
            "%.0f%%" % x[1] for x in detail)))
    print()
    print("  斜率规则 %.1f%%" % base_trend)
    best = max(rows, key=lambda r: r[1])
    print("  Dahlin 最好 λ=%.0f -> %.1f%%" % (best[0], best[1]))
    print()
    if best[1] > base_trend:
        print("  结论：Dahlin 优于斜率规则 %+.1f 个百分点" % (best[1] - base_trend))
    else:
        print("  结论：斜率规则仍最优，Dahlin 差 %.1f 个百分点"
              % (base_trend - best[1]))


if __name__ == "__main__":
    main()
