# -*- coding: utf-8 -*-
"""
消石灰制备数据加载层。

职责：
  1. 扫描 脱硫脱硝消石灰制备数据/ 下所有 dbName_db101-*.zip，解析其中 tagID_*.csv
  2. 按测点名归集多段时序，归并排序 + 时间去重
  3. 对齐到统一分钟网格，产出宽表 WideTable（pandas DataFrame，索引为分钟时间戳）

约定：
  - 时间戳 1970 开头为无效点，直接丢弃
  - 采样不规则（压缩存储），对齐采用「取该分钟内均值」；无数据分钟留 NaN
  - 开关量通过取值集合 ⊆ {0,1} 判定，对齐采用「前向填充」
"""
from __future__ import annotations

import csv
import glob
import os
import time
import zipfile
from bisect import bisect_left, bisect_right
from typing import Dict, List, Sequence, Tuple

import numpy as np

BASE = os.path.dirname(os.path.abspath(__file__))
# 允许环境变量覆盖数据集目录与缓存目录（切换标定集/新数据时用）
DATA_DIR = os.environ.get("XSH_DATA_DIR") or \
    os.path.join(os.path.dirname(BASE), "脱硫脱硝消石灰制备数据")
CACHE_DIR = os.environ.get("XSH_CACHE_DIR") or os.path.join(BASE, ".cache")

MIN_TS = 1577836800  # 2020-01-01，早于此视为无效时间戳
_day_cache: Dict[str, int] = {}


def parse_ts(s: str) -> int:
    """' 2026-10-16 14:00:00.000' -> epoch 秒（本地时区）"""
    s = s.strip()
    if len(s) < 19:
        raise ValueError("bad ts: %r" % s)
    date, hms = s[:10], s[11:19]
    day0 = _day_cache.get(date)
    if day0 is None:
        day0 = int(time.mktime(time.strptime(date, "%Y-%m-%d")))
        _day_cache[date] = day0
    return day0 + int(hms[:2]) * 3600 + int(hms[3:5]) * 60 + int(hms[6:8])


def load_meta() -> Dict[str, dict]:
    """读测点清单 CSV：测点名 -> {desc, unit, ptype}"""
    meta: Dict[str, dict] = {}
    for fp in glob.glob(os.path.join(DATA_DIR, "5#_XSH_*.csv")):
        with open(fp, encoding="utf-8-sig", errors="replace", newline="") as f:
            reader = csv.reader(f)
            header = next(reader, None)
            if not header:
                continue
            idx = {name: i for i, name in enumerate(header)}
            i_name = idx.get("测点名称")
            if i_name is None:
                continue
            i_type = idx.get("点类型（开关量、模拟量、控制点、打包点）")
            i_unit = idx.get("测点单位")
            i_desc = idx.get("描述")
            for row in reader:
                if len(row) <= i_name or not row[i_name]:
                    continue
                meta[row[i_name]] = {
                    "ptype": row[i_type].strip() if i_type is not None and i_type < len(row) else "",
                    "unit": row[i_unit].strip() if i_unit is not None and i_unit < len(row) else "",
                    "desc": row[i_desc].strip() if i_desc is not None and i_desc < len(row) else "",
                }
    return meta


def _merge_segments(segments: Sequence[Tuple[List[int], List[float]]]) -> Tuple[np.ndarray, np.ndarray]:
    """多段（每段内部按时间有序）归并排序 + 按时间去重，取后值覆盖前值"""
    if not segments:
        return np.empty(0, dtype=np.int64), np.empty(0, dtype=np.float64)
    streams = [list(zip(ts, vs)) for ts, vs in segments]
    for st in streams:  # 段内未必严格有序，先稳定排序
        st.sort(key=lambda x: x[0])
    heap = [(st[0][0], si, 0) for si, st in enumerate(streams) if st]
    import heapq
    heapq.heapify(heap)
    ts_out: List[int] = []
    v_out: List[float] = []
    last_ts = None
    while heap:
        ts, si, pi = heapq.heappop(heap)
        val = streams[si][pi][1]
        if ts != last_ts:
            ts_out.append(ts)
            v_out.append(val)
            last_ts = ts
        else:
            v_out[-1] = val  # 同时间戳，后到的覆盖
        pi += 1
        if pi < len(streams[si]):
            heapq.heappush(heap, (streams[si][pi][0], si, pi))
    return np.asarray(ts_out, dtype=np.int64), np.asarray(v_out, dtype=np.float64)


def scan_raw(verbose: bool = False) -> Dict[str, Tuple[np.ndarray, np.ndarray]]:
    """扫描全部 zip -> {测点名: (ts数组, val数组)}"""
    zips = sorted(glob.glob(os.path.join(DATA_DIR, "dbName_db101-*.zip")))
    if not zips:
        raise FileNotFoundError("未找到 zip 数据: %s" % DATA_DIR)
    merged: Dict[str, List[Tuple[List[int], List[float]]]] = {}
    for zp in zips:
        with zipfile.ZipFile(zp) as z:
            for entry in z.namelist():
                if not entry.lower().endswith(".csv"):
                    continue
                with z.open(entry) as f:
                    text = f.read().decode("utf-8", errors="replace")
                lines = text.splitlines()
                if len(lines) < 3:
                    continue
                name_line = next(csv.reader([lines[0]]), None)
                if not name_line or len(name_line) < 2:
                    continue
                name = name_line[1].strip()
                ts_list: List[int] = []
                v_list: List[float] = []
                for line in lines[2:]:
                    if not line:
                        continue
                    parts = next(csv.reader([line]), None)
                    if not parts or len(parts) < 2:
                        continue
                    try:
                        ts = parse_ts(parts[0])
                        val = float(parts[1])
                    except (ValueError, IndexError):
                        continue
                    if ts < MIN_TS:
                        continue
                    ts_list.append(ts)
                    v_list.append(val)
                if ts_list:
                    merged.setdefault(name, []).append((ts_list, v_list))
        if verbose:
            print("  loaded %s" % os.path.basename(zp))
    return {name: _merge_segments(segs) for name, segs in merged.items()}


def is_switchable(vals: np.ndarray) -> bool:
    """取值集合 ⊆ {0,1} 且非全同，判定为开关量"""
    if vals.size == 0:
        return False
    uniq = np.unique(vals)
    if uniq.size > 2:
        return False
    return bool(np.all((uniq == 0) | (uniq == 1)))


def align_to_minute(ts: np.ndarray, vals: np.ndarray, grid: np.ndarray,
                    is_switch: bool) -> np.ndarray:
    """
    把不规则采样对齐到分钟网格 grid（epoch秒，步长60）。

    数据为压缩存储（跳变/动态阈值），无记录即代表「值未变」，
    因此统一用「同分钟取最后值 + 前向填充（step-hold）」语义。
    开关量同分钟内出现 1 即视为开（取 max，避免被 0 覆盖）。
    """
    if ts.size == 0:
        return np.full(grid.shape, np.nan, dtype=np.float64)
    g0 = grid[0]
    bucket = (ts - g0) // 60
    valid = (bucket >= 0) & (bucket < grid.size)
    if not valid.any():
        return np.full(grid.shape, np.nan, dtype=np.float64)
    b = bucket[valid]
    v = vals[valid]

    # 开关量与模拟量统一：同分钟取最后出现的采样值（ts 已排序，后写覆盖前写即达成）
    agg = np.full(grid.size, np.nan, dtype=np.float64)
    agg[b] = v
    filled = _ffill_bfill(agg)
    if is_switch:
        filled = np.nan_to_num(filled, nan=0.0)
    return filled


def _ffill_bfill(a: np.ndarray) -> np.ndarray:
    """前向填充 + 首段回填（数据开头缺失时补首个有效值）"""
    out = a.copy()
    mask = np.isnan(out)
    if mask.all():
        return out
    idx = np.where(~mask, np.arange(out.size), 0)
    np.maximum.accumulate(idx, out=idx)
    out[mask] = out[idx[mask]]
    return out


def build_wide(verbose: bool = True, use_cache: bool = True) -> "WideTable":
    """构建分钟级宽表"""
    os.makedirs(CACHE_DIR, exist_ok=True)
    cache_npz = os.path.join(CACHE_DIR, "wide.npz")
    cache_meta = os.path.join(CACHE_DIR, "wide_meta.json")

    if use_cache and os.path.exists(cache_npz) and os.path.exists(cache_meta):
        import json
        with open(cache_meta, encoding="utf-8") as f:
            meta_json = json.load(f)
        z = np.load(cache_npz, allow_pickle=True)
        return WideTable(
            grid=z["grid"],
            cols=meta_json["cols"],
            data={c: z[c] for c in meta_json["cols"]},
            switches=set(meta_json["switches"]),
            meta={k: {} for k in meta_json["cols"]},
        )

    raw = scan_raw(verbose=verbose)
    if not raw:
        raise RuntimeError("无有效数据")

    t_min = min(ts[0] for ts, _ in raw.values())
    t_max = max(ts[-1] for ts, _ in raw.values())
    t_min = t_min // 60 * 60
    t_max = (t_max // 60 + 1) * 60
    grid = np.arange(t_min, t_max, 60, dtype=np.int64)

    data: Dict[str, np.ndarray] = {}
    switches = set()
    for name, (ts, vals) in raw.items():
        sw = is_switchable(vals)
        if sw:
            switches.add(name)
        data[name] = align_to_minute(ts, vals, grid, sw)

    if verbose:
        print("宽表: %d 分钟 (%s ~ %s), %d 测点" % (
            grid.size,
            time.strftime("%m-%d %H:%M", time.localtime(grid[0])),
            time.strftime("%m-%d %H:%M", time.localtime(grid[-1])),
            len(data)))

    # 缓存
    import json
    np.savez_compressed(cache_npz, grid=grid, **{k: v for k, v in data.items()})
    with open(cache_meta, "w", encoding="utf-8") as f:
        json.dump({"cols": sorted(data.keys()), "switches": sorted(switches)},
                  f, ensure_ascii=False)
    return WideTable(grid=grid, cols=sorted(data.keys()), data=data,
                     switches=switches, meta=load_meta())


class WideTable:
    """分钟级宽表"""

    def __init__(self, grid, cols, data, switches, meta):
        self.grid = grid            # epoch 秒，int64，步长 60
        self.cols = cols
        self.data = data            # name -> np.ndarray(float)
        self.switches = switches
        self.meta = meta

    def __contains__(self, name):
        return name in self.data

    def series(self, name: str) -> np.ndarray:
        return self.data[name]

    def desc(self, name: str) -> str:
        m = self.meta.get(name)
        return (m or {}).get("desc", "") or name

    def time_str(self, i: int) -> str:
        return time.strftime("%m-%d %H:%M", time.localtime(self.grid[i]))

    def time_full(self, i: int) -> str:
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(self.grid[i]))

    def valid_ratio(self, name: str) -> float:
        return float(np.mean(~np.isnan(self.data[name])))


if __name__ == "__main__":
    wt = build_wide()
    print("\n%-34s %-16s %8s %8s %8s %8s" % ("测点", "描述", "有效率", "均值", "最小", "最大"))
    for c in wt.cols:
        v = wt.data[c]
        ok = v[~np.isnan(v)]
        if ok.size == 0:
            print("%-34s %-16s %8s" % (c, wt.desc(c)[:14], "空"))
            continue
        tag = "[开关]" if c in wt.switches else ""
        print("%-34s %-16s %7.1f%% %8.2f %8.2f %8.2f %s" % (
            c, wt.desc(c)[:14], 100 * ok.size / v.size, ok.mean(), ok.min(), ok.max(), tag))
