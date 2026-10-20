# -*- coding: utf-8 -*-
"""最小 DMC 控制器（单 MV 水率 → 单 CV T3）。

结构：
  预测   ŷ(k+i) = y_free(k+i) + Σ_j a[i-j]·Δu_j     （动态矩阵 + 自由响应）
  自由响应 由内部 FOPDT 状态前向仿真（延迟线 + 一阶滤波），
         假设未来 MV 保持当前值
  校正   bias = EMA( y_meas − y_model )，补偿模型失配与扰动
  优化   min ‖A·ΔU − (sp − y_free)‖² + λ‖ΔU‖²   → 解析解
         ΔU = (AᵀA + λI)⁻¹ Aᵀ (sp − y_free)
  约束   MV 幅值域 [lo, hi]、单步 |Δu| ≤ du_max（裁剪实现）

与参考实现（脱硫脱硝 dmc.py）的差异：无多变量、无前馈/DV、无硬约束
CV 保护、求解用解析解而非 SLSQP——本实验只验证 FOPDT+DMC 的
基本伺服与抗扰能力。
"""
from __future__ import annotations

import numpy as np

from fopdt import step_coeffs, build_A


class DMCController:
    def __init__(self, K: float, tau: float, theta: float,
                 sp: float = 118.0, Ts: float = 10.0, P: int = 18, M: int = 3,
                 lam: float = 0.1, u_lo: float = 570.0, u_hi: float = 690.0,
                 du_max: float = 15.0, u_init: float = 630.0,
                 bias_tc: float = 3.0):
        """
        K/tau/theta：FOPDT 参数（℃/(L/t), min, min）
        sp         ：T3 设定 ℃
        Ts/P/M/lam ：控制周期 min、预测步、控制步、抑权
        bias_tc    ：bias 校正时间常数（拍）
        """
        self.K, self.tau, self.theta = K, tau, theta
        self.sp, self.Ts, self.P, self.M, self.lam = sp, Ts, P, M, lam
        self.u_lo, self.u_hi, self.du_max = u_lo, u_hi, du_max
        self.a = step_coeffs(K, tau, theta, Ts, P)
        self.A = build_A(self.a, M)
        self.H = np.linalg.inv(self.A.T @ self.A + lam * np.eye(M)) @ self.A.T
        # 内部状态：延迟线 + 一阶滤波（相对 u0 基准的偏差量建模）
        nd = max(int(round(theta / Ts)), 1)
        self.u0 = u_init
        self._buf = [u_init] * nd
        self._x = u_init
        self.u = u_init
        self.bias = 0.0
        self.bias_tc = max(bias_tc, 1e-9)
        self.steps = 0

    def reset(self, u_init: float = None):
        if u_init is not None:
            self.u0 = u_init
        nd = max(int(round(self.theta / self.Ts)), 1)
        self._buf = [self.u0] * nd
        self._x = self.u0
        self.u = self.u0
        self.bias = 0.0
        self.steps = 0

    def step(self, y_meas: float) -> float:
        """每控制周期调用：给当前 T3 测量，返回新的水率设定"""
        # 1) 模型当前输出（相对基准 u0 的偏差）与 bias 校正
        y_mod = self.K * (self._x - self.u0) + self.bias
        self.bias += (y_meas - y_mod) / self.bias_tc
        self.bias = float(np.clip(self.bias, -30.0, 30.0))

        # 2) 自由响应：滤波状态 x 从当前值向保持值 u 指数趋近
        a = self.Ts / (self.tau + self.Ts)
        i = np.arange(1, self.P + 1)
        xs = self.u + (self._x - self.u) * (1.0 - a) ** i
        y_free = self.K * (xs - self.u0) + self.bias

        # 3) 解析解 + 约束裁剪
        e = self.sp - y_free
        du = self.H @ e
        du_step = float(np.clip(du[0], -self.du_max, self.du_max))
        u_new = float(np.clip(self.u + du_step, self.u_lo, self.u_hi))

        # 4) 用真实下发值推进内部状态一拍（延迟线 + 一阶滤波）
        u_del = self._buf[0]
        self._x += a * (u_del - self._x)
        self._buf.append(u_new)
        self._buf.pop(0)
        self.u = u_new
        self.steps += 1
        return u_new
