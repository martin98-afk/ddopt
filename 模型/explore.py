# -*- coding: utf-8 -*-
"""数据探查：生产时段识别、关键变量分布、控制动作与温度响应关系。"""
import numpy as np
from data_loader import build_wide

wt = build_wide(verbose=False)
g = wt.grid

PERMIT = "5#_XSH_GSGLYXXH"          # 给水给料允许信号
RATIO_SD = "5#_XSH_SL(SHB)SD"       # 水率设定
RATIO_FK = "5#_XSH_SL(SHB)FK"
WATER = "5#_XSH_SLLSJZ"             # 水流量实际值
LIME = "5#_XSH_SSHLLSJZ"            # 生石灰流量实际值
CURR1 = "5#_XSH_1JLXSSJDL"          # 1级电流
CURR2 = "5#_XSH_2JLXSSJDL"
CURR3 = "5#_XSH_3JLXSSJDL"
SPEED1 = "5#_XSH_1JLXSSJSDFK"       # 1级转速反馈
TEMP = [[f"5#_XSH_{j}JWDZ{k}" for k in (1, 2, 3)] for j in (1, 2, 3)]  # TEMP[级-1][测点]

print("=" * 78)
print("1. 生产时段识别（给水给料允许信号）")
print("=" * 78)
perm = wt.series(PERMIT)
print("允许信号=1 占比: %.2f%%  (%d 分钟)" % (100 * perm.mean(), perm.sum()))


def segments(mask):
    """布尔掩码 -> [(start_idx, end_idx_exclusive, length)]"""
    d = np.diff(mask.astype(np.int8))
    starts = list(np.where(d == 1)[0] + 1)
    ends = list(np.where(d == -1)[0] + 1)
    if mask[0]:
        starts.insert(0, 0)
    if mask[-1]:
        ends.append(mask.size)
    return [(s, e, e - s) for s, e in zip(starts, ends)]


segs = segments(perm > 0.5)
print("生产段数: %d" % len(segs))
for s, e, n in segs:
    print("  %s ~ %s  时长 %d 分钟 (%.1f h)" % (wt.time_full(s), wt.time_full(e - 1), n, n / 60))

# 长段（>=30min）作为分析对象
long_segs = [x for x in segs if x[2] >= 30]
prod_mask = np.zeros(g.size, dtype=bool)
for s, e, n in long_segs:
    prod_mask[s:e] = True
print("\n有效生产段(>=30min): %d 段, 合计 %d 分钟 (%.1f h)" % (
    len(long_segs), prod_mask.sum(), prod_mask.sum() / 60))

print()
print("=" * 78)
print("2. 生产时段内关键变量分布")
print("=" * 78)
print("%-22s %8s %8s %8s %8s %8s %8s" % ("变量", "均值", "P05", "P25", "P50", "P75", "P95"))
for label, name in [("L1电流", CURR1), ("L2电流", CURR2), ("L3电流", CURR3),
                    ("水率设定", RATIO_SD), ("水率反馈", RATIO_FK),
                    ("水流量", WATER), ("生石灰流量", LIME), ("1级转速", SPEED1)]:
    v = wt.series(name)[prod_mask]
    v = v[~np.isnan(v)]
    q = np.percentile(v, [5, 25, 50, 75, 95])
    print("%-22s %8.2f %8.2f %8.2f %8.2f %8.2f %8.2f" % (label, v.mean(), *q))

print()
for j in range(3):
    for k in range(3):
        v = wt.series(TEMP[j][k])[prod_mask]
        v = v[~np.isnan(v)]
        q = np.percentile(v, [5, 25, 50, 75, 95])
        print("T%d-%d  %-16s %8.2f %8.2f %8.2f %8.2f %8.2f %8.2f" % (
            j + 1, k + 1, "", v.mean(), *q))

print()
print("=" * 78)
print("3. 层级温度均值与「L2最高」达成率")
print("=" * 78)
t1 = np.nanmean([wt.series(t)[prod_mask] for t in TEMP[0]], axis=0)
t2 = np.nanmean([wt.series(t)[prod_mask] for t in TEMP[1]], axis=0)
t3 = np.nanmean([wt.series(t)[prod_mask] for t in TEMP[2]], axis=0)
print("T1均值 %.1f  T2均值 %.1f  T3均值 %.1f" % (np.nanmean(t1), np.nanmean(t2), np.nanmean(t3)))
print("T2 > T1 占比: %.1f%%" % (100 * np.mean(t2 > t1)))
print("T2 > T3 占比: %.1f%%" % (100 * np.mean(t2 > t3)))
print("T2 同时 >T1 且 >T3: %.1f%%" % (100 * np.mean((t2 > t1) & (t2 > t3))))
print("T3 在 [100,130] 占比: %.1f%%" % (100 * np.mean((t3 >= 100) & (t3 <= 130))))
print("T3 < 100 占比: %.1f%%   T3 > 130 占比: %.1f%%" % (
    100 * np.mean(t3 < 100), 100 * np.mean(t3 > 130)))
print("L1电流 > 18 占比: %.2f%%   最大 %.2f" % (
    100 * np.mean(wt.series(CURR1)[prod_mask] > 18), np.nanmax(wt.series(CURR1)[prod_mask])))

print()
print("=" * 78)
print("4. 水率设定 vs 温度：分段统计（生产时段）")
print("=" * 78)
r = wt.series(RATIO_SD)[prod_mask]
bins = [(300, 400), (400, 500), (500, 600), (600, 700), (700, 760)]
print("%-12s %6s %8s %8s %8s %8s" % ("水率区间", "样本", "T1", "T2", "T3", "L1电流"))
for lo, hi in bins:
    m = (r >= lo) & (r < hi)
    if m.sum() < 5:
        continue
    print("%-12s %6d %8.1f %8.1f %8.1f %8.2f" % (
        "%d-%d" % (lo, hi), m.sum(), np.nanmean(t1[m]), np.nanmean(t2[m]),
        np.nanmean(t3[m]), np.nanmean(wt.series(CURR1)[prod_mask][m])))

print()
print("=" * 78)
print("5. 水率设定 vs 温度：相关性（含时滞 0~40 分钟）")
print("=" * 78)


def corr_lag(a, b, lag):
    """a[t] 与 b[t+lag] 的相关系数"""
    if lag == 0:
        x, y = a, b
    elif lag > 0:
        x, y = a[:-lag], b[lag:]
    else:
        x, y = a[-lag:], b[:lag]
    m = ~(np.isnan(x) | np.isnan(y))
    if m.sum() < 50:
        return np.nan, 0
    return float(np.corrcoef(x[m], y[m])[0, 1]), int(m.sum())


for lag in (0, 5, 10, 15, 20, 30, 40):
    c_t2, n = corr_lag(r, t2, lag)
    c_t3, _ = corr_lag(r, t3, lag)
    c_c1, _ = corr_lag(r, wt.series(CURR1)[prod_mask], lag)
    print("lag=%2d min  n=%5d  corr(水率,T2)=%+.3f  corr(水率,T3)=%+.3f  corr(水率,L1电流)=%+.3f"
          % (lag, n, c_t2, c_t3, c_c1))

print()
print("=" * 78)
print("6. 生石灰流量 vs 1级电流（滞后）")
print("=" * 78)
lime_v = wt.series(LIME)[prod_mask]
c1_v = wt.series(CURR1)[prod_mask]
for lag in (0, 5, 10, 15, 20):
    c, n = corr_lag(lime_v, c1_v, lag)
    print("lag=%2d min  corr(生石灰流量,L1电流)=%+.3f  n=%d" % (lag, c, n))

print()
print("=" * 78)
print("7. 水率实际配比校验：水流量 / 生石灰流量")
print("=" * 78)
w = wt.series(WATER)[prod_mask]
lm = wt.series(LIME)[prod_mask]
m = (lm > 0.5) & (w > 10)
if m.sum() > 0:
    ratio_act = w[m] / lm[m]
    print("样本 %d, 实际水灰比(L/t 或 L每t) 均值 %.0f, P05 %.0f, P50 %.0f, P95 %.0f" % (
        m.sum(), ratio_act.mean(), *np.percentile(ratio_act, [5, 50, 95])))
    print("水率设定 均值 %.0f, 水流量均值 %.0f, 生石灰流量均值 %.2f" % (
        np.nanmean(r[m]), np.nanmean(w[m]), np.nanmean(lm[m])))
    print("推论：水流量单位若为 L/h，则 水率设定 ≈ 水流量/生石灰流量/10 -> 检查系数")
    print("  实际 水流量/生石灰流量 = %.0f ; 水率设定 = %.0f ; 比值 %.2f" % (
        np.nanmean(w[m] / lm[m]), np.nanmean(r[m]),
        np.nanmean(w[m] / lm[m]) / max(np.nanmean(r[m]), 1e-9)))
