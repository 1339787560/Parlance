import logging
import os
import signal
import subprocess
import sys

import threading
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

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
        try:
            out = subprocess.run(
                ["wmic", "process", "where", f"processid={pid}", "get", "parentprocessid"],
                capture_output=True, text=True, timeout=5,
            ).stdout
            for line in out.splitlines():
                line = line.strip()
                if line.isdigit():
                    return int(line)
        except:
            pass
        return None

    @staticmethod
    def _free_port(port: int) -> bool:
        """Kill all processes holding the port via netstat + taskkill /T."""
        if os.name != "nt":
            return False
        try:
            out = subprocess.run(
                ["netstat", "-ano"], capture_output=True, text=True, timeout=10
            ).stdout
            killed = False
            for line in out.splitlines():
                if "LISTENING" in line and f":{port}" in line:
                    pid_str = line.strip().split()[-1]
                    if not pid_str or pid_str == "0":
                        continue
                    pid = int(pid_str)
                    # Kill child process tree
                    subprocess.run(
                        ["taskkill", "/F", "/T", "/PID", str(pid)],
                        capture_output=True, timeout=5,
                    )
                    # Kill parent (reloader) too
                    parent = ManagedService._get_parent_pid(pid)
                    if parent and parent != 1:  # not SYSTEM
                        subprocess.run(
                            ["taskkill", "/F", "/T", "/PID", str(parent)],
                            capture_output=True, timeout=5,
                        )
                    logger.info("[svc] Killed PID %s (parent %s) to free port %d",
                               pid_str, parent or "?", port)
                    killed = True
            return killed
        except:
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

    def restart(self, timeout: float = 15):
        self.stop(timeout=timeout)
        self.start()

    # ── swap_exe: 热替换子服务 exe (规避 Windows 文件占用) ────────────────
    # 对齐 service-server update 简单模式: stop → sleep 2s → cp target/release
    # 同名 exe → start。无 verify/回滚 (失败手动处理)。仅 .exe 业务子服务。

    def swap_exe(self, timeout: float = 15) -> Dict[str, Any]:
        """简单热替换: stop → sleep 2s → cp target/release/{exe} → start。

        源 = exe 同项目 target/release/{basename} (cargo build --release 输出,
        agent 构建后直接落位)。目标 = config command 指向的运行位 exe。
        对齐 service-server update: 杀子服务 + 等 OS 释放句柄 + cp + 启,
        无 verify/回滚 (简单优先, 失败手动处理)。
        """
        import shutil

        exe_path = self._resolve_exe_path()
        if exe_path is None or not exe_path.lower().endswith(".exe"):
            return {"error": f"服务 '{self.name}' command '{self.command}' 非 .exe 业务路径, 不支持 swap_exe"}

        # 源 = exe 同项目 target/release/{basename}
        basename = os.path.basename(exe_path)
        project_dir = os.path.dirname(exe_path)
        new_exe = os.path.join(project_dir, "target", "release", basename)
        if not os.path.isfile(new_exe):
            return {"error": f"新 exe 不存在: {new_exe} (需先 cargo build --release)"}

        logger.info("[svc] swap_exe '%s': %s <- %s", self.name, exe_path, new_exe)

        # 1) stop 释放 exe 占用
        self.stop(timeout=timeout)
        # 2) 等 OS 释放文件句柄 (对齐 service-server sleep 2s)
        time.sleep(2)
        # 3) cp 新 exe 到运行位 (不 mv .bak, 无回滚)
        try:
            shutil.copyfile(new_exe, exe_path)
        except OSError as e:
            logger.error("[svc] swap_exe '%s' cp 失败: %s", self.name, e)
            return {"error": f"exe 替换失败: {e}", "name": self.name}
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
        }

    def _resolve_exe_path(self) -> Optional[str]:
        """解析 self.command 到 exe 绝对路径 (相对 host 进程 cwd)。

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
