#!/usr/bin/env python3
"""Cross-platform launcher entry for infoServer.

Single source of truth for Windows AND macOS: resolves the project's venv
Python interpreter, then exec()s run.py with argv forwarded untouched.

Priority:
    1. project .venv interpreter (win: .venv/Scripts/python.exe,
       posix: .venv/bin/python)
    2. uv (POSIX fallback when .venv missing but uv is on PATH)
    3. current interpreter

Double-click wrappers (start.bat / start.command) call this script so both
platforms share the same entry path.

Usage (identical on win / mac):
    python start.py             # keyboard mode (default)
    python start.py --no-input  # service mode
"""

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent
RUN_PY = ROOT / "run.py"

# ---- 监督模式（--supervise）契约 ----
# 目的: run.py 崩溃时由本层拉回来（未来 :5099 发布器移到 run.py 后, 它不能是单点）。
#
# 为什么**默认关闭**、需显式 --supervise:
#   run.py 的 `ctl stop` / `ctl quit` / `q` 键 / Ctrl+C **都会**让它退出（主循环条件
#   `_running and (service.running or _reloading)` 不再满足）。若无条件重拉, 这些"主动停止"
#   就全变成"重拉" —— 停止功能失效。故 run.py 对主动停止打标记并以 EXIT_DELIBERATE 退出,
#   本层见到该码即收手; 其它退出码（崩溃/main.py 意外死亡）才重拉。
SUPERVISE_FLAG = "--supervise"
EXIT_DELIBERATE = 42        # 必须与 run.py 的 EXIT_DELIBERATE 一致
FAST_WINDOW = 10.0          # 存活不足此秒数 = 快速失败
MAX_FAST = 5                # 连续快速失败上限（防配置错导致自旋刷屏）
BACKOFF = 3.0
BACKOFF_MAX = 30.0


def _supervise_nt(argv, *, backoff: float = BACKOFF, max_fast: int = MAX_FAST,
                  fast_window: float = FAST_WINDOW) -> int:
    """Windows 监督循环: 只有"非主动退出"才重拉。

    退避策略: 每次快速失败退避翻倍（base → BACKOFF_MAX）; 连续 max_fast 次快速失败即放弃
    （返回该退出码, 交回 start_admin.bat 的 pause 让人看到现场）——避免坏配置下无限自旋。
    """
    fails = 0
    sleep_s = backoff
    # 告知 run.py「我在被监督」→ 它才用 EXIT_DELIBERATE 保留码（未受监督时保持 exit 0，
    # 不把非 0 码暴露给 SCM 之类的宿主）。
    child_env = dict(os.environ, INFOSERVER_SUPERVISED="1")
    while True:
        t0 = time.monotonic()
        rc = subprocess.run(argv, env=child_env).returncode
        alive = time.monotonic() - t0

        if rc == EXIT_DELIBERATE:
            print("[start] sgmController 主动退出 (rc=%d) —— 不重拉" % rc)
            return 0

        if alive < fast_window:
            fails += 1
            if fails >= max_fast:
                print("[start] 连续 %d 次快速失败 (rc=%d, 存活 %.1fs) —— 放弃重拉, 请人工排查"
                      % (fails, rc, alive))
                return rc
            sleep_s = min(sleep_s * 2, BACKOFF_MAX)
        else:
            fails = 0
            sleep_s = backoff

        print("[start] sgmController 退出 (rc=%d, 存活 %.1fs) —— %.1fs 后重拉"
              % (rc, alive, sleep_s))
        time.sleep(sleep_s)


def _venv_python() -> Optional[Path]:
    if os.name == "nt":
        p = ROOT / ".venv" / "Scripts" / "python.exe"
    else:
        p = ROOT / ".venv" / "bin" / "python"
    return p if p.exists() else None


def _resolve_python() -> str:
    """Pick the interpreter to run run.py under.

    Re-exec into venv python only when we are NOT already running under it
    (avoids infinite exec loop when start.py is invoked via the venv itself).
    """
    venv = _venv_python()
    if venv and os.path.realpath(sys.executable) != os.path.realpath(str(venv)):
        return str(venv)
    if os.name != "nt" and not venv and shutil.which("uv"):
        return "uv"
    return sys.executable


def main() -> int:
    py = _resolve_python()
    supervise = SUPERVISE_FLAG in sys.argv[1:]
    # --supervise 由本层消费, 不转发给 run.py（run.py 不认识它）
    forwarded = [a for a in sys.argv[1:] if a != SUPERVISE_FLAG]
    argv = [py]
    if py == "uv":
        argv += ["run", "python"]
    argv += [str(RUN_PY), *forwarded]

    # Windows: os.execvp 对含空格的 sys.executable (如 "C:\Program Files\Python313\...")
    # 会拆分成 "C:\Program" + "Files\..." 致 "can't open file" 错误.
    # 改用 subprocess 正确传递 argv, 退出码透传.
    if os.name == "nt":
        if supervise:
            try:
                return _supervise_nt(argv)
            except KeyboardInterrupt:
                print("\n[start] Ctrl+C —— 停止监督（不再重拉）")
                return 130
        result = subprocess.run(argv)
        return result.returncode

    # POSIX: exec replaces this process so signals (Ctrl+C) reach run.py directly.
    # --supervise 目前仅 Windows: POSIX 走 exec 替身, 无法在本层监督（需要时改成
    # subprocess + 信号转发）。
    if supervise:
        print("[start] --supervise 仅 Windows 生效; POSIX 继续 exec 替身")
    os.execvp(py, argv)
    return 0  # unreachable; os.execvp raises on failure


if __name__ == "__main__":
    raise SystemExit(main())
