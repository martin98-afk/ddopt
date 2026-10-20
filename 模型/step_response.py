# -*- coding: utf-8 -*-
"""
阶跃响应分析：识别水率设定发生阶跃变化的时刻，观察各温度/电流的平均响应曲线。
用于获取真实的因果方向与时滞常数（横截面相关性因操作员反馈而不可信）。
"""
import numpy as np
from data_loader import build_wide

wt = build_wide(verbose=False)
g = wt.grid

PERMIT = "5#_XSH_GSGLYXXH"
RATIO = "5#_XSH_SL(SHB)SD"
LIME = "5#_XSH_SSHLLSJZ"
WATER = "5#_XSH_SLLSJZ"
CURR1 = "5#_XSH_1JLXSSJDL"
TEMP = [[f"5#_XSH_{j}JWDZ{k}" for k in (1, 2, 3)] for j in (1, 2, 3)]

perm = wt.series(PERMIT) > 0.5
# 生产段（连续 >= 30 分钟），用于限制事件搜索范围
d = np.diff(perm.astype(np.int8))
starts = list(np.where(d == 1)[0] + 1)
ends = list(np.where(d == -1)[0] + 1)
if perm[0]:
    starts.insert(0, 0)
if perm[-1]:
    ends.append(perm.size)
segs = [(s, e) for s, e in zip(starts, ends) if e - s >= 30]

r = wt.series(RATIO)
t1 = np.nanmean([wt.series(t) for t in TEMP[0]], axis=0)
t2 = np.nanmean([wt.series(t) for t in TEMP[1]], axis=0)
t3 = np.nanmean([wt.series(t) for t in TEMP[2]], axis=0)
c1 = wt.series(CURR1)
lm = wt.series(LIME)
wv = wt.series(WATER)

# ---------- 异常值清洗：单点跳变（前后 5 分钟中位差 > 40℃）视为仪表故障 ----------
def despike(x, thresh=40.0, win=5):
    out = x.copy()
    n = x.size
    for i in range(n):
        if np.isnan(x[i]):
            continue
        lo = max(0, i - win)
        hi = min(n, i + win + 1)
        nb = x[lo:hi]
        nb = nb[~np.isnan(nb)]
        if nb.size < 3:
            continue
        med = np.median(nb)
        if abs(x[i] - med) > thresh and abs(x[i] - med) > 3 * np.std(nb) + 1:
            out[i] = np.nan
    return out


print("=" * 76)
print("0. 温度异常点统计（单点跳变 > 40℃）")
print("=" * 76)
t_clean = []
for j in range(3):
    row = []
    for k in range(3):
        x = wt.series(TEMP[j][k])
        xs = despike(x)
        nbad = int(np.sum(~np.isnan(x)) - np.sum(~np.isnan(xs)))
        print("  T%d-%d  异常点 %d / %d (%.2f%%)  原始最大 %.1f -> 清洗后最大 %.1f" % (
            j + 1, k + 1, nbad, np.sum(~np.isnan(x)),
            100 * nbad / max(np.sum(~np.isnan(x)), 1),
            np.nanmax(x), np.nanmax(xs)))
        row.append(xs)
    t_clean.append(row)

T1 = np.nanmean([t_clean[0][k] for k in range(3)], axis=0)
T2 = np.nanmean([t_clean[1][k] for k in range(3)], axis=0)
T3 = np.nanmean([t_clean[2][k] for k in range(3)], axis=0)

print()
print("=" * 76)
print("1. 清洗后 生产时段 层级温度")
print("=" * 76)
m = perm & ~np.isnan(T1) & ~np.isnan(T2) & ~np.isnan(T3)
print("T1 %.1f  T2 %.1f  T3 %.1f   (样本 %d 分钟)" % (
    np.nanmean(T1[m]), np.nanmean(T2[m]), np.nanmean(T3[m]), m.sum()))
print("T2 > T1 : %.1f%%    T2 > T3 : %.1f%%    T2 最高 : %.1f%%" % (
    100 * np.mean(T2[m] > T1[m]), 100 * np.mean(T2[m] > T3[m]),
    100 * np.mean((T2[m] > T1[m]) & (T2[m] > T3[m]))))
print("T3 在[100,130]: %.1f%%   <100: %.1f%%   >130: %.1f%%" % (
    100 * np.mean((T3[m] >= 100) & (T3[m] <= 130)),
    100 * np.mean(T3[m] < 100), 100 * np.mean(T3[m] > 130)))

# ---------- 事件检测：水率设定阶跃 ----------
PRE, POST = 30, 90          # 事件前 30 分钟基线，事件后 90 分钟观察窗
MIN_STEP = 20.0             # 最小阶跃幅度 (L/t)
QUIET = 30                  # 事件前后需保持稳定的分钟数

events = []
for s, e in segs:
    for i in range(s + PRE, e - POST):
        base = r[i - PRE:i]
        aft = r[i:i + 8]
        if np.isnan(base).any() or np.isnan(aft).any():
            continue
        if base.std() > 5:          # 基线需平稳
            continue
        step = aft.mean() - base.mean()
        if abs(step) < MIN_STEP:
            continue
        # 事件后需保持新值
        if r[i + 8:i + 30].std() > 8:
            continue
        events.append((i, step))

# 去重：相邻太近的事件只保留第一个
dedup = []
last_i = -999
for i, step in events:
    if i - last_i >= 45:
        dedup.append((i, step))
        last_i = i
events = dedup

print()
print("=" * 76)
print("2. 水率设定阶跃事件：%d 个（升 %d / 降 %d）" % (
    len(events), sum(1 for _, s in events if s > 0), sum(1 for _, s in events if s < 0)))
print("=" * 76)

if events:
    HOR = PRE + POST
    resp = {k: np.zeros((len(events), HOR)) for k in
            ["T1", "T2", "T3", "C1", "LIME", "WATER", "RATIO"]}
    valid = np.zeros((len(events), HOR), dtype=bool)
    for ei, (i, step) in enumerate(events):
        sl = slice(i - PRE, i + POST)
        for key, arr in [("T1", T1), ("T2", T2), ("T3", T3), ("C1", c1),
                         ("LIME", lm), ("WATER", wv), ("RATIO", r)]:
            resp[key][ei] = arr[sl]
        valid[ei] = ~np.isnan(T2[sl])
        # 归一化：按阶跃方向翻转，使"加水"方向为正
        if step < 0:
            for key in resp:
                resp[key][ei] = 2 * resp[key][ei][PRE] - resp[key][ei]

    print("\n相对阶跃时刻的平均响应（已按方向归一为「水率↑」）")
    print("%5s %8s %8s %8s %8s %9s %9s" % ("min", "T1", "T2", "T3", "L1电流", "水流量", "水率"))
    for lag in range(-PRE, POST):
        idx = lag + PRE
        n = valid[:, idx].sum()
        if n < len(events) * 0.3:
            continue
        if lag % 5 and lag != 0:
            continue
        print("%5d %8.2f %8.2f %8.2f %8.3f %9.0f %9.1f" % (
            lag, np.nanmean(resp["T1"][:, idx]), np.nanmean(resp["T2"][:, idx]),
            np.nanmean(resp["T3"][:, idx]), np.nanmean(resp["C1"][:, idx]),
            np.nanmean(resp["WATER"][:, idx]), np.nanmean(resp["RATIO"][:, idx])))

    # 估算一阶惯性时滞
    # 注意：观察窗总长 HOR = PRE + POST，索引上限为 HOR-1，
    # 故 h 必须满足 PRE + h < HOR，否则会越界（原实现 h=90 时崩溃）。
    print("\n各温度对水率阶跃的响应幅度（相对事件前基线）")
    for key in ("T1", "T2", "T3"):
        base = np.nanmean(resp[key][:, :PRE], axis=1)
        for h in (10, 20, 30, 45, 60, 89):
            idx = PRE + h
            if idx >= HOR:
                continue
            n = valid[:, idx].sum()
            if n < len(events) * 0.3:
                continue
            delta = np.nanmean(resp[key][:, idx] - base)
            print("  %s @%3dmin: %+6.2f ℃  (n=%d)" % (key, h, delta, n), end="")
        print()

# ---------- 生石灰流量阶跃 ----------
print()
print("=" * 76)
print("3. 生石灰流量阶跃事件")
print("=" * 76)
events_l = []
for s, e in segs:
    for i in range(s + PRE, e - POST):
        base = lm[i - PRE:i]
        aft = lm[i:i + 8]
        if np.isnan(base).any() or np.isnan(aft).any():
            continue
        if base.std() > 0.3:
            continue
        step = aft.mean() - base.mean()
        if abs(step) < 0.3:
            continue
        if lm[i + 8:i + 30].std() > 0.4:
            continue
        events_l.append((i, step))

dedup = []
last_i = -999
for i, step in events_l:
    if i - last_i >= 45:
        dedup.append((i, step))
        last_i = i
events_l = dedup
print("事件数: %d（升 %d / 降 %d）" % (
    len(events_l), sum(1 for _, s in events_l if s > 0), sum(1 for _, s in events_l if s < 0)))

if events_l:
    HOR = PRE + POST
    rl = {k: np.zeros((len(events_l), HOR)) for k in ("T1", "T2", "T3", "C1", "RATIO", "LIME")}
    for ei, (i, step) in enumerate(events_l):
        sl = slice(i - PRE, i + POST)
        for key, arr in [("T1", T1), ("T2", T2), ("T3", T3), ("C1", c1), ("RATIO", r), ("LIME", lm)]:
            rl[key][ei] = arr[sl]
        if step < 0:
            for key in rl:
                rl[key][ei] = 2 * rl[key][ei][PRE] - rl[key][ei]
    print("\n相对阶跃时刻的平均响应（归一为「生石灰↑」）")
    print("%5s %8s %8s %8s %8s %8s" % ("min", "T1", "T2", "T3", "L1电流", "水率"))
    for lag in range(-PRE, POST):
        idx = lag + PRE
        if lag % 5 and lag != 0:
            continue
        print("%5d %8.2f %8.2f %8.2f %8.3f %8.1f" % (
            lag, np.nanmean(rl["T1"][:, idx]), np.nanmean(rl["T2"][:, idx]),
            np.nanmean(rl["T3"][:, idx]), np.nanmean(rl["C1"][:, idx]),
            np.nanmean(rl["RATIO"][:, idx])))
