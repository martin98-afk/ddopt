# -*- coding: utf-8 -*-
"""
用 D:/work/脱硫脱硝/data/脱硫脱硝消石灰制备数据 验证当前模型。

注意：这批数据（10-12 ~ 10-19，8 班次，3079 生产分钟）正是模型标定集，
      因此本脚本是**样本内验证**，只能检验一致性/合规性/假设成立性，
      不能证明泛化能力。

四层验证，从「弱依赖模型假设」到「强依赖模型假设」排列：
  [0] 数据体检       —— 工况覆盖：模型有没有机会发挥作用
  [1] 假设检验       —— 水率→T3 的方向与量级，是否支持控制器设计
  [2] 控制器回放     —— 真实数据逐分钟喂控制器，查安全越界与动作触发
                        （回放读人工水率作基值，输出必然贴近人工，只验合规）
  [3] 反事实闭环     —— 自持水率 + 共同扰动 + 响应核推演，对比人工与恒定水率空白对照
                        （强依赖响应核，属模型内自证，结论需打折）
  [4] 消融           —— 快通道开关、响应核换用物理纯滞后核，分离参数贡献
  [5] 工况对照       —— 工艺需求（T2 应最高、T3 在 100~130）在数据里的实现度
"""
from __future__ import annotations

import os
import sys
import time
from collections import Counter

import numpy as np

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

DATA_DIR = r"D:/work/脱硫脱硝/data/脱硫脱硝消石灰制备数据"

import data_loader                                              # noqa: E402
data_loader.DATA_DIR = DATA_DIR
data_loader.CACHE_DIR = os.path.join(BASE, ".cache_old")

from config import Tag, Config                                  # noqa: E402
from signal_conditioning import SignalConditioner                # noqa: E402
from controller import XshController, Phase, Action              # noqa: E402
from ab_auto import AutoTable, response_fast, G_OLD              # noqa: E402

LO, HI = 100.0, 130.0

# 物理纯滞后冷却核：10min 输运死时间 + 8min 一阶惯性，稳态 -0.15 ℃/(L/t)。
# 与 G_OLD 的唯一差别是去掉了 +0.47 的早期反向峰（水率↑ → T3↑）。
K_LEN = 61
G_PURE = np.array([-0.15 * (1.0 - np.exp(-max(0, k - 10) / 8.0))
                   for k in range(K_LEN)])


# ---------------------------------------------------------------- 工具
def t3_series(wt):
    """T3 聚合：先剔除 >250℃ 的仪表异常点，再取均值"""
    a = np.vstack([wt.series(t) for t in Tag.TEMP[2]]).astype(float)
    a[a > 250.0] = np.nan
    with np.errstate(invalid="ignore"):
        return np.nanmean(a, axis=0)


def t3_inst(wt):
    """T3 瞬时聚合（中位），用于快通道越线率统计"""
    a = np.vstack([wt.series(t) for t in Tag.TEMP[2]]).astype(float)
    a[a > 250.0] = np.nan
    with np.errstate(invalid="ignore"):
        return np.nanmedian(a, axis=0)


def seg_list(perm, min_len=30):
    n = perm.size
    d = np.diff(perm.astype(np.int8))
    s = list(np.where(d == 1)[0] + 1)
    e = list(np.where(d == -1)[0] + 1)
    if perm[0]:
        s.insert(0, 0)
    if perm[-1]:
        e.append(n)
    return [(a, b) for a, b in zip(s, e) if b - a >= min_len]


def band_stats(v):
    v = np.asarray(v, float)
    v = v[~np.isnan(v)]
    if v.size == 0:
        return dict(n=0, mean=np.nan, std=np.nan, ok=np.nan, hi=np.nan, lo=np.nan)
    return dict(n=v.size, mean=float(v.mean()), std=float(v.std()),
                ok=float(100 * np.mean((v >= LO) & (v <= HI))),
                hi=float(100 * np.mean(v > HI)),
                lo=float(100 * np.mean(v < LO)))


# ---------------------------------------------------------------- [0] 数据体检
def stage0(wt, perm, T3, T3i, R, L, C1):
    n = wt.grid.size
    print("=" * 100)
    print("[0] 数据体检")
    print("=" * 100)
    print("跨度 %s ~ %s   %d 分钟   测点 %d" % (
        time.strftime("%Y-%m-%d %H:%M", time.localtime(wt.grid[0])),
        time.strftime("%Y-%m-%d %H:%M", time.localtime(wt.grid[-1])),
        n, len(wt.cols)))
    segs = seg_list(perm)
    print("生产判据：允许信号=1 与 给料>0.1 吻合 %d/%d" % (
        int(np.sum(perm)), int(np.sum(wt.series(Tag.PERMIT) > 0.5))))
    print("生产分钟 %d（%.1f h），班次 %d 个" % (
        int(perm.sum()), perm.sum() / 60.0, len(segs)))
    print()
    print("%-14s %5s %7s %7s %7s %7s %8s %11s %6s %6s" % (
        "班次", "min", "T3均", "T3std", ">130%", "<100%", "瞬>135%", "水率范围", "给料", "I1max"))
    for s, e in segs:
        st = band_stats(T3[s:e])
        r = R[s:e]
        r = r[~np.isnan(r)]
        l = L[s:e]
        l = l[~np.isnan(l)]
        c = C1[s:e]
        c = c[~np.isnan(c)]
        print("%-14s %5d %7.1f %7.1f %6.1f%% %6.1f%% %7.1f%% %5.0f~%-5.0f %6.2f %6.2f" % (
            time.strftime("%m-%d %H:%M", time.localtime(wt.grid[s])), e - s,
            st["mean"], st["std"], st["hi"], st["lo"],
            100 * np.nanmean(T3i[s:e] > 135),
            r.min() if r.size else -1, r.max() if r.size else -1,
            l.mean() if l.size else -1, c.max() if c.size else -1))

    tot = band_stats(T3[perm])
    okc = C1[perm]
    okc = okc[~np.isnan(okc)]
    print()
    print("生产段合计：T3 合格 %.1f%%  >130 %.1f%%  <100 %.1f%%  均值 %.1f" % (
        tot["ok"], tot["hi"], tot["lo"], tot["mean"]))
    print("L1 电流：均值 %.2f  P99 %.2f  最大 %.2f  >X(18) %.2f%%" % (
        okc.mean(), np.percentile(okc, 99), okc.max(), 100 * np.mean(okc >= 18)))
    binlv = wt.series(Tag.BIN_HIGH)[perm]
    print("消石灰料位：≥7.0m 占生产分钟 %.1f%%（模型被外部停料的机会）" % (
        100 * np.nanmean(binlv >= 7.0)))
    return segs, tot


# ---------------------------------------------------------------- [1] 假设检验
def _slope(y):
    y = np.asarray(y, float)
    m = ~np.isnan(y)
    if m.sum() < 5:
        return 0.0
    x = np.arange(y.size)[m]
    return float(np.polyfit(x, y[m], 1)[0])


def stage1(segs, R, T3, thresh=10.0, pre=15, post=60, quiet=25, gap=40):
    print()
    print("=" * 100)
    print("[1] 假设检验：水率 → T3 的方向与量级")
    print("=" * 100)
    print("模型设计前提：加水 → T3 降温（稳态增益 -0.151 ℃/(L/t)，滞后约 30min）")
    print("README 已标注：'动作后 0~10min 先升温' 疑似事件研究伪影，此处用趋势校正复检。")
    print()

    ev = []
    for s, e in segs:
        a = s + 120 if e - s > 150 else s + 60
        if e - a < 100:
            continue
        for i in range(a + pre, e - post):
            bef = R[i - pre:i]
            aft = R[i:i + 5]
            if np.isnan(bef).any() or np.isnan(aft).any():
                continue
            step = aft.mean() - bef.mean()
            if abs(step) < thresh or bef.std() > abs(step) * 0.8:
                continue
            if np.isnan(R[i + 5:i + 5 + quiet]).any():
                continue
            if R[i + 5:i + 5 + quiet].std() > abs(step) * 0.8:
                continue
            ev.append((i, float(step)))
    ded, last = [], -999
    for i, st in ev:
        if i - last >= gap:
            ded.append((i, st))
            last = i
    ev = ded

    wins = [(0, 5), (5, 15), (15, 30), (30, 60)]
    raw_up, raw_dn, adj_up, adj_dn = [], [], [], []
    rows = []
    for i, step in ev:
        if i + max(p for _, p in wins) >= T3.size:
            continue
        base = np.nanmean(T3[max(0, i - pre):i])
        y_pre = T3[max(0, i - 20):i]
        sl = _slope(y_pre)
        sign = 1.0 if step > 0 else -1.0
        r_raw, r_adj = [], []
        for k0, k1 in wins:
            seg = T3[i + k0:i + k1]
            r_raw.append(sign * float(np.nanmean(seg) - base))
            # 趋势校正：用事件前斜率外推作反事实基线
            n_off = np.arange(k0, k1) + 1
            ctr = float(np.nanmean(base + sl * n_off))
            r_adj.append(sign * float(np.nanmean(seg) - ctr))
        rows.append((i, step, base, sl * 10, r_raw, r_adj))
        (raw_up if step > 0 else raw_dn).append(r_raw)
        (adj_up if step > 0 else adj_dn).append(r_adj)

    print("干净事件 %d 个（升 %d / 降 %d），阈值 ±%.0f L/t" % (
        len(ev), len(raw_up), len(raw_dn), thresh))
    print()
    print("%-14s %7s %7s %8s | %8s %8s %8s %8s" % (
        "事件", "Δ水率", "基线T3", "前趋势", "+0~5", "+5~15", "+15~30", "+30~60"))
    print("-" * 100)
    for i, step, base, sl10, r_raw, r_adj in rows:
        print("%-14s %+7.1f %7.1f %+8.1f | %+8.1f %+8.1f %+8.1f %+8.1f" % (
            time.strftime("%m-%d %H:%M", time.localtime(_grid[i])),
            step, base, sl10, *r_raw))
    print()
    print("统一折算为「加水」方向（降水事件取反），相对事件前基线：")
    print("%-12s %10s %10s %10s %10s" % ("方法", "0~5min", "5~15min", "15~30min", "30~60min"))
    for label, grp in [("原始·升水组", raw_up), ("原始·降水组", raw_dn),
                       ("趋势校正·升水组", adj_up), ("趋势校正·降水组", adj_dn)]:
        if not grp:
            continue
        a = np.array(grp)
        print("%-12s %+10.2f %+10.2f %+10.2f %+10.2f" % (
            label, *[float(np.nanmean(a[:, k])) for k in range(len(wins))]))
    a = np.array(raw_up + raw_dn)
    print("%-12s %+10.2f %+10.2f %+10.2f %+10.2f" % (
        "原始·合并", *[float(np.nanmean(a[:, k])) for k in range(len(wins))]))
    a = np.array(adj_up + adj_dn)
    print("%-12s %+10.2f %+10.2f %+10.2f %+10.2f" % (
        "趋势校正·合并", *[float(np.nanmean(a[:, k])) for k in range(len(wins))]))
    print()
    # 稳态回归：生产段 T3 ~ 水率（小时粒度去自相关）
    m = np.zeros(T3.size, bool)
    for s, e in segs:
        m[s:e] = True
    rr, tt = R[m], T3[m]
    ok = ~np.isnan(rr) & ~np.isnan(tt)
    if ok.sum() > 30:
        k, b = np.polyfit(rr[ok], tt[ok], 1)
        res = tt[ok] - (k * rr[ok] + b)
        print("稳态回归（生产段逐分钟，含班次间差异）：T3 = %.1f %+.4f × 水率   R² = %.3f   n=%d" % (
            b, k, 1 - res.var() / tt[ok].var(), ok.sum()))

    # 班次内去均值回归：剥离原料批次等班次间差异，看净增益
    xs, ys = [], []
    for s, e in segs:
        mm = np.zeros(T3.size, bool)
        mm[s:e] = True
        o = mm & ~np.isnan(T3) & ~np.isnan(R)
        if o.sum() < 50 or np.nanstd(R[o]) < 1.0:
            continue
        xs.append(R[o] - R[o].mean())
        ys.append(T3[o] - T3[o].mean())
    if xs:
        x, y = np.concatenate(xs), np.concatenate(ys)
        if np.dot(x, x) > 0:
            k2 = float(np.dot(x, y) / np.dot(x, x))
            r2 = 1 - (y - k2 * x).var() / y.var()
            print("班次内去均值回归（剥离批次差异）：T3 = %+.4f × 水率   R² = %.3f   n=%d" % (
                k2, r2, x.size))
            print("  → 模型设定增益 -0.151 ℃/(L/t)，实测净增益 %+.4f" % k2)

    # 滞后互相关：正 lag = 水率先动、T3 后动（因果方向）；负 lag 大 = T3 先动、人工后调水（反馈）
    # 逐班次计算后平均，避免跨班次边界拼接污染
    zs, ys_ = [], []
    for s, e in segs:
        o = np.zeros(T3.size, bool)
        o[s:e] = True
        o &= ~np.isnan(T3) & ~np.isnan(R)
        if o.sum() < 100 or np.nanstd(R[o]) < 1.0:
            continue
        x = R[o] - R[o].mean()
        y = T3[o] - T3[o].mean()
        t = np.arange(x.size)
        x = x - np.polyval(np.polyfit(t, x, 1), t)
        y = y - np.polyval(np.polyfit(t, y, 1), t)
        if x.std() < 1e-6 or y.std() < 1e-6:
            continue
        zs.append(x / x.std())
        ys_.append(y / y.std())

    if zs:
        lags = (-40, -20, -10, -5, 0, 5, 10, 15, 20, 30, 40)
        acc = {k: [] for k in lags}
        for x, y in zip(zs, ys_):
            n = x.size
            for lag in lags:
                # corr(x[t], y[t+lag])：lag<0 取 x 后段配 y 前段
                a = x[-lag:] if lag < 0 else x[:n - lag] if lag > 0 else x
                b2 = y[:n + lag] if lag < 0 else y[lag:] if lag > 0 else y
                if a.size > 30:
                    acc[lag].append(float(np.corrcoef(a, b2)[0, 1]))
        print()
        print("滞后互相关 corr(水率[t], T3[t+lag])，班次内去均值去趋势，%d 班次平均：" % len(zs))
        print("  lag<0 = T3 先变、操作员后调水（反馈）；lag>0 = 水率先变（因果）")
        print("  " + "  ".join("%+d:%+.2f" % (k, float(np.nanmean(acc[k]))) for k in lags))
        c_neg = max(abs(float(np.nanmean(acc[k]))) for k in (-5, -10, -20))
        c_pos = max(abs(float(np.nanmean(acc[k]))) for k in (10, 20, 30))
        print("  峰值 |corr|：lag<0 %.2f vs lag>0 %.2f → 相关主体在 %s" % (
            c_neg, c_pos, "反馈方向（T3 先动、人工后调水）" if c_neg > c_pos
            else "因果方向（水率先动、T3 后动）"))
    return rows


# ---------------------------------------------------------------- [2] 控制器回放
def stage2(wt, perm, cfg, T3):
    print()
    print("=" * 100)
    print("[2] 控制器回放（真实数据逐分钟喂，无条件计算）")
    print("=" * 100)
    segs = seg_list(perm)
    rows = []
    for s, e in segs:
        sc = SignalConditioner(wt, cfg)
        ctrl = XshController(sc, cfg)
        acts = Counter()
        viol = Counter()
        phases = Counter()
        for i in range(s, e, 10):   # 按控制周期 10min 调用
            out = ctrl.step(i)
            acts[out.action.value] += 1
            phases[out.phase.value] += 1
            if not (cfg.safety.ratio_safe_min - 1e-6 <= out.ratio_set
                    <= cfg.safety.ratio_safe_max + 1e-6):
                viol["水率越界"] += 1
            if not (cfg.safety.lime_min - 1e-6 <= out.lime_set
                    <= cfg.safety.lime_max + 1e-6):
                viol["给料越界"] += 1
            if not np.isnan(out.curr1) and out.curr1 >= cfg.safety.curr1_trip:
                viol["电流高高报"] += 1
            if not np.isnan(out.temp3) and out.temp3 > cfg.safety.temp_hard_high:
                viol["T3硬边界"] += 1
        n_act = sum(c for k, c in acts.items() if k != "保持")
        rows.append((s, e, acts, viol, phases, n_act))
        print("%-14s %4dmin  拍数%3d  动作%3d  阶段%s  越界%s" % (
            time.strftime("%m-%d %H:%M", time.localtime(wt.grid[s])),
            e - s, sum(acts.values()), n_act,
            dict(phases), dict(viol) if viol else "无"))
    tot_v = Counter()
    for _, _, _, v, _, _ in rows:
        tot_v.update(v)
    print()
    print("全量安全越界：%s" % (dict(tot_v) if tot_v else "0（全部合规）"))
    print("注：回放以人工水率设定为基值，绝大部分时间输出=人工值，不能作为控制能力证据。")
    return rows


# ---------------------------------------------------------------- [3] 反事实闭环
def build_disturbance(s0, e0, G, T3, R):
    u_act = np.where(np.isnan(R), 0.0, R).astype(np.float64)
    for i in range(1, u_act.size):
        if np.isnan(R[i]):
            u_act[i] = u_act[i - 1]
    base0 = float(T3[s0])
    resp0 = response_fast(u_act, G, s0)
    d = np.full(e0 - s0 + 1, np.nan)
    for k, t in enumerate(range(s0, e0 + 1)):
        if np.isnan(T3[t]):
            continue
        d[k] = T3[t] - base0 - (response_fast(u_act, G, t) - resp0)
    m = np.isnan(d)
    if not m.all():
        idx = np.where(~m, np.arange(d.size), 0)
        np.maximum.accumulate(idx, out=idx)
        d[m] = d[idx[m]]
    return d, base0, resp0, u_act


def sim_t3(u_sim, s0, e0, G, base0, resp0, d):
    out = np.full(e0 - s0 + 1, np.nan)
    for k, t in enumerate(range(s0, e0 + 1)):
        out[k] = base0 + (response_fast(u_sim, G, t) - resp0) + d[k]
    return out


def run_auto(wt, s0, e0, cfg, G=G_OLD):
    """模型自持水率闭环，返回水率/温度/动作"""
    R = wt.series(Tag.RATIO_SD)
    T3 = t3_series(wt)
    d, base0, resp0, u_act = build_disturbance(s0, e0, G, T3, R)

    sim = AutoTable(wt)
    sc = SignalConditioner(sim, cfg)
    ctrl = XshController(sc, cfg)
    cur_ratio = float(R[s0]) if not np.isnan(R[s0]) and R[s0] > 0 else cfg.control.ratio_init
    cur_lime = float(np.nanmean(wt.series(Tag.LIME)[s0:s0 + 10]))
    if not np.isfinite(cur_lime) or cur_lime <= 0:
        cur_lime = cfg.control.lime_field_sp

    u_sim = u_act.copy()
    r_sim = np.full(e0 - s0 + 1, np.nan)
    t_sim = np.full(e0 - s0 + 1, np.nan)
    acts = []
    for t in range(s0, e0 + 1):
        sim.set_ratio(t, cur_ratio)
        sim.set_lime(t, cur_lime)
        u_sim[t] = cur_ratio
        v = sim_t3(u_sim, t, t, G, base0, resp0, d[t - s0:t - s0 + 1])[0]
        if np.isfinite(v):
            sim.set_t3(t, v)
            t_sim[t - s0] = v
        r_sim[t - s0] = cur_ratio
        if (t - s0) % 10 == 0:
            out = ctrl.step(t)
            if abs(out.ratio_set - cur_ratio) > 1e-9 or abs(out.lime_set - cur_lime) > 1e-9:
                acts.append((t - s0, out.action.value, out.ratio_set, out.reason))
            cur_ratio = float(out.ratio_set)
            cur_lime = float(out.lime_set)
    return dict(r_sim=r_sim, t_sim=t_sim, acts=acts,
                r_act=R[s0:e0 + 1].copy(), t_act=T3[s0:e0 + 1].copy(),
                d=d, u_act=u_act[s0:e0 + 1])


def stage3(wt, perm, cfg):
    print()
    print("=" * 100)
    print("[3] 反事实闭环（自持水率 + 共同扰动 + 响应核 G_OLD）")
    print("=" * 100)
    print("初值取班次内实测水率，之后由模型自持；T3 用响应核推演，双方共用同一扰动 d。")
    print("强依赖 G_OLD，属模型内自证。")
    print()
    segs = seg_list(perm, min_len=180)
    R = wt.series(Tag.RATIO_SD)
    T3 = t3_series(wt)
    consts = [580, 600, 620, 640, 660, 680, 700]

    print("%-14s %5s %8s %8s %8s %8s %8s %6s %6s" % (
        "班次", "min", "人工合格", "模型合格", "人工>130", "模型>130",
        "恒定最优", "动作", "d~u"))
    rows = []
    for s, e in segs:
        s0 = s + 120 if e - s > 300 else s + 60
        if e - s0 < 120:
            continue
        r = run_auto(wt, s0, e - 1, cfg)
        ta, ts = r["t_act"], r["t_sim"]
        a, b = band_stats(ta), band_stats(ts)
        # 恒定水率空白对照（同一扰动）
        d, base0, resp0, u_act = build_disturbance(s0, e - 1, G_OLD, T3, R)
        best, best_ok, const_ok = None, -1, {}
        for c in consts:
            u = u_act.copy()
            u[s0:e] = float(c)
            ts_c = sim_t3(u, s0, e - 1, G_OLD, base0, resp0, d)
            ok = band_stats(ts_c)["ok"]
            const_ok[c] = ok
            if ok > best_ok:
                best, best_ok = c, ok
        corr = float(np.corrcoef(r["u_act"], r["d"])[0, 1]) if np.std(r["d"]) > 0 else np.nan
        lab = time.strftime("%m-%d %H:%M", time.localtime(wt.grid[s0]))
        print("%-14s %5d %7.1f%% %7.1f%% %7.1f%% %7.1f%% %6d/%.0f%% %6d %+6.2f" % (
            lab, e - s0, a["ok"], b["ok"], a["hi"], b["hi"],
            best, best_ok, len(r["acts"]), corr))
        rows.append(dict(label=lab, dur=e - s0, a=a, b=b, best=best,
                         best_ok=best_ok, const=const_ok, n_act=len(r["acts"]),
                         corr=corr, acts=r["acts"],
                         r_sim=r["r_sim"], r_act=r["r_act"]))
    print()
    print("恒定水率扫描（各班次 T3 合格率 %）：")
    print("%-14s %6s " % ("班次", "人工") + " ".join("%6d" % c for c in consts) + " %8s" % "模型")
    for r in rows:
        print("%-14s %5.1f%% " % (r["label"], r["a"]["ok"]) +
              " ".join("%5.1f%%" % r["const"][c] for c in consts) +
              " %7.1f%%" % r["b"]["ok"])
    print()
    n = sum(r["dur"] for r in rows)
    wa = sum(r["a"]["ok"] * r["dur"] for r in rows) / n if n else 0
    wb = sum(r["b"]["ok"] * r["dur"] for r in rows) / n if n else 0
    wbest = sum(r["best_ok"] * r["dur"] for r in rows) / n if n else 0
    print("加权（%d 分钟）：人工 %.1f%%   模型 %.1f%%   恒定水率最优 %.1f%%" % (
        n, wa, wb, wbest))
    print("动作明细（前 20 条）：")
    for r in rows:
        if not r["acts"]:
            continue
        print(" %s" % r["label"])
        for k, act, val, why in r["acts"][:20]:
            print("   +%3dmin %-8s -> %.0f  %s" % (k, act, val, why[:70]))
    return rows


# ---------------------------------------------------------------- [4] 消融
def stage4(wt, perm, cfg_on):
    """快通道开关 × 响应核(含反馈峰 / 物理纯滞后)，分离参数与核的贡献"""
    print()
    print("=" * 100)
    print("[4] 消融：快通道 × 响应核")
    print("=" * 100)
    print("G_OLD 含 +0.47 早期反向峰（水率↑→T3↑）；G_PURE = 10min 死时间 + 8min 惯性，稳态 -0.15。")
    print("若换成 G_PURE 后成绩更好，说明 G_OLD 的反向峰在拖累控制器。")
    print()
    cfg_off = Config()
    cfg_off.control.temp3_fast_high = 9999.0
    cfg_off.control.temp3_fast_low = -9999.0
    variants = [("G_OLD 快开", G_OLD, cfg_on), ("G_OLD 快关", G_OLD, cfg_off),
                ("G_PURE 快开", G_PURE, cfg_on), ("G_PURE 快关", G_PURE, cfg_off)]

    segs = seg_list(perm, min_len=180)
    print("%-14s %5s %7s | " % ("班次", "min", "人工")
          + " | ".join("%-13s" % v[0] for v in variants))
    agg = {k: [] for k, _, _ in variants}
    durs = []
    for s, e in segs:
        s0 = s + 120 if e - s > 300 else s + 60
        if e - s0 < 120:
            continue
        dur = e - s0
        durs.append(dur)
        cells = []
        for name, G, cfg in variants:
            r = run_auto(wt, s0, e - 1, cfg, G)
            ok = band_stats(r["t_sim"])["ok"]
            na = len([x for x in r["acts"] if x[1] != "保持"])
            agg[name].append(ok)
            cells.append("%6.1f%%/%2d" % (ok, na))
        print("%-14s %5d %6.1f%% | " % (
            time.strftime("%m-%d %H:%M", time.localtime(wt.grid[s0])), dur,
            band_stats(t3_series(wt)[s0:e])["ok"]) + " | ".join(cells))
    tot = sum(durs)
    print()
    print("加权（%d min）：" % tot)
    for name, _, _ in variants:
        w = sum(d * x for d, x in zip(durs, agg[name])) / tot
        print("  %-12s %.1f%%" % (name, w))


# ---------------------------------------------------------------- [5] 工况对照
def stage5(wt, perm):
    """对照《预期实现效果.txt》的工艺要求，看这批数据本身实现了多少"""
    print()
    print("=" * 100)
    print("[5] 工况对照：工艺需求在数据里的实现度")
    print("=" * 100)
    print("需求原文：'二级消化器温度须高于1、3级'；'三级温度稳定 100~130℃'")
    print()

    def agg(lev):
        a = np.vstack([wt.series(t) for t in Tag.TEMP[lev]]).astype(float)
        a[a > 250] = np.nan
        with np.errstate(invalid="ignore"):
            return np.nanmean(a, axis=0)

    L1, L2, L3 = agg(0), agg(1), agg(2)
    m = perm & ~np.isnan(L1) & ~np.isnan(L2) & ~np.isnan(L3)
    print("层级均值：T1 %.1f  T2 %.1f  T3 %.1f（生产 %d min）" % (
        L1[m].mean(), L2[m].mean(), L3[m].mean(), m.sum()))
    print("T2 > T1 占比 %.1f%%   T2 > T3 占比 %.1f%%   T2 同时最高 %.1f%%" % (
        100 * np.mean(L2[m] > L1[m]), 100 * np.mean(L2[m] > L3[m]),
        100 * np.mean((L2[m] > L1[m]) & (L2[m] > L3[m]))))
    print()
    print("T3 合格 %.1f%%（>130 %.1f%%，<100 %.1f%%）" % (
        100 * np.mean((L3[m] >= LO) & (L3[m] <= HI)),
        100 * np.mean(L3[m] > HI), 100 * np.mean(L3[m] < LO)))
    print()
    print("水流量 vs 水率×给料 相关 %.3f（README 记录 +0.672，实测含水率控制回路独立）" % (
        np.corrcoef(wt.series(Tag.WATER)[m], (wt.series(Tag.RATIO_SD)[m]
                                             * wt.series(Tag.LIME)[m]))[0, 1]))
    print("生石灰流量设定值 SSHLLSDZ 在数据中：%s" % (Tag.LIME_SD in wt))
    print("水流量设定值 SLLSDZ 在数据中：%s" % ("5#_XSH_SLLSDZ" in wt))


# ---------------------------------------------------------------- main
_grid = None


def main():
    global _grid
    wt = data_loader.build_wide(verbose=False, use_cache=True)
    _grid = wt.grid
    perm = (wt.series(Tag.PERMIT) > 0.5) & (wt.series(Tag.LIME) > 0.1)
    T3 = t3_series(wt)
    T3i = t3_inst(wt)
    R = wt.series(Tag.RATIO_SD)
    L = wt.series(Tag.LIME)
    C1 = wt.series(Tag.CURR1)
    cfg = Config()

    segs, tot = stage0(wt, perm, T3, T3i, R, L, C1)
    stage1(segs, R, T3)
    stage2(wt, perm, cfg, T3)
    stage3(wt, perm, cfg)
    stage4(wt, perm, cfg)
    stage5(wt, perm)


if __name__ == "__main__":
    main()
