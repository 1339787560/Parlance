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

