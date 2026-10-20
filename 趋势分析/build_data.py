# -*- coding: utf-8 -*-
"""
消石灰制备数据预处理脚本
解析 脱硫脱硝消石灰制备数据/ 下的 zip 历史数据 + 测点清单 CSV，
生成趋势分析页面用的 data.js（模拟量分钟级降采样 + 开关量变化点 + 分布统计）。
纯标准库实现，直接运行：python build_data.py
"""
import base64
import csv
import glob
import heapq
import json
import os
import struct
import sys
import time
import zipfile

BASE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(os.path.dirname(BASE), "脱硫脱硝消石灰制备数据")
OUT_JS = os.path.join(BASE, "data.js")

# 无效时间戳阈值（1970 数据直接丢弃）
MIN_TS = 1577836800  # 2020-01-01
# 直方图分位截断与 bin 数
HIST_PLO, HIST_PHI, HIST_BINS = 0.01, 0.99, 50


def parse_ts(s):
    """解析 ' 2026-10-16 14:00:00.000' -> epoch 秒（本地时区），带日期缓存"""
    s = s.strip()
    date, hms = s[:10], s[11:19]
    day0 = _day_cache.get(date)
    if day0 is None:
        day0 = int(time.mktime(time.strptime(date, "%Y-%m-%d")))
        _day_cache[date] = day0
    return day0 + int(hms[:2]) * 3600 + int(hms[3:5]) * 60 + int(hms[6:8])


_day_cache = {}


def load_meta():
    """读独立测点清单 CSV：测点名 -> {desc, unit, ptype}"""
    meta = {}
    for fp in glob.glob(os.path.join(DATA_DIR, "5#_XSH_*.csv")):
        with open(fp, encoding="utf-8-sig", errors="replace", newline="") as f:
            reader = csv.reader(f)
            header = next(reader, None)
            if not header:
                continue
            idx = {name: i for i, name in enumerate(header)}
            i_name = idx.get("测点名称")
            i_type = idx.get("点类型（开关量、模拟量、控制点、打包点）")
            i_unit = idx.get("测点单位")
            i_desc = idx.get("描述")
            if i_name is None:
                continue
            for row in reader:
                if len(row) <= i_name or not row[i_name]:
                    continue
                meta[row[i_name]] = {
                    "ptype": row[i_type].strip() if i_type is not None and i_type < len(row) else "",
                    "unit": row[i_unit].strip() if i_unit is not None and i_unit < len(row) else "",
                    "desc": row[i_desc].strip() if i_desc is not None and i_desc < len(row) else "",
                }
    return meta


def scan_zips():
    """扫描 zip：name -> [(src_idx, rows)...]，rows 为每 zip 内 (ts, val) 列表"""
    zips = sorted(glob.glob(os.path.join(DATA_DIR, "dbName_db101-*.zip")))
    if not zips:
        print("未找到 zip 数据文件: %s" % DATA_DIR)
        sys.exit(1)
    merged = {}   # name -> list of (ts, val) list（每 zip 一段）
    for zi, zp in enumerate(zips):
        z = zipfile.ZipFile(zp)
        n_rows = 0
        for entry in z.namelist():
            if not entry.lower().endswith(".csv"):
                continue
            with z.open(entry) as f:
                text = f.read().decode("utf-8", errors="replace")
            lines = text.splitlines()
            if len(lines) < 3:
                continue
            # 第 1 行: "","测点名","描述"
            name_line = next(csv.reader([lines[0]]), None)
            if not name_line or len(name_line) < 2:
                continue
            name = name_line[1].strip()
            ts_list, v_list = [], []
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
                n_rows += len(ts_list)
        z.close()
        print("  [%d/%d] %s  (%.1f 万行)" % (zi + 1, len(zips), os.path.basename(zp), n_rows / 1e4))
    return merged


def merge_sort(segments):
    """多段有序数据归并 + 按时间去重，返回 (ts_list, v_list)"""
    if not segments:
        return [], []
    streams = [zip(seg[0], seg[1]) for seg in segments]
    ts_out, v_out = [], []
    last_ts = None
    for ts, v in heapq.merge(*streams):
        if ts == last_ts:
            continue
        last_ts = ts
        ts_out.append(ts)
        v_out.append(v)
    return ts_out, v_out


def percentile(sorted_v, p):
    if not sorted_v:
        return 0.0
    i = min(len(sorted_v) - 1, max(0, int(p * len(sorted_v))))
    return sorted_v[i]


def downsample_minute(ts_list, v_list):
    """1 分钟窗口均值降采样 -> (分钟偏移列表, 均值列表)"""
    acc = {}
    for ts, v in zip(ts_list, v_list):
        m = ts // 60
        a = acc.get(m)
        if a is None:
            acc[m] = [v, 1]
        else:
            a[0] += v
            a[1] += 1
    minutes = sorted(acc)
    vals = [acc[m][0] / acc[m][1] for m in minutes]
    return minutes, vals


def build_stats_hist(v_list):
    """秒级原始数据统计 + 直方图（p1~p99 范围 50 bin，两端溢出单独计）"""
    sv = sorted(v_list)
    n = len(sv)
    stats = {
        "min": sv[0], "max": sv[-1],
        "mean": sum(v_list) / n,
        "p1": percentile(sv, HIST_PLO), "p5": percentile(sv, 0.05),
        "p25": percentile(sv, 0.25), "p50": percentile(sv, 0.50),
        "p75": percentile(sv, 0.75), "p95": percentile(sv, 0.95),
        "p99": percentile(sv, HIST_PHI),
    }
    var = sum((x - stats["mean"]) ** 2 for x in v_list) / n
    stats["std"] = var ** 0.5
    lo, hi = stats["p1"], stats["p99"]
    if hi <= lo:
        hi = lo + max(abs(lo) * 1e-6, 1e-6)
    step = (hi - lo) / HIST_BINS
    counts = [0] * HIST_BINS
    out_lo = out_hi = 0
    for x in v_list:
        if x < lo:
            out_lo += 1
        elif x > hi:
            out_hi += 1
        else:
            counts[min(HIST_BINS - 1, int((x - lo) / step))] += 1
    hist = {"lo": lo, "hi": hi, "counts": counts, "outLo": out_lo, "outHi": out_hi}
    return stats, hist


def b64_u16(arr):
    return base64.b64encode(struct.pack("<%dH" % len(arr), *arr)).decode()


def b64_u8(arr):
    return base64.b64encode(struct.pack("<%dB" % len(arr), *arr)).decode()


def b64_f32(arr):
    return base64.b64encode(struct.pack("<%df" % len(arr), *arr)).decode()


def main():
    t_start = time.time()
    print("1/4 读取测点清单元数据 ...")
    meta = load_meta()
    print("     清单测点数: %d" % len(meta))

    print("2/4 扫描 zip 数据包 ...")
    merged = scan_zips()
    print("     实际含数据测点数: %d" % len(merged))

    print("3/4 合并、降采样、统计 ...")
    points = {}
    t0_global = None
    done = 0
    for name, segments in merged.items():
        ts_list, v_list = merge_sort(segments)
        if not ts_list:
            continue
        t_start_p, t_end_p = ts_list[0], ts_list[-1]
        if t0_global is None:
            t0_global = t_start_p
        m = meta.get(name, {})
        ptype = m.get("ptype", "")
        # 值域优先判定：清单点类型字段常误标（全写模拟量），值域 ⊆{0,1} 即开关量
        vs = set(v_list[:20000])
        if vs and vs <= {0.0, 1.0}:
            ptype = "开关量"
        is_switch = "开关量" in ptype
        entry = {
            "desc": m.get("desc") or "", "unit": m.get("unit") or "",
            "ptype": ptype, "t0": t_start_p,
            "span": [t_start_p, t_end_p], "rawN": len(ts_list),
        }
        if is_switch:
            ct, cv = [], []
            prev = None
            for ts, v in zip(ts_list, v_list):
                if prev is None or v != prev:
                    ct.append(ts // 60 - t_start_p // 60)
                    cv.append(int(v))
                    prev = v
            entry["ct"] = b64_u16(ct)
            entry["cv"] = b64_u8(cv)
            on_n = sum(1 for x in v_list if x != 0)
            entry["onRatio"] = round(on_n / len(v_list), 4)
        else:
            minutes, vals = downsample_minute(ts_list, v_list)
            entry["ts"] = b64_u16([mm - t_start_p // 60 for mm in minutes])
            entry["v"] = b64_f32(vals)
            stats, hist = build_stats_hist(v_list)
            entry["stats"] = {k: round(x, 6) for k, x in stats.items()}
            entry["hist"] = hist
        points[name] = entry
        done += 1
        if done % 10 == 0:
            print("     %d/%d ..." % (done, len(merged)))

    print("4/4 写出 data.js ...")
    buf = ['{"generated":%s,"t0Global":%s,"points":{' % (
        json.dumps(time.strftime("%Y-%m-%d %H:%M:%S")), json.dumps(t0_global))]
    for i, (name, e) in enumerate(points.items()):
        if i:
            buf.append(",")
        buf.append(json.dumps(name, ensure_ascii=False) + ":" + json.dumps(e, ensure_ascii=False))
    buf.append("}}")
    with open(OUT_JS, "w", encoding="utf-8") as f:
        f.write("window.XSH_DATA=" + "".join(buf) + ";")

    size_mb = os.path.getsize(OUT_JS) / 1e6
    n_sim = sum(1 for e in points.values() if e["ptype"] != "开关量")
    n_sw = len(points) - n_sim
    print("完成: %s" % OUT_JS)
    print("  测点: %d (模拟量 %d / 开关量 %d), 文件大小 %.2f MB, 耗时 %.1fs" % (
        len(points), n_sim, n_sw, size_mb, time.time() - t_start))


if __name__ == "__main__":
    main()
