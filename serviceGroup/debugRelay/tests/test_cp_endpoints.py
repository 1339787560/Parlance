# -*- coding: utf-8 -*-
"""CP 测试面端点集成测试（FastAPI TestClient — 不起服务、不占端口、不动本机在跑的 relay）。

覆盖:
- GET  /api/cp/modules  清单形状 + 读写标记（不依赖客户端）
- POST /api/cp/call     未登记 module/req → 400（白名单）
- POST /api/cp/call     白名单通过但无客户端连接 → 409（证明走到了 _resolve_client）

运行: cd serviceGroup/debugRelay && python -m pytest tests/test_cp_endpoints.py -v
"""
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# 让 debug_relay 可导入（tests/ 的父目录 = debugRelay/）
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import debug_relay as dr  # noqa: E402


@pytest.fixture
def client(tmp_path):
    """独立状态：临时 events 目录 + 清空注册表 + 关白名单（同 test_multi_client 约定）。"""
    dr.events_dir = tmp_path / "events"
    dr.events_dir.mkdir(parents=True, exist_ok=True)
    dr.src_dir = None
    dr.whitelist_enabled = False
    dr.clients.clear()
    dr.browsers.clear()
    dr._client_counter = 0
    with TestClient(dr.app) as c:
        yield c
    dr.clients.clear()
    dr.browsers.clear()


def test_cp_modules_endpoint(client):
    r = client.get("/api/cp/modules")
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["count"] == 43
    assert data["namespace_count"] == 13
    assert data["categories"][0] == "award"

    ns = data["namespaces"]
    assert "cp.award" in ns
    read = ns["cp.award"]["queryAdVideoCfg"]
    assert read["ro"] is True and read["params"] == {}
    write = ns["cp.award"]["takeAdVideoGift_v2"]
    assert write["ro"] is False, "写操作必须 ro=False（UI 据此标 [写]）"
    # 命名参数: dict + arity
    relic = ns["cp.award"]["takeReliefReward_v2"]
    assert relic["arity"] == 3 and isinstance(relic["params"], dict)


def test_cp_call_rejects_unregistered(client):
    r = client.post("/api/cp/call", json={"module": "award", "req": "noSuchReq"})
    assert r.status_code == 400
    assert "未登记" in r.json()["error"]

    r2 = client.post("/api/cp/call", json={"module": "noSuchModule", "req": "queryAdVideoCfg"})
    assert r2.status_code == 400


def test_cp_call_no_client_409(client):
    """白名单通过 → 进 _resolve_client → 无客户端 409（不是 400/404）。"""
    r = client.post("/api/cp/call", json={"module": "luckyturntable", "req": "queryLuckyTurntableConfig"})
    assert r.status_code == 409
    assert "no game client" in r.json()["error"]
