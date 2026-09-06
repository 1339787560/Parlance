#!/usr/bin/env python3
"""session-registry meta 字段测试（rolemanager配置化重构 T1）。

覆盖测试用例文档「registry meta 模块」U1-U4 + E1（双写者互不覆盖）。
运行：cd infoserver 仓根 && .venv/bin/pytest serviceGroup/sessionRegistry/test_meta.py -v
"""

import json
import time

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """隔离 DATA_FILE 到 tmp_path，重置内存 store。

    ⚠ 禁用 importlib.reload：reload 会重执行模块把 DATA_FILE 重置回真实路径，
    覆盖 monkeypatch → 测试写穿生产数据文件（2026-09-05 曾因此污染一次）。
    路由函数运行时读模块全局 DATA_FILE，setattr 后不 reload 即生效。
    """
    import main as m

    monkeypatch.setattr(m, "DATA_DIR", tmp_path)
    monkeypatch.setattr(m, "DATA_FILE", tmp_path / "session-registry.json")
    m._store = {}
    with TestClient(m.app) as c:
        yield c
    m._store = {}


def _get(client, owner="extension", agent_id="agent-1"):
    r = client.get(f"/sessions/{owner}/{agent_id}")
    assert r.status_code == 200, r.text
    return r.json()


# ---------- U1: register 不带 meta 键，已有 meta 保留 ----------

def test_register_without_meta_preserves_existing(client):
    client.post("/sessions/register", json={
        "owner": "extension", "agent_id": "agent-1",
        "meta": {"prompt_ledger": {"gen": 1, "injected": {"common": {"hash": "a1"}}}},
    })
    # 宿主 30s 全量重报：不带 meta 键
    r = client.post("/sessions/register", json={
        "owner": "extension", "agent_id": "agent-1", "session_id": "ses_x", "cli": "opencode",
    })
    assert r.status_code == 200
    assert r.json()["meta"]["prompt_ledger"]["injected"]["common"]["hash"] == "a1"
    assert r.json()["session_id"] == "ses_x"


# ---------- U2: register 带 meta，顶层键深合并，他人键不丢 ----------

def test_register_meta_top_level_deep_merge(client):
    client.post("/sessions/register", json={
        "owner": "extension", "agent_id": "agent-1",
        "meta": {"prompt_ledger": {"gen": 1}, "other_writer_key": {"keep": True}},
    })
    r = client.post("/sessions/register", json={
        "owner": "extension", "agent_id": "agent-1",
        "meta": {"prompt_ledger": {"gen": 2, "injected": {"common": {"hash": "b2"}}}},
    })
    meta = r.json()["meta"]
    assert meta["prompt_ledger"]["gen"] == 2  # 同键覆盖（快照语义）
    assert meta["other_writer_key"] == {"keep": True}  # 异键保留


# ---------- U3: PUT 不存在记录 → 404 ----------

def test_update_missing_record_404(client):
    r = client.put("/sessions/extension/agent-nope", json={"meta": {"x": 1}})
    assert r.status_code == 404


# ---------- U3b: PUT 带 meta 合并 + 不带 meta 保留 ----------

def test_update_meta_merge_and_preserve(client):
    client.post("/sessions/register", json={
        "owner": "extension", "agent_id": "agent-1",
        "meta": {"prompt_ledger": {"gen": 1}},
    })
    r = client.put("/sessions/extension/agent-1", json={
        "label": "L", "meta": {"prompt_ledger": {"gen": 2}},
    })
    assert r.status_code == 200
    assert r.json()["meta"]["prompt_ledger"]["gen"] == 2
    assert r.json()["label"] == "L"
    # 不带 meta 的 PUT 不清空
    r = client.put("/sessions/extension/agent-1", json={"cli": "claude"})
    assert r.json()["meta"]["prompt_ledger"]["gen"] == 2


# ---------- U4: GC — alive=false 超 N 天清 meta，N 可配置 ----------

def test_gc_clears_stale_dead_meta(client, monkeypatch):
    import main as m

    monkeypatch.setattr(m, "GC_DAYS", 1)
    client.post("/sessions/register", json={
        "owner": "extension", "agent_id": "agent-dead",
        "meta": {"prompt_ledger": {"gen": 9}},
    })
    # 置死 + 时间拨回 2 天前
    client.post("/sessions/extension/agent-dead/release")
    key = m._key("extension", "agent-dead")
    m._store[key]["updated_at"] = int(time.time() * 1000) - 2 * 86400 * 1000
    # 触发一次写操作带动 GC
    client.post("/sessions/register", json={"owner": "extension", "agent_id": "agent-alive"})
    assert m._store[key]["meta"] == {}
    assert m._store[key]["alive"] is False  # 骨架保留
    assert m._store[key]["agent_id"] == "agent-dead"


def test_gc_keeps_recent_dead_meta(client, monkeypatch):
    import main as m

    monkeypatch.setattr(m, "GC_DAYS", 30)
    client.post("/sessions/register", json={
        "owner": "extension", "agent_id": "agent-2", "meta": {"prompt_ledger": {"gen": 1}},
    })
    client.post("/sessions/extension/agent-2/release")
    client.post("/sessions/register", json={"owner": "extension", "agent_id": "agent-3"})
    assert m._store[m._key("extension", "agent-2")]["meta"] != {}


# ---------- E1: 双写者并发字段互不覆盖（模拟宿主重报 × RoleManager 推 meta） ----------

def test_two_writers_do_not_clobber(client):
    # RoleManager 补建占位（无 session_id）
    client.post("/sessions/register", json={
        "owner": "extension", "agent_id": "agent-4",
        "meta": {"prompt_ledger": {"gen": 7}},
    })
    # 宿主重报带 session_id，不带 meta
    client.post("/sessions/register", json={
        "owner": "extension", "agent_id": "agent-4", "session_id": "ses_abc",
    })
    rec = _get(client, agent_id="agent-4")
    assert rec["session_id"] == "ses_abc"
    assert rec["meta"]["prompt_ledger"]["gen"] == 7
    # 占位记录无 session_id：不进 claimed
    client.post("/sessions/register", json={
        "owner": "extension", "agent_id": "agent-5", "meta": {"prompt_ledger": {"gen": 3}},
    })
    claimed = client.get("/sessions/claimed").json()["sessions"]
    assert "agent-5" not in [r["agent_id"] for r in claimed]


# ---------- 回归：既有行为不变 ----------

def test_session_id_conflict_409(client):
    client.post("/sessions/register", json={
        "owner": "extension", "agent_id": "agent-a", "session_id": "ses_shared",
    })
    r = client.post("/sessions/register", json={
        "owner": "castflow", "agent_id": "agent-b", "session_id": "ses_shared",
    })
    assert r.status_code == 409


def test_release_keeps_session_id_binding(client):
    """回归钉：release 只置 alive=false，session_id 仍占位——他 key 重绑同 session 依旧 409。

    现状语义（v0.1.0 即如此，本 feature 不改）：claimed 视图排除死记录，但
    _conflict_session 不看 alive。两处口径不一致记为事实项，改动需另立任务。
    """
    client.post("/sessions/register", json={
        "owner": "extension", "agent_id": "agent-c", "session_id": "ses_c",
    })
    client.post("/sessions/extension/agent-c/release")
    claimed = client.get("/sessions/claimed").json()["sessions"]
    assert "ses_c" not in [r["session_id"] for r in claimed]
    r = client.post("/sessions/register", json={
        "owner": "castflow", "agent_id": "agent-d", "session_id": "ses_c",
    })
    assert r.status_code == 409


def test_persistence_roundtrip(client, tmp_path):
    client.post("/sessions/register", json={
        "owner": "extension", "agent_id": "agent-p",
        "meta": {"prompt_ledger": {"gen": 5}},
    })
    import main as m

    data = json.loads((tmp_path / "session-registry.json").read_text(encoding="utf-8"))
    assert data["sessions"]["extension:agent-p"]["meta"]["prompt_ledger"]["gen"] == 5
