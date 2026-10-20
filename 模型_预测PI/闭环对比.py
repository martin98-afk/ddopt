# -*- coding: utf-8 -*-
"""闭环对比：预测 PI vs 现役斜率规则，输出曲线数据。

与 对比验证.py 的区别：
  对比验证.py 是开环（输出不写回数据，T3 读实测值）—— 只能比"建议差异"
  本脚本是闭环（T3 由响应核推演，水率变化会改变 T3）—— 能比"实际控制效果"

对象核用 标定参数.py 里的 GAIN/TAU/THETA，与预测 PI 内部模型一致，
即在"模型准确"的前提下对比。标定后重跑，两侧都换成实测核。

共同扰动法：d[t] = 实测T3 − 人工水率下的模型响应，两套算法共用同一条 d，
保证面对的是同一批次原料、同一环境扰动。

输出：闭环曲线.json（供画图）
运行：python 闭环对比.py
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

import 标定参数 as P                                           # noqa: E402
from controller_ppi import attach_predictive_pi, make_config  # noqa: E402

KLEN = 601


def fopdt_kernel(n=KLEN, K=None, tau=None, theta=None):
    K = P.GAIN if K is None else K
    tau = P.TAU if tau is None else tau
    theta = P.THETA if theta is None else theta
    t = np.arange(n, dtype=float)
    g = np.zeros(n)
    m = t >= theta
    g[m] = K * (1.0 - np.exp(-(t[m] - theta) / tau))
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
    """可写宽表：T3 / 水率 / 给料量可覆盖"""

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


def run_shift(wt, s, e, use_ppi, Gex):
    """跑一个班次，返回 (T3曲线, 水率曲线, 实测T3)"""
    L = e - s
    dt = P.CONTROL_INTERVAL_MIN
    t3_meas = np.nanmean(np.vstack([wt.series(t) for t in Tag.TEMP[2]]),
                         axis=0)[s:e]
    R = ffill(wt.series(Tag.RATIO_SD)[s:e])
    base0 = t3_meas[0] if not np.isnan(t3_meas[0]) else P.TARGET_T3
    u_act = ffill(R)
    resp0 = response(u_act, Gex, 0)

    # 共同扰动：实测 − 人工水率下的模型响应
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
    if use_ppi:
        attach_predictive_pi(ctrl, cfg)

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
    Gex = extend(fopdt_kernel(), max(e - s for s, e in segs) + KLEN)

    print("=" * 92)
    print("闭环对比：预测 PI vs 现役斜率规则")
    print("对象核 K=%.3f τ=%.0f θ=%.0f（与 标定参数.py 一致，模型准确前提）"
          % (P.GAIN, P.TAU, P.THETA))
    print("周期 %.1f min   限幅 [%.0f, %.0f]" % (
        P.CONTROL_INTERVAL_MIN, P.RATIO_LO, P.RATIO_HI))
    if not P.CALIBRATED:
        print("[提示] 未标定，对象与控制器用的是同一组占位参数")
    print("=" * 92)

    out = []
    for s, e in segs:
        L = e - s
        idxs = sorted(set(list(range(0, L, max(1, int(P.CONTROL_INTERVAL_MIN))))
                          + [L - 1]))
        times = [wt.time_full(s + i)[5:] for i in idxs]

        ta, ra, tm = run_shift(wt, s, e, False, Gex)   # 斜率规则
        tb, rb, _ = run_shift(wt, s, e, True, Gex)     # 预测 PI

        def pk(a, n=1):
            return [None if (x is None or x != x) else round(float(x), n)
                    for x in a[idxs]]

        item = dict(name=wt.time_full(s), n=len(idxs), times=times,
                    t3_act=pk(tm), rat_act=pk(ffill(wt.series(Tag.RATIO_SD)[s:e])),
                    band_act=band(tm[idxs]),
                    trend=dict(t3=pk(ta), rat=pk(ra), band=band(ta)),
                    ppi=dict(t3=pk(tb), rat=pk(rb), band=band(tb)))
        out.append(item)

        print()
        print("班次 %s  (%d 拍)" % (item["name"], len(idxs)))
        print("  %-12s %8s %8s %10s %8s" % (
            "算法", "合格", "T3std", "行程", "顶界"))
        for nm, d in (("人工实测", item), ("斜率规则", item["trend"]),
                      ("预测PI", item["ppi"])):
            if nm == "人工实测":
                v = np.array([x for x in item["t3_act"] if x is not None], float)
            else:
                v = np.array([x for x in d["t3"] if x is not None], float)
            r = (np.array([x for x in item["rat_act"] if x is not None], float)
                 if nm == "人工实测"
                 else np.array([x for x in d["rat"] if x is not None], float))
            print("  %-12s %7.1f%% %8.1f %10.0f %7.0f%%" % (
                nm, band(v), v.std(), np.abs(np.diff(r)).sum(),
                100 * np.mean((r >= P.RATIO_HI - 1e-6) |
                              (r <= P.RATIO_LO + 1e-6))))

    with open(os.path.join(_HERE, "闭环曲线.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False)
    print()
    print("曲线数据已写入 闭环曲线.json")


if __name__ == "__main__":
    main()
