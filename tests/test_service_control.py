#!/usr/bin/env python3
"""Unit tests for main.py ServiceControlServer (服务组级控制面).

Covers main.py::ServiceControlServer dispatch + request handling:
  services (status_all 权威清单) / restart (按端口重启单个, 含错误分支)。
Integration (real socket round-trip) left to manual smoke; see README.
"""

import sys
import time
from pathlib import Path
from unittest import mock

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import main as main_mod  # noqa: E402


# ── Fakes ───────────────────────────────────────────────────────────────────

class _FakeSvc:
    """Stand-in for ManagedService: only surfaces ServiceControlServer touches."""

    def __init__(self, name, port, enabled=True, managed=True):
        self.name = name
        self.port = port
        self.enabled = enabled
        self.managed = managed
        self.status = "running"
        self.pid = 12345
        self.restart_calls = 0

    def restart(self, timeout=15):
        self.restart_calls += 1
        self.pid += 1
        self.status = "running"

    def to_dict(self):
        return {
            "name": self.name,
            "port": self.port,
            "status": self.status,
            "pid": self.pid,
            "enabled": self.enabled,
            "managed": self.managed,
        }


class _FakeSvcMgr:
    def __init__(self, services):
        self.services = services

    def status_all(self):
        return [s.to_dict() for s in self.services]


@pytest.fixture
def svc_mgr():
    return _FakeSvcMgr([
        _FakeSvc("parlance-chat", 5001),
        _FakeSvc("serviceServer", 5000),
        _FakeSvc("statistic", 5002),
        _FakeSvc("disabled-svc", 9001, enabled=False),
        _FakeSvc("daemon-svc", 9002, managed=False),
    ])


@pytest.fixture
def server(svc_mgr):
    return main_mod.ServiceControlServer(svc_mgr)


# ── _dispatch: services ─────────────────────────────────────────────────────

def test_dispatch_services_returns_status_all(server, svc_mgr):
    out = server._dispatch("services", {})
    assert "services" in out
    assert [s["name"] for s in out["services"]] == [s.name for s in svc_mgr.services]
    # disabled/daemon 服务仍在清单里 (enabled/managed 字段标注)
    assert out["services"][3]["enabled"] is False
    assert out["services"][4]["managed"] is False


# ── _dispatch: restart ──────────────────────────────────────────────────────

def test_dispatch_restart_by_port(server, svc_mgr):
    target = svc_mgr.services[0]  # parlance-chat :5001
    out = server._dispatch("restart", {"port": 5001})
    assert out == {"ok": True, "name": "parlance-chat", "port": 5001,
                   "status": "running", "pid": 12346}
    assert target.restart_calls == 1
    # 其他服务未被触碰
    assert all(s.restart_calls == 0 for s in svc_mgr.services[1:])


def test_dispatch_restart_accepts_str_port(server, svc_mgr):
    out = server._dispatch("restart", {"port": "5002"})
    assert out["ok"] is True
    assert out["name"] == "statistic"


def test_dispatch_restart_unknown_port(server, svc_mgr):
    out = server._dispatch("restart", {"port": 9999})
    assert "error" in out
    assert "no managed service on port 9999" in out["error"]
    assert all(s.restart_calls == 0 for s in svc_mgr.services)


def test_dispatch_restart_missing_port(server, svc_mgr):
    out = server._dispatch("restart", {})
    assert out == {"error": "port required"}


def test_dispatch_restart_disabled_service(server, svc_mgr):
    out = server._dispatch("restart", {"port": 9001})
    assert "disabled" in out["error"]
    assert svc_mgr.services[3].restart_calls == 0


def test_dispatch_restart_daemon_service(server, svc_mgr):
    out = server._dispatch("restart", {"port": 9002})
    assert "daemon" in out["error"]
    assert svc_mgr.services[4].restart_calls == 0


def test_dispatch_unknown_method_raises(server):
    with pytest.raises(main_mod._MethodNotFound):
        server._dispatch("nope", {})


# ── _handle_request ─────────────────────────────────────────────────────────

def test_handle_request_services_envelope(server):
    raw = {"jsonrpc": "2.0", "id": 3, "method": "services"}
    resp = server._handle_request(raw)
    assert resp["jsonrpc"] == "2.0"
    assert resp["id"] == 3
    assert "services" in resp["result"]


def test_handle_request_notification_no_response(server, svc_mgr):
    raw = {"jsonrpc": "2.0", "method": "restart", "params": {"port": 5000}}
    resp = server._handle_request(raw)
    assert resp is None
    assert svc_mgr.services[1].restart_calls == 1


def test_handle_request_unknown_method(server):
    resp = server._handle_request({"jsonrpc": "2.0", "id": 1, "method": "foobar"})
    assert resp["error"]["code"] == main_mod._ERR_METHOD_NOT_FOUND


def test_handle_request_dispatch_exception_internal_error(server):
    server.svc_mgr.status_all = mock.Mock(side_effect=RuntimeError("boom"))
    resp = server._handle_request({"jsonrpc": "2.0", "id": 9, "method": "services"})
    assert resp["error"]["code"] == main_mod._ERR_INTERNAL
    assert "boom" in resp["error"]["message"]


# ── _svc_ctl_address ────────────────────────────────────────────────────────

def test_svc_ctl_address_win():
    with mock.patch.object(main_mod.os, "name", "nt"):
        addr, family = main_mod._svc_ctl_address()
        assert family == "AF_PIPE"
        assert "infoserver_svc" in addr


def test_svc_ctl_address_posix():
    with mock.patch.object(main_mod.os, "name", "posix"):
        addr, family = main_mod._svc_ctl_address()
        assert family == "AF_UNIX"
        assert addr.endswith("infoserver_svc.sock")
