# -*- coding: utf-8 -*-
"""
回归验证：ratio_band 45 -> 60 是否破坏旧数据（10-12~10-19）上的已标定行为。

旧数据在 D:/work/脱硫脱硝/data/脱硫脱硝消石灰制备数据/，
通过 DATA_DIR 环境变量指给 data_loader，不动新数据目录。
"""
import os
import sys
import time

import numpy as np

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

OLD_DATA = r"D:/work/脱硫脱硝/data/脱硫脱硝消石灰制备数据"
os.environ["XSH_DATA_DIR"] = OLD_DATA

# 强制 data_loader 用旧目录
import data_loader                                        # noqa: E402
data_loader.DATA_DIR = OLD_DATA
data_loader.CACHE_DIR = os.path.join(BASE, ".cache_old")

from config import Tag, Config                             # noqa: E402
from signal_conditioning import SignalConditioner          # noqa: E402
from controller import XshController, Phase, Action        # noqa: E402


def run(cfg, wt):
    sc = SignalConditioner(wt, cfg)
    ctrl = XshController(sc, cfg)
    from collections import Counter
    acts = Counter()
    viol = {"水率": 0, "给料": 0, "电流": 0, "T3": 0}
    t3_act, t3_sim = [], []
    T3 = np.nanmean([wt.series(t) for t in Tag.TEMP[2]], axis=0)
    for i in range(wt.grid.size):
        out = ctrl.step(i)
        if out.phase == Phase.IDLE:
            continue
        acts[out.action.value] += 1
        if out.ratio_set < cfg.safety.ratio_safe_min - 1 or \
           out.ratio_set > cfg.safety.ratio_safe_max + 1:
            viol["水率"] += 1
        if out.action != Action.STOP_FEED and (
                out.lime_set < cfg.safety.lime_min - 1e-6 or
                out.lime_set > cfg.safety.lime_max + 1e-6):
            viol["给料"] += 1
        if not np.isnan(out.curr1) and out.curr1 >= cfg.safety.curr1_trip:
            viol["电流"] += 1
        if not np.isnan(out.temp3) and out.temp3 > cfg.safety.temp_hard_high:
            viol["T3"] += 1
        if out.phase == Phase.STEADY and not np.isnan(out.temp3):
            t3_act.append(T3[i])
            t3_sim.append(out.temp3)
    return acts, viol, t3_act, t3_sim


def main():
    print("=" * 92)
    print("回归验证：ratio_band 45 -> 60 对旧数据已标定行为的影响")
    print("=" * 92)
    print("旧数据目录: %s" % OLD_DATA)
    wt = data_loader.build_wide(verbose=False, use_cache=False)
    print("载入 %d 测点，%d 分钟（%s ~ %s）" % (
        len(wt.cols), wt.grid.size,
        time.strftime("%m-%d %H:%M", time.localtime(wt.grid[0])),
        time.strftime("%m-%d %H:%M", time.localtime(wt.grid[-1]))))

    perm = (wt.series(Tag.PERMIT) > 0.5) & (wt.series(Tag.LIME) > 0.1)
    R = wt.series(Tag.RATIO_SD)
    rp = R[perm]
    print("生产分钟 %d，水率范围 %.0f ~ %.0f" % (perm.sum(), np.nanmin(rp), np.nanmax(rp)))

    results = {}
    for label, band in [("band=60(新)", 60.0), ("band=45(旧)", 45.0)]:
        cfg = Config()
        cfg.control.ratio_band = band
        acts, viol, ta, ts = run(cfg, wt)
        results[label] = (acts, viol, ta, ts)
        print("\n【%s】" % label)
        print("  动作: %s" % dict(acts))
        print("  违规: %s" % viol)
        if ta:
            a = np.array(ta)
            b = np.array(ts)
            print("  T3 实际人工 合格率 %.1f%%   模型接管 合格率 %.1f%%" % (
                100 * np.mean((a >= 100) & (a <= 130)),
                100 * np.mean((b >= 100) & (b <= 130))))

    print()
    print("=" * 92)
    print("差异汇总")
    print("=" * 92)
    a_old, v_old, _, _ = results["band=45(旧)"]
    a_new, v_new, _, _ = results["band=60(新)"]
    print("%-14s %8s %8s %8s" % ("动作", "旧", "新", "变化"))
    for k in sorted(set(a_old) | set(a_new), key=lambda x: -a_new.get(x, 0)):
        d = a_new.get(k, 0) - a_old.get(k, 0)
        print("%-14s %8d %8d %+8d" % (k, a_old.get(k, 0), a_new.get(k, 0), d))
    print()
    for k in v_old:
        print("  违规[%s]: 旧 %d -> 新 %d" % (k, v_old[k], v_new[k]))

    print()
    print("=" * 92)
    print("结论")
    print("=" * 92)
    changed = {k: a_new.get(k, 0) - a_old.get(k, 0) for k in set(a_old) | set(a_new)}
    material = {k: v for k, v in changed.items() if abs(v) >= 3}
    if not material:
        print("  无实质性变化，改动安全。")
    else:
        print("  有变化: %s" % material)
    if all(v == 0 for v in v_new.values()):
        print("  安全约束仍全部合规。")


if __name__ == "__main__":
    main()
