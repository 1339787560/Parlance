from flask import render_template, render_template_string, request, jsonify, send_file
from flask_cors import CORS # 导入 CORS
import subprocess
# 修改导入方式，避免使用import *
import sys
import time
import Service
import JsonConfigParser
import json
from multiprocessing.connection import Client
from . import app
from . import TemplateDB # 导入 TemplateDB

from datetime import datetime, timedelta # 导入 datetime

from CommonTools.xzmpDB.TQVIP import TQVIPManager, TQMonthCardManager, timeUtil # 导入 TQVIPManager, TQMonthCardManager, timeUtil
import CommonTools.xzmpDB.tqvip_pb2 as tqvip_pb2 # 导入 tqvip_pb2
from CommonTools.xzmpDB.LuaDataManager import CostumeManager, TQNewPlayerGiftManager, _getdatenum # Lua 版本数据管理

CORS(app) # 初始化 CORS，允许所有来源

# ===== 宿主管道客户端 (_call_svc): deploy 编排经此调 host 原语 stop/start/swap_exe =====
# 2026-09-22 (U5) svn 编排退役后, 本段只服务 deploy 产物包直推 —— 铁律见下方 deploy 段:
# exe 的停/起一律经宿主管道 (谁 Popen 谁持有句柄), 句柄始终留宿主。
SVC_CTL_PIPE_WIN = r"\\.\pipe\infoserver_svc"
SVC_CTL_SOCKET_POSIX = "/tmp/infoserver_svc.sock"

def _svc_ctl_address():
    if os.name == "nt":
        return (SVC_CTL_PIPE_WIN, "AF_PIPE")
    return (SVC_CTL_SOCKET_POSIX, "AF_UNIX")

def _call_svc(method, params=None, timeout=15):
    """连 main.py ServiceControlServer socket 调 JSON-RPC method, 返 result 内容 (unwrap envelope)。"""
    addr, family = _svc_ctl_address()
    conn = Client(addr, family=family)
    try:
        conn.send({"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}})
        resp = conn.recv()
    finally:
        try:
            conn.close()
        except Exception:
            pass
    # unwrap JSON-RPC envelope: {id, jsonrpc, result} → result 内容
    if isinstance(resp, dict) and "jsonrpc" in resp and "result" in resp:
        return resp["result"]
    return resp


# ===== deploy 产物包直推 (legacy 侧编排, 2026-09-13 改造) =====
# 链路: make_deploy_pack.py 打 zip (py+exe+资源+manifest) → POST /api/deploy/upload
#   存 infoServer 根/deploys/ → POST /api/deploy/activate → **legacy 自己异步编排**
#   (非 exe 就地替换 / exe 交宿主管道换代 / 备份+失败回滚 / 收尾重启自己) →
#   GET /api/deploy/log 轮询。
#
# 为什么编排放 legacy 而不是 host:
#   ① legacy 是 Python, 运行中不锁自己的文件 → 唯一能自我更新的组件 (引导器);
#   ② 换 exe 时前端 (:5000) 正是被停目标, 走前端轮询在停机窗口必然断;
#   ③ 编排若住在 host 则改不动 (host 文件不在任何 deploy 包的管理范围内),
#      历史 7 条坑因此长期无人顺手修。
# 铁律: exe 的停/起一律经宿主管道 (_call_svc stop/start/swap_exe)。谁 Popen 谁
#   持有句柄 — 句柄一旦落在宿主之外, 服务就再也停不掉、exe 永远换不了
#   (2026-09-13 堡垒机 53 孤儿 exe 事故)。
#
# 鉴权: 回环免口令; 非回环必须带 X-Deploy-Token (值 = env DEPLOY_TOKEN 或
#   infoServer 根/deploy.token, 缺失则首次启动自动生成并打印到日志)。
import hashlib as _hashlib
import json as _json
import os as _os  # 本段位于文件首次 import os 之前, 显式导入
import secrets as _secrets
import shutil as _shutil
import threading as _threading
import time as _time
import zipfile as _zipfile

_LEGACY_ROOT = _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))))  # infoServer 根 (ServiceRoute 在 CustomRoute/ 下共 4 层)
DEPLOY_DIR = _os.path.join(_LEGACY_ROOT, 'deploys')
DEPLOY_LOG_PATH = _os.path.join(_LEGACY_ROOT, 'deploy.log')
DEPLOY_BACKUP_DIR = _os.path.join(_LEGACY_ROOT, '.deploy_backup')
LEGACY_PREFIX = 'serviceGroup/serviceServer-legacy/'
DEPLOY_TOKEN_ENV = 'DEPLOY_TOKEN'
DEPLOY_TOKEN_FILE = _os.path.join(_LEGACY_ROOT, 'deploy.token')
LEGACY_PORT = int(_os.environ.get('SERVICESVR_PORT', '5099'))

_deploy_lock = _threading.Lock()
_deploy_running = {'v': False}
_deploy_token_cache = {'v': None}


def _deploy_token():
    """部署口令: env DEPLOY_TOKEN 优先 → infoServer 根/deploy.token → 生成一份。"""
    if _deploy_token_cache['v']:
        return _deploy_token_cache['v']
    tok = _os.environ.get(DEPLOY_TOKEN_ENV, '').strip()
    if not tok:
        try:
            if _os.path.isfile(DEPLOY_TOKEN_FILE):
                with open(DEPLOY_TOKEN_FILE, 'r', encoding='utf-8') as f:
                    tok = f.read().strip()
            if not tok:
                tok = _secrets.token_hex(16)
                with open(DEPLOY_TOKEN_FILE, 'w', encoding='utf-8') as f:
                    f.write(tok)
                print(f"[deploy] 已生成部署口令 → {DEPLOY_TOKEN_FILE} (远端客户端用 X-Deploy-Token 头传递)")
        except OSError as e:
            print(f"[deploy] 口令文件读写失败, 非本机部署将被拒绝: {e}")
            return None
    _deploy_token_cache['v'] = tok
    return tok


def _deploy_authed():
    """写操作鉴权: 回环免口令, 其余必须带 X-Deploy-Token。"""
    if request.remote_addr in ('127.0.0.1', '::1', 'localhost'):
        return True
    tok = _deploy_token()
    if not tok:
        return False
    got = request.headers.get('X-Deploy-Token', '')
    return bool(got) and _secrets.compare_digest(str(got), tok)


def _deploy_denied():
    return jsonify({'success': False,
                    'message': '部署口令缺失或错误 (需要 X-Deploy-Token 头; '
                               '值见目标机 infoServer 根/deploy.token)'}), 401


def _host_diag():
    """目标机自述 (远端读不到它的文件系统/进程表, 由它自己报进 deploy record):

    - host_files: 根级宿主代码指纹 —— 比对"磁盘到底是不是新版"
    - python_procs: 所有 python 进程 (PID/启动时间/命令行) —— 看是否残留孤儿宿主
      (旧宿主若在 launcher 退出后存活, 会继续占着 infoserver_svc 管道应答,
       新宿主即使起来了也接管不了 → "重启了却没生效" 的典型成因)
    """
    d = {'host_files': {}, 'python_procs': None}
    for f in ('main.py', 'service_manager.py'):
        p = _os.path.join(_LEGACY_ROOT, f)
        try:
            with open(p, 'rb') as fh:
                d['host_files'][f] = {'sha1': _hashlib.sha1(fh.read()).hexdigest()[:12],
                                      'mtime': _time.strftime('%Y-%m-%d %H:%M:%S',
                                                              _time.localtime(_os.path.getmtime(p)))}
        except OSError as e:
            d['host_files'][f] = f'ERR {e}'
    try:
        r = subprocess.run(
            ['powershell', '-NoProfile', '-Command',
             "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
             "Select-Object ProcessId,CreationDate,CommandLine | ConvertTo-Json -Compress"],
            capture_output=True, text=True, timeout=25)
        raw = (r.stdout or '').strip()
        if raw:
            procs = _json.loads(raw)
            if isinstance(procs, dict):
                procs = [procs]
            d['python_procs'] = [{'pid': x.get('ProcessId'), 'created': x.get('CreationDate'),
                                  'cmd': (x.get('CommandLine') or '')[:160]} for x in procs]
    except Exception as e:
        d['python_procs'] = f'ERR {e.__class__.__name__}: {e}'
    return d


def _deploy_rec(record):
    with open(DEPLOY_LOG_PATH, 'w', encoding='utf-8') as f:
        _json.dump(record, f, ensure_ascii=False, indent=1)


def _host_services():
    """宿主托管服务清单 (name/port/exe_path/enabled/managed) — 权威源在 host。"""
    r = _call_svc('services')
    if isinstance(r, dict):
        return r.get('services') or []
    return []


def _rel_to_root(path):
    try:
        return _os.path.relpath(path, _LEGACY_ROOT).replace('\\', '/')
    except (ValueError, TypeError):
        return None


def _exe_from_command(command):
    """从宿主 to_dict 的 command 串抽运行位 exe (首 token 以 .exe 结尾时)。"""
    if not command:
        return None
    tok = str(command).strip().strip('"').split(' ')[0].strip('"')
    return tok if tok.lower().endswith('.exe') else None


def _deploy_run(zip_path, record):
    """编排主体 (后台线程内跑): 解压校验 → 非 exe 就地替换 → exe 交宿主换代 → 收尾。"""
    root = _LEGACY_ROOT
    staging = _os.path.join(DEPLOY_DIR, '_staging_' + _time.strftime('%Y%m%d%H%M%S'))
    try:
        with _zipfile.ZipFile(zip_path) as zf:
            zf.extractall(staging)
        man_path = _os.path.join(staging, 'manifest.json')
        if not _os.path.isfile(man_path):
            raise RuntimeError('manifest.json missing in zip')
        with open(man_path, 'r', encoding='utf-8') as f:
            manifest = _json.load(f)
        files = manifest.get('files') or []
        missing = [r for r in files if not _os.path.isfile(_os.path.join(staging, r.replace('/', _os.sep)))]
        if not files or missing:
            raise RuntimeError(f'manifest/files mismatch, missing: {missing[:5]}')
        record['manifest'] = {'built_at': manifest.get('built_at'),
                              'git_rev': manifest.get('git_rev'), 'files': len(files)}
        record['stage'] = 'unzipped'
        record['host_diag'] = _host_diag()   # 目标机自述: 宿主文件指纹 + python 进程表
        _deploy_rec(record)

        # 目标 exe: **凡包内 .exe 一律走宿主换代** (就地拷贝必撞运行中占用)。
        # 映射到宿主服务拿 port: exe_path 优先, 退回 command 首 token; 映射不到 → 显式失败。
        svc_by_rel = {}
        _host_svcs = _host_services()
        # 宿主版本探针: 新版 to_dict 带 exe_path, 旧版没有 (远端无法读宿主文件, 靠它判定)
        record['host_probe'] = {'services': len(_host_svcs),
                                'exe_path_present': any('exe_path' in s for s in _host_svcs)}
        for s in _host_svcs:
            rel = _rel_to_root(s.get('exe_path') or '') or _rel_to_root(_exe_from_command(s.get('command')))
            if rel:
                svc_by_rel[rel] = s
        exe_plan, exe_rels = [], set()
        for rel in sorted(r for r in files if r.lower().endswith('.exe')):
            s = svc_by_rel.get(rel)
            if not s or not s.get('port'):
                record.setdefault('unmapped_exe', []).append(rel)
                continue
            exe_rels.add(rel)
            exe_plan.append({'name': s.get('name'), 'port': s.get('port'), 'rel': rel,
                             'src': _os.path.join(staging, rel.replace('/', _os.sep))})
        record['exe_plan'] = [{'name': e['name'], 'port': e['port'], 'file': e['rel']} for e in exe_plan]
        # 映射不到服务的 .exe 绝不就地覆盖 (必撞运行中占用) → 显式失败, 触发回滚
        unmapped = [r for r in files if r.lower().endswith('.exe') and r not in exe_rels]
        plain = [r for r in files if r not in exe_rels and r not in set(unmapped)]

        # 1) 非 exe 文件: 备份 + 就地替换 (运行中的进程不锁 .py/.html, 无需停服)
        backup_dir = _os.path.join(DEPLOY_BACKUP_DIR, _time.strftime('%Y%m%d%H%M%S') + '_deploy')
        backed, replaced, failures = 0, [], []
        for rel in unmapped:
            failures.append({'file': rel,
                             'error': 'exe 未映射到宿主服务 (缺 exe_path/port), 拒绝就地覆盖'})
        for rel in plain:
            rel_os = rel.replace('/', _os.sep)
            dst = _os.path.join(root, rel_os)
            try:
                if _os.path.isfile(dst):
                    b = _os.path.join(backup_dir, rel_os)
                    _os.makedirs(_os.path.dirname(b), exist_ok=True)
                    _shutil.copy2(dst, b)
                    backed += 1
                _os.makedirs(_os.path.dirname(dst), exist_ok=True)
                _shutil.copy2(_os.path.join(staging, rel_os), dst)
                replaced.append(rel)
            except OSError as e:
                failures.append({'file': rel, 'error': f'{e.__class__.__name__}: {e}'})
                print(f"[deploy] 替换失败 {rel}: {e}")
        record['backup'] = {'dir': backup_dir, 'files': backed}
        record['replaced'] = len(replaced)
        record['stage'] = 'replaced'
        _deploy_rec(record)

        # 2) exe: 交宿主管道换代 (宿主持有句柄, 停/起都在宿主侧)
        exe_done = []
        for e in exe_plan:
            r = _swap_exe_via_host(e)
            item = {'file': e['rel'], 'name': e.get('name'), 'port': e.get('port'),
                    'how': r.get('how'), 'backup': r.get('backup'), 'error': r.get('error'),
                    'host_error': r.get('host_error'), 'attempts': r.get('attempts')}
            if r.get('ok'):
                exe_done.append(item)
            else:
                failures.append(item)
        record['exe_done'] = exe_done
        record['stage'] = 'exe_swapped'
        _deploy_rec(record)

        # 3) 有失败 → 恢复备份 (非 exe 拷回; exe 用宿主 swap 回备份) 并标记回滚
        if failures:
            restored = 0
            for rel in replaced:
                src = _os.path.join(backup_dir, rel.replace('/', _os.sep))
                try:
                    if _os.path.isfile(src):
                        _shutil.copy2(src, _os.path.join(root, rel.replace('/', _os.sep)))
                        restored += 1
                except OSError:
                    pass
            for d in exe_done:
                if d.get('backup'):
                    try:
                        _call_svc('swap_exe', {'port': d.get('port'), 'src': d.get('backup')})
                    except Exception:
                        pass
            record.update(ok=False, stage='rolled_back', error=f'{len(failures)} 项失败, 已回滚',
                          failures=failures[:20], restored=restored,
                          finished_at=_time.strftime('%Y-%m-%d %H:%M:%S'))
        else:
            record.update(ok=True, stage='done',
                          finished_at=_time.strftime('%Y-%m-%d %H:%M:%S'))

        # 4) 动过 legacy 自己的文件且整体成功 → 异步重启自己 (response 早已返回),
        #    让新代码生效。回滚场景不重启 (新代码已被备份覆盖回去)。
        if not failures and any(r.startswith(LEGACY_PREFIX) for r in replaced):
            record['self_restart'] = LEGACY_PORT
            _threading.Thread(target=_delayed_self_restart, daemon=True).start()
        _deploy_rec(record)
    except Exception as e:
        record.update(ok=False, stage='error', error=str(e),
                      finished_at=_time.strftime('%Y-%m-%d %H:%M:%S'))
        _deploy_rec(record)
    finally:
        _shutil.rmtree(staging, ignore_errors=True)
        with _deploy_lock:
            _deploy_running['v'] = False


def _swap_exe_via_host(e):
    """exe 换代: 优先宿主 swap_exe (句柄留宿主)。

    降级 (两条): ① 管道调用抛异常 (宿主没跑/管道断); ② 宿主返回错误 —— 典型是
    旧版宿主不认 src 参数 (只找 target/release), 即"宿主自己还没升到新版"的引导
    顺序死结。两种都退到本地路径: 自行按端口强杀 → 等可写 → 拷贝 → 请宿主 start
    (start 仍经宿主, 句柄最终回到宿主手里)。
    """
    host_err = None
    try:
        r = _call_svc('swap_exe', {'port': e['port'], 'src': e['src']}, timeout=90)
        if isinstance(r, dict) and r.get('ok'):
            return {'ok': True, 'name': e['name'], 'port': e['port'],
                    'how': 'host', 'backup': r.get('backup'), 'error': None}
        host_err = (r or {}).get('error') if isinstance(r, dict) else str(r)
        print(f"[deploy] 宿主 swap_exe 未成功 ({host_err}), 降级本地处理")
    except Exception as ex:
        host_err = f'{ex.__class__.__name__}: {ex}'
        print(f"[deploy] 宿主 swap_exe 调用失败, 降级本地处理: {host_err}")
    local = _swap_exe_local(e)
    # 降级即使成功也留住宿主的原话 — 否则"宿主旧版"与"宿主停不掉"两种情况分不开
    local['host_error'] = host_err
    return local


def _kill_listener(port):
    """按端口强杀监听进程 (只杀监听 PID, 不碰父进程; 仅统计 LISTENING 行)。"""
    if not port:
        return
    out = subprocess.run(['netstat', '-ano'], capture_output=True, text=True, timeout=10).stdout
    for line in out.splitlines():
        parts = line.split()
        if len(parts) < 5 or 'LISTENING' not in parts or parts[1].rsplit(':', 1)[-1] != str(port):
            continue
        subprocess.run(['taskkill', '/F', '/T', '/PID', parts[-1]], capture_output=True, timeout=10)
        print(f"[deploy] 强杀端口 {port} 监听进程 PID {parts[-1]}")


def _wait_writable(dst, timeout=15):
    deadline = _time.time() + timeout
    while _time.time() < deadline:
        try:
            with open(dst, 'r+b'):
                return True
        except OSError:
            _time.sleep(0.5)
    return False


def _port_listeners(port):
    """该端口所有 LISTENING 行 (诊断用)。"""
    if not port:
        return []
    try:
        out = subprocess.run(['netstat', '-ano'], capture_output=True, text=True, timeout=10).stdout
        return [l.strip() for l in out.splitlines()
                if 'LISTENING' in l and l.split()[1].rsplit(':', 1)[-1] == str(port)]
    except Exception:
        return []


def _procs_of(image):
    """同名进程清单 (诊断用): tasklist 摘要行。"""
    try:
        out = subprocess.run(['tasklist', '/FI', f'IMAGENAME eq {image}'],
                             capture_output=True, text=True, timeout=10).stdout
        return [l.strip() for l in out.splitlines() if image.lower() in l.lower()]
    except Exception:
        return []


def _diag(dst, port):
    """失败现场的旁证: 端口监听者 + 同名进程 + 此刻是否可写 (真机上看不到进程表, 靠它落地)。"""
    d = {'listeners': _port_listeners(port), 'procs': _procs_of(_os.path.basename(dst))}
    if not _os.path.exists(dst):
        d['writable_now'] = 'missing'
        return d
    try:
        with open(dst, 'r+b'):
            d['writable_now'] = True
    except OSError as e:
        d['writable_now'] = f'{e.__class__.__name__}: {e}'
    return d


def _swap_exe_local(e):
    """降级路径: **先请宿主停** (关键) → 按端口强杀 → 等可写 → 拷贝 → 请宿主启。

    "先请宿主停"不能省: 外部直接 taskkill 时宿主 monitor 会把服务自动拉起
    (它的 _stop_event 没被置位), 于是"刚杀完文件又被映射回去"——2026-09-13 在
    53 上实测踩到 (可写检查通过、紧接着 copy 报 WinError32)。走一次宿主管道
    stop 即置 _stop_event, 抑制 auto_restart; 旧版宿主 stop() 里 _stop_event.set()
    也在 `if not self._process: return` 之前, 所以宿主没有句柄时同样有效。
    拷贝做重试: 被重新映射时再来一轮 (杀 → 等 → 拷), 失败现场写进 diag。
    """
    name, port, rel, src = e['name'], e['port'], e['rel'], e['src']
    dst = _os.path.join(_LEGACY_ROOT, rel.replace('/', _os.sep))
    backup, last_err, attempts = None, None, 0
    try:
        if _os.path.isfile(dst):
            bdir = _os.path.join(DEPLOY_BACKUP_DIR, _time.strftime('%Y%m%d%H%M%S') + '_exe')
            _os.makedirs(bdir, exist_ok=True)
            backup = _os.path.join(bdir, _os.path.basename(dst))
            _shutil.copy2(dst, backup)
        if port:
            try:
                _call_svc('stop', {'port': port}, timeout=60)
            except Exception as ex:
                print(f"[deploy] 宿主管道 stop 失败 (继续自处理): {ex}")
        for i in range(4):
            attempts = i + 1
            _kill_listener(port)
            if not _wait_writable(dst, 10):
                last_err = f'等待可写超时 (第 {attempts} 轮)'
                print(f"[deploy] {last_err}")
                continue
            try:
                _shutil.copy2(src, dst)
                r = _call_svc('start', {'port': port}, timeout=60)
                return {'ok': bool(isinstance(r, dict) and r.get('ok')), 'name': name, 'port': port,
                        'how': 'local', 'backup': backup, 'attempts': attempts,
                        'error': None if isinstance(r, dict) and r.get('ok') else f'宿主 start 失败: {r}'}
            except OSError as ce:
                # 可写检查刚过、拷贝即失败 = 文件在这一瞬又被映射回去 (有人重新拉起进程)
                last_err = f'copy 失败 (第 {attempts} 轮): {ce.__class__.__name__}: {ce}'
                print(f"[deploy] {last_err}")
                _time.sleep(1)
        # 四轮都没成: 把服务交回宿主, 并留下现场旁证
        if port:
            try:
                _call_svc('start', {'port': port}, timeout=60)
            except Exception:
                pass
        return {'ok': False, 'name': name, 'port': port, 'how': 'local', 'backup': backup,
                'attempts': attempts, 'error': last_err, 'diag': _diag(dst, port)}
    except Exception as ex:
        return {'ok': False, 'name': name, 'port': port, 'how': 'local',
                'backup': backup, 'attempts': attempts,
                'error': f'{ex.__class__.__name__}: {ex}', 'diag': _diag(dst, port)}


def _delayed_self_restart():
    """等 response 发完, 再请宿主重启 legacy 自己 (Python 文件不锁, 换完只差重启生效)。"""
    _time.sleep(2)
    try:
        _call_svc('restart', {'port': LEGACY_PORT}, timeout=60)
    except Exception as e:
        print(f"[deploy] 自重启失败 (人工重启 legacy 生效): {e}")


@app.route('/api/deploy/upload', methods=['POST'])
def api_deploy_upload():
    """接收 deploy zip (multipart 字段 'file'), 存 deploys/<原名>。"""
    if not _deploy_authed():
        return _deploy_denied()
    try:
        f = request.files.get('file')
        if f is None:
            return jsonify({'success': False, 'message': "multipart 字段 'file' 缺失"}), 400
        name = _os.path.basename(f.filename or '')
        if not name or not name.lower().endswith('.zip'):
            return jsonify({'success': False, 'message': '文件名必须以 .zip 结尾'}), 400
        _os.makedirs(DEPLOY_DIR, exist_ok=True)
        path = _os.path.join(DEPLOY_DIR, name)
        f.save(path)
        return jsonify({'success': True, 'name': name, 'size': _os.path.getsize(path), 'saved': path})
    except Exception as e:
        return jsonify({'success': False, 'message': f'保存失败: {e}'}), 500


@app.route('/api/deploy/activate', methods=['POST'])
def api_deploy_activate():
    """触发 legacy 侧异步 deploy 编排。body {"zip": "<名>"} 缺省 = deploys/ 最新。"""
    if not _deploy_authed():
        return _deploy_denied()
    with _deploy_lock:
        if _deploy_running['v']:
            return jsonify({'success': False, 'message': '已有 deploy 在跑, 查 /api/deploy/log'}), 409
        data = request.get_json(silent=True) or {}
        name = data.get('zip')
        if name:
            if not name.endswith('.zip'):
                name += '.zip'
            zip_path = _os.path.join(DEPLOY_DIR, _os.path.basename(name))
            if not _os.path.isfile(zip_path):
                return jsonify({'success': False, 'message': f'找不到包: {zip_path}'}), 404
        else:
            if not _os.path.isdir(DEPLOY_DIR):
                return jsonify({'success': False, 'message': 'deploys/ 目录不存在'}), 404
            zips = [f for f in _os.listdir(DEPLOY_DIR) if f.endswith('.zip')]
            if not zips:
                return jsonify({'success': False, 'message': 'deploys/ 下没有 zip'}), 404
            zip_path = _os.path.join(DEPLOY_DIR, max(zips))
        record = {'timestamp': _time.strftime('%Y-%m-%d %H:%M:%S'),
                  'zip': _os.path.basename(zip_path), 'stage': 'start'}
        _deploy_rec(record)
        _deploy_running['v'] = True
        _threading.Thread(target=_deploy_run, args=(zip_path, record), name='legacy-deploy', daemon=True).start()
    return jsonify({'success': True,
                    'message': f"deploy triggered (legacy 编排): {_os.path.basename(zip_path)}"
                               f" | 进度查 /api/deploy/log",
                    'log': DEPLOY_LOG_PATH, 'zip': _os.path.basename(zip_path)})


@app.route('/api/deploy/log', methods=['GET'])
def api_deploy_log():
    """查 deploy 编排状态 + 最近一次日志 (legacy 自己读 deploy.log, 不经前端)。"""
    result = {'running': _deploy_running['v']}
    try:
        if _os.path.isfile(DEPLOY_LOG_PATH):
            with open(DEPLOY_LOG_PATH, 'r', encoding='utf-8') as f:
                result['last'] = _json.load(f)
        else:
            result['message'] = 'no deploy log yet'
    except Exception as e:
        result['error'] = f'read deploy log failed: {e}'
    return jsonify(result)


# ===== 工具自身重启 (service-server :5000 自陈列「重启自身」入口) =====
# 为什么落 legacy: :5000 正是被重启目标, 不能自己编排自己的死; legacy (Python, 不锁自身
# 文件) 与宿主同侧, 作为第三方替我发号。停/起一律经宿主管道 restart (stop_verified 端口
# 判据 → start, 句柄最终留在宿主), 严禁 legacy 自己 Popen (谁 Popen 谁持句柄铁律)。
TOOL_PORT = int(_os.environ.get('SERVICESVR_TOOL_PORT', '5000'))


def _self_restart_thread(port):
    """给 HTTP 响应留出返回时间后再动手 (否则调用方拿不到回包)。"""
    _time.sleep(1.5)
    try:
        r = _call_svc('restart', {'port': port}, timeout=90)
        print(f"[deploy] self-restart port={port} -> {r}")
    except Exception as e:
        print(f"[deploy] self-restart port={port} 失败: {e}")


@app.route('/api/deploy/self-restart', methods=['POST'])
def api_deploy_self_restart():
    """重启工具自身 (缺省 :5000)。异步: 立即返「已提交」, 实际重启在后台。"""
    if not _deploy_authed():
        return _deploy_denied()
    data = request.get_json(silent=True) or {}
    try:
        port = int(data.get('port') or TOOL_PORT)
    except (TypeError, ValueError):
        return jsonify({'success': False, 'message': 'port 非法'}), 400
    _threading.Thread(target=_self_restart_thread, args=(port,),
                      name='legacy-self-restart', daemon=True).start()
    return jsonify({'success': True,
                    'message': f'工具自身重启已提交 (端口 {port}), 约 5-10 秒后刷新页面'})

import subprocess
import os
import threading

# ===== Deposit 远程代理 (浏览器不可达 192.168.105.62:5003 时, 由 servicesvr 服务端转发) =====
# 与 servicesvr 的 /api/set-gold (走 RobotToolD.exe) 并列; 积分/银两原本由 deposit.html
# 浏览器直连远程 :5003, 跨网/防火墙场景下浏览器不可达 → servicesvr 同 LAN 可达, 代理之.
DEPOSIT_REMOTE_HOST = 'http://192.168.105.62:5003'
# servicesvr 本机 origin, 给 deposit 远程代理伪装 Referer/Origin 用 (绕 WAF)
SERVICESVR_ORIGIN = 'http://localhost:5000'

def _proxy_deposit_remote(endpoint, user_ids_str, count, gameid, opid, timeout=5):
    """服务端 POST form 转发到 deposit 远程 HTTP 服务. 返 (parsed_json_or_dict, http_status).
    HTTPError (远端返非 2xx) 单独处理: 服务可达, 返远端 status + body.
    URLError (网络不可达): 502 + reachable:false.
    """
    import urllib.request, urllib.parse, urllib.error
    url = f"{DEPOSIT_REMOTE_HOST}{endpoint}"
    payload = urllib.parse.urlencode({
        'userid': user_ids_str,
        'count': str(count),
        'gameid': str(gameid),
        'opid': str(opid),
    }).encode('utf-8')
    req = urllib.request.Request(url, data=payload, method='POST')
    req.add_header('Content-Type', 'application/x-www-form-urlencoded')
    # 伪装浏览器头绕 WAF/反爬层 (105.62 拦 Python-urllib → 返 500 HTML).
    # deposit.html 浏览器 fetch 能 200, urllib 默认 UA 被 500 → 加 UA + Origin + Referer 对齐.
    req.add_header('User-Agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                                 'AppleWebKit/537.36 (KHTML, like Gecko) '
                                 'Chrome/126.0.0.0 Safari/537.36')
    req.add_header('Accept', '*/*')
    req.add_header('Origin', SERVICESVR_ORIGIN)
    req.add_header('Referer', f'{SERVICESVR_ORIGIN}/deposit')
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode('utf-8', errors='replace')
            try:
                return json.loads(body), resp.status
            except Exception:
                return {'raw': body}, resp.status
    except urllib.error.HTTPError as e:
        # 远端返非 2xx (如 500): 服务可达, 只是业务错. 透传远端 status + body.
        body = e.read().decode('utf-8', errors='replace')
        try:
            parsed = json.loads(body)
        except Exception:
            parsed = {'raw': body}
        return {'error': f'HTTP {e.code}', 'reachable': True,
                'upstream_status': e.code, 'body': parsed, 'url': url}, e.code
    except urllib.error.URLError as e:
        return {'error': f'{e}', 'reachable': False, 'url': url}, 502
    except Exception as e:
        return {'error': str(e), 'url': url}, 500


def _validate_deposit_payload(data):
    """提取并校验 userIds/count/gameid/opid. 返 (user_id_list, count, gameid, opid, err_msg).

    返 user_id **列表** (非逗号串). 远端 105.62 /setscore|/SetSilver 仅支持单 userid,
    多账号逗号串会触发 500 (见 _proxy_deposit_multi). 上层按列表逐个调用.
    """
    user_ids = data.get('userIds') or []
    count = data.get('count')
    gameid = data.get('gameid', 283)  # 川麻 xzmo 默认 (105 ≠ 川麻, 远端无此玩家表 → 500)
    opid = data.get('opid')
    if not isinstance(user_ids, list) or not user_ids:
        return None, None, None, None, 'userIds 必填且非空'
    if count is None:
        return None, None, None, None, 'count 必填'
    try:
        count = int(count)
        if count <= 0:
            return None, None, None, None, 'count 必须为正整数'
    except (ValueError, TypeError):
        return None, None, None, None, 'count 格式错误'
    valid = []
    for uid in user_ids:
        try:
            n = int(uid)
            if n > 0:
                valid.append(str(n))
        except (ValueError, TypeError):
            continue
    if not valid:
        return None, None, None, None, '无有效 userId'
    return valid, count, int(gameid), (int(opid) if opid is not None else None), None


def _proxy_deposit_multi(endpoint, user_ids, count, gameid, opid, per_user_timeout=5):
    """逐个 userId 调用 deposit 远程 (远端不支持逗号串多账号 → 500), 聚合结果.

    返 (results_list, overall_status). overall_status = 200 若全成功, 否则 500.
    results_list: [{userId, status, ok}], 失败项带 upstream 字段供排查.
    """
    results = []
    all_ok = True
    for uid in user_ids:
        upstream, status = _proxy_deposit_remote(
            endpoint, uid, count, gameid, opid, timeout=per_user_timeout
        )
        ok = (status == 200)
        if not ok:
            all_ok = False
        results.append({'userId': uid, 'status': status, 'ok': ok, **({'upstream': upstream} if not ok else {})})
    return results, (200 if all_ok else 500)


# 荣耀特权累计经验 -> 等级折算表（达到该等级所需累计经验下限）
# 与 chunkSvr TQVipConfig.lua configs.grade[].experience 单级阈值求和一致
# 与 leveldefine_xzmp.jsonc levelContent[].experience 累计阈值一致
TQVIP_GRADE_THRESHOLDS = [
    0, 100, 600, 1600, 4600, 9600, 19600, 39600,
    79600, 159600, 309600, 609600, 1209600, 2209600, 4209600, 7209600
]

def calc_tqvip_grade(experience):
    """根据累计经验返回目标等级：满足阈值的最大等级。"""
    grade = 0
    for i, threshold in enumerate(TQVIP_GRADE_THRESHOLDS):
        if experience >= threshold:
            grade = i
        else:
            break
    return grade

def calc_tqvip_in_grade_exp(experience, grade):
    """累计经验减去该等级累计下限，得到当前级内经验（符合 chunkSvr Lua 语义）。"""
    return experience - TQVIP_GRADE_THRESHOLDS[grade]


def execute_robot_tool_command(exe_path, command):
    """执行RobotToolD.exe命令，添加超时和自动终止功能"""
    try:
        # 使用subprocess执行命令
        process = subprocess.Popen(
            [exe_path],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=os.path.dirname(exe_path)
        )
        
        # 发送命令到进程
        stdout, stderr = process.communicate(input=command + '\n', timeout=3)
        
        # 记录执行结果
        if stdout:
            print(f"RobotToolD输出: {stdout}")
        if stderr:
            print(f"RobotToolD错误: {stderr}")
            
    except subprocess.TimeoutExpired:
        # 超时后强制终止进程
        print("RobotToolD执行超时，正在终止进程...")
        try:
            process.terminate()  # 尝试优雅终止
            process.wait(timeout=2)  # 等待2秒让进程结束
        except subprocess.TimeoutExpired:
            # 如果优雅终止失败，强制杀死进程
            print("优雅终止失败，强制杀死进程...")
            process.kill()
            process.wait()
        print("RobotToolD进程已终止")
        
    except Exception as e:
        print(f"执行RobotToolD命令时发生错误: {str(e)}")
        # 确保异常时也终止进程
        try:
            process.terminate()
            process.wait(timeout=1)
        except:
            try:
                process.kill()
                process.wait()
            except:
                pass

# ===== 做牌器 test.ini 文件读写（直读 D:\game\{svc}\server_game，绕开 servicesvr 运行态要求） =====
import re as _re
import shutil as _shutil
MAKECARD_SERVICES = {
    'xzmo':  r'D:\game\xzmo\server_game',
    'xzms':  r'D:\game\xzms\server_game',
    'xzmo2': r'D:\game\xzmo2\server_game',
}
_MAKECARD_FILE_RE = _re.compile(r'^test[\w.-]*\.ini$', _re.IGNORECASE)

# ===== 做牌开关（[Card] Made 键；引擎 MjTable::CreateCardsFromFile 语义：Made>0 按 Total 布局做牌，0/缺省不做牌） =====
# 字节级解析/改写：只动 Made 行，其余字节原样（保 GBK 编码与换行风格；引擎 GetPrivateProfileInt 走 ANSI 解析）
_MADE_LINE_RE = _re.compile(rb'(?mi)^[ \t]*Made[ \t]*=[^\r\n]*')

def _read_test_ini_made(path):
    """读生效 test.ini 的 Made 值，返回 (made, raw_bytes)；无键/非法值按引擎缺省 = 0"""
    with open(path, 'rb') as f:
        raw = f.read()
    m = _MADE_LINE_RE.search(raw)
    if not m:
        return 0, raw
    try:
        return int(m.group(0).split(b'=', 1)[1].strip()), raw
    except ValueError:
        return 0, raw

