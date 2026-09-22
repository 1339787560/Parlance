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

@app.route('/api/services/status', methods=['GET'])
def api_get_services_status():
    try:
        status = Service.get_all_service_status()
        return jsonify(status)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/services/start', methods=['POST'])
def api_start_service():
    try:
        data = request.json
        name = data.get('name')
        type_name = data.get('type')
        exe_name = data.get('exe')
        
        if not all([name, type_name, exe_name]):
            return jsonify({'success': False, 'message': '参数不完整'}), 400
        
        # 启动服务的线程，避免阻塞
        def start_service_thread():
            service_display_name = Service.get_service_display_name(name, type_name)
            # 先直接使用subprocess方式启动服务
            success, message = Service.start_service(name, type_name, exe_name)
            
            if not success:
                # 如果失败，添加详细错误信息
                with Service.lock:
                    Service.service_status[f"{name}_{type_name}"] = "启动失败"
                # 可以选择是否记录错误日志
                print(f"服务启动失败: {message}")
        
        thread = threading.Thread(target=start_service_thread)
        thread.daemon = True
        thread.start()
        
        return jsonify({'success': True, 'message': '服务启动请求已提交'})
    except Exception as e:
        return jsonify({'success': False, 'message': f'启动服务时发生错误: {str(e)}'}), 500

@app.route('/api/services/stop', methods=['POST'])
def api_stop_service():
    try:
        data = request.json
        exe_name = data.get('exe')
        name = data.get('name')
        type_name = data.get('type')
        
        if not exe_name:
            return jsonify({'success': False, 'message': '请提供可执行文件名'}), 400
        
        success, message = Service.stop_service(name, type_name, exe_name)
        
        return jsonify({'success': success, 'message': message})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/services/deploy', methods=['POST'])
def api_deploy_service():
    try:
        data = request.json
        name = data.get('name')
        type_name = data.get('type')
        exe_name = data.get('exe')
        
        if not all([name, type_name, exe_name]):
            return jsonify({'success': False, 'message': '参数不完整'}), 400
        
        success, message = Service.deploy_service(name, type_name, exe_name)
        return jsonify({'success': success, 'message': message})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/services/start-all', methods=['POST'])
def api_start_all_services():
    try:
        # 在新线程中启动所有服务，避免阻塞
        def start_all_services_thread():
            Service.start_all_services()
        
        thread = threading.Thread(target=start_all_services_thread)
        thread.daemon = True
        thread.start()
        
        return jsonify({'success': True, 'message': '所有服务已开始启动，请稍后查看状态'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/services/delete', methods=['POST'])
def api_delete_service():
    try:
        data = request.json
        name = data.get('name')
        type_name = data.get('type')
        
        if not all([name, type_name]):
            return jsonify({'success': False, 'message': '参数不完整'}), 400
        
        success, message = Service.delete_service(name, type_name)
        return jsonify({'success': success, 'message': message})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/services/update', methods=['POST'])
def api_update_service():
    try:
        # 获取表单数据
        name = request.form.get('name')
        type_name = request.form.get('type')
        exe_name = request.form.get('exe')
        
        if 'file_exe' not in request.files:
            return jsonify({'success': False, 'message': '未找到上传的 .exe 文件'}), 400
        if 'file_pdb' not in request.files:
            return jsonify({'success': False, 'message': '未找到上传的 .pdb 文件'}), 400
            
        file_exe = request.files['file_exe']
        file_pdb = request.files['file_pdb']
        
        if file_exe.filename == '':
            return jsonify({'success': False, 'message': '未选择 .exe 文件'}), 400
        if file_pdb.filename == '':
            return jsonify({'success': False, 'message': '未选择 .pdb 文件'}), 400
            
        # 验证文件名是否一致
        if file_exe.filename.lower() != exe_name.lower():
            return jsonify({'success': False, 'message': f'上传的 .exe 文件名 {file_exe.filename} 与配置的 {exe_name} 不匹配'}), 400
        
        # 验证 .pdb 文件名是否与 .exe 文件名匹配 (基本名称)
        exe_base_name = os.path.splitext(file_exe.filename)[0].lower()
        pdb_base_name = os.path.splitext(file_pdb.filename)[0].lower()

        if exe_base_name != pdb_base_name:
            return jsonify({'success': False, 'message': f'上传的 .exe 文件 ({file_exe.filename}) 和 .pdb 文件 ({file_pdb.filename}) 的基本文件名不匹配'}), 400

        # 在后端执行更新逻辑
        file_exe_content = file_exe.read()
        file_pdb_content = file_pdb.read()
        success, message = Service.update_service_file(name, type_name, exe_name, file_exe_content, file_pdb_content)
        
        return jsonify({'success': success, 'message': message})
    except Exception as e:
        return jsonify({'success': False, 'message': f'更新服务时发生错误: {str(e)}'}), 500

@app.route('/api/services/restart', methods=['POST'])
def api_restart_service():
    """热更新服务：停止 → 等待进程退出 → 启动。文件已在本地（deploy 包推送或手动替换），不需要上传。"""
    try:
        data = request.json
        name = data.get('name')
        type_name = data.get('type')
        exe_name = data.get('exe')

        if not all([name, type_name, exe_name]):
            return jsonify({'success': False, 'message': '参数不完整（需要 name, type, exe）'}), 400

        def restart_thread():
            service_display_name = Service.get_service_display_name(name, type_name)
            # 1. 停止服务
            stop_success, stop_msg = Service.stop_service(name, type_name, exe_name)
            if not stop_success and "不存在" not in stop_msg and "已经停止" not in stop_msg and "未找到" not in stop_msg:
                with Service.lock:
                    Service.service_status[f"{name}_{type_name}"] = f"重启失败(停止失败): {stop_msg}"
                return
            # 2. 等待进程退出
            time.sleep(2)
            # 3. 启动服务
            start_success, start_msg = Service.start_service(name, type_name, exe_name)
            if not start_success:
                with Service.lock:
                    Service.service_status[f"{name}_{type_name}"] = f"重启失败(启动失败): {start_msg}"

        thread = threading.Thread(target=restart_thread)
        thread.daemon = True
        thread.start()

        return jsonify({'success': True, 'message': '服务重启请求已提交（停止 → 等待 → 启动）'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

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

@app.route('/api/set-gold', methods=['POST'])
def api_set_gold():
    try:
        data = request.json
        operation = data.get('operation')
        gold_count = data.get('goldCount')
        
        if not operation or not gold_count:
            return jsonify({'success': False, 'message': '参数不完整'}), 400
        
        # 验证金币数量
        try:
            gold_count = int(gold_count)
            if gold_count <= 0:
                return jsonify({'success': False, 'message': '金币数量必须为正整数'}), 400
        except (ValueError, TypeError):
            return jsonify({'success': False, 'message': '金币数量格式错误'}), 400
        
        # 构建RobotToolD.exe的路径
        exe_path = os.path.join(os.getcwd(), 'exeDir', 'RobotToolD.exe')
        
        if not os.path.exists(exe_path):
            return jsonify({'success': False, 'message': 'RobotToolD.exe不存在'}), 400
        
        # 在新线程中执行设置操作，避免阻塞
        def execute_gold_setting():
            try:
                if operation == 'single':
                    user_id = data.get('userId')
                    if not user_id:
                        return
                    
                    try:
                        user_id = int(user_id)
                        if user_id <= 0:
                            return
                    except (ValueError, TypeError):
                        return
                    
                    # 构建命令：setSingleGold userId goldCount
                    command = f'setSingleGold {user_id} {gold_count}'
                    execute_robot_tool_command(exe_path, command)
                    
                elif operation == 'multi':
                    user_ids = data.get('userIds')
                    if not user_ids or not isinstance(user_ids, list):
                        return
                    
                    # 验证所有用户ID
                    valid_user_ids = []
                    for user_id in user_ids:
                        try:
                            user_id = int(user_id)
                            if user_id > 0:
                                valid_user_ids.append(str(user_id))
                        except (ValueError, TypeError):
                            continue
                    
                    if not valid_user_ids:
                        return
                    
                    # 构建命令：setMultiGold userId1 userId2 ... userIdN goldCount
                    command = f'setMultiGold {" ".join(valid_user_ids)} {gold_count}'
                    execute_robot_tool_command(exe_path, command)
                
            except Exception as e:
                print(f"设置金币时发生错误: {str(e)}")
        
        # 启动线程执行设置操作
        thread = threading.Thread(target=execute_gold_setting)
        thread.daemon = True
        thread.start()
        
        return jsonify({
            'success': True, 
            'message': f'金币设置请求已提交，操作类型: {operation}'
        })
        
    except Exception as e:
        return jsonify({'success': False, 'message': f'设置金币时发生错误: {str(e)}'}), 500

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


@app.route('/api/set-points', methods=['POST'])
def api_set_points():
    """积分设置: servicesvr 代理转发到 deposit 远程 :5003/setscore.
    Body JSON: {userIds: [int], count: int, gameid?: 105, opid?: 0(设置绝对值)}.
    opid: 0=设置相应的值 / 1=增加 / 2=减少 (与 deposit.html setscore 一致).
    远端仅支持单 userid, 这里拆 userIds 逐个调用聚合 (deposit.html 逗号串静默 500 bug 规避).
    """
    data = request.json or {}
    user_ids, count, gameid, opid, err = _validate_deposit_payload(data)
    if err:
        return jsonify({'success': False, 'message': err}), 400
    if opid is None:
        opid = 0
    results, status = _proxy_deposit_multi('/setscore', user_ids, count, gameid, opid)
    return jsonify({'success': status == 200, 'results': results,
                    'userIds': ','.join(user_ids), 'count': count, 'opid': opid}), status


@app.route('/api/set-silver', methods=['POST'])
def api_set_silver():
    """银两设置: servicesvr 代理转发到 deposit 远程 :5003/SetSilver.
    Body JSON: {userIds: [int], count: int, gameid?: 105, opid?: 2(游戏里的银子)}.
    silver opid 全集: 1=保险箱 / 2=游戏里 / 3=后备箱 / 4=保险柜. 默认 2 = "发放到游戏中".
    远端仅支持单 userid, 拆 userIds 逐个调用聚合.
    """
    data = request.json or {}
    user_ids, count, gameid, opid, err = _validate_deposit_payload(data)
    if err:
        return jsonify({'success': False, 'message': err}), 400
    if opid is None:
        opid = 2
    results, status = _proxy_deposit_multi('/SetSilver', user_ids, count, gameid, opid)
    return jsonify({'success': status == 200, 'results': results,
                    'userIds': ','.join(user_ids), 'count': count, 'opid': opid}), status

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


@app.route('/api/set-tqvip', methods=['POST'])
def api_set_tqvip():
    """设置荣耀特权数据。经验决定等级，上次登录时间决定 datetag，上次展示动画等级同步为当前等级。"""
    try:
        data = request.json
        user_ids = data.get('userIds')
        experience = data.get('experience')
        last_login_date = data.get('lastLoginDate')
        isdemoteani = data.get('isdemoteani')
        rewardstatus = data.get('rewardstatus')  # list of grade indices whose one-time reward is claimed

        if not all([user_ids, experience is not None, last_login_date is not None, isdemoteani is not None]):
            return jsonify({'success': False, 'message': '参数不完整'}), 400

        try:
            experience = int(experience)
            if experience < 0:
                raise ValueError
        except (ValueError, TypeError):
            return jsonify({'success': False, 'message': '经验值必须是非负整数'}), 400

        grade = calc_tqvip_grade(experience)
        # experience 是累计经验，chunkSvr Lua 的 experience 字段语义为级内进度。
        # 拆出级内经验写入，符合 Lua checkGrade 语义（级内 < 下一级阈值则不触发升级）。
        in_grade_exp = calc_tqvip_in_grade_exp(experience, grade)

        # 解析上次登录时间 -> datetag（YYYYMMDD 格式）
        try:
            if isinstance(last_login_date, int):
                datetag = last_login_date
            elif isinstance(last_login_date, str):
                # 支持 "2026-06-30T12:34" 或 "2026-06-30 12:34:56"
                dt = datetime.fromisoformat(last_login_date.replace(' ', 'T'))
                datetag = timeUtil.getdatenum(dt)
            else:
                datetag = timeUtil.getdatenum(datetime.now())
        except (ValueError, TypeError):
            return jsonify({'success': False, 'message': '上次登录时间格式错误'}), 400

        manager = TQVIPManager()
        results = {}
        for user_id in user_ids:
            vip_message = manager.get_vip_data(user_id)
            if not vip_message:
                vip_message = tqvip_pb2.TQVip_PlayerData() # 如果不存在，则创建新的

            vip_message.experience = in_grade_exp
            vip_message.grade = grade
            vip_message.maxexperience = in_grade_exp
            vip_message.maxgrade = grade
            vip_message.lastshowanigrade = grade
            vip_message.isdemoteani = isdemoteani
            vip_message.datetag = datetag

            # rewardstatus: 前端已按当前等级构建完整数组，长度 = grade+1，1=已领取，0=未领取
            if rewardstatus is not None:
                vip_message.ClearField('rewardstatus')
                provided = list(rewardstatus)[:grade + 1]
                provided += [0] * (grade + 1 - len(provided))
                vip_message.rewardstatus.extend(provided)
            # 未传入时不做修改，保留玩家原有已领取状态

            if manager.set_vip_data(user_id, vip_message):
                results[user_id] = '成功'
            else:
                results[user_id] = '失败'

        return jsonify({
            'success': True,
            'message': '荣耀特权设置请求已提交',
            'results': results,
            'computedGrade': grade,
            'inGradeExperience': in_grade_exp,
            'datetag': datetag
        })
    except Exception as e:
        return jsonify({'success': False, 'message': f'设置荣耀特权时发生错误: {str(e)}'}), 500

@app.route('/api/set-weekcard', methods=['POST'])
def api_set_weekcard():
    """设置周卡数据"""
    try:
        data = request.json
        user_ids = data.get('userIds')
        days = data.get('days')

        if not all([user_ids, days is not None]):
            return jsonify({'success': False, 'message': '参数不完整'}), 400
        
        manager = TQMonthCardManager()
        results = {}
        for user_id in user_ids:
            month_card_cache = manager.get_month_card_data(user_id)
            if not month_card_cache:
                month_card_cache = tqvip_pb2.TQMonthCard_Cache() # 如果不存在，则创建新的

            # 设置周卡信息
            month_card_cache.player.weekcard.datetag = timeUtil.getdatenum(datetime.now())
            month_card_cache.player.weekcard.starttime = timeUtil.gettimenum(datetime.now())
            month_card_cache.player.weekcard.endtime = timeUtil.add_time_to_timenum(timeUtil.gettimenum(datetime.now()), days=days)

            if manager.set_month_card_data(user_id, month_card_cache):
                results[user_id] = '成功'
            else:
                results[user_id] = '失败'
        
        return jsonify({'success': True, 'message': '周卡设置请求已提交', 'results': results})
    except Exception as e:
        return jsonify({'success': False, 'message': f'设置周卡时发生错误: {str(e)}'}), 500

@app.route('/api/set-monthcard', methods=['POST'])
def api_set_monthcard():
    """设置月卡数据"""
    try:
        data = request.json
        user_ids = data.get('userIds')
        days = data.get('days')

        if not all([user_ids, days is not None]):
            return jsonify({'success': False, 'message': '参数不完整'}), 400
        
        manager = TQMonthCardManager()
        results = {}
        for user_id in user_ids:
            month_card_cache = manager.get_month_card_data(user_id)
            if not month_card_cache:
                month_card_cache = tqvip_pb2.TQMonthCard_Cache() # 如果不存在，则创建新的

            # 设置月卡信息
            month_card_cache.player.monthcard.datetag = timeUtil.getdatenum(datetime.now())
            month_card_cache.player.monthcard.starttime = timeUtil.gettimenum(datetime.now())
            month_card_cache.player.monthcard.endtime = timeUtil.add_time_to_timenum(timeUtil.gettimenum(datetime.now()), days=days)

            if manager.set_month_card_data(user_id, month_card_cache):
                results[user_id] = '成功'
            else:
                results[user_id] = '失败'
        
        return jsonify({'success': True, 'message': '月卡设置请求已提交', 'results': results})
    except Exception as e:
        return jsonify({'success': False, 'message': f'设置月卡时发生错误: {str(e)}'}), 500

@app.route('/api/query-costume', methods=['POST'])
def api_query_costume():
    """查询 Lua 版本玩家装扮（已拥有 + 时限 + 已装备）。"""
    try:
        data = request.json
        user_id = data.get('userId')
        if not user_id:
            return jsonify({'success': False, 'message': '参数不完整'}), 400

        try:
            user_id = int(user_id)
            if user_id <= 0:
                raise ValueError
        except (ValueError, TypeError):
            return jsonify({'success': False, 'message': '玩家ID格式错误'}), 400

        manager = CostumeManager()
        result = manager.query_costume(user_id)
        return jsonify({'success': True, 'data': result})
    except Exception as e:
        return jsonify({'success': False, 'message': f'查询装扮失败: {str(e)}'}), 500

@app.route('/api/set-newplayer-gift', methods=['POST'])
def api_set_newplayer_gift():
    """设置/取消 Lua 版本玩家迎新礼包状态。"""
    try:
        data = request.json
        user_ids = data.get('userIds')
        cancel = data.get('cancel', False)

        if not user_ids or not isinstance(user_ids, list):
            return jsonify({'success': False, 'message': '参数不完整'}), 400

        valid_user_ids = []
        for uid in user_ids:
            try:
                uid = int(uid)
                if uid > 0:
                    valid_user_ids.append(uid)
            except (ValueError, TypeError):
                continue

        if not valid_user_ids:
            return jsonify({'success': False, 'message': '请输入有效的玩家ID列表'}), 400

        manager = TQNewPlayerGiftManager()
        if cancel:
            results = manager.cancel_gift(valid_user_ids)
            message = '取消迎新礼包请求已提交'
        else:
            receivable_day = data.get('receivableDay')
            receivedays = data.get('receivedays')

            if receivable_day is not None:
                # "第 X 天可领" 模式：玩家可立即领取第 X 天奖励
                # -> receivedays = X-1, lastdate = 昨日(YYYYMMDD)
                try:
                    receivable_day = int(receivable_day)
                    if receivable_day < 1 or receivable_day > 7:
                        raise ValueError
                except (ValueError, TypeError):
                    return jsonify({'success': False, 'message': '可领天数必须是 1-7 的整数'}), 400
                target_receivedays = receivable_day - 1
                yesterday = _getdatenum(datetime.now() - timedelta(days=1))
                results = manager.set_receivedays(
                    valid_user_ids, target_receivedays, target_lastdate=yesterday)
                message = f'迎新礼包设置请求已提交（第 {receivable_day} 天可领）'
            else:
                if receivedays is None:
                    return jsonify({'success': False, 'message': '参数不完整'}), 400
                try:
                    receivedays = int(receivedays)
                    if receivedays < 0 or receivedays > 7:
                        raise ValueError
                except (ValueError, TypeError):
                    return jsonify({'success': False, 'message': '领取天数必须是 0-7 的整数'}), 400
                results = manager.set_receivedays(valid_user_ids, receivedays)
                message = '迎新礼包设置请求已提交'

        return jsonify({'success': True, 'message': message, 'results': results})
    except Exception as e:
        return jsonify({'success': False, 'message': f'设置迎新礼包失败: {str(e)}'}), 500

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

@app.route('/deposit')
def deposit_page():
    """显示设置货币页面"""
    return render_template('deposit.html')

@app.route('/fileontimer')
def fileontimer_page():
    """显示FileOnTimer文件浏览页面"""
    return render_template('FileOnTimer.html')

@app.route('/makecard')
def makecard_page():
    """显示做牌器页面"""
    return render_template('makecard.html')

# ===== 做牌器 test.ini 文件读写（直读 D:\game\{svc}\server_game，绕开 servicesvr 运行态要求） =====
import re as _re
import shutil as _shutil
MAKECARD_SERVICES = {
    'xzmo':  r'D:\game\xzmo\server_game',
    'xzms':  r'D:\game\xzms\server_game',
    'xzmo2': r'D:\game\xzmo2\server_game',
}
_MAKECARD_FILE_RE = _re.compile(r'^test[\w.-]*\.ini$', _re.IGNORECASE)

@app.route('/api/makecard/files', methods=['GET'])
def api_makecard_files():
    """列出服务目录下所有 test*.ini（含场景备份与 remove/ 子目录）"""
    svc = request.args.get('service')
    base = MAKECARD_SERVICES.get(svc)
    if not base:
        return jsonify({'success': False, 'message': f'不支持的服务: {svc}'}), 400
    files = []
    if os.path.exists(base):
        for f in sorted(os.listdir(base)):
            if _MAKECARD_FILE_RE.match(f):
                files.append(f)
    # remove/ 子目录备份
    remove_dir = os.path.join(base, 'remove')
    if os.path.isdir(remove_dir):
        for f in sorted(os.listdir(remove_dir)):
            if _MAKECARD_FILE_RE.match(f):
                files.append('remove/' + f)
    return jsonify({'success': True, 'files': files, 'service': svc, 'base': base})

@app.route('/api/makecard/read', methods=['GET'])
def api_makecard_read():
    """读取服务目录下指定 test*.ini 内容（自动探测编码）"""
    svc = request.args.get('service')
    file = request.args.get('file')
    base = MAKECARD_SERVICES.get(svc)
    if not base:
        return jsonify({'success': False, 'message': f'不支持的服务: {svc}'}), 400
    if not file or not _MAKECARD_FILE_RE.match(file.split('/')[-1]):
        return jsonify({'success': False, 'message': '非法文件名（需 test*.ini）'}), 400
    path = os.path.join(base, file)
    if not os.path.abspath(path).startswith(os.path.abspath(base)):
        return jsonify({'success': False, 'message': '路径越界'}), 400
    if not os.path.exists(path):
        return jsonify({'success': False, 'message': f'文件不存在: {file}'}), 404
    try:
        raw = open(path, 'rb').read()
        content = None
        for enc in ('utf-8-sig', 'utf-8', 'gbk', 'latin-1'):
            try:
                content = raw.decode(enc); break
            except UnicodeDecodeError:
                continue
        return jsonify({'success': True, 'content': content, 'file': file, 'service': svc})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/makecard/save', methods=['POST'])
def api_makecard_save():
    """保存做牌内容到 test*.ini（写前 .bak 备份，原位写）"""
    data = request.json or {}
    svc = data.get('service')
    file = data.get('file')
    content = data.get('content')
    base = MAKECARD_SERVICES.get(svc)
    if not base:
        return jsonify({'success': False, 'message': f'不支持的服务: {svc}'}), 400
    if not file or not _MAKECARD_FILE_RE.match(file.split('/')[-1]):
        return jsonify({'success': False, 'message': '非法文件名（需 test*.ini）'}), 400
    if content is None:
        return jsonify({'success': False, 'message': '缺少 content'}), 400
    path = os.path.join(base, file)
    if not os.path.abspath(path).startswith(os.path.abspath(base)):
        return jsonify({'success': False, 'message': '路径越界'}), 400
    try:
        # 写前备份（同目录 .bak，不覆盖已存在的 .bak）
        if os.path.exists(path):
            bak = path + '.bak'
            if not os.path.exists(bak):
                try: _shutil.copy2(path, bak)
                except Exception: pass
        # 原位写（与 servicesvr 一致，避免 rename 漏文件监视）
        with open(path, 'w', encoding='utf-8', newline='') as f:
            f.write(content)
        return jsonify({'success': True, 'message': '已保存', 'file': file,
                        'service': svc, 'path': path})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/makecard/activate', methods=['POST'])
def api_makecard_activate():
    """将指定 test*.ini 设为生效：备份当前 test.ini → remove/test.ini.bak.{ts}，复制 file → test.ini"""
    data = request.json or {}
    svc = data.get('service')
    file = data.get('file')
    base = MAKECARD_SERVICES.get(svc)
    if not base:
        return jsonify({'success': False, 'message': f'不支持的服务: {svc}'}), 400
    if not file or not _MAKECARD_FILE_RE.match(file.split('/')[-1]):
        return jsonify({'success': False, 'message': '非法文件名（需 test*.ini）'}), 400
    if file == 'test.ini':
        return jsonify({'success': False, 'message': 'test.ini 已是生效文件'}), 400
    src = os.path.join(base, file)
    active = os.path.join(base, 'test.ini')
    if not os.path.abspath(src).startswith(os.path.abspath(base)):
        return jsonify({'success': False, 'message': '路径越界'}), 400
    if not os.path.exists(src):
        return jsonify({'success': False, 'message': f'文件不存在: {file}'}), 404
    try:
        # 读 branch 原始字节 + 解码
        branch_raw = open(src, 'rb').read()
        branch_text = None
        for enc in ('utf-8-sig', 'utf-8', 'gbk', 'latin-1'):
            try:
                branch_text = branch_raw.decode(enc); break
            except UnicodeDecodeError:
                continue
        # 备份当前 test.ini（时间戳，不覆盖）
        backup_rel = ''
        if os.path.exists(active):
            from datetime import datetime as _dt
            ts = _dt.now().strftime('%Y%m%d_%H%M%S')
            remove_dir = os.path.join(base, 'remove')
            if not os.path.isdir(remove_dir):
                os.makedirs(remove_dir)
            backup_rel = f'remove/test.ini.bak.{ts}'
            _shutil.copy2(active, os.path.join(base, backup_rel))
        # branch 原位写入 test.ini（保留原编码字节）
        with open(active, 'wb') as f:
            f.write(branch_raw)
        return jsonify({
            'success': True,
            'message': f'已生效（旧 test.ini → {backup_rel or "无（原 test.ini 不存在）"}）',
            'backup': backup_rel, 'content': branch_text,
            'activated': file, 'service': svc,
        })
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/makecard/delete', methods=['POST'])
def api_makecard_delete():
    """删除做牌记录文件（test.ini 生效文件禁删；remove/ 备份可删）"""
    data = request.json or {}
    svc = data.get('service')
    file = data.get('file')
    base = MAKECARD_SERVICES.get(svc)
    if not base:
        return jsonify({'success': False, 'message': f'不支持的服务: {svc}'}), 400
    if not file or not _MAKECARD_FILE_RE.match(file.split('/')[-1]):
        return jsonify({'success': False, 'message': '非法文件名（需 test*.ini）'}), 400
    path = os.path.join(base, file)
    # 规范化相对路径（防 remove/../test.ini 穿越绕过），越界 + 生效文件判定均基于它
    rel = os.path.relpath(os.path.abspath(path), os.path.abspath(base)).replace('\\', '/')
    if rel.startswith('..'):
        return jsonify({'success': False, 'message': '路径越界'}), 400
    if rel.lower() == 'test.ini':
        return jsonify({'success': False, 'message': 'test.ini 为生效文件，禁止删除'}), 400
    if not os.path.exists(path):
        return jsonify({'success': False, 'message': f'文件不存在: {file}'}), 404
    try:
        os.remove(path)
        return jsonify({'success': True, 'message': f'已删除 {file}', 'file': file, 'service': svc})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/makecard/rename', methods=['POST'])
def api_makecard_rename():
    """重命名做牌记录（根目录 test.ini 生效文件禁改；新名不含路径，总落根目录）"""
    data = request.json or {}
    svc = data.get('service')
    file = data.get('file')
    new_file = data.get('newFile')
    base = MAKECARD_SERVICES.get(svc)
    if not base:
        return jsonify({'success': False, 'message': f'不支持的服务: {svc}'}), 400
    if not file or not _MAKECARD_FILE_RE.match(file.split('/')[-1]):
        return jsonify({'success': False, 'message': '非法文件名（需 test*.ini）'}), 400
    if not new_file or '/' in new_file or not _MAKECARD_FILE_RE.match(new_file):
        return jsonify({'success': False, 'message': '非法新文件名（需 test*.ini，不含路径）'}), 400
    src = os.path.join(base, file)
    # 规范化相对路径（防 remove/../test.ini 穿越绕过），越界 + 生效文件判定均基于它
    rel = os.path.relpath(os.path.abspath(src), os.path.abspath(base)).replace('\\', '/')
    if rel.startswith('..'):
        return jsonify({'success': False, 'message': '路径越界'}), 400
    if rel.lower() == 'test.ini':
        return jsonify({'success': False, 'message': 'test.ini 为生效文件，禁止重命名'}), 400
    dst = os.path.join(base, new_file)
    if not os.path.exists(src):
        return jsonify({'success': False, 'message': f'文件不存在: {file}'}), 404
    if os.path.exists(dst):
        return jsonify({'success': False, 'message': f'目标已存在: {new_file}'}), 400
    if os.path.abspath(src).lower() == os.path.abspath(dst).lower():
        return jsonify({'success': False, 'message': '新文件名与原名相同'}), 400
    try:
        os.rename(src, dst)
        return jsonify({'success': True, 'message': f'已重命名 {file} → {new_file}',
                        'file': new_file, 'service': svc})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

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

@app.route('/api/makecard/made', methods=['GET'])
def api_makecard_made():
    """查询当前生效 test.ini 的做牌开关状态"""
    svc = request.args.get('service')
    base = MAKECARD_SERVICES.get(svc)
    if not base:
        return jsonify({'success': False, 'message': f'不支持的服务: {svc}'}), 400
    path = os.path.join(base, 'test.ini')
    if not os.path.exists(path):
        return jsonify({'success': False, 'message': f'生效文件不存在: test.ini（{base}）'}), 404
    try:
        made, _ = _read_test_ini_made(path)
        return jsonify({'success': True, 'service': svc, 'made': made})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/makecard/toggle', methods=['POST'])
def api_makecard_toggle():
    """开关做牌：原位改生效 test.ini 的 [Card] Made（1=开 0=关）。
    关闭（1→0）前整份备份 test.ini → remove/test_made_on.{ts}.ini——关闭态引擎会把每局
    实况随机牌写回 Total（MjTable.cpp WritePrivateProfileString）覆盖原布局，留档才能恢复。"""
    data = request.json or {}
    svc = data.get('service')
    made = data.get('made')
    base = MAKECARD_SERVICES.get(svc)
    if not base:
        return jsonify({'success': False, 'message': f'不支持的服务: {svc}'}), 400
    if made not in (0, 1):
        return jsonify({'success': False, 'message': 'made 仅支持 0（关）/ 1（开）'}), 400
    path = os.path.join(base, 'test.ini')
    if not os.path.exists(path):
        return jsonify({'success': False, 'message': f'生效文件不存在: test.ini（{base}）'}), 404
    try:
        cur, raw = _read_test_ini_made(path)
        if cur == made:
            return jsonify({'success': True, 'message': f'已是目标状态（Made={made}），未改动',
                            'service': svc, 'made': made, 'backup': None})
        backup = None
        if made == 0 and cur > 0:
            remove_dir = os.path.join(base, 'remove')
            os.makedirs(remove_dir, exist_ok=True)
            ts = time.strftime('%Y%m%d_%H%M%S')
            _shutil.copy2(path, os.path.join(remove_dir, f'test_made_on.{ts}.ini'))
            backup = f'remove/test_made_on.{ts}.ini'
        new_line = f'Made={made}'.encode('ascii')
        if _MADE_LINE_RE.search(raw):
            new_raw = _MADE_LINE_RE.sub(lambda _m: new_line, raw, count=1)
        else:
            # 无 Made 键 → 插到 [Card] 节行后（跟随该行换行风格）；无节则文件头插入
            sec = _re.search(rb'(?mi)^[ \t]*\[Card\][^\r\n]*', raw)
            if sec:
                pos = sec.end()
                nl = b'\r\n' if raw[pos:pos + 2] == b'\r\n' else b'\n'
                new_raw = raw[:pos] + nl + new_line + raw[pos:]
            else:
                new_raw = new_line + b'\r\n' + raw
        with open(path, 'wb') as f:
            f.write(new_raw)
        msg = (f'做牌已关闭（Made=0），原布局备份 {backup}' if made == 0 else '做牌已开启（Made=1）')
        return jsonify({'success': True, 'message': msg, 'service': svc, 'made': made, 'backup': backup})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/fileontimer/list', methods=['GET'])
def api_fileontimer_list():
    """获取FileOnTimer目录下的文件列表"""
    try:
        path = request.args.get('path', 'FileOnTimer')
        
        # 构建完整路径
        full_path = os.path.join(os.getcwd(), path)
        
        # 安全检查：确保路径在允许的范围内
        if not full_path.startswith(os.getcwd()):
            return jsonify({'success': False, 'message': '路径访问被拒绝'}), 403
        
        if not os.path.exists(full_path):
            return jsonify({'success': False, 'message': '路径不存在'}), 404
        
        files = []
        for item in os.listdir(full_path):
            item_path = os.path.join(full_path, item)
            is_directory = os.path.isdir(item_path)
            size = 0 if is_directory else os.path.getsize(item_path)
            
            files.append({
                'name': item,
                'is_directory': is_directory,
                'size': size
            })
        
        # 按文件夹优先，然后按名称排序
        files.sort(key=lambda x: (not x['is_directory'], x['name'].lower()))
        
        return jsonify({'success': True, 'files': files})
        
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/fileontimer/download', methods=['GET'])
def api_fileontimer_download():
    """下载FileOnTimer目录下的文件"""
    try:
        path = request.args.get('path')
        if not path:
            return jsonify({'success': False, 'message': '请提供文件路径'}), 400
        
        # 构建完整路径
        full_path = os.path.join(os.getcwd(), path)
        
        # 安全检查：确保路径在允许的范围内
        if not full_path.startswith(os.getcwd()):
            return jsonify({'success': False, 'message': '路径访问被拒绝'}), 403
        
        if not os.path.exists(full_path):
            return jsonify({'success': False, 'message': '文件不存在'}), 404
        
        if os.path.isdir(full_path):
            return jsonify({'success': False, 'message': '无法下载文件夹'}), 400
        
        # 发送文件
        return send_file(full_path, as_attachment=True)
        
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500
    
import json
import subprocess
import threading

@app.route('/api/spideorder/get', methods=['GET'])
def api_spideorder_get():
    """获取spideOrder配置"""
    try:
        config_path = os.path.join(os.getcwd(), 'config.json')
        
        if not os.path.exists(config_path):
            return jsonify({'success': False, 'message': '配置文件不存在'}), 404
        
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
        
        commands = config.get('spideOrder', [])
        return jsonify({'success': True, 'commands': commands})
        
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/config', methods=['GET'])
def api_get_config():
    """获取config.json的全部内容"""
    try:
        config_path = os.path.join(os.getcwd(), 'config.json')
        
        if not os.path.exists(config_path):
            return jsonify({'success': False, 'message': '配置文件不存在'}), 404
        
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
        
        return jsonify(config)
        
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/spideorder/save', methods=['POST'])
def api_spideorder_save():
    """保存spideOrder配置"""
    try:
        data = request.json
        commands = data.get('commands', [])
        
        # 过滤空命令
        commands = [cmd.strip() for cmd in commands if cmd.strip()]
        
        config_path = os.path.join(os.getcwd(), 'config.json')
        
        if not os.path.exists(config_path):
            return jsonify({'success': False, 'message': '配置文件不存在'}), 404
        
        # 读取现有配置
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
        
        # 更新spideOrder配置
        config['spideOrder'] = commands
        
        # 保存配置
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=4)
        
        return jsonify({'success': True, 'message': '配置保存成功'})
        
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/spideorder/execute', methods=['POST'])
def api_spideorder_execute():
    """执行spideOnlineLog.py命令"""
    try:
        config_path = os.path.join(os.getcwd(), 'config.json')
        
        if not os.path.exists(config_path):
            return jsonify({'success': False, 'message': '配置文件不存在'}), 404
        
        # 读取配置
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
        
        commands = config.get('spideOrder', [])
        
        if not commands:
            return jsonify({'success': False, 'message': '没有配置执行命令'}), 400
        
        # 在新线程中执行命令，避免阻塞
        def execute_commands_thread():
            for command in commands:
                try:
                    # 执行spideOnlineLog.py命令
                    process = subprocess.Popen(
                        ['python', 'spideOnlineLog.py'] + command.split(),
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True
                    )
                    
                    stdout, stderr = process.communicate(timeout=300)  # 5分钟超时
                    
                    if stdout:
                        print(f"命令执行输出: {stdout}")
                    if stderr:
                        print(f"命令执行错误: {stderr}")
                        
                except subprocess.TimeoutExpired:
                    print(f"命令执行超时: {command}")
                    process.kill()
                except Exception as e:
                    print(f"命令执行失败: {command}, 错误: {str(e)}")
        
        thread = threading.Thread(target=execute_commands_thread)
        thread.daemon = True
        thread.start()
        
        return jsonify({'success': True, 'message': '命令执行已开始'})
        
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/serverstatus')
def serverstatus_page():
    """显示服务器状态页面"""
    return render_template('ServerStatus.html')

@app.route('/api/templates/save', methods=['POST'])
def api_save_template():
    """保存模板"""
    try:
        data = request.json
        name = data.get('name')
        template_type = data.get('type')
        template_data = data.get('data')

        if not all([name, template_type, template_data]):
            return jsonify({'success': False, 'message': '参数不完整'}), 400

        template_id = TemplateDB.add_template(name, template_type, template_data)
        return jsonify({'success': True, 'message': '模板保存成功', 'id': template_id})
    except Exception as e:
        return jsonify({'success': False, 'message': f'保存模板失败: {str(e)}'}), 500

@app.route('/api/templates/update', methods=['POST'])
def api_update_template():
    """更新已有模板（覆盖）"""
    try:
        data = request.json
        template_id = data.get('id')
        name = data.get('name')
        template_type = data.get('type')
        template_data = data.get('data')

        if not all([template_id, name, template_type, template_data]):
            return jsonify({'success': False, 'message': '参数不完整'}), 400

        if TemplateDB.update_template(template_id, name, template_type, template_data):
            return jsonify({'success': True, 'message': '模板更新成功'})
        else:
            return jsonify({'success': False, 'message': '模板不存在'}), 404
    except Exception as e:
        return jsonify({'success': False, 'message': f'更新模板失败: {str(e)}'}), 500

@app.route('/api/templates/get', methods=['GET'])
def api_get_templates():
    """获取所有模板"""
    try:
        templates = TemplateDB.get_templates()
        return jsonify({'success': True, 'templates': templates})
    except Exception as e:
        return jsonify({'success': False, 'message': f'获取模板失败: {str(e)}'}), 500

@app.route('/api/templates/delete', methods=['POST'])
def api_delete_template():
    """删除模板"""
    try:
        data = request.json
        template_id = data.get('id')

        if not template_id:
            return jsonify({'success': False, 'message': '模板ID不能为空'}), 400

        if TemplateDB.delete_template(template_id):
            return jsonify({'success': True, 'message': '模板删除成功'})
        else:
            return jsonify({'success': False, 'message': '模板不存在或删除失败'}), 404
    except Exception as e:
        return jsonify({'success': False, 'message': f'删除模板失败: {str(e)}'}), 500

import os
import glob

@app.route('/onlineConfigModify')
def online_config_modify_page():
    """显示在线配置修改页面"""
    return render_template('onlineConfigModify.html')

@app.route('/api/config/files', methods=['GET'])
def api_get_config_files():
    """获取服务目录下的配置文件列表"""
    try:
        service_id = request.args.get('serviceId')
        if not service_id:
            return jsonify({'success': False, 'message': '缺少服务ID'}), 400
        
        # 从服务状态获取服务路径
        services_status = Service.get_all_service_status()
        service_info = services_status.get(service_id)
        
        if not service_info:
            return jsonify({'success': False, 'message': '服务不存在'}), 404
            
        service_path = service_info.get('path')
        # 规范化路径，确保使用一致的分隔符
        service_path = os.path.normpath(service_path) if service_path else None
        
        # 保持原有逻辑：只允许运行中的服务访问配置文件，以确保安全
        if not service_path or service_info.get('status') != '运行中':
            return jsonify({'success': False, 'message': '服务未运行或路径不可用'}), 404
        
        # 确保路径存在
        if not os.path.exists(service_path):
            return jsonify({'success': False, 'message': '服务路径不存在'}), 404
        
        # 查找.ini和.json文件，避免重复
        config_files = []
        seen_files = set()  # 用于跟踪已经添加的文件，防止重复
        
        # 修改逻辑：仅查找服务路径根目录下的文件，不再递归查找子目录
        for file in os.listdir(service_path):
            file_path = os.path.join(service_path, file)
            
            # 只处理文件，跳过子目录
            if os.path.isfile(file_path) and file.lower().endswith(('.ini', '.json',".lua")):
                # 使用绝对路径作为唯一标识符，避免重复
                abs_file_path = os.path.normpath(os.path.abspath(file_path))
                if abs_file_path in seen_files:
                    continue
                    
                seen_files.add(abs_file_path)
                
                # 添加文件信息
                config_files.append({
                    'filename': os.path.basename(file_path),
                    'path': os.path.normpath(file),  # 相对于服务路径的路径（非递归）
                    'full_path': os.path.normpath(file_path)  # 规范化完整路径
                })
    
        return jsonify({'success': True, 'files': config_files})
        
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/config/file/content', methods=['GET'])
def api_get_config_file_content():
    """获取配置文件内容"""
    try:
        file_path = request.args.get('filePath')
        requested_encoding = request.args.get('encoding', 'utf-8') # 获取编码参数，默认为utf-8
        if not file_path:
            return jsonify({'success': False, 'message': '缺少文件路径'}), 400
        
        # 安全检查：确保路径在服务目录内
        abs_file_path = os.path.abspath(file_path)
        # 修改安全检查逻辑：检查文件是否在服务路径下，而不是当前工作目录
        services_status = Service.get_all_service_status()
        valid_paths = []
        for service_info in services_status.values():
            if 'path' in service_info and service_info['path']:
                valid_paths.append(os.path.abspath(service_info['path']))
        
        # 检查文件路径是否在任何一个有效的服务路径下
        is_valid_path = False
        for valid_path in valid_paths:
            if abs_file_path.startswith(valid_path):
                is_valid_path = True
                break
        
        if not is_valid_path:
            return jsonify({'success': False, 'message': '路径访问被拒绝'}), 403
        
        # 检查文件扩展名是否为.ini或.json
        ext = os.path.splitext(file_path)[1].lower()
        if ext not in ['.ini', '.json',".lua"]:
            return jsonify({'success': False, 'message': '只允许访问.ini和.json文件'}), 400
        
        if not os.path.exists(file_path):
            return jsonify({'success': False, 'message': '文件不存在'}), 404
        
        # Call Service function to read content with encoding
        content, actual_encoding = Service.read_file_content(file_path, requested_encoding)
        
        print(f"DEBUG: api_get_config_file_content - Path: {file_path}, Requested Encoding: {requested_encoding}, Actual Encoding: {actual_encoding}, Content-Type Header: text/plain; charset={actual_encoding}, Content (first 50 chars): {content[:50]}")
        return content, 200, {'Content-Type': f'text/plain; charset={actual_encoding}'}
        
    except FileNotFoundError:
        return jsonify({'success': False, 'message': '文件不存在'}), 404
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/config/file/save', methods=['POST'])
def api_save_config_file():
    """保存配置文件内容"""
    try:
        data = request.json
        file_path = data.get('filePath')
        content = data.get('content')
        requested_encoding = data.get('encoding') # Get the encoding parameter
        
        if not file_path or content is None:
            return jsonify({'success': False, 'message': '缺少必要参数'}), 400
        
        # 安全检查：确保路径在服务目录内
        abs_file_path = os.path.abspath(file_path)
        # 修改安全检查逻辑：检查文件是否在服务路径下，而不是当前工作目录
        services_status = Service.get_all_service_status()
        valid_paths = []
        for service_info in services_status.values():
            if 'path' in service_info and service_info['path']:
                valid_paths.append(os.path.abspath(service_info['path']))
        
        is_valid_path = False
        for valid_path in valid_paths:
            if abs_file_path.startswith(valid_path):
                is_valid_path = True
                break
        
        if not is_valid_path:
            return jsonify({'success': False, 'message': '路径访问被拒绝'}), 403
        
        # 检查文件扩展名是否为.ini或.json
        ext = os.path.splitext(file_path)[1].lower()
        if ext not in ['.ini', '.json',".lua"]:
            return jsonify({'success': False, 'message': '只允许保存.ini和.json文件'}), 400
        
        if not os.path.exists(file_path):
            return jsonify({'success': False, 'message': '文件不存在'}), 404
        
        # Call Service function to save content with encoding
        Service.save_file_content(file_path, content, requested_encoding)
        
        return jsonify({'success': True, 'message': '文件保存成功'})
        
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/config/services/running', methods=['GET'])
def api_get_running_config_services():
    """获取正在运行的服务列表，用于配置管理页面"""
    try:
        status = Service.get_all_service_status()
        
        # 读取 config.json 获取 configHide 配置
        config_path = os.path.join(os.getcwd(), 'config.json')
        config_hide = {}
        if os.path.exists(config_path):
            with open(config_path, 'r', encoding='utf-8') as f:
                full_config = json.load(f)
                config_hide = full_config.get('configHide', {})
        
        running_services = {}
        for service_id, service_info in status.items():
            if service_info['status'] == '运行中':
                service_group = service_info.get('name')
                service_type = service_info.get('type')
                
                # 检查服务是否应该被隐藏
                if service_group in config_hide and service_type in config_hide[service_group]:
                    continue # 跳过被隐藏的服务
                
                # 创建服务显示名称：服务组 + 空格 + exe名称
                display_name = f"{service_info['name']} {service_info['exe']}"
                
                # 保留原始信息，但更新名称
                modified_service_info = service_info.copy()
                modified_service_info['name'] = display_name
                modified_service_info['original_name'] = service_group  # 保留原始服务组名称
                modified_service_info['exe_name'] = service_info['exe']        # 保留exe名称
                
                # 直接使用Service.get_all_service_status返回的路径，无需重新计算
                running_services[service_id] = modified_service_info
        
        return jsonify(running_services)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/config/file/branches', methods=['GET'])
def api_get_branch_files():
    """获取文件的所有分支配置文件"""
    try:
        file_path = request.args.get('filePath')
        if not file_path:
            return jsonify({'success': False, 'message': '缺少文件路径'}), 400
        
        # 安全检查：确保路径在服务目录内
        abs_file_path = os.path.abspath(file_path)
        services_status = Service.get_all_service_status()
        valid_paths = []
        for service_info in services_status.values():
            if 'path' in service_info and service_info['path']:
                valid_paths.append(os.path.abspath(service_info['path']))
        
        is_valid_path = False
        for valid_path in valid_paths:
            if abs_file_path.startswith(valid_path):
                is_valid_path = True
                break
        
        if not is_valid_path:
            return jsonify({'success': False, 'message': '路径访问被拒绝'}), 403
        
        if not os.path.exists(file_path):
            return jsonify({'success': False, 'message': '文件不存在'}), 404
        
        # 获取当前文件的基本信息
        dir_path = os.path.dirname(file_path)
        base_filename = os.path.basename(file_path)
        name, ext = os.path.splitext(base_filename)
        
        # 查找同目录下的所有分支文件（以"basename_"开头的文件）
        branch_files = []
        for filename in os.listdir(dir_path):
            if filename.startswith(f"{name}_") and filename.endswith(ext):
                branch_files.append(filename)
        
        # 包含当前文件的信息
        current_file = os.path.basename(file_path)
        
        return jsonify({
            'success': True,
            'current_file': current_file,
            'branch_files': branch_files
        })
        
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/config/file/create_branch', methods=['POST'])
def api_create_branch_file():
    """创建一个新的分支配置文件"""
    try:
        data = request.json
        file_path = data.get('filePath')
        branch_name = data.get('branchName')
        content = data.get('content')  # 新增：接收当前编辑器内容
        
        if not file_path or not branch_name:
            return jsonify({'success': False, 'message': '缺少必要参数'}), 400
        
        # 安全检查：确保路径在服务目录内
        abs_file_path = os.path.abspath(file_path)
        services_status = Service.get_all_service_status()
        valid_paths = []
        for service_info in services_status.values():
            if 'path' in service_info and service_info['path']:
                valid_paths.append(os.path.abspath(service_info['path']))
        
        is_valid_path = False
        for valid_path in valid_paths:
            if abs_file_path.startswith(valid_path):
                is_valid_path = True
                break
        
        if not is_valid_path:
            return jsonify({'success': False, 'message': '路径访问被拒绝'}), 403
        
        if not os.path.exists(file_path):
            return jsonify({'success': False, 'message': '源文件不存在'}), 404
        
        # 构建分支文件路径
        dir_path = os.path.dirname(file_path)
        base_filename = os.path.basename(file_path)
        name, ext = os.path.splitext(base_filename)
        
        # 验证分支名称（不允许特殊字符）
        import re
        if not re.match(r'^[a-zA-Z0-9_-]+$', branch_name):
            return jsonify({'success': False, 'message': '分支名称只能包含字母、数字、下划线和连字符'}), 400
        
        branch_filename = f"{name}_{branch_name}{ext}"
        branch_file_path = os.path.join(dir_path, branch_filename)
        
        # 检查分支文件是否已存在
        if os.path.exists(branch_file_path):
            return jsonify({'success': False, 'message': '分支文件已存在'}), 400
        
        # 如果提供了当前编辑器内容，则使用它；否则复制源文件内容
        if content is not None:
            # 使用当前编辑器中的内容
            file_content = content
        else:
            # 如果没有提供内容，则复制源文件内容（向后兼容）
            with open(file_path, 'r', encoding='utf-8') as src:
                file_content = src.read()
        
        # 写入分支文件
        with open(branch_file_path, 'w', encoding='utf-8') as dst:
            dst.write(file_content)
        
        return jsonify({
            'success': True,
            'message': '分支文件创建成功',
            'branch_file': branch_filename
        })
        
    except UnicodeDecodeError:
        return jsonify({'success': False, 'message': '文件编码错误，请检查文件格式'}), 400
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/config/file/switch_branch', methods=['POST'])
def api_switch_branch_file():
    """切换到指定的分支配置文件"""
    try:
        data = request.json
        file_path = data.get('filePath')
        target_branch = data.get('branchName')
        
        if not file_path or not target_branch:
            return jsonify({'success': False, 'message': '缺少必要参数'}), 400
        
        # 安全检查：确保路径在服务目录内
        abs_file_path = os.path.abspath(file_path)
        services_status = Service.get_all_service_status()
        valid_paths = []
        for service_info in services_status.values():
            if 'path' in service_info and service_info['path']:
                valid_paths.append(os.path.abspath(service_info['path']))
        
        is_valid_path = False
        for valid_path in valid_paths:
            if abs_file_path.startswith(valid_path):
                is_valid_path = True
                break
        
        if not is_valid_path:
            return jsonify({'success': False, 'message': '路径访问被拒绝'}), 403
        
        if not os.path.exists(file_path):
            return jsonify({'success': False, 'message': '主文件不存在'}), 404
        
        # 构建目标分支文件路径
        dir_path = os.path.dirname(file_path)
        base_filename = os.path.basename(file_path)
        name, ext = os.path.splitext(base_filename)
        
        target_file_path = os.path.join(dir_path, f"{name}_{target_branch}{ext}")
        
        if not os.path.exists(target_file_path):
            return jsonify({'success': False, 'message': '目标分支文件不存在'}), 404
        
        # 移动当前文件到remove文件夹
        remove_dir = os.path.join(dir_path, 'remove')
        if not os.path.exists(remove_dir):
            os.makedirs(remove_dir)
        
        import shutil
        removed_file_path = os.path.join(remove_dir, base_filename)
        
        # 移动当前文件到remove目录（先备份）
        try:
            shutil.move(file_path, removed_file_path)
        except Exception as e:
            return jsonify({'success': False, 'message': f'备份原文件失败: {str(e)}'}), 500
        
        # 将目标分支文件复制回原位置
        try:
            shutil.copy2(target_file_path, file_path)
            
            # 确认文件复制成功
            if not os.path.exists(file_path):
                # 如果复制失败，尝试恢复原文件
                shutil.move(removed_file_path, file_path)
                return jsonify({'success': False, 'message': '切换分支失败：无法创建目标文件'}), 500
        except Exception as e:
            # 如果复制失败，恢复原文件
            shutil.move(removed_file_path, file_path)
            return jsonify({'success': False, 'message': f'复制分支文件失败: {str(e)}'}), 500
        
        # 额外验证：确认目标文件内容已正确写入
        try:
            with open(file_path, 'rb') as f_target, open(target_file_path, 'rb') as f_source:
                if f_target.read() != f_source.read():
                    # 如果内容不匹配，恢复原文件
                    shutil.move(removed_file_path, file_path)
                    return jsonify({'success': False, 'message': '切换分支失败：文件内容验证失败'}), 500
        except Exception as e:
            return jsonify({'success': False, 'message': f'文件验证失败: {str(e)}'}), 500
        
        return jsonify({
            'success': True,
            'message': '分支切换成功',
            'current_file': base_filename
        })
        
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/config/file/remove_branch', methods=['DELETE'])
def api_remove_branch_file():
    """删除指定的分支配置文件"""
    try:
        file_path = request.args.get('filePath')
        branch_name = request.args.get('branchName')
        
        if not file_path or not branch_name:
            return jsonify({'success': False, 'message': '缺少必要参数'}), 400
        
        # 安全检查：确保路径在服务目录内
        abs_file_path = os.path.abspath(file_path)
        services_status = Service.get_all_service_status()
        valid_paths = []
        for service_info in services_status.values():
            if 'path' in service_info and service_info['path']:
                valid_paths.append(os.path.abspath(service_info['path']))
        
        is_valid_path = False
        for valid_path in valid_paths:
            if abs_file_path.startswith(valid_path):
                is_valid_path = True
                break
        
        if not is_valid_path:
            return jsonify({'success': False, 'message': '路径访问被拒绝'}), 403
        
        if not os.path.exists(file_path):
            return jsonify({'success': False, 'message': '主文件不存在'}), 404
        
        # 构建要删除的分支文件路径
        dir_path = os.path.dirname(file_path)
        base_filename = os.path.basename(file_path)
        name, ext = os.path.splitext(base_filename)
        
        branch_file_path = os.path.join(dir_path, f"{name}_{branch_name}{ext}")
        
        if not os.path.exists(branch_file_path):
            return jsonify({'success': False, 'message': '分支文件不存在'}), 404
        
        # 删除分支文件
        os.remove(branch_file_path)
        
        return jsonify({
            'success': True,
            'message': '分支文件删除成功'
        })
        
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500
    

import requests
from bs4 import BeautifulSoup

from datetime import datetime, timedelta

def get_latest_bg_info():
    """扫描所有背景图目录，返回日期最新的背景图信息"""
    user_bg_dir = os.path.join(os.getcwd(), 'src', 'background')
    cache_dir = os.path.join(os.getcwd(), 'src', 'cache', 'backgrounds')
    
    bg_files = []
    
    # 扫描用户目录 (格式: YYYYMMDD.webp)
    if os.path.exists(user_bg_dir):
        for f in os.listdir(user_bg_dir):
            if f.endswith('.webp') and len(f) == 13: # 20260305.webp
                date_str = f[:8]
                if date_str.isdigit():
                    bg_files.append({
                        'path': os.path.join(user_bg_dir, f),
                        'url': f"/static/background/{f}",
                        'date': date_str,
                        'size': os.path.getsize(os.path.join(user_bg_dir, f))
                    })
                    
    # 扫描缓存目录 (格式: bg_YYYYMMDD.webp)
    if os.path.exists(cache_dir):
        for f in os.listdir(cache_dir):
            if f.startswith('bg_') and f.endswith('.webp'):
                date_str = f[3:11]
                if date_str.isdigit():
                    bg_files.append({
                        'path': os.path.join(cache_dir, f),
                        'url': f"/static/cache/backgrounds/{f}",
                        'date': date_str,
                        'size': os.path.getsize(os.path.join(cache_dir, f))
                    })
                    
    if not bg_files:
        return None
        
    # 按日期降序排序，返回最新的
    bg_files.sort(key=lambda x: x['date'], reverse=True)
    return bg_files[0]

def get_daily_bg_filename():
    """重构后的逻辑：优先返回最新的背景图，如果没有则返回预设的路径用于抓取"""
    latest = get_latest_bg_info()
    if latest:
        return latest['path'], latest['url'], latest['date']
        
    # 如果完全没有背景图，返回默认的今日日期路径
    target_date = datetime.now().strftime('%Y%m%d')
    cache_dir = os.path.join(os.getcwd(), 'src', 'cache', 'backgrounds')
    if not os.path.exists(cache_dir): os.makedirs(cache_dir)
    return os.path.join(cache_dir, f"bg_{target_date}.webp"), f"/static/cache/backgrounds/bg_{target_date}.webp", target_date

import re
from playwright.sync_api import sync_playwright

@app.route('/api/fetch-background', methods=['GET'])
def api_fetch_background():
    """抓取背景图：仅在无背景图或强制刷新时爬取"""
    force = request.args.get('force', 'false').lower() == 'true'
    latest_bg = get_latest_bg_info()

    # 判断是否需要执行爬取逻辑
    should_crawl = False
    if not latest_bg:
        should_crawl = True
    elif force:
        should_crawl = True

    # 如果不需要爬取，直接返回最新的图
    if not should_crawl and latest_bg:
        return jsonify({'success': True, 'bg_url': latest_bg['url'], 'cached': True, 'date': latest_bg['date']})
    
    try:
        friendlink_path = os.path.join(os.getcwd(), 'src', 'extern', 'friendlink.json')
        spider_url = None
        if os.path.exists(friendlink_path):
            with open(friendlink_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                spider_url = data.get('spiderUrl')
        
        fallback_bg = "https://webstatic.mihoyo.com/upload/op-public/2023/04/18/744005e8e34898495944517351119572_7718912217696144990.jpg"
        if not spider_url:
            return jsonify({'success': True, 'bg_url': fallback_bg})

        bg_url = None
        
        # 1. 使用 Playwright 模拟浏览器抓取
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            )
            page = context.new_page()
            page.set_default_timeout(15000)
            
            try:
                page.goto(spider_url, wait_until="networkidle")
                page.wait_for_timeout(2000)
                
                bg_url = page.evaluate(r'''() => {
                    const imageCandidates = [];
                    document.querySelectorAll('img').forEach(img => {
                        if (img.src && img.src.startsWith('http')) {
                            imageCandidates.push({
                                url: img.src,
                                area: img.naturalWidth * img.naturalHeight
                            });
                        }
                    });
                    document.querySelectorAll('*').forEach(el => {
                        const style = window.getComputedStyle(el);
                        const bgImg = style.backgroundImage;
                        if (bgImg && bgImg !== 'none' && bgImg.includes('url')) {
                            const match = bgImg.match(/url\("?(.+?)"?\)/);
                            if (match) {
                                let url = match[1];
                                if (url.startsWith('//')) url = window.location.protocol + url;
                                if (!url.startsWith('http')) url = new URL(url, document.baseURI).href;
                                const rect = el.getBoundingClientRect();
                                imageCandidates.push({ url: url, area: rect.width * rect.height });
                            }
                        }
                    });
                    const largeImages = imageCandidates.filter(item => item.area > 40000);
                    if (largeImages.length === 0) return null;
                    largeImages.sort((a, b) => {
                        const aHas = a.url.includes('mihoyo') || a.url.includes('cloudgame');
                        const bHas = b.url.includes('mihoyo') || b.url.includes('cloudgame');
                        if (aHas && !bHas) return -1;
                        if (!aHas && bHas) return 1;
                        return b.area - a.area;
                    });
                    return largeImages[0].url;
                }''')
            except Exception as pe:
                print(f"Playwright error: {pe}")
            finally:
                browser.close()

        # 2. 如果找到了 URL，下载并比对大小
        if bg_url:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Referer': spider_url
            }
            try:
                img_res = requests.get(bg_url, headers=headers, timeout=10)
                if img_res.status_code == 200:
                    new_content = img_res.content
                    new_size = len(new_content)
                    
                    # 比对大小
                    if latest_bg and new_size == latest_bg['size'] and not force:
                        print(f"背景图大小相同 ({new_size})，跳过保存。")
                        return jsonify({'success': True, 'bg_url': latest_bg['url'], 'cached': True, 'date': latest_bg['date']})
                    
                    # 保存新图
                    cache_dir = os.path.join(os.getcwd(), 'src', 'cache', 'backgrounds')
                    if not os.path.exists(cache_dir): os.makedirs(cache_dir)
                    today_str = datetime.now().strftime('%Y%m%d')
                    new_filename = f"bg_{today_str}.webp"
                    new_path = os.path.join(cache_dir, new_filename)
                    new_static_url = f"/static/cache/backgrounds/{new_filename}"
                    
                    with open(new_path, 'wb') as f:
                        f.write(new_content)
                    
                    return jsonify({
                        'success': True, 
                        'bg_url': new_static_url, 
                        'cached': False, 
                        'date': today_str,
                        'size_changed': True
                    })
            except Exception as e:
                print(f"下载背景图失败: {str(e)}")
        
        # 兜底返回
        if latest_bg:
            return jsonify({'success': True, 'bg_url': latest_bg['url'], 'cached': True, 'date': latest_bg['date'], 'error': '抓取失败，返回旧图'})
        return jsonify({'success': True, 'bg_url': fallback_bg, 'error': '抓取失败且无旧图'})
            
    except Exception as e:
        print(f"背景图抓取重大失败: {str(e)}")
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/friendlinks', methods=['GET'])
def api_get_friendlinks():
    """获取友链数据"""
    try:
        friendlink_path = os.path.join(os.getcwd(), 'src', 'extern', 'friendlink.json')
        
        if not os.path.exists(friendlink_path):
            return jsonify({'success': True, 'friendlinks': []}) # 文件不存在则返回空列表
        
        with open(friendlink_path, 'r', encoding='utf-8') as f:
            loaded_data = json.load(f)
        
        # 从加载的数据中提取 'friendlink' 数组，如果不存在则默认为空列表
        friendlinks = loaded_data.get('friendlink', [])
        
        return jsonify({'success': True, 'friendlinks': friendlinks})
        
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

import hashlib

def get_cached_icon_path(url):
    """根据URL生成缓存图标路径"""
    cache_dir = os.path.join(os.getcwd(), 'src', 'cache', 'icons')
    if not os.path.exists(cache_dir):
        os.makedirs(cache_dir)
    
    # 使用URL的MD5作为文件名
    url_hash = hashlib.md5(url.encode('utf-8')).hexdigest()
    # 我们暂时不确定后缀，先返回基础路径
    return os.path.join(cache_dir, url_hash), url_hash

@app.route('/api/fetch-metadata', methods=['GET'])
def api_fetch_metadata():
    """根据URL抓取页面标题和图标，支持本地缓存和深度优化"""
    url = request.args.get('url')
    if not url:
        return jsonify({'success': False, 'message': '缺少URL参数'}), 400
    
    # 确保URL有协议
    if not url.startswith(('http://', 'https://')):
        url = 'http://' + url
        
    try:
        # 1. 检查缓存
        cache_base_path, url_hash = get_cached_icon_path(url)
        # 尝试查找已存在的任何扩展名的文件
        cached_file = None
        # 扩展支持 webp
        for ext in ['.png', '.jpg', '.jpeg', '.ico', '.svg', '.webp']:
            if os.path.exists(cache_base_path + ext):
                cached_file = f"/static/cache/icons/{url_hash}{ext}"
                break
        
        # 即使有缓存，我们依然抓取页面以获取最新的标题
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
            'Referer': url # 使用当前 URL 作为 Referer 绕过某些防盗链
        }
        
        title = None
        favicon_url = None

        try:
            response = requests.get(url, headers=headers, timeout=5, verify=False) # 忽略 SSL 错误，防止部分站点无法访问
            response.raise_for_status()
            response.encoding = response.apparent_encoding
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # 抓取标题
            if soup.title and soup.title.string:
                title = soup.title.string.strip()
            
            if not title:
                # 尝试从 og:title, twitter:title 获取
                meta_title = soup.find('meta', property='og:title') or soup.find('meta', name='twitter:title')
                if meta_title:
                    title = meta_title.get('content')
            
            if not title:
                # 尝试抓取第一个 H1
                h1 = soup.find('h1')
                if h1:
                    title = h1.get_text().strip()

            # 如果已经有缓存图标，且抓取到了标题，就直接返回
            if cached_file and title:
                return jsonify({
                    'success': True, 
                    'title': title,
                    'favicon': cached_file,
                    'cached': True
                })

            # 抓取图标逻辑
            icon_tags = []
            icon_tags.extend(soup.find_all('link', rel=lambda x: x and ('icon' in x.lower() or 'apple-touch-icon' in x.lower())))
            
            # 针对部分站点增加 meta 标签抓取
            tile_image = soup.find('meta', name='msapplication-TileImage')
            if tile_image:
                icon_tags.append(tile_image)

            best_icon = None
            max_size = 0
            
            for tag in icon_tags:
                href = tag.get('href') or tag.get('content')
                if not href: continue
                
                current_score = 1
                rel = str(tag.get('rel', '')).lower()
                if 'apple-touch-icon' in rel: current_score += 10
                if '.png' in href.lower(): current_score += 5
                
                # 检查尺寸
                sizes = tag.get('sizes', '')
                if sizes and 'x' in sizes:
                    try:
                        size = int(sizes.split('x')[0])
                        if size > max_size:
                            max_size = size
                            current_score += size // 10
                    except: pass
                
                if not best_icon or current_score > best_icon['score']:
                    best_icon = {'href': href, 'score': current_score}
            
            if best_icon:
                favicon_url = best_icon['href']
                from urllib.parse import urljoin
                if not favicon_url.startswith(('http://', 'https://')):
                    favicon_url = urljoin(url, favicon_url)

        except Exception as crawl_err:
            print(f"爬取页面失败 ({url}): {str(crawl_err)}")
            # 爬取失败时，如果已经有缓存，依然返回缓存
            if cached_file:
                return jsonify({
                    'success': True, 
                    'title': title or url,
                    'favicon': cached_file,
                    'cached': True
                })

        # 兜底方案：尝试域名根目录的 favicon.ico
        if not favicon_url:
            from urllib.parse import urlparse
            parsed_url = urlparse(url)
            favicon_url = f"{parsed_url.scheme}://{parsed_url.netloc}/favicon.ico"

        # 下载并保存图标
        if not cached_file:
            try:
                icon_res = requests.get(favicon_url, headers=headers, timeout=5, verify=False)
                if icon_res.status_code == 200:
                    content_type = icon_res.headers.get('Content-Type', '').lower()
                    ext = '.png'
                    if 'image/x-icon' in content_type or 'vnd.microsoft.icon' in content_type: ext = '.ico'
                    elif 'image/jpeg' in content_type: ext = '.jpg'
                    elif 'image/svg' in content_type: ext = '.svg'
                    elif 'image/gif' in content_type: ext = '.gif'
                    elif 'image/webp' in content_type: ext = '.webp'
                    
                    with open(cache_base_path + ext, 'wb') as f:
                        f.write(icon_res.content)
                    cached_file = f"/static/cache/icons/{url_hash}{ext}"
            except Exception as e:
                print(f"下载图标失败 ({favicon_url}): {str(e)}")

        return jsonify({
            'success': True, 
            'title': title or url,
            'favicon': cached_file or favicon_url,
            'cached': False
        })
    except Exception as e:
        print(f"抓取元数据重大失败 ({url}): {str(e)}")
        return jsonify({'success': False, 'message': f'抓取失败: {str(e)}'}), 500

@app.route('/api/fetch-title', methods=['GET'])
def api_fetch_title():
    """根据URL抓取页面标题"""
    url = request.args.get('url')
    if not url:
        return jsonify({'success': False, 'message': '缺少URL参数'}), 400
    
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3'}
        response = requests.get(url, headers=headers, timeout=5)
        response.raise_for_status() # 检查HTTP请求是否成功
        
        soup = BeautifulSoup(response.text, 'html.parser')
        title = soup.title.string if soup.title else url # 如果没有title标签，则使用URL作为标题
        
        return jsonify({'success': True, 'title': title})
    except requests.exceptions.RequestException as e:
        return jsonify({'success': False, 'message': f'请求URL失败: {str(e)}'}), 500
    except Exception as e:
        return jsonify({'success': False, 'message': f'抓取标题失败: {str(e)}'}), 500
    


# ==================== 做牌接口 (makedeal) ====================
# 移植自 svn scriptTools/serviceServer CustomRoute/ServiceRoute.py (caiyf: r58900/r59114/r59912),
# 写入 D:/game/zgdb/server_assist/makedeal.json (路径取 config.json 的 makedealFilePath)。

@app.route('/api/makedeal/start', methods=['POST'])
def api_makedeal_start():
    """写入发牌配置到 makedeal.json 的 StartDeal 字段"""
    try:
        data = request.get_json(silent=True)
        if not data or not isinstance(data, dict):
            return jsonify({'success': False, 'message': '请求体不是合法 JSON'}), 400

        # 必填字段检查（仅 Chair0/1/2/Bottom/Total）
        required_fields = ['Chair0', 'Chair1', 'Chair2', 'Bottom', 'Total']
        for field in required_fields:
            if field not in data:
                return jsonify({'success': False, 'message': f'缺少必填字段: {field}'}), 400

        # 牌号字段：必须是 '|' 分隔的整数字符串，每个牌号在 0-53 范围内
        card_fields = ['Chair0', 'Chair1', 'Chair2', 'Bottom', 'Total']

        parsed_cards = {}  # field -> [int, ...]
        for field in card_fields:
            value = data[field]
            if not isinstance(value, str) or not value:
                return jsonify({'success': False, 'message': f'{field} 必须是非空字符串'}), 400

            parts = value.split('|')
            cards = []
            for p in parts:
                try:
                    n = int(p)
                except ValueError:
                    return jsonify({'success': False, 'message': f'{field} 中包含非整数: {p}'}), 400
                if n < 0 or n > 53:
                    return jsonify({'success': False, 'message': f'{field} 中牌号超出范围(0-53): {n}'}), 400
                cards.append(n)

            # 单个字段内部不应有重复
            if len(cards) != len(set(cards)):
                return jsonify({'success': False, 'message': f'{field} 中存在重复牌号'}), 400

            parsed_cards[field] = cards

        # 检查 Chair0/Chair1/Chair2/Bottom 互不重叠
        combined = parsed_cards['Chair0'] + parsed_cards['Chair1'] + parsed_cards['Chair2'] + parsed_cards['Bottom']
        if len(combined) != len(set(combined)):
            return jsonify({'success': False, 'message': 'Chair0/Chair1/Chair2/Bottom 之间存在重复牌号'}), 400

        # 检查 Total 与 Chair0+Chair1+Chair2+Bottom 集合相等（不要求顺序一致）
        if set(parsed_cards['Total']) != set(combined):
            return jsonify({'success': False, 'message': 'Total 的牌号集合与 Chair0+Chair1+Chair2+Bottom 不一致'}), 400
        if len(parsed_cards['Total']) != len(combined):
            return jsonify({'success': False, 'message': 'Total 的牌号数量与 Chair0+Chair1+Chair2+Bottom 不一致'}), 400

        # 构建写入数据
        write_data = {
            'ReadCardsFromFile': 1,  # 固定为 1（启用从文件读牌）
            'Chair0': data['Chair0'],
            'Chair1': data['Chair1'],
            'Chair2': data['Chair2'],
            'Bottom': data['Bottom'],
            'Total': data['Total'],
        }

        # RazzValue 和 Banker 是可选字段，如果提供则使用，否则不写入
        if 'RazzValue' in data:
            if not isinstance(data['RazzValue'], int):
                return jsonify({'success': False, 'message': 'RazzValue 必须是整数'}), 400
            write_data['RazzValue'] = data['RazzValue']

        if 'Banker' in data:
            if not isinstance(data['Banker'], int):
                return jsonify({'success': False, 'message': 'Banker 必须是整数'}), 400
            write_data['Banker'] = data['Banker']

        # RandomReject 是可选字段，如果提供则必须是整数
        if 'randomReject' in data:
            if not isinstance(data['randomReject'], int):
                return jsonify({'success': False, 'message': 'randomReject 必须是整数'}), 400
            write_data['RandomReject'] = data['randomReject']

        # roomId 是可选字段，如果提供则必须是正整数
        if 'roomId' in data:
            if not isinstance(data['roomId'], int):
                return jsonify({'success': False, 'message': 'roomId 必须是整数'}), 400
            if data['roomId'] <= 0:
                return jsonify({'success': False, 'message': 'roomId 必须是正整数'}), 400

        # 读取 makedealFilePath
        config = JsonConfigParser.read_config()
        makedeal_file_path = config.get('makedealFilePath')
        if not makedeal_file_path:
            return jsonify({'success': False, 'message': 'config.json 中未配置 makedealFilePath'}), 400

        # 规范化路径
        makedeal_file_path = os.path.normpath(makedeal_file_path)

        # 读取或新建 makedeal.json
        existing_data = {}
        if os.path.exists(makedeal_file_path):
            try:
                with open(makedeal_file_path, 'r', encoding='utf-8') as f:
                    existing_data = json.load(f)
            except (json.JSONDecodeError, Exception) as e:
                return jsonify({'success': False, 'message': f'读取 makedeal.json 失败: {str(e)}'}), 500

        # 根据是否有 roomId 决定写入的字段名
        if 'roomId' in data:
            field_name = f'StartDeal_{data["roomId"]}'
        else:
            field_name = 'StartDeal'

        existing_data[field_name] = write_data

        # 写入文件
        os.makedirs(os.path.dirname(makedeal_file_path), exist_ok=True)
        with open(makedeal_file_path, 'w', encoding='utf-8') as f:
            json.dump(existing_data, f, ensure_ascii=False, indent=4)

        return jsonify({'success': True, 'message': '发牌配置写入成功'})

    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/makedeal/randomReject', methods=['GET'])
def api_makedeal_random_reject():
    """单独修改 makedeal.json 中 StartDeal_{roomId}.RandomReject 字段；不存在则用默认值新建"""
    try:
        # 参数校验
        room_id_raw = request.args.get('roomId')
        value_raw = request.args.get('value')
        if room_id_raw is None:
            return jsonify({'success': False, 'message': '缺少必填参数: roomId'}), 400
        if value_raw is None:
            return jsonify({'success': False, 'message': '缺少必填参数: value'}), 400

        try:
            room_id = int(room_id_raw)
        except (ValueError, TypeError):
            return jsonify({'success': False, 'message': 'roomId 必须是整数'}), 400
        if room_id <= 0:
            return jsonify({'success': False, 'message': 'roomId 必须是正整数'}), 400

        try:
            value = int(value_raw)
        except (ValueError, TypeError):
            return jsonify({'success': False, 'message': 'value 必须是整数'}), 400

        # 读取 makedealFilePath
        config = JsonConfigParser.read_config()
        makedeal_file_path = config.get('makedealFilePath')
        if not makedeal_file_path:
            return jsonify({'success': False, 'message': 'config.json 中未配置 makedealFilePath'}), 400

        # 规范化路径
        makedeal_file_path = os.path.normpath(makedeal_file_path)

        # 读取或新建 makedeal.json
        existing_data = {}
        if os.path.exists(makedeal_file_path):
            try:
                with open(makedeal_file_path, 'r', encoding='utf-8') as f:
                    existing_data = json.load(f)
            except (json.JSONDecodeError, Exception) as e:
                return jsonify({'success': False, 'message': f'读取 makedeal.json 失败: {str(e)}'}), 500

        field_name = f'StartDeal_{room_id}'
        # 不存在则用默认值新建（ReadCardsFromFile=0，牌号字段为空字符串）
        if field_name not in existing_data or not isinstance(existing_data[field_name], dict):
            existing_data[field_name] = {
                'ReadCardsFromFile': 0,
                'Chair0': '',
                'Chair1': '',
                'Chair2': '',
                'Bottom': '',
                'Total': '',
            }

        # 只更新 RandomReject，其它字段保持不变
        existing_data[field_name]['RandomReject'] = value

        # 写入文件
        os.makedirs(os.path.dirname(makedeal_file_path), exist_ok=True)
        with open(makedeal_file_path, 'w', encoding='utf-8') as f:
            json.dump(existing_data, f, ensure_ascii=False, indent=4)

        return jsonify({'success': True, 'message': 'RandomReject 更新成功'})

    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

