# -*- coding: utf-8 -*-
"""预测 PI 在线推理微服务（FastAPI）。

与 模型/infer.py 的差异：
  1. 温度控制律换成预测 PI（装配见 controller_ppi.py）
  2. 虚拟时间轴改用浮点分钟累计，不再对每拍独立取整。
     原实现 i = round(tick × interval)，在 interval=1/6（10 秒）时
     会得到重复值（实测前 12 拍为 0,0,0,0,1,1,1,1,1,2,2,2），
     导致间隙检测与节拍计时错乱。

其余（/startup、/infer、/reset、时序库取数、电流规则、输出限幅）
全部沿用 模型/ 的既有逻辑。

启动：
    python service_ppi.py                  # 0.0.0.0:9998
    python service_ppi.py --port 9998
默认端口 9998，与 模型/ 的 9999 错开，可两服务并行对拍。
"""
from __future__ import annotations

import argparse
import math
import os
import sys
import threading
from contextlib import asynccontextmanager
from typing import Dict, Optional

import yaml
from fastapi import FastAPI, HTTPException

_HERE = os.path.dirname(os.path.abspath(__file__))
_MODEL_DIR = os.path.join(os.path.dirname(_HERE), "模型")
for _p in (_HERE, _MODEL_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from config import Tag                                       # noqa: E402
from controller import Phase, XshController                  # noqa: E402
from service import XshService, SnapshotAdapter              # noqa: E402
from signal_conditioning import SignalConditioner            # noqa: E402
from tsdb_client import TSDBClient, TSDBError                # noqa: E402

import 标定参数 as P                                           # noqa: E402
from controller_ppi import make_config, attach_predictive_pi  # noqa: E402

DEFAULT_CONFIG_PATH = os.path.join(_HERE, "config.yaml")
_INIT_FIELDS = ("ratio_init", "lime_sp", "curr1_high", "speed_set")


def load_yaml_config(path: str) -> dict:
    if not path or not os.path.isfile(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _required_tags() -> Dict[str, str]:
    m: Dict[str, str] = {}
    for j in range(3):
        for k in range(3):
            m[Tag.TEMP[j][k]] = "temp%d_%d" % (j + 1, k + 1)
    m[Tag.CURR1] = "curr1"
    return m


@asynccontextmanager
async def lifespan(app: FastAPI):
    _init_state(app)
    yield


def _init_state(app: FastAPI) -> None:
    """初始化 app.state。抽成函数，供 lifespan 与懒初始化共用。

    不依赖 lifespan：某些调用方式（TestClient 直接构造、部分 ASGI 服务器）
    不触发 lifespan，只靠它会导致 KeyError。
    """
    if getattr(app.state, "_ready", False):
        return
    yml = app.state.yaml_cfg
    app.state.startup_defaults = dict(yml.get("startup") or {})
    app.state.tsdb = TSDBClient(
        base_url=str((yml.get("tsdb") or {}).get("base_url")
                     or "http://168.168.10.46:18800"),
        token=str((yml.get("tsdb") or {}).get("token") or ""),
        timeout=float((yml.get("tsdb") or {}).get("timeout") or 8.0))
    app.state.cfg = None
    app.state.svc = None
    app.state.lock = threading.Lock()
    app.state.steps = 0
    app.state.last_src = None
    app.state._ready = True


app = FastAPI(lifespan=lifespan)
app.state.yaml_cfg = load_yaml_config(DEFAULT_CONFIG_PATH)


class PPIService(XshService):
    """继承 XshService，改两处：装配预测 PI + 时间轴去抖动"""

    def __init__(self, cfg=None):
        super().__init__(cfg)
        self.ppi = None
        self._t_min = 0.0        # 浮点分钟累计

    def on_tick(self, snap: Dict[str, float],
                phase: Optional["Phase"] = None):
        if self.sc is None:
            self.sc = SignalConditioner(
                SnapshotAdapter(snap, self.cfg.control.control_interval_min),
                self.cfg)
            self.ctrl = XshController(self.sc, self.cfg)
            self.ppi = attach_predictive_pi(self.ctrl, self.cfg)
        else:
            self.sc.wt.push(snap)
            if self.ppi is None:
                self.ppi = attach_predictive_pi(self.ctrl, self.cfg)

        # 浮点分钟轴：单调累加，避免 round 造成索引重复
        t = self._t_min
        i = int(math.floor(t + 1e-9))
        out = self.ctrl.step(i, phase, data_idx=SnapshotAdapter.HIST - 1)
        self._t_min += self.cfg.control.control_interval_min
        self.tick += 1
        self.last_output = out
        return out


def _num(v, name: str) -> float:
    try:
        x = float(v)
    except (TypeError, ValueError):
        raise HTTPException(400, "字段 %s 不是数值: %r" % (name, v))
    if x != x:
        raise HTTPException(400, "字段 %s 非有限数值: %r" % (name, v))
    return x


def _apply_init(cfg, p: dict) -> None:
    if p.get("ratio_init") is not None:
        cfg.control.ratio_init = _num(p["ratio_init"], "ratio_init")
    if p.get("lime_sp") is not None:
        sp = _num(p["lime_sp"], "lime_sp")
        if sp - cfg.safety.lime_min < cfg.control.lime_band:
            raise HTTPException(400, "lime_sp=%.2f 过小" % sp)
        cfg.control.lime_field_sp = sp
    if p.get("speed_set") is not None:
        cfg.control.speed1_fixed = _num(p["speed_set"], "speed_set")


def _do_reset(p: dict) -> None:
    merged = dict(app.state.startup_defaults)
    merged.update({k: v for k, v in p.items() if v is not None})
    cfg = make_config()
    _apply_init(cfg, merged)
    app.state.cfg = cfg
    app.state.svc = PPIService(cfg)
    app.state.steps = 0


def _fetch_snapshot(p: dict) -> Dict[str, float]:
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
            raise HTTPException(503, "时序库故障: %s" % e)
        missing = [f for f in _required_tags().values() if f not in snap]
        if missing:
            raise HTTPException(503, "时序库缺测点: %s" % ", ".join(missing))
    return snap


def _infer_one(phase: Phase, p: dict) -> dict:
    _init_state(app)
    if app.state.svc is None:
        _do_reset({})
    snap = _fetch_snapshot(p)
    with app.state.lock:
        out = app.state.svc.on_tick(snap, phase=phase)
        app.state.steps += 1
    ppi = app.state.svc.ppi
    return {
        "ratio_set": round(float(out.ratio_set), 1),
        "lime_set": round(float(out.lime_set), 2),
        "speed_set": round(float(out.speed_set), 1),
        "info": {
            "phase": out.phase.value,
            "action": out.action.value,
            "reason": out.reason,
            "notes": list(out.notes),
            "temp3": None if out.temp3 != out.temp3 else round(float(out.temp3), 1),
            "curr1": None if out.curr1 != out.curr1 else round(float(out.curr1), 2),
            "src": app.state.last_src,
            "steps": app.state.steps,
            "calibrated": P.CALIBRATED,
            "ppi": ppi.snapshot() if ppi is not None else None,
        },
    }


@app.get("/health")
def health():
    _init_state(app)
    ppi = app.state.svc.ppi if app.state.svc is not None else None
    return {
        "status": "ok",
        "calibrated": P.CALIBRATED,
        "warning": None if P.CALIBRATED else (
            "标定参数.py 的 GAIN/TAU/THETA 为占位值，未经现场阶跃验证，"
            "请勿直接下控。方法见 标定说明.md"),
        "model": dict(gain=P.GAIN, tau=P.TAU, theta=P.THETA,
                      kp=P.KP, ti=P.TI),
        "control_interval_min": P.CONTROL_INTERVAL_MIN,
        "steps": app.state.steps,
        "last_src": app.state.last_src,
        "ppi": ppi.snapshot() if ppi is not None else None,
        "tsdb_base_url": app.state.tsdb.base_url,
    }


@app.post("/startup")
def startup(payload: dict = None):
    _init_state(app)
    p = payload if isinstance(payload, dict) else {}
    if p.get("reset") or any(f in p for f in _INIT_FIELDS):
        with app.state.lock:
            _do_reset(p)
    return _infer_one(Phase.STARTUP, p)


@app.post("/infer")
def infer(payload: dict = None):
    _init_state(app)
    p = payload if isinstance(payload, dict) else {}
    return _infer_one(Phase.STEADY, p)


@app.post("/reset")
def reset():
    with app.state.lock:
        app.state.cfg = None
        app.state.svc = None
        app.state.steps = 0
    return {"reset": True}


def main():
    ap = argparse.ArgumentParser(description="消石灰制备 · 预测PI 推理服务")
    ap.add_argument("--config", default=DEFAULT_CONFIG_PATH)
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=9998)
    a = ap.parse_args()
    app.state.yaml_cfg = load_yaml_config(a.config)
    import uvicorn
    uvicorn.run(app, host=a.host, port=a.port)


if __name__ == "__main__":
    main()
