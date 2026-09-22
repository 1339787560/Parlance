#!/usr/bin/env python3
"""Unit tests for deploy_service.py (:5099 发布通道落在 L2/run.py).

Covers the pure helpers (file classification / post-deploy actions / upload name
& auth guards) plus DeployOrchestrator end-to-end against a fake host control
client and tmp dirs. HTTP layer (DeployServer) is covered by an ephemeral-port
round trip. Design rationale: SDD `legacy退役与部署规范化` (发布器落 L2).
"""

import json
import sys
import zipfile
from pathlib import Path
from unittest import mock

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import deploy_service as ds  # noqa: E402


# ── safe_zip_name ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw,expect", [
    ("pkg_20260922.zip", "pkg_20260922.zip"),
    ("  spaced.zip  ", "spaced.zip"),
    ("/abs/path/pkg.zip", "pkg.zip"),          # basename only
    ("C:\\tmp\\pkg.zip", "pkg.zip"),           # windows path stripped
    ("../escape.zip", "escape.zip"),           # traversal neutralised
    ("pkg.ZIP", "pkg.ZIP"),                    # suffix check case-insensitive
])
def test_safe_zip_name_accepts(raw, expect):
    assert ds.safe_zip_name(raw) == expect


@pytest.mark.parametrize("raw", [
    "", None, "noext", "pkg.tar.gz", "pkg.txt", "pkg.zip.exe",
])
def test_safe_zip_name_rejects(raw):
    assert ds.safe_zip_name(raw) is None


# ── looks_like_multipart ─────────────────────────────────────────────────────

def test_multipart_sniff_detects_old_client():
    assert ds.looks_like_multipart(b"------WebKitFormBoundaryABC\r\nContent-Dis")
    assert ds.looks_like_multipart(b"--boundary\r\n")


def test_multipart_sniff_passes_zip_magic():
    # PK\x03\x04 = zip local file header; must NOT be mistaken for multipart
    assert not ds.looks_like_multipart(b"PK\x03\x04rest-of-zip")


# ── auth guards ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("peer", ["127.0.0.1", "::1", "localhost"])
def test_loopback_peers_recognised(peer):
    assert ds.is_loopback(peer)


@pytest.mark.parametrize("peer", ["192.168.102.53", "10.0.0.7", "", None])
def test_non_loopback_peers_rejected(peer):
    assert not ds.is_loopback(peer)


def test_auth_loopback_needs_no_token():
    assert ds.auth_ok("127.0.0.1", "", "secret")


def test_auth_remote_requires_matching_token():
    assert ds.auth_ok("192.168.102.53", "secret", "secret")
    assert not ds.auth_ok("192.168.102.53", "wrong", "secret")
    assert not ds.auth_ok("192.168.102.53", "", "secret")


def test_auth_remote_denied_when_no_token_configured():
    assert not ds.auth_ok("192.168.102.53", "anything", None)


# ── rel_to_root / exe_from_command ───────────────────────────────────────────

def test_rel_to_root_normalises_separators():
    root = str(Path("C:/repo"))
    out = ds.rel_to_root(str(Path("C:/repo/serviceGroup/a/b.exe")), root)
    assert out == "serviceGroup/a/b.exe"


def test_rel_to_root_outside_root_returns_none():
    assert ds.rel_to_root("C:/other/x.exe", "C:/repo") is None


@pytest.mark.parametrize("command,expect", [
    ("./serviceGroup/x/svc.exe", "./serviceGroup/x/svc.exe"),   # 原样返回 token (归一在 rel_to_root)
    ("/abs/svc.exe --flag", "/abs/svc.exe"),
    ('"C:\\a b\\svc.exe" --flag', "C:\\a b\\svc.exe"),          # 带空格路径 (引号优先)
    ("'C:/x y/svc.exe' --flag", "C:/x y/svc.exe"),
    ("python main.py", None),
    ("", None),
    (None, None),
])
def test_exe_from_command(command, expect):
    assert ds.exe_from_command(command) == expect


# ── classify_deploy_files ────────────────────────────────────────────────────

def _svc(name, port, rel_exe):
    return {"name": name, "port": port, "exe_path": str(Path("C:/repo") / rel_exe),
            "command": rel_exe}


SVC_BY_REL = {
    "serviceGroup/serviceServer/service-server.exe": _svc("serviceServer-rust", 5000,
                                                           "serviceGroup/serviceServer/service-server.exe"),
    "serviceGroup/xzmo/server_game/xzmoGame.exe": _svc("xzmo_game", 9001,
                                                       "serviceGroup/xzmo/server_game/xzmoGame.exe"),
}


def test_classify_splits_exe_helper_plain():
    files = [
        "serviceGroup/serviceServer/service-server.exe",     # → swap_exe
        "serviceGroup/serviceServer-legacy/assetTool.exe",   # → helper (plain)
        "main.py",                                           # → plain
        "serviceGroup/serviceServer/index.html",             # → plain
    ]
    out = ds.classify_deploy_files(files, SVC_BY_REL)
    assert [e["rel"] for e in out["exe_plan"]] == ["serviceGroup/serviceServer/service-server.exe"]
    assert out["exe_plan"][0]["port"] == 5000
    assert out["helper"] == ["serviceGroup/serviceServer-legacy/assetTool.exe"]
    assert out["unmapped"] == []
    assert sorted(out["plain"]) == [
        "main.py",
        "serviceGroup/serviceServer-legacy/assetTool.exe",
        "serviceGroup/serviceServer/index.html",
    ]


def test_classify_unmapped_exe_is_flagged_never_plain():
    files = ["serviceGroup/unknown/orphan.exe"]
    out = ds.classify_deploy_files(files, SVC_BY_REL)
    assert out["unmapped"] == ["serviceGroup/unknown/orphan.exe"]
    assert out["plain"] == []          # 未映射 exe 绝不落 plain（必撞运行中占用）
    assert out["exe_plan"] == []


def test_classify_skips_protected_prefix():
    files = ["serviceGroup/statisticServer/x.py", "main.py"]
    out = ds.classify_deploy_files(files, SVC_BY_REL)
    assert out["protected"] == ["serviceGroup/statisticServer/x.py"]
    assert out["plain"] == ["main.py"]


def test_classify_exe_without_port_stays_unmapped():
    svc_by_rel = {"a/svc.exe": {"name": "broken", "port": None, "exe_path": "C:/repo/a/svc.exe",
                                "command": "a/svc.exe"}}
    out = ds.classify_deploy_files(["a/svc.exe"], svc_by_rel)
    assert out["unmapped"] == ["a/svc.exe"]


# ── classify_targets (post-deploy action) ───────────────────────────────────

def test_targets_self_update_for_launcher_files():
    out = ds.classify_targets(["run.py", "serviceGroup/serviceServer/index.html"])
    assert out == {"self_update": True, "reseat_l3": False, "restart_legacy": False}


def test_targets_self_update_also_for_start_py():
    out = ds.classify_targets(["start.py"])
    assert out["self_update"] is True


def test_targets_reseat_for_host_files():
    out = ds.classify_targets(["main.py", "service_manager.py"])
    assert out == {"self_update": False, "reseat_l3": True, "restart_legacy": False}


def test_targets_self_update_wins_over_reseat():
    out = ds.classify_targets(["main.py", "run.py"])
    assert out["self_update"] is True
    assert out["reseat_l3"] is False     # L1 重拉新码会顺带重建 L3, 无需各自再 reseat


def test_targets_restart_legacy_prefix():
    out = ds.classify_targets(["serviceGroup/serviceServer-legacy/CustomRoute/templates/deposit.html"])
    assert out == {"self_update": False, "reseat_l3": False, "restart_legacy": True}


def test_targets_noop_for_plain_service_files():
    out = ds.classify_targets(["serviceGroup/serviceServer/src/main.rs"])
    assert out == {"self_update": False, "reseat_l3": False, "restart_legacy": False}


# ── SvcClient ────────────────────────────────────────────────────────────────

def test_svc_client_unwraps_jsonrpc_envelope():
    conn = mock.Mock()
    conn.recv.return_value = {"jsonrpc": "2.0", "id": 1, "result": {"ok": True, "port": 5000}}
    with mock.patch.object(ds, "_connect_svc", return_value=conn):
        client = ds.SvcClient()
        out = client.call("services")
    assert out == {"ok": True, "port": 5000}
    conn.send.assert_called_once()


def test_svc_client_returns_raw_when_not_enveloped():
    conn = mock.Mock()
    conn.recv.return_value = {"plain": 1}
    with mock.patch.object(ds, "_connect_svc", return_value=conn):
        assert ds.SvcClient().call("x") == {"plain": 1}


# ── DeployOrchestrator ───────────────────────────────────────────────────────

class _FakeSvc:
    """Records svc calls; returns canned results per method."""

    def __init__(self, services=None, swap_result=None, start_error=None):
        self.services = services or []
        self.swap_result = swap_result or {"ok": True, "backup": "C:/bak/old.exe"}
        self.start_error = start_error        # 模拟"宿主重启不起来" → 触发回滚
        self.calls = []

    def call(self, method, params=None, timeout=15):
        self.calls.append((method, params or {}))
        if method == "services":
            return {"services": self.services}
        if method == "swap_exe":
            return dict(self.swap_result)
        if method == "start" and self.start_error:
            return {"error": self.start_error}
        if method == "restart":
            return {"ok": True}
        return {"ok": True}


def _make_zip(dst: Path, files: dict, manifest_extra=None):
    """Build a deploy zip: files = {rel_path: bytes}. manifest lists rel paths."""
    with zipfile.ZipFile(dst, "w") as zf:
        for rel, data in files.items():
            zf.writestr(rel, data)
        man = {"built_at": "2026-09-22 21:00:00", "git_rev": "abc123",
               "files": sorted(files.keys())}
        if manifest_extra:
            man.update(manifest_extra)
        zf.writestr("manifest.json", json.dumps(man))
    return dst


@pytest.fixture
def repo(tmp_path):
    """Minimal fake infoServer root."""
    (tmp_path / "deploys").mkdir()
    (tmp_path / "main.py").write_text("old-main\n", encoding="utf-8")
    (tmp_path / "serviceGroup" / "serviceServer").mkdir(parents=True)
    (tmp_path / "serviceGroup" / "serviceServer" / "index.html").write_text("old\n", encoding="utf-8")
    return tmp_path


def _orchestrator(repo, svc, **kw):
    calls = {"self_update": 0, "reseat": 0}
    orch = ds.DeployOrchestrator(
        root=str(repo), svc=svc,
        on_self_update=kw.pop("on_self_update", lambda: calls.__setitem__("self_update", calls["self_update"] + 1)),
        on_reseat_l3=kw.pop("on_reseat_l3", lambda: calls.__setitem__("reseat", calls["reseat"] + 1)),
        diag_provider=kw.pop("diag_provider", lambda: {"stub": True}),
    )
    return orch, calls


def test_orchestrator_happy_path_replaces_files(repo):
    zip_path = _make_zip(repo / "deploys" / "p.zip",
                         {"main.py": b"new-main\n",
                          "serviceGroup/serviceServer/index.html": b"new\n"})
    svc = _FakeSvc()
    orch, calls = _orchestrator(repo, svc)
    record = {}
    orch.run(zip_path, record)

    assert record["ok"] is True
    assert record["stage"] == "done"
    assert record["replaced"] == 2
    assert (repo / "main.py").read_text(encoding="utf-8") == "new-main\n"
    assert record["manifest"]["files"] == 2
    # main.py 属 L3 层 → 需要 reseat；run.py 未动 → 不自杀
    assert calls["reseat"] == 1
    assert calls["self_update"] == 0


def test_orchestrator_rolls_back_on_unmapped_exe(repo):
    zip_path = _make_zip(repo / "deploys" / "p.zip",
                         {"main.py": b"new-main\n",
                          "serviceGroup/unknown/orphan.exe": b"MZfake"})
    svc = _FakeSvc()
    orch, calls = _orchestrator(repo, svc)
    record = {}
    orch.run(zip_path, record)

    assert record["ok"] is False
    assert record["stage"] == "rolled_back"
    assert record["unmapped_exe"] == ["serviceGroup/unknown/orphan.exe"]
    # 非 exe 文件已回滚成旧内容
    assert (repo / "main.py").read_text(encoding="utf-8") == "old-main\n"
    assert calls["reseat"] == 0        # 失败不重启


def test_orchestrator_swaps_mapped_exe_via_svc(repo):
    exe_rel = "serviceGroup/serviceServer/service-server.exe"
    zip_path = _make_zip(repo / "deploys" / "p.zip", {exe_rel: b"MZnew"})
    svc = _FakeSvc(services=[{"name": "serviceServer-rust", "port": 5000,
                              "exe_path": str(repo / exe_rel), "command": exe_rel}])
    orch, calls = _orchestrator(repo, svc)
    record = {}
    orch.run(zip_path, record)

    assert record["ok"] is True
    assert [e["file"] for e in record["exe_plan"]] == [exe_rel]
    assert record["exe_done"][0]["how"] == "host"
    swap = [c for c in svc.calls if c[0] == "swap_exe"]
    assert len(swap) == 1
    # src 必须指向 staging 里的新 exe，而非运行位
    assert swap[0][1]["port"] == 5000
    assert swap[0][1]["src"].endswith(exe_rel.replace("/", "\\")) or \
        swap[0][1]["src"].endswith(exe_rel)


def test_orchestrator_failed_swap_rolls_back(repo):
    """宿主 swap 失败 + 降级路径也拉不起来 → 记 failures 并回滚 (不留半替换现场)。"""
    exe_rel = "serviceGroup/serviceServer/service-server.exe"
    zip_path = _make_zip(repo / "deploys" / "p.zip", {exe_rel: b"MZnew"})
    svc = _FakeSvc(services=[{"name": "svc", "port": 5000,
                              "exe_path": str(repo / exe_rel), "command": exe_rel}],
                   swap_result={"error": "stop failed"},
                   start_error="start blocked")
    orch, calls = _orchestrator(repo, svc)
    record = {}
    orch.run(zip_path, record)

    assert record["ok"] is False
    assert record["stage"] == "rolled_back"
    assert record["failures"][0]["file"] == exe_rel
    assert calls["reseat"] == 0


def test_orchestrator_rejects_manifest_mismatch(repo):
    zip_path = _make_zip(repo / "deploys" / "p.zip", {"main.py": b"x"})
    # 篡改 manifest：声明一个包里没有的文件
    with zipfile.ZipFile(repo / "deploys" / "bad.zip", "w") as zf:
        zf.writestr("main.py", b"x")
        zf.writestr("manifest.json", json.dumps({"files": ["main.py", "ghost.py"]}))
    svc = _FakeSvc()
    orch, _ = _orchestrator(repo, svc)
    record = {}
    orch.run(repo / "deploys" / "bad.zip", record)
    assert record["ok"] is False
    assert record["stage"] == "error"
    assert "mismatch" in record["error"]


def test_orchestrator_self_update_on_run_py(repo):
    zip_path = _make_zip(repo / "deploys" / "p.zip", {"run.py": b"# new l2\n"})
    svc = _FakeSvc()
    orch, calls = _orchestrator(repo, svc)
    record = {}
    orch.run(zip_path, record)
    assert record["ok"] is True
    assert calls["self_update"] == 1
    assert calls["reseat"] == 0


def test_orchestrator_restarts_reader_when_legacy_dir_files_change(repo):
    """U8 (2026-09-22): legacy 服务已退役 ⇒ 该目录文件由 :5000 读取, 收尾重启 :5000。

    包内只有 legacy 文件 (无 :5000 exe) ⇒ 必须发起一次 restart(:5000)。
    """
    rel = "serviceGroup/serviceServer-legacy/CustomRoute/templates/deposit.html"
    zip_path = _make_zip(repo / "deploys" / "p.zip", {rel: b"<!-- new -->\n"})
    svc = _FakeSvc()
    orch, _ = _orchestrator(repo, svc)
    record = {}
    orch.run(zip_path, record)
    assert record["ok"] is True
    assert record["post"]["restart_legacy"] is True      # 分类键名保留历史, 含义见 deploy_service
    assert record["restart_reader_port"] == ds.TOOL_PORT
    restarts = [c for c in svc.calls if c[0] == "restart"]
    assert len(restarts) == 1
    assert restarts[0][1]["port"] == ds.TOOL_PORT


def test_orchestrator_skips_reader_restart_when_5000_exe_already_swapped(repo):
    """包同时含 :5000 exe 与 legacy 文件 ⇒ swap_exe 自带的停/起已让新文件生效, 不再重复重启。"""
    exe_rel = "serviceGroup/serviceServer/service-server.exe"
    leg_rel = "serviceGroup/serviceServer-legacy/CustomRoute/templates/deposit.html"
    zip_path = _make_zip(repo / "deploys" / "p.zip",
                         {exe_rel: b"MZnew", leg_rel: b"<!-- new -->\n"})
    svc = _FakeSvc(services=[{"name": "serviceServer-rust", "port": ds.TOOL_PORT,
                              "exe_path": str(repo / exe_rel), "command": exe_rel}])
    orch, _ = _orchestrator(repo, svc)
    record = {}
    orch.run(zip_path, record)
    assert record["ok"] is True
    assert record["post"]["restart_legacy"] is True       # 分类仍标记该层被动过
    assert [c for c in svc.calls if c[0] == "restart"] == []   # 但不额外重启


def test_orchestrator_creates_new_dirs_and_backup(repo):
    rel = "serviceGroup/serviceServer/src/brand_new.rs"
    zip_path = _make_zip(repo / "deploys" / "p.zip", {rel: b"// new\n"})
    svc = _FakeSvc()
    orch, _ = _orchestrator(repo, svc)
    record = {}
    orch.run(zip_path, record)
    assert (repo / rel).read_text(encoding="utf-8") == "// new\n"
    assert record["backup"]["files"] == 0        # 新文件无旧备份
    assert record["replaced"] == 1


# ── DeployServer (HTTP round trip, ephemeral port) ──────────────────────────

def _token_must_not_be_touched():
    """回归: 回环请求免口令 → 不该触碰 token_provider。

    真实 `deploy_token()` 有副作用 (首次调用即生成 `deploy.token` 文件) ——
    为 loopback 白造一个秘密文件是 bug (2026-09-22 实测: A3 推送后根目录多出
    deploy.token)。故这里让 provider 直接炸: loopback 若碰它, 测试立刻失败。
    """
    raise AssertionError("回环请求不应触碰 token_provider (会生成 deploy.token)")

def test_deploy_server_upload_activate_log_round_trip(repo):
    import urllib.request

    zip_bytes = (repo / "deploys" / "src.zip")
    _make_zip(zip_bytes, {"main.py": b"new-main\n"})
    payload = zip_bytes.read_bytes()

    svc = _FakeSvc()
    orch, _ = _orchestrator(repo, svc)
    server = ds.DeployServer("127.0.0.1", 0, orchestrator=orch, root=str(repo),
                             token_provider=_token_must_not_be_touched)   # 回环免口令 → provider 不应被触碰
    server.start()
    try:
        base = f"http://127.0.0.1:{server.port}"

        # upload: raw body + filename header (loopback → no token needed)
        req = urllib.request.Request(
            f"{base}/api/deploy/upload", data=payload, method="POST",
            headers={"X-Deploy-Filename": "round_trip.zip",
                     "Content-Type": "application/octet-stream"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            assert resp.status == 200
            body = json.loads(resp.read())
        assert body["success"] is True
        assert (repo / "deploys" / "round_trip.zip").is_file()

        # activate (async) → 等编排落盘
        req = urllib.request.Request(f"{base}/api/deploy/activate",
                                     data=json.dumps({"zip": "round_trip.zip"}).encode(),
                                     method="POST",
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            assert resp.status == 200

        deadline = __import__("time").time() + 10
        last = None
        while __import__("time").time() < deadline:
            with urllib.request.urlopen(f"{base}/api/deploy/log", timeout=10) as resp:
                last = json.loads(resp.read())
            if last.get("last", {}).get("stage") in ("done", "rolled_back", "error"):
                break
            __import__("time").sleep(0.2)
        assert last["last"]["ok"] is True
        assert (repo / "main.py").read_text(encoding="utf-8") == "new-main\n"

        # 404 for unknown path
        with pytest.raises(urllib.error.HTTPError) as ei:
            urllib.request.urlopen(f"{base}/api/deploy/nope", timeout=5)
        assert ei.value.code == 404
    finally:
        server.stop()


def test_deploy_server_rejects_multipart_body(repo):
    import urllib.request

    svc = _FakeSvc()
    orch, _ = _orchestrator(repo, svc)
    server = ds.DeployServer("127.0.0.1", 0, orchestrator=orch, root=str(repo),
                             token_provider=_token_must_not_be_touched)   # 回环免口令 → provider 不应被触碰
    server.start()
    try:
        base = f"http://127.0.0.1:{server.port}"
        req = urllib.request.Request(
            f"{base}/api/deploy/upload",
            data=b"------WebKitFormBoundaryABC\r\nContent-Disposition: form-data; name=\"file\"\r\n",
            method="POST",
            headers={"X-Deploy-Filename": "old_client.zip"})
        with pytest.raises(urllib.error.HTTPError) as ei:
            urllib.request.urlopen(req, timeout=5)
        assert ei.value.code == 400
        assert "raw" in ei.value.read().decode("utf-8", "ignore").lower()
    finally:
        server.stop()


def test_deploy_server_rejects_bad_name(repo):
    import urllib.request

    svc = _FakeSvc()
    orch, _ = _orchestrator(repo, svc)
    server = ds.DeployServer("127.0.0.1", 0, orchestrator=orch, root=str(repo),
                             token_provider=_token_must_not_be_touched)   # 回环免口令 → provider 不应被触碰
    server.start()
    try:
        base = f"http://127.0.0.1:{server.port}"
        req = urllib.request.Request(f"{base}/api/deploy/upload", data=b"PK\x03\x04x",
                                     method="POST",
                                     headers={"X-Deploy-Filename": "not_a_zip.txt"})
        with pytest.raises(urllib.error.HTTPError) as ei:
            urllib.request.urlopen(req, timeout=5)
        assert ei.value.code == 400
    finally:
        server.stop()
