# -*- coding: utf-8 -*-
"""
找适合验证「减水方向」的班次。

需求：T3 有落到守护带下限（110）以下的数据，
      才能检验模型在 T3 偏低时是否会减水。
同时最好有「先超上限、后跌到下限」的完整过程，
      这样一次验证两个方向。
"""
import os
import sys
import time

import numpy as np

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

OLD_DATA = r"D:/work/脱硫脱硝/data/脱硫脱硝消石灰制备数据"
os.environ["XSH_DATA_DIR"] = OLD_DATA

import data_loader                                        # noqa: E402
data_loader.DATA_DIR = OLD_DATA
data_loader.CACHE_DIR = os.path.join(BASE, ".cache_old")

from config import Tag                                      # noqa: E402

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

print("=" * 108)
print("各班次稳态段的 T3 分布（找有减水机会的）")
print("=" * 108)
print("%-16s %6s %8s %8s %7s %7s %7s %9s" % (
    "稳态段", "时长", "T3均值", "T3std", ">122", "<110", "<100", "跌到<110时刻"))

cands = []
for s, e in segs:
    s0 = s + 120 if e - s > 150 else s + 60
    if e - s0 < 90:
        continue
    t3 = T3[s0:e]
    valid = ~np.isnan(t3)
    if valid.sum() < 60:
        continue
    t3v = t3[valid]
    label = time.strftime("%m-%d %H:%M", time.localtime(wt.grid[s0]))
    below = 100 * np.mean(t3v < 110)
    above = 100 * np.mean(t3v > 122)
    # 首次跌破 110 的位置（相对稳态段起点）
    idx_below = np.where(t3v < 110)[0]
    first_below = int(idx_below[0]) if idx_below.size else -1
    row = dict(s0=s0, e=e, label=label, n=int(valid.sum()),
               mean=float(t3v.mean()), std=float(t3v.std()),
               above=above, below=below,
               below100=float(100 * np.mean(t3v < 100)),
               first_below=first_below,
               has_both=(above > 5 and below > 5))
    cands.append(row)
    print("%-16s %6d %8.1f %8.1f %6.1f%% %6.1f%% %6.1f%% %9s" % (
        label, row["n"], row["mean"], row["std"], above, below,
        row["below100"],
        ("t=%d min" % first_below) if first_below >= 0 else "无"))

print()
print("=" * 108)
print("按 <110 占比排序（减水机会最多的）")
print("=" * 108)
cands.sort(key=lambda x: -x["below"])
for c in cands:
    tag = "  <== 双向（先超后跌）" if c["has_both"] else ""
    print("  %s  <110 占 %.1f%%  >122 占 %.1f%%  T3均值 %.1f%s" % (
        c["label"], c["below"], c["above"], c["mean"], tag))

if cands:
    best = max(cands, key=lambda x: x["below"])
    print()
    if best["below"] > 1:
        print("推荐: %s（T3<110 占 %.1f%%，s0=%d, e=%d）" % (
            best["label"], best["below"], best["s0"], best["e"]))
    else:
        print("历史数据中几乎没有 T3<110 的稳态段，减水方向无从验证。")
        print("建议：若要验证减水，需现场提供 T3 偏低工况的数据。")
