# -*- coding: utf-8 -*-
"""生成偏低班次（10-16 00:04）的 AB 对比 HTML：验证减水方向。"""
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
from ab_worst import run_shift, G_OLD, response_fast, _ffill   # noqa: E402

OUT = os.path.join(BASE, ".cache", "low_ab.json")
S0, E0 = 4690, 5110


def main():
    import time
    wt = data_loader.build_wide(verbose=False, use_cache=False)
    R = wt.series(Tag.RATIO_SD)
    T3 = np.nanmean([wt.series(t) for t in Tag.TEMP[2]], axis=0)
    label = time.strftime("%m-%d %H:%M", time.localtime(wt.grid[S0]))

    r = run_shift(wt, S0, E0 - 1, G_OLD, T3, R)

    # 恒定水率对照
    n = wt.grid.size
    u_act = np.where(np.isnan(R), 0.0, R).astype(np.float64)
    for i in range(1, n):
        if np.isnan(R[i]):
            u_act[i] = u_act[i - 1]
    base0 = T3[S0]
    resp0 = response_fast(u_act, G_OLD, S0)
    dd = np.full(E0 - S0 + 1, np.nan)
    for k, t in enumerate(range(S0, E0 + 1)):
        if np.isnan(T3[t]):
            continue
        dd[k] = T3[t] - base0 - (response_fast(u_act, G_OLD, t) - resp0)
    dd = _ffill(dd)

    def fixed_run(f):
        u = u_act.copy()
        t3 = np.full(E0 - S0 + 1, np.nan)
        for t in range(S0, E0 + 1):
            u[t] = f
            t3[t - S0] = base0 + (response_fast(u, G_OLD, t) - resp0) + dd[t - S0]
        return t3

    baselines = []
    for f in [580, 600, 620, 630, 640, 660]:
        t3 = fixed_run(f)
        baselines.append(dict(
            ratio=f, mean=round(float(t3.mean()), 1),
            in_band=round(float(100 * np.mean((t3 >= 100) & (t3 <= 130))), 1),
            below100=round(float(100 * np.mean(t3 < 100)), 1)))

    idx = list(range(0, len(r["ratio_sim"]), 5))
    payload = {
        "label": label,
        "dur": int(E0 - S0),
        "t": idx,
        "ratio_act": [None if np.isnan(r["ratio_act"][i]) else round(float(r["ratio_act"][i]), 0) for i in idx],
        "ratio_sim": [None if np.isnan(r["ratio_sim"][i]) else round(float(r["ratio_sim"][i]), 0) for i in idx],
        "t3_act": [None if np.isnan(r["t3_act"][i]) else round(float(r["t3_act"][i]), 1) for i in idx],
        "t3_sim": [None if np.isnan(r["t3_sim"][i]) else round(float(r["t3_sim"][i]), 1) for i in idx],
        "acts": [{"t": int(a[0]), "action": a[1], "ratio": round(float(a[2]), 0),
                  "reason": a[4]} for a in r["acts"] if a[1] != "保持"],
        "baselines": baselines,
        "summary": {
            "act_in": round(float(100 * np.mean(
                (r["t3_act"][~np.isnan(r["t3_act"])] >= 100) &
                (r["t3_act"][~np.isnan(r["t3_act"])] <= 130))), 1),
            "sim_in": round(float(100 * np.mean(
                (r["t3_sim"][~np.isnan(r["t3_sim"])] >= 100) &
                (r["t3_sim"][~np.isnan(r["t3_sim"])] <= 130))), 1),
            "act_below100": round(float(100 * np.mean(
                r["t3_act"][~np.isnan(r["t3_act"])] < 100)), 1),
            "sim_below100": round(float(100 * np.mean(
                r["t3_sim"][~np.isnan(r["t3_sim"])] < 100)), 1),
            "n_lower": int(sum(1 for a in r["acts"] if a[1] == "降低水率")),
            "n_raise": int(sum(1 for a in r["acts"] if a[1] == "提高水率")),
            "ratio_sim_min": round(float(np.nanmin(r["ratio_sim"])), 0),
            "ratio_sim_max": round(float(np.nanmax(r["ratio_sim"])), 0),
        },
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)
    print("已保存: %s" % OUT)
    print("减水 %d 次 / 加水 %d 次" % (payload["summary"]["n_lower"],
                                       payload["summary"]["n_raise"]))


if __name__ == "__main__":
    main()
