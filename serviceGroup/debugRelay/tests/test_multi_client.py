"""
debugRelay 多客户端管理集成测试。

覆盖核心场景（SC01/SC02/SC03/SC04/SC05/SC07）：
- 多游戏端同时连接，各自独立缓冲
- 浏览器按订阅隔离（replay 只含所订阅客户端的数据）
- 切换订阅后面板按新客户端重建
- REST 单客户端回退 / 多客户端必须显式定位
- 客户端断开不影响其他客户端

用 FastAPI TestClient + 嵌套 websocket_connect，replay/REST 为 pull 式（无 WS receive 阻塞竞态）。
"""
import json
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# 让 debug_relay 可导入（tests/ 的父目录 = debugRelay/）
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import debug_relay as dr  # noqa: E402


# ---- fixtures ----

@pytest.fixture
def relay(tmp_path):
    """每个测试用独立状态：清空注册表 + 指向临时 events 目录 + 关白名单。"""
    dr.events_dir = tmp_path / "events"
    dr.events_dir.mkdir(parents=True, exist_ok=True)
    dr.src_dir = None
    dr.whitelist_enabled = False
    dr.clients.clear()
    dr.browsers.clear()
    dr._client_counter = 0
    yield
    dr.clients.clear()
    dr.browsers.clear()


# ---- helpers ----

def _console(content, level="log"):
    return {"type": f"console_{level}", "content": content, "ts": "2026-07-14T00:00:00"}


def _wait_clients(client, n, timeout=3.0):
    """轮询 /api/clients 直到客户端数 == n，返回按 id 排序的客户端摘要列表。"""
    deadline = time.time() + timeout
    last = []
    while time.time() < deadline:
        r = client.get("/api/clients").json()
        last = r.get("clients", [])
        if len(last) == n:
            return sorted(last, key=lambda c: c["id"])
        time.sleep(0.05)
    raise AssertionError(f"expected {n} clients, got {len(last)}: {last}")


def _poll_console(client, client_id, needle, timeout=3.0):
    """轮询 /api/console?client= 直到出现 needle，返回 messages。"""
    deadline = time.time() + timeout
    last = []
    while time.time() < deadline:
        url = f"/api/console?client={client_id}&limit=2000"
        last = client.get(url).json().get("messages", [])
        if any(m.get("content") == needle for m in last):
            return last
        time.sleep(0.05)
    return last


def _recv_until(ws, want_type, max_msgs=30):
    """从 WS 连续接收直到 type 匹配；防止永久阻塞（上限 max_msgs 条）。"""
    for _ in range(max_msgs):
        msg = ws.receive_json()
        if msg.get("type") == want_type:
            return msg
    raise AssertionError(f"did not receive {want_type} within {max_msgs} messages")


# ---- tests ----

def test_two_games_connect_independent(relay):
    """SC01: 两个游戏端同时连同一 relay，互不踢掉。"""
    with TestClient(dr.app) as client:
        with client.websocket_connect("/ws/game") as ga, \
                client.websocket_connect("/ws/game") as gb:
            summary = _wait_clients(client, 2)
            assert {c["id"] for c in summary} == {"c1", "c2"}
            # 标签含序号 + IP
            assert summary[0]["label"].startswith("#1 ·")
            assert summary[1]["label"].startswith("#2 ·")
            # 两条 WS 仍开（未抛异常即代表未被踢）


def test_buffer_isolation_per_client(relay):
    """SC02 核心：c1 的 console 不进入 c2 的缓冲（REST pull 验证，无竞态）。"""
    with TestClient(dr.app) as client:
        with client.websocket_connect("/ws/game") as ga, \
                client.websocket_connect("/ws/game") as gb:
            ids = [c["id"] for c in _wait_clients(client, 2)]
            ga.send_text(json.dumps(_console("fromA")))
            gb.send_text(json.dumps(_console("fromB")))

            a_msgs = _poll_console(client, ids[0], "fromA")
            assert any(m["content"] == "fromA" for m in a_msgs)
            assert all(m["content"] != "fromB" for m in a_msgs), \
                "c2 的消息泄漏到 c1 的缓冲"

            b_msgs = _poll_console(client, ids[1], "fromB")
            assert any(m["content"] == "fromB" for m in b_msgs)
            assert all(m["content"] != "fromA" for m in b_msgs), \
                "c1 的消息泄漏到 c2 的缓冲"


def test_browser_replay_isolated(relay):
    """SC02/SC03：浏览器订阅 c1 只 replay c1 的历史，切到 c2 只看 c2。"""
    with TestClient(dr.app) as client:
        with client.websocket_connect("/ws/game") as ga, \
                client.websocket_connect("/ws/game") as gb:
            ids = [c["id"] for c in _wait_clients(client, 2)]
            ga.send_text(json.dumps(_console("fromA")))
            gb.send_text(json.dumps(_console("fromB")))
            # 确保两端都已缓冲
            _poll_console(client, ids[0], "fromA")
            _poll_console(client, ids[1], "fromB")

            # 浏览器 X 订阅 c1
            with client.websocket_connect("/ws/browser") as bx:
                bx.send_text(json.dumps({"type": "select_client", "client_id": ids[0]}))
                batch = _recv_until(bx, "console_batch")
                assert batch["client_id"] == ids[0]
                contents = [m["content"] for m in batch["messages"]]
                assert "fromA" in contents
                assert "fromB" not in contents, "订阅 c1 却 replay 到 c2 的消息"

            # 浏览器 Y 订阅 c2
            with client.websocket_connect("/ws/browser") as by:
                by.send_text(json.dumps({"type": "select_client", "client_id": ids[1]}))
                batch = _recv_until(by, "console_batch")
                assert batch["client_id"] == ids[1]
                contents = [m["content"] for m in batch["messages"]]
                assert "fromB" in contents
                assert "fromA" not in contents


def test_rest_single_client_fallback(relay):
    """SC04：仅 1 个客户端时，REST 不带 client 参数自动回退（向后兼容现有 MCP 调用）。"""
    with TestClient(dr.app) as client:
        with client.websocket_connect("/ws/game") as ga:
            _wait_clients(client, 1)
            ga.send_text(json.dumps(_console("only-one")))
            # 不带 client 参数（单客户端回退）
            msgs = _poll_console_no_client(client, "only-one")
            assert any(m["content"] == "only-one" for m in msgs)


def _poll_console_no_client(client, needle, timeout=3.0):
    deadline = time.time() + timeout
    last = []
    while time.time() < deadline:
        last = client.get("/api/console?limit=2000").json().get("messages", [])
        if any(m.get("content") == needle for m in last):
            return last
        time.sleep(0.05)
    return last


def test_rest_multi_requires_client(relay):
    """SC05：多客户端时 REST 必须显式 ?client=，否则 409 + 列出可选 id。"""
    with TestClient(dr.app) as client:
        with client.websocket_connect("/ws/game") as ga, \
                client.websocket_connect("/ws/game") as gb:
            ids = [c["id"] for c in _wait_clients(client, 2)]
            r = client.get("/api/console?limit=500")
            assert r.status_code == 409
            body = r.json()
            listed = [c["id"] for c in body.get("clients", [])]
            assert set(listed) == set(ids)
            # 带 client 正常
            r2 = client.get(f"/api/console?client={ids[0]}&limit=500")
            assert r2.status_code == 200


def test_rest_client_not_found(relay):
    with TestClient(dr.app) as client:
        with client.websocket_connect("/ws/game") as ga:
            _wait_clients(client, 1)
            r = client.get("/api/console?client=c999&limit=500")
            assert r.status_code == 404


def test_disconnect_isolation(relay):
    """SC07：c1 断开不影响 c2，/api/clients 移除 c1。"""
    with TestClient(dr.app) as client:
        with client.websocket_connect("/ws/game") as ga:
            with client.websocket_connect("/ws/game") as gb:
                _wait_clients(client, 2)
            # gb 关闭
            remaining = _wait_clients(client, 1)
            assert len(remaining) == 1


def test_client_list_pushed_to_browser(relay):
    """浏览器连接立即收到 client_list；游戏上下线后 client_list 更新。"""
    with TestClient(dr.app) as client:
        with client.websocket_connect("/ws/browser") as bx:
            first = _recv_until(bx, "client_list")
            assert first["clients"] == []
            with client.websocket_connect("/ws/game") as ga:
                upd = _recv_until(bx, "client_list")
                assert len(upd["clients"]) == 1
            # 游戏断开后 server 广播 client_list（clients=[]）
            emptied = _recv_until(bx, "client_list")
            assert emptied["clients"] == []
