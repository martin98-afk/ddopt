# -*- coding: utf-8 -*-
"""
从历史数据中挑出 T3 超限最严重的稳态段，用于反事实 A/B。

判据：稳态段内 T3 >130℃ 占比最高的班次。
只用旧数据（D:/work/脱硫脱硝/data/），新数据不参与。
"""
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

print("=" * 100)
print("历史数据各班次稳态段的 T3 超限情况（挑最严重的做反事实）")
print("=" * 100)
print("%-18s %6s %8s %8s %8s %8s %8s %8s" % (
    "稳态段起点", "时长", "T3均值", "T3std", ">130", ">126", "<100", "水率均值"))

cands = []
import time
for s, e in segs:
    s0 = s + 120 if e - s > 150 else s + 60
    if e - s0 < 90:
        continue
    t3 = T3[s0:e]
    t3 = t3[~np.isnan(t3)]
    if t3.size < 60:
        continue
    r = R[s0:e]
    r = r[~np.isnan(r)]
    label = time.strftime("%m-%d %H:%M", time.localtime(wt.grid[s0]))
    row = dict(s0=s0, e=e, label=label, n=int(t3.size),
               mean=float(t3.mean()), std=float(t3.std()),
               above130=float(100 * np.mean(t3 > 130)),
               above126=float(100 * np.mean(t3 > 126)),
               below100=float(100 * np.mean(t3 < 100)),
               ratio=float(r.mean()) if r.size else np.nan)
    cands.append(row)
    print("%-18s %6d %8.1f %8.1f %7.1f%% %7.1f%% %7.1f%% %8.0f" % (
        label, row["n"], row["mean"], row["std"],
        row["above130"], row["above126"], row["below100"], row["ratio"]))

print()
print("=" * 100)
print("按 T3>130 占比排序，前 5 名")
print("=" * 100)
cands.sort(key=lambda x: -x["above130"])
for i, c in enumerate(cands[:5]):
    print("  %d. %s  >130 占 %.1f%%  T3均值 %.1f  std %.1f  (%d min)" % (
        i + 1, c["label"], c["above130"], c["mean"], c["std"], c["n"]))

print()
print("=" * 100)
print("按 T3>126 占比排序，前 5 名（守护带上级别）")
print("=" * 100)
cands.sort(key=lambda x: -x["above126"])
for i, c in enumerate(cands[:5]):
    print("  %d. %s  >126 占 %.1f%%  T3均值 %.1f  std %.1f  (%d min)" % (
        i + 1, c["label"], c["above126"], c["mean"], c["std"], c["n"]))

if cands:
    best = max(cands, key=lambda x: x["above130"])
    print()
    print("推荐用于反事实: %s  (T3>130 占 %.1f%%, 起点索引 s0=%d, 终点 e=%d)" % (
        best["label"], best["above130"], best["s0"], best["e"]))
