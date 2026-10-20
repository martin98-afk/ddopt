# -*- coding: utf-8 -*-
"""
生石灰流量（给料量）控制曲线：模型 vs 人工。

这是模型三个输出通道里唯一实际动作过的：
  水率     —— 全程不动
  水流量   —— 不直接控制
  给料量   —— T3 逼近上限时降载（本脚本呈现的就是它）

纪律：单班次最多 3 次降载，每次 -0.2 t/h，下限 3.0 t/h，
      超出则停止自动降料并报警转人工。
"""
import json
import os
import time

import numpy as np

from ab_test import identify_kernel, run_shift
from data_loader import build_wide
from config import Tag, Config

BASE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(BASE, ".cache", "lime_cmp.json")


def main():
    wt = build_wide(verbose=False)
    R = wt.series(Tag.RATIO_SD)
    T3 = np.nanmean([wt.series(t) for t in Tag.TEMP[2]], axis=0)
    perm = wt.series(Tag.PERMIT) > 0.5

    d = np.diff(perm.astype(np.int8))
    starts = list(np.where(d == 1)[0] + 1)
    ends = list(np.where(d == -1)[0] + 1)
    if perm[0]:
        starts.insert(0, 0)
    if perm[-1]:
        ends.append(perm.size)
    segs = [(s, e) for s, e in zip(starts, ends) if e - s >= 30]

    G, n_ev, _, _ = identify_kernel(wt, segs, R, T3)

    print("=" * 88)
    print("生石灰流量（给料量）控制对比")
    print("=" * 88)
    print("%-16s %5s | %-16s | %-16s | %6s" % (
        "班次", "时长", "人工给料 t/h", "模型给料 t/h", "降载次数"))
    print("%-16s %5s | %7s %7s | %7s %7s | %6s" % (
        "", "min", "均值", "std", "均值", "std", ""))

    rows, charts = [], []
    for s, e in segs:
        s0 = s + 120 if e - s > 150 else s + 60
        if e - s0 < 90:
            continue
        cfg = Config()
        cfg.set_curr1_high(18.0)
        r = run_shift(wt, cfg, s0, e - 1, G, T3, R)

        la = r["lime_act"]
        ls = r["lime_sim"]
        la = la[~np.isnan(la)]
        ls = ls[~np.isnan(ls)]

        # 降载动作次数（只统计真的降了的）
        n_derate = sum(1 for a in r["acts"]
                       if a[1] == "减少给料")
        label = time.strftime("%m-%d %H:%M", time.localtime(wt.grid[s0]))
        print("%-16s %5d | %7.2f %7.2f | %7.2f %7.2f | %6d" % (
            label, e - s0, la.mean(), la.std(), ls.mean(), ls.std(), n_derate))

        idx = list(range(0, len(r["lime_sim"]), 5))
        charts.append(dict(
            label=label, t=idx,
            act=[None if np.isnan(r["lime_act"][i]) else round(float(r["lime_act"][i]), 2)
                 for i in idx],
            sim=[None if np.isnan(r["lime_sim"][i]) else round(float(r["lime_sim"][i]), 2)
                 for i in idx],
            # 降载动作的时刻与幅度，用于在图上打点
            marks=[{"t": int(a[0]), "v": round(float(a[3]), 2)}
                   for a in r["acts"] if a[1] == "减少给料"],
        ))
        rows.append(dict(label=label, dur=int(e - s0),
                         act_mean=float(la.mean()), act_std=float(la.std()),
                         sim_mean=float(ls.mean()), sim_std=float(ls.std()),
                         n_derate=n_derate,
                         t3_high=float(np.nanmean(r["t3_sim"] > 126)) * 100))

    tot_act_std = np.mean([r["act_std"] for r in rows])
    tot_sim_std = np.mean([r["sim_std"] for r in rows])
    tot_derate = sum(r["n_derate"] for r in rows)
    hours = sum(r["dur"] for r in rows) / 60.0
    print()
    print("-" * 88)
    print("汇总（%.1f 小时，%d 个班次）" % (hours, len(rows)))
    print("-" * 88)
    print("  给料量标准差    人工 %.2f    模型 %.2f" % (tot_act_std, tot_sim_std))
    print("  降载动作总次数  %d 次（%.2f 次/小时）" % (
        tot_derate, tot_derate / hours))
    print("  降载纪律        单班次 ≤3 次，步长 -0.2 t/h，下限 3.0 t/h")
    print()
    print("  未触发降载的班次: %d / %d" % (
        sum(1 for r in rows if r["n_derate"] == 0), len(rows)))
    print("  全程给料量最低点: %.2f t/h" % min(r["sim_mean"] for r in rows))

    print()
    print("=" * 88)
    print("这条通道的三条硬约束")
    print("=" * 88)
    print("""  1. 次数上限 3 次/班次  —— 防止无限降载（曾出现 29 次横跳）
  2. 幅度下限 3.0 t/h    —— 保证产量，不因降温把料停了
  3. 仅 T3 逼近上限时触发 —— 距 130℃ 不足 8℃ 时才启用（加水短期会更升温）

  且仿真中给料量对 T3 无影响（过程模型只有 水率→T3），
  故这些动作的降温效果在本次工作中未被验证。""")

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump({"rows": rows, "charts": charts}, f, ensure_ascii=False)
    print("\n已保存: %s" % OUT)


if __name__ == "__main__":
    main()
