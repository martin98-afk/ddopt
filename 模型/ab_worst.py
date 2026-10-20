# -*- coding: utf-8 -*-
"""
在 T3 超限最严重的历史班次上做反事实 A/B。

选用 10-18 00:05 稳态段（374 min，T3>130 占 48.4%）。
方法：模型自主调控，初值只取该班次开工水率，之后自维护。
"""
import json
import os
import sys

import numpy as np

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

OLD_DATA = r"D:/work/脱硫脱硝/data/脱硫脱硝消石灰制备数据"
os.environ["XSH_DATA_DIR"] = OLD_DATA

import data_loader                                        # noqa: E402
data_loader.DATA_DIR = OLD_DATA
data_loader.CACHE_DIR = os.path.join(BASE, ".cache_old")

from config import Tag, Config                             # noqa: E402
from signal_conditioning import SignalConditioner         # noqa: E402
from controller import XshController, Phase, Action       # noqa: E402

OUT = os.path.join(BASE, ".cache", "worst_ab.json")
CTRL_PERIOD = 10

# 响应核（旧模型，10-12~10-19 的 12 个阶跃事件辨识结果）
G_OLD = np.array([
    0.0000, 0.3595, 0.3970, 0.4299, 0.4532, 0.4675, 0.4663, 0.4529,
    0.4239, 0.3845, 0.3327, 0.2730, 0.2099, 0.1506, 0.0984, 0.0430,
    -0.0137, -0.0689, -0.1124, -0.1521, -0.1841, -0.2155, -0.2390, -0.2612,
    -0.2799, -0.2945, -0.3098, -0.3175, -0.3224, -0.3222, -0.3190, -0.3203,
    -0.3213, -0.3254, -0.3236, -0.3176, -0.3091, -0.2973, -0.2856, -0.2745,
    -0.2679, -0.2532, -0.2401, -0.2283, -0.2272, -0.2275, -0.2266, -0.2264,
    -0.2253, -0.2260, -0.2304, -0.2386, -0.2485, -0.2559, -0.2579, -0.2539,
    -0.2458, -0.2323, -0.2270, -0.2229, -0.1510])


class AutoTable:
    def __init__(self, wt):
        self.wt = wt
        self.grid = wt.grid
        self._ov = {}
        for nm in list(Tag.TEMP[2]) + [Tag.RATIO_SD, Tag.RATIO_FK, Tag.LIME]:
            self._ov[nm] = wt.series(nm).copy()

    def set_ratio(self, i, v):
        self._ov[Tag.RATIO_SD][i] = v
        self._ov[Tag.RATIO_FK][i] = v

    def set_lime(self, i, v):
        self._ov[Tag.LIME][i] = v

    def set_t3(self, i, v):
        for nm in Tag.TEMP[2]:
            self._ov[nm][i] = v

    def series(self, n):
        return self._ov.get(n, self.wt.series(n))

    def __contains__(self, n):
        return True


def response_fast(u, G, t):
    K = len(G)
    if t + 1 < K:
        du = np.diff(u[:t + 1])
        return float(np.dot(G[:du.size][::-1], du))
    du = np.diff(u[t - K + 1:t + 1])
    return float(np.dot(G[:du.size][::-1], du))


def _ffill(a):
    out = a.copy()
    m = np.isnan(out)
    if m.all():
        return out
    idx = np.where(~m, np.arange(out.size), 0)
    np.maximum.accumulate(idx, out=idx)
    out[m] = out[idx[m]]
    return out


def run_shift(wt, s0, e0, G, T3, R):
    n = wt.grid.size
    u_act = np.where(np.isnan(R), 0.0, R).astype(np.float64)
    for i in range(1, n):
        if np.isnan(R[i]):
            u_act[i] = u_act[i - 1]

    base0 = T3[s0]
    resp0 = response_fast(u_act, G, s0)
    d = np.full(e0 - s0 + 1, np.nan)
    for k, t in enumerate(range(s0, e0 + 1)):
        if np.isnan(T3[t]):
            continue
        d[k] = T3[t] - base0 - (response_fast(u_act, G, t) - resp0)
    d = _ffill(d)

    sim = AutoTable(wt)
    sc = SignalConditioner(sim, Config())
    cfg = Config()
    ctrl = XshController(sc, cfg)

    cur_ratio = R[s0] if not np.isnan(R[s0]) and R[s0] > 0 else 630.0
    cur_lime = np.nanmean(wt.series(Tag.LIME)[s0:s0 + 10])
    if np.isnan(cur_lime) or cur_lime <= 0:
        cur_lime = 3.5

    u_sim = u_act.copy()
    ratio_sim = np.full(e0 - s0 + 1, np.nan)
    t3_sim = np.full(e0 - s0 + 1, np.nan)
    acts = []

    for t in range(s0, e0 + 1):
        sim.set_ratio(t, cur_ratio)
        sim.set_lime(t, cur_lime)
        u_sim[t] = cur_ratio

        v = base0 + (response_fast(u_sim, G, t) - resp0) + d[t - s0]
        if not np.isnan(v):
            sim.set_t3(t, v)
            t3_sim[t - s0] = v
        ratio_sim[t - s0] = cur_ratio

        if (t - s0) % CTRL_PERIOD == 0:
            out = ctrl.step(t)
            cur_ratio = out.ratio_set
            cur_lime = out.lime_set
            acts.append((t - s0, out.action.value, out.ratio_set,
                         out.lime_set, out.reason))

    return dict(ratio_sim=ratio_sim, t3_sim=t3_sim,
                ratio_act=R[s0:e0 + 1].copy(), t3_act=T3[s0:e0 + 1].copy(),
                acts=acts)


def main():
    wt = data_loader.build_wide(verbose=False, use_cache=False)
    n = wt.grid.size
    R = wt.series(Tag.RATIO_SD)
    T3 = np.nanmean([wt.series(t) for t in Tag.TEMP[2]], axis=0)
    perm = (wt.series(Tag.PERMIT) > 0.5) & (wt.series(Tag.LIME) > 0.1)

    d = np.diff(perm.astype(np.int8))
    starts = list(np.where(d == 1)[0] + 1)
    ends = list(np.where(d == -1)[0] + 1)
    if perm[0]:
        starts.insert(0, 0)
    if perm[-1]:
        ends.append(n)
    segs = [(s, e) for s, e in zip(starts, ends) if e - s >= 30]

    # 自动挑 T3>130 占比最高的稳态段
    import time
    best, best_pct = None, -1
    for s, e in segs:
        s0 = s + 120 if e - s > 150 else s + 60
        if e - s0 < 90:
            continue
        t3 = T3[s0:e]
        t3 = t3[~np.isnan(t3)]
        if t3.size < 60:
            continue
        pct = 100 * np.mean(t3 > 130)
        if pct > best_pct:
            best_pct, best = pct, (s0, e)

    s0, e0 = best
    print("=" * 92)
    print("反事实 A/B：T3 超限最严重的班次")
    print("=" * 92)
    print("选用稳态段 %s ~ %s（%d min，T3>130 占 %.1f%%）" % (
        time.strftime("%m-%d %H:%M", time.localtime(wt.grid[s0])),
        time.strftime("%m-%d %H:%M", time.localtime(wt.grid[e0 - 1])),
        e0 - s0, best_pct))

    r = run_shift(wt, s0, e0 - 1, G_OLD, T3, R)

    rs = r["ratio_sim"][~np.isnan(r["ratio_sim"])]
    ra = r["ratio_act"][~np.isnan(r["ratio_act"])]
    ta = r["t3_act"][~np.isnan(r["t3_act"])]
    ts = r["t3_sim"][~np.isnan(r["t3_sim"])]

    print()
    print("水率:")
    print("  人工: 均值 %.0f  std %.1f  范围 %.0f~%.0f  动作 %d 次" % (
        ra.mean(), ra.std(), ra.min(), ra.max(),
        int(np.sum(np.abs(np.diff(ra)) > 0.5))))
    print("  模型: 均值 %.0f  std %.1f  范围 %.0f~%.0f  动作 %d 次" % (
        rs.mean(), rs.std(), rs.min(), rs.max(),
        sum(1 for a in r["acts"] if a[1] != "保持")))

    print()
    print("T3:")
    print("  人工实际操作: 均值 %.1f  合格率 %.1f%%  >130 %.1f%%  最大 %.1f" % (
        ta.mean(), 100 * np.mean((ta >= 100) & (ta <= 130)),
        100 * np.mean(ta > 130), ta.max()))
    print("  模型接管    : 均值 %.1f  合格率 %.1f%%  >130 %.1f%%  最大 %.1f" % (
        ts.mean(), 100 * np.mean((ts >= 100) & (ts <= 130)),
        100 * np.mean(ts > 130), ts.max()))

    print()
    print("=" * 92)
    print("模型动作明细")
    print("=" * 92)
    for a in r["acts"]:
        if a[1] != "保持":
            print("  t=%3d  %-10s 水率->%.0f  给料->%.2f  %s" % (
                a[0], a[1], a[2], a[3], a[4][:58]))

    # 保存
    idx = list(range(0, len(r["ratio_sim"]), 5))
    payload = {
        "s0": int(s0), "e0": int(e0),
        "label": time.strftime("%m-%d %H:%M", time.localtime(wt.grid[s0])),
        "t": idx,
        "ratio_act": [None if np.isnan(r["ratio_act"][i]) else round(float(r["ratio_act"][i]), 0) for i in idx],
        "ratio_sim": [None if np.isnan(r["ratio_sim"][i]) else round(float(r["ratio_sim"][i]), 0) for i in idx],
        "t3_act": [None if np.isnan(r["t3_act"][i]) else round(float(r["t3_act"][i]), 1) for i in idx],
        "t3_sim": [None if np.isnan(r["t3_sim"][i]) else round(float(r["t3_sim"][i]), 1) for i in idx],
        "summary": {
            "act_mean": float(ta.mean()),
            "act_in": float(100 * np.mean((ta >= 100) & (ta <= 130))),
            "act_above": float(100 * np.mean(ta > 130)),
            "sim_mean": float(ts.mean()),
            "sim_in": float(100 * np.mean((ts >= 100) & (ts <= 130))),
            "sim_above": float(100 * np.mean(ts > 130)),
            "act_ratio_std": float(ra.std()),
            "sim_ratio_std": float(rs.std()),
            "n_act": int(sum(1 for a in r["acts"] if a[1] != "保持")),
            "dur": int(e0 - s0),
        },
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)
    print("\n已保存: %s" % OUT)


if __name__ == "__main__":
    main()
