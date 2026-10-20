# -*- coding: utf-8 -*-
"""核实给水给料允许信号及生产判据的原始取值。"""
import numpy as np
from data_loader import scan_raw, DATA_DIR

raw = scan_raw()
for key in ["5#_XSH_GSGLYXXH", "5#_XSH_GLJQTXH", "5#_XSH_XHQDBPQFJYXXH",
            "5#_XSH_GYSXJSFK", "5#_XSH_GYSXJSFG"]:
    if key not in raw:
        print("%s : 缺失" % key)
        continue
    ts, v = raw[key]
    uniq, cnt = np.unique(v, return_counts=True)
    print("\n%s" % key)
    print("  样本 %d, 时间 %s ~ %s" % (
        ts.size,
        __import__("time").strftime("%m-%d %H:%M", __import__("time").localtime(ts[0])),
        __import__("time").strftime("%m-%d %H:%M", __import__("time").localtime(ts[-1]))))
    print("  取值分布: %s" % dict(zip(uniq.tolist(), cnt.tolist())))
    print("  相邻采样间隔(分钟): 中位 %.1f, 均值 %.1f" % (
        np.median(np.diff(ts)) / 60, np.mean(np.diff(ts)) / 60))
    # 取值为 1 的时段
    idx1 = np.where(v > 0.5)[0]
    if idx1.size:
        print("  =1 的采样点时间(前10):")
        import time as _t
        for i in idx1[:10]:
            print("     " + _t.strftime("%m-%d %H:%M", _t.localtime(ts[i])))
        print("  =1 的采样点总数: %d" % idx1.size)

# 检查生石灰流量实际值 —— 若>0 即代表在给料
print()
print("=" * 70)
for key in ["5#_XSH_SSHLLSJZ", "5#_XSH_SLLSJZ", "5#_XSH_SL(SHB)SD"]:
    ts, v = raw[key]
    print("%s: 样本%d, 非零占比 %.1f%%, 均值(非零) %.2f, 时间 %s~%s" % (
        key, v.size, 100 * np.mean(v > 0.01),
        v[v > 0.01].mean() if (v > 0.01).any() else 0,
        __import__("time").strftime("%m-%d %H:%M", __import__("time").localtime(ts[0])),
        __import__("time").strftime("%m-%d %H:%M", __import__("time").localtime(ts[-1]))))
