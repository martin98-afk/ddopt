# -*- coding: utf-8 -*-
"""
核查：模型水率与人工水率「几乎一样」，到底是模型调得好，还是模型在复读？

核心怀疑：
  控制器每步用 sc.wt.series(RATIO_SD)[i] 作为 ratio_set 初值，
  而这条正是人工历史设定值。只要模型不改，输出就等于人工。
  => 曲线重合是结构性必然，不证明任何控制能力。

要回答三个问题：
  1. 模型与人工不一致的时刻有哪些？改了什么？
  2. 那些不一致，是模型主动决策，还是被 base_lime/别的东西带偏？
  3. 若把模型换成「永远不动」，结果会差多少？（空白对照）
"""
import os
import sys

import numpy as np

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
from validate_new import load_single_zip, build_minute_table   # noqa: E402
from config import Tag, Config                                  # noqa: E402
from signal_conditioning import SignalConditioner               # noqa: E402
from controller import XshController, Phase, Action             # noqa: E402


class NeverMoveController(XshController):
    """空白对照：永远保持人工设定值，什么都不做"""

    def _steady_logic(self, i, out, t3, curr1, ratio_act):
        out.action = Action.HOLD
        out.reason = "空白对照：保持人工设定值"
        return out

    def _startup_logic(self, i, out, t3, curr1, elapsed):
        out.action = Action.HOLD
        return out


def run(ctrl_cls, wt):
    sc = SignalConditioner(wt, Config())
    cfg = Config()
    ctrl = ctrl_cls(sc, cfg)
    n = wt.grid.size
    ratio = np.full(n, np.nan)
    acts = {}
    for i in range(n):
        out = ctrl.step(i)
        ratio[i] = out.ratio_set
        acts[out.action.value] = acts.get(out.action.value, 0) + 1
    return ratio, acts


def main():
    DATA_DIR = os.path.join(os.path.dirname(BASE), "脱硫脱硝消石灰制备数据")
    zips = sorted(f for f in os.listdir(DATA_DIR) if f.endswith(".zip"))
    wt = build_minute_table(load_single_zip(os.path.join(DATA_DIR, zips[-1])))
    n = wt.grid.size
    R = wt.series(Tag.RATIO_SD)
    perm = (wt.series(Tag.PERMIT) > 0.5) & (wt.series(Tag.LIME) > 0.1)

    ratio_m, acts_m = run(XshController, wt)
    ratio_n, acts_n = run(NeverMoveController, wt)

    both = perm & ~np.isnan(ratio_m) & ~np.isnan(ratio_n)
    diff = np.abs(ratio_m - ratio_n)
    moved = both & (diff > 0.5)

    print("=" * 84)
    print("1. 模型 vs 空白对照（永远不动）")
    print("=" * 84)
    print("  模型接管分钟: %d" % both.sum())
    print("  其中水率被改动(>0.5 L/t)的分钟: %d (%.1f%%)" % (
        moved.sum(), 100 * moved.sum() / both.sum()))
    print("  即 %.1f%% 的时间，模型输出 == 人工设定值（复读）" % (
        100 * (both.sum() - moved.sum()) / both.sum()))

    print()
    print("=" * 84)
    print("2. 模型改动都发生在什么时候")
    print("=" * 84)
    idx = np.where(moved)[0]
    if idx.size:
        T3 = np.nanmean([wt.series(t) for t in Tag.TEMP[2]], axis=0)
        print("  %-16s %8s %8s %8s" % ("时刻", "人工", "模型", "T3"))
        for i in idx[:25]:
            import time
            print("  %-16s %8.0f %8.0f %8.1f" % (
                time.strftime("%m-%d %H:%M", time.localtime(wt.grid[i])),
                R[i], ratio_m[i], T3[i]))
        if idx.size > 25:
            print("  ... 共 %d 个" % idx.size)
        print()
        d = diff[moved]
        print("  改动幅度: 中位 %.1f  最大 %.1f  L/t" % (np.median(d), d.max()))

    print()
    print("=" * 84)
    print("3. 动作构成对比")
    print("=" * 84)
    print("  模型   : %s" % acts_m)
    print("  空白对照: %s" % acts_n)

    print()
    print("=" * 84)
    print("结论")
    print("=" * 84)
    pct = 100 * (both.sum() - moved.sum()) / both.sum() if both.sum() else 0
    print("""
  模型有 %.1f%% 的时间在复读人工设定值，只有 %.1f%% 的时间真正做了改动。
  「两条曲线几乎一样」是结构性必然，不能作为模型有效的证据。
""" % (pct, 100 - pct))


if __name__ == "__main__":
    main()
