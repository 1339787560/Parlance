#!/usr/bin/env python3
"""infoServer deploy 打包 + 推送工具 (发布/更新唯一通道: 打包直推, 以推送端内容为准)。

打包: 白名单收集本机验证过的运行产物 (py + 运行位 exe + 模板/静态资源) +
      manifest.json (built_at / git_rev / files) → deploys/deploy_<ts>.zip
推送: --push <base_url> 时 upload (**raw zip body**) + activate (发布面异步编排:
      解包校验 → exe 交宿主管道换代 / 非 exe 备份+就地替换 → 失败回滚 →
      按"包动了哪一层"收尾重启) + 轮询 deploy.log 到编排结束。

发布面 = **:5099** (2026-09-22 起由 L2 `run.py` 承接; 原 legacy Flask 让位 5098)。
**勿指向 :5000** —— 换 exe 时它自己就是被停目标, 停机窗口必断。

用法:
    python make_deploy_pack.py                    # 只打包
    python make_deploy_pack.py --push http://127.0.0.1:5099      # 打包+推本机
    python make_deploy_pack.py --push http://192.168.102.53:5099 # 打包+推 53

设计约束:
  - config.yaml 与 serviceGroup 下 config*.json/yaml 不打包 (现场配置分叉保护,
    53 与本机值不同; manifest.skipped_configs 记录未含配置供人工核对)。
  - exe 从 config.yaml 各服务 command/args 解析运行位路径收集 (不扫 target
    目录, 避免中间物进包; statistic 运行位在 target/release 也能被显式路径命中)。
"""

import argparse
import datetime
import json
import os
import subprocess
import sys
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent

# serviceGroup 递归收集的扩展名白名单 (纯代码/资源资产)
INCLUDE_EXT = {".py", ".html", ".js", ".css", ".json", ".yaml", ".yml",
               ".png", ".jpg", ".svg", ".woff", ".woff2", ".ttf", ".ico", ".txt"}
# 助手 exe（非服务二进制，目标机走「就地替换 + 备份」，不经宿主 swap_exe）。
# 为什么必须显式登记：目录扫描按 INCLUDE_EXT 过滤且**不含 .exe**，而下面的服务 exe 只从
# config.yaml 的 command 收集 —— 助手 exe 不登记就会**静默漏打包**（同 2026-09-09「exe 恒漏」）。
HELPER_EXES = {"serviceGroup/serviceServer-legacy/assetTool.exe"}
# 目录黑名单 (target 例外: 显式 exe 路径单独收集, 不走目录扫描)
EXCLUDE_DIRS = {".svn", ".git", "__pycache__", ".venv", "venv", "node_modules",
                "logs", "target", "deploys", "_staging", ".deploy_backup",
                ".codegraph", ".claude", ".cursor", "tests", "docs"}
# 不打包的现场配置 (相对根; serviceGroup 下的 config*.json 同理在收集时按名排除)
ROOT_SKIP_FILES = {"config.yaml", "config.full.yaml"}
CONFIG_NAME_PREFIXES = ("config",)


def _is_config_name(p: Path) -> bool:
    return p.name.startswith(CONFIG_NAME_PREFIXES) and p.suffix in (".json", ".yaml", ".yml")


def _git_rev() -> str:
    try:
        r = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                           capture_output=True, text=True, timeout=10, cwd=ROOT)
        if r.returncode == 0:
            return r.stdout.strip()
    except Exception:
        pass
    return "unknown"


# 受保护服务 (host 侧 _DEPLOY_PROTECTED 同款): 本机 AI API 网关, 误停 = 断 AI 会话。
# 打包默认排除其文件; 要更新它需 --only statistic-server 显式指定 (53 侧同理人工评估)。
PROTECTED_SERVICES = {"statistic-server"}


def _plat_service_specs() -> list[dict]:
    """config.yaml 服务声明 → [{name, command, args, cwd}] (平台键解析对齐 service_manager)。"""
    try:
        import yaml
    except ModuleNotFoundError:
        # 2026-09-21 实测坑: 系统 py3.14 没装 PyYAML → 打包第一步就 ModuleNotFoundError,
        # 现场表现像「打包工具坏了」而不是「解释器选错了」。明确指路:
        raise SystemExit(
            "缺少 PyYAML —— 本工具需用 infoServer 自带 venv 运行:\n"
            "  .venv\\Scripts\\python.exe make_deploy_pack.py ...     (Windows)\n"
            "  ./.venv/bin/python make_deploy_pack.py ...            (macOS)\n"
            "或用 serviceGroup/serviceServer/deploy.bat 一键 build + 打包 + 推送。"
        )
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8")) or {}
    plat = "win" if sys.platform.startswith("win") else ("mac" if sys.platform == "darwin" else None)
    specs = []
    for svc in cfg.get("services", []):
        if plat:
            command = svc.get(f"command_{plat}") or svc.get("command")
            args_v = svc.get(f"args_{plat}")
            if args_v is None:  # 空列表 [] 也是合法值
                args_v = svc.get("args", [])
            cwd_v = svc.get(f"cwd_{plat}") or svc.get("cwd")
        else:
            command = svc.get("command")
            args_v = svc.get("args", [])
            cwd_v = svc.get("cwd")
        if command and not os.path.isabs(command) and ("/" in command or "\\" in command):
            command = os.path.abspath(command)  # 相对项目根 (与 service_manager 一致)
        specs.append({"name": svc.get("name", "unnamed"), "command": command or "",
                      "args": list(args_v or []), "cwd": cwd_v})
    return specs


def _service_owners() -> dict[str, dict]:
    """{svc_name: {"prefix": "serviceGroup/<dir>/", "runs": [运行文件 rel...]}}。

    prefix = cwd 相对根 posix (服务资产域: 模板/静态/js 等归此前缀);
    runs = command/args 对应的文件 (py/exe)。ROOT 外 (np-reader/caddy) 跳过。
    """
    owners = {}
    for spec in _plat_service_specs():
        runs, prefix = [], None
        for entry in [spec["command"]] + spec["args"]:
            entry = (entry or "").strip().strip('"')
            if not entry:
                continue
            # command 常为相对 ROOT 全路径 (./serviceGroup/serviceServer/service-server.exe),
            # args 常为相对 cwd 裸名 (main.py)。直接 Path(cwd)/entry 会把 ROOT 相对全路径
            # 重复拼 cwd 目录 → is_file False → exe 漏收集 (2026-09-09 deploy 事故)。
            if os.path.isabs(entry):
                full = Path(entry)
            else:
                cand = ROOT / entry.lstrip("./\\")
                full = cand.resolve() if cand.is_file() else Path(spec["cwd"] or ROOT) / entry
            try:
                rel = full.resolve().relative_to(ROOT).as_posix()
            except ValueError:
                continue
            if full.is_file():
                runs.append(rel)
        if spec["cwd"]:
            try:
                c = Path(spec["cwd"])
                c = c if c.is_absolute() else ROOT / c
                prefix = c.resolve().relative_to(ROOT).as_posix() + "/"
            except ValueError:
                pass
        if runs or prefix:
            owners[spec["name"]] = {"prefix": prefix, "runs": runs}
    return owners


def _owner_of(rel: str, owners: dict[str, dict]) -> str:
    """文件归属: 命中服务运行文件 → 该服务; 否则落在服务资产前缀下 → 该服务; 否则 shared。"""
    for name, o in owners.items():
        if rel in o["runs"]:
            return name
    for name, o in owners.items():
        if o["prefix"] and rel.startswith(o["prefix"]):
            return name
    return "shared"


def collect_files(only: list[str] | None = None) -> tuple[list[str], list[str]]:
    """返 (files, skipped_configs): 相对根 posix 路径。

    only = 服务名列表 (含 'host' 控根级 launcher py): 只打包选中服务的文件;
    None = 全量 (但剔除 PROTECTED_SERVICES 的文件)。
    """
    owners = _service_owners()
    files, skipped = [], []
    exclude_owners = set()
    if only is not None:
        keep = set(only)
        unknown = keep - set(owners) - {"host", "shared"}
        if unknown:
            raise SystemExit(f"未知服务名: {sorted(unknown)}; 可选: {sorted(owners) + ['host', 'shared']}")
    else:
        keep = None  # 全量
        exclude_owners = PROTECTED_SERVICES

    def _want(owner: str) -> bool:
        if keep is not None:
            return owner in keep
        return owner not in exclude_owners

    for p in sorted(ROOT.glob("*.py")):
        if _want("host"):
            files.append(p.relative_to(ROOT).as_posix())

    # owners.values() 是 {prefix, runs} dict, 须取 ["runs"] — 遍历 dict 本身只会得键
    # "prefix"/"runs", exe 恒漏 (2026-09-09: 工具首次真正带上 exe)
    for spec in owners.values():
        for rel in spec["runs"]:
            if rel.endswith(".exe") and _want(_owner_of(rel, owners)) and rel not in files:
                files.append(rel)

    # 助手 exe（见 HELPER_EXES 注释）：显式收集，缺失即静默跳过（本机还没 build 时不报错）。
    for rel in sorted(HELPER_EXES):
        if (ROOT / rel).is_file() and _want(_owner_of(rel, owners)) and rel not in files:
            files.append(rel)

    sg = ROOT / "serviceGroup"
    for dirpath, dirnames, filenames in os.walk(sg):
        dirnames[:] = [d for d in dirnames
                       if d not in EXCLUDE_DIRS and not d.startswith("_staging")]
        for fn in sorted(filenames):
            p = Path(dirpath) / fn
            rel = p.relative_to(ROOT).as_posix()
            if p.suffix.lower() not in INCLUDE_EXT:
                continue
            if _is_config_name(p):
                skipped.append(rel)
                continue
            if _want(_owner_of(rel, owners)) and rel not in files:
                files.append(rel)

    for name in ROOT_SKIP_FILES:
        if (ROOT / name).is_file():
            skipped.append(name)
    return sorted(files), sorted(skipped)


def _exe_source(rel: str) -> Path:
    """exe 打包源: 同项目 cargo 产物 target/release/<basename> 比运行位新时优先用它。

    为什么 (2026-09-21 实测): 运行位 exe 被运行中进程锁着 (Windows image section),
    本机 `build.bat` 的 `copy /Y` 落位必然失败 → 运行位长期停留在旧 build, 打包也就
    永远带旧 exe。而 deploy 的换代本来就由**目标机宿主持句柄**完成 (stop → cp → start),
    所以包里直接带新构建产物才是正解: 本机不需要先把新 exe 落到运行位。
    """
    dst = ROOT / rel
    cand = dst.parent / "target" / "release" / dst.name
    if not cand.is_file():
        return dst
    try:
        if not dst.is_file() or cand.stat().st_mtime > dst.stat().st_mtime:
            return cand
    except OSError:
        return cand
    return dst


def build_zip(files: list[str], skipped: list[str]) -> Path:
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    manifest = {
        "built_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "git_rev": _git_rev(),
        "platform": sys.platform,
        "files": files,
        "skipped_configs": skipped,
    }
    deploy_dir = ROOT / "deploys"
    deploy_dir.mkdir(exist_ok=True)
    zip_path = deploy_dir / f"deploy_{ts}.zip"
    # 记录被替换的 exe 源 (运行位 → 构建产物), 供推送后核对与排查。
    exe_src: dict[str, str] = {}
    for rel in files:
        if not rel.lower().endswith(".exe"):
            continue
        src = _exe_source(rel)
        if src != ROOT / rel:
            exe_src[rel] = src.relative_to(ROOT).as_posix()
    if exe_src:
        manifest["exe_src"] = exe_src
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=1))
        for rel in files:
            src = _exe_source(rel) if rel.lower().endswith(".exe") else ROOT / rel
            zf.write(src, rel)
    return zip_path


def push(zip_path: Path, base: str, timeout: int = 180, token: str = "") -> int:
    import requests
    base = base.rstrip("/")
    headers = {"X-Deploy-Token": token} if token else {}
    if not token:
        token = os.environ.get("DEPLOY_TOKEN", "").strip()
        if token:
            headers = {"X-Deploy-Token": token}
    # 直连发布面 (:5099)。2026-09-22 起 :5099 由 **L2 (run.py)** 承接 (原 legacy Flask
    # 让位 5098) —— 换 exe 时前端 (:5000) 本身就是被停目标, 走前端轮询在停机窗口必然断。
    # upload 契约 = **raw zip body** (不再 multipart): 文件名走 X-Deploy-Filename ——
    # 省掉收端 multipart 解析层 (cgi 在 Python 3.13 已移除, 不该押在它上面)。
    with open(zip_path, "rb") as f:
        up_headers = dict(headers)
        up_headers["Content-Type"] = "application/zip"
        up_headers["X-Deploy-Filename"] = zip_path.name
        r = requests.post(f"{base}/api/deploy/upload",
                          data=f, headers=up_headers, timeout=300)
    print(f"[upload] {r.status_code}: {r.text[:300]}")
    if r.status_code != 200 or not r.json().get("success"):
        return 1
    # 记录 activate 前的旧编排 timestamp: 轮询只认更新的 record
    # (编排 sleep 1.5s 才动笔, 旧 done record 会先被读到导致提前退出)
    try:
        old_ts = (requests.get(f"{base}/api/deploy/log", headers=headers, timeout=15)
                  .json().get("last") or {}).get("timestamp", "")
    except Exception:
        old_ts = ""
    r = requests.post(f"{base}/api/deploy/activate",
                      json={"zip": zip_path.name}, headers=headers, timeout=30)
    print(f"[activate] {r.status_code}: {r.text[:300]}")
    if r.status_code != 200 or not r.json().get("success"):
        return 1
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            log = requests.get(f"{base}/api/deploy/log", headers=headers, timeout=15).json()
            last = log.get("last") or {}
            stage = last.get("stage")
            fresh = last.get("timestamp", "") > old_ts if old_ts else True
            print(f"[deploy] running={log.get('running')} stage={stage} "
                  f"ok={last.get('ok')}" + ("" if fresh else " (旧record, 等新编排)"))
            if fresh and stage in ("done", "rolled_back", "error", "aborted_dirty",
                                   "aborted_locked", "aborted_stop_failed"):
                print(json.dumps(last, ensure_ascii=False, indent=1)[:2000])
                return 0 if last.get("ok") else 2
        except Exception as e:
            print(f"[deploy] poll error (编排停服期属正常): {e}")
        time.sleep(5)
    print("[deploy] 轮询超时, 手动查 /api/deploy/log")
    return 3


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", metavar="SVCS",
                    help="只打包指定服务 (逗号分隔; host=根级 launcher py; 缺省=全量但排除受保护服务)")
    ap.add_argument("--push", metavar="BASE_URL",
                    help="打包后推送到该基址。**指向发布面 :5099** "
                         "(本机 http://127.0.0.1:5099; 堡垒机 http://192.168.102.53:5099) —— "
                         "该面自 2026-09-22 起由 L2 (run.py) 承接; 走 :5000 前端在换 exe 时会自断")
    ap.add_argument("--token", metavar="TOK",
                    help="部署口令 (缺省取 env DEPLOY_TOKEN); 目标机回环可免, 远端必填")
    args = ap.parse_args()

    only = [s.strip() for s in args.only.split(",") if s.strip()] if args.only else None
    files, skipped = collect_files(only)
    zip_path = build_zip(files, skipped)
    scope = f"only={','.join(only)}" if only else f"全量(排除受保护: {sorted(PROTECTED_SERVICES)})"
    print(f"[pack] {zip_path} ({zip_path.stat().st_size} bytes, {len(files)} files, {scope})")
    if skipped:
        print(f"[pack] 未含现场配置 {len(skipped)} 项: {skipped[:8]}{'...' if len(skipped) > 8 else ''}")
    if not args.push:
        return 0
    rc = push(zip_path, args.push, token=args.token or "")
    return rc


if __name__ == "__main__":
    sys.exit(main())
