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
import sys
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent
RUN_PY = ROOT / "run.py"


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
    argv = [py]
    if py == "uv":
        argv += ["run", "python"]
    argv += [str(RUN_PY), *sys.argv[1:]]
    # exec replaces this process so signals (Ctrl+C) reach run.py directly.
    os.execvp(py, argv)
    return 0  # unreachable; os.execvp raises on failure


if __name__ == "__main__":
    raise SystemExit(main())
