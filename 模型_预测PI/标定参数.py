# -*- coding: utf-8 -*-
"""★ 现场标定参数 —— 下控前唯一需要修改的文件 ★

做完受控阶跃试验后，把实测值填进下面三个数，其余代码不用动。

    gain   稳态增益  ℃/(L/t)   水率 +1 L/t 最终让 T3 变多少
    tau    时间常数  min        效应显现的快慢（63% 所需时间）
    theta  纯滞后    min        从动作到 T3 开始转向的等待时间

再调这两个控制参数（可用默认值先跑）：

    kp     比例增益  L/t per ℃  偏差 1℃ 该动多少水率
    ti     积分时间  min        越小越积极，越大越保守
"""
from __future__ import annotations

# ============================================================ 对象参数（待标定）
# 当前为占位值，来源：模型/replay_shift_model.py 的保守 FOPDT 核。
# 未经现场阶跃验证，置信度低。标定后替换。
GAIN = -0.151        # ℃/(L/t)   负号=加水降温
TAU = 60.0           # min
THETA = 30.0         # min

# ============================================================ 控制参数
KP = 3.0             # L/t per ℃
TI = 20.0            # min

# ============================================================ 标定状态标记
# 改成 True 表示上面三个数已由现场阶跃验证，可以下控。
# 代码会在启动时检查，为 False 时仍可运行但会在 /health 与日志里提示。
CALIBRATED = False

# ============================================================ 服务与现场设定
CONTROL_INTERVAL_MIN = 10.0   # 控制周期（分钟）。现场 10 秒调用时填 1/6。
RATIO_INIT = 600.0            # 初始水率 L/t
RATIO_LO = 500.0              # 水率下限
RATIO_HI = 690.0              # 水率上限
RATIO_STEP_MAX = 25.0         # 单拍步长上限 L/t（10 分钟周期下的口径）

# 步长上限的速率化写法：RATE_MAX 是每分钟允许的最大变化 L/t。
# 单拍上限 = RATE_MAX × CONTROL_INTERVAL_MIN，与调用周期无关。
# 为什么必须速率化：固定"每拍 25 L/t"在 10 秒周期下等于 150 L/t/min，
# 是 10 分钟周期的 60 倍，会直接自激。这是现役斜率规则的主要缺陷。
# 现场按 10 秒调用时不要改 RATIO_STEP_MAX，改这个数即可。
# 依据：量程 190 L/t，死时间 30 min 量级，取 6 L/t/min ≈ 32 分钟走完全程。
RATE_MAX = 6.0                # L/t per min

def step_limit(interval_min: float = None) -> float:
    """单拍步长上限 = RATE_MAX × 周期（分钟）。

    现场 10 秒调用（interval=1/6）时自动收敛到 1 L/t/拍，
    避免"固定每拍 25 L/t"在高频下被放大 60 倍。
    """
    dt = CONTROL_INTERVAL_MIN if interval_min is None else interval_min
    return float(min(RATIO_STEP_MAX, RATE_MAX * max(dt, 1e-9)))


LIME_SP = 3.5                 # 现场下料量设定 t/h
LIME_BAND = 0.5               # 允许偏离 ±
SPEED_FIXED = 46.0            # 一级电机转速固定输出
CURR1_HIGH = 18.0             # 一级电流上限 A（X）

TARGET_T3 = 118.0             # T3 目标 ℃
T3_LOW, T3_HIGH = 100.0, 130.0   # 合格区间
