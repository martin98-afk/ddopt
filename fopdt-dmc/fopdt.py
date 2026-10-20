# -*- coding: utf-8 -*-
"""FOPDT（一阶惯性+纯滞后）工具：拟合、阶跃系数。

模型：y(t) = y0 + K·(1 - exp(-(t-θ)/τ))·Δu，t ≥ θ
  K: 稳态增益 ℃/(L/t)   τ: 时间常数 min   θ: 纯滞后 min

已知局限（本实验要验证的核心点）：
  水率→T3 是**非最小相位**（加水后 T3 先升 +6℃ 再降），FOPDT 的
  单调阶跃响应无法表达符号反转，拟合只能抓住稳态段（K<0），
  前段反向响应全部落入残差。残差大小 = DMC 的模型失配下限。
"""
from __future__ import annotations

import numpy as np


def fit_fopdt_from_kernel(G: np.ndarray, Ts: float = 1.0):
    """
    从阶跃响应核 G[k]（℃ per L/t，单位阶跃的逐分钟响应）拟合 FOPDT。

    方法：θ 网格逐点平移 + (K, τ) 非线性最小二乘（或网格 + 线性解）。
    返回 dict(K, tau, theta, rmse, r2, tail_gain)。
    """
    G = np.asarray(G, float)
    n = len(G)
    k = np.arange(n) * Ts
    var = float(np.var(G)) or 1e-12

    thetas = np.arange(0.0, 31.0, 1.0)          # 0~30 min
    taus = np.array([2., 3., 5., 8., 10., 15., 20., 30., 45., 60., 90., 120.])
    best = None
    for th in thetas:
        for tau in taus:
            a = np.where(k >= th, 1.0 - np.exp(-(k - th) / tau), 0.0)
            # 线性解 K（无截距：核从 0 起步）
            K = float(np.dot(a, G) / max(np.dot(a, a), 1e-12))
            rmse = float(np.sqrt(np.mean((G - K * a) ** 2)))
            if best is None or rmse < best["rmse"]:
                best = dict(K=K, tau=float(tau), theta=float(th),
                            rmse=rmse, r2=1.0 - rmse ** 2 / var)
    # 精修：在网格最优附近局部优化 τ
    th0, tau0 = best["theta"], best["tau"]
    for tau in np.linspace(max(tau0 * 0.5, 0.5), tau0 * 1.5, 40):
        a = np.where(k >= th0, 1.0 - np.exp(-(k - th0) / tau), 0.0)
        K = float(np.dot(a, G) / max(np.dot(a, a), 1e-12))
        rmse = float(np.sqrt(np.mean((G - K * a) ** 2)))
        if rmse < best["rmse"]:
            best.update(K=K, tau=float(tau), rmse=rmse, r2=1.0 - rmse ** 2 / var)
    best["tail_gain"] = float(G[-1])
    return best


def step_coeffs(K: float, tau: float, theta: float, Ts: float, P: int):
    """FOPDT 的 P 步单位阶跃响应系数 a[k]（每 +1 单位 MV 的 CV 响应）"""
    k = np.arange(1, P + 1) * Ts
    return np.where(k >= theta, K * (1.0 - np.exp(-(k - theta) / max(tau, 1e-9))),
                    0.0)


def build_A(a: np.ndarray, M: int):
    """P×M 动态矩阵：A[i,j] = a[i-j]，i<j 时为 0"""
    P = len(a)
    A = np.zeros((P, M))
    for i in range(P):
        for j in range(M):
            if i - j >= 0:
                A[i, j] = a[i - j]
    return A
