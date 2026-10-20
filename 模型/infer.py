# -*- coding: utf-8 -*-
"""消石灰制备控制模型 · 在线推理微服务（FastAPI）。

服务形态对齐 D:/work/脱硫脱硝/model/infer.py 参考实现，按启动/运行两个
阶段拆成两个推理端点，阶段切换由外部（DCS/上位机）判定并选择调用：

  GET  /health    健康检查
  POST /startup   启动阶段模型服务：外部持续调用。
                  温度同样走趋势闭环（现场人工在启动阶段也调水率），
                  另加一级电流按现场规则保护（水率优先 → 转速辅助 → 负荷兜底），
                  下料量限制在现场设定值 ±0.5 t/h。
                  返回体带 T3 供外部判定切换（T3 ≥ 100℃ 切运行阶段）。
  POST /infer     运行阶段模型服务：T3 ≥ 100℃ 后外部切换调用。
                  温度控制 = 趋势预测（当前温度 + 变化斜率提前干预）
                  + 相同的一级电流规则。
  POST /reset     重置为未初始化状态（下次推理重新惰性初始化）。

每次推理从时序库拉实时 9 个温度测点 + 一级电流，返回三个控制值：
  {"ratio_set": 水率设定 L/t, "lime_set": 生石灰流量设定 t/h,
   "speed_set": 一级电机转速（现阶段固定值，取实测中位 46）}
诊断信息收在 "info" 子对象。

/startup 载荷（全部可选；携带任一字段即视为新一轮启动，重置历史状态）：
  {"ratio_init": 600.0,   # 初始水率 L/t
   "lime_sp": 3.0,        # 现场下料量设定值 t/h（调节范围 ±0.5）
   "curr1_high": 18.0,    # 一级电流上限 X (A)
   "speed_set": 46.0}     # 一级电机转速固定输出值

/infer 载荷（可选）：{"temp1_1": ..., ..., "curr1": ...} 直接覆盖测点
（离线测试 / 时序库故障兜底）。

用法：
  python infer.py                              # 读同目录 config.yaml，0.0.0.0:9999
  python infer.py --config my.yaml --port 10030
"""
from __future__ import annotations

import argparse
import os
import sys
import threading
from contextlib import asynccontextmanager
from typing import Dict, Optional

import yaml
from fastapi import FastAPI, HTTPException

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from config import Config, Tag
from controller import Phase
from service import XshService
from tsdb_client import TSDBClient, TSDBError

DEFAULT_CONFIG_PATH = os.path.join(_HERE, "config.yaml")
# /startup 载荷里视为「新一轮启动」的字段
_INIT_FIELDS = ("ratio_init", "lime_sp", "curr1_high", "speed_set")


def load_yaml_config(path: str) -> dict:
    """读统一配置文件；文件缺失/为空返回 {}（全回落代码默认值）"""
    if not path or not os.path.isfile(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _required_tags() -> Dict[str, str]:
    """推理需要的实时位号 → 快照字段映射（9 温度测点 + 一级电流）"""
    m: Dict[str, str] = {}
    for j in range(3):
        for k in range(3):
            m[Tag.TEMP[j][k]] = "temp%d_%d" % (j + 1, k + 1)
    m[Tag.CURR1] = "curr1"
    return m


@asynccontextmanager
async def lifespan(app: FastAPI):
    yml = app.state.yaml_cfg
    app.state.startup_defaults: dict = dict(yml.get("startup") or {})
    app.state.tsdb = TSDBClient(
        base_url=str((yml.get("tsdb") or {}).get("base_url")
                     or "http://168.168.10.46:18800"),
        token=str((yml.get("tsdb") or {}).get("token") or ""),
        timeout=float((yml.get("tsdb") or {}).get("timeout") or 8.0))
    app.state.cfg: Optional[Config] = None
    app.state.svc: Optional[XshService] = None
    app.state.lock = threading.Lock()
    app.state.steps = 0
    app.state.last_src = None
    yield


app = FastAPI(lifespan=lifespan)
app.state.yaml_cfg: dict = load_yaml_config(DEFAULT_CONFIG_PATH)


# ============================================================ 辅助
def _num(v, name: str) -> float:
    try:
        x = float(v)
    except (TypeError, ValueError):
        raise HTTPException(400, "字段 %s 不是数值: %r" % (name, v))
    if x != x:      # NaN
        raise HTTPException(400, "字段 %s 非有限数值: %r" % (name, v))
    return x


def _apply_init(cfg: Config, p: dict) -> None:
    """把现场初始设定写进配置"""
    if p.get("ratio_init") is not None:
        cfg.control.ratio_init = _num(p["ratio_init"], "ratio_init")
    if p.get("lime_sp") is not None:
        sp = _num(p["lime_sp"], "lime_sp")
        if sp - cfg.safety.lime_min < cfg.control.lime_band:
            # 设定值太靠近绝对下限时 ±0.5 带会被裁掉，提前暴露问题
            raise HTTPException(400, "lime_sp=%.2f 过小：设定值-0.5 将低于"
                                     "绝对下限 %.1f" % (sp, cfg.safety.lime_min))
        cfg.control.lime_field_sp = sp
    if p.get("curr1_high") is not None:
        try:
            cfg.set_curr1_high(_num(p["curr1_high"], "curr1_high"))
        except ValueError as e:
            raise HTTPException(400, str(e))
    if p.get("speed_set") is not None:
        cfg.control.speed1_fixed = _num(p["speed_set"], "speed_set")


# config.yaml control 段 → ControlParams 字段映射（趋势控制参数）
_CONTROL_KEYS = ("trend_kp", "trend_predict_min", "trend_dead",
                 "trend_dead_slope", "trend_step_max", "trend_step_fast",
                 "trend_slope_window", "trend_ratio_lo",
                 "temp3_fast_high", "temp3_fast_low")


def _apply_control(cfg: Config, yml: dict) -> None:
    """把 config.yaml 的 control 段（趋势控制参数）写进配置；
    缺字段回落 config.py 默认值"""
    ctl = yml.get("control") or {}
    for k in _CONTROL_KEYS:
        if ctl.get(k) is not None:
            setattr(cfg.control, k, _num(ctl[k], "control.%s" % k))
    if ctl.get("target") is not None:
        cfg.safety.temp3_target = _num(ctl["target"], "control.target")


def _do_reset(p: dict) -> None:
    """新一轮启动：config.yaml startup 段为基准，载荷字段覆盖；
    新配置 + 新服务实例 = 历史缓冲与控制器状态全部归零"""
    merged = dict(app.state.startup_defaults)
    merged.update({k: v for k, v in p.items() if v is not None})
    cfg = Config()
    _apply_control(cfg, app.state.yaml_cfg)   # 趋势控制参数
    _apply_init(cfg, merged)
    app.state.cfg = cfg
    app.state.svc = XshService(cfg)     # 惰性构建：首次 on_tick 才建控制器
    app.state.steps = 0
    app.state.last_src = None


def _fetch_snapshot(p: dict) -> Dict[str, float]:
    """
    组装快照。两种模式：
      · 手动喂数：载荷含任一测点字段 → 全部以此为准，不访问时序库
        （离线测试 / 时序库故障兜底，零网络等待）
      · 常规轮询：载荷为空 → 时序库拉实时 9 温度 + 一级电流
    """
    snap: Dict[str, float] = {}
    manual = any(f in p for f in _required_tags().values())
    if manual:
        for field in _required_tags().values():
            if field in p:
                snap[field] = _num(p[field], field)
        app.state.last_src = "payload"
    else:
        try:
            vals = app.state.tsdb.fetch_latest(_required_tags().keys())
            for tag, field in _required_tags().items():
                if tag in vals:
                    snap[field] = float(vals[tag])
            app.state.last_src = "tsdb" if vals else None
        except TSDBError as e:
            raise HTTPException(503, "时序库故障: %s（可在请求体中直接传入测点值兜底）"
                                     % e)
        missing = [f for f in _required_tags().values() if f not in snap]
        if missing:
            raise HTTPException(503, "时序库缺测点: %s" % ", ".join(missing))
    return snap


def _infer_one(phase: Phase, p: dict) -> dict:
    if app.state.svc is None:
        _do_reset({})       # 未显式初始化：用配置默认值惰性启动
    snap = _fetch_snapshot(p)
    with app.state.lock:
        out = app.state.svc.on_tick(snap, phase=phase)
        app.state.steps += 1
    cfg = app.state.cfg
    return {
        # ---- 三个控制值（模型输出）----
        "ratio_set": round(float(out.ratio_set), 1),
        "lime_set": round(float(out.lime_set), 2),
        "speed_set": round(float(out.speed_set), 1),
        # ---- 诊断信息（不参与下控）----
        "info": {
            "phase": out.phase.value,
            "action": out.action.value,
            "reason": out.reason,
            "notes": list(out.notes),
            "temp1": None if out.temp1 != out.temp1 else round(float(out.temp1), 1),
            "temp2": None if out.temp2 != out.temp2 else round(float(out.temp2), 1),
            "temp3": None if out.temp3 != out.temp3 else round(float(out.temp3), 1),
            "curr1": None if out.curr1 != out.curr1 else round(float(out.curr1), 2),
            "lime_band": [round(cfg.control.lime_field_sp - cfg.control.lime_band, 2),
                          round(cfg.control.lime_field_sp + cfg.control.lime_band, 2)],
            "src": app.state.last_src,
            "steps": app.state.steps,
        },
    }


# ============================================================ 路由
@app.get("/health")
def health():
    cfg = app.state.cfg
    svc: Optional[XshService] = app.state.svc
    o = svc.last_output if svc is not None else None
    d = app.state.startup_defaults
    return {
        "status": "ok",
        "started": svc is not None,
        "steps": app.state.steps,
        "last_src": app.state.last_src,
        "ratio_init": cfg.control.ratio_init if cfg else d.get("ratio_init"),
        "lime_sp": cfg.control.lime_field_sp if cfg else d.get("lime_sp"),
        "lime_band": None if cfg is None else cfg.control.lime_band,
        "speed_set": cfg.control.speed1_fixed if cfg else d.get("speed_set"),
        "curr1_high": cfg.safety.curr1_high if cfg else d.get("curr1_high"),
        "curr1_trip": None if cfg is None else cfg.safety.curr1_trip,
        "tsdb_base_url": app.state.tsdb.base_url,
        "tsdb_token_set": bool(app.state.tsdb.token),
        "last_output": None if o is None else {
            "ratio_set": round(float(o.ratio_set), 1),
            "lime_set": round(float(o.lime_set), 2),
            "speed_set": round(float(o.speed_set), 1),
            "phase": o.phase.value,
        },
    }


@app.post("/startup")
def startup(payload: dict = None):
    """启动阶段模型服务（外部持续调用）。

    启动阶段同样走趋势闭环（现场人工在启动阶段也调水率），
    另加一级电流规则的负荷保护，下料量限制在现场设定值 ±0.5 t/h。
    返回体带 T3，外部据其判定切换运行阶段（T3 ≥ 100℃）。

    载荷可选；携带任一初始设定字段（或 "reset": true）即重置历史状态，
    视为新一轮启动。之后的轮询调用传 {} 即可。
    """
    p = payload if isinstance(payload, dict) else {}
    if p.get("reset") or any(f in p for f in _INIT_FIELDS):
        with app.state.lock:
            _do_reset(p)
    return _infer_one(Phase.STARTUP, p)


@app.post("/infer")
def infer(payload: dict = None):
    """运行阶段模型服务（T3 ≥ 100℃ 后由外部切换调用）。

    温度控制 = 趋势预测（预测温度 + 变化斜率提前干预）+ 相同一级电流规则。
    """
    p = payload if isinstance(payload, dict) else {}
    return _infer_one(Phase.STEADY, p)


@app.post("/reset")
def reset(payload: dict = None):
    """重置为未初始化状态（下次推理时重新惰性初始化）。"""
    with app.state.lock:
        app.state.cfg = None
        app.state.svc = None
        app.state.steps = 0
        app.state.last_src = None
    return {"reset": True}


def main():
    ap = argparse.ArgumentParser(description="消石灰制备模型推理微服务")
    ap.add_argument("--config", default=DEFAULT_CONFIG_PATH,
                    help="统一配置文件路径（默认同目录 config.yaml）")
    ap.add_argument("--host", default=None, help="覆盖配置文件 server.host")
    ap.add_argument("--port", type=int, default=None, help="覆盖配置文件 server.port")
    ap.add_argument("--ratio-init", type=float, default=None,
                    help="覆盖配置文件 startup.ratio_init")
    ap.add_argument("--lime-sp", type=float, default=None,
                    help="覆盖配置文件 startup.lime_sp")
    ap.add_argument("--curr1-high", type=float, default=None,
                    help="覆盖配置文件 startup.curr1_high")
    ap.add_argument("--speed-set", type=float, default=None,
                    help="覆盖配置文件 startup.speed_set")
    a = ap.parse_args()

    app.state.yaml_cfg = load_yaml_config(a.config)
    srv = app.state.yaml_cfg.get("server") or {}
    host = a.host if a.host is not None else srv.get("host", "0.0.0.0")
    port = a.port if a.port is not None else int(srv.get("port", 9999))

    # 命令行给了初始设定则作为覆盖项并入 startup 默认
    overrides = {k: v for k, v in (("ratio_init", a.ratio_init),
                                   ("lime_sp", a.lime_sp),
                                   ("curr1_high", a.curr1_high),
                                   ("speed_set", a.speed_set)).items()
                 if v is not None}
    if overrides:
        app.state.startup_defaults = dict(app.state.startup_defaults) \
            if hasattr(app.state, "startup_defaults") else \
            dict(app.state.yaml_cfg.get("startup") or {})
        app.state.startup_defaults.update(overrides)

    import uvicorn
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
