# -*- coding: utf-8 -*-
"""
核对现场规律与现有模型的差异。

现场规律（来自总结图）：
  启动阶段：
    1. 现场设定初始下料量、水率、一级电机转速
    2. 以一级电机电流为主要负荷反馈
    3. 电流升高时：优先增加水率 → 仍升高则提高一级电机转速 →
       仍无法降低则降低下料量及水率
    4. 下料量调节范围限制在现场设定值 ±0.5 t/h
    5. 电流超 XA 开始调整；超 23A 立即停止并报警

  运行阶段：
    1. T3 > 100℃ 后切入运行模型
    2. 动态计算与当前物料负荷匹配的最佳水率
    3. 继续按启动阶段相同的电流控制原则
    4. T3 偏高增加水率，T3 偏低减少水率
    5. 在 T3 合格基础上使二级保持较高稳定温度

需核对：
  A. 一级电机转速这个手段，历史数据里有没有
  B. 下料量实际波动范围 vs ±0.5 t/h 约束
  C. 电流手段顺序：现场是 水率→转速→下料量
"""
import os
import sys

import numpy as np

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

OLD_DATA = r"D:/work/脱硫脱硝/data/脱硫脱硝消石灰制备数据"
os.environ["XSH_DATA_DIR"] = OLD_DATA

import data_loader                                        # noqa: E402
data_loader.DATA_DIR = OLD_DATA
data_loader.CACHE_DIR = os.path.join(BASE, ".cache_old")

from config import Tag                                      # noqa: E402

wt = data_loader.build_wide(verbose=False, use_cache=False)
n = wt.grid.size
R = wt.series(Tag.RATIO_SD)
L = wt.series(Tag.LIME)
C1 = wt.series(Tag.CURR1)
SPD_SD_NAME = "5#_XSH_1JLXSSJZSGD"
SPD_FK_NAME = "5#_XSH_1JLXSSJSDFK"
perm = (wt.series(Tag.PERMIT) > 0.5) & (L > 0.1)

print("=" * 98)
print("A. 一级电机转速手段（现场规律的第二步）")
print("=" * 98)
print("  宽表中是否存在转速给定测点: %s" % (SPD_SD_NAME in wt))
print("  宽表中是否存在转速反馈测点: %s" % (SPD_FK_NAME in wt))
print()
print("  原始数据中的情况（不过滤 1970）:")
import zipfile, csv
zips = sorted(f for f in os.listdir(OLD_DATA) if f.endswith(".zip"))
found = {}
with zipfile.ZipFile(os.path.join(OLD_DATA, zips[-1])) as z:
    for entry in z.namelist():
        if not entry.lower().endswith(".csv"):
            continue
        with z.open(entry) as f:
            lines = f.read().decode("utf-8", errors="replace").splitlines()
        if len(lines) < 3:
            continue
        nm = next(csv.reader([lines[0]]), None)
        if not nm or len(nm) < 2:
            continue
        name = nm[1].strip()
        if "1JLXSSJZ" in name:
            ts, vs = [], []
            for line in lines[2:]:
                p = next(csv.reader([line]), None)
                if not p or len(p) < 2:
                    continue
                try:
                    ts.append(p[0].strip())
                    vs.append(float(p[1]))
                except (ValueError, IndexError):
                    continue
            if vs:
                found[name] = (ts, vs)

for name, (ts, vs) in found.items():
    uniq, cnt = np.unique(vs, return_counts=True)
    print("    %s" % name)
    print("      样本 %d, 取值分布 %s" % (
        len(vs), dict(zip(uniq.tolist(), cnt.tolist()))))
    print("      首时间 %s   末时间 %s" % (ts[0], ts[-1]))

print()
print("  => 若取值全为 0 或时间为 1970，说明该手段从未被使用，模型无法调用。")

print()
print("=" * 98)
print("B. 下料量约束（现场：设定值 ±0.5 t/h）")
print("=" * 98)
# 分段看每班次的下料量波动
dd = np.diff(perm.astype(np.int8))
starts = list(np.where(dd == 1)[0] + 1)
ends = list(np.where(dd == -1)[0] + 1)
if perm[0]:
    starts.insert(0, 0)
if perm[-1]:
    ends.append(n)
segs = [(s, e) for s, e in zip(starts, ends) if e - s >= 30]

import time
print("  %-16s %8s %8s %8s %10s %10s" % (
    "班次", "下料均值", "std", "范围", "极差", "是否超±0.5"))
for s, e in segs:
    lv = L[s:e]
    lv = lv[~np.isnan(lv)]
    if lv.size < 30:
        continue
    rng = lv.max() - lv.min()
    print("  %-16s %8.2f %8.2f %8s %10.2f %10s" % (
        time.strftime("%m-%d %H:%M", time.localtime(wt.grid[s])),
        lv.mean(), lv.std(),
        "%.2f~%.2f" % (lv.min(), lv.max()), rng,
        "超" if rng > 0.5 else "符合"))

print()
allv = L[perm]
allv = allv[~np.isnan(allv)]
print("  全部生产时段: 范围 %.2f ~ %.2f  极差 %.2f" % (
    allv.min(), allv.max(), allv.max() - allv.min()))
print("  现场约束 ±0.5 t/h 意味着单班次极差应 <= 0.5，实际远超。")
print("  说明现场下料量本身波动较大，±0.5 是「模型调节范围」限制，")
print("  不是「实际值波动」限制。")

print()
print("=" * 98)
print("C. 电流手段顺序核对")
print("=" * 98)
print("""
现场规律：电流升高 → 先加水率 → 再加转速 → 最后降下料量和水率
现有模型：T3 偏高 → 先加水率 → 水率到顶才降给料量
          电流越限 → 只写 notes，不干预

差异：
  1. 模型缺少「一级电机转速」手段（历史无有效数据）
  2. 模型的电流保护是纯提示，不执行降载
  3. 现场启动阶段就用电流作反馈，模型要等 T3>100 才进稳态

核对结论见下方统计。
""")

print("=" * 98)
print("D. 模型当前手段清单 vs 现场规律")
print("=" * 98)
print("""
  手段                 现场规律     现有模型
  ─────────────────────────────────────────────
  水率                 有           有
  一级电机转速          有           无（历史无数据）
  下料量               有（±0.5）   有（范围 3.0~5.27）
  电流反馈              有           仅提示，不执行
""")
