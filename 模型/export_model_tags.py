# -*- coding: utf-8 -*-
"""
导出模型输出的三个设定值，作为新测点供「控制趋势分析」页面叠加显示。

输出三个序列，长度与宽表一致（分钟级），非生产段为 None：
  MODEL_RATIO  模型水率设定     L/t
  MODEL_LIME   模型生石灰流量   t/h
  MODEL_WATER  模型水流量设定   L/h  = 水率 × 给料量

关键修正：早期版本用 5 分钟降采样统计，把波动平均掉了，
导致算出的 std 只有真实值的 1/7。这里一律用分钟级原始值。
"""
import json
import os

import numpy as np

from ab_test import identify_kernel, run_shift
from data_loader import build_wide
from config import Tag, Config, ControlParams

BASE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(BASE, ".cache", "model_tags.json")


def main():
    wt = build_wide(verbose=False)
    n = wt.grid.size
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
    print("响应核辨识：%d 个事件" % n_ev)

    ratio = np.full(n, np.nan)
    lime = np.full(n, np.nan)
    notes = []

    for s, e in segs:
        s0 = s + 120 if e - s > 150 else s + 60
        if e - s0 < 90:
            continue
        cfg = Config()
        cfg.set_curr1_high(18.0)
        r = run_shift(wt, cfg, s0, e - 1, G, T3, R)
        m = r["ratio_sim"].size
        ratio[s0:s0 + m] = r["ratio_sim"]
        lime[s0:s0 + m] = r["lime_sim"]
        notes.append((s0, e, int(np.nansum(~np.isnan(r["lime_sim"])))))

    water = ratio * lime

    def dump(v):
        return [None if np.isnan(x) else round(float(x), 2) for x in v]

    payload = {
        "generated": __import__("time").strftime("%Y-%m-%d %H:%M:%S"),
        "grid": [int(x) for x in wt.grid],
        "tags": {
            "MODEL_RATIO": dump(ratio),
            "MODEL_LIME": dump(lime),
            "MODEL_WATER": dump(water),
        },
        "meta": {
            "MODEL_RATIO": {"desc": "模型水率设定", "unit": "L/t"},
            "MODEL_LIME": {"desc": "模型生石灰流量设定", "unit": "t/h"},
            "MODEL_WATER": {"desc": "模型水流量设定", "unit": "L/h"},
        },
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)

    # 统计
    ok = ~np.isnan(ratio)
    print("\n导出 %d 个分钟点，其中有效 %d (%.1f%%)" % (
        n, ok.sum(), 100 * ok.sum() / n))
    for k, v in [("水率", ratio), ("给料量", lime), ("水流量", water)]:
        x = v[ok]
        print("  %-8s 均值 %8.2f  std %7.2f  范围 %8.2f ~ %8.2f" % (
            k, x.mean(), x.std(), x.min(), x.max()))
    print("\n已保存: %s (%.1f KB)" % (OUT, os.path.getsize(OUT) / 1024))


if __name__ == "__main__":
    main()
