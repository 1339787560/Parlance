#!/usr/bin/env python3
"""infoServer — pure ServiceGroup manager (sgManager) (走法 A: 无 HTTP, 不占端口).

读 config.yaml → ServiceGroupManager.start_all → 阻塞等 SIGINT → stop_all。
sgManager 不监听任何 TCP 端口; 所有子服务(含 parlanceChat) 由 config.yaml services 声明,
按 enabled 开关即装/卸 → 可拆卸性。

服务级控制面 (ServiceControlServer):
  sgManager 虽无 HTTP, 但开一个跨平台控制 socket (multiprocessing.connection, 同 run.py 模式),
  供外部 agent (cwd-mcp) 查询托管服务清单 / 按端口重启单个子服务:
    services → ServiceGroupManager.status_all()   (每个托管子服务实时状态)
    restart  → 按 port 找服务 → svc.restart()      (stop+start, 不触发 auto_restart 计数)
  这是子服务的唯一权威所有者视图; run.py 只负责拉起本 sgManager, 不管理子服务。
"""

import json
import logging
import os
import shutil
import signal
import socket
import sys
import threading
import time
import zipfile
from multiprocessing.connection import Connection, Listener
from pathlib import Path
from typing import Any, Optional

import yaml

from service_manager import ServiceGroupManager, ManagedService

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("main")

SVC_CTL_PIPE_WIN = r"\\.\pipe\infoserver_svc"
SVC_CTL_SOCKET_POSIX = "/tmp/infoserver_svc.sock"

_ERR_PARSE = -32700
_ERR_METHOD_NOT_FOUND = -32601
_ERR_INTERNAL = -32603


def config_path() -> Path:
    """配置文件选择: --config 参 > env INFOSERVER_CONFIG > 缺省 config.yaml.

    本机用 config.yaml (6 融入 castflow 的服务已 disabled);
    堡垒机全量用 config.full.yaml (run.py --config config.full.yaml)。
    """
    argv = sys.argv[1:]
    for i, a in enumerate(argv):
        if a == "--config" and i + 1 < len(argv):
            return Path(argv[i + 1])
        if a.startswith("--config="):
            return Path(a.split("=", 1)[1])
    return Path(os.environ.get("INFOSERVER_CONFIG") or "config.yaml")


def load_config() -> dict:
    cfg_path = config_path()
    if not cfg_path.exists():
        logger.warning("%s not found, using defaults (no services)", cfg_path)
        return {"services": []}
    with open(cfg_path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _svc_ctl_address() -> tuple[str, str]:
    """返回 (address, family) for multiprocessing.connection.Listener."""
    if os.name == "nt":
        return (SVC_CTL_PIPE_WIN, "AF_PIPE")
    return (SVC_CTL_SOCKET_POSIX, "AF_UNIX")


class _MethodNotFound(Exception):
    pass


class ServiceControlServer:
    """JSON-RPC 控制面 — ServiceGroupManager 子服务级操作 (与 run.py ControlServer 同构).

    方法:
      services  → {"services": status_all()}   每个托管子服务实时状态 (含 disabled)
      restart   → {"port": N} → 按 port 找服务 → svc.restart() → {"ok","name","status","pid"}
                  (未知端口 / disabled / daemon managed=false → 结构化 error)
      swap_exe  → {"port": N} → svc.swap_exe() (热替换 .exe, 无 verify/回滚)
      deploy    → {"zip"} → 异步 deploy 产物包直推编排 (停→备份→原位替换→启→探活→失败恢复备份)
      deploy_log → {"running", "last"}  最近一次 deploy 编排实时进度 + 结果
    """

    def __init__(self, svc_mgr: ServiceGroupManager):
        self.svc_mgr = svc_mgr
        self._listener: Optional[Listener] = None
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._address, self._family = _svc_ctl_address()
        self._deploy_running = False  # deploy 异步编排锁 (防 reload/重复触发竞态)

    @property
    def address(self) -> str:
        return self._address

    def start(self):
        # Clear stale UDS file (posix only; Named Pipe is kernel-managed on win)
        if self._family == "AF_UNIX" and os.path.exists(self._address):
            try:
                os.unlink(self._address)
            except OSError:
                pass
        try:
            self._listener = Listener(self._address, family=self._family)
        except Exception as e:
            # 控制管道被占 = 另有 sgManager 持有。不退出 (sgManager 可能刚被 run.py 拉起,
            # 旧 sgManager 尚未释放管道), 转后台每 10s 重试接管, 让最后存活的 sgManager
            # 自动成为控制面所有者 (2026-08-19 双实例事故根因修复的接管侧)。
            logger.warning(
                "ServiceControlServer bind failed (%s): %s — retrying every 10s "
                "to take over the control pipe when the old sgManager exits.",
                self._address, e,
            )
            retry = threading.Thread(
                target=self._retry_bind, name="svc-ctl-retry", daemon=True
            )
            retry.start()
            return
        self._bind_serve()

    def _bind_serve(self):
        """正式启动 accept loop (绑定成功后调用)。"""
        self._thread = threading.Thread(
            target=self._accept_loop, name="svc-ctl-accept", daemon=True
        )
        self._thread.start()
        logger.info("ServiceControlServer listening on %s", self._address)

    def _retry_bind(self):
        """绑定失败后的接管重试: 每 10s 重绑控制管道, 成功后启动 accept loop。"""
        while not self._stop.is_set():
            time.sleep(10)
            try:
                self._listener = Listener(self._address, family=self._family)
            except Exception:
                continue
            logger.info("ServiceControlServer acquired %s", self._address)
            self._bind_serve()
            return

    def stop(self):
        self._stop.set()
        if self._listener is not None:
            try:
                self._listener.close()
            except Exception:
                pass
        if self._thread is not None:
            self._thread.join(timeout=2)

    def _accept_loop(self):
        while not self._stop.is_set():
            try:
                conn = self._listener.accept()
            except (OSError, EOFError):
                break
            except Exception:
                if self._stop.is_set():
                    break
                continue
            t = threading.Thread(
                target=self._handle_conn, args=(conn,),
                name="svc-ctl-conn", daemon=True,
            )
            t.start()

    def _handle_conn(self, conn: Connection):
        try:
            while not self._stop.is_set():
                try:
                    raw = conn.recv()
                except (EOFError, OSError):
                    break
                response = self._handle_request(raw)
                if response is None:
                    continue
                try:
                    conn.send(response)
                except (OSError, BrokenPipeError):
                    break
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def _handle_request(self, raw) -> Optional[dict]:
        if not isinstance(raw, dict):
            return self._error(None, _ERR_PARSE, "Expected JSON object")
        req_id = raw.get("id")
        method = raw.get("method")
        params = raw.get("params") or {}
        if not isinstance(method, str):
            return self._error(req_id, _ERR_PARSE, "Missing 'method'")
        try:
            result = self._dispatch(method, params)
        except _MethodNotFound:
            return self._error(req_id, _ERR_METHOD_NOT_FOUND,
                               f"Method not found: {method}")
        except Exception as e:
            logger.exception("ServiceControlServer dispatch error: %s", e)
            return self._error(req_id, _ERR_INTERNAL, str(e))
        if req_id is None:
            return None  # JSON-RPC notification → no response
        return {"jsonrpc": "2.0", "id": req_id, "result": result}

    def _dispatch(self, method: str, params: dict) -> dict:
        if method == "services":
            return {"services": self.svc_mgr.status_all()}
        if method == "restart":
            return self._restart_by_port(params.get("port"))
        if method == "swap_exe":
            return self._swap_exe_by_port(params.get("port"), params.get("src"))
        if method == "stop":
            return self._stop_by_port(params.get("port"))
        if method == "start":
            return self._start_by_port(params.get("port"))
        if method == "deploy":
            return self._deploy_services(params.get("zip"))
        if method == "deploy_log":
            return self._deploy_log()
        raise _MethodNotFound(method)

    def _restart_by_port(self, port) -> dict[str, Any]:
        if self._deploy_running:
            return {"error": "deploy in progress, restart blocked"}
        if port is None:
            return {"error": "port required"}
        svc: Optional[ManagedService] = self._find_by_port(int(port))
        if svc is None:
            return {"error": f"no managed service on port {port}"}
        if not svc.enabled:
            return {"error": f"service '{svc.name}' on port {port} is disabled (enabled=false)"}
        if not svc.managed:
            return {"error": f"service '{svc.name}' on port {port} is daemon (managed=false), restart not supported"}
        svc.restart(timeout=15)
        return {
            "ok": True,
            "name": svc.name,
            "port": svc.port,
            "status": svc.status,
            "pid": svc.pid,
        }

    def _swap_exe_by_port(self, port, src=None) -> dict[str, Any]:
        if self._deploy_running:
            return {"error": "deploy in progress, swap_exe blocked"}
        if port is None:
            return {"error": "port required"}
        svc: Optional[ManagedService] = self._find_by_port(int(port))
        if svc is None:
            return {"error": f"no managed service on port {port}"}
        if not svc.enabled:
            return {"error": f"service '{svc.name}' on port {port} is disabled (enabled=false)"}
        if not svc.managed:
            return {"error": f"service '{svc.name}' on port {port} is daemon (managed=false)"}
        result = svc.swap_exe(src=src)
        result.setdefault("name", svc.name)
        result.setdefault("port", svc.port)
        return result

    def _find_by_port(self, port: int) -> Optional[ManagedService]:
        for svc in self.svc_mgr.services:
            if svc.port == port:
                return svc
        return None

    def _stop_by_port(self, port) -> dict[str, Any]:
        """单服务停止原语 (供 cwd_infoserver_build_swap 停→build→start 编排解锁 exe)."""
        if self._deploy_running:
            return {"error": "deploy in progress, stop blocked"}
        if port is None:
            return {"error": "port required"}
        svc: Optional[ManagedService] = self._find_by_port(int(port))
        if svc is None:
            return {"error": f"no managed service on port {port}"}
        if not svc.enabled:
            return {"error": f"service '{svc.name}' on port {port} is disabled (enabled=false)"}
        if not svc.managed:
            return {"error": f"service '{svc.name}' on port {port} is daemon (managed=false), stop not supported"}
        info = svc.stop_verified(timeout=15)
        return {"ok": bool(info.get("ok")), "name": svc.name, "port": svc.port,
                "status": svc.status, "stop": info}

    def _start_by_port(self, port) -> dict[str, Any]:
        """单服务启动原语 (供 build_swap 停→build→start 编排; 已运行则幂等)."""
        if self._deploy_running:
            return {"error": "deploy in progress, start blocked"}
        if port is None:
            return {"error": "port required"}
        svc: Optional[ManagedService] = self._find_by_port(int(port))
        if svc is None:
            return {"error": f"no managed service on port {port}"}
        if not svc.enabled:
            return {"error": f"service '{svc.name}' on port {port} is disabled (enabled=false)"}
        if not svc.managed:
            return {"error": f"service '{svc.name}' on port {port} is daemon (managed=false)"}
        if svc.running:
            return {"ok": True, "name": svc.name, "port": svc.port, "status": svc.status, "note": "already running"}
        svc.start()
        return {"ok": True, "name": svc.name, "port": svc.port, "status": svc.status}

    # ── deploy 产物包直推编排: 上传的 zip (make_deploy_pack.py 打包) → 停受影响服务
    # → 备份被覆盖文件 → 原位替换 → 启 → 探活 → 失败自动恢复备份。
    # 替代 svn 更新: 推的是本机验证过的精确产物 (py+exe+模板一体),
    # 无 svn 依赖 / 无冲突中止 / 回滚 = 恢复备份 (秒级, 非 svn -r)。

    _DEPLOY_LOG = "deploy.log"
    _DEPLOY_FALLBACK_NAMES = ["serviceServer-rust", "serviceServer-legacy"]
    # 受保护服务: 打包默认不含其文件; 即使 manifest 含 (手动 --only 或旧包) 也不停不替换。
    # statistic-server = 本机 AI API 网关 (DeepSeek 代理), 误停 = 断 AI 会话 (2026-09-09 用户指令)。
    _DEPLOY_PROTECTED = {"statistic-server"}

    def _protected_scope(self):
        """受保护服务的文件域: (prefixes, files)。替换循环按此跳过。"""
        prefixes, files = [], []
        root = os.getcwd()
        for svc in self.svc_mgr.services:
            if svc.name not in self._DEPLOY_PROTECTED:
                continue
            if svc.cwd:
                try:
                    rel = os.path.relpath(os.path.abspath(svc.cwd), root).replace("\\", "/")
                    if not rel.startswith(".."):
                        prefixes.append(rel + "/")
                except ValueError:
                    pass
            for entry in [svc.command] + (svc.args or []):
                entry = (entry or "").strip().strip('"')
                if not entry:
                    continue
                full = entry if os.path.isabs(entry) else os.path.join(svc.cwd or root, entry)
                try:
                    rel = os.path.relpath(full, root).replace("\\", "/")
                except ValueError:
                    continue
                files.append(rel)
        return prefixes, files

    @staticmethod
    def _locked_files(pairs):
        """返 [(rel, err)] — 打不开写句柄的文件 (= 被占用, 替换必 WinError32)。"""
        out = []
        for rel, dst in pairs:
            if not os.path.isfile(dst):
                continue
            try:
                with open(dst, "r+b"):
                    pass
            except OSError as e:
                out.append((rel, f"{e.__class__.__name__}: {e}"))
        return out

    @classmethod
    def _wait_writable(cls, pairs, timeout: float = 15):
        """轮询等文件可写。进程退出后 Windows 释放 image section 有延迟 (本地实测偶发
        >2s, 既有 handoff 记为 14s 量级), 固定 sleep 赌不过去 → 轮询到可写或超时。
        超时返仍被占用的 [(rel, err)]。"""
        deadline = time.time() + timeout
        locked = cls._locked_files(pairs)
        while locked and time.time() < deadline:
            time.sleep(0.5)
            locked = cls._locked_files(pairs)
        return locked

    def _restart_stopped(self, record):
        """把本轮编排里已停 (且验证停成功) 的目标服务重新拉起 — 中止/异常路径兜底,
        杜绝"停着不起来"。"""
        names = [s.get("name") for s in (record.get("stop") or []) if s.get("ok")]
        started, failed = [], []
        for n in names:
            svc = self.svc_mgr.get(n)
            if svc is None:
                continue
            try:
                svc.start()
                started.append(n)
            except Exception as e:
                logger.error("[deploy] restart '%s' on abort failed: %s", n, e)
                failed.append(n)
        if started or failed:
            record["restarted_on_abort"] = {"started": started, "failed": failed}

    def _deploy_services(self, zip_name=None):
        """触发异步 deploy 编排。zip_name 缺省 = deploys/ 下最新 zip。"""
        if self._deploy_running:
            return {"error": "deploy already running, poll deploy_log"}
        deploys_dir = os.path.join(os.getcwd(), "deploys")
        zip_path = self._latest_deploy_zip(deploys_dir, zip_name)
        if not zip_path:
            hint = f" matching '{zip_name}'" if zip_name else ""
            return {"error": f"no deploy zip found in {deploys_dir}{hint}"}
        self._deploy_running = True  # deploy 编排锁 (互斥 restart/swap 守卫同源)
        log_path = os.path.join(os.getcwd(), self._DEPLOY_LOG)
        t = threading.Thread(target=self._deploy_async, args=(zip_path, log_path),
                             name="svc-deploy", daemon=True)
        t.start()
        return {"ok": True,
                "message": "deploy triggered (async), poll deploy_log for result",
                "log": log_path, "zip": os.path.basename(zip_path)}

    @staticmethod
    def _latest_deploy_zip(deploys_dir, zip_name=None):
        """定位 deploy zip: 指定名精确匹配, 缺省取 deploys/ 下文件名最大 (时间戳命名) 的。"""
        if zip_name:
            if not zip_name.endswith(".zip"):
                zip_name += ".zip"
            p = os.path.join(deploys_dir, zip_name)
            return p if os.path.isfile(p) else None
        if not os.path.isdir(deploys_dir):
            return None
        zips = [f for f in os.listdir(deploys_dir) if f.endswith(".zip")]
        return os.path.join(deploys_dir, max(zips)) if zips else None

    def _deploy_log(self):
        """返最近一次 deploy 编排状态 + 日志 (前端轮询)。running 与 update 共用编排锁。"""
        log_path = os.path.join(os.getcwd(), self._DEPLOY_LOG)
        result = {"running": self._deploy_running}
        if os.path.exists(log_path):
            try:
                with open(log_path, "r", encoding="utf-8") as f:
                    result["last"] = json.load(f)
            except Exception as e:
                result["error"] = f"read log failed: {e}"
        else:
            result["message"] = "no deploy log yet"
        return result

    def _services_hit_by(self, rel_files):
        """manifest 文件命中运行文件 (command/args 内路径) 的受管服务列表。

        deploy 包里出现某服务的 .py/.exe 运行文件 → 该服务需停 (解锁文件) 后替换。
        命中为空时由调用方回落默认 rust+legacy (纯模板/资源更新至少重启宿主)。
        """
        root = os.getcwd()
        rels = {rel.replace("\\", "/") for rel in rel_files}
        hits = []
        for svc in self.svc_mgr.services:
            if not (svc.enabled and svc.managed):
                continue
            for entry in [svc.command] + (svc.args or []):
                # strip+去引号: config.yaml 的 command 常带尾空格, 不归一则 relpath
                # 键带空格对不上 manifest (2026-09-09 WinError32 事故: exe 未停即替换)
                entry = (entry or "").strip().strip('"')
                if not entry:
                    continue
                full = entry if os.path.isabs(entry) else os.path.join(
                    svc.cwd or root, entry)
                try:
                    rel = os.path.relpath(full, root).replace("\\", "/")
                except ValueError:
                    continue
                if rel in rels:
                    hits.append(svc)
                    break
        return hits

    def _deploy_async(self, zip_path, log_path):
        """后台编排: 解压校验 → 定位受影响服务 → 停 → 备份+原位替换 → 启 → 探活
        → 失败自动恢复备份。每关键节点写 log_path (deploy_log 实时可见), finally 解锁+清 staging。
        """
        staging = None
        try:
            time.sleep(1.5)  # 让 activate 路由响应先发 (legacy 是被停目标)
            record = {"timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                      "zip": os.path.basename(zip_path), "stage": "start"}

            # 0) 解压 + manifest 校验 (files 全在包内才算合法)
            staging = os.path.join(os.path.dirname(zip_path),
                                   "_staging_" + time.strftime("%Y%m%d%H%M%S"))
            with zipfile.ZipFile(zip_path) as zf:
                zf.extractall(staging)
            manifest_path = os.path.join(staging, "manifest.json")
            if not os.path.isfile(manifest_path):
                raise RuntimeError("manifest.json missing in zip")
            with open(manifest_path, "r", encoding="utf-8") as f:
                manifest = json.load(f)
            files = manifest.get("files") or []
            missing = [rel for rel in files
                       if not os.path.isfile(os.path.join(staging, rel.replace("/", os.sep)))]
            if not files or missing:
                raise RuntimeError(f"manifest/files mismatch, missing in zip: {missing[:5]}")
            record["manifest"] = {"built_at": manifest.get("built_at"),
                                  "git_rev": manifest.get("git_rev"),
                                  "files": len(files)}
            record["stage"] = "unzipped"
            self._write_orchestration_record(log_path, record)
            logger.info("[deploy] zip ok: %d files, staging=%s", len(files), staging)

            # 1) 受影响服务: manifest 命中运行文件的服务; 无命中回落 rust+legacy。
            #    受保护服务 (AI 网关) 剔除: 不停, 其文件在替换阶段按保护域跳过。
            targets = [s for s in self._services_hit_by(files)
                       if s.name not in self._DEPLOY_PROTECTED]
            if not targets:
                targets = [s for n in self._DEPLOY_FALLBACK_NAMES
                           if (s := self.svc_mgr.get(n)) and s.enabled and s.managed]
            record["targets"] = [s.name for s in targets]

            # 1a) 停服 + 校验: stop() 对"非本宿主子进程"(孤儿/手工起/daemon) 会静默空转,
            #     日志照样写 stopped, 文件锁却还在 → 替换阶段才以 WinError32 炸出来。
            #     这里以端口是否仍 LISTENING 为判据, 不空则按端口强杀兜底, 并把结论写进 record。
            record["stop"] = [svc.stop_verified(timeout=15) for svc in targets]
            stop_failed = [s["name"] for s in record["stop"] if not s["ok"]]
            record["stage"] = "stopped"
            self._write_orchestration_record(log_path, record)
            logger.info("[deploy] stopped %s (detail=%s)", ", ".join(s.name for s in targets),
                        [(s["name"], s["how"]) for s in record["stop"]])
            if stop_failed:
                # 停不下来的服务, 其文件必然替换失败; 与其半途抛错留下半替换现场,
                # 不如带服务名提前中止, 并把已停的服务拉回来 (2026-09-13 WinError32 事故)。
                self._restart_stopped(record)
                record.update(ok=False, stage="aborted_stop_failed",
                              error=f"服务无法停止, 未执行替换: {stop_failed} "
                                    f"→ 详见 record.stop (端口被非本宿主进程占用时需人工处理)",
                              finished_at=time.strftime("%Y-%m-%d %H:%M:%S"))
                self._write_orchestration_record(log_path, record)
                logger.error("[deploy] aborted: stop failed for %s", stop_failed)
                return

            # 2) 备份被覆盖文件 → 原位替换 (含新建目录; 覆盖前旧文件留 .deploy_backup/<ts>/)。
            #    受保护服务文件域 (前缀+运行文件) 跳过不替换 — 不停服就不能动其文件 (WinError32)。
            root = os.getcwd()
            prot_prefixes, prot_files = self._protected_scope()

            def _is_protected(rel: str) -> bool:
                return rel in prot_files or any(rel.startswith(p) for p in prot_prefixes)

            skipped_protected = [rel for rel in files if _is_protected(rel)]
            replace_pairs = [(rel, os.path.join(root, rel.replace("/", os.sep)))
                             for rel in files if not _is_protected(rel)]

            # 2a) 替换前可写探测: 进程退出后 image section 释放有延迟 (本地实测偶发 >2s,
            #     既有 handoff 记为 14s 量级)。固定 sleep 2s 赌不过去 → 轮询到可写为止,
            #     超时则带文件名提前中止, 而不是 copy 到一半抛 WinError32。
            locked = self._wait_writable(replace_pairs, timeout=15)
            if locked:
                self._restart_stopped(record)
                record.update(ok=False, stage="aborted_locked",
                              locked=[{"file": r, "error": e} for r, e in locked[:20]],
                              locked_count=len(locked),
                              error=f"{len(locked)} 个文件替换前仍被占用, 未执行替换",
                              finished_at=time.strftime("%Y-%m-%d %H:%M:%S"))
                self._write_orchestration_record(log_path, record)
                logger.error("[deploy] aborted: %d files locked: %s",
                             len(locked), [r for r, _ in locked[:5]])
                return

            backup_dir = os.path.join(root, ".deploy_backup", time.strftime("%Y%m%d%H%M%S"))
            backed = 0
            failures = []
            for rel, dst in replace_pairs:
                rel_os = rel.replace("/", os.sep)
                try:
                    if os.path.isfile(dst):
                        b = os.path.join(backup_dir, rel_os)
                        os.makedirs(os.path.dirname(b), exist_ok=True)
                        shutil.copy2(dst, b)
                        backed += 1
                    os.makedirs(os.path.dirname(dst), exist_ok=True)
                    shutil.copy2(os.path.join(staging, rel_os), dst)
                except OSError as e:
                    # per-file 容错: 单个文件失败不再炸掉整包, 记名继续 (2026-09-13)
                    failures.append({"file": rel, "error": f"{e.__class__.__name__}: {e}"})
                    logger.error("[deploy] replace failed: %s (%s)", rel, e)
            record["backup"] = {"dir": backup_dir, "files": backed}
            record["replaced"] = len(replace_pairs) - len(failures)
            record["replace_failures"] = failures
            record["skipped_protected"] = skipped_protected
            record["stage"] = "replaced"
            self._write_orchestration_record(log_path, record)
            logger.info("[deploy] replaced %d/%d files (%d backed up, %d failed) → %s",
                        len(replace_pairs) - len(failures), len(replace_pairs),
                        backed, len(failures), backup_dir)


            # 2b) 部分替换失败 → 恢复备份 (回滚 = 拷回 + 重启 + 再探活), 不留半替换现场。
            if failures:
                self._restore_backup(backup_dir, targets, record, log_path)
                record.update(ok=False, stage="rolled_back",
                              error=f"{len(failures)} 个文件替换失败, 已回滚",
                              finished_at=time.strftime("%Y-%m-%d %H:%M:%S"))
                self._write_orchestration_record(log_path, record)
                logger.error("[deploy] replace partial (%d failed) → rolled back", len(failures))
                return


            # 3) 启 + 探活 (30s)
            for svc in targets:
                svc.start()
            record["started_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
            record["stage"] = "started"
            self._write_orchestration_record(log_path, record)
            probe_ok, probe_detail = self._probe_all(targets, timeout=30)
            record["probe"] = probe_detail
            record["stage"] = "probed"
            self._write_orchestration_record(log_path, record)

            # 4) 失败自动恢复备份 (回滚 = 拷回备份 + 重启 + 再探活)
            if not probe_ok:
                record["ok"] = False
                self._restore_backup(backup_dir, targets, record, log_path)
                record["stage"] = "rolled_back"
            else:
                record["rollback"] = {"needed": False}
                record["ok"] = True
            record["finished_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
            record["stage"] = "done"
            self._write_orchestration_record(log_path, record)
            logger.info("[deploy] finished (ok=%s), log: %s", record["ok"], log_path)
        except Exception as e:
            logger.exception("deploy async failed: %s", e)
            # 补写进原 record (保留 targets/stopped 等已积累上下文), 不整覆盖
            if record is not None and isinstance(record, dict):
                record.update({"ok": False, "error": str(e), "stage": "error",
                               "finished_at": time.strftime("%Y-%m-%d %H:%M:%S")})
                # 兜底: 异常路径也要把已停的目标服务拉回来, 杜绝"停着不起来"
                self._restart_stopped(record)
                self._write_orchestration_record(log_path, record)
            else:
                self._write_orchestration_record(log_path, {"ok": False, "error": str(e),
                    "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"), "stage": "error"})
        finally:
            if staging and os.path.isdir(staging):
                shutil.rmtree(staging, ignore_errors=True)
            self._deploy_running = False

    def _restore_backup(self, backup_dir, targets, record, log_path):
        """恢复备份: 停 (坏产物可能 crash-loop, 先停解锁) → 拷回备份 → 启 → 再探活。"""
        logger.warning("[deploy] probe failed, restoring backup %s", backup_dir)
        detail = {"needed": True, "backup_dir": backup_dir}
        for svc in targets:
            if svc.running:
                svc.stop(timeout=15)
        root = os.getcwd()
        restored = 0
        for dirpath, _dirnames, fnames in os.walk(backup_dir):
            for fn in fnames:
                src = os.path.join(dirpath, fn)
                rel = os.path.relpath(src, backup_dir)
                shutil.copy2(src, os.path.join(root, rel))
                restored += 1
        detail["restored"] = restored
        for svc in targets:
            svc.start()
        ok, probe_detail = self._probe_all(targets, timeout=30)
        detail["probe_after"] = probe_detail
        record["rollback"] = detail
        self._write_orchestration_record(log_path, record)

    def _probe_svc(self, svc: ManagedService, timeout: float = 0.5) -> bool:
        """探活单个子服务: 进程存活 + (有端口) 端口 listening."""
        if not svc.running:
            return False
        if not svc.port:
            return True  # 无端口 → 进程存活即视为就绪
        try:
            with socket.create_connection(("127.0.0.1", svc.port), timeout=timeout):
                return True
        except OSError:
            return False

    def _probe_all(self, targets, timeout: float = 30):
        """探活全部 targets (30s 超时), 返 (ok, detail).
        detail: {ok, timeout, services: [{name, port, listening}]} (关键节点日志用).
        """
        results = {svc.name: False for svc in targets}
        deadline = time.time() + timeout
        while time.time() < deadline:
            all_ok = True
            for svc in targets:
                if results[svc.name]:
                    continue
                if self._probe_svc(svc):
                    results[svc.name] = True
                else:
                    all_ok = False
            if all_ok:
                break
            time.sleep(1)
        detail = {
            "ok": all(results.values()),
            "timeout": timeout,
            "services": [{"name": svc.name, "port": svc.port,
                          "listening": results[svc.name]} for svc in targets],
        }
        return detail["ok"], detail

    def _write_orchestration_record(self, log_path, record):
        """把当前 record 写编排日志 (deploy.log, 关键节点刷新, 供 deploy_log 轮询)."""
        try:
            with open(log_path, "w", encoding="utf-8") as f:
                json.dump(record, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning("write %s failed: %s", log_path, e)

    @staticmethod
    def _error(req_id, code: int, message: str) -> dict:
        return {"jsonrpc": "2.0", "id": req_id,
                "error": {"code": code, "message": message}}


def main():
    config = load_config()

    svc_mgr = ServiceGroupManager(config.get("services") or [])
    svc_mgr.start_all()

    ctl = ServiceControlServer(svc_mgr)
    ctl.start()

    # 阻塞等信号; ServiceGroupManager 监控线程是 daemon, 主线程必须存活
    stop_event = threading.Event()

    def _on_signal(signum, frame):
        logger.info("Signal %d received, shutting down ServiceGroup", signum)
        stop_event.set()

    signal.signal(signal.SIGINT, _on_signal)
    # Windows 仅 SIGINT 可达; SIGTERM 仅 POSIX 注册
    if hasattr(signal, "SIGTERM"):
        try:
            signal.signal(signal.SIGTERM, _on_signal)
        except (ValueError, OSError):
            pass

    logger.info("ServiceGroup manager (sgManager) running (no HTTP). Ctrl+C to stop.")
    try:
        while not stop_event.is_set():
            time.sleep(0.5)
    finally:
        ctl.stop()
        svc_mgr.stop_all()
        logger.info("sgManager shut down")


if __name__ == "__main__":
    main()
