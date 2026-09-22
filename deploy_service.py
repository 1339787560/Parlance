#!/usr/bin/env python3
"""deploy 产物包直推通道 —— 发布器落在 L2 (run.py)。

链路: make_deploy_pack.py 打 zip (py+exe+资源+manifest) → `POST :5099/api/deploy/upload`
  (raw zip body) → 存 infoServer 根/deploys/ → `POST /api/deploy/activate` →
  **本模块异步编排** (非 exe 就地替换 / exe 经宿主管道换代 / 备份+失败回滚 /
  按落点决定收尾重启) → `GET /api/deploy/log` 轮询。

为什么发布器落 L2 (run.py) 而不是子服务 (2026-09-22 用户裁定, 见 SDD
`legacy退役与部署规范化` 决策日志):
  ① L2 的上级是 L1 (`start.py --supervise`) → 它能换掉下面全部 (含 main.py) 而自己
     由 L1 重拉 ⇒ **零组件需要"自我更新"**, 断掉"子服务当发布器"的绕行;
  ② 换 exe 时前端 :5000 正是被停目标, 走前端轮询在停机窗口必断 → 发布面必须在
     被停目标之外;
  ③ 谁 spawn 谁, 谁负责重启与替换谁: L2 spawn L3 (main.py), 故 L2 是唯一能
     reseat L3 (Job Object 重建) 的层。

铁律: exe 的停/起一律经宿主管道 (`svc` socket → L3 main.py) 的
  stop/start/swap_exe。谁 Popen 谁持有句柄 —— 句柄一旦落在宿主之外, 服务就再也
  停不掉、exe 永远换不了 (2026-09-13 堡垒机 53 孤儿 exe 事故)。

鉴权: 回环免口令; 非回环必须带 X-Deploy-Token (值 = env DEPLOY_TOKEN 或
  infoServer 根/deploy.token).
"""

import hashlib
import json
import logging
import os
import re
import secrets
import shutil
import subprocess
import threading
import time
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable, Dict, List, Optional
from urllib.parse import parse_qs, urlparse

from multiprocessing.connection import Client

logger = logging.getLogger("deploy")

ROOT = Path(__file__).resolve().parent

# ── 路径与常量 ──────────────────────────────────────────────────────────────
DEFAULT_PORT = 5099
DEPLOY_DIR = str(ROOT / "deploys")
DEPLOY_LOG_PATH = str(ROOT / "deploy.log")
DEPLOY_BACKUP_DIR = str(ROOT / ".deploy_backup")
DEPLOY_TOKEN_FILE = str(ROOT / "deploy.token")
DEPLOY_TOKEN_ENV = "DEPLOY_TOKEN"

# 工具自身 (:5000) —— `/api/deploy/self-restart` 的目标
TOOL_PORT = int(os.environ.get("SERVICESVR_TOOL_PORT", "5000"))

# legacy 目录前缀。**2026-09-22 U8 后该子服务已退役** —— 目录只承载「数据 +
# 数据层助手 (.py/.exe) + 页面模板 + config.json」, 且这些文件现由 **:5000 前台**读取
# (templates/*.html 与 src/** 每请求现读; config.json 亦然; 只有 templates.db 是启动时
# 打开)。故「动过 legacy 文件」的收尾 = **重启读取方 :5000**, 不再重启已不存在的 legacy 服务。
LEGACY_PREFIX = "serviceGroup/serviceServer-legacy/"

# 助手 exe (非服务二进制, 如 assetTool.exe): 目标机上没有对应的宿主服务/端口可换,
# 故**不**走 swap_exe, 也**不**按「未映射」判失败 —— 等同普通文件走「备份 + 就地替换」。
# 清单须与 make_deploy_pack.py 的 HELPER_EXES 保持一致 (两处同源)。
HELPER_EXES = {"serviceGroup/serviceServer-legacy/assetTool.exe"}

# 受保护服务的文件域: 打包默认不含其文件; 即使 manifest 含 (手动 --only 或旧包)
# 也不替换。statistic-server = 本机 AI API 网关 (DeepSeek 代理), 误停 = 断 AI 会话
# (2026-09-09 用户指令)。
PROTECTED_PREFIXES = ("serviceGroup/statisticServer/",)

# 落点分层 (收尾动作由"包动了谁"决定):
#   L2 文件 (run.py/start.py) → 发布器自己换代: 停 L3 → 退出非保留码 → L1 重拉新码
#   L3 文件 (main.py/service_manager.py) → reseat L3 (Job Object 重建, 全子服务重启)
#   legacy 目录文件 → 请宿主重启读取方 :5000 (U8: legacy 服务已退役; 见 LEGACY_PREFIX 注释)
LAUNCHER_FILES = ("run.py", "start.py")
HOST_FILES = ("main.py", "service_manager.py")

# 上传体上限 (500MB; 发布包含 exe, 几十 MB 量级)
MAX_UPLOAD_BYTES = 500 * 1024 * 1024

_ERR_UNAUTHORIZED = 401


# ── 纯函数 (可测) ───────────────────────────────────────────────────────────

def rel_to_root(path: str, root: str) -> Optional[str]:
    """绝对路径 → 相对 infoServer 根的 posix 形式; 不在根内返 None。"""
    if not path:
        return None
    try:
        rel = os.path.relpath(path, root)
    except (ValueError, TypeError):
        return None
    if rel.startswith(".."):
        return None
    return rel.replace("\\", "/")


def exe_from_command(command: Optional[str]) -> Optional[str]:
    """从服务 command 串抽运行位 exe (首 token 以 .exe 结尾时)。

    支持带引号的路径 (`"C:\\a b\\svc.exe" --flag`) —— 按空格裸切会在路径含空格时
    截成 `C:\\a` (legacy 旧实现的 bug), 故按引号优先取首 token。
    """
    if not command:
        return None
    cmd = str(command).strip()
    m = re.match(r'^"([^"]+)"', cmd) or re.match(r"^'([^']+)'", cmd) or re.match(r"^(\S+)", cmd)
    if not m:
        return None
    tok = m.group(1).strip()
    return tok if tok.lower().endswith(".exe") else None


def safe_zip_name(raw: Optional[str]) -> Optional[str]:
    """上传文件名归一: 取 basename (中和路径/穿越), 必须以 .zip 结尾。"""
    if not raw:
        return None
    name = os.path.basename(str(raw).strip().strip('"'))
    if not name or not name.lower().endswith(".zip"):
        return None
    if name in (".", ".."):
        return None
    return name


def looks_like_multipart(first_bytes: bytes) -> bool:
    """旧版客户端 (multipart/form-data) 嗅探 —— 上传契约 2026-09-22 起改为 raw body。

    multipart 体以 `--<boundary>` 开头 (RFC 7578), zip 以 `PK` 开头, 二者不冲突。
    """
    return first_bytes[:2] == b"--"


def is_loopback(peer: Optional[str]) -> bool:
    return peer in ("127.0.0.1", "::1", "localhost")


def auth_ok(peer: Optional[str], token_header: Optional[str], expected: Optional[str]) -> bool:
    """写操作鉴权: 回环免口令, 其余必须带 X-Deploy-Token。"""
    if is_loopback(peer):
        return True
    if not expected:
        return False
    return bool(token_header) and secrets.compare_digest(str(token_header), expected)


def classify_deploy_files(files: List[str],
                          svc_by_rel: Dict[str, dict],
                          helper_exes=HELPER_EXES,
                          protected_prefixes=PROTECTED_PREFIXES) -> Dict[str, list]:
    """包内文件三分类 (发布编排的核心判据)。

    - exe_plan : 映射到宿主服务的 .exe → 交宿主管道 swap_exe 换代 (就地拷贝必撞占用)
    - helper   : 助手 exe → 落 plain 通道 (备份 + 就地替换)
    - unmapped : 映射不到服务的 .exe → **显式失败** (绝不就地覆盖), 触发回滚
    - plain    : 其余文件 (py/资源/模板) → 备份 + 就地替换, 无需停服
    - protected: 受保护服务文件域 → 跳过不替换
    """
    helper_set = set(helper_exes)
    exe_plan, helper, protected, unmapped = [], [], [], []
    exe_rels = set()
    for rel in sorted(files):
        rel = rel.replace("\\", "/")
        if any(rel.startswith(p) for p in protected_prefixes):
            protected.append(rel)
            continue
        if rel in helper_set:
            helper.append(rel)
            continue
        if rel.lower().endswith(".exe"):
            svc = svc_by_rel.get(rel)
            if not svc or not svc.get("port"):
                unmapped.append(rel)
                continue
            exe_rels.add(rel)
            exe_plan.append({"name": svc.get("name"), "port": svc.get("port"), "rel": rel})
    skip = exe_rels | set(unmapped) | set(protected)
    plain = [r.replace("\\", "/") for r in files if r.replace("\\", "/") not in skip]
    return {"exe_plan": exe_plan, "helper": helper, "unmapped": unmapped,
            "plain": plain, "protected": protected}


def classify_targets(replaced: List[str],
                     launcher_files=LAUNCHER_FILES,
                     host_files=HOST_FILES,
                     legacy_prefix: str = LEGACY_PREFIX) -> Dict[str, bool]:
    """替换成功后该做什么收尾 —— 由"包动了哪一层"决定 (互斥, self_update 优先)。

    注: `restart_legacy` 键名保留历史, **含义自 U8 (2026-09-22) 起 = 重启 legacy 目录文件
    的读取方 :5000** (legacy 服务已退役; 该目录只剩数据/助手/模板, 由前台读取)。"""
    rels = [r.replace("\\", "/") for r in replaced]
    self_update = any(r in launcher_files for r in rels)
    reseat_l3 = any(r in host_files for r in rels) and not self_update
    restart_legacy = any(r.startswith(legacy_prefix) for r in rels) and not self_update
    return {"self_update": self_update, "reseat_l3": reseat_l3,
            "restart_legacy": restart_legacy}


# ── 宿主管道客户端 (L3 main.py 的 svc socket) ───────────────────────────────

SVC_CTL_PIPE_WIN = r"\\.\pipe\infoserver_svc"
SVC_CTL_SOCKET_POSIX = "/tmp/infoserver_svc.sock"


def _svc_ctl_address():
    if os.name == "nt":
        return (SVC_CTL_PIPE_WIN, "AF_PIPE")
    return (SVC_CTL_SOCKET_POSIX, "AF_UNIX")


def _connect_svc():
    addr, family = _svc_ctl_address()
    return Client(addr, family=family)


class SvcClient:
    """调 L3 stop/start/restart/swap_exe/services 的薄客户端 (unwrap JSON-RPC 信封)。"""

    def __init__(self, timeout: float = 15):
        self.timeout = timeout

    def call(self, method: str, params: Optional[dict] = None, timeout: float = None) -> dict:
        conn = _connect_svc()
        try:
            conn.send({"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}})
            resp = conn.recv()
        finally:
            try:
                conn.close()
            except Exception:
                pass
        if isinstance(resp, dict) and "jsonrpc" in resp and "result" in resp:
            return resp["result"]
        return resp


# ── 编排 ────────────────────────────────────────────────────────────────────

def host_diag(root: str) -> dict:
    """目标机自述 (远端读不到它的文件系统/进程表, 由它自己报进 deploy record):

    - host_files : 根级宿主代码指纹 —— 比对"磁盘到底是不是新版"
    - python_procs: 所有 python 进程 (PID/启动时间/命令行) —— 看是否残留孤儿宿主
      (旧宿主若在 launcher 退出后存活, 会继续占着 infoserver_svc 管道应答,
       新宿主即使起来了也接管不了 → "重启了却没生效" 的典型成因)
    """
    d = {"host_files": {}, "python_procs": None}
    for f in ("main.py", "service_manager.py", "run.py", "start.py"):
        p = os.path.join(root, f)
        try:
            with open(p, "rb") as fh:
                d["host_files"][f] = {
                    "sha1": hashlib.sha1(fh.read()).hexdigest()[:12],
                    "mtime": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(os.path.getmtime(p))),
                }
        except OSError as e:
            d["host_files"][f] = f"ERR {e}"
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
             "Select-Object ProcessId,CreationDate,CommandLine | ConvertTo-Json -Compress"],
            capture_output=True, text=True, timeout=25)
        raw = (r.stdout or "").strip()
        if raw:
            procs = json.loads(raw)
            if isinstance(procs, dict):
                procs = [procs]
            d["python_procs"] = [{"pid": x.get("ProcessId"), "created": x.get("CreationDate"),
                                  "cmd": (x.get("CommandLine") or "")[:160]} for x in procs]
    except Exception as e:
        d["python_procs"] = f"ERR {e.__class__.__name__}: {e}"
    return d


class DeployOrchestrator:
    """发布编排主体 (在后台线程里跑)。

    回调 (由 run.py 注入, 让本模块不依赖 SgmController 内部):
      on_self_update() : 包动了 run.py/start.py → 发布器自己换代 (停 L3 + 退出等 L1 重拉)
      on_reseat_l3()   : 包动了 main.py/service_manager.py → reseat L3
    """

    def __init__(self, root: str, svc: SvcClient,
                 on_self_update: Optional[Callable[[], None]] = None,
                 on_reseat_l3: Optional[Callable[[], None]] = None,
                 diag_provider: Optional[Callable[[], dict]] = None):
        self.root = root
        self.svc = svc
        self.on_self_update = on_self_update or (lambda: None)
        self.on_reseat_l3 = on_reseat_l3 or (lambda: None)
        self.diag_provider = diag_provider or (lambda: host_diag(root))
        self.deploy_dir = os.path.join(root, "deploys")
        self.log_path = os.path.join(root, "deploy.log")
        self.backup_root = os.path.join(root, ".deploy_backup")
        self._lock = threading.Lock()
        self._running = False

    # ── 状态 ──
    @property
    def running(self) -> bool:
        return self._running

    def write_record(self, record: dict) -> None:
        try:
            with open(self.log_path, "w", encoding="utf-8") as f:
                json.dump(record, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning("write %s failed: %s", self.log_path, e)

    # ── 触发 ──
    def trigger(self, zip_name: Optional[str] = None) -> dict:
        with self._lock:
            if self._running:
                return {"success": False, "message": "已有 deploy 在跑, 查 /api/deploy/log"}
            zip_path = self._locate_zip(zip_name)
            if not zip_path:
                hint = f" matching '{zip_name}'" if zip_name else ""
                return {"success": False,
                        "message": f"找不到包: {self.deploy_dir}{hint}"}
            self._running = True
        record = {"timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                  "zip": os.path.basename(zip_path), "stage": "start"}
        self.write_record(record)
        threading.Thread(target=self._run_guarded, args=(zip_path, record),
                         name="deploy-orchestrate", daemon=True).start()
        return {"success": True,
                "message": f"deploy triggered (L2 编排): {os.path.basename(zip_path)}"
                           f" | 进度查 /api/deploy/log",
                "log": self.log_path, "zip": os.path.basename(zip_path)}

    def _locate_zip(self, zip_name: Optional[str]) -> Optional[str]:
        if zip_name:
            name = safe_zip_name(zip_name)
            if not name:
                return None
            p = os.path.join(self.deploy_dir, name)
            return p if os.path.isfile(p) else None
        if not os.path.isdir(self.deploy_dir):
            return None
        zips = [f for f in os.listdir(self.deploy_dir) if f.lower().endswith(".zip")]
        return os.path.join(self.deploy_dir, max(zips)) if zips else None

    def _run_guarded(self, zip_path: str, record: dict) -> None:
        try:
            self.run(zip_path, record)
        finally:
            with self._lock:
                self._running = False

    # ── 主编排 (从 legacy ServiceRoute.py::_deploy_run 搬来, 收尾动作按分层重写) ──
    def run(self, zip_path, record: dict) -> dict:
        staging = os.path.join(self.deploy_dir, "_staging_" + time.strftime("%Y%m%d%H%M%S"))
        try:
            with zipfile.ZipFile(zip_path) as zf:
                zf.extractall(staging)
            man_path = os.path.join(staging, "manifest.json")
            if not os.path.isfile(man_path):
                raise RuntimeError("manifest.json missing in zip")
            with open(man_path, "r", encoding="utf-8") as f:
                manifest = json.load(f)
            files = [str(r).replace("\\", "/") for r in (manifest.get("files") or [])]
            missing = [r for r in files
                       if not os.path.isfile(os.path.join(staging, r.replace("/", os.sep)))]
            if not files or missing:
                raise RuntimeError(f"manifest/files mismatch, missing: {missing[:5]}")
            record["manifest"] = {"built_at": manifest.get("built_at"),
                                  "git_rev": manifest.get("git_rev"), "files": len(files)}
            record["stage"] = "unzipped"
            record["host_diag"] = self.diag_provider()
            self.write_record(record)

            # 目标 exe: 凡包内 .exe 一律走宿主管道换代 (就地拷贝必撞运行中占用)。
            svc_by_rel = {}
            host_svcs = self._host_services()
            record["host_probe"] = {"services": len(host_svcs),
                                    "exe_path_present": any("exe_path" in s for s in host_svcs)}
            for s in host_svcs:
                rel = rel_to_root(s.get("exe_path") or "", self.root) \
                    or rel_to_root(exe_from_command(s.get("command")) or "", self.root)
                if rel:
                    svc_by_rel[rel] = s
            cls = classify_deploy_files(files, svc_by_rel)
            exe_plan, unmapped = cls["exe_plan"], cls["unmapped"]
            record["exe_plan"] = [{"name": e["name"], "port": e["port"], "file": e["rel"]}
                                  for e in exe_plan]
            record["helper_exes"] = sorted(cls["helper"])
            if cls["protected"]:
                record["skipped_protected"] = sorted(cls["protected"])
            if unmapped:
                record["unmapped_exe"] = sorted(unmapped)

            # 1) 非 exe 文件: 备份 + 就地替换 (运行中的进程不锁 .py/.html, 无需停服)
            backup_dir = os.path.join(self.backup_root, time.strftime("%Y%m%d%H%M%S") + "_deploy")
            backed, replaced, failures = 0, [], []
            for rel in unmapped:
                failures.append({"file": rel,
                                 "error": "exe 未映射到宿主服务 (缺 exe_path/port), 拒绝就地覆盖"})
            for rel in cls["plain"]:
                rel_os = rel.replace("/", os.sep)
                dst = os.path.join(self.root, rel_os)
                try:
                    if os.path.isfile(dst):
                        b = os.path.join(backup_dir, rel_os)
                        os.makedirs(os.path.dirname(b), exist_ok=True)
                        shutil.copy2(dst, b)
                        backed += 1
                    os.makedirs(os.path.dirname(dst), exist_ok=True)
                    shutil.copy2(os.path.join(staging, rel_os), dst)
                    replaced.append(rel)
                except OSError as e:
                    failures.append({"file": rel, "error": f"{e.__class__.__name__}: {e}"})
                    logger.error("[deploy] 替换失败 %s: %s", rel, e)
            record["backup"] = {"dir": backup_dir, "files": backed}
            record["replaced"] = len(replaced)
            record["stage"] = "replaced"
            self.write_record(record)

            # 2) exe: 交宿主管道换代 (宿主持有句柄, 停/起都在宿主侧)
            exe_done = []
            for e in exe_plan:
                item = dict(e)
                item["src"] = os.path.join(staging, e["rel"].replace("/", os.sep))
                r = self._swap_exe_via_host(item)
                out = {"file": e["rel"], "name": e.get("name"), "port": e.get("port"),
                       "how": r.get("how"), "backup": r.get("backup"), "error": r.get("error"),
                       "host_error": r.get("host_error"), "attempts": r.get("attempts")}
                if r.get("ok"):
                    exe_done.append(out)
                else:
                    failures.append(out)
            record["exe_done"] = exe_done
            record["stage"] = "exe_swapped"
            self.write_record(record)

            # 3) 有失败 → 恢复备份 (非 exe 拷回; exe 用宿主 swap 回备份) 并标记回滚
            if failures:
                restored = 0
                for rel in replaced:
                    src = os.path.join(backup_dir, rel.replace("/", os.sep))
                    try:
                        if os.path.isfile(src):
                            shutil.copy2(src, os.path.join(self.root, rel.replace("/", os.sep)))
                            restored += 1
                    except OSError:
                        pass
                for d in exe_done:
                    if d.get("backup"):
                        try:
                            self.svc.call("swap_exe", {"port": d.get("port"),
                                                       "src": d.get("backup")}, timeout=90)
                        except Exception:
                            pass
                record.update(ok=False, stage="rolled_back",
                              error=f"{len(failures)} 项失败, 已回滚",
                              failures=failures[:20], restored=restored,
                              finished_at=time.strftime("%Y-%m-%d %H:%M:%S"))
                self.write_record(record)
                logger.error("[deploy] %d 项失败 → 已回滚", len(failures))
                return record

            # 4) 成功 → 按"包动了哪一层"决定收尾重启
            actions = classify_targets(replaced)
            record.update(ok=True, stage="done", post=actions,
                          finished_at=time.strftime("%Y-%m-%d %H:%M:%S"))
            if actions["restart_legacy"]:
                record["restart_reader_port"] = TOOL_PORT
            self.write_record(record)   # ★ 必须在收尾动作之前落盘 (self_update 会退出本进程)

            if actions["self_update"]:
                logger.warning("[deploy] 包动了 L2 自身 (run.py/start.py) → 换代: 停 L3 后退出, "
                               "等 L1 --supervise 重拉新码")
                self.on_self_update()
            elif actions["reseat_l3"]:
                logger.warning("[deploy] 包动了 L3 (main.py/service_manager.py) → reseat L3")
                self.on_reseat_l3()
            elif actions["restart_legacy"]:
                # U8 (2026-09-22): legacy 服务已退役, 这些文件由 :5000 读取 ⇒ 重启 :5000 生效。
                # 若本次已换代 :5000 的 exe (swap_exe 自带停/起), 则跳过以免重复重启。
                if any(e.get("port") == TOOL_PORT for e in exe_done):
                    logger.info("[deploy] legacy 目录文件随 :5000 换代已重启生效, 跳过额外重启")
                else:
                    try:
                        self.svc.call("restart", {"port": TOOL_PORT}, timeout=90)
                    except Exception as e:
                        logger.warning("[deploy] 重启 :5000 (%s) 失败 (人工重启生效): %s",
                                       TOOL_PORT, e)
            return record
        except Exception as e:
            record.update(ok=False, stage="error", error=str(e),
                          finished_at=time.strftime("%Y-%m-%d %H:%M:%S"))
            self.write_record(record)
            logger.exception("[deploy] 编排异常: %s", e)
            return record
        finally:
            shutil.rmtree(staging, ignore_errors=True)

    # ── 宿主交互 ──
    def _host_services(self) -> list:
        try:
            r = self.svc.call("services")
        except Exception as e:
            logger.warning("[deploy] 取宿主服务清单失败: %s", e)
            return []
        if isinstance(r, dict):
            return r.get("services") or []
        return []

    def _swap_exe_via_host(self, e: dict) -> dict:
        """exe 换代: 优先宿主 swap_exe (句柄留宿主)。

        降级 (两条): ① 管道调用抛异常 (宿主没跑/管道断); ② 宿主返回错误 —— 典型是
        旧版宿主不认 src 参数 (只找 target/release), 即"宿主自己还没升到新版"的引导
        顺序死结。两种都退到本地路径: 自行按端口强杀 → 等可写 → 拷贝 → 请宿主 start
        (start 仍经宿主, 句柄最终回到宿主手里)。
        """
        host_err = None
        try:
            r = self.svc.call("swap_exe", {"port": e["port"], "src": e["src"]}, timeout=90)
            if isinstance(r, dict) and r.get("ok"):
                return {"ok": True, "how": "host", "backup": r.get("backup")}
            host_err = (r or {}).get("error") if isinstance(r, dict) else str(r)
            logger.warning("[deploy] 宿主 swap_exe 未成功 (%s), 降级本地处理", host_err)
        except Exception as ex:
            host_err = f"{ex.__class__.__name__}: {ex}"
            logger.warning("[deploy] 宿主 swap_exe 调用失败, 降级本地处理: %s", host_err)
        local = self._swap_exe_local(e)
        local["host_error"] = host_err   # 降级成功也留宿主原话, 区分"宿主旧版"/"宿主停不掉"
        return local

    def _swap_exe_local(self, e: dict) -> dict:
        """降级路径: **先请宿主停** (关键) → 按端口强杀 → 等可写 → 拷贝 → 请宿主启。

        "先请宿主停"不能省: 外部直接 taskkill 时宿主 monitor 会把服务自动拉起
        (它的 _stop_event 没被置位), 于是"刚杀完文件又被映射回去" —— 2026-09-13 在
        53 上实测踩到 (可写检查通过、紧接着 copy 报 WinError32)。走一次宿主管道
        stop 即置 _stop_event 抑制 auto_restart。
        """
        name, port, rel, src = e.get("name"), e.get("port"), e["rel"], e["src"]
        dst = os.path.join(self.root, rel.replace("/", os.sep))
        backup, last_err, attempts = None, None, 0
        try:
            if os.path.isfile(dst):
                bdir = os.path.join(self.backup_root, time.strftime("%Y%m%d%H%M%S") + "_exe")
                os.makedirs(bdir, exist_ok=True)
                backup = os.path.join(bdir, os.path.basename(dst))
                shutil.copy2(dst, backup)
            if port:
                try:
                    self.svc.call("stop", {"port": port}, timeout=60)
                except Exception as ex:
                    logger.warning("[deploy] 宿主管道 stop 失败 (继续自处理): %s", ex)
            for i in range(4):
                attempts = i + 1
                _kill_listener(port)
                if not _wait_writable(dst, 10):
                    last_err = f"等待可写超时 (第 {attempts} 轮)"
                    logger.warning("[deploy] %s", last_err)
                    continue
                try:
                    shutil.copy2(src, dst)
                    r = self.svc.call("start", {"port": port}, timeout=60)
                    return {"ok": bool(isinstance(r, dict) and r.get("ok")),
                            "how": "local", "backup": backup, "attempts": attempts,
                            "error": None if isinstance(r, dict) and r.get("ok")
                                     else f"宿主 start 失败: {r}"}
                except OSError as ce:
                    # 可写检查刚过、拷贝即失败 = 文件在这一瞬又被映射回去 (有人重新拉起进程)
                    last_err = f"copy 失败 (第 {attempts} 轮): {ce.__class__.__name__}: {ce}"
                    logger.warning("[deploy] %s", last_err)
                    time.sleep(1)
            if port:
                try:
                    self.svc.call("start", {"port": port}, timeout=60)
                except Exception:
                    pass
            return {"ok": False, "how": "local", "backup": backup, "attempts": attempts,
                    "error": last_err, "diag": _diag(dst, port)}
        except Exception as ex:
            return {"ok": False, "how": "local", "backup": backup, "attempts": attempts,
                    "error": f"{ex.__class__.__name__}: {ex}", "diag": _diag(dst, port)}


# ── 本地换 exe 的辅助 (netstat/taskkill; 仅降级路径用) ──────────────────────

def _kill_listener(port) -> None:
    """按端口强杀监听进程 (只杀监听 PID, 不碰父进程; 仅统计 LISTENING 行)。"""
    if not port:
        return
    try:
        out = subprocess.run(["netstat", "-ano"], capture_output=True, text=True,
                             timeout=10).stdout
    except Exception:
        return
    for line in out.splitlines():
        parts = line.split()
        if len(parts) < 5 or "LISTENING" not in parts or parts[1].rsplit(":", 1)[-1] != str(port):
            continue
        subprocess.run(["taskkill", "/F", "/T", "/PID", parts[-1]],
                       capture_output=True, timeout=10)
        logger.info("[deploy] 强杀端口 %s 监听进程 PID %s", port, parts[-1])


def _wait_writable(dst: str, timeout: float = 15) -> bool:
    # 目标不存在 = 新建文件, 没有"被占用"可言 → 立即放行。
    # (legacy 旧实现不判存在, 遇到新文件会白等满 timeout × 4 轮 = 40s, 实测踩到。)
    if not os.path.exists(dst):
        return True
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with open(dst, "r+b"):
                return True
        except OSError:
            time.sleep(0.5)
    return False


def _port_listeners(port) -> list:
    if not port:
        return []
    try:
        out = subprocess.run(["netstat", "-ano"], capture_output=True, text=True,
                             timeout=10).stdout
        return [l.strip() for l in out.splitlines()
                if "LISTENING" in l and l.split()[1].rsplit(":", 1)[-1] == str(port)]
    except Exception:
        return []


def _diag(dst: str, port) -> dict:
    """失败现场的旁证: 端口监听者 + 此刻是否可写。"""
    d = {"listeners": _port_listeners(port)}
    if not os.path.exists(dst):
        d["writable_now"] = "missing"
        return d
    try:
        with open(dst, "r+b"):
            d["writable_now"] = True
    except OSError as e:
        d["writable_now"] = f"{e.__class__.__name__}: {e}"
    return d


# ── HTTP 面 (:5099) ────────────────────────────────────────────────────────

def deploy_token() -> Optional[str]:
    """部署口令: env DEPLOY_TOKEN 优先 → 根/deploy.token → 生成一份。"""
    tok = (os.environ.get(DEPLOY_TOKEN_ENV) or "").strip()
    if tok:
        return tok
    try:
        if os.path.isfile(DEPLOY_TOKEN_FILE):
            with open(DEPLOY_TOKEN_FILE, "r", encoding="utf-8") as f:
                tok = f.read().strip()
        if not tok:
            tok = secrets.token_hex(16)
            with open(DEPLOY_TOKEN_FILE, "w", encoding="utf-8") as f:
                f.write(tok)
            logger.info("[deploy] 已生成部署口令 → %s (远端客户端用 X-Deploy-Token 头传递)",
                        DEPLOY_TOKEN_FILE)
        return tok or None
    except OSError as e:
        logger.warning("[deploy] 口令文件读写失败, 非本机部署将被拒绝: %s", e)
        return None


class _DeployHandler(BaseHTTPRequestHandler):
    server_version = "infoServerDeploy/1.0"
    protocol_version = "HTTP/1.1"

    # 让访问日志走 logging (launcher 控制台是 relay, 别直接写 stderr)
    def log_message(self, fmt, *args):
        logger.info("[deploy-http] %s - %s", self.address_string(), fmt % args)

    # ── helpers ──
    def _send_json(self, code: int, payload: dict):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _peer(self) -> str:
        return self.client_address[0] if self.client_address else ""

    def _authed(self) -> bool:
        peer = self._peer()
        # 回环先判: 免口令 —— 且**不触碰 token_provider**, 因为 deploy_token() 有副作用
        # (首次调用会生成 deploy.token 文件); 为 loopback 白造一个秘密没意义。
        if is_loopback(peer):
            return True
        token = self.server.token_provider()  # type: ignore[attr-defined]
        return auth_ok(peer, self.headers.get("X-Deploy-Token"), token)

    def _deny(self):
        self._send_json(_ERR_UNAUTHORIZED,
                        {"success": False,
                         "message": "部署口令缺失或错误 (需要 X-Deploy-Token 头; "
                                    "值见目标机 infoServer 根/deploy.token)"})

    def _read_body(self) -> bytes:
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            n = 0
        if n <= 0 or n > MAX_UPLOAD_BYTES:
            return b""
        return self.rfile.read(n)

    # ── routes ──
    def do_GET(self):
        if urlparse(self.path).path == "/api/deploy/log":
            orch = self.server.orchestrator  # type: ignore[attr-defined]
            result = {"running": orch.running}
            try:
                if os.path.isfile(orch.log_path):
                    with open(orch.log_path, "r", encoding="utf-8") as f:
                        result["last"] = json.load(f)
                else:
                    result["message"] = "no deploy log yet"
            except Exception as e:
                result["error"] = f"read deploy log failed: {e}"
            self._send_json(200, result)
            return
        self._send_json(404, {"success": False, "message": "not found"})

    def do_POST(self):
        path = urlparse(self.path).path
        if not self._authed():
            self._deny()
            return
        if path == "/api/deploy/upload":
            self._handle_upload()
        elif path == "/api/deploy/activate":
            self._handle_activate()
        elif path == "/api/deploy/self-restart":
            self._handle_self_restart()
        else:
            self._send_json(404, {"success": False, "message": "not found"})

    def _handle_upload(self):
        orch = self.server.orchestrator  # type: ignore[attr-defined]
        q = parse_qs(urlparse(self.path).query)
        raw_name = (self.headers.get("X-Deploy-Filename")
                    or (q.get("name") or [""])[0])
        if raw_name:
            # 显式给了名字就必须合法 —— 静默改名会让"推错包"看起来成功
            name = safe_zip_name(raw_name)
            if not name:
                self._send_json(400, {"success": False,
                                      "message": f"文件名必须以 .zip 结尾 (收到: {raw_name!r})"})
                return
        else:
            name = f"deploy_{time.strftime('%Y%m%d%H%M%S')}.zip"
        body = self._read_body()
        if not body:
            self._send_json(400, {"success": False,
                                  "message": "空 body 或 Content-Length 缺失/超限"})
            return
        if looks_like_multipart(body):
            self._send_json(400, {"success": False,
                                  "message": "upload 契约已改为 raw zip body "
                                             "(旧版 multipart 不再支持): 请用新版 "
                                             "make_deploy_pack.py 推送"})
            return
        try:
            os.makedirs(orch.deploy_dir, exist_ok=True)
            path = os.path.join(orch.deploy_dir, name)
            with open(path, "wb") as f:
                f.write(body)
            self._send_json(200, {"success": True, "name": name,
                                  "size": os.path.getsize(path), "saved": path})
        except OSError as e:
            self._send_json(500, {"success": False, "message": f"保存失败: {e}"})

    def _handle_activate(self):
        orch = self.server.orchestrator  # type: ignore[attr-defined]
        body = self._read_body()
        zip_name = None
        if body:
            try:
                zip_name = (json.loads(body.decode("utf-8")) or {}).get("zip")
            except Exception:
                zip_name = None
        out = orch.trigger(zip_name)
        self._send_json(200 if out.get("success") else 409, out)

    def _handle_self_restart(self):
        """工具自身 (:5000) 重启: 委派宿主 restart (句柄留宿主, 不做自杀式换代)。"""
        orch = self.server.orchestrator  # type: ignore[attr-defined]
        body = self._read_body()
        port = TOOL_PORT
        if body:
            try:
                port = int((json.loads(body.decode("utf-8")) or {}).get("port") or TOOL_PORT)
            except Exception:
                port = TOOL_PORT

        def _delayed():
            time.sleep(1.5)     # 给 HTTP 响应留出返回时间
            try:
                orch.svc.call("restart", {"port": port}, timeout=90)
            except Exception as e:
                logger.warning("[deploy] 自身重启失败 (人工重启生效): %s", e)

        threading.Thread(target=_delayed, name="deploy-self-restart", daemon=True).start()
        self._send_json(200, {"success": True, "message": f"restart scheduled (port {port})"})


class DeployServer:
    """ThreadingHTTPServer 封装 (port=0 时取随机端口, 便于测试)。"""

    def __init__(self, host: str, port: int, orchestrator: DeployOrchestrator,
                 root: Optional[str] = None, token_provider: Optional[Callable[[], Optional[str]]] = None):
        self.orchestrator = orchestrator
        self.token_provider = token_provider or deploy_token
        self._httpd = ThreadingHTTPServer((host, port), _DeployHandler)
        self._httpd.daemon_threads = True
        self._httpd.orchestrator = orchestrator       # type: ignore[attr-defined]
        self._httpd.token_provider = self.token_provider  # type: ignore[attr-defined]
        self._thread: Optional[threading.Thread] = None

    @property
    def port(self) -> int:
        return self._httpd.server_address[1]

    def start(self):
        self._thread = threading.Thread(target=self._httpd.serve_forever,
                                        name="deploy-http", daemon=True)
        self._thread.start()
        logger.info("发布面 (: %d) 已就绪 — POST /api/deploy/{upload,activate,self-restart}, "
                    "GET /api/deploy/log", self.port)

    def stop(self):
        try:
            self._httpd.shutdown()
        except Exception:
            pass
        try:
            self._httpd.server_close()
        except Exception:
            pass
        if self._thread is not None:
            self._thread.join(timeout=2)
