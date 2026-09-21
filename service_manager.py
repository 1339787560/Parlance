import json
import logging
import os
import signal
import subprocess
import sys

import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def wait_writable(path: str, timeout: float = 15, interval: float = 0.5) -> bool:
    """轮询到 path 能打开写句柄为止 (最多 timeout 秒)。

    进程退出后 Windows 释放 image section 有延迟 (本地实测偶发 >2s, 既有 handoff
    记为 14s 量级), 固定 sleep 赌不过去。文件不存在视为可写 (新建场景)。
    """
    deadline = time.time() + timeout
    while True:
        if not os.path.exists(path):
            return True
        try:
            with open(path, "r+b"):
                return True
        except OSError:
            if time.time() >= deadline:
                return False
            time.sleep(interval)

# ── Windows Job Object (foreground/managed mode only) ─────────────────────
_WIN_JOB = None

def _ensure_job():
    global _WIN_JOB
    if os.name != "nt" or _WIN_JOB is not None:
        return False
    import ctypes
    k32 = ctypes.windll.kernel32

    class BL(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_int64),
            ("PerJobUserTimeLimit", ctypes.c_int64),
            ("LimitFlags", ctypes.c_uint32),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", ctypes.c_uint32),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", ctypes.c_uint32),
            ("SchedulingClass", ctypes.c_uint32),
        ]

    class IO(ctypes.Structure):
        _fields_ = [("R", ctypes.c_uint64), ("W", ctypes.c_uint64), ("O", ctypes.c_uint64),
                    ("RT", ctypes.c_uint64), ("WT", ctypes.c_uint64), ("OT", ctypes.c_uint64)]

    class EL(ctypes.Structure):
        _fields_ = [("Basic", BL), ("Io", IO),
                    ("_p1", ctypes.c_uint32 * 4), ("_p2", ctypes.c_uint32 * 4),
                    ("_p3", ctypes.c_uint32 * 4), ("_p4", ctypes.c_uint32 * 4)]

    job = k32.CreateJobObjectW(None, None)
    if not job:
        return False

    info = EL()
    info.Basic.LimitFlags = 0x2000
    if not k32.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info)):
        k32.CloseHandle(job)
        return False

    _WIN_JOB = job
    return True


def _assign_job(proc) -> bool:
    if os.name != "nt" or _WIN_JOB is None:
        return False
    import ctypes
    k32 = ctypes.windll.kernel32
    h = getattr(proc, '_handle', None)
    if not h:
        h = k32.OpenProcess(0x1F0FFF, False, proc.pid)
        if not h:
            return False
        ok = k32.AssignProcessToJobObject(_WIN_JOB, h)
        k32.CloseHandle(h)
        return bool(ok)
    return bool(k32.AssignProcessToJobObject(_WIN_JOB, h))


class ManagedService:
    """Subprocess wrapper. Two modes:

    managed=True (foreground/CLI):
      - Pipes stdout/stderr → logger
      - Assigned to Job Object → killed on parent exit
      - stop()/restart() works
      - ⚠ Orphan risk if parent force-killed before Job Object cleanup

    managed=False (daemon):
      - No pipe, no tracking, fire-and-forget
      - Child survives parent exit
      - stop()/restart() not supported
    """

    def __init__(self, name: str, command: str, args: Optional[List[str]] = None,
                 cwd: Optional[str] = None, env: Optional[dict] = None,
                 auto_restart: bool = False, health_check: Optional[dict] = None,
                 tags: Optional[List[str]] = None, enabled: bool = True,
                 managed: bool = True, port: Optional[int] = None):
        self.name = name
        self.command = command
        self.args = args or []
        self.cwd = cwd
        self.env = env or {}
        self.auto_restart = auto_restart
        self.health_check = health_check
        self.tags = tags or []
        self.enabled = enabled
        self.managed = managed
        self.port = port

        self._process: Optional[subprocess.Popen] = None
        self._stop_event = threading.Event()
        self._start_time: Optional[float] = None
        self._exit_code: Optional[int] = None
        self._last_error: Optional[str] = None

        # Auto-restart policy: 3 quick retries, then hourly
        self._crash_restart_count: int = 0
        self._stability_seconds: int = 60      # runs longer → consider stable, reset counter
        self._max_quick_retries: int = 3
        self._backoff_seconds: int = 3600      # 1 hour

    # ── Properties ──────────────────────────────────────────────────────

    @property
    def running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    @property
    def pid(self) -> Optional[int]:
        return self._process.pid if self._process else None

    @property
    def status(self) -> str:
        if self._process is None:
            return "stopped"
        if self.running:
            return "running"
        return "exited"

    @property
    def uptime(self) -> Optional[float]:
        if self.running and self._start_time:
            return time.time() - self._start_time
        return None

    # ── Lifecycle ───────────────────────────────────────────────────────

    @staticmethod
    def _get_parent_pid(pid: int) -> Optional[int]:
        """Get parent PID via wmic."""
        return ManagedService._get_parent_info(pid)[0]

    @staticmethod
    def _get_parent_info(pid: int) -> tuple:
        """(parent_pid, parent_image_name); 失败返 (None, None)。

        wmic 在 Win11 已被移除 (本机实测 FileNotFoundError), 故回退 PowerShell CIM。
        """
        # 1) wmic (老系统)
        try:
            out = subprocess.run(
                ["wmic", "process", "where", f"processid={pid}",
                 "get", "parentprocessid,name"],
                capture_output=True, text=True, timeout=5,
            ).stdout
            ppid, name = None, ""
            for line in out.splitlines():
                toks = line.split()
                if not toks:
                    continue
                num = next((t for t in toks if t.isdigit()), None)
                img = next((t for t in toks if t.lower().endswith(".exe")), None)
                if num is None:
                    continue
                ppid = int(num)
                name = (img or "").lower()
                break
            if ppid is not None:
                return ppid, name
        except Exception:
            pass
        # 2) PowerShell CIM 回退
        try:
            out = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command",
                 f"(Get-CimInstance Win32_Process -Filter 'ProcessId={pid}') | "
                 f"Select-Object -Property ParentProcessId,Name | ConvertTo-Json -Compress"],
                capture_output=True, text=True, timeout=15,
            ).stdout.strip()
            if out:
                d = json.loads(out)
                if isinstance(d, list):
                    d = d[0] if d else {}
                return d.get("ParentProcessId"), (d.get("Name") or "").lower()
        except Exception:
            pass
        return None, None

    @staticmethod
    def _netstat_listeners(port: int) -> List[int]:
        """监听该端口的 PID 列表 (netstat -ano)。端口列末段精确比较, 避免 :500 撞 :5002。"""
        pids: List[int] = []
        if os.name != "nt" or port is None:
            return pids
        try:
            out = subprocess.run(
                ["netstat", "-ano"], capture_output=True, text=True, timeout=10
            ).stdout
        except Exception:
            return pids
        for line in out.splitlines():
            parts = line.split()
            if len(parts) < 5 or "LISTENING" not in parts:
                continue
            if parts[1].rsplit(":", 1)[-1] != str(port):
                continue
            try:
                pid = int(parts[-1])
            except ValueError:
                continue
            if pid and pid not in pids:
                pids.append(pid)
        return pids

    def _free_port(self, port: int, kill_parent: bool = True) -> bool:
        """Kill all processes holding the port via netstat + taskkill /T。

        kill_parent: 连父进程一起杀 —— 仅对"父进程与自己同镜像"的情况生效 (python
        reloader 的父进程也是 python.exe)。旧实现无条件杀父进程 (除 SYSTEM), 在
        端口被非本宿主进程占用时可能顺着 PPID 误杀无关进程 (PPID 不随父进程退出
        而更新, 可能已被系统复用) — 2026-09-13 收窄。
        """
        if os.name != "nt":
            return False
        own_image = os.path.basename((self.command or "").strip().strip('"')).lower()
        try:
            killed = False
            for pid in self._netstat_listeners(port):
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(pid)],
                    capture_output=True, timeout=5,
                )
                parent, parent_img = (None, "")
                if kill_parent:
                    parent, parent_img = self._get_parent_info(pid)
                    if parent and parent != 1 and parent != os.getpid() \
                            and own_image and parent_img == own_image:
                        subprocess.run(
                            ["taskkill", "/F", "/T", "/PID", str(parent)],
                            capture_output=True, timeout=5,
                        )
                    elif parent:
                        logger.info("[svc] skip parent kill PID %s (%s ≠ %s)",
                                    parent, parent_img or "?", own_image or "?")
                logger.info("[svc] Killed PID %s (parent %s/%s) to free port %d",
                            pid, parent or "-", parent_img or "-", port)
                killed = True
            return killed
        except Exception:
            pass
        return False

    def start(self):
        if self.running:
            logger.warning("Service %s already running", self.name)
            return

        if not self.enabled:
            logger.info("Service '%s' disabled, skipping", self.name)
            return

        self._stop_event.clear()
        self._last_error = None
        self._exit_code = None

        # Pre-flight: cwd must exist if specified
        if self.cwd and not os.path.isdir(self.cwd):
            self._last_error = f"cwd '{self.cwd}' not found"
            logger.warning("[svc] '%s' skipped: %s", self.name, self._last_error)
            self.enabled = False
            return

        # Pre-flight: command must be resolvable (PATH lookup or direct path)
        import shutil
        if not (os.path.isfile(self.command) or shutil.which(self.command)):
            self._last_error = f"command '{self.command}' not found"
            logger.warning("[svc] '%s' skipped: %s", self.name, self._last_error)
            self.enabled = False
            return

        # Free configured port before start
        if self.port is not None:
            self._free_port(self.port)
            time.sleep(0.3)  # let OS release socket

        proc_env = os.environ.copy()
        if self.env:
            proc_env.update(self.env)

        for attempt in range(2):
            try:
                if self.managed:
                    _ensure_job()
                    cf = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0

                    self._process = subprocess.Popen(
                        [self.command] + self.args,
                        cwd=self.cwd, env=proc_env,
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                        creationflags=cf,
                    )
                    _assign_job(self._process)
                else:
                    self._process = subprocess.Popen(
                        [self.command] + self.args,
                        cwd=self.cwd, env=proc_env,
                    )

                self._start_time = time.time()

                # Check immediate crash (e.g. port conflict)
                if self._process.poll() is not None:
                    code = self._process.returncode
                    if attempt == 0 and self.port is not None:
                        logger.warning("[svc] '%s' exited (code %d), freeing port and retry...",
                                       self.name, code)
                        self._free_port(self.port)
                        time.sleep(0.5)  # let OS release socket + reloader die
                        self._process = None
                        continue
                    self._last_error = f"Exit code {code}"
                    logger.error("[svc] '%s' start failed: %s", self.name, self._last_error)
                    return

                mode = "foreground" if self.managed else "daemon"
                logger.info("[svc] '%s' started (PID %d, %s)", self.name, self._process.pid, mode)

                t = threading.Thread(target=self._monitor if self.managed else self._wait_daemon, daemon=True)
                t.start()
                return

            except FileNotFoundError:
                self._last_error = f"Command '{self.command}' not found"
                logger.warning("[svc] '%s' skipped: %s", self.name, self._last_error)
                self.enabled = False
                return
            except OSError as e:
                # exe 被独占锁住时 Popen 直接 WinError32; 不能让启动失败炸掉调用方
                # (deploy 编排 / 管道 RPC 都经这里), 记 _last_error 后如实返回。
                self._last_error = f"{e.__class__.__name__}: {e}"
                logger.error("[svc] '%s' start failed: %s", self.name, self._last_error)
                return

    def stop(self, timeout: float = 15):
        if not self.managed:
            logger.info("Service '%s' is daemon, stop not supported", self.name)
            return
        self._stop_event.set()
        if not self._process:
            return

        pid = self._process.pid
        logger.info("Stopping service '%s' (PID %d)", self.name, pid)

        try:
            self._kill_tree(pid)
            self._process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            logger.warning("Service '%s' didn't stop in %ds", self.name, timeout)
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(pid)],
                    capture_output=True, timeout=5,
                )
        except Exception as e:
            self._last_error = str(e)
            logger.error("Error stopping service '%s': %s", self.name, e)

    def stop_verified(self, timeout: float = 15, force_port: bool = True) -> Dict[str, Any]:
        """停服 + **校验真的停了**。返回 {name, ok, how, pid, port_pids, detail}。

        stop() 对两种情况会静默空转: ① `managed=false` (daemon) ② `_process is None`
        (进程不是本宿主 spawn 的 — 孤儿/手工起/上一代宿主遗留)。此时日志照样写
        "stopped", 文件锁却还在, 替换阶段才以 WinError32 暴露, 排查成本极高。
        这里以"端口是否还有 LISTENING"为唯一判据, 不空则按端口强杀兜底
        (kill_parent=False — 不能把宿主自己的进程树当 reloader 顺手杀掉)。
        """
        info: Dict[str, Any] = {"name": self.name, "ok": False, "how": None,
                                "pid": self.pid, "port_pids": [], "detail": ""}
        self.stop(timeout=timeout)
        info["port_pids"] = self._netstat_listeners(self.port)
        if not info["port_pids"]:
            info["ok"] = True
            info["how"] = "handle" if info["pid"] else "dead"
            return info
        info["detail"] = f"stop() 未生效, 端口 {self.port} 仍被 PID {info['port_pids']} 占用"
        if not force_port:
            info["how"] = "still_listening"
            return info
        self._free_port(self.port, kill_parent=False)
        info["port_pids"] = self._netstat_listeners(self.port)
        if not info["port_pids"]:
            info["ok"] = True
            info["how"] = "port_kill"
            return info
        info["how"] = "port_kill_failed"
        info["detail"] += " → 按端口强杀仍失败 (权限不足?)"
        return info

    def restart(self, timeout: float = 15, force_port: bool = True):
        """停 (带校验, 端口判据兜底) → 启。句柄丢了也能停掉 (2026-09-13)。"""
        info = self.stop_verified(timeout=timeout, force_port=force_port)
        self.start()
        return info

    # ── swap_exe: 热替换子服务 exe (规避 Windows 文件占用) ────────────────
    # stop(带校验) → 等到运行位可写 → cp 新 exe → start。
    # 源缺省 = 同项目 target/release/{basename}; src 显式给出时用它 (deploy 从
    # staging 换 exe 走这条)。句柄永远留在宿主: 停/起都经本对象, 不外部 Popen。

    def swap_exe(self, timeout: float = 15, src: Optional[str] = None) -> Dict[str, Any]:
        """热替换运行位 exe。

        src 缺省 = exe 同项目 target/release/{basename} (cargo build --release 输出);
        src 显式给出 (绝对路径或相对 infoServer 根) → 用该文件, 供 deploy 编排
        从 staging 换 exe。停服走 stop_verified (端口判据 + 强杀兜底), 替换前
        轮询等文件可写 (进程退出后 image section 释放有延迟, 固定 sleep 2s 不够)。
        """
        import shutil

        exe_path = self._resolve_exe_path()
        if exe_path is None or not exe_path.lower().endswith(".exe"):
            return {"error": f"服务 '{self.name}' command '{self.command}' 非 .exe 业务路径, 不支持 swap_exe"}

        basename = os.path.basename(exe_path)
        if src:
            cand = Path(src)
            if not cand.is_absolute():
                cand = Path(os.getcwd()) / src
            new_exe = str(cand)
        else:
            new_exe = os.path.join(os.path.dirname(exe_path), "target", "release", basename)
        if not os.path.isfile(new_exe):
            return {"error": f"新 exe 不存在: {new_exe}"
                             + ("" if src else " (需先 cargo build --release)")}

        logger.info("[svc] swap_exe '%s': %s <- %s", self.name, exe_path, new_exe)

        # 1) stop + 校验 (孤儿/句柄丢失也能靠端口强杀停掉)
        stop_info = self.stop_verified(timeout=timeout)
        # 2) 等到运行位真的可写 (替代固定 sleep 2s)
        if not wait_writable(exe_path, timeout=15):
            self.start()  # 别把服务留在停着的状态
            return {"error": f"运行位 exe 仍被占用, 未替换: {exe_path}"
                             f" (占用者非本宿主可停的进程, 需人工处理)",
                    "name": self.name, "port": self.port,
                    "restart_error": self._last_error, "stop": stop_info}
        # 3) 备份旧 exe → cp 新 exe 到运行位
        backup = None
        if os.path.isfile(exe_path):
            try:
                bdir = os.path.join(os.getcwd(), ".deploy_backup", time.strftime("%Y%m%d%H%M%S") + "_swap")
                os.makedirs(bdir, exist_ok=True)
                backup = os.path.join(bdir, basename)
                shutil.copy2(exe_path, backup)
            except OSError as e:
                logger.warning("[svc] swap_exe '%s' 备份旧 exe 失败 (继续): %s", self.name, e)
        try:
            shutil.copyfile(new_exe, exe_path)
        except OSError as e:
            logger.error("[svc] swap_exe '%s' cp 失败: %s", self.name, e)
            self.start()
            return {"error": f"exe 替换失败: {e}", "name": self.name,
                    "backup": backup, "stop": stop_info}
        # 4) start 拉新 exe
        self.start()

        return {
            "ok": True,
            "name": self.name,
            "port": self.port,
            "status": self.status,
            "pid": self.pid,
            "exe": exe_path,
            "new_exe": new_exe,
            "backup": backup,
            "stop": stop_info,
        }

    def _resolve_exe_path(self) -> Optional[str]:
        """解析 self.command 到 exe 绝对路径 (相对 sgManager 进程 cwd)。

        返 None = 不支持 swap (裸 PATH 名如 python/node, 或路径不存在)。
        基准: command 必须是显式文件路径 (绝对或相对含分隔符), 区分编译型
        业务 exe (./.../service-server.exe) 与解释器裸名 (python) — 后者
        shutil.which 虽命中 python.exe, 但那是系统解释器, 非托管业务二进制。
        """
        cmd = self.command
        if not (os.path.isabs(cmd) or os.path.sep in cmd or "/" in cmd or "\\" in cmd):
            return None
        if os.path.isabs(cmd):
            return cmd
        if os.path.isfile(cmd):
            return os.path.abspath(cmd)
        return None

    # ── Info ────────────────────────────────────────────────────────────

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "pid": self.pid,
            "running": self.running,
            "uptime": round(self.uptime, 1) if self.uptime else None,
            "exit_code": self._exit_code,
            "last_error": self._last_error,
            "auto_restart": self.auto_restart,
            "enabled": self.enabled,
            "managed": self.managed,
            "port": self.port,
            "tags": self.tags,
            "command": f"{self.command} {' '.join(self.args)}",
            "exe_path": self._resolve_exe_path(),  # 运行位 exe 绝对路径 (非 .exe 服务为 None);
                                                   # deploy 编排靠它把包内文件映射到 port
            "health_check_url": self.health_check.get("url") if self.health_check else None,
            "crash_restart_count": self._crash_restart_count,
            "in_backoff": self._crash_restart_count > self._max_quick_retries,
        }

    # ── Internal ────────────────────────────────────────────────────────

    def _kill_tree(self, pid: int):
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                capture_output=True, timeout=10,
            )
        else:
            # POSIX 无 Job Object: 递归杀后代(debugrelay/statistic 是 infoServer 子进程),
            # 再杀本进程; 不误杀 run.py 启动器(它是 infoServer 的父, 非子)。
            # 旧实现 os.killpg(os.getpgid(pid)) 会连 run.py 同组一起杀, 致 r 重载时启动器先死。
            self._kill_descendants_posix(pid)
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass

    @staticmethod
    def _kill_descendants_posix(pid: int):
        """递归 pgrep -P 找后代并 SIGKILL(POSIX 下 Win Job Object 的等效替代)。"""
        try:
            out = subprocess.run(
                ["pgrep", "-P", str(pid)],
                capture_output=True, text=True, timeout=5,
            ).stdout
        except Exception:
            return
        for line in out.split():
            try:
                child = int(line.strip())
            except ValueError:
                continue
            ManagedService._kill_descendants_posix(child)  # 先杀孙再杀子
            try:
                os.kill(child, signal.SIGKILL)
            except ProcessLookupError:
                pass

    def _check_stability(self, uptime: float):
        """If service ran long enough, reset crash counter (consider it healthy)."""
        if uptime >= self._stability_seconds:
            if self._crash_restart_count > 0:
                logger.info("[svc] '%s' ran for %.0fs (≥%ds), resetting crash counter",
                            self.name, uptime, self._stability_seconds)
            self._crash_restart_count = 0

    def _handle_restart(self):
        """Restart policy: 3 quick retries, then hourly backoff."""
        if not self.auto_restart or self._stop_event.is_set():
            return
        self._crash_restart_count += 1
        if self._crash_restart_count <= self._max_quick_retries:
            logger.info("[svc] Auto-restarting '%s' (attempt %d/%d)",
                        self.name, self._crash_restart_count, self._max_quick_retries)
            self.start()
        else:
            logger.warning("[svc] '%s' failed %d times, will retry in %ds",
                           self.name, self._crash_restart_count - 1, self._backoff_seconds)
            time.sleep(self._backoff_seconds)
            if not self._stop_event.is_set():
                logger.info("[svc] Retrying '%s' after backoff", self.name)
                self.start()

    def _monitor(self):
        """Foreground mode: read pipes concurrently, log output, detect exit."""
        assert self._process is not None

        def _read_pipe(pipe, log_fn, prefix):
            for line in pipe:
                log_fn("[%s] %s", prefix, line.decode(errors="replace").rstrip())

        t_out = threading.Thread(
            target=_read_pipe,
            args=(self._process.stdout, logger.info, self.name),
            daemon=True,
        )
        t_err = threading.Thread(
            target=_read_pipe,
            args=(self._process.stderr, logger.warning, self.name),
            daemon=True,
        )
        t_out.start()
        t_err.start()
        t_out.join()
        t_err.join()

        self._process.wait()
        self._exit_code = self._process.returncode
        uptime = (time.time() - self._start_time) if self._start_time else 0
        self._start_time = None
        logger.info("[svc] '%s' exited with code %d", self.name, self._exit_code)
        if self._exit_code != 0:
            self._last_error = f"Exit code {self._exit_code}"
        self._check_stability(uptime)
        self._handle_restart()

    def _wait_daemon(self):
        """Daemon mode: just wait for exit, no pipe reading."""
        assert self._process is not None
        self._process.wait()
        self._exit_code = self._process.returncode
        uptime = (time.time() - self._start_time) if self._start_time else 0
        self._start_time = None
        logger.info("[svc] daemon '%s' exited with code %d", self.name, self._exit_code)
        if self._exit_code != 0:
            self._last_error = f"Exit code {self._exit_code}"
        self._check_stability(uptime)
        self._handle_restart()


class ServiceGroupManager:
    """Manage group of external services."""

    def __init__(self, services_config: Optional[list] = None):
        self.services: List[ManagedService] = []
        self._name_map: Dict[str, ManagedService] = {}

        # 平台后缀:win / mac / None(Linux 及未知 → 回退基础字段)
        if sys.platform.startswith("win"):
            _plat = "win"
        elif sys.platform == "darwin":
            _plat = "mac"
        else:
            _plat = None

        for cfg in (services_config or []):
            # 平台专属 command/args/cwd 覆盖,缺省回退基础字段。
            # enabled 不覆盖:无 enabled_<plat> 的服务靠 pre-flight 跳过
            # (如 http-photo-server 在 Mac 上靠 cwd 预检跳过)。
            if _plat:
                command = cfg.get(f"command_{_plat}") or cfg.get("command")
                args_v = cfg.get(f"args_{_plat}")
                if args_v is None:            # 空列表 [] 也是合法值,用 is None 判断
                    args_v = cfg.get("args", [])
                cwd_v = cfg.get(f"cwd_{_plat}") or cfg.get("cwd")
            else:
                command = cfg.get("command")
                args_v = cfg.get("args", [])
                cwd_v = cfg.get("cwd")

            # 相对路径型 command 解析为绝对路径(相对父进程 cwd=项目根)。
            # subprocess.Popen 先 chdir(cwd) 再 execv,相对 executable 会按子进程
            # cwd(服务目录)解析而失败;此处提前 abspath 让 precheck 与 exec 一致。
            # bare 名(如 "python")与绝对路径均不动:前者走 PATH 查找,后者已确定。
            if command and not os.path.isabs(command) and ('/' in command or '\\' in command):
                command = os.path.abspath(command)
            # 基础 command 缺失时不崩(command=""),交 precheck 报 "command '' not found" 后跳过
            command = command or ""

            svc = ManagedService(
                name=cfg.get("name", "unnamed"),
                command=command,
                args=args_v,
                cwd=cwd_v,
                env=cfg.get("env", {}),
                auto_restart=cfg.get("auto_restart", False),
                health_check=cfg.get("health_check"),
                tags=cfg.get("tags", []),
                enabled=cfg.get("enabled", True),
                managed=cfg.get("managed", True),
                port=cfg.get("port"),
            )
            self.services.append(svc)
            self._name_map[svc.name] = svc

    def get(self, name: str) -> Optional[ManagedService]:
        return self._name_map.get(name)

    def start_all(self):
        foreground = [s for s in self.services if s.managed and s.enabled]
        daemon = [s for s in self.services if not s.managed and s.enabled]

        if foreground:
            logger.warning("─" * 50)
            logger.warning("⚠ 前台服务 (foreground/managed=true): 父进程退出时连带终止子进程")
            logger.warning("  但如果父进程被强制杀死（如任务管理器结束进程），")
            logger.warning("  子进程可能变成孤儿进程继续运行。")
            for s in foreground:
                logger.warning("  • %s (PID after start)", s.name)
            logger.warning("─" * 50)

        if daemon:
            logger.info("守护服务 (daemon/managed=false): 独立运行，不受父进程影响")
            for s in daemon:
                logger.info("  • %s", s.name)

        for svc in self.services:
            svc.start()

    def stop_all(self, timeout: float = 15):
        for svc in self.services:
            svc.stop(timeout=timeout)

    def status_all(self) -> List[Dict[str, Any]]:
        return [svc.to_dict() for svc in self.services]
