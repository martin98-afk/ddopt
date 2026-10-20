# -*- coding: utf-8 -*-
"""时序库实时数据客户端。

对接现场时序库网关（工具导出配置，serverUrl http://168.168.10.46:18800）：
  GET rest/database/queryRealTimeValues?tagnames=tag1,tag2
  · tagnames：测点名列表，英文逗号分隔
  · 返回：{"code": "0", "data": [{"value": "...", "timestamp": "...",
            "status": "..."}, ...]}
  · data 元素无测点名字段时按请求顺序对应；value 为空 = 该测点未采集任何数据
  · 鉴权：Authorization: Bearer {token}（token 来自 config.yaml tsdb.token）

配置来源（优先级高到低）：
  1. infer.py 传入的构造参数（来自统一配置文件 config.yaml）
  2. 下方代码默认值
"""
from __future__ import annotations

import math
import os
import threading
from datetime import datetime
from typing import Dict, Iterable, List, Optional

import requests

DEFAULT_BASE_URL = "http://168.168.10.46:18800"
REALTIME_PATH = "/rest/database/queryRealTimeValues"


class TSDBError(RuntimeError):
    """时序库查询失败（网络/HTTP/响应无法解析）"""


def _to_float(v) -> Optional[float]:
    """宽容转数值：None/空串/NaN/非数值返回 None"""
    if v is None or isinstance(v, bool):
        return None
    s = str(v).strip()
    if not s:
        return None
    try:
        x = float(s)
    except ValueError:
        return None
    return x if math.isfinite(x) else None


class TSDBClient:
    """时序库实时值查询客户端（线程安全：requests.Session 加锁）"""

    def __init__(self, base_url: str = DEFAULT_BASE_URL, token: str = "",
                 timeout: float = 8.0):
        self.base_url = base_url.rstrip("/")
        self.token = (token or "").strip()
        self.timeout = timeout
        self._session = requests.Session()
        self._lock = threading.Lock()

    def fetch_latest(self, tags: Iterable[str],
                     now: Optional[datetime] = None) -> Dict[str, float]:
        """
        拉取一批测点的实时值，返回 {位号: 最新有效值}。
        未采集/无效的测点不出现在返回值里。整体失败抛 TSDBError。
        now 参数保留兼容签名，实时接口不使用。
        """
        tags = [t for t in tags if t]
        if not tags:
            return {}
        url = self.base_url + REALTIME_PATH
        headers = {}
        if self.token:
            headers["Authorization"] = "Bearer %s" % self.token
        try:
            with self._lock:
                resp = self._session.get(
                    url, params={"tagnames": ",".join(tags)},
                    headers=headers, timeout=self.timeout)
        except requests.RequestException as e:
            raise TSDBError("时序库请求失败: %s" % e) from e
        if resp.status_code != 200:
            raise TSDBError("时序库 HTTP %d: %s" % (resp.status_code,
                                                    resp.text[:200]))
        try:
            payload = resp.json()
        except ValueError as e:
            raise TSDBError("时序库响应非 JSON: %s" % resp.text[:200]) from e

        data = self._data_list(payload)
        if data is None:
            raise TSDBError("时序库响应无法解析: %s" % str(payload)[:200])
        return self._zip(tags, data)

    @staticmethod
    def _data_list(payload) -> Optional[List[dict]]:
        """取响应里的 data 数组；兼容 data 嵌套一层对象的情况"""
        if not isinstance(payload, dict):
            return None
        d = payload.get("data")
        if isinstance(d, list):
            return d
        if isinstance(d, dict) and isinstance(d.get("data"), list):
            return d["data"]
        return None

    @staticmethod
    def _zip(tags: List[str], data: List) -> Dict[str, float]:
        """
        把返回列表对应到位号。
        实测响应（168.168.10.46:18800 queryRealTimeValues）：
          {"tagname": "5#_XSH_1JWDZ1",
           "data": {"type": "5", "value": "", "status": "DATA_INVALID",
                    "timestamp": "1970-01-01 08:00:00"}}
        规则：优先按元素测点名字段对应，否则按请求顺序；
             value 无效或 status 含 INVALID（未采集）→ 跳过该测点。
        """
        out: Dict[str, float] = {}
        named = 0
        for item in data:
            if not isinstance(item, dict):
                continue
            name = next((item[k] for k in ("tagname", "tagName", "name", "tag")
                         if k in item and isinstance(item[k], str)), None)
            v, status = TSDBClient._item_value(item)
            if v is None or "INVALID" in status:
                continue
            if name is not None:
                for t in tags:
                    if t.strip().lower() == name.strip().lower():
                        out[t] = v
                        named += 1
                        break
            else:
                pass
        if named > 0:
            return out
        # 无测点名：按请求顺序对应
        out = {}
        idx = 0
        for item in data:
            if idx >= len(tags):
                break
            v, status = TSDBClient._item_value(item)
            if v is None or "INVALID" in status:
                idx += 1
                continue
            out[tags[idx]] = v
            idx += 1
        return out

    @staticmethod
    def _item_value(item: dict):
        """取元素的 (数值, status)：值可能在顶层 value 或内层 data.value"""
        inner = item.get("data")
        if isinstance(inner, dict):
            return _to_float(inner.get("value")), str(inner.get("status") or "")
        return _to_float(item.get("value")), str(item.get("status") or "")


if __name__ == "__main__":
    # 冒烟：按 config.yaml 直连现场库（办公网不可达时会报 TSDBError，属预期）
    import yaml

    from config import Tag
    tags = [t for row in Tag.TEMP for t in row] + [Tag.CURR1]
    cfg = {}
    yaml_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "config.yaml")
    if os.path.isfile(yaml_path):
        with open(yaml_path, "r", encoding="utf-8") as f:
            cfg = (yaml.safe_load(f) or {}).get("tsdb", {}) or {}
    c = TSDBClient(base_url=cfg.get("base_url", DEFAULT_BASE_URL),
                   token=cfg.get("token", ""),
                   timeout=float(cfg.get("timeout", 8.0)))
    vals = c.fetch_latest(tags)
    print("取到 %d/%d 个位号" % (len(vals), len(tags)))
    for k in tags:
        print("  %-24s %s" % (k, vals.get(k, "无数据")))
