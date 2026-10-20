# -*- coding: utf-8 -*-
"""
信号调理层：把原始测点变成模型可信任的状态量。

三件事：
  1. 生产状态判定 —— 给水给料允许信号为唯一入口，配合流量确认
  2. 温度测点清洗与层级聚合 —— 剔除仪表故障点，输出每层可信温度
  3. 变化率估计 —— 用于趋势预测与超温预警

实测依据：
  - 允许信号与生石灰流量>0 完全一致（3079 分钟，100% 吻合）
  - T2-2/T2-3 在启动后 20~140 分钟会出现 >200℃ 读数（峰值 422.9℃），
    用户确认为正常现象（二级反应剧烈），不作为故障剔除，
    但对超过物理上限（250℃）的点做标记，不参与控制目标计算
  - T2-1 全程无 >200℃ 读数，是唯一"干净"的二级测点
"""
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import numpy as np

from config import Tag, DEFAULT_CONFIG


@dataclass
class LayerTemp:
    """单层温度的聚合结果"""
    level: int                  # 1/2/3
    median: float               # 层中位温度（稳健主值）
    mean: float                 # 层均值（剔除异常后）
    valid_count: int            # 有效测点数
    raw: List[float] = field(default_factory=list)     # 各测点清洗后值
    suspect: List[bool] = field(default_factory=list)  # 各测点是否可疑
    rising_rate: float = 0.0    # 最近 10 分钟升温速率 ℃/10min

    @property
    def trustworthy(self) -> bool:
        return self.valid_count >= DEFAULT_CONFIG.control.min_valid_points


class SignalConditioner:
    """有状态的信号调理器（按分钟步进调用）"""

    def __init__(self, wt, cfg=DEFAULT_CONFIG):
        self.wt = wt
        self.cfg = cfg
        self.n = wt.grid.size
        # 温度历史缓存，用于变化率估计
        self._hist: List[List[float]] = [[] for _ in range(3)]

    @property
    def min_per_index(self) -> float:
        """每个数据索引代表的分钟数。

        离线回放宽表逐分钟采样 → 1.0；
        在线环形缓冲每格 = 一个控制周期（默认 10 min）→ 由 SnapshotAdapter 给。
        趋势斜率必须以真实分钟为横轴，否则在线模式下会被放大 10 倍。
        """
        return float(getattr(self.wt, "min_per_index", 1.0))

    def _win_indices(self, minutes: float) -> int:
        """把「多少分钟」换成「多少个数据索引」。
        离线每格 1 分钟 → 原值；在线每格 10 分钟 → 15min 只要 2 格。
        不做换算则在线模式的 15min 窗口实际覆盖 150min。"""
        step = self.min_per_index
        return max(1, int(round(minutes / step)))

    # ---------------------------------------------------------- 生产状态
    def production_mask(self) -> np.ndarray:
        """
        生产状态判定。
        主判据：给水给料允许信号 == 1（用户明确要求）
        辅判据：生石灰实际流量 > 0.1 t/h（100% 与主判据吻合，用于交叉校验）
        """
        perm = self.wt.series(Tag.PERMIT)
        lime = self.wt.series(Tag.LIME)
        mask = (perm > 0.5) & (lime > 0.1)
        return mask

    def interlocks_ok(self, i: int) -> Tuple[bool, str]:
        """
        运行就绪连锁条件检查。
        返回 (是否允许模型控制, 原因)
        """
        wt = self.wt
        # 排气风机必须运行
        if Tag.EXHAUST_FAN in wt:
            if wt.series(Tag.EXHAUST_FAN)[i] < 0.5:
                return False, "消化器顶部排气风机未运行"
        # 生石灰仓有料
        lime_bin = wt.series(Tag.LIME_BIN)[i]
        if not np.isnan(lime_bin) and lime_bin < self.cfg.safety.lime_bin_min:
            return False, "生石灰仓位过低(%.2f)" % lime_bin
        # 工艺水箱水位
        tank = wt.series(Tag.WATER_TANK)[i]
        if not np.isnan(tank) and tank <= 0:
            return False, "工艺水箱无水"
        return True, ""

    def bin_level_state(self, i: int) -> str:
        """消石灰料仓状态：high / normal / low"""
        lv = self.wt.series(Tag.BIN_HIGH)[i]
        if np.isnan(lv):
            return "unknown"
        if lv >= self.cfg.safety.bin_level_stop:
            return "high"
        if lv <= self.cfg.safety.bin_level_start:
            return "low"
        return "normal"

    # ---------------------------------------------------------- 温度清洗
    def clean_temp(self, level: int, i: int) -> LayerTemp:
        """
        取第 level 层（1/2/3）第 i 分钟的温度。
        清洗规则：
          - 绝对值 > temp_outlier_abs  -> 标记可疑，不参与聚合
          - 与同层其他测点偏差过大（>100℃且其余点一致）-> 标记可疑
          - 10 分钟内变化 > temp_outlier_rate -> 平滑处理
        """
        cfg = self.cfg.control
        names = Tag.TEMP[level - 1]
        vals, suspect = [], []
        for nm in names:
            v = self.wt.series(nm)[i]
            s = False
            if np.isnan(v):
                vals.append(np.nan)
                suspect.append(True)
                continue
            if v > self.cfg.safety.temp_hard_high:
                s = True
            # 变化率校验：与 10 分钟前比较
            if i >= 10:
                prev = self.wt.series(nm)[i - 10]
                if not np.isnan(prev) and abs(v - prev) > cfg.temp_outlier_rate * 3:
                    s = True
            vals.append(v)
            suspect.append(s)

        arr = np.array(vals, dtype=np.float64)
        good = arr[~np.array(suspect) & ~np.isnan(arr)]

        # 同层交叉校验：若某点与层中位偏差 > 100℃，判可疑
        if good.size >= 2:
            med = np.median(good)
            for k in range(3):
                if not suspect[k] and not np.isnan(arr[k]) and abs(arr[k] - med) > 100:
                    suspect[k] = True
            good = arr[~np.array(suspect) & ~np.isnan(arr)]

        valid = int(good.size)
        median = float(np.median(good)) if valid else np.nan
        mean = float(np.mean(good)) if valid else np.nan

        # 变化率
        rate = 0.0
        self._hist[level - 1].append(median if valid else np.nan)
        h = self._hist[level - 1]
        if len(h) > 200:
            h.pop(0)
        if len(h) >= 11 and not np.isnan(h[-1]) and not np.isnan(h[-11]):
            rate = h[-1] - h[-11]

        return LayerTemp(level=level, median=median, mean=mean, valid_count=valid,
                         raw=vals, suspect=suspect, rising_rate=rate)

    def temp3_control_value(self, i: int) -> float:
        """
        用于控制与评估的 T3 值：滑动均值（15 分钟窗口），抑制噪声。
        实测 T3 的 10 分钟波动均值仅 0.23~0.86℃，噪声很小，
        但存在仪表跳变，故取滑动中位+均值混合。
        """
        w = self._win_indices(self.cfg.control.temp3_eval_window)
        lo = max(0, i - w + 1)
        vals = []
        for k in range(lo, i + 1):
            lt = self.clean_temp(3, k)
            if not np.isnan(lt.median):
                vals.append(lt.median)
        if not vals:
            return np.nan
        return float(np.median(vals))

    def t3_slope(self, i: int, window: float = 15.0) -> float:
        """趋势控制用：最近 window 分钟滑动中位 T3 的线性拟合斜率 ℃/min。

        横轴用真实分钟（索引 × min_per_index），否则在线模式下每拍 10 min
        却只走一格，斜率会被放大 10 倍。
        最少 3 点即拟合：控制周期 10min 时 15min 窗口只有 2 格，
        门槛设 5 会让斜率恒为 0，趋势项彻底失效（踩过这个坑）。"""
        w = self._win_indices(window)
        step = self.min_per_index
        lo = max(0, i - w + 1)
        ks, vs = [], []
        for k in range(lo, i + 1):
            lt = self.clean_temp(3, k)
            if not np.isnan(lt.median):
                ks.append(float(k) * step)
                vs.append(lt.median)
        if len(ks) < 3:
            return 0.0
        return float(np.polyfit(ks, vs, 1)[0])

    def curr1(self, i: int) -> float:
        return float(self.wt.series(Tag.CURR1)[i])

    def curr1_smooth(self, i: int, window: int = 5) -> float:
        lo = max(0, i - window + 1)
        v = self.wt.series(Tag.CURR1)[lo:i + 1]
        v = v[~np.isnan(v)]
        return float(np.mean(v)) if v.size else np.nan

    def ratio_actual(self, i: int) -> float:
        """实际水灰比 L/t（水流量 / 生石灰流量）；无流量时返回上次设定"""
        w = self.wt.series(Tag.WATER)[i]
        l = self.wt.series(Tag.LIME)[i]
        if not np.isnan(w) and not np.isnan(l) and l > 0.1:
            return float(w / l)
        return float(self.wt.series(Tag.RATIO_FK)[i])

    def lime_flow(self, i: int) -> float:
        return float(self.wt.series(Tag.LIME)[i])

    def is_producing(self, i: int) -> bool:
        return bool(self.wt.series(Tag.PERMIT)[i] > 0.5
                    and self.wt.series(Tag.LIME)[i] > 0.1)
