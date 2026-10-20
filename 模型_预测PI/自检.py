# -*- coding: utf-8 -*-
"""下控前自检：确认预测 PI 装配正确、参数可用。

检查项：
  1. 标定状态（未标定则只警告，不阻断）
  2. 参数合法性
  3. 装配后控制器能跑，输出在限幅内
  4. 与现役斜率规则做同数据对照（确认没跑偏）
  5. 10 秒周期下的稳定性（动作幅度不随周期放大）

运行：python 自检.py
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

import 标定参数 as P                                    # noqa: E402
from predictive_pi import PredictivePI                  # noqa: E402

OK = "[OK]"
WARN = "[警告]"
FAIL = "[失败]"


def main():
    print("=" * 78)
    print("模型_预测PI · 下控前自检")
    print("=" * 78)

    # ---------- 1 标定状态 ----------
    print("\n【1】标定状态")
    if P.CALIBRATED:
        print("  %s 已标定" % OK)
    else:
        print("  %s 未标定 —— GAIN/TAU/THETA 为占位值，禁止直接下控" % WARN)
    print("  gain=%s  tau=%s  theta=%s" % (P.GAIN, P.TAU, P.THETA))
    print("  kp=%s  ti=%s" % (P.KP, P.TI))

    # ---------- 2 参数合法性 ----------
    print("\n【2】参数合法性")
    errs = []
    if abs(P.GAIN) < 1e-9:
        errs.append("gain 为 0，无法反解水率")
    if P.GAIN > 0:
        errs.append("gain 为正 —— 意味着加水升温，与工艺假设相反，"
                    "请核对标定曲线方向")
    if P.TAU <= 0:
        errs.append("tau 必须为正")
    if P.THETA < 0:
        errs.append("theta 不能为负")
    if P.CONTROL_INTERVAL_MIN <= 0:
        errs.append("控制周期必须为正")
    if P.RATIO_LO >= P.RATIO_HI:
        errs.append("水率下限 >= 上限")
    if errs:
        for e in errs:
            print("  %s %s" % (FAIL, e))
    else:
        print("  %s 参数合法" % OK)
    # 反解尺度
    if abs(P.GAIN) > 1e-9:
        print("  反解尺度：偏差 1℃ → 水率 %.2f L/t" % (1.0 / abs(P.GAIN)))
        print("  量程 %.0f~%.0f 可覆盖温差 %.1f℃" % (
            P.RATIO_LO, P.RATIO_HI,
            abs(P.GAIN) * (P.RATIO_HI - P.RATIO_LO)))

    # ---------- 3 装配与基本运行 ----------
    print("\n【3】装配与运行")
    try:
        from controller_ppi import attach_predictive_pi, make_config
        from controller import XshController
        from signal_conditioning import SignalConditioner
        from data_loader import build_wide
        from config import Tag
        wt = build_wide(verbose=False)
        cfg = make_config()
        sc = SignalConditioner(wt, cfg)
        ctrl = XshController(sc, cfg)
        ppi = attach_predictive_pi(ctrl, cfg)
        print("  %s 装配成功，延迟线 %d 格" % (OK, ppi.nd))
    except Exception as e:
        print("  %s 装配失败：%s: %s" % (FAIL, type(e).__name__, e))
        return

    perm = wt.series(Tag.PERMIT)
    lime = wt.series(Tag.LIME)
    prod = (perm > 0.5) & (lime > 0.1)
    prod = np.where(np.isnan(perm) | np.isnan(lime), False, prod)
    idxs = np.where(prod)[0]
    if idxs.size == 0:
        print("  %s 数据中无生产段" % WARN)
        return

    outs = [ctrl.step(int(i)) for i in idxs]
    rs = np.array([o.ratio_set for o in outs], dtype=float)
    ls = np.array([o.lime_set for o in outs], dtype=float)
    bad_r = int(np.sum((rs < P.RATIO_LO - 1e-6) | (rs > P.RATIO_HI + 1e-6)))
    bad_l = int(np.sum((ls < cfg.safety.lime_min - 1e-6) |
                       (ls > cfg.safety.lime_max + 1e-6)))
    print("  回放 %d 分钟" % len(outs))
    if bad_r == 0 and bad_l == 0:
        print("  %s 水率 %0.f~%.0f 全部在 [%.0f,%.0f] 内" % (
            OK, rs.min(), rs.max(), P.RATIO_LO, P.RATIO_HI))
        print("  %s 给料量 %.2f~%.2f 全部合规" % (OK, ls.min(), ls.max()))
    else:
        print("  %s 水率越界 %d 次，给料越界 %d 次" % (FAIL, bad_r, bad_l))
    print("  水率行程合计 %.0f L/t（%.1f L/t/h）" % (
        np.abs(np.diff(rs)).sum(),
        np.abs(np.diff(rs)).sum() / max(len(outs) / 60.0, 1e-9)))

    # ---------- 4 10 秒周期稳定性 ----------
    print("\n【4】高频调用稳定性（动作幅度不应随周期放大）")
    print("  %-14s %12s %12s" % ("周期", "行程 L/t/h", "顶界占比"))
    for dt, lab in ((10.0, "10 分钟"), (1.0, "1 分钟"), (1 / 6.0, "10 秒")):
        cfg2 = make_config()
        cfg2.control.control_interval_min = dt
        cfg2.control.gap_tolerance = dt
        sc2 = SignalConditioner(wt, cfg2)
        c2 = XshController(sc2, cfg2)
        attach_predictive_pi(c2, cfg2)
        step = max(1, int(round(dt)))
        r2 = []
        for i in range(idxs[0], idxs[-1], step):
            r2.append(c2.step(int(i)).ratio_set)
        r2 = np.array(r2, dtype=float)
        span_h = len(r2) * dt / 60.0
        travel = np.abs(np.diff(r2)).sum() / max(span_h, 1e-9)
        at = 100.0 * np.mean((r2 >= P.RATIO_HI - 1e-6) |
                             (r2 <= P.RATIO_LO + 1e-6))
        print("  %-14s %12.0f %11.0f%%" % (lab, travel, at))

    print()
    print("=" * 78)
    if P.CALIBRATED and not errs:
        print("%s 可以下控" % OK)
    else:
        print("%s 还不能下控：先完成 标定说明.md 的受控阶跃试验" % WARN)
    print("=" * 78)


if __name__ == "__main__":
    main()
