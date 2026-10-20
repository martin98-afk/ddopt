# -*- coding: utf-8 -*-
"""
在 T3 偏低的班次上验证模型的「减水」方向。

选用 10-16 00:04（T3<110 占 64.3%，均值 108.8）。
这个班次考验的是：T3 低于守护带下限时，模型会不会减水。
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

from config import Tag                                      # noqa: E402
from ab_worst import run_shift, G_OLD                       # noqa: E402


def analyse(wt, s0, e0, label, tag):
    R = wt.series(Tag.RATIO_SD)
    T3 = np.nanmean([wt.series(t) for t in Tag.TEMP[2]], axis=0)
    r = run_shift(wt, s0, e0 - 1, G_OLD, T3, R)

    rs = r["ratio_sim"][~np.isnan(r["ratio_sim"])]
    ra = r["ratio_act"][~np.isnan(r["ratio_act"])]
    ta = r["t3_act"][~np.isnan(r["t3_act"])]
    ts = r["t3_sim"][~np.isnan(r["t3_sim"])]
    n_act = sum(1 for a in r["acts"] if a[1] != "保持")

    print("=" * 96)
    print("%s  %s（%d min）" % (tag, label, e0 - s0))
    print("=" * 96)
    print("水率:")
    print("  人工: 均值 %.0f  std %.1f  范围 %.0f~%.0f  动作 %d 次" % (
        ra.mean(), ra.std(), ra.min(), ra.max(),
        int(np.sum(np.abs(np.diff(ra)) > 0.5))))
    print("  模型: 均值 %.0f  std %.1f  范围 %.0f~%.0f  动作 %d 次" % (
        rs.mean(), rs.std(), rs.min(), rs.max(), n_act))
    print("T3:")
    print("  人工: 均值 %.1f  合格率 %.1f%%  <110 %.1f%%  <100 %.1f%%" % (
        ta.mean(), 100 * np.mean((ta >= 100) & (ta <= 130)),
        100 * np.mean(ta < 110), 100 * np.mean(ta < 100)))
    print("  模型: 均值 %.1f  合格率 %.1f%%  <110 %.1f%%  <100 %.1f%%" % (
        ts.mean(), 100 * np.mean((ts >= 100) & (ts <= 130)),
        100 * np.mean(ts < 110), 100 * np.mean(ts < 100)))

    print()
    print("模型动作:")
    for a in r["acts"]:
        if a[1] != "保持":
            print("  t=%3d  %-10s 水率->%.0f  给料->%.2f  %s" % (
                a[0], a[1], a[2], a[3], a[4][:58]))
    if n_act == 0:
        print("  （无动作）")

    # 动作方向统计
    from collections import Counter
    c = Counter(a[1] for a in r["acts"] if a[1] != "保持")
    print()
    print("方向统计: %s" % dict(c))
    print()
    return r


def main():
    wt = data_loader.build_wide(verbose=False, use_cache=False)
    R = wt.series(Tag.RATIO_SD)
    T3 = np.nanmean([wt.series(t) for t in Tag.TEMP[2]], axis=0)
    perm = (wt.series(Tag.PERMIT) > 0.5) & (wt.series(Tag.LIME) > 0.1)

    d = np.diff(perm.astype(np.int8))
    starts = list(np.where(d == 1)[0] + 1)
    ends = list(np.where(d == -1)[0] + 1)
    if perm[0]:
        starts.insert(0, 0)
    if perm[-1]:
        ends.append(n_ := wt.grid.size)
    segs = [(s, e) for s, e in zip(starts, ends) if e - s >= 30]

    import time
    targets = []
    for s, e in segs:
        s0 = s + 120 if e - s > 150 else s + 60
        if e - s0 < 90:
            continue
        t3 = T3[s0:e]
        t3 = t3[~np.isnan(t3)]
        if t3.size < 60:
            continue
        below = 100 * np.mean(t3 < 110)
        above = 100 * np.mean(t3 > 122)
        targets.append((below, above, s0, e,
                        time.strftime("%m-%d %H:%M", time.localtime(wt.grid[s0]))))

    targets.sort(key=lambda x: -x[0])

    results = []
    for below, above, s0, e, label in targets[:2]:
        if below < 5:
            continue
        tag = "【偏低工况】" if above < 5 else "【双向工况】"
        r = analyse(wt, s0, e, label, tag)
        results.append((label, r))

    print("=" * 96)
    print("汇总：模型在偏低工况下的减水行为")
    print("=" * 96)
    for label, r in results:
        acts = [a for a in r["acts"] if a[1] != "保持"]
        n_lower = sum(1 for a in acts if a[1] == "降低水率")
        n_raise = sum(1 for a in acts if a[1] == "提高水率")
        rs = r["ratio_sim"][~np.isnan(r["ratio_sim"])]
        ra = r["ratio_act"][~np.isnan(r["ratio_act"])]
        print("  %s  模型减水 %d 次 / 加水 %d 次   水率 %.0f→%.0f（人工 %.0f→%.0f）" % (
            label, n_lower, n_raise, rs[0], rs[-1], ra[0], ra[-1]))

    print()
    print("判读：")
    print("  T3 持续低于守护带下限 110 时，模型应当【减水】以升温。")
    print("  若减水次数为 0，说明模型在偏低方向仍然失灵，需再查。")


if __name__ == "__main__":
    main()
