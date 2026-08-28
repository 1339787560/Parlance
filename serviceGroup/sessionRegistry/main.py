#!/usr/bin/env python3
r"""session-registry — 权威 Agent 会话注册表（infoserver 子服务）。

职责：
- 分别记录 castflow / extension 两类客户端启动的 agent 会话归属。
- 持久化到本地 JSON 文件，重启不丢。
- 提供注册/更新/心跳/释放/查询 API，作为两端“谁占用哪个 CLI session”的唯一真相源。

用法：
    python main.py --port 5011

API 摘要：
    GET  /health
    GET  /sessions
    GET  /sessions/claimed
    POST /sessions/register
    PUT  /sessions/{owner}/{agent_id}
    GET  /sessions/{owner}/{agent_id}
    POST /sessions/{owner}/{agent_id}/heartbeat
    POST /sessions/{owner}/{agent_id}/release
"""

from __future__ import annotations

import argparse
import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
import uvicorn

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DATA_FILE = DATA_DIR / "session-registry.json"

ALLOWED_OWNERS = {"castflow", "extension"}

app = FastAPI(title="session-registry", version="0.1.0")
_lock = threading.Lock()
_store: Dict[str, Dict[str, Any]] = {}


# ---------- persistence ----------

def _load() -> None:
    global _store
    if DATA_FILE.exists():
        try:
            data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
            _store = data.get("sessions", {})
        except Exception:
            _store = {}
    else:
        _store = {}


def _save() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = DATA_FILE.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps({"sessions": _store}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(tmp, DATA_FILE)


def _key(owner: str, agent_id: str) -> str:
    return f"{owner}:{agent_id}"


def _now() -> int:
    return int(time.time() * 1000)


# ---------- models ----------

class RegisterBody(BaseModel):
    owner: str
    agent_id: str = Field(min_length=1)
    session_id: Optional[str] = None
    label: Optional[str] = None
    role: Optional[str] = None
    cli: Optional[str] = None
    cwd: Optional[str] = None
    alive: bool = True


class UpdateBody(BaseModel):
    session_id: Optional[str] = None
    label: Optional[str] = None
    role: Optional[str] = None
    cli: Optional[str] = None
    cwd: Optional[str] = None
    alive: Optional[bool] = None


# ---------- helpers ----------

def _validate_owner(owner: str) -> None:
    if owner not in ALLOWED_OWNERS:
        raise HTTPException(status_code=400, detail=f"owner 必须是 {sorted(ALLOWED_OWNERS)} 之一")


def _conflict_session(session_id: str, exclude_key: Optional[str] = None) -> Optional[str]:
    """session_id 已被其他 key 占用时返回占用 key，否则 None。"""
    if not session_id:
        return None
    for k, v in _store.items():
        if k == exclude_key:
            continue
        if v.get("session_id") == session_id:
            return k
    return None


def _public(owner: str, agent_id: str) -> Dict[str, Any]:
    v = _store[_key(owner, agent_id)]
    return {
        "owner": v["owner"],
        "agent_id": v["agent_id"],
        "session_id": v.get("session_id"),
        "label": v.get("label"),
        "role": v.get("role"),
        "cli": v.get("cli"),
        "cwd": v.get("cwd"),
        "alive": bool(v.get("alive", True)),
        "created_at": v.get("created_at"),
        "updated_at": v.get("updated_at"),
    }


# ---------- routes ----------

@app.get("/health")
def health() -> Dict[str, Any]:
    return {"ok": True, "service": "session-registry", "sessions": len(_store)}


@app.get("/sessions")
def list_sessions(owner: Optional[str] = None) -> Dict[str, Any]:
    with _lock:
        rows = [
            _public(v["owner"], v["agent_id"])
            for v in _store.values()
            if owner is None or v["owner"] == owner
        ]
    rows.sort(key=lambda r: (r["owner"], r["agent_id"]))
    return {"count": len(rows), "sessions": rows}


@app.get("/sessions/claimed")
def list_claimed() -> Dict[str, Any]:
    """返回所有**当前存活**（alive=true）且已绑定 session_id 的会话。

    释放/关闭（alive=false）的记录不再视为占用，允许历史会话被重新选择。
    需要全量审计时用 GET /sessions。
    """
    with _lock:
        rows = [
            _public(v["owner"], v["agent_id"])
            for v in _store.values()
            if v.get("session_id") and v.get("alive", True)
        ]
    rows.sort(key=lambda r: (r["owner"], r["agent_id"]))
    return {"count": len(rows), "sessions": rows}


@app.post("/sessions/register")
def register(body: RegisterBody) -> Dict[str, Any]:
    _validate_owner(body.owner)
    k = _key(body.owner, body.agent_id)
    with _lock:
        conflict = _conflict_session(body.session_id or "", exclude_key=k)
        if conflict:
            raise HTTPException(
                status_code=409,
                detail=f"session_id 已被 {conflict} 占用",
            )
        now = _now()
        if k in _store:
            v = _store[k]
            if body.session_id is not None:
                v["session_id"] = body.session_id
            if body.label is not None:
                v["label"] = body.label
            if body.role is not None:
                v["role"] = body.role
            if body.cli is not None:
                v["cli"] = body.cli
            if body.cwd is not None:
                v["cwd"] = body.cwd
            v["alive"] = body.alive
            v["updated_at"] = now
        else:
            _store[k] = {
                "owner": body.owner,
                "agent_id": body.agent_id,
                "session_id": body.session_id,
                "label": body.label,
                "role": body.role,
                "cli": body.cli,
                "cwd": body.cwd,
                "alive": body.alive,
                "created_at": now,
                "updated_at": now,
            }
        _save()
        return _public(body.owner, body.agent_id)


@app.put("/sessions/{owner}/{agent_id}")
def update(owner: str, agent_id: str, body: UpdateBody) -> Dict[str, Any]:
    _validate_owner(owner)
    k = _key(owner, agent_id)
    with _lock:
        if k not in _store:
            raise HTTPException(status_code=404, detail="会话记录不存在")
        conflict = _conflict_session(body.session_id or "", exclude_key=k)
        if conflict:
            raise HTTPException(
                status_code=409,
                detail=f"session_id 已被 {conflict} 占用",
            )
        v = _store[k]
        for field in ("session_id", "label", "role", "cli", "cwd", "alive"):
            val = getattr(body, field)
            if val is not None:
                v[field] = val
        v["updated_at"] = _now()
        _save()
        return _public(owner, agent_id)


@app.get("/sessions/{owner}/{agent_id}")
def get_one(owner: str, agent_id: str) -> Dict[str, Any]:
    _validate_owner(owner)
    with _lock:
        k = _key(owner, agent_id)
        if k not in _store:
            raise HTTPException(status_code=404, detail="会话记录不存在")
        return _public(owner, agent_id)


@app.post("/sessions/{owner}/{agent_id}/heartbeat")
def heartbeat(owner: str, agent_id: str) -> Dict[str, Any]:
    _validate_owner(owner)
    with _lock:
        k = _key(owner, agent_id)
        if k not in _store:
            raise HTTPException(status_code=404, detail="会话记录不存在")
        _store[k]["alive"] = True
        _store[k]["updated_at"] = _now()
        _save()
        return _public(owner, agent_id)


@app.post("/sessions/{owner}/{agent_id}/release")
def release(owner: str, agent_id: str) -> Dict[str, Any]:
    _validate_owner(owner)
    with _lock:
        k = _key(owner, agent_id)
        if k not in _store:
            raise HTTPException(status_code=404, detail="会话记录不存在")
        _store[k]["alive"] = False
        _store[k]["updated_at"] = _now()
        _save()
        return _public(owner, agent_id)


_load()


def main() -> None:
    parser = argparse.ArgumentParser(description="session-registry")
    parser.add_argument("--port", type=int, default=5011)
    parser.add_argument("--host", default="0.0.0.0")
    args = parser.parse_args()
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
