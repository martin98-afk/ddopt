# -*- coding: utf-8 -*-
"""
在线服务接口：把控制器包装成可对接实时数据库的形式。

用法：
    svc = XshService()
    out = svc.on_tick(snapshot_dict)     # 每个控制周期调用一次
    # out 含 ratio_set / lime_set / water_set 等可直接下发的设定值

快照字段（模拟量 float，开关量 0/1）：
    permit        给水给料允许信号
    temp1_1..3    1级三个温度
    temp2_1..3    2级三个温度
    temp3_1..3    3级三个温度
    curr1         1级螺旋输送机电流
    water_flow    水流量实际值 L/h
    lime_flow     生石灰流量实际值 t/h
    ratio_set     当前水率设定 L/t
    lime_set      当前生石灰流量设定 t/h（无则传实际值）
    bin_level     消石灰料仓料位 m
    lime_bin      生石灰仓位 m
    water_tank    工艺水箱水位 m
    exhaust_fan   消化器顶部排气风机运行信号
"""
from typing import Dict, Optional

import numpy as np

from config import Config, Tag
from controller import XshController, ControlOutput, Phase, Action
from signal_conditioning import SignalConditioner


class SnapshotAdapter:
    """
    把实时快照适配成 SignalConditioner 所需的 WideTable 接口。

    控制器内部会回看历史（变化率校验回看 10 分钟、T3 评估窗口 15 分钟），
    因此这里维护一个环形缓冲，保留最近 HIST 个周期的快照，
    最新一份放在索引 [-1]。调用方须按固定周期调用。
    """

    HIST = 30      # 保留最近 30 个控制周期

    def __init__(self, snap: Dict[str, float], min_per_index: float = 10.0):
        # 每个缓冲格 = 一个控制周期（默认 10 min），斜率与升温速率按此换算
        self.min_per_index = float(min_per_index)
        self._init_from(snap)

    def _init_from(self, snap: Dict[str, float]):
        m = {
            Tag.PERMIT: snap.get("permit", 0.0),
            Tag.LIME: snap.get("lime_flow", np.nan),
            Tag.WATER: snap.get("water_flow", np.nan),
            Tag.RATIO_SD: snap.get("ratio_set", np.nan),
            Tag.RATIO_FK: snap.get("ratio_set", np.nan),
            Tag.CURR1: snap.get("curr1", np.nan),
            Tag.BIN_HIGH: snap.get("bin_level", np.nan),
            Tag.LIME_BIN: snap.get("lime_bin", np.nan),
            Tag.WATER_TANK: snap.get("water_tank", np.nan),
            Tag.EXHAUST_FAN: snap.get("exhaust_fan", 1.0),
        }
        for j in range(3):
            for k in range(3):
                m[Tag.TEMP[j][k]] = snap.get("temp%d_%d" % (j + 1, k + 1), np.nan)
        self._cols = list(m.keys())
        self._data = {k: np.full(self.HIST, np.nan) for k in self._cols}
        self.grid = np.zeros(self.HIST, dtype=np.int64)
        self.push(snap)

    def push(self, snap: Dict[str, float]) -> None:
        """追加一个新快照（左移丢弃最旧）"""
        for k in self._cols:
            a = self._data[k]
            a[:-1] = a[1:]
        latest = {
            Tag.PERMIT: snap.get("permit", 0.0),
            Tag.LIME: snap.get("lime_flow", np.nan),
            Tag.WATER: snap.get("water_flow", np.nan),
            Tag.RATIO_SD: snap.get("ratio_set", np.nan),
            Tag.RATIO_FK: snap.get("ratio_set", np.nan),
            Tag.CURR1: snap.get("curr1", np.nan),
            Tag.BIN_HIGH: snap.get("bin_level", np.nan),
            Tag.LIME_BIN: snap.get("lime_bin", np.nan),
            Tag.WATER_TANK: snap.get("water_tank", np.nan),
            Tag.EXHAUST_FAN: snap.get("exhaust_fan", 1.0),
        }
        for j in range(3):
            for k in range(3):
                latest[Tag.TEMP[j][k]] = snap.get("temp%d_%d" % (j + 1, k + 1), np.nan)
        for k in self._cols:
            v = latest.get(k, np.nan)
            self._data[k][-1] = float(v) if v is not None else np.nan

    def series(self, name: str) -> np.ndarray:
        return self._data.get(name, np.array([np.nan]))

    def __contains__(self, name) -> bool:
        return name in self._data

    def __getitem__(self, name) -> np.ndarray:
        return self.series(name)


class XshService:
    """在线控制服务"""

    def __init__(self, cfg: Optional[Config] = None):
        self.cfg = cfg or Config()
        self.ctrl: Optional[XshController] = None
        self.sc: Optional[SignalConditioner] = None
        self.tick = 0
        self.last_output: Optional[ControlOutput] = None
        # 节流用：上次真正下发新值的时刻（epoch 秒）。初始 0 保证首拍必算。
        self._last_update_ts = 0.0
        self._update_seq = 0      # 真正下发的次数（驱动虚拟时间轴）

    def set_curr1_high(self, x: float) -> None:
        """在线修改 L1 电流上限 X"""
        self.cfg.set_curr1_high(x)

    def on_tick(self, snap: Dict[str, float],
                phase: Optional["Phase"] = None) -> ControlOutput:
        """
        每次调用喂一份实时快照。

        模型只负责算出 ratio_set 与 lime_set，不判断现场是否接管。
        停机很久后再启动，索引跳变由内部间隙检测处理，仅复位内部状态。

        节流（throttle_min）：外部可高频调用（如 10 秒一次），
        但距上次下发不满 throttle_min 分钟时，什么都不做，原样返回上次结果；
        满了才取当前数据算一次，下发新值。

        phase：微服务模式下由外部判定阶段后强制传入（Phase.STARTUP /
        Phase.STEADY）；缺省时控制器内部自动判定（离线回放）。
        """
        import time as _time
        thr = float(getattr(self.cfg.control, "throttle_min", 0.0) or 0.0)
        now = _time.time()
        if thr > 0 and self.last_output is not None:
            if (now - self._last_update_ts) < thr * 60.0:
                # 未到下发给时间：原样返回上次结果，不推数据、不算
                self.tick += 1
                return self.last_output

        if self.sc is None:
            self.sc = SignalConditioner(
                SnapshotAdapter(snap,
                                self.cfg.control.control_interval_min),
                self.cfg)
            self.ctrl = XshController(self.sc, self.cfg)
        else:
            self.sc.wt.push(snap)

        i = int(round(self._update_seq
                      * self.cfg.control.control_interval_min))
        out = self.ctrl.step(i, phase, data_idx=SnapshotAdapter.HIST - 1)
        self._last_update_ts = now
        self._update_seq += 1
        self.tick += 1
        self.last_output = out
        return out

    def status(self) -> Dict:
        """返回当前输出摘要，便于上位机展示"""
        o = self.last_output
        if o is None:
            return {"ready": False}
        return {
            "ready": True,
            "phase": o.phase.value,
            "action": o.action.value,
            "reason": o.reason,
            "notes": o.notes,
            "ratio_set": round(o.ratio_set, 1),
            "lime_set": round(o.lime_set, 2),
            "speed_set": round(o.speed_set, 1),
            "water_set": round(o.water_set, 0),
            "temp1": None if np.isnan(o.temp1) else round(o.temp1, 1),
            "temp2": None if np.isnan(o.temp2) else round(o.temp2, 1),
            "temp3": None if np.isnan(o.temp3) else round(o.temp3, 1),
            "curr1": None if np.isnan(o.curr1) else round(o.curr1, 2),
            "curr1_limit": self.cfg.safety.curr1_high,
        }


def demo():
    """用历史数据的真实快照演示在线调用"""
    from data_loader import build_wide
    wt = build_wide(verbose=False)
    svc = XshService()
    svc.set_curr1_high(18.0)

    TEMP = Tag.TEMP
    prod_idx = np.where(wt.series(Tag.PERMIT) > 0.5)[0]
    picks = [int(x) for x in prod_idx[::300]]      # 每 5 小时取一个采样点

    print("=" * 82)
    print("在线服务演示（每 5 小时取一个真实快照）")
    print("=" * 82)
    print("%-17s %-6s %-10s %8s %8s %8s %7s" % (
        "时间", "阶段", "动作", "水率", "给料", "T3", "I1"))
    for i in picks:
        snap = {
            "permit": float(wt.series(Tag.PERMIT)[i]),
            "lime_flow": float(wt.series(Tag.LIME)[i]),
            "water_flow": float(wt.series(Tag.WATER)[i]),
            "ratio_set": float(wt.series(Tag.RATIO_SD)[i]),
            "curr1": float(wt.series(Tag.CURR1)[i]),
            "bin_level": float(wt.series(Tag.BIN_HIGH)[i]),
            "lime_bin": float(wt.series(Tag.LIME_BIN)[i]),
            "water_tank": float(wt.series(Tag.WATER_TANK)[i]),
            "exhaust_fan": float(wt.series(Tag.EXHAUST_FAN)[i]),
        }
        for j in range(3):
            for k in range(3):
                snap["temp%d_%d" % (j + 1, k + 1)] = float(wt.series(TEMP[j][k])[i])
        out = svc.on_tick(snap)
        import time as _t
        ts = _t.strftime("%m-%d %H:%M", _t.localtime(wt.grid[i]))
        print("%-17s %-6s %-10s %8.0f %8.2f %8.1f %7.2f" % (
            ts, out.phase.value, out.action.value,
            out.ratio_set, out.lime_set, out.temp3, out.curr1))
        if out.alarms:
            print("      报警: " + "; ".join(out.alarms))


if __name__ == "__main__":
    demo()
