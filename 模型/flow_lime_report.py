# -*- coding: utf-8 -*-
"""
水流量 / 生石灰流量 控制曲线：模型 vs 人工。

从 A/B 仿真取模型输出，与历史实际值逐点对照，
产出 .cache/flow_lime_cmp.json 供 build_flow_report.py 渲染。

两个重要口径约定：
  1. 统计用分钟级原始值，画图才用 5 分钟降采样
  2. std 分「单班次内」与「跨班次合并」两种口径，本脚本输出前者。
     后者会大得多（含班次间均值差异），两者不可混用。
"""
import json
import os
import time

import numpy as np

from ab_test import identify_kernel, run_shift
from data_loader import build_wide
from config import Tag, Config

BASE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(BASE, ".cache", "flow_lime_cmp.json")


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
    print("响应核：%d 个事件" % n_ev)

    rows, charts = [], []
    for s, e in segs:
        s0 = s + 120 if e - s > 150 else s + 60
        if e - s0 < 90:
            continue
        cfg = Config()
        cfg.set_curr1_high(18.0)
        r = run_shift(wt, cfg, s0, e - 1, G, T3, R)
        label = time.strftime("%m-%d %H:%M", time.localtime(wt.grid[s0]))

        rs = r["ratio_sim"]
        ls = r["lime_sim"]
        ws = rs * ls                        # 模型水流量（推算）
        wa = wt.series(Tag.WATER)[s0:e]     # 人工水流量（实测）
        la = r["lime_act"]

        idx = list(range(0, len(rs), 5))

        def ds(arr):
            return [None if (i >= len(arr) or np.isnan(arr[i]))
                    else round(float(arr[i]), 2) for i in idx]

        charts.append(dict(
            label=label, t=idx,
            w_act=ds(wa), w_sim=ds(ws),
            l_act=ds(la), l_sim=ds(ls),
        ))

        def st(a):
            """单班次内的分钟级统计（不用降采样序列，否则波动被平均掉）"""
            x = np.asarray(a, dtype=np.float64)
            x = x[~np.isnan(x)]
            if x.size == 0:
                return dict(mean=np.nan, std=np.nan, min_=np.nan, max_=np.nan)
            return dict(mean=float(x.mean()), std=float(x.std()),
                        min_=float(x.min()), max_=float(x.max()))

        rows.append(dict(label=label, dur=int(e - s0),
                         w_act=st(wa), w_sim=st(ws),
                         l_act=st(la), l_sim=st(ls)))

    print()
    print("=" * 96)
    print("逐班次（std 为单班次内口径）")
    print("=" * 96)
    print("%-16s %5s | %8s %8s | %8s %8s" % (
        "班次", "时长", "水std(人)", "水std(模)", "料std(人)", "料std(模)"))
    for r in rows:
        print("%-16s %5d | %8.0f %8.0f | %8.2f %8.2f" % (
            r["label"], r["dur"],
            r["w_act"]["std"], r["w_sim"]["std"],
            r["l_act"]["std"], r["l_sim"]["std"]))

    print()
    print("汇总（单班次内 std 的平均）:")
    print("  水流量     人工 %.0f   模型 %.0f" % (
        np.mean([r["w_act"]["std"] for r in rows]),
        np.mean([r["w_sim"]["std"] for r in rows])))
    print("  生石灰流量 人工 %.2f   模型 %.2f" % (
        np.mean([r["l_act"]["std"] for r in rows]),
        np.mean([r["l_sim"]["std"] for r in rows])))
    print("  水流量均值 人工 %.0f   模型 %.0f" % (
        np.mean([r["w_act"]["mean"] for r in rows]),
        np.mean([r["w_sim"]["mean"] for r in rows])))
    print("  给料量均值 人工 %.2f   模型 %.2f" % (
        np.mean([r["l_act"]["mean"] for r in rows]),
        np.mean([r["l_sim"]["mean"] for r in rows])))

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump({"rows": rows, "charts": charts}, f, ensure_ascii=False)
    print("\n已保存: %s (%.1f KB)" % (OUT, os.path.getsize(OUT) / 1024))


if __name__ == "__main__":
    main()
