# -*- coding: utf-8 -*-
"""与现役斜率规则做同数据对照，确认预测 PI 没跑偏。

口径说明（重要）：
  离线数据是分钟粒度，模型输出不写回数据，所以这里是**开环建议**对照 ——
  比的是"面对同样的温度历史，两套算法给出的水率建议有何不同"。
  真正的效果对比需要闭环仿真或现场 A/B。

用途：
  1. 确认装配正确（不崩、不越界）
  2. 看两套算法的动作差异（幅度、频率、方向一致性）
  3. 标定后重跑，确认新参数下预测 PI 的建议更合理

运行：python 对比验证.py
"""
from __future__ import annotations

import os
import sys

import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
_MODEL_DIR = os.path.join(os.path.dirname(_HERE), "模型")
for _p in (_HERE, _MODEL_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

os.environ.setdefault(
    "XSH_DATA_DIR",
    r"D:\work\梅钢脱硫脱硝\data\脱硫脱硝消石灰制备数据")

from config import Tag                                       # noqa: E402
from controller import XshController, Phase                  # noqa: E402
from signal_conditioning import SignalConditioner            # noqa: E402
from data_loader import build_wide                           # noqa: E402

import 标定参数 as P                                           # noqa: E402
from controller_ppi import attach_predictive_pi, make_config  # noqa: E402


def prod_indices(wt):
    perm = wt.series(Tag.PERMIT)
    lime = wt.series(Tag.LIME)
    prod = (perm > 0.5) & (lime > 0.1)
    return np.where(np.where(np.isnan(perm) | np.isnan(lime), False, prod))[0]


def run(kind: str, wt, idxs):
    """kind: '斜率规则' 或 '预测PI'"""
    cfg = make_config()
    sc = SignalConditioner(wt, cfg)
    ctrl = XshController(sc, cfg)
    if kind == "预测PI":
        attach_predictive_pi(ctrl, cfg)
    outs = [ctrl.step(int(i)) for i in idxs]
    return np.array([o.ratio_set for o in outs], dtype=float), outs


def main():
    print("=" * 88)
    print("现役斜率规则 vs 预测 PI —— 同数据开环建议对照")
    print("口径：输出不写回数据，比的是面对同一温度历史的建议差异")
    print("=" * 88)
    if not P.CALIBRATED:
        print()
        print("[提示] 标定参数.py 尚未标定，预测PI 用的是占位参数，")
        print("       这里的数字只用于验证装配与量纲，不代表真实效果。")

    wt = build_wide(verbose=False)
    idxs = prod_indices(wt)
    print("\n生产 %d 分钟" % idxs.size)

    ra, oa = run("斜率规则", wt, idxs)
    rb, ob = run("预测PI", wt, idxs)

    print()
    print("%-16s %10s %10s %10s %10s %10s" % (
        "算法", "水率均值", "水率std", "行程", "顶690", "触500"))
    for nm, r in (("斜率规则", ra), ("预测PI", rb)):
        print("%-16s %10.1f %10.1f %10.0f %9.0f%% %9.0f%%" % (
            nm, r.mean(), r.std(), np.abs(np.diff(r)).sum(),
            100 * np.mean(r >= P.RATIO_HI - 1e-6),
            100 * np.mean(r <= P.RATIO_LO + 1e-6)))

    # ---- 方向一致性：两套算法在同一时刻给出的调整方向 ----
    da = np.diff(ra)
    db = np.diff(rb)
    same = np.sign(da) == np.sign(db)
    both_move = (np.abs(da) > 1e-9) & (np.abs(db) > 1e-9)
    if both_move.any():
        agree = 100.0 * np.mean(same[both_move])
        print("\n两套算法同时动作的拍数：%d / %d" % (
            int(both_move.sum()), len(da)))
        print("  其中方向一致：%.1f%%" % agree)
        print("  方向相反：%.1f%%" % (100.0 - agree))

    # ---- 动作幅度分布 ----
    print("\n单拍动作幅度 |Δu| 分位：")
    print("  %-12s %8s %8s %8s %8s" % ("算法", "P50", "P90", "P99", "max"))
    for nm, r in (("斜率规则", ra), ("预测PI", rb)):
        d = np.abs(np.diff(r))
        print("  %-12s %8.1f %8.1f %8.1f %8.1f" % (
            nm, np.percentile(d, 50), np.percentile(d, 90),
            np.percentile(d, 99), d.max()))

    # ---- 分阶段 ----
    print("\n启动阶段 vs 稳态阶段的建议水率：")
    for nm, outs in (("斜率规则", oa), ("预测PI", ob)):
        su = [o.ratio_set for o in outs if o.phase == Phase.STARTUP]
        st = [o.ratio_set for o in outs if o.phase == Phase.STEADY]
        if su and st:
            print("  %-12s 启动 %6.1f (%d 拍)   稳态 %6.1f (%d 拍)" % (
                nm, np.mean(su), len(su), np.mean(st), len(st)))

    print()
    print("=" * 88)
    print("结论读法：")
    print("  · 预测PI 的行程与幅度应显著小于斜率规则（因为它按增益反解，")
    print("    不是每拍固定步长）；若反而更大，说明参数或装配有问题")
    print("  · 方向一致性低于 70% 需要排查（两套算法对温度趋势的判断相左）")
    print("  · 标定完成后重跑本脚本，看预测PI 的稳态均值是否更接近人工值")
    print("=" * 88)


if __name__ == "__main__":
    main()
