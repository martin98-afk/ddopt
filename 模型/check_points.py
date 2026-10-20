# -*- coding: utf-8 -*-
"""测点诊断：温度测点时序形态、异常区间、各段统计。"""
import numpy as np
from data_loader import build_wide

wt = build_wide(verbose=False)
PERMIT = "5#_XSH_GSGLYXXH"
perm = wt.series(PERMIT) > 0.5

TEMP = [[f"5#_XSH_{j}JWDZ{k}" for k in (1, 2, 3)] for j in (1, 2, 3)]

print("=" * 88)
print("1. 各温度测点：全周期 / 生产时段 分位统计")
print("=" * 88)
print("%-8s %10s %8s %8s %8s %8s %8s %8s" % ("测点", "生产均值", "P01", "P50", "P99", "最大", "最大时刻", ">200占比"))
for j in range(3):
    for k in range(3):
        n = TEMP[j][k]
        x = wt.series(n)
        xp = x[perm]
        q = np.percentile(xp, [1, 50, 99])
        imax = int(np.nanargmax(x))
        print("%-8s %10.1f %8.1f %8.1f %8.1f %8.1f %8s %8.2f%%" % (
            "T%d-%d" % (j + 1, k + 1), np.nanmean(xp), q[0], q[1], q[2],
            np.nanmax(x), wt.time_str(imax), 100 * np.nanmean(xp > 200)))

print()
print("=" * 88)
print("2. 极端值时段定位（温度 > 250℃ 的连续区间）")
print("=" * 88)
for j in range(3):
    for k in range(3):
        x = wt.series(TEMP[j][k])
        m = x > 250
        if not m.any():
            continue
        d = np.diff(m.astype(np.int8))
        s = list(np.where(d == 1)[0] + 1)
        e = list(np.where(d == -1)[0] + 1)
        if m[0]:
            s.insert(0, 0)
        if m[-1]:
            e.append(m.size)
        print("T%d-%d: %d 分钟 >250℃" % (j + 1, k + 1, m.sum()))
        for a, b in list(zip(s, e))[:8]:
            print("    %s ~ %s (%d min) 峰值 %.0f  生产=%s" % (
                wt.time_full(a), wt.time_full(b - 1), b - a,
                np.nanmax(x[a:b]), "是" if perm[a] else "否"))

print()
print("=" * 88)
print("3. T2 三个测点的一致性（生产时段，两两差）")
print("=" * 88)
a, b, c = [wt.series(TEMP[1][k])[perm] for k in range(3)]
print("T2-1 vs T2-2: 均值差 %+.1f, 相关系数 %+.3f" % (
    np.nanmean(a - b), np.corrcoef(a[~np.isnan(a) & ~np.isnan(b)],
                                   b[~np.isnan(a) & ~np.isnan(b)])[0, 1]))
print("T2-1 vs T2-3: 均值差 %+.1f, 相关系数 %+.3f" % (
    np.nanmean(a - c), np.corrcoef(a[~np.isnan(a) & ~np.isnan(c)],
                                   c[~np.isnan(a) & ~np.isnan(c)])[0, 1]))
print("T2-2 vs T2-3: 均值差 %+.1f, 相关系数 %+.3f" % (
    np.nanmean(b - c), np.corrcoef(b[~np.isnan(b) & ~np.isnan(c)],
                                   c[~np.isnan(b) & ~np.isnan(c)])[0, 1]))

print()
print("=" * 88)
print("4. 各生产班次的关键指标（按段）")
print("=" * 88)
d = np.diff(perm.astype(np.int8))
starts = list(np.where(d == 1)[0] + 1)
ends = list(np.where(d == -1)[0] + 1)
if perm[0]:
    starts.insert(0, 0)
if perm[-1]:
    ends.append(perm.size)
segs = [(s, e) for s, e in zip(starts, ends) if e - s >= 30]

T1 = np.nanmean([wt.series(t) for t in TEMP[0]], axis=0)
T2 = np.nanmean([wt.series(t) for t in TEMP[1]], axis=0)
T3 = np.nanmean([wt.series(t) for t in TEMP[2]], axis=0)
C1 = wt.series("5#_XSH_1JLXSSJDL")
R = wt.series("5#_XSH_SL(SHB)SD")
L = wt.series("5#_XSH_SSHLLSJZ")

print("%-20s %6s %7s %7s %7s %7s %7s %7s" % (
    "班次起始", "时长", "T1", "T2", "T3", "L1电流", "水率", "石灰流量"))
for s, e in segs:
    sl = slice(s, e)
    print("%-20s %6d %7.1f %7.1f %7.1f %7.2f %7.0f %7.2f" % (
        wt.time_full(s), e - s, np.nanmean(T1[sl]), np.nanmean(T2[sl]),
        np.nanmean(T3[sl]), np.nanmean(C1[sl]), np.nanmean(R[sl]), np.nanmean(L[sl])))

print()
print("=" * 88)
print("5. 非生产时段（允许信号=0）的温度与流量：确认停机特征")
print("=" * 88)
off = ~perm
print("非生产 %d 分钟" % off.sum())
print("  T1 %.1f  T2 %.1f  T3 %.1f" % (
    np.nanmean(T1[off]), np.nanmean(T2[off]), np.nanmean(T3[off])))
print("  L1电流 %.2f  生石灰流量 %.2f  水流量 %.0f" % (
    np.nanmean(C1[off]), np.nanmean(L[off]), np.nanmean(wt.series("5#_XSH_SLLSJZ")[off])))
