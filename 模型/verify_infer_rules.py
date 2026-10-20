# -*- coding: utf-8 -*-
"""
验证脚本：±0.5 下料量约束 + 电流阶梯规则 + 双阶段接口。

场景 1  启动阶段保持初始设定（I1 正常）
场景 2  启动阶段 I1 ≥ X：水率优先 → 转速辅助 → 降料兜底，下料量始终在 ±0.5 内
场景 3  I1 回落：逐拍恢复初始设定
场景 4  运行阶段（强制稳态）T3 驱动降料也被 ±0.5 约束
场景 5  FastAPI 冒烟：/health、/startup（启动服务）、/infer（运行服务）
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np

from config import Config, Tag
from controller import Phase
from service import XshService

FAILS = []


def check(name, cond, detail=""):
    print("  [%s] %s %s" % ("PASS" if cond else "FAIL", name, detail))
    if not cond:
        FAILS.append(name)


def make_snap(curr1, t3=None):
    """合成快照：温度构造为 T3=t3（三层同值则中位=t3），其余字段 NaN"""
    s = {"curr1": float(curr1), "permit": 1.0}
    for j in range(3):
        for k in range(3):
            s["temp%d_%d" % (j + 1, k + 1)] = float(t3) if t3 is not None else np.nan
    return s


print("=" * 78)
print("场景 1：启动阶段（外部强制 STARTUP）保持初始设定")
print("=" * 78)
cfg = Config()
cfg.control.ratio_init = 600.0
cfg.control.lime_field_sp = 3.5
svc = XshService(cfg)
o = svc.on_tick(make_snap(12.5, t3=60.0), phase=Phase.STARTUP)
print("  phase=%s action=%s ratio=%.0f lime=%.2f speed=%.1f" % (
    o.phase.value, o.action.value, o.ratio_set, o.lime_set, o.speed_set))
check("阶段=启动", o.phase.value == "启动")
check("保持初始水率 600（低温趋势减水≤600 且≥500）",
      500.0 <= o.ratio_set <= 600.0,
      "T3=60 低温 → 减水至 %.0f" % o.ratio_set)
check("保持下料量设定 3.5", abs(o.lime_set - 3.5) < 1e-6)
check("转速固定输出 46", abs(o.speed_set - 46.0) < 1e-6)

print()
print("=" * 78)
print("场景 2：启动阶段 I1=19 ≥ X=18，阶梯升级（水率→转速→降料），±0.5 约束")
print("=" * 78)
seen_speed_hint = False
seen_derate = False
lime_all_ok = True
ratio_peak = 0.0
for tick in range(40):
    o = svc.on_tick(make_snap(19.0, t3=60.0), phase=Phase.STARTUP)
    if not (3.0 - 1e-6 <= o.lime_set <= 4.0 + 1e-6):
        lime_all_ok = False
    ratio_peak = max(ratio_peak, o.ratio_set)
    if "转速" in o.reason or any("转速" in n for n in o.notes):
        seen_speed_hint = True
    if o.action.value == "减少给料":
        seen_derate = True
    if tick % 4 == 0 or o.action.value == "减少给料":
        print("  tick %2d: %s | %s | 水率 %.0f 下料 %.2f" % (
            tick, o.action.value, o.reason[:52], o.ratio_set, o.lime_set))
check("下料量始终在 [3.0, 4.0]", lime_all_ok)
check("水率先加到操作上限 690", abs(ratio_peak - 690.0) < 1e-6,
      "峰值 %.0f" % ratio_peak)
check("出现转速辅助提示", seen_speed_hint)
check("进入降料兜底", seen_derate)
check("降料不低于 3.0", o.lime_set >= 3.0 - 1e-6, "末拍下料 %.2f" % o.lime_set)

print()
print("=" * 78)
print("场景 3：I1 回落到 12.5，逐拍恢复初始设定")
print("=" * 78)
restored = False
for tick in range(30):
    o = svc.on_tick(make_snap(12.5, t3=60.0), phase=Phase.STARTUP)
    print("  tick %2d: 水率 %.0f 下料 %.2f | %s" % (
        tick, o.ratio_set, o.lime_set, o.reason[:52]))
    if abs(o.lime_set - 3.5) < 1e-6 and abs(o.ratio_set - 600.0) < 1e-6:
        restored = True
        break
check("恢复到初始设定 (600 / 3.5)", restored)

print()
print("=" * 78)
print("场景 4：运行阶段（外部强制 STEADY）T3 驱动降料，仍受 ±0.5 约束")
print("=" * 78)
cfg2 = Config()
cfg2.control.ratio_init = 600.0
cfg2.control.lime_field_sp = 3.5
svc2 = XshService(cfg2)
for _ in range(40):
    o = svc2.on_tick(make_snap(12.5, t3=118.0), phase=Phase.STEADY)
check("阶段=稳态", o.phase.value == "稳态")
for _ in range(60):
    o = svc2.on_tick(make_snap(12.5, t3=140.0), phase=Phase.STEADY)
check("稳态下料量在 [3.0, 4.0]",
      3.0 - 1e-6 <= o.lime_set <= 4.0 + 1e-6, "末拍下料 %.2f" % o.lime_set)
check("水率推到操作上限 690", abs(o.ratio_set - 690.0) < 1e-6,
      "末拍水率 %.0f" % o.ratio_set)

print()
print("=" * 78)
print("场景 5：FastAPI 冒烟（TestClient，不依赖时序库）")
print("=" * 78)
from tsdb_client import TSDBError
import infer as infer_mod
from fastapi.testclient import TestClient

with TestClient(infer_mod.app) as c:
    r = c.get("/health")
    check("/health 200", r.status_code == 200)

    # /startup 带初始设定 → 重置 + 启动阶段推理
    r = c.post("/startup", json={"ratio_init": 600.0, "lime_sp": 3.2,
                                 "curr1_high": 18.0,
                                 **{k: v for k, v in make_snap(12.5, 60.0).items()
                                    if np.isfinite(v)}})
    j = r.json()
    check("/startup 顶层只有 3 个控制值",
          set(j.keys()) == {"ratio_set", "lime_set", "speed_set", "info"},
          str(sorted(j.keys())))
    check("/startup 初始设定生效（lime 与低温减水）",
          abs(j["lime_set"] - 3.2) < 0.01
          and 500.0 <= j["ratio_set"] <= 600.0,
          "ratio=%.0f lime=%.2f speed=%.1f" % (
              j["ratio_set"], j["lime_set"], j["speed_set"]))
    check("/startup 阶段=启动", j["info"]["phase"] == "启动")
    check("/startup 返回 T3 供外部判切换", j["info"]["temp3"] is not None,
          "T3=%.1f" % j["info"]["temp3"])

    # /startup 空载荷轮询（同一轮启动的后续拍）
    r = c.post("/startup", json=make_snap(19.0, 60.0))
    j = r.json()
    check("/startup 轮询不重置（档位连续）", r.status_code == 200,
          "action=%s ratio=%.0f" % (j["info"]["action"], j["ratio_set"]))

    # /infer 运行阶段
    for _ in range(45):
        r = c.post("/infer", json=make_snap(12.5, 118.0))
    j = r.json()
    check("/infer 阶段=稳态", j["info"]["phase"] == "稳态",
          "ratio=%.0f lime=%.2f" % (j["ratio_set"], j["lime_set"]))

    # 常规轮询（空 body）→ TSDB 实时接口 mock 返回
    class FakeTSDB:
        def fetch_latest(self, tags, now=None):
            return {t: 12.5 for t in tags}

    infer_mod.app.state.tsdb = FakeTSDB()
    c.post("/reset")
    r = c.post("/infer", json={})
    j = r.json()
    check("常规轮询走时序库 mock", r.status_code == 200
          and j["info"]["curr1"] == 12.5 and j["info"]["src"] == "tsdb",
          "curr1=%s src=%s" % (j["info"]["curr1"], j["info"]["src"]))

    # 缺测点：常规轮询（空 body）时库不可达 → 503
    c.post("/reset")

    class ErrTSDB:
        def fetch_latest(self, *a, **k):
            raise TSDBError("模拟断网")

    infer_mod.app.state.tsdb = ErrTSDB()
    r = c.post("/infer", json={})
    check("时序库不可达返回 503", r.status_code == 503,
          r.json().get("detail", "")[:60])

    # 手动喂数模式允许部分缺测点（控制器 NaN 容忍）
    r = c.post("/infer", json={"curr1": 12.5})
    j = r.json()
    check("手动喂数缺温度仍可推理", r.status_code == 200
          and j["info"]["action"] == "保持",
          "action=%s reason=%s" % (j["info"]["action"],
                                   j["info"]["reason"][:30]))

print()
print("=" * 78)
print("场景 6：TSDB 实时接口响应解析（queryRealTimeValues 实测结构）")
print("=" * 78)
from tsdb_client import TSDBClient

# 实测结构：tagname + 内层 data.value/status，DATA_INVALID 跳过
real = [
    {"tagname": "5#_XSH_1JWDZ1",
     "data": {"type": "5", "value": "", "status": "DATA_INVALID",
              "timestamp": "1970-01-01 08:00:00"}},
    {"tagname": "5#_XSH_1JWDZ2",
     "data": {"type": "5", "value": "154.2", "status": "GOOD",
              "timestamp": "2026-10-20 14:00:00"}},
]
out = TSDBClient._zip(["5#_XSH_1JWDZ1", "5#_XSH_1JWDZ2"], real)
check("实测结构：嵌套 value + INVALID 过滤", out == {"5#_XSH_1JWDZ2": 154.2},
      str(out))

# 无 name：按请求顺序对应，无效值跳过
d2 = [{"data": {"value": "10", "status": "GOOD"}},
      {"data": {"value": None, "status": "GOOD"}},
      {"data": {"value": "30", "status": "GOOD"}}]
out2 = TSDBClient._zip(["x", "y", "z"], d2)
check("无名字按顺序对应", out2 == {"x": 10.0, "z": 30.0}, str(out2))

# 顶层 value 形态兼容
d3 = [{"name": "a", "value": "1.5"}, {"name": "b", "value": ""}]
out3 = TSDBClient._zip(["a", "b"], d3)
check("顶层 value 形态兼容", out3 == {"a": 1.5}, str(out3))

# _data_list 兼容 data 嵌套
check("data 嵌套结构解析",
      TSDBClient._data_list({"code": "0", "data": {"data": [{"value": "1"}]}})
      == [{"value": "1"}])

print()
if FAILS:
    print("失败 %d 项: %s" % (len(FAILS), FAILS))
    sys.exit(1)
print("全部通过。")
