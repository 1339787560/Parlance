#!/usr/bin/env python3
"""Cross-platform startup manager for infoServer.

Usage:
    python startup.py install    # Register auto-start at boot
    python startup.py uninstall  # Remove auto-start
    python startup.py status     # Check current auto-start status

Windows: uses Task Scheduler (runs at boot, no login required)
macOS:   uses launchd (LaunchAgents, runs at login)
"""

import os
import sys
import platform
import subprocess
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
SERVICE_LABEL = "com.codlib.infoserer"
TASK_NAME = "InfoServer"

# ── Helpers ──────────────────────────────────────────────────────────────────

def _venv_python() -> str:
    """Return the Python executable inside .venv."""
    if platform.system() == "Windows":
        p = PROJECT_DIR / ".venv" / "Scripts" / "python.exe"
    else:
        p = PROJECT_DIR / ".venv" / "bin" / "python"
    return str(p) if p.exists() else sys.executable


def _uvicorn_cmd() -> list[str]:
    """Build the uvicorn launch command."""
    py = _venv_python()
    return [py, "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]


# ── macOS (launchd) ─────────────────────────────────────────────────────────

def _plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{SERVICE_LABEL}.plist"


def _plist_xml() -> str:
    cmd = _uvicorn_cmd()
    stdout_log = PROJECT_DIR / "logs" / "stdout.log"
    stderr_log = PROJECT_DIR / "logs" / "stderr.log"
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{SERVICE_LABEL}</string>

    <key>ProgramArguments</key>
    <array>
{chr(10).join(f'        <string>{c}</string>' for c in cmd)}
    </array>

    <key>WorkingDirectory</key>
    <string>{PROJECT_DIR}</string>

    <key>EnvironmentVariables</key>
    <dict>
        <key>PYTHONUNBUFFERED</key>
        <string>1</string>
    </dict>

    <key>RunAtLoad</key>
    <true/>

    <key>KeepAlive</key>
    <dict>
        <key>SuccessfulExit</key>
        <false/>
    </dict>

    <key>StandardOutPath</key>
    <string>{stdout_log}</string>

    <key>StandardErrorPath</key>
    <string>{stderr_log}</string>

    <key>ThrottleInterval</key>
    <integer>10</integer>
</dict>
</plist>
"""


def _mac_install():
    plist = _plist_path()
    (PROJECT_DIR / "logs").mkdir(exist_ok=True)
    plist.parent.mkdir(parents=True, exist_ok=True)
    plist.write_text(_plist_xml())
    subprocess.run(["launchctl", "unload", str(plist)], capture_output=True)
    subprocess.run(["launchctl", "load", str(plist)], check=True)
    print(f"✅  launchd service loaded: {plist}")
    print(f"    Logs: {PROJECT_DIR / 'logs' / 'stdout.log'}")


def _mac_uninstall():
    plist = _plist_path()
    if not plist.exists():
        print("⚠️  Not installed (plist not found)")
        return
    subprocess.run(["launchctl", "unload", str(plist)], capture_output=True)
    plist.unlink()
    print(f"✅  Removed: {plist}")


def _mac_status():
    plist = _plist_path()
    if not plist.exists():
        print("❌  Not installed")
        return
    result = subprocess.run(
        ["launchctl", "list", SERVICE_LABEL],
        capture_output=True, text=True,
    )
    if result.returncode == 0:
        print("✅  Loaded")
        for line in result.stdout.strip().splitlines():
            print(f"    {line}")
    else:
        print("⚠️  Plist exists but service not loaded")


# ── Windows (Task Scheduler) ────────────────────────────────────────────────

def _task_xml() -> str:
    cmd = " ".join(f'"{c}"' for c in _uvicorn_cmd())
    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>infoServer - LAN InfoShare service</Description>
  </RegistrationInfo>
  <Triggers>
    <BootTrigger>
      <Enabled>true</Enabled>
    </BootTrigger>
  </Triggers>
  <Principals>
    <Principal>
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <Priority>7</Priority>
    <RestartOnFailure>
      <Interval>PT1M</Interval>
      <Count>3</Count>
    </RestartOnFailure>
  </Settings>
  <Actions>
    <Exec>
      <Command>{_uvicorn_cmd()[0]}</Command>
      <Arguments>{" ".join(_uvicorn_cmd()[1:])}</Arguments>
      <WorkingDirectory>{PROJECT_DIR}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"""


def _win_install():
    xml_path = PROJECT_DIR / "_task.xml"
    (PROJECT_DIR / "logs").mkdir(exist_ok=True)
    xml_path.write_text(_task_xml(), encoding="utf-16")
    subprocess.run(
        ["schtasks", "/Create", "/TN", TASK_NAME, "/XML", str(xml_path), "/F"],
        check=True,
    )
    xml_path.unlink()
    subprocess.run(["schtasks", "/Run", "/TN", TASK_NAME], check=True)
    print(f"✅  Task Scheduler job created: {TASK_NAME}")


def _win_uninstall():
    result = subprocess.run(
        ["schtasks", "/Delete", "/TN", TASK_NAME, "/F"],
        capture_output=True, text=True,
    )
    if result.returncode == 0:
        print(f"✅  Removed task: {TASK_NAME}")
    else:
        print(f"⚠️  {result.stderr.strip()}")


def _win_status():
    result = subprocess.run(
        ["schtasks", "/Query", "/TN", TASK_NAME, "/FO", "LIST", "/V"],
        capture_output=True, text=True,
    )
    if result.returncode == 0:
        print("✅  Task exists")
        for line in result.stdout.strip().splitlines():
            print(f"    {line}")
    else:
        print("❌  Task not found")


# ── Dispatch ─────────────────────────────────────────────────────────────────

_HANDLERS = {
    "Darwin":  (_mac_install,   _mac_uninstall,   _mac_status),
    "Windows": (_win_install,   _win_uninstall,   _win_status),
}


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in ("install", "uninstall", "status"):
        print(__doc__.strip())
        sys.exit(1)

    action = sys.argv[1]
    os_name = platform.system()
    handlers = _HANDLERS.get(os_name)
    if not handlers:
        print(f"❌  Unsupported OS: {os_name}")
        sys.exit(1)

    idx = {"install": 0, "uninstall": 1, "status": 2}[action]
    handlers[idx]()


if __name__ == "__main__":
    main()
