# -*- coding: utf-8 -*-
"""趋势预测控制器（现役温度控制算法，模仿人工操作逻辑）。

核心思想（来自人工操作经验）：
  · 不设守护带死区、不锁节拍——温度在哪都持续微调
  · 按「当前温度 + 变化斜率」预测未来温度，提前干预：
      预测温度 > 目标（正在超标或将要超标）→ 提水率
      预测温度 < 目标（温度在掉）→ 降水率
      贴着目标且平稳 → 不动
  · 双向连续调节：温度降回目标附近且趋势向下，水率跟着回调，
    绝不顶死在一个值上

控制律（增量式，每拍可动）：
  预测温度 pred = t3_now + slope × predict_min
  误差       err = pred − target
  步长       step = clip(kp × err, ±step_cap)     严重越线时 step_cap 放宽
  水率       u ← clip(u + step, u_lo, u_hi)

slope 由调用方提供（对温度历史窗口做线性拟合，℃/min）。
"""
from __future__ import annotations

import numpy as np


class TrendController:
    def __init__(self,
                 target: float = 118.0,       # T3 目标 ℃
                 kp: float = 2.0,             # L/t per ℃（预测误差比例系数）
                 predict_min: float = 15.0,   # 趋势前瞻（分钟）
                 dead: float = 3.0,           # 预测误差死区 ℃
                 dead_slope: float = 0.3,     # 斜率死区 ℃/min
                 step_max: float = 25.0,      # 单拍步长上限 L/t（温和，像人工）
                 step_fast: float = 60.0,     # 瞬时严重越线时步长上限 L/t
                 fast_hi: float = 135.0,      # 瞬时严重超温线 ℃
                 fast_lo: float = 95.0,       # 瞬时严重低温线 ℃
                 u_lo: float = 500.0,         # 水率下限（控制范围 500~690）
                 u_hi: float = 690.0,         # 水率上限
                 u_init: float = 630.0):
        self.target = target
        self.kp = kp
        self.predict_min = predict_min
        self.dead = dead
        self.dead_slope = dead_slope
        self.step_max = step_max
        self.step_fast = step_fast
        self.fast_hi = fast_hi
        self.fast_lo = fast_lo
        self.u_lo = u_lo
        self.u_hi = u_hi
        # 初始值必须先裁到控制范围：现场设定可能落在范围外（如 720 > 690），
        # 否则首拍直接输出越界值，且此后 u 一直贴在外面。
        self.u = float(np.clip(u_init, u_lo, u_hi))
        self.last_reason = ""
        self.steps = 0

    def reset(self, u_init: float = None):
        if u_init is not None:
            self.u = float(np.clip(u_init, self.u_lo, self.u_hi))
        self.steps = 0
        self.last_reason = ""

    def sync(self, u: float) -> None:
        """外部（电流规则）改动水率后同步内部状态。
        不做同步则电流规则降载到 580、内部仍停在 690，
        恢复完成后趋势一接管就把水率阶跃弹回去。"""
        self.u = float(np.clip(u, self.u_lo, self.u_hi))

    def update(self, t3_now: float, slope: float) -> float:
        """
        每控制周期调用一次。
        t3_now : 当前 T3（滑动中位或瞬时聚合）
        slope  : 最近窗口的 T3 线性拟合斜率 ℃/min
        返回新的水率设定。
        """
        pred = t3_now + slope * self.predict_min
        err = pred - self.target

        # 严重越线时放宽步长（快速压回），平时温和微调
        severe = (t3_now > self.fast_hi) or (t3_now < self.fast_lo)
        cap = self.step_fast if severe else self.step_max

        if abs(err) <= self.dead and abs(slope) < self.dead_slope:
            self.last_reason = ("趋势控制：T3=%.1f 斜率=%+.2f℃/min，预测 %.1f "
                                "贴目标 %.0f±%.0f，保持 %.0f" % (
                                    t3_now, slope, pred, self.target,
                                    self.dead, self.u))
            self.steps += 1
            return self.u

        delta = float(np.clip(self.kp * err, -cap, cap))
        new_u = float(np.clip(self.u + delta, self.u_lo, self.u_hi))
        direction = "提水率" if new_u > self.u else "降水率"
        severe_tag = "（严重越线，加大步长）" if severe else ""
        self.last_reason = ("趋势控制：T3=%.1f 斜率=%+.2f℃/min → 预测 %.1f "
                            "(目标 %.0f) → %s %+.0f → %.0f L/t%s" % (
                                t3_now, slope, pred, self.target,
                                direction, new_u - self.u, new_u, severe_tag))
        self.u = new_u
        self.steps += 1
        return self.u


def slope_linfit(series, tail: int = 15) -> float:
    """对温度序列（逐分钟，含 None/NaN）最近 tail 个点做线性拟合，返回 ℃/min。
    有效点 <5 时返回 0（信息不足不预判）。"""
    vals = [v for v in series[-tail:] if v is not None and v == v]
    if len(vals) < 5:
        return 0.0
    ks = np.arange(len(vals), dtype=float)
    return float(np.polyfit(ks, vals, 1)[0])
