# -*- coding: utf-8 -*-
"""FOPDT+DMC vs 现行规则控制器 vs 人工：同一仿真环境对比实验。

环境：复用 模型/ab_test 的框架——
  真对象   水率阶跃事件辨识出的响应核 G（61 min，含非最小相位）
  共同扰动 d[t] = 实际 T3 − base0 − G∘(实际水率)，双方面对同一 d[t]
  闭环     每分钟推演 T3，每 10 分钟一拍控制

对比三方（指标口径一致：T3∈[100,130] 合格率、动作次数、稳态 std）：
  1. 人工       实际水率轨迹（不干预）
  2. 规则控制器 模型/ 现行版本（守护带 + 水率优先 + 35min 节拍）
  3. FOPDT+DMC  响应核拟合 FOPDT(K,τ,θ) → 最小 DMC（解析解）

用法：python run_experiment.py
"""
from __future__ import annotations

import os
import sys
import time as _t

import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
_MODEL = os.path.join(_HERE, "..", "模型")
for p in (_HERE, _MODEL):
    if p not in sys.path:
        sys.path.insert(0, p)

from data_loader import build_wide
from config import Tag, Config
from signal_conditioning import SignalConditioner
from controller import XshController
from ab_test import CTRL_PERIOD, SimTable, collect_events, identify_kernel, \
    response_fast
from fopdt import fit_fopdt_from_kernel
from dmc import DMCController

T3_TAGS = Tag.TEMP[2]
SP = 118.0

# ---- 真对象响应核（10-12~10-19 的 12 个阶跃事件辨识，README 权威口径）----
# 前段为正（加水先升 ~+4.7℃/100L/t @5min），k≈16 过零，最深 −0.322 @28min，
# 稳态 −0.151 ℃/(L/t)。与 模型/validate_new.py 的 G_OLD 同源。
G_OLD = np.array([
    0.0000, 0.3595, 0.3970, 0.4299, 0.4532, 0.4675, 0.4663, 0.4529,
    0.4239, 0.3845, 0.3327, 0.2730, 0.2099, 0.1506, 0.0984, 0.0430,
    -0.0137, -0.0689, -0.1124, -0.1521, -0.1841, -0.2155, -0.2390, -0.2612,
    -0.2799, -0.2945, -0.3098, -0.3175, -0.3224, -0.3222, -0.3190, -0.3203,
    -0.3213, -0.3254, -0.3236, -0.3176, -0.3091, -0.2973, -0.2856, -0.2745,
    -0.2679, -0.2532, -0.2401, -0.2283, -0.2272, -0.2275, -0.2266, -0.2264,
    -0.2253, -0.2260, -0.2304, -0.2386, -0.2485, -0.2559, -0.2579, -0.2539,
    -0.2458, -0.2323, -0.2270, -0.2229, -0.1510])


# --------------------------------------------------------------- 响应核尾部延伸
def extend_kernel(G: np.ndarray, total_min: int):
    """把响应核尾部用稳态增益 G[-1] 延伸到 total_min+1 长。

    为什么必须：原 KERNEL_LEN=61 的 FIR 截断会让阶跃的**稳态效应在
    仿真里 61 分钟后被洗掉**（水率差 40 L/t 的稳态温差 +6℃ 凭空消失），
    导致不同水率策略的 T3 轨迹在稳态段虚假重合。
    """
    G = np.asarray(G, float)
    if total_min + 1 <= len(G):
        return G
    return np.concatenate([G, np.full(total_min + 1 - len(G), G[-1])])


# --------------------------------------------------------------- 共同扰动提取
def extract_common_disturbance(wt, s0, e0, G, T3, R, u_sim_base):
    """d[t] = T3[t] − base0 − (G∘u − G∘u[s0])，双方面对同一 d"""
    base0 = T3[s0]
    resp_act0 = response_fast(u_sim_base, G, s0)
    d = np.full(e0 - s0 + 1, np.nan)
    for idx, t in enumerate(range(s0, e0 + 1)):
        if not np.isnan(T3[t]):
            d[idx] = T3[t] - base0 - (response_fast(u_sim_base, G, t) - resp_act0)
    for i in range(1, len(d)):
        if np.isnan(d[i]):
            d[i] = d[i - 1]
    for i in range(len(d) - 2, -1, -1):
        if np.isnan(d[i]):
            d[i] = d[i + 1]
    return base0, resp_act0, d


def _prep(wt, s0, e0, R):
    """实际水率的前推填充序列（响应计算用）"""
    n = wt.grid.size
    u = np.where(np.isnan(R), 0.0, R).astype(np.float64)
    for i in range(1, n):
        if np.isnan(R[i]):
            u[i] = u[i - 1]
    return u


# --------------------------------------------------------------- 规则控制器闭环
def run_shift_rule(wt, cfg, s0, e0, G, T3, R):
    """现行规则控制器（守护带 + 水率优先 + 节拍）在同一环境闭环"""
    u_base = _prep(wt, s0, e0, R)
    u_sim = u_base.copy()
    base0, resp_act0, d = extract_common_disturbance(wt, s0, e0, G, T3, R, u_base)

    sim = SimTable(wt)
    sc = SignalConditioner(sim, cfg)
    ctrl = XshController(sc, cfg)

    t3_sim = np.full(e0 - s0 + 1, np.nan)
    ratio_sim = np.full(e0 - s0 + 1, np.nan)
    acts = []
    log = []      # (t-s0, 滑动T3评估值, action.value, ratio)

    cur_ratio = R[s0] if not np.isnan(R[s0]) and R[s0] > 0 else 630.0
    cur_lime = float(np.nanmean(wt.series(Tag.LIME)[s0:s0 + 10]))
    if np.isnan(cur_lime) or cur_lime <= 0:
        cur_lime = 3.5

    for t in range(s0, e0 + 1):
        sim.set_ratio(t, cur_ratio)
        sim.set_lime(t, cur_lime)
        u_sim[t] = cur_ratio
        v = base0 + (response_fast(u_sim, G, t) - resp_act0) + d[t - s0]
        if not np.isnan(v):
            sim.set_t3(t, v)
            t3_sim[t - s0] = v
        ratio_sim[t - s0] = cur_ratio
        if (t - s0) % CTRL_PERIOD == 0:
            out = ctrl.step(t)
            cur_ratio = out.ratio_set
            tv = out.temp3 if not np.isnan(out.temp3) else float("nan")
            log.append((t - s0, tv, out.action.value, cur_ratio))
    return dict(t3_sim=t3_sim, ratio_sim=ratio_sim, acts=acts, log=log)


# --------------------------------------------------------------- FOPDT+DMC 闭环
def run_shift_dmc(wt, s0, e0, G, T3, R, K, tau, theta, lam=0.1):
    """FOPDT+DMC 在同一环境闭环"""
    u_base = _prep(wt, s0, e0, R)
    u_sim = u_base.copy()
    base0, resp_act0, d = extract_common_disturbance(wt, s0, e0, G, T3, R, u_base)

    sim = SimTable(wt)
    u0 = float(R[s0]) if not np.isnan(R[s0]) and R[s0] > 0 else 630.0
    dmc = DMCController(K=K, tau=tau, theta=theta, sp=SP, lam=lam, u_init=u0)

    t3_sim = np.full(e0 - s0 + 1, np.nan)
    ratio_sim = np.full(e0 - s0 + 1, np.nan)
    acts = []
    cur_ratio = u0

    for t in range(s0, e0 + 1):
        sim.set_ratio(t, cur_ratio)
        u_sim[t] = cur_ratio
        v = base0 + (response_fast(u_sim, G, t) - resp_act0) + d[t - s0]
        if not np.isnan(v):
            sim.set_t3(t, v)
            t3_sim[t - s0] = v
        ratio_sim[t - s0] = cur_ratio
        if (t - s0) % CTRL_PERIOD == 0 and not np.isnan(v):
            new_u = dmc.step(v)
            if abs(new_u - cur_ratio) >= 2.0:
                acts.append(t - s0)
            cur_ratio = new_u
    return dict(t3_sim=t3_sim, ratio_sim=ratio_sim, acts=acts)


# --------------------------------------------------------------- 指标
def metrics(t3, ratio, lo=100.0, hi=130.0):
    v = np.asarray(t3, float)
    ok = ~np.isnan(v)
    v = v[ok]
    r = np.asarray(ratio, float)[ok]
    moves = int(np.sum(np.abs(np.diff(r)) >= 2.0)) if r.size > 1 else 0
    return dict(rate=float(np.mean((v >= lo) & (v <= hi)) * 100.0) if v.size else 0.0,
                std=float(np.std(v)) if v.size else 0.0,
                moves=moves, n=int(v.size))


def main():
    print("=" * 88)
    print("FOPDT+DMC vs 现行规则控制器 vs 人工（响应核真对象 + 共同扰动）")
    print("=" * 88)
    wt = build_wide(verbose=False)
    R = wt.series(Tag.RATIO_SD)
    T3 = np.nanmean([wt.series(t) for t in T3_TAGS], axis=0)
    perm = wt.series(Tag.PERMIT) > 0.5

    # 班次切分：与 ab_test 同口径
    d = np.diff(perm.astype(np.int8))
    starts = list(np.where(d == 1)[0] + 1)
    ends = list(np.where(d == -1)[0] + 1)
    if perm[0]:
        starts.insert(0, 0)
    if perm[-1]:
        ends.append(perm.size)
    segs = [(s, e) for s, e in zip(starts, ends) if e - s >= 150]

    # ---- 响应核（真对象）----
    # 现场重辨识对照：当前宽表数据与 README 时代不同，仅 2 个事件且形状
    # 不可信（稳态 −0.84 vs 权威 −0.151），故真对象用 G_OLD。
    # 另：原 61 分钟 FIR 截断会把水率阶跃的稳态效应在仿真里洗掉
    # （不同策略的 T3 轨迹稳态段虚假重合），已做尾部稳态延伸。
    G_chk, n_ev_chk, _, _ = identify_kernel(wt, segs, R, T3)
    print("\n[1a] 现场重辨识对照：%d 个事件，稳态 g[60]=%+.4f（数据口径已变，不采用）"
          % (n_ev_chk, G_chk[-1] if G_chk is not None else float("nan")))
    span = max(e - s for s, e in segs)
    G = extend_kernel(G_OLD, span + 61)
    print("\n[1b] 真对象 = G_OLD（权威核）+ 尾部稳态延伸至 %d min，"
          "稳态增益 %+.4f ℃/(L/t)" % (len(G), G[-1]))
    for k in (0, 5, 10, 15, 20, 28, 40, 60):
        print("    k=%2d min : %+.4f  (即 +100 L/t -> %+.2f ℃)" % (k, G[k], G[k] * 100))

    # ---- FOPDT 拟合 ----
    f = fit_fopdt_from_kernel(G, Ts=1.0)
    print("\n[2] FOPDT 拟合（响应核 → K,τ,θ）：")
    print("    K=%+.4f ℃/(L/t)  τ=%.1f min  θ=%.0f min  R²=%.3f  RMSE=%.4f"
          % (f["K"], f["tau"], f["theta"], f["r2"], f["rmse"]))
    print("    ⚠ 非最小相位：核峰值 %+.2f℃/100L/t @%dmin（先升后降），"
          "FOPDT 单调响应无法表达，前段全部落入残差"
          % (G.max() * 100, int(np.argmax(G))))

    # ---- 三方对比，逐班次 ----
    cfg = Config()
    print("\n[3] 班次对比（共同扰动 d[t]，控制周期 %d min）：" % CTRL_PERIOD)
    header = "%-17s %5s | %6s %6s %4s | %6s %6s %4s | %6s %6s %4s" % (
        "班次", "分钟",
        "人工%", "人工σ", "动次",
        "规则%", "规则σ", "动次",
        "DMC%", "DMCσ", "动次")
    print(header)
    print("-" * len(header))
    agg = {"act": [], "rule": [], "dmc": []}
    for s0, e0 in segs:
        r_rule = run_shift_rule(wt, cfg, s0, e0, G, T3, R)
        r_dmc = run_shift_dmc(wt, s0, e0, G, T3, R, f["K"], f["tau"],
                              f["theta"], lam=0.1)
        if len(segs) == 1:
            # 单班次：打印规则控制器逐拍决策（启动段 + 首次超标段附近），
            # 回答「T3 超 130 为什么没加水」
            print("\n    规则控制器逐拍（滑动 T3 评估值 = 15min 滑动中位）：")
            print("    %-6s %-8s %-10s %-7s" % ("拍(min)", "T3评估", "动作", "水率"))
            shown = 0
            for (tt, tv, act, rr) in r_rule["log"]:
                peak = tt <= 90 or (100 <= tt <= 200)
                if shown < 12 or (peak and shown < 24):
                    tv_s = "%.1f" % tv if tv == tv else "nan"
                    print("    %-6d %-8s %-10s %-7.0f" % (tt, tv_s, act, rr))
                    shown += 1
        m_act = metrics(T3[s0:e0 + 1], R[s0:e0 + 1])
        m_rule = metrics(r_rule["t3_sim"], r_rule["ratio_sim"])
        m_dmc = metrics(r_dmc["t3_sim"], r_dmc["ratio_sim"])
        agg["act"].append(m_act)
        agg["rule"].append(m_rule)
        agg["dmc"].append(m_dmc)
        ts = _t.strftime("%m-%d %H:%M", _t.localtime(wt.grid[s0]))
        print("%-17s %5d | %5.1f %6.2f %4d | %5.1f %6.2f %4d | %5.1f %6.2f %4d"
              % (ts, e0 - s0,
                 m_act["rate"], m_act["std"], m_act["moves"],
                 m_rule["rate"], m_rule["std"], m_rule["moves"],
                 m_dmc["rate"], m_dmc["std"], m_dmc["moves"]))

    def wavg(key, field):
        tot = sum(m["n"] for m in agg[key]) or 1
        return sum(m[field] * m["n"] for m in agg[key]) / tot

    print("-" * len(header))
    print("%-17s %5s | %5.1f %6.2f %4d | %5.1f %6.2f %4d | %5.1f %6.2f %4d"
          % ("加权平均", "",
             wavg("act", "rate"), wavg("act", "std"),
             sum(m["moves"] for m in agg["act"]),
             wavg("rule", "rate"), wavg("rule", "std"),
             sum(m["moves"] for m in agg["rule"]),
             wavg("dmc", "rate"), wavg("dmc", "std"),
             sum(m["moves"] for m in agg["dmc"])))

    # ---- DMC 诊断：水率轨迹 + λ 敏感性 ----
    print("\n[4] DMC 诊断（单班次 %s）：" % ("仅 1 个" if len(segs) == 1 else "各班次"))
    r_dmc0 = run_shift_dmc(wt, *segs[0], G, T3, R, f["K"], f["tau"],
                           f["theta"], lam=0.1)
    rr = r_dmc0["ratio_sim"]
    print("    DMC 水率轨迹范围 [%.0f, %.0f]（操作带 [570,690]），末值 %.0f"
          % (np.nanmin(rr), np.nanmax(rr), rr[~np.isnan(rr)][-1]))
    print("    %-8s | %6s %6s %4s" % ("λ", "DMC%", "DMCσ", "动次"))
    for lam in (0.01, 0.1, 1.0, 10.0):
        r = run_shift_dmc(wt, *segs[0], G, T3, R, f["K"], f["tau"],
                          f["theta"], lam=lam)
        m = metrics(r["t3_sim"], r["ratio_sim"])
        print("    %-8.2f | %5.1f %6.2f %4d" % (lam, m["rate"], m["std"], m["moves"]))

    print("""
说明：
  · 真对象 = 响应核 G（含非最小相位：加水先升后降），FOPDT 拟合不到的
    前段反向响应就是 DMC 的内生模型失配——这正是本实验要量化的东西
  · 三方共用同一扰动 d[t]，差别只在操作序列（共同随机数法）
  · 合格率口径 T3∈[100,130]℃；动次 = 水率变化 ≥2 L/t 的分钟数""")


if __name__ == "__main__":
    main()
