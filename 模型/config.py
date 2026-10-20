# -*- coding: utf-8 -*-
"""
消石灰制备控制模型 · 参数配置

所有可调阈值集中在此，现场可改。默认值依据 10-12~10-19 共 8 个生产班次
（51.3 小时）的实测数据标定，标注了每个数字的来源与置信度。
"""
from dataclasses import dataclass, field, asdict
from typing import Dict


# ---------------------------------------------------------------- 测点名常量
class Tag:
    PERMIT = "5#_XSH_GSGLYXXH"      # 给水给料允许信号（生产判据，唯一入口）
    SCRAPER = "5#_XSH_GLJQTXH"      # 刮料机启停信号
    RATIO_SD = "5#_XSH_SL(SHB)SD"   # 水率(水灰比)设定   L/t
    RATIO_FK = "5#_XSH_SL(SHB)FK"   # 水率(水灰比)反馈
    WATER = "5#_XSH_SLLSJZ"         # 水流量实际值       L/h
    LIME = "5#_XSH_SSHLLSJZ"        # 生石灰流量实际值   t/h
    LIME_SD = "5#_XSH_SSHLLSDZ"     # 生石灰流量设定值
    SPEED1_SD = "5#_XSH_1JLXSSJZSGD"  # 1级螺旋输送机转速给定
    SPEED1_FK = "5#_XSH_1JLXSSJSDFK"  # 1级螺旋输送机速度反馈
    CURR1 = "5#_XSH_1JLXSSJDL"      # 1级螺旋输送机电流  A
    CURR2 = "5#_XSH_2JLXSSJDL"
    CURR3 = "5#_XSH_3JLXSSJDL"
    BIN_HIGH = "5#_XSH_XSHLCGLW"    # 消石灰料仓高料位（= 消石灰仓位）
    LIME_BIN = "5#_XSH_SSHCW"       # 生石灰仓位
    WATER_TANK = "5#_XSH_GYSXSW"    # 工艺水箱水位
    EXHAUST_FAN = "5#_XSH_XHQDBPQFJYXXH"  # 消化器顶部排气风机运行信号

    # 温度：TEMP[级序号0-2][测点序号0-2]
    TEMP = [[f"5#_XSH_{j}JWDZ{k}" for k in (1, 2, 3)] for j in (1, 2, 3)]
    # 温度高报警
    TEMP_ALARM_H = [[f"5#_XSH_{j}JWDZ{k}BJXHG" for k in (1, 2, 3)] for j in (1, 2, 3)]


@dataclass
class SafetyLimits:
    """安全约束 —— 硬边界，任何情况下不可突破"""

    # ---- L1 螺旋输送机电流 (A) ----
    # 实测：生产时段 均值 12.53 / 标准差 0.36 / P99 14.11 / 最大 15.96（51.3h 无越限）
    curr1_warn: float = 16.0     # 预警：开始减料
    curr1_high: float = 18.0     # 高报：强制降载（用户指定 X，默认 18）
    curr1_trip: float = 23.0     # 高高报：停产（用户指定，现场最高状态）

    # ---- L3 出口温度 (℃) ----
    temp3_low: float = 100.0     # 低于此值反应不充分
    temp3_high: float = 130.0    # 高于此值超限
    temp3_target: float = 118.0  # 目标中值（区间中心偏上，留 12℃ 上下余量）

    # ---- 温度硬边界（设备/安全）----
    temp_hard_high: float = 250.0    # 任何级温度超过此值判定测点异常或严重超温
    temp_rise_rate_max: float = 15.0  # 10 分钟内升速上限 ℃/10min
    # 非最小相位下加水前 10 分钟的瞬时升温幅度（实测升水率事件 +5min +8.3℃）
    temp3_reverse_rise: float = 8.0

    # ---- 料位 ----
    bin_level_stop: float = 7.0   # 消石灰仓高料位，达到则停止制料
    bin_level_start: float = 3.0  # 消石灰仓低料位，达到则启动制料（对应现场 3m/7m）
    lime_bin_min: float = 2.0     # 生石灰仓最低料位，低于此无法给料

    # ---- 水率 ----
    ratio_min: float = 200.0      # L/t（文档给定下限）
    ratio_max: float = 800.0      # L/t（文档给定上限）
    ratio_safe_min: float = 350.0  # 实际安全下限，低于此反应不充分易板结
    ratio_safe_max: float = 750.0  # 实际安全上限

    # ---- 生石灰流量 ----
    lime_min: float = 2.0         # t/h
    lime_max: float = 6.0         # t/h
    lime_default: float = 3.5     # 默认给料量（文档：一般 3.5t 稳定不调）


@dataclass
class ControlParams:
    """控制律参数"""

    # ---- 阶段划分 ----
    startup_max_min: float = 120.0    # 启动阶段最长时长（实测：T2 高温持续到 ~140min）
    temp3_stable_min: float = 100.0   # T3 超过此值视为进入稳定

    # ---- 水率调节步长与死区 ----
    # 【重要设计修正，来自反事实 A/B 仿真】
    # 初版设计追求「把 T3 纠到目标 118℃」，结果仿真中模型把水率从 630
    # 一路拉到 350（物理下限），T3 标准差反而从 2.9 涨到 9.6，合格率
    # 从 100% 掉到 91% —— 而同期人工操作是「水率恒定 630 不动」。
    #
    # 原因：水率对 T3 的稳态增益仅 -0.151 ℃/(L/t)，而 T3 的班次间差异
    # 达 28.6℃ 且由原料批次主导（不可控）。在一个主导扰动不可控、
    # 执行器增益又很小的系统里，最优策略是「最小干预」，不是「持续纠偏」。
    #
    # 因此改为：宽死区 + 窄操作带 + 无积分。
    # 操作带收窄到实测操作员实际使用的区间，而不是文档给的 200~800。
    ratio_op_min: float = 580.0       # 水率操作下限 L/t
    ratio_op_max: float = 690.0       # 水率操作上限 L/t
    ratio_nominal: float = 630.0      # 经验中值（实测众数 630）
    # 偏离经验中值的最大幅度。注意：hi = min(ratio_op_max, nominal+band)
    #   lo = max(ratio_op_min, nominal-band)
    # band 必须与 op_min/op_max 自洽，否则历史数据会持续越界。
    # 旧值 band=45 -> hi=675，而实测水率最高 690，导致模型每分钟都
    # 触发「水率回归」动作（新数据验证中 46 次降低水率全是这个，与温度无关）。
    # 现扩到 60，使操作带 [570, 690] 完整覆盖实测范围 300~750 中的常用段。
    ratio_band: float = 60.0
    ratio_step_max: float = 15.0      # 单次最大调节步长 L/t
    ratio_step_min: float = 2.0       # 最小有效步长 L/t（旧值 5 会挡掉小幅纠偏）
    temp3_deadband: float = 2.0       # T3 控制死区 ℃
    # 【守护带 = 工艺合格区间 100~130℃，不可收窄】
    # 依据《控制逻辑.txt》：L3 层温度保持在 100 度 - 130 度。
    # 这是工艺硬约束，不是可调参数。
    #
    # 曾自作聪明收窄到 110~122，结果在 T3 均值 108.8 的班次上，
    # 模型判定「偏低」一路减水到 594，把 T3 推到 100℃ 以下 9 分钟，
    # 合格率反而比人工低 2.1 个百分点。
    # 教训：守护带必须等于工艺要求，不能比它更严。
    temp3_action_low: float = 100.0   # 工艺下限，低于此才纠偏
    temp3_action_high: float = 130.0  # 工艺上限，高于此才纠偏

    # ---- 手段优先级：水率优先，给料量为后备 ----
    # 【设计修正：手段顺序搞反了】
    # 初版把降料写在加水之前，且降料触发线 130-8=122 低于纠偏触发线 126，
    # 数学上导致加水分支永远执行不到（死代码）——一旦 T3 越过 126 进入纠偏，
    # 它必然同时 > 122，直接落到降料。
    #
    # 现场经验与水率物理意义一致：水率越大温度越低（稳态增益 -0.151℃/(L/t)）。
    # 故手段顺序应为：先加水，水率用到操作上限仍压不住，才动给料量。
    #
    # 三条触发线的大小关系必须严格满足：
    #   temp3_action_high(126) < temp3_derate_high(136) < temp3_high(130)? 
    # 注意：降料线应设在「已越合格上限且加水空间用尽」之后，
    # 即 水率到操作上限 且 T3 仍 > temp3_derate_high 才降料。
    temp3_derate_high: float = 132.0  # T3 高过此值 且 水率已到操作上限 → 才降料

    # ---- 控制周期 ----
    control_interval_min: float = 10.0   # 控制周期（分钟）
    # 索引跳变容差：超过此值视为停机/通信中断，重置班次状态。
    # 默认取控制周期，保证「按控制周期调用」不会被误判为间隙。
    gap_tolerance: float = 10.0

    # ---- 节流：多久真正更新一次设定值 ----
    # 现场规则引擎每 10 秒调用一次推理服务。模型按真实时间戳判断：
    # 距上次下发不满 throttle_min 分钟 -> 原样返回上次结果，什么都不做；
    # 满了才取当前温度算一次，输出新值。
    #
    #   throttle_min = 0   不节流，每次调用都算
    #   throttle_min = 10  每 10 分钟下发一次新值（推荐，等同离线验证口径）
    #
    # 节流期内不推数据、不推进时间轴，所以缓冲内容与「直接每 10 分钟
    # 调用一次」完全相同，两者输出逐拍一致（已验证，最大差 0.0000）。
    # 节流只影响「多久下发一次」，不影响单次动作幅度。
    throttle_min: float = 10.0
    temp3_eval_window: float = 15.0      # T3 评估窗口（分钟），用滑动均值抑制噪声

    # ---- 预测与时滞（严格事件研究，12 个水率阶跃）----
    # 升水率： +5min +8.3℃  +15min -0.0℃  +30min -3.3℃
    # 降水率： +5min -6.5℃  +15min -3.6℃  +30min +6.5℃
    # => 非最小相位，反向期约 15 min，稳态效应在 30 min 后显现
    lag_temp3_reverse: float = 10.0  # 反向响应峰值时刻（分钟），此期间禁止追加同向动作
    lag_temp3_steady: float = 30.0   # 稳态效应显现时刻（分钟）
    action_wait_min: float = 35.0    # 两次动作的最小间隔，必须 > lag_temp3_steady

    # ---- 比例增益 ----
    # 依据辨识出的稳态增益 -0.151 ℃/(L/t)，其倒数为 -6.6 L/t per ℃。
    # 考虑模型不确定性（12 个样本，外推性存疑），取 60% -> 4.0
    kp_temp3: float = 4.0        # L/t per ℃
    # 积分项取消：主导扰动（原料批次）不可控，积分只会累积成单向漂移，
    # 把水率推到物理边界。这是仿真中查出的最大缺陷。
    ki_temp3: float = 0.0
    kd_temp3: float = 0.0        # 微分对噪声敏感，稳态 T3 噪声小但存在跳变

    # ---- 电流保护 ----
    curr1_action_step: float = 0.2   # 每次降载的给料量步长 t/h
    curr1_recover_step: float = 0.1  # 每次恢复的给料量步长 t/h（比降载更保守）
    # 电流规则（水率优先 -> 转速辅助 -> 降料兑底）相邻两步的最小间隔（分钟）。
    # 与 T3 节拍（35min）分开：负荷保护等不了那么久，按一个控制周期升级一档。
    curr_rule_wait_min: float = 10.0
    # 电流规则中单次加水率的步长 L/t（用比 T3 纠偏更快的节奏响应负荷）
    curr_rule_ratio_step: float = 15.0
    # 降料兑底时同步回降水的步长 L/t（现场规则：降下料量及水率）
    curr_rule_ratio_back: float = 5.0

    # ---- 严重超温/超低温快通道（瞬时值直判，不受滑动滞后与节拍限制）----
    # 背景：滑动中位对跳变型超温滞后达 30min，且节拍锁死后续拍无法追加。
    temp3_fast_high: float = 135.0   # 瞬时 T3 超此值当拍触发（防毛刺靠信号调理层变化率剔除）
    temp3_fast_low: float = 95.0     # 瞬时 T3 低于此值当拍触发（仅稳态阶段生效）
    fast_step_min: float = 15.0      # 快通道最小步长 L/t
    fast_step_max: float = 90.0      # 快通道最大步长 L/t（按偏差比例，可一步顶格）

    # ---- 趋势预测控制（现役算法，模仿人工：当前温度+变化斜率提前干预）----
    # 旧守护带算法（死区+节拍+顶格锁死）已移除。
    # 预测温度 = 当前 + 斜率×前瞻；预测偏离目标 118℃ 即按比例调水率：
    # 温度超标→提水率；降回目标且趋势向下→减水回调；双向、每拍可动。
    trend_kp: float = 2.0            # L/t per ℃（预测误差比例系数）
    # 斜率前瞻（分钟）。原值 15.0，2026-10-21 改为 8.0，依据实测：
    #   用真实数据检验线性外推的预测精度（对 873 个生产分钟）：
    #     前瞻 5min  -> RMSE 11.81℃  相关 0.764
    #     前瞻 10min -> RMSE 17.26℃  相关 0.535
    #     前瞻 15min -> RMSE 23.80℃  相关 0.245   <- 原值，预判几乎失效
    #     前瞻 20min -> RMSE 29.64℃  相关 0.056
    #   超出 5~8 分钟后温度已转向，线性外推跟不上，再往前看反而引入噪声。
    #   闭环对照（对象 K=-0.151 τ=60 θ=30，周期 10min）：
    #     predict_min=15 -> 77.2%，行程 1504
    #     predict_min=8  -> 80.2%，行程 1197
    #   合格 +3.0 个百分点，同时行程降 20%。
    trend_predict_min: float = 8.0
    trend_dead: float = 3.0          # 预测误差死区 ℃
    trend_dead_slope: float = 0.3    # 斜率死区 ℃/min（贴目标且平稳时不动）
    trend_step_max: float = 25.0     # 单拍步长上限 L/t（温和微调，像人工）
    trend_step_fast: float = 60.0    # 瞬时严重越线（>135/<95）时单拍步长上限
    trend_slope_window: float = 15.0 # 斜率拟合窗口（分钟）
    trend_ratio_lo: float = 500.0    # 水率下限（控制范围 500~690，不可超过）

    # ---- 下料量调节范围（现场规则：限制在现场设定值 ±0.5 t/h 内）----
    lime_field_sp: float = 3.5       # 现场下料量设定值 t/h（服务配置，/reset 可改）
    lime_band: float = 0.5           # 允许偏离设定值的最大幅度 t/h

    # ---- 启动初始设定（现场设定，/reset 可覆盖）----
    ratio_init: float = 600.0        # 初始水率 L/t（现场例：600）
    # 一级电机转速：现阶段固定输出（不参与调节）。
    # 取自实测生产数据：反馈 42~50、中位 46（众数 46）；/startup 可改。
    speed1_fixed: float = 46.0

    # ---- 给料量降载纪律（T3 偏高时的最后手段）----
    # 仿真教训：曾出现 29 次连续降载，给料量在 2.85~3.58 t/h 间横跳，
    # 既无效又伤产量。故限制总次数与降幅下限。
    lime_derate_max: int = 3         # 单班次内最多自动降料 3 次
    lime_derate_step: float = 0.2    # 每次降载步长 t/h
    # 下限改由 lime_field_sp - lime_band 推出（现场规则：设定值 ±0.5）

    # ---- 数据质量 ----
    temp_outlier_abs: float = 250.0   # 温度绝对值异常阈值
    temp_outlier_rate: float = 30.0   # 10 分钟内变化速率异常阈值 ℃
    min_valid_points: int = 2         # 每层至少需要的有效温度测点数


@dataclass
class Config:
    safety: SafetyLimits = field(default_factory=SafetyLimits)
    control: ControlParams = field(default_factory=ControlParams)

    def set_curr1_high(self, x: float) -> None:
        """设置 L1 电流上限 X（用户可配置，默认 18）"""
        if not (0 < x < self.safety.curr1_trip):
            raise ValueError("X 必须满足 0 < X < 高高报阈值(%.1f)" % self.safety.curr1_trip)
        self.safety.curr1_high = x
        # 预警阈值跟随下调，保持 2A 余量
        self.safety.curr1_warn = max(x - 2.0, self.safety.curr1_warn * 0.8)

    def to_dict(self) -> Dict:
        return {"safety": asdict(self.safety), "control": asdict(self.control)}


DEFAULT_CONFIG = Config()
