# -*- coding: utf-8 -*-
"""预测 PI 控制器（Hägglund 1992 / 与 Smith 预估器等价）。

接口与 模型/trend.py 的 TrendController **完全一致**（reset/sync/update），
因此可以直接替换 controller.py 里的 self._trend，其余逻辑一行不用改。

偏差定义：e = y_pred − sp（温度偏高 → e>0 → 加水 → Δu>0）
这个符号必须与对象增益 KAING<0（加水降温）配合，改动时注意。
"""
from __future__ import annotations

from collections import deque
from typing import Optional

import numpy as np


class PredictivePI:
    """死时间补偿 PI 控制器。

    对象：G(s) = K/(τs+1) · e^(−θs)
      · x    一阶滤波状态，代表"无死时间模型"的输出偏差
      · buf  y0 的延迟线，长度 θ/dt，队首即"θ 分钟前的模型输出"

    每拍：
      y0      = K·x                无死时间模型输出
      y0_del  = buf[0]             θ 分钟前的模型输出（含死时间）
      d_hat   = y_meas − y0_del    扰动估计（含模型失配）
      y_pred  = y0 + d_hat         去掉死时间的预测
      e       = y_pred − sp
      Δu      = Kp·(e_k−e_{k−1}) + Kp·dt/Ti·e_k
    """

    def __init__(self,
                 target: float = 118.0,
                 kp: float = 3.0,          # L/t per ℃
                 ti: float = 20.0,         # min
                 gain: float = -0.151,     # ℃/(L/t)，负号=加水降温
                 tau: float = 60.0,        # min
                 theta: float = 30.0,      # min
                 dt_min: float = 10.0,     # 控制周期（分钟）
                 u_lo: float = 500.0,
                 u_hi: float = 690.0,
                 u_init: float = 600.0,
                 step_max: float = 25.0):
        if abs(gain) < 1e-9:
            raise ValueError("对象增益 gain 不能为 0，无法反解水率")
        if tau <= 0:
            raise ValueError("时间常数 tau 必须为正")
        if theta < 0:
            raise ValueError("纯滞后 theta 不能为负")
        if dt_min <= 0:
            raise ValueError("控制周期 dt_min 必须为正")

        self.target = float(target)
        self.kp = float(kp)
        self.ti = float(ti)
        self.gain = float(gain)
        self.tau = float(tau)
        self.theta = float(theta)
        self.dt_min = float(dt_min)
        self.u_lo = float(u_lo)
        self.u_hi = float(u_hi)
        self.step_max = float(step_max)

        self._build_delay_line()
        self.u = float(np.clip(u_init, u_lo, u_hi))
        self.u0 = float(self.u)         # 模型基准（偏差从此起算）
        self.y_base = float(target)     # 温度的绝对基准
        self.x = 0.0                    # 一阶滤波状态（相对 u0 的偏差）
        self.prev_e: Optional[float] = None
        self.last_reason = ""
        self.steps = 0

    # ------------------------------------------------------------ 延迟线
    def _build_delay_line(self) -> None:
        """延迟线长度 = θ/dt（格）。θ=0 时退化为 1 格。"""
        n = max(1, int(round(self.theta / self.dt_min)))
        self.nd = n
        self.buf = deque([0.0] * n, maxlen=n)

    def set_dt(self, dt_min: float) -> None:
        """控制周期变化时重建延迟线并清空状态。

        周期变了，延迟线格数就变了；旧状态与新格数不对应，必须清。
        """
        dt_min = float(dt_min)
        if abs(dt_min - self.dt_min) < 1e-12:
            return
        self.dt_min = dt_min
        self._build_delay_line()
        self.x = 0.0
        self.prev_e = None

    # ------------------------------------------------------------ 状态接口
    def reset(self, u_init: Optional[float] = None) -> None:
        """班次切换/重启：清空内部模型。

        必须清：上个班次把水率推到 690 且模型已"记住"大量在途效应，
        新班次带着这份记忆开工，首拍会算出极端值。
        """
        if u_init is not None:
            self.u = float(np.clip(u_init, self.u_lo, self.u_hi))
        self.u0 = float(self.u)
        self.y_base = self.target
        self.x = 0.0
        self.buf = deque([0.0] * self.nd, maxlen=self.nd)
        self.prev_e = None
        self.steps = 0
        self.last_reason = ""

    def sync(self, u: float) -> None:
        """外部（电流规则）改动水率后同步当前值。

        不重建内部模型：电流规则造成的水率变化是真实发生的动作，
        物理上已进入对象，模型的在途状态应当保留。
        """
        self.u = float(np.clip(u, self.u_lo, self.u_hi))

    # ------------------------------------------------------------ 主入口
    def update(self, t3_now: float, slope: float = 0.0) -> float:
        """每个控制周期调用一次，返回新的水率设定 L/t。

        slope 参数保留仅为接口兼容，预测 PI 不使用它
        （它靠内部模型外推，不需要外部斜率）。
        """
        if not np.isfinite(t3_now):
            self.last_reason = "T3 无效，保持 %.0f 不动" % self.u
            self.steps += 1
            return self.u

        # ---- 预测：去掉死时间 ----
        y0 = self.gain * self.x                  # 无死时间模型输出
        y0_del = self.buf[0]                     # θ 分钟前的模型输出
        d_hat = t3_now - (self.y_base + y0_del)  # 扰动 + 失配
        y_pred = self.y_base + y0 + d_hat

        # ---- PI（增量式）----
        e = y_pred - self.target
        de = 0.0 if self.prev_e is None else (e - self.prev_e)
        self.prev_e = e
        du = self.kp * de + self.kp * self.dt_min / self.ti * e
        du = float(np.clip(du, -self.step_max, self.step_max))
        u_new = float(np.clip(self.u + du, self.u_lo, self.u_hi))

        # ---- 用真实下发值推进内部模型 ----
        a = self.dt_min / (self.tau + self.dt_min)
        self.x += a * ((u_new - self.u0) - self.x)
        self.buf.append(self.gain * self.x)

        delta = u_new - self.u
        self.u = u_new
        direction = "提水率" if delta > 1e-9 else ("降水率" if delta < -1e-9 else "保持")
        self.last_reason = (
            "预测PI：T3=%.1f 模型%.1f 扰动%+.1f → 预测%.1f (目标%.0f) "
            "偏差%+.1f → %s %+.1f → %.0f L/t"
            % (t3_now, self.gain * self.x, d_hat, y_pred, self.target,
               e, direction, delta, u_new))
        self.steps += 1
        return u_new

    # ------------------------------------------------------------ 诊断
    def snapshot(self) -> dict:
        """内部状态快照，供 /health 与 HMI 显示"""
        return {
            "u": round(self.u, 1),
            "model_out": round(self.gain * self.x, 2),
            "model_delayed": round(self.buf[0], 2),
            "disturbance": round(
                (self.gain * self.x) - self.buf[0], 2) if self.buf else 0.0,
            "delay_cells": self.nd,
            "steps": self.steps,
        }
