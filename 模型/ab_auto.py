# -*- coding: utf-8 -*-
"""
正确的反事实验证：模型自主调控，不读人工历史水率。

【之前错在哪】
旧脚本每步用 sc.wt.series(RATIO_SD)[i] 作 ratio_set 初值，
那是人工历史设定值。模型等于在人工轨迹上做微调，
99.5% 时间输出 == 人工值，验证结果毫无意义。

【现在怎么做】
1. 初值：取班次开始时的人工水率（开工设定，合理）
2. 之后：模型自己维护 cur_ratio，每步用自己上一轮的输出继续调
3. 人工历史水率完全不进入控制回路，只用于事后对比
4. T3 用响应核 + 共同扰动 d[t] 推演（共同扰动法，双方面对同一扰动）

这样才是真正的「若当时由模型接管会怎样」。
"""
import json
import os
import sys
import time

import numpy as np

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

from validate_new import load_single_zip, build_minute_table, G_OLD   # noqa: E402
from config import Tag, Config                                        # noqa: E402
from signal_conditioning import SignalConditioner                     # noqa: E402
from controller import XshController, Phase, Action                   # noqa: E402

OUT = os.path.join(BASE, ".cache", "new_ab_auto.json")
CTRL_PERIOD = 10


class AutoTable:
    """
    可写宽表：水率、给料量、T3 三测点可被逐分钟覆盖。
    控制器读到的水率是模型自己上一轮的值，不是人工历史值。
    """

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
    """模型自主调控：cur_ratio 由模型自己维护，不读人工历史"""
    n = wt.grid.size
    u_act = np.where(np.isnan(R), 0.0, R).astype(np.float64)
    for i in range(1, n):
        if np.isnan(R[i]):
            u_act[i] = u_act[i - 1]

    # 共同扰动：实际 T3 中水率解释不了的部分
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

    # 初值：班次开始时的人工水率（开工设定）
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
            # 模型只算给定值，是否采用由外部决定，故这里始终采纳
            cur_ratio = out.ratio_set
            cur_lime = out.lime_set
            acts.append((t - s0, out.action.value, out.ratio_set, out.reason))

    return dict(ratio_sim=ratio_sim, t3_sim=t3_sim,
                ratio_act=R[s0:e0 + 1].copy(), t3_act=T3[s0:e0 + 1].copy(),
                acts=acts)


def main():
    DATA_DIR = os.path.join(os.path.dirname(BASE), "脱硫脱硝消石灰制备数据")
    zips = sorted(f for f in os.listdir(DATA_DIR) if f.endswith(".zip"))
    wt = build_minute_table(load_single_zip(os.path.join(DATA_DIR, zips[-1])))
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

    print("=" * 90)
    print("正确的反事实验证：模型自主调控（不读人工历史水率）")
    print("=" * 90)
    print("初值取班次开工水率，之后由模型自己维护，人工历史不进入控制回路。")

    rows = []
    for s, e in segs:
        s0 = s + 120 if e - s > 150 else s + 60
        if e - s0 < 90:
            continue
        r = run_shift(wt, s0, e - 1, G_OLD, T3, R)
        label = time.strftime("%m-%d %H:%M", time.localtime(wt.grid[s0]))

        rs = r["ratio_sim"][~np.isnan(r["ratio_sim"])]
        ra = r["ratio_act"][~np.isnan(r["ratio_act"])]
        ta = r["t3_act"][~np.isnan(r["t3_act"])]
        ts = r["t3_sim"][~np.isnan(r["t3_sim"])]
        n_act = sum(1 for a in r["acts"] if a[1] not in ("保持",))

        rows.append(dict(label=label, dur=int(e - s0),
                         r_act_mean=float(ra.mean()), r_act_std=float(ra.std()),
                         r_sim_mean=float(rs.mean()), r_sim_std=float(rs.std()),
                         r_sim_min=float(rs.min()), r_sim_max=float(rs.max()),
                         t3_act=float(100 * np.mean((ta >= 100) & (ta <= 130))),
                         t3_sim=float(100 * np.mean((ts >= 100) & (ts <= 130))),
                         n_act=n_act))
        print("\n%s  (%d min)" % (label, e - s0))
        print("  人工水率: 均值 %.0f  std %.1f  范围 %.0f~%.0f" % (
            ra.mean(), ra.std(), ra.min(), ra.max()))
        print("  模型水率: 均值 %.0f  std %.1f  范围 %.0f~%.0f  动作 %d 次" % (
            rs.mean(), rs.std(), rs.min(), rs.max(), n_act))
        print("  T3 合格率: 人工 %.1f%%   模型 %.1f%%" % (
            100 * np.mean((ta >= 100) & (ta <= 130)),
            100 * np.mean((ts >= 100) & (ts <= 130))))

    print()
    print("=" * 90)
    print("汇总")
    print("=" * 90)
    print("%-16s %6s | %8s %8s | %8s %8s | %8s %8s %6s" % (
        "班次", "时长", "人工std", "模型std", "人工合格", "模型合格", "模型范围", "", "动作"))
    for r in rows:
        print("%-16s %6d | %8.1f %8.1f | %7.1f%% %7.1f%% | %4.0f~%-4.0f %6s %6d" % (
            r["label"], r["dur"], r["r_act_std"], r["r_sim_std"],
            r["t3_act"], r["t3_sim"], r["r_sim_min"], r["r_sim_max"], "", r["n_act"]))

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump({"rows": rows}, f, ensure_ascii=False)
    print("\n已保存: %s" % OUT)


if __name__ == "__main__":
    main()
