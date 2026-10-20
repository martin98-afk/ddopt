# -*- coding: utf-8 -*-
"""
反事实 A/B 仿真。

===== 方法论 =====

之前说"离线无法做反事实仿真"，是指不能直接用历史数据推断。
现在换个办法：**先从数据辨识出过程模型，再用模型做反事实推演**。

  1. 辨识：从 12 个干净水率阶跃事件，得到水率 → T3 的阶跃响应核 g[k]
  2. 拆扰动：把实际 T3 轨迹拆成「水率驱动部分」+「不可解释部分 d」
  3. 反事实：保持 d 不变（共同随机数法），只把水率操作序列换成模型的，
     推演 T3 会怎么走

第 3 步的公平性来自共同随机数：双方面对完全相同的原料批次/环境扰动，
唯一差别是水率操作序列。这才是有效的 A/B。

===== 必须承认的局限 =====

仿真在"自己辨识出的模型"内进行，属于模型内自证。若 g 有偏，
结论就有偏。真实检验仍需现场 A/B：部分班次走模型闭环，部分走人工。
"""
import json
import os
import time

import numpy as np

from data_loader import build_wide
from config import Tag, Config
from signal_conditioning import SignalConditioner
from controller import XshController, Phase, Action

BASE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(BASE, ".cache")
OUT_JSON = os.path.join(BASE, ".cache", "ab_result.json")

KERNEL_LEN = 61          # 阶跃响应核长度（分钟）
SIM_STEP = 1             # 仿真粒度（分钟）
CTRL_PERIOD = 10         # 控制周期（分钟）

T3_TAGS = Tag.TEMP[2]


# --------------------------------------------------------------- 仿真用宽表
class SimTable:
    """
    可写宽表：索引与真实宽表一致。
    T3 三测点、水率设定、生石灰流量可被逐分钟覆盖，其余量一律读真实值
    （T1/T2/电流/料位/permit 是状态与约束，不是被控输出）。

    给料量必须可覆盖：控制器每步以「实际给料量」为基准，
    若不覆盖，它会一路跟着历史实际值走，模型下发值被丢弃，
    降载动作也就无法在轨迹上体现。
    """

    def __init__(self, wt):
        self.wt = wt
        self.grid = wt.grid
        self._ov = {}
        for nm in list(T3_TAGS) + [Tag.RATIO_SD, Tag.RATIO_FK, Tag.LIME]:
            self._ov[nm] = wt.series(nm).copy()

    def set_t3(self, i, v):
        for nm in T3_TAGS:
            self._ov[nm][i] = v

    def set_ratio(self, i, v):
        self._ov[Tag.RATIO_SD][i] = v
        self._ov[Tag.RATIO_FK][i] = v

    def set_lime(self, i, v):
        self._ov[Tag.LIME][i] = v

    def series(self, name):
        if name in self._ov:
            return self._ov[name]
        return self.wt.series(name)

    def __contains__(self, name):
        return True


# --------------------------------------------------------------- 1. 辨识
def collect_events(wt, segs, R, T3, thresh=10.0, quiet_after=25, min_gap=40):
    """收集稳态期内干净的水率设定阶跃事件"""
    PRE, POST = 15, KERNEL_LEN - 1
    ev = []
    for s, e in segs:
        a = s + 120 if e - s > 150 else s + 60
        if e - a < 80:
            continue
        for i in range(a + PRE, e - POST):
            bef, aft = R[i - PRE:i], R[i:i + 5]
            if np.isnan(bef).any() or np.isnan(aft).any():
                continue
            step = aft.mean() - bef.mean()
            if abs(step) < thresh or bef.std() > abs(step) * 0.8:
                continue
            if R[i + 5:i + 5 + quiet_after].std() > abs(step) * 0.8:
                continue
            ev.append((i, step))
    ded, last = [], -999
    for i, st in ev:
        if i - last >= min_gap:
            ded.append((i, st))
            last = i
    return ded


def identify_kernel(wt, segs, R, T3):
    """辨识水率 -> T3 的单位阶跃响应核 g[k] (℃ per L/t)"""
    events = collect_events(wt, segs, R, T3)
    curves, amps, ups, downs = [], [], [], []
    for i, step in events:
        base = np.nanmean(T3[max(0, i - 15):i])
        r = T3[i:i + KERNEL_LEN] - base
        if len(r) < KERNEL_LEN:
            continue
        if step < 0:
            r, step = -r, -step
        curves.append(r / step)
        amps.append(step)
        (ups if step > 0 else downs).append(r / step)
    if not curves:
        return None, 0, [], []
    G = np.mean(curves, axis=0)
    # 轻度平滑（3 点移动平均），抑制事件样本少带来的锯齿
    k = np.array([1.0, 1.0, 1.0]) / 3
    G = np.convolve(G, k, mode="same")
    G[0] = 0.0
    return G, len(curves), ups, downs


# --------------------------------------------------------------- 2. 响应计算
def response(u, G, t):
    """Σ g[k] * Δu[t-k]，Δu 为水率增量"""
    K = len(G)
    lo = max(1, t - K + 1)
    s = 0.0
    for j in range(lo, t + 1):
        k = t - j
        if k < K:
            s += G[k] * (u[j] - u[j - 1])
    return s


def response_fast(u, G, t):
    """向量化版本：用冲激响应与历史输入做点积"""
    K = len(G)
    if t + 1 < K:
        du = np.diff(u[:t + 1])
        g = G[:du.size][::-1]
        return float(np.dot(g, du))
    du = np.diff(u[t - K + 1:t + 1])
    return float(np.dot(G[:du.size][::-1], du))


# --------------------------------------------------------------- 3. A/B 仿真
def run_shift(wt, cfg, s0, e0, G, T3, R, verbose=True):
    """在单个班次 [s0, e0) 上做反事实仿真"""
    n = wt.grid.size

    # 实际水率序列（复制，供响应计算）
    u_act_full = np.where(np.isnan(R), 0.0, R).astype(np.float64)
    # 前推填充 NaN
    for i in range(1, n):
        if np.isnan(R[i]):
            u_act_full[i] = u_act_full[i - 1]

    u_sim = u_act_full.copy()

    # --- 共同扰动 d[t]：实际轨迹中水率解释不了的部分 ---
    base0 = T3[s0]
    resp_act0 = response_fast(u_act_full, G, s0)
    d = np.full(e0 - s0 + 1, np.nan)
    for idx, t in enumerate(range(s0, e0 + 1)):
        if np.isnan(T3[t]):
            continue
        d[idx] = T3[t] - base0 - (response_fast(u_act_full, G, t) - resp_act0)
    d = _ffill_bfill(d)

    # --- 控制器与仿真表 ---
    sim = SimTable(wt)
    sc = SignalConditioner(sim, cfg)
    ctrl = XshController(sc, cfg)

    t3_sim = np.full(e0 - s0 + 1, np.nan)
    ratio_sim = np.full(e0 - s0 + 1, np.nan)
    ratio_act = np.full(e0 - s0 + 1, np.nan)
    lime_sim = np.full(e0 - s0 + 1, np.nan)
    acts = []

    cur_ratio = R[s0] if not np.isnan(R[s0]) else 630.0
    if cur_ratio <= 0:
        cur_ratio = 630.0

    # 给料量：从历史实际值起步，控制器在其上施加降载。
    # 用稳态段前 10 分钟的均值，而不是起点瞬时值 —— 后者会被起点的
    # 偶然波动带偏（实测起点 4.83 vs 整段均值 4.00），
    # 导致模型输出看起来「比人工高」，其实是取值方式造成的假象。
    cur_lime = np.nanmean(wt.series(Tag.LIME)[s0:s0 + 10])
    if np.isnan(cur_lime) or cur_lime <= 0:
        cur_lime = 3.5

    for t in range(s0, e0 + 1):
        # 写入本步水率与给料量（让控制器以模型自己的轨迹为基准）
        sim.set_ratio(t, cur_ratio)
        sim.set_lime(t, cur_lime)
        u_sim[t] = cur_ratio

        # 推演 T3
        v = base0 + (response_fast(u_sim, G, t) - resp_act0) + d[t - s0]
        if not np.isnan(v):
            sim.set_t3(t, v)
            t3_sim[t - s0] = v
        ratio_sim[t - s0] = cur_ratio
        ratio_act[t - s0] = R[t]

        # 控制决策
        if (t - s0) % CTRL_PERIOD == 0:
            out = ctrl.step(t)
            if out.phase != Phase.IDLE and out.action != Action.STOP_FEED:
                cur_ratio = out.ratio_set
                cur_lime = out.lime_set
            acts.append((t - s0, out.action.value, out.ratio_set,
                         out.lime_set, out.reason))
        lime_sim[t - s0] = cur_lime

    return dict(t3_sim=t3_sim, t3_act=T3[s0:e0 + 1].copy(),
                ratio_sim=ratio_sim, ratio_act=ratio_act,
                lime_sim=lime_sim,
                lime_act=wt.series(Tag.LIME)[s0:e0 + 1].copy(),
                d=d[:e0 - s0], acts=acts)


def _ffill_bfill(a):
    out = a.copy()
    m = np.isnan(out)
    if m.all():
        return np.zeros_like(out)
    idx = np.where(~m, np.arange(out.size), 0)
    np.maximum.accumulate(idx, out=idx)
    out[m] = out[idx[m]]
    return out


# --------------------------------------------------------------- 指标
def metrics(t3, lo=100.0, hi=130.0):
    v = np.asarray(t3, dtype=np.float64)
    v = v[~np.isnan(v)]
    if v.size == 0:
        return dict(n=0, mean=np.nan, std=np.nan, in_band=np.nan,
                    below=np.nan, above=np.nan, max_=np.nan, min_=np.nan)
    return dict(n=int(v.size), mean=float(v.mean()), std=float(v.std()),
                in_band=float(100 * np.mean((v >= lo) & (v <= hi))),
                below=float(100 * np.mean(v < lo)),
                above=float(100 * np.mean(v > hi)),
                max_=float(v.max()), min_=float(v.min()))


def main():
    t_start = time.time()
    wt = build_wide(verbose=False)
    R = wt.series(Tag.RATIO_SD)
    T3 = np.nanmean([wt.series(t) for t in T3_TAGS], axis=0)
    perm = wt.series(Tag.PERMIT) > 0.5

    d = np.diff(perm.astype(np.int8))
    starts = list(np.where(d == 1)[0] + 1)
    ends = list(np.where(d == -1)[0] + 1)
    if perm[0]:
        starts.insert(0, 0)
    if perm[-1]:
        ends.append(perm.size)
    segs = [(s, e) for s, e in zip(starts, ends) if e - s >= 30]

    print("=" * 84)
    print("反事实 A/B 仿真")
    print("=" * 84)

    # ---- 1. 辨识 ----
    G, n_ev, ups, downs = identify_kernel(wt, segs, R, T3)
    if G is None:
        print("辨识失败：无有效阶跃事件")
        return
    print("\n[1] 阶跃响应核辨识：%d 个事件" % n_ev)
    print("    单位阶跃响应 g[k] (℃ per L/t)，选点：")
    for k in [0, 5, 10, 15, 20, 25, 30, 40, 50, 60]:
        print("      k=%2d min : %+.4f  (即 +100 L/t -> %+.2f ℃)" % (
            k, G[k], G[k] * 100))
    print("    最终稳态增益 g[60] = %+.4f ℃/(L/t) = %+.2f ℃ per +100 L/t" % (
        G[60], G[60] * 100))
    print("    峰值（反向）%+.2f ℃ per +100 L/t @ k=%d" % (
        G.max() * 100, int(np.argmax(G))))

    # ---- 2. 逐班次 A/B ----
    print("\n[2] 逐班次反事实仿真（稳态段，共同扰动）")
    print("-" * 84)
    print("%-18s %6s | %7s %7s %8s | %7s %7s %8s" % (
        "班次", "时长", "人工T3", "人工std", "人工合格", "模型T3", "模型std", "模型合格"))

    results = []
    for s, e in segs:
        # 从稳态起点开始（跳过启动爬温）
        s0 = s + 120 if e - s > 150 else s + 60
        if e - s0 < 90:
            continue
        cfg = Config()
        cfg.set_curr1_high(18.0)
        r = run_shift(wt, cfg, s0, e - 1, G, T3, R)
        ma = metrics(r["t3_act"])
        ms = metrics(r["t3_sim"])
        import time as _t
        results.append(dict(
            label=_t.strftime("%m-%d %H:%M", _t.localtime(wt.grid[s0])),
            t0=s0, t1=e,
            t3_act=r["t3_act"], t3_sim=r["t3_sim"],
            ratio_act=r["ratio_act"], ratio_sim=r["ratio_sim"],
            m_act=ma, m_sim=ms, acts=r["acts"],
        ))
        print("%-18s %6d | %7.1f %7.1f %7.1f%% | %7.1f %7.1f %7.1f%%" % (
            results[-1]["label"], e - s0, ma["mean"], ma["std"], ma["in_band"],
            ms["mean"], ms["std"], ms["in_band"]))

    # ---- 3. 汇总 ----
    print("\n[3] 汇总")
    print("-" * 84)
    tot_act = tot_sim = tot_n = 0
    for r in results:
        tot_act += r["m_act"]["in_band"] * r["m_act"]["n"]
        tot_sim += r["m_sim"]["in_band"] * r["m_sim"]["n"]
        tot_n += r["m_act"]["n"]
    print("样本 %d 分钟" % tot_n)
    print("  人工 T3 合格率 %.1f%%   模型 T3 合格率 %.1f%%   提升 %+.1f 个百分点" % (
        tot_act / tot_n, tot_sim / tot_n, (tot_sim - tot_act) / tot_n))

    all_act = np.concatenate([r["t3_act"] for r in results])
    all_sim = np.concatenate([r["t3_sim"] for r in results])
    all_act = all_act[~np.isnan(all_act)]
    all_sim = all_sim[~np.isnan(all_sim)]
    print("  人工 T3 标准差 %.2f    模型 T3 标准差 %.2f" % (
        all_act.std(), all_sim.std()))
    print("  人工 >130 占比 %.1f%%    模型 >130 占比 %.1f%%" % (
        100 * np.mean(all_act > 130), 100 * np.mean(all_sim > 130)))
    print("  人工 <100 占比 %.1f%%    模型 <100 占比 %.1f%%" % (
        100 * np.mean(all_act < 100), 100 * np.mean(all_sim < 100)))

    # ---- 4. 保存（降采样到 5 分钟，供 HTML）----
    os.makedirs(CACHE, exist_ok=True)
    payload = {
        "kernel": [float(x) for x in G],
        "kernel_events": n_ev,
        "shifts": [],
        "summary": {
            "act_in_band": tot_act / tot_n, "sim_in_band": tot_sim / tot_n,
            "act_std": float(all_act.std()), "sim_std": float(all_sim.std()),
            "act_above": 100 * float(np.mean(all_act > 130)),
            "sim_above": 100 * float(np.mean(all_sim > 130)),
            "act_below": 100 * float(np.mean(all_act < 100)),
            "sim_below": 100 * float(np.mean(all_sim < 100)),
            "n": tot_n,
        },
    }
    for r in results:
        step = 5
        idx = list(range(0, len(r["t3_act"]), step))
        payload["shifts"].append({
            "label": r["label"],
            "t": idx,
            "t3_act": [None if np.isnan(r["t3_act"][i]) else round(float(r["t3_act"][i]), 1)
                       for i in idx],
            "t3_sim": [None if np.isnan(r["t3_sim"][i]) else round(float(r["t3_sim"][i]), 1)
                       for i in idx],
            "r_act": [None if np.isnan(r["ratio_act"][i]) else round(float(r["ratio_act"][i]), 0)
                      for i in idx],
            "r_sim": [None if np.isnan(r["ratio_sim"][i]) else round(float(r["ratio_sim"][i]), 0)
                      for i in idx],
            "m_act": r["m_act"], "m_sim": r["m_sim"],
            "n_act": sum(1 for a in r["acts"]),
        })
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)
    print("\n结果已保存: %s (%.1fs)" % (OUT_JSON, time.time() - t_start))


if __name__ == "__main__":
    main()
