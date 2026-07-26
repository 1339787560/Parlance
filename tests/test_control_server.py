#!/usr/bin/env python3
"""Unit tests for infoServer control surface.

Covers run.py::ControlServer dispatch + request handling, and start.py
venv resolution. Integration (real Launcher + socket round-trip) is left
to manual smoke; see README and BDD SC01/SC02/SC04.
"""

import os
import sys
import time
from pathlib import Path
from unittest import mock

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import run as run_mod  # noqa: E402
import start as start_mod  # noqa: E402


# ── Fake Launcher ────────────────────────────────────────────────────────────

class _FakeLauncher:
    """Stand-in exposing only the surface ControlServer touches."""

    def __init__(self):
        self.reloaded = 0
        self.stopped = 0
        self.started = 0
        self.shutdown_calls = 0
        self.svc = mock.Mock()
        self.svc.running = True
        self.svc.status = "running"
        self.svc.pid = 12345
        self.svc.uptime = 42.5
        self.svc._last_error = None
        self.port = 5001

    def reload(self):
        self.reloaded += 1

    def stop(self):
        self.stopped += 1

    def start(self):
        self.started += 1
        return True

    def shutdown(self):
        self.shutdown_calls += 1

    def status_dict(self):
        return {
            "running": bool(self.svc.running),
            "status": self.svc.status,
            "pid": self.svc.pid,
            "uptime": self.svc.uptime,
            "port": self.port,
            "last_error": self.svc._last_error,
        }


@pytest.fixture
def launcher():
    return _FakeLauncher()


@pytest.fixture
def server(launcher):
    return run_mod.ControlServer(launcher)


# ── _dispatch ────────────────────────────────────────────────────────────────

def test_dispatch_reload(server, launcher):
    assert server._dispatch("reload", {}) == {"ok": True}
    assert launcher.reloaded == 1


def test_dispatch_status_returns_dict(server, launcher):
    out = server._dispatch("status", {})
    assert out["pid"] == 12345
    assert out["status"] == "running"
    assert out["port"] == 5001
    assert out["uptime"] == 42.5


def test_dispatch_start(server, launcher):
    assert server._dispatch("start", {}) == {"ok": True}
    assert launcher.started == 1


def test_dispatch_stop(server, launcher):
    assert server._dispatch("stop", {}) == {"ok": True}
    assert launcher.stopped == 1


def test_dispatch_unknown_raises(server):
    with pytest.raises(run_mod._MethodNotFound):
        server._dispatch("nope", {})


def test_dispatch_quit_defers_shutdown(server, launcher):
    out = server._dispatch("quit", {})
    assert out == {"ok": True}
    # shutdown scheduled on a 0.2s-deferred daemon thread
    time.sleep(0.4)
    assert launcher.shutdown_calls == 1


# ── _handle_request ──────────────────────────────────────────────────────────

def test_handle_request_valid(server, launcher):
    raw = {"jsonrpc": "2.0", "id": 7, "method": "status"}
    resp = server._handle_request(raw)
    assert resp["jsonrpc"] == "2.0"
    assert resp["id"] == 7
    assert resp["result"]["pid"] == 12345
    assert "error" not in resp


def test_handle_request_notification_no_id(server, launcher):
    # JSON-RPC notification (no id) → server MUST NOT respond
    raw = {"jsonrpc": "2.0", "method": "reload"}
    resp = server._handle_request(raw)
    assert resp is None
    assert launcher.reloaded == 1


def test_handle_request_unknown_method(server):
    raw = {"jsonrpc": "2.0", "id": 1, "method": "foobar"}
    resp = server._handle_request(raw)
    assert resp["error"]["code"] == run_mod._ERR_METHOD_NOT_FOUND
    assert resp["error"]["message"].startswith("Method not found")


def test_handle_request_non_dict_payload(server):
    resp = server._handle_request("not a dict")
    assert resp["error"]["code"] == run_mod._ERR_PARSE
    assert resp["id"] is None


def test_handle_request_missing_method(server):
    resp = server._handle_request({"jsonrpc": "2.0", "id": 1})
    assert resp["error"]["code"] == run_mod._ERR_PARSE


def test_handle_request_dispatch_exception_returns_internal_error(server):
    # Force _dispatch to blow up by patching launcher.status_dict
    server.launcher.status_dict = mock.Mock(side_effect=RuntimeError("boom"))
    resp = server._handle_request({"jsonrpc": "2.0", "id": 9, "method": "status"})
    assert resp["error"]["code"] == run_mod._ERR_INTERNAL
    assert "boom" in resp["error"]["message"]


# ── _ctl_address ─────────────────────────────────────────────────────────────

def test_ctl_address_win():
    with mock.patch.object(run_mod.os, "name", "nt"):
        addr, family = run_mod._ctl_address()
        assert family == "AF_PIPE"
        assert "infoserver_ctl" in addr


def test_ctl_address_posix():
    with mock.patch.object(run_mod.os, "name", "posix"):
        addr, family = run_mod._ctl_address()
        assert family == "AF_UNIX"
        assert addr.endswith("infoserver_ctl.sock")


# ── start.py::resolve_python ─────────────────────────────────────────────────

def test_resolve_python_picks_venv_when_present(tmp_path, monkeypatch):
    if os.name == "nt":
        venv = tmp_path / ".venv" / "Scripts" / "python.exe"
    else:
        venv = tmp_path / ".venv" / "bin" / "python"
    venv.parent.mkdir(parents=True)
    venv.write_text("")
    monkeypatch.setattr(start_mod, "ROOT", tmp_path)
    # realpath mismatch → re-exec into venv
    monkeypatch.setattr(start_mod.os.path, "realpath",
                        lambda x: str(x) + "_canonical")
    out = start_mod._resolve_python()
    assert os.path.basename(out) in ("python", "python.exe")
    assert str(venv) == out or out.endswith(os.path.basename(str(venv)))


def test_resolve_python_no_venv_returns_current(tmp_path, monkeypatch):
    monkeypatch.setattr(start_mod, "ROOT", tmp_path)
    monkeypatch.setattr(start_mod.shutil, "which", lambda _: None)
    out = start_mod._resolve_python()
    assert out == sys.executable
