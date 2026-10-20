# -*- coding: utf-8 -*-
"""用真实历史数据试着标定，验证"是否确实无法标定"。

只取生产期间的数据（给水给料允许信号=1 且 给料量>0.1），
未生产时段温度与水率的关系不成立，必须排除。

做法：把每个生产段导出成 辨识.py 能读的 CSV，再调辨识.py 辨识，
最后汇总各段结果看是否一致。

运行：python 历史标定试验.py
"""
from __future__ import annotations

import csv
import os
import sys

import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
_MODEL_DIR = os.path.join(os.path.dirname(_HERE), "模型")
for _p in (_HERE, _MODEL_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

os.environ.setdefault(
    "XSH_DATA_DIR",
    r"D:\work\梅钢脱硫脱硝\data\脱硫脱硝消石灰制备数据")

from data_loader import build_wide                            # noqa: E402
from config import Tag                                        # noqa: E402

import 辨识 as ID                                              # noqa: E402
import 标定参数 as P                                            # noqa: E402

EXPORT_DIR = os.path.join(_HERE, "_标定导出")
NOISE = 0.15


def production_segments(wt, min_len=60):
    """只保留生产期间：允许信号=1 且 给料量>0.1"""
    perm = wt.series(Tag.PERMIT)
    lime = wt.series(Tag.LIME)
    prod = (perm > 0.5) & (lime > 0.1)
    prod = np.where(np.isnan(perm) | np.isnan(lime), False, prod)
    d = np.diff(prod.astype(np.int8))
    st = list(np.where(d == 1)[0] + 1)
    en = list(np.where(d == -1)[0] + 1)
    if prod[0]:
        st.insert(0, 0)
    if prod[-1]:
        en.append(prod.size)
    return [(s, e) for s, e in zip(st, en) if e - s >= min_len]


def export_seg(wt, s, e, path):
    """导出一个生产段成 CSV：time / ratio / t3(中位)"""
    u = wt.series(Tag.RATIO_SD)[s:e]
    # 温度取三测点中位（与 辨识.py 要求一致）
    T = np.vstack([wt.series(t)[s:e] for t in Tag.TEMP[2]])
    y = np.nanmedian(T, axis=0)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["time", "ratio", "t3"])
        for k in range(e - s):
            uu = u[k]
            yy = y[k]
            w.writerow([wt.time_full(s + k)[-5:],
                        "" if uu != uu else round(float(uu), 1),
                        "" if yy != yy else round(float(yy), 2)])
    return path


def cut_startup(wt, s, e, t3_min=100.0, stable_min=150, quiet_std=6.0):
    """剔除生产段开头的启动升温期。

    为什么必须剔除：启动阶段 T3 从常温冲到 150℃ 以上，
    这段温度由化学反应放热驱动，与水率几乎无关。
    实测 10-14 班次前 100 分钟 T3 从 39.5 升到 163.6℃，
    同期水率也在大幅调整 —— 两者都被第三方（反应进程）驱动，
    拟合会把这段巨大的共同趋势误当成水率效应。

    剔除判据（取最靠后的一个作为起点）：
      1. T3 首次达到 t3_min（默认 100℃）
      2. 再等 stable_min 分钟让反应稳定
      3. 或直到 T3 的滑动标准差降到 quiet_std 以下
    """
    T = np.vstack([wt.series(t)[s:e] for t in Tag.TEMP[2]])
    y = np.nanmedian(T, axis=0)
    n = len(y)
    start = 0
    # 1) T3 首次达标
    ok = np.where((~np.isnan(y)) & (y >= t3_min))[0]
    if ok.size:
        start = max(start, int(ok[0]) + stable_min)
    # 2) 滑动 std 降到阈值以下并持续
    win = 30
    for i in range(0, max(1, n - win)):
        seg = y[i:i + win]
        seg = seg[~np.isnan(seg)]
        if seg.size >= win // 2 and np.std(seg) < quiet_std:
            start = max(start, i)
            break
    return min(start, n - 60), n     # 至少留 60 分钟


def main():
    os.makedirs(EXPORT_DIR, exist_ok=True)
    wt = build_wide(verbose=False)
    segs = production_segments(wt)

    print("=" * 92)
    print("用真实历史数据试标定（仅生产期间，剔除启动升温段）")
    print("=" * 92)
    print("数据总量 %d 分钟，生产 %d 分钟（%.1f%%），合格生产段 %d 段"
          % (wt.grid.size, sum(e - s for s, e in segs),
             100.0 * sum(e - s for s, e in segs) / wt.grid.size, len(segs)))
    print()
    print("两道过滤，缺一不可：")
    print("  ① 只取生产期间 —— 未生产时无物料通过，水率与温度关系不成立")
    print("  ② 剔除启动升温 —— 启动期 T3 由反应放热驱动，与水率无关，")
    print("     实测 10-14 班次前 100 分钟 T3 从 39.5℃ 冲到 163.6℃，")
    print("     混进去会把共同趋势误当成水率效应")

    all_res = []
    for si, (s, e) in enumerate(segs):
        off, total = cut_startup(wt, s, e)
        s2 = s + off
        if e - s2 < 120:
            print()
            print("生产段 %d（%s）：剔除启动后仅剩 %d 分钟，过短，跳过"
                  % (si, wt.time_full(s), e - s2))
            continue
        path = os.path.join(EXPORT_DIR, "seg%d.csv" % si)
        export_seg(wt, s2, e, path)
        print()
        print("=" * 92)
        print("生产段 %d：%s  总 %d 分钟，剔除启动后 %d 分钟（起于 %s）"
              % (si, wt.time_full(s), total, e - s2, wt.time_full(s2)))
        print("=" * 92)

        ts, us, ys = ID.load_csv(path)
        u, y = ID.resample_to_minute(ts, us, ys)
        steps = ID.find_steps(u)
        print("  水率阶跃 %d 次：%s" % (
            len(steps), ", ".join("t=%d Δ%+.0f" % (i, u[i] - u[i - 1])
                                  for i in steps[:8])))

        b = ID.fit(u, y)
        if b is None:
            print("  全段拟合失败（数据不足）")
            continue
        print("  全段拟合： K=%+.4f  τ=%.0f  θ=%.0f  RMSE=%.2f  R²=%.2f"
              % (b["K"], b["tau"], b["theta"], b["rmse"], b["r2"]))
        all_res.append((si, wt.time_full(s), b, len(steps)))

    # ---------- 汇总判定 ----------
    print()
    print("=" * 92)
    print("汇总：历史数据到底能不能标定")
    print("=" * 92)
    if len(all_res) < 2:
        print("  有效生产段不足 2 段，无法做一致性判断")
    else:
        print("  %-18s %8s %6s %6s %7s %6s %6s" % (
            "生产段", "K", "τ", "θ", "R²", "阶跃", "判定"))
        ks = []
        for si, name, b, ns in all_res:
            ks.append(b["K"])
            print("  %-18s %+8.4f %6.0f %6.0f %7.2f %6d %6s"
                  % (name[-11:], b["K"], b["tau"], b["theta"],
                     b["r2"], ns, ""))
        print()
        print("  K 值：min %+.4f / max %+.4f" % (min(ks), max(ks)))
        verdict = []
        if min(ks) * max(ks) < 0:
            verdict.append("✗ 各段 K 符号相反 —— 无法标定")
        elif max(abs(x) for x in ks) / max(min(abs(x) for x in ks), 1e-9) > 2.0:
            verdict.append("✗ 各段 K 相差 %.1f 倍（>2 倍）—— 无法标定"
                           % (max(abs(x) for x in ks)
                              / max(min(abs(x) for x in ks), 1e-9)))
        else:
            verdict.append("✓ 各段 K 一致")
        mean_r2 = np.mean([b["r2"] for _, _, b, _ in all_res])
        print("  平均 R² = %.2f  %s" % (
            mean_r2, "✓ 拟合可信" if mean_r2 >= 0.7 else "✗ 拟合不可信（R²<0.7）"))
        if mean_r2 < 0.7:
            verdict.append("✗ R² 过低")
        any_pos = any(b["K"] > 0 for _, _, b, _ in all_res)
        if any_pos:
            verdict.append("✗ 存在 K>0（加水升温），与工艺相反")

        print()
        for v in verdict:
            print("  " + v)
        ok = all(s.startswith("✓") for s in verdict)
        print()
        if ok:
            print("  结论：历史数据【可以】标定，可省去现场试验")
            kk = float(np.median(ks))
            tt = float(np.median([b["tau"] for _, _, b, _ in all_res]))
            th = float(np.median([b["theta"] for _, _, b, _ in all_res]))
            print("  建议填：  GAIN=%+.4f   TAU=%.0f   THETA=%.0f" % (kk, tt, th))
        else:
            print("  结论：历史数据【无法】可靠标定，必须做现场受控阶跃试验")
            print("        方法见 标定说明.md")


if __name__ == "__main__":
    main()
