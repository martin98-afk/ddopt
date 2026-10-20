# -*- coding: utf-8 -*-
"""把预测 PI 装进 模型/ 的控制器骨架。

做法：复用 模型/controller.py 的 XshController（电流规则、阶段判定、
输出限幅、间隙检测全部保留），只把它的 self._trend 换成 PredictivePI。

为什么这么做而不是自己写一套控制器：
  模型/controller.py 里有大量现场规则，是从真实数据里踩坑总结出来的，
  重新实现一遍必然丢东西。换掉温度控制律是最小改动。
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

from config import Config                                    # noqa: E402
from controller import XshController                         # noqa: E402
from signal_conditioning import SignalConditioner            # noqa: E402

import 标定参数 as P                                          # noqa: E402
from predictive_pi import PredictivePI                       # noqa: E402


def _step_limit(interval_min: float = None) -> float:
    """单拍步长上限（速率化）：RATE_MAX × 周期。

    现役斜率规则的 step_max 是固定"每拍"值，在 10 秒周期下等于放大 60 倍。
    这里按真实时间换算，周期缩短时单拍上限自动变小。
    """
    return P.step_limit(interval_min)


def make_config() -> Config:
    """按 标定参数.py 构造配置"""
    cfg = Config()
    c = cfg.control
    c.control_interval_min = P.CONTROL_INTERVAL_MIN
    # 间隙检测容差跟随周期，否则按周期调用会被误判为通信中断
    c.gap_tolerance = P.CONTROL_INTERVAL_MIN
    c.ratio_init = P.RATIO_INIT
    c.trend_ratio_lo = P.RATIO_LO
    c.ratio_op_max = P.RATIO_HI
    c.trend_step_max = P.RATIO_STEP_MAX
    c.lime_field_sp = P.LIME_SP
    c.lime_band = P.LIME_BAND
    c.speed1_fixed = P.SPEED_FIXED
    cfg.set_curr1_high(P.CURR1_HIGH)
    return cfg


def attach_predictive_pi(ctrl: XshController,
                         cfg: Config) -> PredictivePI:
    """把控制器内部的温度控制律替换为预测 PI，并加装输出速率总闸。

    周期与步长上限都取自 cfg.control.control_interval_min，
    这样离线对比不同周期时，预测 PI 的限幅会跟着同步变化。
    """
    dt = cfg.control.control_interval_min
    ppi = PredictivePI(
        target=P.TARGET_T3,
        kp=P.KP,
        ti=P.TI,
        gain=P.GAIN,
        tau=P.TAU,
        theta=P.THETA,
        dt_min=dt,
        u_lo=max(cfg.safety.ratio_safe_min, P.RATIO_LO),
        u_hi=P.RATIO_HI,
        u_init=cfg.control.ratio_init,
        step_max=_step_limit(dt))
    ctrl._trend = ppi
    _install_rate_gate(ctrl, dt)
    return ppi


# ============================================================ 输出速率总闸
def _install_rate_gate(ctrl: XshController, dt: float) -> None:
    """包住 step()，对最终 ratio_set 再做一次速率限幅。

    为什么需要：controller.py 里水率基准优先读现场设定值 RATIO_SD，
    跨班次或现场手动改设定时，输出会直接跳过去（实测单拍跳变达 139 L/t）。
    PredictivePI 内部的 step_max 管不到这条路径。

    总闸放在最后，无论水率从温度控制、电流规则还是现场基准来，
    都强制按 RATE_MAX（L/t/min）限速。这是高频调用下不出事故的最后一道保险。
    """
    if getattr(ctrl, "_rate_gate_on", False):
        return
    cap = _step_limit(dt)
    lo, hi = P.RATIO_LO, P.RATIO_HI
    prev = {"u": None}
    orig_step = ctrl.step

    def step(i, phase=None, data_idx=None):
        out = orig_step(i, phase, data_idx)
        u = float(out.ratio_set)
        if prev["u"] is not None:
            du = u - prev["u"]
            if abs(du) > cap:
                u = prev["u"] + (cap if du > 0 else -cap)
                out.rate_limited = True          # 供 HMI 提示
        u = float(min(max(u, lo), hi))
        out.ratio_set = u
        # 让控制律内部状态跟上被限幅后的真实输出
        ppi = getattr(ctrl, "_trend", None)
        if ppi is not None and hasattr(ppi, "sync"):
            ppi.sync(u)
        prev["u"] = u
        return out

    ctrl.step = step
    ctrl._rate_gate_on = True
    ctrl._rate_gate_cap = cap


def build(wt=None):
    """构造 (cfg, conditioner, controller, ppi)

    wt 为 None 时只返回配置相关对象，供离线调用方自行注入宽表。
    """
    cfg = make_config()
    if wt is None:
        return cfg, None, None, None
    sc = SignalConditioner(wt, cfg)
    ctrl = XshController(sc, cfg)
    ppi = attach_predictive_pi(ctrl, cfg)
    return cfg, sc, ctrl, ppi
