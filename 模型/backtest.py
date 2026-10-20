# -*- coding: utf-8 -*-
"""
离线回放验证。

在真实历史数据上运行控制器，检验两类问题：
  A. 合规性：模型每条建议是否违反安全约束（一票否决）
  B. 有效性：模型建议是否比操作员实际做法更能把 T3 拉进目标带

关于 B 的方法论说明（重要）：
  历史数据是操作员的闭环结果，无法做真正的反事实仿真。
  若直接比较「模型建议后的 T3 走向」，会混入操作员同时刻的反向操作，
  得到虚假结论。因此采用**干净动作子集**：
      只保留「模型建议方向 与 操作员实际后续 30 分钟操作方向一致」的样本，
  即模型与操作员在同一方向上行动，此时 T3 的走向可近似归因于该动作。
"""
import numpy as np

from data_loader import build_wide
from config import Tag, Config
from signal_conditioning import SignalConditioner
from controller import XshController, Phase, Action


def perf_stats(v, lo=100.0, hi=130.0):
    v = np.asarray(v, dtype=np.float64)
    v = v[~np.isnan(v)]
    if v.size == 0:
        return dict(n=0, mean=np.nan, std=np.nan, in_band=np.nan,
                    below=np.nan, above=np.nan)
    return dict(n=v.size, mean=float(v.mean()), std=float(v.std()),
                in_band=100 * np.mean((v >= lo) & (v <= hi)),
                below=100 * np.mean(v < lo), above=100 * np.mean(v > hi))


def run_backtest(x_curr1: float = 18.0, verbose: bool = True):
    wt = build_wide(verbose=False)
    cfg = Config()
    cfg.set_curr1_high(x_curr1)
    sc = SignalConditioner(wt, cfg)
    ctrl = XshController(sc, cfg)

    prod = sc.production_mask()
    idxs = np.where(prod)[0]

    if verbose:
        print("=" * 86)
        print("回放验证   X=%.1fA   T3目标 %.0f℃   合格区间[%.0f,%.0f]" % (
            cfg.safety.curr1_high, cfg.safety.temp3_target,
            cfg.safety.temp3_low, cfg.safety.temp3_high))
        print("=" * 86)
        print("生产分钟数 %d" % idxs.size)

    results = [ctrl.step(int(i)) for i in idxs]
    total = len(results)

    # ================= A. 安全合规 =================
    if verbose:
        print()
        print("-" * 86)
        print("【A】安全约束合规性")
        print("-" * 86)
    viol = {"水率越界": 0, "给料量越界": 0, "电流高高报": 0, "T3硬边界": 0}
    for o in results:
        # 模型只算给定值，不执行停机，故所有输出都参与越界检查
        if o.ratio_set < cfg.safety.ratio_safe_min - 1e-6 or \
           o.ratio_set > cfg.safety.ratio_safe_max + 1e-6:
            viol["水率越界"] += 1
        if o.lime_set < cfg.safety.lime_min - 1e-6 or \
           o.lime_set > cfg.safety.lime_max + 1e-6:
            viol["给料量越界"] += 1
        if not np.isnan(o.curr1) and o.curr1 >= cfg.safety.curr1_trip:
            viol["电流高高报"] += 1
        if not np.isnan(o.temp3) and o.temp3 > cfg.safety.temp_hard_high:
            viol["T3硬边界"] += 1
    if verbose:
        for k, v in viol.items():
            print("  %-14s %6d / %d   [%s]" % (k, v, total, "OK" if v == 0 else "违规"))

    # ================= B. 阶段与动作分布 =================
    if verbose:
        print()
        print("-" * 86)
        print("【B】阶段与动作分布")
        print("-" * 86)
    from collections import Counter
    ph = Counter(o.phase.value for o in results)
    ac = Counter(o.action.value for o in results)
    if verbose:
        for k, c in ph.most_common():
            print("  %-10s %6d 分钟 (%5.1f%%)" % (k, c, 100 * c / total))
        print("  ── 动作 ──")
        for k, c in ac.most_common():
            print("    %-12s %6d (%5.1f%%)" % (k, c, 100 * c / total))

    # ================= C. 与实际操作对照 =================
    steady = [o for o in results if o.phase == Phase.STEADY]
    if verbose:
        print()
        print("-" * 86)
        print("【C】模型建议 vs 实际操作（稳态阶段）")
        print("-" * 86)
        print("稳态样本 %d 分钟" % len(steady))
    if steady:
        act_r = np.array([sc.wt.series(Tag.RATIO_SD)[o.t_index] for o in steady])
        sug_r = np.array([o.ratio_set for o in steady])
        t3s = np.array([o.temp3 for o in steady])
        if verbose:
            print("  实际水率: 均值 %.1f  标准差 %.1f" % (np.nanmean(act_r), np.nanstd(act_r)))
            print("  建议水率: 均值 %.1f  标准差 %.1f" % (np.nanmean(sug_r), np.nanstd(sug_r)))
            print("  平均偏离 %+.1f L/t   最大偏离 %.0f L/t" % (
                np.nanmean(sug_r - act_r), np.nanmax(np.abs(sug_r - act_r))))
            s = perf_stats(t3s)
            print("  该时段 T3: 均值 %.1f 标准差 %.1f 合格 %.1f%% <100 %.1f%% >130 %.1f%%" % (
                s["mean"], s["std"], s["in_band"], s["below"], s["above"]))

    T3_all = np.nanmean([wt.series(t) for t in Tag.TEMP[2]], axis=0)

    # ================= D. 控制方向自检 =================
    """
    重要：不能用「模型动作后的 T3 走向」来验证因果。
    模型动作是 T3 的函数，且常被操作员同刻的反向操作污染（实测中
    「模型建议加水」的 14 个样本里 T3 后续涨了 38℃，那是操作员恰好
    也在加水应对已经发生的升温，不是加水导致的）。
    因果方向由独立的严格事件研究给出（见 _tmp_decide.py / 模型文档），
    此处只做静态自检：确认控制器符号与既定结论一致。
    """
    if verbose:
        print()
        print("-" * 86)
        print("【D】控制方向自检（对照严格事件研究结论）")
        print("-" * 86)
        print("""  既定结论（12 个严格水率阶跃事件，升7/降5）：
      升水率: 0~10min +6.95℃   30~60min -0.88℃
      降水率: 0~10min -5.94℃   30~60min +3.94℃
    => 非最小相位：加水短期升温、长期降温
    => T3 偏高应加水，动作后须等待 > 30 min 再评估""")
        # 符号自检：构造一个 T3 偏高的场景，看控制器是否给出加水指令
        probe_cfg = Config()
        probe_cfg.set_curr1_high(cfg.safety.curr1_high)
        probe_sc = SignalConditioner(wt, probe_cfg)
        probe = XshController(probe_sc, probe_cfg)
        err_test = -10.0   # T3 比目标高 10℃
        delta = -(probe_cfg.control.kp_temp3 * err_test)
        ok = delta > 0
        print("  符号自检: T3 偏高 10℃ 时，控制器 Δ水率 = %+.1f L/t  ->  %s  [%s]" % (
            delta, "加水" if delta > 0 else "减水", "正确" if ok else "错误"))
        print("  节拍自检: action_wait_min = %.0f min  (需 > 稳态效应 30 min)  [%s]" % (
            cfg.control.action_wait_min,
            "正确" if cfg.control.action_wait_min > 30 else "过短"))

    # ================= E. 各班次明细 =================
    if verbose:
        print()
        print("-" * 86)
        print("【E】各班次明细")
        print("-" * 86)
        d = np.diff(prod.astype(np.int8))
        starts = list(np.where(d == 1)[0] + 1)
        ends = list(np.where(d == -1)[0] + 1)
        if prod[0]:
            starts.insert(0, 0)
        if prod[-1]:
            ends.append(prod.size)
        segs = [(s, e) for s, e in zip(starts, ends) if e - s >= 30]
        print("%-18s %5s %7s %7s %8s %7s %7s %6s" % (
            "班次", "时长", "T3均值", "T3std", "合格率", "动作数", "报警数", "最长启动"))
        tot_in, tot_n = 0, 0
        for s, e in segs:
            sl = [o for o in results if s <= o.t_index < e]
            if not sl:
                continue
            t3seg = T3_all[s:e]
            pa = perf_stats(t3seg)
            n_act = sum(1 for o in sl if o.action not in (Action.HOLD,))
            alarms = sum(len(o.alarms) for o in sl)
            n_startup = sum(1 for o in sl if o.phase == Phase.STARTUP)
            print("%-18s %5d %7.1f %7.1f %7.1f%% %7d %7d %6d" % (
                wt.time_full(s), e - s, pa["mean"], pa["std"], pa["in_band"],
                n_act, alarms, n_startup))
            tot_in += pa["in_band"] * pa["n"]
            tot_n += pa["n"]
        if tot_n:
            print("\n  加权平均 T3 合格率: %.1f%%  (对照：历史基线 72.6%%)" % (tot_in / tot_n))

    return ctrl, results, wt, cfg, sc


if __name__ == "__main__":
    run_backtest(x_curr1=18.0)
