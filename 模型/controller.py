# -*- coding: utf-8 -*-
"""
消石灰制备参数控制模型 · 核心控制器

============================ 设计依据（全部来自实测数据） ============================

数据基础：2026-10-12 ~ 10-19，8 个生产班次，51.3 小时，3079 分钟生产数据。
生产判据：给水给料允许信号 == 1（与生石灰流量>0 完全一致，3079/3079 = 100%）

【核心发现 1】水率 -> T3 的响应存在争议，已按「滞后互相关」重新定符号
    早期事件研究（15 个动作事件）测到水率↑ 后 0~10 min T3 +4.7℃、20~35 min
    -6.5℃，据此推断非最小相位。后续用滞后互相关复检发现：lag=-5 时
    corr=+0.44（T3 先动，操作员随后加水）是操作员反馈伪影，lag=+20 时
    corr=-0.51 才是真实因果（水率先加，T3 后降）。
    => 水率对 T3 是纯滞后负响应，不存在瞬时反向段。
       现役趋势控制按这一结论实现：斜率项代表 T3 自身走势，不是水率的
       反向响应，故无需「动作 → 等待 → 再评估」的节拍锁。

【核心发现 2】生石灰流量 -> L1 电流 在分钟级几乎无响应（25 个事件，±0.1A）
    稳态段 L1 电流标准差仅 0.19A，给料量调整 0.2t/h 的电流响应淹没在噪声里。
    => 电流保护不能依赖精细模型，只能用「阶跃降载 + 观察」的保守规则。

【核心发现 3】各温度层的稳态特征
    T1 ≈ 154℃（稳定，波动小）  T2 ≈ 115℃  T3 ≈ 121℃（标准差 10.4，>130 占 25%）
    启动后 20~40 分钟 T2 会出现剧烈反应（峰值可达 422℃），实测为正常现象。

【核心发现 4】班次间的主导扰动是原料批次/环境，不是水率
    水率在稳态段标准差仅 12.5 L/t（操作员几乎不调），
    而 T3 在各班次稳态均值从 108.8 到 137.4，跨度 28.6℃。
    => 开环设定值无法保证 T3 合格，必须闭环；但也说明单靠水率调节能力有限，
       故生石灰流量作为第二手段（改变热负荷总量）。

============================ 控制架构 ============================

【第 0 层】异常只记录
  · 联锁 / 料位 / 电流 / 温度边界 -> 只写 notes，不拦截
  · 停不停机、切不切手动由 DCS 决定，模型不干预
  · 唯一例外：L1 电流 ≥ X 时负荷保护规则接管水率与给料

【第 1 层】阶段判定
  · 启动阶段（外部走 /startup）：温度同样进闭环，不做特殊门控
  · 稳态阶段（外部走 /infer）：现场约定启动 120min 且 T3 ≥ 100℃ 后切换
  · 两阶段的温度控制都是趋势预测，区别只在外部何时切端点

【第 2 层】温度控制 = 趋势预测（现役算法，实现见 trend.py）
  · 预测温度 = T3 当前 + 斜率 × 15 min 前瞻
  · 预测偏离目标 118℃ 就按比例调水率（双向、每拍可动）
  · 贴目标且平稳（|err| ≤ 3℃ 且 |slope| < 0.3）才不动
  · 斜率取自 T3 滑动中位的线性拟合，横轴是真实分钟（在线每拍 10min）

【第 3 层】输出限幅
  · 单拍步长上限 25 L/t（瞬时 T3 > 135 或 < 95 时放宽到 60）
  · 水率裁剪到 [500, 690]
  · 给料量裁剪到现场设定值 ±0.5 t/h

============================ 职责边界（最重要的一条）=============================

    本模型**只负责计算两个设定值**：水率（L/t）与生石灰流量（t/h）。

    以下事情**全部与模型无关**，由 DCS / 操作员决定：
      · 停不停机、停不停料
      · 切自动还是手动
      · 联锁、报警、跳闸
      · 料位高时怎么处理
      · 电流超限时是否降负荷

    旧版把这些都揽进模型里（料位高就 STOP_FEED 并 return、
    联锁不满足就 MANUAL 退出、电流高就强制降载），导致两个后果：
      1. 模型经常主动放弃控制权，等于自己关掉自己
         （新数据验证中第二班次料位全程 >= 7.0m，模型 50 分钟全在停机）
      2. 验证时测不到模型的真实能力，因为大部分时间它根本没在算

    现版：模型只要收到温度与电流，就无条件算出给定值。
    外部怎么用这个值，模型不关心、不干预、不判断。
    异常情况只写进 notes 供外部参考，不改变输出。
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Tuple

import numpy as np

from config import Config, SafetyLimits, ControlParams, DEFAULT_CONFIG, Tag
from trend import TrendController


class Phase(Enum):
    """阶段只用于内部逻辑，不表示是否接管现场"""
    STARTUP = "启动"
    STEADY = "稳态"


class Action(Enum):
    """只描述「模型这次算什么」，不描述对现场执行了什么"""
    HOLD = "保持"
    RAISE_RATIO = "提高水率"
    LOWER_RATIO = "降低水率"
    RAISE_LIME = "增加给料"
    LOWER_LIME = "减少给料"


@dataclass
class ControlOutput:
    """模型输出：两个设定值 + 决策说明 + 提示信息"""

    t_index: int
    phase: Phase
    ratio_set: float          # 水率设定 L/t
    lime_set: float           # 生石灰流量设定 t/h
    speed_set: float = np.nan  # 一级电机转速（现阶段固定值，不参与调节）
    action: Action = Action.HOLD
    reason: str = ""
    notes: List[str] = field(default_factory=list)   # 提示，不改变输出

    # 状态快照（供 HMI 显示，不参与计算）
    temp1: float = np.nan
    temp2: float = np.nan
    temp3: float = np.nan
    curr1: float = np.nan
    ratio_act: float = np.nan

    @property
    def water_set(self) -> float:
        """由水率与给料量反算水流量设定 L/h"""
        return self.ratio_set * self.lime_set


@dataclass
class ControllerState:
    """控制器内部状态（跨周期保持）"""
    last_idx: Optional[int] = None      # 上次被调用的分钟索引，用于间隙检测
    last_action_idx: int = -9999        # 上次动作的分钟索引
    integral: float = 0.0               # T3 偏差积分
    consecutive_over: int = 0           # 连续超限计数
    curr1_derate_active: bool = False   # 电流降载中
    startup_start_idx: Optional[int] = None
    phase: Phase = Phase.STARTUP
    lime_override: Optional[float] = None  # 电流保护产生的给料量覆盖值
    lime_derate_count: int = 0       # 降料次数（T3 偏高时），超上限即转人工
    ratio_override: Optional[float] = None  # 模型自持水率（模型动作后持久化，微服务模式下不读现场水率设定）
    curr_stage: int = 0              # 电流规则档位：0 保持 / 1 加水率 / 2 建议提转速 / 3 降料兑底
    curr_stage_idx: int = -9999      # 上次电流规则动作索引
    recovering: bool = False         # 电流回落后的恢复中（持续到回到设定值/初始值）
    fast_count: int = 0              # 瞬时严重越线计数（保留用于 reason 展示与将来滤波）
    recovering: bool = False         # 电流回落后的恢复中（持续到回到设定值/初始值）


class XshController:
    """
    消石灰制备控制器。

    调用方式：每个控制周期（默认 10 分钟）调用一次 step(i)，
    内部自行维护状态。
    """

    def __init__(self, conditioner, cfg: Config = DEFAULT_CONFIG):
        self.conditioner = conditioner
        self.sc = conditioner
        self.cfg = cfg
        self.S = cfg.safety
        self.C = cfg.control
        self.state = ControllerState()
        self.history: List[ControlOutput] = []
        # 趋势预测控制器（现役温度控制算法）：参数从 config 读
        self._trend = TrendController(
            target=self.S.temp3_target,
            kp=self.C.trend_kp,
            predict_min=self.C.trend_predict_min,
            dead=self.C.trend_dead,
            dead_slope=self.C.trend_dead_slope,
            step_max=self.C.trend_step_max,
            step_fast=self.C.trend_step_fast,
            fast_hi=self.C.temp3_fast_high,
            fast_lo=self.C.temp3_fast_low,
            u_lo=max(self.S.ratio_safe_min, self.C.trend_ratio_lo),
            u_hi=self.C.ratio_op_max,
            u_init=self.C.ratio_init)

    # ============================================================ 状态重置
    def _reset_shift(self, st: "ControllerState") -> None:
        """班次切换或停机：清空所有跨班次状态，防止残留污染下一个班次"""
        st.phase = Phase.STARTUP
        st.startup_start_idx = None
        st.last_action_idx = -9999
        st.lime_override = None
        st.lime_derate_count = 0
        st.curr_stage = 0
        st.curr_stage_idx = -9999
        st.recovering = False
        st.fast_count = 0
        st.ratio_override = None   # 班次切换即弃，微服务重启用 /reset 重设
        # 趋势控制器内部水率必须一起回初始值，否则上一个班次把它推到 690，
        # 新班次首拍直接从 690 起算，等于带着旧班次的结论开工。
        self._trend.reset(self.C.ratio_init)

    # ============================================================ 下料量边界
    def _lime_lo(self) -> float:
        """下料量下限 = max(绝对下限, 现场设定值 − 调节带)"""
        return max(self.S.lime_min, self.C.lime_field_sp - self.C.lime_band)

    def _lime_hi(self) -> float:
        """下料量上限 = min(绝对上限, 现场设定值 + 调节带)"""
        return min(self.S.lime_max, self.C.lime_field_sp + self.C.lime_band)

    # ============================================================ 主入口
    def step(self, i: int, phase: Optional[Phase] = None,
             data_idx: Optional[int] = None) -> ControlOutput:
        """执行第 i 分钟的控制周期。

        i：时间轴（分钟），用于动作间隔/阶段计时；
           在线模式下由 service 传虚拟时间轴（每拍 = 一个控制周期）。
        data_idx：数据访问索引，缺省 = i（离线回放，宽表全量）；
           在线模式传环形缓冲末位（只有末位是最新值）。
        phase：缺省时内部自动判定（离线回放）；
           微服务由外部判定阶段，经 /startup、/infer 分别强制传入。
        """
        sc = self.sc
        st = self.state
        di = i if data_idx is None else data_idx

        t1 = sc.clean_temp(1, di)
        t2 = sc.clean_temp(2, di)
        t3m = sc.clean_temp(3, di)
        t3 = sc.temp3_control_value(di)
        curr1 = sc.curr1_smooth(di)
        ratio_act = sc.ratio_actual(di)
        lime_act = sc.lime_flow(di)

        # ---------- 索引间隙检测（必须在构造输出之前）----------
        # 判据是「间距 > gap_tolerance」，默认取控制周期 10。
        # 教训：早期写死为 1，在 10 分钟粒度采样中每步都误判为通信中断，
        # _reset_shift 反复触发，节拍计时与降料计数全部失效。
        # 顺序也踩过坑：reset 若放在构造 out 之后，本拍仍用旧班次的
        # ratio_override 起算，重置形同虚设。
        if st.last_idx is not None and i > st.last_idx + self.C.gap_tolerance:
            self._reset_shift(st)
        st.last_idx = i

        # 生石灰流量：下料量调节范围限制在现场设定值 ±0.5 t/h（现场规则），
        # 故基准锚定设定值而非实际流量；模型干预后用自持值保证动作可累积。
        if st.lime_override is not None:
            base_lime = st.lime_override
        else:
            base_lime = self.C.lime_field_sp

        # 水率基准：模型自持值优先（微服务模式下现场水率设定不可实时读取），
        # 其次数据表设定值（离线回放），最后启动初始水率（现场设定）。
        rv = float(sc.wt.series(Tag.RATIO_SD)[di])
        if st.ratio_override is not None:
            ratio_base = st.ratio_override
        elif not np.isnan(rv):
            ratio_base = rv
        else:
            ratio_base = self.C.ratio_init

        out = ControlOutput(
            t_index=i, phase=st.phase,
            ratio_set=float(ratio_base),
            lime_set=float(base_lime),
            speed_set=float(self.C.speed1_fixed),
            temp1=t1.median, temp2=t2.median, temp3=t3, curr1=curr1,
            ratio_act=ratio_act,
        )

        # ---------- 阶段判定 ----------
        # 离线回放：内部按 elapsed 与 T3 自动判定；
        # 微服务：外部判定阶段并选择调用端点，这里直接采用传入阶段。
        if phase is not None:
            is_startup = (phase == Phase.STARTUP)
            st.phase = phase
            if st.startup_start_idx is None:
                st.startup_start_idx = i
            elapsed = i - st.startup_start_idx
        else:
            if st.startup_start_idx is None:
                st.startup_start_idx = i
            elapsed = i - st.startup_start_idx
            t3_ready = (not np.isnan(t3)) and (t3 >= self.C.temp3_stable_min)
            is_startup = elapsed < self.C.startup_max_min and not t3_ready
            st.phase = Phase.STARTUP if is_startup else Phase.STEADY
        out.phase = st.phase

        # ---------- 异常情况只记录，不拦截 ----------
        # 料位、联锁、电流、温度边界，全部只写 notes。
        # 是否停机由 DCS 决定，模型不干预。
        bin_state = sc.bin_level_state(di)
        if bin_state == "high":
            out.notes.append("消石灰仓高料位 %.2f，建议外部评估停料" %
                             sc.wt.series(Tag.BIN_HIGH)[di])
        elif bin_state == "low":
            out.notes.append("消石灰仓低料位 %.2f" %
                             sc.wt.series(Tag.BIN_HIGH)[di])

        ok, why = sc.interlocks_ok(di)
        if not ok:
            out.notes.append("联锁异常：%s" % why)

        if not np.isnan(curr1):
            if curr1 >= self.S.curr1_trip:
                out.notes.append("L1电流 %.2fA 已达高高报 %.1fA" % (
                    curr1, self.S.curr1_trip))
            elif curr1 >= self.S.curr1_high:
                out.notes.append("L1电流 %.2fA 超上限 %.1fA" % (
                    curr1, self.S.curr1_high))
            elif curr1 >= self.S.curr1_warn:
                out.notes.append("L1电流 %.2fA 接近上限" % curr1)

        # ---------- 阶段主逻辑：无条件算出给定值 ----------
        # 温度控制 = 趋势预测算法（模仿人工，见 trend.TrendController）。
        # 电流规则（现场逻辑：水率优先、转速辅助、负荷兑底）优先于趋势控制：
        # I1 ≥ X 或已有电流干预未恢复时，负荷保护接管。
        curr_active = (not np.isnan(curr1)) and \
                      (curr1 >= self.S.curr1_high or st.curr_stage > 0) \
                      or st.recovering
        if curr_active:
            out = self._curr_rule_logic(i, out, curr1)
        elif np.isnan(t3):
            out.action = Action.HOLD
            out.reason = "T3 无效，保持水率 %.0f 不动" % out.ratio_set
        else:
            slope = sc.t3_slope(di, self.C.trend_slope_window)
            # 趋势控制器的水率状态以 out.ratio_set 为准（它可能已被电流规则
            # 或现场设定改动过），先同步再算，避免内部值与实际输出各走一路。
            self._trend.sync(out.ratio_set)
            new_r = self._trend.update(t3, slope)
            delta = new_r - out.ratio_set
            out.ratio_set = new_r
            st.ratio_override = new_r
            st.last_action_idx = i
            out.action = (Action.RAISE_RATIO if delta > 0 else
                          (Action.LOWER_RATIO if delta < 0 else Action.HOLD))
            out.reason = self._trend.last_reason

        # ---------- 输出限幅：下料量永远限制在现场设定值 ±lime_band 内 ----------
        out.lime_set = float(np.clip(out.lime_set, self._lime_lo(), self._lime_hi()))

        out.phase = st.phase
        self.history.append(out)
        return out

    # ==================================================== 电流规则（两阶段共用）
    def _curr_rule_logic(self, i: int, out: ControlOutput,
                         curr1: float) -> ControlOutput:
        """
        一级电流规则（现场控制逻辑，启动/运行阶段共用）

          水率优先：I1 ≥ X 先加水率；
          转速辅助：水率到操作上限仍高 → 建议提高一级电机转速（模型无转速输出，仅提示）；
          负荷兑底：仍高 → 降低下料量及水率，下料量限制在现场设定值 ±0.5 t/h；
          I1 ≥ 高高报(23A)：高负荷风险报警（停机由 DCS 执行，模型不干预）。

        电流回落到 X 以下后，逐拍恢复到初始设定/设定值（恢复步长比降载保守）。
        """
        st = self.state
        C = self.C
        wait = max(C.control_interval_min, C.curr_rule_wait_min)

        if np.isnan(curr1) or curr1 < self.S.curr1_high:
            st.recovering = True
            return self._curr_recover(i, out, curr1)

        since = i - st.curr_stage_idx
        if st.curr_stage > 0 and since < wait:
            out.action = Action.HOLD
            out.reason = ("电流规则：I1=%.2f ≥ X=%.1f（档位%d），距上次动作 %d min /"
                          " 需 %d min，等待响应" % (
                              curr1, self.S.curr1_high, st.curr_stage,
                              int(since), int(wait)))
            return out

        # ---- 阶梯升级 ----
        if st.curr_stage == 0:
            st.curr_stage = 1

        if st.curr_stage == 1:
            hi_r = min(C.ratio_op_max, C.ratio_nominal + C.ratio_band)
            if out.ratio_set < hi_r - 1e-6:
                new_r = float(min(out.ratio_set + C.curr_rule_ratio_step, hi_r))
                out.ratio_set = new_r
                st.ratio_override = new_r
                st.curr_stage_idx = i
                out.action = Action.RAISE_RATIO
                out.reason = ("电流规则(水率优先)：I1=%.2f ≥ X=%.1f → 加水率至"
                              " %.0f L/t" % (curr1, self.S.curr1_high, new_r))
                return out
            st.curr_stage = 2
            st.curr_stage_idx = i
            out.action = Action.HOLD
            out.reason = ("电流规则(转速辅助)：水率已到操作上限 %.0f 仍 I1=%.2f，"
                          "建议提高一级电机转速加快进料（模型无转速输出）" % (
                              hi_r, curr1))
            out.notes.append("建议人工提高一级电机转速")
            return out

        if st.curr_stage == 2:
            # 转速辅助观察一个周期仍高 → 转入兑底
            st.curr_stage = 3

        # ---- 档位 3：负荷兑底：降下料量及水率 ----
        lo = self._lime_lo()
        r_floor = max(self.S.ratio_safe_min, min(self.C.ratio_init, C.ratio_op_min))
        moved = False
        if out.lime_set > lo + 1e-6:
            new_lime = float(max(out.lime_set - C.curr1_action_step, lo))
            out.lime_set = new_lime
            st.lime_override = new_lime
            moved = True
        if out.ratio_set > r_floor + 1e-6:
            new_r = float(max(out.ratio_set - C.curr_rule_ratio_back, r_floor))
            out.ratio_set = new_r
            st.ratio_override = new_r
            moved = True
        if moved:
            st.curr_stage_idx = i
            out.action = Action.LOWER_LIME
            out.reason = ("电流规则(负荷兑底)：I1=%.2f 仍 ≥ X=%.1f → 降下料量至"
                          " %.2f t/h、水率 %.0f L/t（下料量限 %.2f~%.2f）" % (
                              curr1, self.S.curr1_high, out.lime_set,
                              out.ratio_set, lo, self._lime_hi()))
        else:
            out.action = Action.HOLD
            out.reason = ("电流规则：下料量/水率均已到兑底下限（%.2f t/h / %.0f L/t），"
                          "维持并提示人工" % (lo, r_floor))
            out.notes.append("电流仍高但调节空间耗尽，需人工介入")
        return out

    def _curr_recover(self, i: int, out: ControlOutput,
                      curr1: float) -> ControlOutput:
        """电流回落到 X 以下：逐拍恢复到初始设定/设定值（步长比降载保守）"""
        st = self.state
        C = self.C
        st.curr_stage = 0
        moved = False
        if st.lime_override is not None:
            target = C.lime_field_sp
            new_lime = float(np.clip(st.lime_override + C.curr1_recover_step,
                                     target - C.lime_band, target))
            st.lime_override = None if abs(new_lime - target) <= 1e-6 else new_lime
            out.lime_set = new_lime
            moved = True
        if st.ratio_override is not None and \
                st.ratio_override < self.C.ratio_init - 1e-6:
            new_r = float(min(st.ratio_override + C.curr_rule_ratio_step,
                              self.C.ratio_init))
            st.ratio_override = None if new_r >= self.C.ratio_init - 1e-6 else new_r
            out.ratio_set = new_r
            moved = True
        if not moved:
            st.recovering = False   # 恢复完成
        if moved:
            st.curr_stage_idx = i
            out.action = Action.HOLD
            out.reason = ("电流已回落至 X=%.1f 以下，恢复设定（下料量 %.2f t/h、"
                          "水率 %.0f L/t）" % (self.S.curr1_high,
                                               out.lime_set, out.ratio_set))
        else:
            out.action = Action.HOLD
            out.reason = ("电流正常（I1=%.2f < X=%.1f），保持设定" % (
                curr1 if not np.isnan(curr1) else -999, self.S.curr1_high))
        return out
