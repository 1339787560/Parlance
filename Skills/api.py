#!/usr/bin/env python3
"""
VersionManage API CLI — UTF-8 safe, auto revision management.

Usage:
  python api.py snapshot                          # GET /api/snapshot
  python api.py rev                               # print current revision
  python api.py version create <name> [options]   # POST /api/versions
  python api.py version update <id> [options]     # PUT /api/versions/:id
  python api.py version delete <id>               # DELETE /api/versions/:id
  python api.py task create <name> [options]      # POST /api/tasks
  python api.py task update <id> [options]        # PUT /api/tasks/:id
  python api.py task delete <id>                  # DELETE /api/tasks/:id
  python api.py tasks [version-id]                # list tasks (filter by versionId)

Options:
  --status, -s TEXT        任务状态 (未开始/进行中/已完成/已暂停)
  --assignee, -a TEXT      负责人
  --hours, -H FLOAT        estimatedHours
  --version, -v TEXT       versionId (task 必填)
  --parent, -p TEXT        parentId (子任务)
  --priority, -P TEXT      优先级 (P0/P1/P2/P3, 默认 P2)
  --start-date, -d TEXT    startDate (YYYY-MM-DD)
  --project, --proj TEXT   项目标签
  --base-rev, -r INT       baseRevision (不传则自动获取)

Env: API_URL=http://127.0.0.1:8787/api
"""

import json
import os
import sys
import urllib.error
import urllib.request

# Force stdout to UTF-8 on Windows
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

API_URL = os.environ.get("API_URL", "http://127.0.0.1:8787/api")


# ── HTTP helpers ──────────────────────────────────────────────

def _api(method, path, data=None):
    url = API_URL + path
    body = json.dumps(data, ensure_ascii=False).encode("utf-8") if data is not None else None
    req = urllib.request.Request(url, data=body, method=method)
    req.add_header("Content-Type", "application/json; charset=utf-8")
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")
        return {"_error": e.code, "_message": err_body}


def get_snapshot():
    return _api("GET", "/snapshot")


def current_revision():
    return get_snapshot()["revision"]


def write(method, path, payload):
    """Write with auto revision management. Retries once on 409."""
    if "baseRevision" not in payload:
        payload["baseRevision"] = current_revision()
    result = _api(method, path, payload)
    if result.get("_error") == 409:
        # retry with fresh revision
        fresh = get_snapshot()
        payload["baseRevision"] = fresh["revision"]
        result = _api(method, path, payload)
    return result


# ── CLI ───────────────────────────────────────────────────────

def cmd_snapshot(args=None):
    data = get_snapshot()
    print(json.dumps(data, ensure_ascii=False, indent=2))


def cmd_rev(args=None):
    print(current_revision())


def cmd_version_create(args):
    name = args[0]
    data = {
        "name": name,
        "status": _opt(args, "--status", "-s", "未开始"),
        "startDate": _opt(args, "--start-date", "-d", ""),
    }
    r = write("POST", "/versions", data)
    _print_result(r)


def cmd_version_update(args):
    vid = args[0]
    data = {}
    for k, flag in [("name", "--name"), ("status", "--status"), ("startDate", "--start-date"),
                    ("endDate", "--end-date")]:
        v = _opt(args, flag)
        if v:
            data[k] = v
    if not data:
        print("{}")
        return
    data["baseRevision"] = current_revision()
    r = write("PUT", f"/versions/{vid}", data)
    _print_result(r)


def cmd_version_delete(args):
    vid = args[0]
    r = write("DELETE", f"/versions/{vid}", {})
    _print_result(r)


def cmd_task_create(args):
    name = args[0]
    data = {
        "name": name,
        "versionId": _req_opt(args, "--version", "-v"),
        "status": _opt(args, "--status", "-s", "未开始"),
        "priority": _opt(args, "--priority", "-P", "P2"),
        "estimatedHours": float(_opt(args, "--hours", "-H", "0")),
        "assignee": _opt(args, "--assignee", "-a", ""),
        "project": _opt(args, "--project", "--proj", ""),
    }
    parent = _opt(args, "--parent", "-p")
    if parent:
        data["parentId"] = parent
    start_date = _opt(args, "--start-date", "-d")
    if start_date:
        data["startDate"] = start_date
    r = write("POST", "/tasks", data)
    _print_result(r)


def cmd_task_update(args):
    tid = args[0]
    pairs = [
        ("name", "--name"),
        ("status", "--status"),
        ("assignee", "--assignee", "-a"),
        ("project", "--project"),
        ("priority", "--priority"),
        ("startDate", "--start-date", "-d"),
    ]
    data = {}
    for fields in pairs:
        val = _opt(args, *fields[1:])
        if val:
            data[fields[0]] = val
    hours = _opt(args, "--hours", "-H")
    if hours:
        data["estimatedHours"] = float(hours)
    if not data:
        print("{}")
        return
    r = write("PUT", f"/tasks/{tid}", data)
    _print_result(r)


def cmd_task_delete(args):
    tid = args[0]
    r = write("DELETE", f"/tasks/{tid}", {})
    _print_result(r)


def cmd_tasks(args=None):
    snap = get_snapshot()
    tasks = snap["tasks"]
    ver_filter = args[0] if args else None
    if ver_filter:
        tasks = [t for t in tasks if t.get("versionId") == ver_filter]
    print(json.dumps(tasks, ensure_ascii=False, indent=2))


# ── helpers ───────────────────────────────────────────────────

def _opt(args, *flags):
    for i, a in enumerate(args):
        if a in flags and i + 1 < len(args):
            return args[i + 1]
    return None


def _req_opt(args, *flags):
    val = _opt(args, *flags)
    if val is None:
        print(f"Error: {'/'.join(flags)} is required", file=sys.stderr)
        sys.exit(1)
    return val


def _print_result(r):
    if r.get("_error"):
        print(f"Error {r['_error']}: {r['_message']}", file=sys.stderr)
        sys.exit(1)
    print(json.dumps(r, ensure_ascii=False))


# ── dispatch ──────────────────────────────────────────────────

COMMANDS = {
    "snapshot": cmd_snapshot,
    "rev": cmd_rev,
    "tasks": cmd_tasks,
    "version": {
        "create": cmd_version_create,
        "update": cmd_version_update,
        "delete": cmd_version_delete,
    },
    "task": {
        "create": cmd_task_create,
        "update": cmd_task_update,
        "delete": cmd_task_delete,
    },
}


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__, file=sys.stderr)
        sys.exit(1)

    cmd = COMMANDS
    depth = 0
    while isinstance(cmd, dict) and depth < 3 and args:
        key = args.pop(0)
        if key in cmd:
            cmd = cmd[key]
            depth += 1
        else:
            print(f"Unknown command: {key}", file=sys.stderr)
            sys.exit(1)

    if isinstance(cmd, dict):
        print(f"Subcommand required. Available: {list(cmd.keys())}", file=sys.stderr)
        sys.exit(1)

    cmd(args)


if __name__ == "__main__":
    main()
