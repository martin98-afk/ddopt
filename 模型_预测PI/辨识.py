# -*- coding: utf-8 -*-
"""从现场阶跃试验数据辨识对象参数 K / τ / θ。

用法：
    python 辨识.py 阶跃数据.csv

CSV 格式（表头必须有 time, ratio, t3）：
    time,ratio,t3
    2026-10-21 09:00,600,121.3
    2026-10-21 09:01,660,121.5
    ...

输出：
  1. 控制台打印 K / τ / θ 与拟合质量（RMSE、R²）
  2. 前 15 分钟响应方向诊断（判断"加水先升温"是真是假）
  3. 双向一致性检验（升/降两段分别辨识，看是否吻合）
  4. 可直接抄进 标定参数.py 的数值

拟合方法：网格搜索 θ 与 τ，线性最小二乘求 K，取 RMSE 最小组合。
不需要等到完全稳态——只要数据覆盖了 θ + 2τ 就能同时估出三个参数。
"""
from __future__ import annotations

import csv
import os
import sys
from typing import List, Optional, Tuple

import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
for _p in (_HERE, os.path.join(os.path.dirname(_HERE), "模型")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import 标定参数 as P  # noqa: E402


# ============================================================ 数据读取
def load_csv(path: str) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """返回 (分钟轴, 水率, T3)。时间只取 HH:MM 的相对分钟。"""
    ts, us, ys = [], [], []
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        rd = csv.DictReader(f)
        if rd.fieldnames is None:
            raise ValueError("CSV 无表头")
        # 表头兼容中文
        def pick(names: List[str], *cands: str) -> str:
            for c in cands:
                for n in names:
                    if n and n.strip().lower() == c.lower():
                        return n
            raise ValueError("CSV 缺少必要列，需含 %s" % "/".join(cands))

        ct = pick(rd.fieldnames, "time", "时间", "timestamp", "ts")
        cu = pick(rd.fieldnames, "ratio", "水率", "u", "water_ratio")
        cy = pick(rd.fieldnames, "t3", "T3", "温度", "temp", "y")

        t0: Optional[int] = None
        for row in rd:
            try:
                hm = str(row[ct]).strip()
                # 支持 "2026-10-21 09:00" 或 "09:00"
                hms = hm.split(" ")[-1]
                hh, mm = hms.split(":")[:2]
                minute = int(hh) * 60 + int(mm)
            except Exception:
                continue
            try:
                u = float(row[cu])
                y = float(row[cy])
            except (TypeError, ValueError):
                continue
            if u != u or y != y:
                continue
            if t0 is None:
                t0 = minute
            ts.append(minute - t0)
            us.append(u)
            ys.append(y)
    if not ts:
        raise ValueError("CSV 无有效数据行")
    return (np.asarray(ts, float), np.asarray(us, float),
            np.asarray(ys, float))


def resample_to_minute(ts: np.ndarray, us: np.ndarray, ys: np.ndarray
                       ) -> Tuple[np.ndarray, np.ndarray]:
    """对齐到 1 分钟网格（缺失前向填充）。要求 ts 单位已是分钟。"""
    n = int(np.nanmax(ts)) + 1
    ug = np.full(n, np.nan)
    yg = np.full(n, np.nan)
    idx = np.clip(np.round(ts).astype(int), 0, n - 1)
    ug[idx] = us
    yg[idx] = ys
    # 前向填充
    for i in range(1, n):
        if np.isnan(ug[i]):
            ug[i] = ug[i - 1]
        if np.isnan(yg[i]):
            yg[i] = yg[i - 1]
    return ug, yg


# ============================================================ FOPDT 拟合
def fopdt_kernel(K: float, tau: float, theta: float, n: int) -> np.ndarray:
    t = np.arange(n, dtype=float)
    g = np.zeros(n)
    m = t >= theta
    if tau > 0:
        g[m] = K * (1.0 - np.exp(-(t[m] - theta) / tau))
    else:
        g[m] = K
    return g


def sim_response(u: np.ndarray, g: np.ndarray, y0: float) -> np.ndarray:
    """y(t) = y0 + Σ g[k]·Δu(t-k)"""
    n = len(u)
    out = np.full(n, y0)
    L = len(g)
    for t in range(n):
        s = 0.0
        for k in range(min(L, t + 1)):
            du = u[t - k] - (u[t - k - 1] if t - k - 1 >= 0 else u[0])
            if du:
                s += g[k] * du
        out[t] = y0 + s
    return out


def fit(u: np.ndarray, y: np.ndarray,
        thetas=(0, 5, 10, 15, 20, 25, 30, 40, 50, 60),
        taus=(2, 5, 8, 12, 20, 30, 45, 60, 90, 120)):
    """网格搜 θ/τ + 线性最小二乘求 K。返回最优参数与拟合质量。

    数据太短（<20 点）或水率无变化时返回 None，调用方须判空。
    """
    n = len(u)
    if n < 20 or float(np.ptp(u)) < 1e-9:
        return None
    y0 = y[0]
    best = None
    var = float(np.var(y)) or 1e-12
    if var < 1e-12:
        return None
    for th in thetas:
        for tau in taus:
            # 用单位 K=1 的核算基函数，再线性求 K
            g1 = fopdt_kernel(1.0, float(tau), float(th), n)
            base = sim_response(u, g1, 0.0)
            denom = float(np.dot(base, base))
            if denom < 1e-12:
                continue
            K = float(np.dot(base, y - y0) / denom)
            gk = fopdt_kernel(K, float(tau), float(th), n)
            ym = sim_response(u, gk, y0)
            rmse = float(np.sqrt(np.mean((y - ym) ** 2)))
            if best is None or rmse < best["rmse"]:
                best = dict(K=K, tau=float(tau), theta=float(th),
                            rmse=rmse, r2=1.0 - rmse ** 2 / var,
                            y_model=ym)
    return best


# ============================================================ 分段诊断
def find_steps(u: np.ndarray, min_gap: int = 20) -> List[int]:
    """找水率发生阶跃的时刻（变化幅度 > 5 L/t 且距上次 > min_gap）"""
    idx = []
    for i in range(1, len(u)):
        if abs(u[i] - u[i - 1]) > 5.0:
            if not idx or i - idx[-1] >= min_gap:
                idx.append(i)
    return idx


def early_direction(u: np.ndarray, y: np.ndarray, step_i: int,
                    win: int = 15) -> dict:
    """阶跃后前 win 分钟 T3 的走向（判断"加水先升温"的真伪）。

    前置条件：阶跃前 win 分钟内没有其他阶跃，且 T3 已基本平稳。
    否则前一次阶跃的效应仍在衰减，会掩盖本次的方向 —— 这种情况下
    返回 ok=False 并说明原因，不做判断（宁缺毋滥，避免误报"反向"）。

    这是历史辨识踩过的坑：事件研究把"原趋势延续"误标为水率效应。
    """
    # 前序阶跃是否干扰
    prev_u = u[max(0, step_i - win):step_i]
    if len(prev_u) > 1 and float(np.ptp(prev_u)) > 1e-9:
        return dict(ok=False, why="前 %d 分钟内还有别的水率变动，"
                                  "前序效应未消退" % win)
    # 阶跃前 T3 是否平稳
    pre = y[max(0, step_i - win):step_i]
    if len(pre) >= 3:
        sl = float(np.polyfit(np.arange(len(pre)), pre, 1)[0])
        if abs(sl) > 0.15:      # ℃/min，超过此值视为仍在漂移
            return dict(ok=False,
                        why="阶跃前 T3 仍在漂移（斜率 %+.2f ℃/min）" % sl)
    du = u[step_i] - u[step_i - 1]
    seg = y[step_i:step_i + win]
    if len(seg) < 3:
        return dict(ok=False, why="阶跃后数据不足 %d 分钟" % win)
    dy = seg[-1] - y[step_i]
    # 噪声门槛：死时间内 T3 本就不该动，此时的微小变化是噪声不是响应。
    # 温度噪声 std ≈ 0.15℃，取 0.5℃（约 3σ）作为"确实动了"的判据。
    NOISE = 0.5
    if abs(dy) < NOISE:
        return dict(ok=False,
                    why="%d min 内 T3 变化 %+.2f℃，未超过噪声门槛 "
                        "%.1f℃（死时间内本不应有响应）" % (win, dy, NOISE))
    normal = (du > 0 and dy < 0) or (du < 0 and dy > 0)
    return dict(ok=True, du=float(du), dy=float(dy),
                reversed=not normal,
                slope=float(np.polyfit(np.arange(len(seg)), seg, 1)[0]))


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        print("用法：python 辨识.py 阶跃数据.csv")
        sys.exit(1)

    path = sys.argv[1]
    if not os.path.isfile(path):
        print("文件不存在: %s" % path)
        sys.exit(1)

    ts, us, ys = load_csv(path)
    u, y = resample_to_minute(ts, us, ys)
    print("=" * 84)
    print("阶跃试验辨识   数据 %d 分钟   水率 %.0f~%.0f   T3 %.1f~%.1f"
          % (len(u), u.min(), u.max(), y.min(), y.max()))
    print("=" * 84)

    steps = find_steps(u)
    print("\n检测到 %d 次水率阶跃：%s" % (
        len(steps), ", ".join("t=%dmin Δu=%+.0f" % (
            i, u[i] - u[i - 1]) for i in steps)))

    # ---------- 全段拟合 ----------
    print("\n【1】全段拟合（K / τ / θ 同时估计）")
    b = fit(u, y)
    print("  K     = %+.4f  ℃/(L/t)" % b["K"])
    print("  τ     = %.0f  min" % b["tau"])
    print("  θ     = %.0f  min" % b["theta"])
    print("  RMSE  = %.3f ℃    R² = %.3f" % (b["rmse"], b["r2"]))
    if b["r2"] < 0.5:
        print("  [警告] R² < 0.5，拟合质量差。可能原因：")
        print("         · 试验期间有其他参数变动（给料量、转速）")
        print("         · 存在强烈未被记录的扰动")
        print("         · 对象不是一阶（比如真有反向段）")
    if b["K"] > 0:
        print("  [警告] K 为正 —— 意味着加水升温，与工艺假设相反。")
        print("         请核对 CSV 列是否对应正确（ratio 是水率、t3 是温度）")

    # ---------- 前段方向诊断 ----------
    print("\n【2】阶跃后前 15 分钟方向诊断（判断'加水先升温'真伪）")
    for i in steps:
        r = early_direction(u, y, i)
        if not r["ok"]:
            print("  t=%4dmin  Δu=%+6.0f  无法判断：%s"
                  % (i, u[i] - u[i - 1], r.get("why", "数据不足")))
            continue
        tag = "反向！疑似非最小相位" if r["reversed"] else "正常（加水降温）"
        print("  t=%4dmin  Δu=%+6.0f → 15min内 ΔT3=%+6.2f  %s"
              % (i, r["du"], r["dy"], tag))
    print("  注：若多次阶跃都显示'反向'，则对象是最小相位以外的结构，")
    print("      预测PI 的纯滞后模型不适用，需换方案。")

    # ---------- 分段一致性 ----------
    # 用「阶跃后」的窗口单独拟合：每段从阶跃时刻起取 min(90, 段长) 分钟，
    # 段内水率恒定是正常的（阶跃试验本就要求保持不动），
    # 判空条件应看窗口长度，而不是段内是否有水率变化。
    if len(steps) >= 2:
        print("\n【3】分段一致性（各阶跃段单独拟合，看是否吻合）")
        results = []
        for i in steps:
            # 窗口必须包含阶跃点本身，否则段首 Δu=0，拟合会把响应全部
            # 归到残差里 —— 实测这会让 K 估成 +0.053（符号都反了）。
            start = max(0, i - 1)
            end = min(len(u), i + 90)
            if end - start < 40:
                print("  阶跃 t=%4dmin 后续数据不足 40 min，跳过" % i)
                continue
            sb = fit(u[start:end], y[start:end])
            if sb is None:
                print("  阶跃 t=%4dmin 数据不足，跳过" % i)
                continue
            results.append(sb)
            print("  阶跃 t=%4dmin Δu=%+6.0f (%3d min)  K=%+.4f  τ=%3.0f  "
                  "θ=%3.0f  R²=%.2f"
                  % (i, u[i] - u[i - 1], end - i,
                     sb["K"], sb["tau"], sb["theta"], sb["r2"]))
        if len(results) < 2:
            print("\n  有效段不足 2 段，跳过一致性检验")
        else:
            ks = [r["K"] for r in results]
            print("\n  K 的离散度：min %+.4f / max %+.4f" % (min(ks), max(ks)))
            if min(ks) * max(ks) < 0:
                print("  [警告] 各段 K 符号不一致 —— 试验受污染，需重做")
            elif (max(abs(x) for x in ks)
                  / max(min(abs(x) for x in ks), 1e-9)) > 2.0:
                print("  [警告] 各段 K 相差 2 倍以上 —— 建议重做或取中位数")
            else:
                print("  [OK] 各段 K 一致，可用中位数")

    # ---------- 输出建议值 ----------
    print("\n" + "=" * 84)
    print("把下面三个数抄进 标定参数.py（并把 CALIBRATED 改成 True）：")
    print("=" * 84)
    print("    GAIN  = %+.4f" % b["K"])
    print("    TAU   = %.1f" % b["tau"])
    print("    THETA = %.1f" % b["theta"])
    print()
    print("抄完后运行：python 自检.py     确认可以下控")
    print("再运行：python 闭环对比.py     看新参数下的实际效果")


if __name__ == "__main__":
    main()
