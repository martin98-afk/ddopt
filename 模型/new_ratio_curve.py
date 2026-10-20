# -*- coding: utf-8 -*-
"""
新数据上：模型水率 vs 人工水率 逐分钟对比。

与 validate_new.py 的区别：本脚本逐分钟记录模型输出的水率设定值，
与历史实际水率并列，供画曲线用。

隔离要求：只用今天这一个 zip，响应核用旧模型写死的 G_OLD，不重新辨识。
"""
import os
import sys
import time

import numpy as np

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

from validate_new import load_single_zip, build_minute_table, G_OLD  # noqa: E402
from config import Tag, Config                                       # noqa: E402
from signal_conditioning import SignalConditioner                    # noqa: E402
from controller import XshController, Phase, Action                  # noqa: E402

OUT = os.path.join(BASE, ".cache", "new_ratio_cmp.json")


def main():
    DATA_DIR = os.path.join(os.path.dirname(BASE), "脱硫脱硝消石灰制备数据")
    zips = sorted(f for f in os.listdir(DATA_DIR) if f.endswith(".zip"))
    zp = os.path.join(DATA_DIR, zips[-1])
    print("只用: %s" % os.path.basename(zp))

    wt = build_minute_table(load_single_zip(zp))
    n = wt.grid.size
    print("%d 分钟，%s ~ %s" % (
        n,
        time.strftime("%m-%d %H:%M", time.localtime(wt.grid[0])),
        time.strftime("%m-%d %H:%M", time.localtime(wt.grid[-1]))))

    sc = SignalConditioner(wt, Config())
    cfg = Config()
    ctrl = XshController(sc, cfg)

    ratio_sim = np.full(n, np.nan)
    ratio_act = wt.series(Tag.RATIO_SD).copy()
    lime_sim = np.full(n, np.nan)
    T3 = np.nanmean([wt.series(t) for t in Tag.TEMP[2]], axis=0)
    perm = sc.production_mask()

    for i in range(n):
        out = ctrl.step(i)
        if out.phase == Phase.IDLE:
            continue
        ratio_sim[i] = out.ratio_set
        lime_sim[i] = out.lime_set

    # 只在生产段有值
    ratio_sim[~perm] = np.nan
    lime_sim[~perm] = np.nan

    # 分段
    d = np.diff(perm.astype(np.int8))
    starts = list(np.where(d == 1)[0] + 1)
    ends = list(np.where(d == -1)[0] + 1)
    if perm[0]:
        starts.insert(0, 0)
    if perm[-1]:
        ends.append(n)
    segs = [(s, e) for s, e in zip(starts, ends) if e - s >= 30]

    print("\n生产班次 %d 段" % len(segs))
    for s, e in segs:
        ra = ratio_act[s:e]
        rs = ratio_sim[s:e]
        ok = ~np.isnan(rs)
        print("  %s ~ %s  %4d min" % (
            time.strftime("%m-%d %H:%M", time.localtime(wt.grid[s])),
            time.strftime("%m-%d %H:%M", time.localtime(wt.grid[e - 1])), e - s))
        if ok.sum():
            print("     人工水率: %.0f~%.0f (std %.1f, 变动 %d 次)" % (
                np.nanmin(ra), np.nanmax(ra), np.nanstd(ra),
                int(np.sum(np.abs(np.diff(ra[ok])) > 0.5))))
            print("     模型水率: %.0f~%.0f (std %.1f, 变动 %d 次)" % (
                np.nanmin(rs), np.nanmax(rs), np.nanstd(rs),
                int(np.sum(np.abs(np.diff(rs[ok])) > 0.5))))

    # 导出（降采样到 5 分钟）
    idx = list(range(0, n, 5))
    payload = {
        "t0": int(wt.grid[0]),
        "labels": [time.strftime("%m-%d %H:%M", time.localtime(wt.grid[i]))
                   for i in idx],
        "t": idx,
        "ratio_act": [None if np.isnan(ratio_act[i]) else round(float(ratio_act[i]), 0)
                      for i in idx],
        "ratio_sim": [None if np.isnan(ratio_sim[i]) else round(float(ratio_sim[i]), 0)
                      for i in idx],
        "t3": [None if np.isnan(T3[i]) else round(float(T3[i]), 1) for i in idx],
        "segs": [{"label": time.strftime("%m-%d %H:%M",
                                         time.localtime(wt.grid[s])),
                  "s": int(s), "e": int(e)} for s, e in segs],
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    import json
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)
    print("\n已保存: %s" % OUT)

    # 汇总
    print("\n" + "=" * 78)
    print("汇总（全部生产段）")
    print("=" * 78)
    ra = ratio_act[perm & ~np.isnan(ratio_act)]
    rs = ratio_sim[perm & ~np.isnan(ratio_sim)]
    print("  人工水率: 均值 %.1f  std %.2f  范围 %.0f~%.0f" % (
        ra.mean(), ra.std(), ra.min(), ra.max()))
    print("  模型水率: 均值 %.1f  std %.2f  范围 %.0f~%.0f" % (
        rs.mean(), rs.std(), rs.min(), rs.max()))
    print("  人工变动次数: %d" % int(np.sum(np.abs(np.diff(ra)) > 0.5)))
    print("  模型变动次数: %d" % int(np.sum(np.abs(np.diff(rs)) > 0.5)))


if __name__ == "__main__":
    main()
