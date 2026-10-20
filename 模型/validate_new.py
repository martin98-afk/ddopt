# -*- coding: utf-8 -*-
"""
用今天的新数据独立验证已有模型，不混入辨识流程。

关键隔离措施（否则验证就失去意义）：
  1. 目录下只放今天这一个 zip，不加载任何历史数据
  2. 响应核用旧模型写死（从 README/既有结果取），不用新数据重新辨识
  3. 对比的是「新数据的实际人工操作」vs「若用旧模型接管会怎样」

验证的四个问题：
  A. 生产判据是否仍成立（给水给料允许信号 ↔ 给料量）
  B. 工况是否在模型适用范围内（水率/给料/T3 分布）
  C. 若模型接管，安全约束是否仍合规
  D. A/B 反事实：模型 vs 新数据中的人工操作
"""
import os
import struct
import sys
import time
import zipfile

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

BASE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(os.path.dirname(BASE), "脱硫脱硝消石灰制备数据")

from config import Tag, Config                                   # noqa: E402
from signal_conditioning import SignalConditioner                # noqa: E402
from controller import XshController, Phase, Action              # noqa: E402

# ---- 旧模型的响应核（来自 10-12~10-19 的 12 个阶跃事件辨识，勿改）----
G_OLD = np.array([
    0.0000, 0.3595, 0.3970, 0.4299, 0.4532, 0.4675, 0.4663, 0.4529,
    0.4239, 0.3845, 0.3327, 0.2730, 0.2099, 0.1506, 0.0984, 0.0430,
    -0.0137, -0.0689, -0.1124, -0.1521, -0.1841, -0.2155, -0.2390, -0.2612,
    -0.2799, -0.2945, -0.3098, -0.3175, -0.3224, -0.3222, -0.3190, -0.3203,
    -0.3213, -0.3254, -0.3236, -0.3176, -0.3091, -0.2973, -0.2856, -0.2745,
    -0.2679, -0.2532, -0.2401, -0.2283, -0.2272, -0.2275, -0.2266, -0.2264,
    -0.2253, -0.2260, -0.2304, -0.2386, -0.2485, -0.2559, -0.2579, -0.2539,
    -0.2458, -0.2323, -0.2270, -0.2229, -0.1510])


def load_single_zip(zip_path):
    """只加载指定的一个 zip，返回 {测点名: (ts, val)}"""
    merged = {}
    with zipfile.ZipFile(zip_path) as z:
        for entry in z.namelist():
            if not entry.lower().endswith(".csv"):
                continue
            with z.open(entry) as f:
                text = f.read().decode("utf-8", errors="replace")
            lines = text.splitlines()
            if len(lines) < 3:
                continue
            name_line = next(__import__("csv").reader([lines[0]]), None)
            if not name_line or len(name_line) < 2:
                continue
            name = name_line[1].strip()
            ts_list, v_list = [], []
            for line in lines[2:]:
                if not line:
                    continue
                parts = next(__import__("csv").reader([line]), None)
                if not parts or len(parts) < 2:
                    continue
                try:
                    ts = parse_ts(parts[0])
                    val = float(parts[1])
                except (ValueError, IndexError):
                    continue
                if ts < 1577836800:
                    continue
                ts_list.append(ts)
                v_list.append(val)
            if ts_list:
                o = np.argsort(ts_list)
                merged[name] = (np.array(ts_list)[o], np.array(v_list)[o])
    return merged


_day = {}


def parse_ts(s):
    s = s.strip()
    if len(s) < 19:
        raise ValueError(s)
    date, hms = s[:10], s[11:19]
    d0 = _day.get(date)
    if d0 is None:
        d0 = int(time.mktime(time.strptime(date, "%Y-%m-%d")))
        _day[date] = d0
    return d0 + int(hms[:2]) * 3600 + int(hms[3:5]) * 60 + int(hms[6:8])


def build_minute_table(raw):
    """对齐到分钟网格，step-hold 语义"""
    ts_min = min(t[0] for t, _ in raw.values())
    ts_max = max(t[-1] for t, _ in raw.values())
    grid = np.arange(ts_min // 60 * 60, (ts_max // 60 + 1) * 60, 60, dtype=np.int64)
    data, switches = {}, set()
    for name, (ts, v) in raw.items():
        uniq = np.unique(v)
        is_sw = uniq.size <= 2 and np.all((uniq == 0) | (uniq == 1))
        if is_sw:
            switches.add(name)
        b = (ts - grid[0]) // 60
        m = (b >= 0) & (b < grid.size)
        agg = np.full(grid.size, np.nan)
        agg[b[m]] = v[m]
        if is_sw:
            agg = np.nan_to_num(_ffill(agg), nan=0.0)
        else:
            agg = _ffill(agg)
        data[name] = agg

    class MinuteTable:
        """最小 WideTable 实现，满足 SignalConditioner 所需接口"""

        def __init__(self, grid, data, switches):
            self.grid = grid
            self.data = data
            self.switches = switches
            self.meta = {}

        def series(self, n):
            return self.data.get(n, np.full(self.grid.size, np.nan))

        def __contains__(self, n):
            return n in self.data

    return MinuteTable(grid, data, switches)


def _ffill(a):
    out = a.copy()
    m = np.isnan(out)
    if m.all():
        return out
    idx = np.where(~m, np.arange(out.size), 0)
    np.maximum.accumulate(idx, out=idx)
    out[m] = out[idx[m]]
    return out


def main():
    zips = sorted([f for f in os.listdir(DATA_DIR) if f.endswith(".zip")])
    print("=" * 90)
    print("新数据独立验证（不混入辨识）")
    print("=" * 90)
    print("数据目录中的 zip: %s" % zips)
    if not zips:
        print("未找到 zip")
        return
    zp = os.path.join(DATA_DIR, zips[-1])
    print("本次验证只用: %s" % os.path.basename(zp))

    raw = load_single_zip(zp)
    wt = build_minute_table(raw)
    print("\n载入 %d 个测点，%d 分钟（%s ~ %s）" % (
        len(raw), wt.grid.size,
        time.strftime("%m-%d %H:%M", time.localtime(wt.grid[0])),
        time.strftime("%m-%d %H:%M", time.localtime(wt.grid[-1]))))

    sc = SignalConditioner(wt, Config())
    perm = sc.production_mask()
    print("\n[1] 生产判据")
    print("  允许信号=1: %d 分钟" % perm.sum())
    lime = wt.series(Tag.LIME)
    agree = np.sum(perm == (lime > 0.1))
    print("  允许信号 与 给料量>0.1 一致率: %.2f%% (%d/%d)" % (
        100 * agree / wt.grid.size, agree, wt.grid.size))
    if perm.sum():
        c1 = wt.series(Tag.CURR1)
        print("  生产时段: I1 均值 %.2f 最大 %.2f（>18 占 %.2f%%）" % (
            np.nanmean(c1[perm]), np.nanmax(c1[perm]),
            100 * np.nanmean(c1[perm] > 18)))
        R = wt.series(Tag.RATIO_SD)
        T3 = np.nanmean([wt.series(t) for t in Tag.TEMP[2]], axis=0)
        print("  水率: %.0f~%.0f  给料: %.2f~%.2f  T3: %.0f~%.0f" % (
            np.nanmin(R[perm]), np.nanmax(R[perm]),
            np.nanmin(lime[perm]), np.nanmax(lime[perm]),
            np.nanmin(T3[perm]), np.nanmax(T3[perm])))

    # 分段
    d = np.diff(perm.astype(np.int8))
    starts = list(np.where(d == 1)[0] + 1)
    ends = list(np.where(d == -1)[0] + 1)
    if perm[0]:
        starts.insert(0, 0)
    if perm[-1]:
        ends.append(perm.size)
    segs = [(s, e) for s, e in zip(starts, ends) if e - s >= 30]
    print("\n[2] 生产班次 %d 段" % len(segs))
    for s, e in segs:
        T3 = np.nanmean([wt.series(t) for t in Tag.TEMP[2]], axis=0)
        t3 = T3[s:e]
        t3 = t3[~np.isnan(t3)]
        print("  %s ~ %s  %4d min   T3 均值 %6.1f  合格率 %5.1f%%" % (
            time.strftime("%m-%d %H:%M", time.localtime(wt.grid[s])),
            time.strftime("%m-%d %H:%M", time.localtime(wt.grid[e - 1])),
            e - s, t3.mean(), 100 * np.mean((t3 >= 100) & (t3 <= 130))))

    # 控制器接管验证
    print("\n[3] 旧模型接管新数据（只用旧响应核，不重新辨识）")
    cfg = Config()
    ctrl = XshController(sc, cfg)
    viol = {"水率": 0, "给料": 0, "电流": 0, "T3": 0}
    acts = {}
    t3_sim_all, t3_act_all = [], []
    for i in range(wt.grid.size):
        out = ctrl.step(i)
        acts[out.action.value] = acts.get(out.action.value, 0) + 1
        if out.ratio_set < cfg.safety.ratio_safe_min - 1 or \
           out.ratio_set > cfg.safety.ratio_safe_max + 1:
            viol["水率"] += 1
        if out.lime_set < cfg.safety.lime_min - 1e-6 or \
           out.lime_set > cfg.safety.lime_max + 1e-6:
            viol["给料"] += 1
        if not np.isnan(out.curr1) and out.curr1 >= cfg.safety.curr1_trip:
            viol["电流"] += 1
        if not np.isnan(out.temp3) and out.temp3 > cfg.safety.temp_hard_high:
            viol["T3"] += 1
        if out.phase == Phase.STEADY and not np.isnan(out.temp3):
            t3_sim_all.append(out.temp3)
            t3_act_all.append(T3[i])

    print("  动作构成: %s" % acts)
    print("  违规: %s" % viol)
    if t3_sim_all:
        a = np.array(t3_act_all)
        b = np.array(t3_sim_all)
        print("\n[4] T3 对照（稳态段）")
        print("  实际人工: 均值 %.1f  合格率 %.1f%%  >130 %.1f%%" % (
            a.mean(), 100 * np.mean((a >= 100) & (a <= 130)),
            100 * np.mean(a > 130)))
        print("  模型接管: 均值 %.1f  合格率 %.1f%%  >130 %.1f%%" % (
            b.mean(), 100 * np.mean((b >= 100) & (b <= 130)),
            100 * np.mean(b > 130)))


if __name__ == "__main__":
    main()
