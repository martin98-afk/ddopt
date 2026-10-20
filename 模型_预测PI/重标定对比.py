# -*- coding: utf-8 -*-
"""用历史标定出的参数重跑预测 PI，并与斜率规则对比。

背景：历史标定试验.py 从真实数据辨识出一组新参数
    K=-0.330  τ=2  θ=15      （原占位值是 -0.151 / 60 / 30）
τ 从 60 降到 2，意味着响应快 30 倍，动作可以更激进。

但这组参数的 R² 只有 0.51，且半合成检验证明它失真
（真值即使是 -0.151/60/30，用这批数据也只能辨识出 -0.330/2/15）。
所以本脚本跑三组，看清楚"如果新参数是对的/错的"分别会怎样：

  A 组  真对象=占位核，控制器=占位核       基线（模型准确）
  B 组  真对象=新核，   控制器=新核         若新参数正确，效果应很好
  C 组  真对象=占位核，控制器=新核         若新参数错误（最可能），会不会出事

C 组是关键：它回答"拿不准的参数直接用，风险有多大"。

输出：重标定曲线.json
运行：python 重标定对比.py
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
from predictive_pi import PredictivePI                       # noqa: E402

import 标定参数 as P                                           # noqa: E402
from controller_ppi import make_config, _step_limit           # noqa: E402

KLEN = 601

# 原占位参数（模型/replay_shift_model.py 的保守核）
OLD = dict(K=-0.151, tau=60.0, theta=30.0)
# 历史标定辨识出的新参数
NEW = dict(K=-0.330, tau=2.0, theta=15.0)


def fopdt_kernel(n=KLEN, K=-0.151, tau=60.0, theta=30.0):
    t = np.arange(n, dtype=float)
    g = np.zeros(n)
    m = t >= theta
    if tau > 0:
        g[m] = K * (1.0 - np.exp(-(t[m] - theta) / tau))
    else:
        g[m] = K
    return g


def extend(G, total):
    G = np.asarray(G, float)
    return G[:total] if total <= len(G) else np.concatenate(
        [G, np.full(total - len(G), G[-1])])


def response(u, G, t):
    K = len(G)
    if t + 1 < K:
        du = np.diff(u[:t + 1])
        return float(np.dot(G[:du.size][::-1], du))
    du = np.diff(u[t - K + 1:t + 1])
    return float(np.dot(G[:du.size][::-1], du))


def ffill(a):
    out = a.astype(np.float64, copy=True)
    for i in range(1, out.size):
        if np.isnan(out[i]):
            out[i] = out[i - 1]
    return out


class SimTable:
    def __init__(self, wt):
        self.wt = wt
        self.grid = wt.grid
        self._ov = {nm: wt.series(nm).copy()
                    for nm in list(Tag.TEMP[2]) + [Tag.RATIO_SD, Tag.RATIO_FK, Tag.LIME]}

    def set_t3(self, i, v):
        for nm in Tag.TEMP[2]:
            self._ov[nm][i] = v

    def set_ratio(self, i, v):
        self._ov[Tag.RATIO_SD][i] = v
        self._ov[Tag.RATIO_FK][i] = v

    def set_lime(self, i, v):
        self._ov[Tag.LIME][i] = v

    def series(self, name):
        return self._ov[name] if name in self._ov else self.wt.series(name)

    def __contains__(self, name):
        return True


def segments(wt, min_len=30):
    perm = wt.series(Tag.PERMIT) > 0.5
    lime = wt.series(Tag.LIME) > 0.1
    prod = np.where(np.isnan(perm) | np.isnan(lime), False, perm & lime)
    d = np.diff(prod.astype(np.int8))
    st = list(np.where(d == 1)[0] + 1)
    en = list(np.where(d == -1)[0] + 1)
    if prod[0]:
        st.insert(0, 0)
    if prod[-1]:
        en.append(prod.size)
    return [(s, e) for s, e in zip(st, en) if e - s >= min_len]


def attach(ctrl, cfg, kernel):
    """把预测 PI 装进控制器，kernel 决定控制器内部模型"""
    dt = cfg.control.control_interval_min
    ppi = PredictivePI(
        target=P.TARGET_T3, kp=P.KP, ti=P.TI,
        gain=kernel["K"], tau=kernel["tau"], theta=kernel["theta"],
        dt_min=dt,
        u_lo=max(cfg.safety.ratio_safe_min, P.RATIO_LO),
        u_hi=P.RATIO_HI, u_init=cfg.control.ratio_init,
        step_max=_step_limit(dt))
    ctrl._trend = ppi
    # 输出速率总闸
    cap = _step_limit(dt)
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
        ppi.sync(u)
        prev["u"] = u
        return out

    ctrl.step = step
    return ppi


def run_shift(wt, s, e, mode, plant_k, ctrl_k, Gex):
    """mode: 'trend' 用现役斜率规则 / 'ppi' 用预测PI"""
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
    if mode == "ppi":
        attach(ctrl, cfg, ctrl_k)

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


def band(v):
    x = v[~np.isnan(v)]
    return round(float(np.mean((x >= P.T3_LOW) & (x <= P.T3_HIGH)) * 100), 1) \
        if x.size else 0.0


def main():
    wt = build_wide(verbose=False)
    segs = segments(wt)
    maxlen = max(e - s for s, e in segs)

    groups = [
        ("A 真=占位 控=占位", OLD, OLD),
        ("B 真=新核 控=新核", NEW, NEW),
        ("C 真=占位 控=新核", OLD, NEW),
    ]

    out = {"segs": [], "groups": {}}
    print("=" * 96)
    print("历史标定参数重跑：预测 PI vs 斜率规则")
    print("原占位 K=%.3f τ=%.0f θ=%.0f  |  新标定 K=%.3f τ=%.0f θ=%.0f"
          % (OLD["K"], OLD["tau"], OLD["theta"],
             NEW["K"], NEW["tau"], NEW["theta"]))
    print("周期 %.0f min" % P.CONTROL_INTERVAL_MIN)
    print("=" * 96)

    for gi, (gname, pk, ck) in enumerate(groups):
        Gex = extend(fopdt_kernel(K=pk["K"], tau=pk["tau"], theta=pk["theta"]),
                     maxlen + KLEN)
        print()
        print("-" * 96)
        print("【%s】" % gname)
        print("-" * 96)
        print("  %-18s %8s %8s %10s %8s" % (
            "班次/算法", "合格", "T3std", "行程", "顶界"))
        gdata = []
        for s, e in segs:
            ta, ra, tm = run_shift(wt, s, e, "trend", pk, ck, Gex)
            tb, rb, _ = run_shift(wt, s, e, "ppi", pk, ck, Gex)
            item = dict(name=wt.time_full(s),
                        trend=dict(band=band(ta), t3=ta, rat=ra),
                        ppi=dict(band=band(tb), t3=tb, rat=rb))
            gdata.append(item)
            for nm, t3x, rx in (("斜率规则", ta, ra), ("预测PI", tb, rb)):
                v = t3x[~np.isnan(t3x)]
                print("  %-18s %7.1f%% %8.1f %10.0f %7.0f%%" % (
                    "%s %s" % (wt.time_full(s)[5:10], nm),
                    band(t3x), v.std(), np.abs(np.diff(rx)).sum(),
                    100 * np.mean((rx >= P.RATIO_HI - 1e-6) |
                                  (rx <= P.RATIO_LO + 1e-6))))
        # 加权
        def wband(key):
            tot = sum(np.count_nonzero(~np.isnan(x[key]["t3"])) for x in gdata)
            return round(sum(x[key]["band"] *
                             np.count_nonzero(~np.isnan(x[key]["t3"]))
                             for x in gdata) / max(tot, 1), 1)
        print("  %-18s %7.1f%%" % ("加权 斜率规则", wband("trend")))
        print("  %-18s %7.1f%%" % ("加权 预测PI", wband("ppi")))
        out["groups"][gname] = dict(weighted_trend=wband("trend"),
                                    weighted_ppi=wband("ppi"))

    # 导出曲线：只导 B 组和 C 组（A 组已在闭环对比.py 出过）
    print()
    print("导出曲线数据 ...")
    curve_segs = []
    for s, e in segs:
        L = e - s
        idxs = sorted(set(list(range(0, L, max(1, int(P.CONTROL_INTERVAL_MIN))))
                          + [L - 1]))
        times = [wt.time_full(s + i)[5:] for i in idxs]
        t3_meas = np.nanmean(np.vstack([wt.series(t) for t in Tag.TEMP[2]]),
                             axis=0)[s:e]

        def pk(a, n=1):
            return [None if (x is None or x != x) else round(float(x), n)
                    for x in a[idxs]]

        item = dict(name=wt.time_full(s), times=times, t3_act=pk(t3_meas),
                    rat_act=pk(ffill(wt.series(Tag.RATIO_SD)[s:e])),
                    band_act=band(t3_meas[idxs]))
        for gi, (gname, pk_, ck_) in enumerate(groups):
            Gex = extend(fopdt_kernel(K=pk_["K"], tau=pk_["tau"],
                                      theta=pk_["theta"]), maxlen + KLEN)
            tb, rb, _ = run_shift(wt, s, e, "ppi", pk_, ck_, Gex)
            ta, ra, _ = run_shift(wt, s, e, "trend", pk_, ck_, Gex)
            item[gname] = dict(ppi_t3=pk(tb), ppi_rat=pk(rb),
                               trend_t3=pk(ta), trend_rat=pk(ra),
                               ppi_band=band(tb), trend_band=band(ta))
        curve_segs.append(item)
    out["segs"] = curve_segs

    with open(os.path.join(_HERE, "重标定曲线.json"), "w",
              encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False)
    print("已写入 重标定曲线.json")

    print()
    print("=" * 96)
    print("汇总")
    print("=" * 96)
    print("  %-22s %12s %12s" % ("组", "斜率规则", "预测PI"))
    for gname, v in out["groups"].items():
        print("  %-22s %11.1f%% %11.1f%%" % (
            gname, v["weighted_trend"], v["weighted_ppi"]))


if __name__ == "__main__":
    main()
