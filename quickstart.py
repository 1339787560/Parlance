#!/usr/bin/env python3
"""infoServer Quickstart — setup & uninstall.

Usage:
    python quickstart.py                        # Setup: create venv + install deps
    python quickstart.py --startup              # Setup + register auto-start at boot
    python quickstart.py uninstall              # Remove auto-start + delete venv
    python quickstart.py uninstall --all        # Also delete data, logs, uploads
"""

import os
import sys
import shutil
import subprocess
import platform
from pathlib import Path

PROJECT = Path(__file__).resolve().parent
VENV_DIR = PROJECT / ".venv"

# Generated / runtime directories (safe to delete)
_CLEAN_DIRS = [".venv", "__pycache__", "logs"]
_CLEAN_ALL_DIRS = ["data", "uploads", "logs"]  # includes user data


def _venv_python() -> Path:
    if platform.system() == "Windows":
        return VENV_DIR / "Scripts" / "python.exe"
    return VENV_DIR / "bin" / "python"


def _venv_pip() -> Path:
    if platform.system() == "Windows":
        return VENV_DIR / "Scripts" / "pip.exe"
    return VENV_DIR / "bin" / "pip"


def _pip_index() -> list[str]:
    if os.environ.get("PIP_INDEX_URL"):
        return []
    return ["-i", "https://pypi.tuna.tsinghua.edu.cn/simple"]


def _run(cmd: list[str], **kw):
    print(f"  $ {' '.join(str(c) for c in cmd)}")
    subprocess.run([str(c) for c in cmd], cwd=str(PROJECT), check=True, **kw)


def _safe_rm(path: Path):
    if not path.exists():
        return
    if path.is_dir():
        shutil.rmtree(path)
        print(f"  🗑  {path.name}/")
    else:
        path.unlink()
        print(f"  🗑  {path.name}")


# ── Setup ────────────────────────────────────────────────────────────────────

def step_venv():
    py = _venv_python()
    if py.exists():
        print(f"✅  venv exists: {VENV_DIR}")
        return
    print("📦  Creating venv...")
    _run([sys.executable, "-m", "venv", str(VENV_DIR)])
    print(f"✅  venv created")


def step_deps():
    req = PROJECT / "requirements.txt"
    if not req.exists():
        print("⚠️  requirements.txt not found, skipping")
        return
    print("📦  Installing dependencies...")
    _run([_venv_pip(), "install", "--upgrade", "pip"])
    _run([_venv_pip(), "install", "-r", str(req)] + _pip_index())
    print("✅  Dependencies installed")


def step_startup():
    print("🚀  Registering startup service...")
    _run([_venv_python(), str(PROJECT / "startup.py"), "install"])


def do_setup(startup: bool):
    print()
    print("╔══════════════════════════════════════╗")
    print("║         infoServer Setup              ║")
    print("╚══════════════════════════════════════╝")
    print(f"  Project : {PROJECT}")
    print(f"  Python  : {sys.executable}")
    print(f"  OS      : {platform.system()} {platform.release()}")
    print()

    step_venv()
    step_deps()
    if startup:
        step_startup()

    py = _venv_python()
    print()
    print("=" * 50)
    print("  🎉  Setup complete!")
    print("=" * 50)
    print()
    print("  Start server:  python main.py")
    print("  Or directly:   {} main.py".format(py))
    if startup:
        print("  Auto-start:    ✅ enabled (runs at boot)")
    else:
        print("  Auto-start:    ❌ not set (use --startup to enable)")
    print()


# ── Uninstall ────────────────────────────────────────────────────────────────

def do_uninstall(clean_all: bool):
    print()
    print("╔══════════════════════════════════════╗")
    print("║       infoServer Uninstall            ║")
    print("╚══════════════════════════════════════╝")
    print()

    # 1. Remove startup service
    startup_py = PROJECT / "startup.py"
    if startup_py.exists() and VENV_DIR.exists():
        print("🔌  Removing startup service...")
        try:
            _run([_venv_python(), str(startup_py), "uninstall"])
        except subprocess.CalledProcessError:
            print("  ⚠️  startup uninstall failed (may not be registered)")

    # 2. Clean pycache (skip .venv)
    print()
    print("🧹  Cleaning caches...")
    for p in PROJECT.rglob("__pycache__"):
        if ".venv" not in p.parts:
            _safe_rm(p)

    # 3. Remove venv
    print()
    print("🧹  Removing venv...")
    _safe_rm(VENV_DIR)

    # 4. Optionally remove data/logs/uploads
    if clean_all:
        print()
        print("🧹  Removing data, logs, uploads...")
        for name in _CLEAN_ALL_DIRS:
            _safe_rm(PROJECT / name)

    print()
    print("=" * 50)
    print("  ✅  Uninstall complete")
    print("=" * 50)
    if not clean_all:
        print("  ℹ️  Data/logs/uploads preserved (use --all to remove)")
    print()


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    args = sys.argv[1:]
    uninstall = "uninstall" in args
    clean_all = "--all" in args
    startup = "--startup" in args

    try:
        if uninstall:
            do_uninstall(clean_all)
        else:
            do_setup(startup)
    except subprocess.CalledProcessError as e:
        print(f"\n❌  Failed (exit {e.returncode})")
        sys.exit(e.returncode)
    except KeyboardInterrupt:
        print("\n⚠️  Cancelled")
        sys.exit(130)


if __name__ == "__main__":
    main()
