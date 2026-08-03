from flask import render_template, render_template_string, request, jsonify, send_file
from flask_cors import CORS # 导入 CORS
import subprocess
# 修改导入方式，避免使用import *
import sys
import time
import Service
import JsonConfigParser
import json
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
    """热更新服务：停止 → 等待进程退出 → 启动。文件已在本地（SVN update 或手动替换），不需要上传。"""
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

@app.route('/api/svn/status', methods=['GET'])
def api_get_svn_status():
    try:
        is_latest, message = Service.get_svn_status()
        return jsonify({'success': True, 'is_latest': is_latest, 'message': message})
    except Exception as e:
        return jsonify({'success': False, 'message': f'获取SVN状态失败: {str(e)}'}), 500

@app.route('/api/svn/update', methods=['POST'])
def api_update_svn():
    try:
        success, message = Service.update_svn()
        return jsonify({'success': success, 'message': message})
    except Exception as e:
        return jsonify({'success': False, 'message': f'执行SVN更新失败: {str(e)}'}), 500

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

@app.route('/api/serverstatus/get', methods=['GET'])
def api_serverstatus_get():
    """获取服务器状态信息"""
    try:
        # 获取系统状态
        system_data = get_system_status()
        
        # 获取当前Python进程状态
        python_data = get_python_process_status()
        
        return jsonify({
            'success': True,
            'system': system_data,
            'python': python_data
        })
        
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

def get_system_status():
    """获取系统状态信息"""
    # CPU使用率
    cpu_percent = Service.psutil.cpu_percent(interval=1)
    
    # 内存信息
    memory = Service.psutil.virtual_memory()
    memory_used = memory.used
    memory_total = memory.total
    
    # 进程、线程、句柄数
    process_count = len(Service.psutil.pids())
    thread_count = sum([p.num_threads() for p in Service.psutil.process_iter() if p.is_running()])
    
    # 磁盘信息
    disk = Service.psutil.disk_usage('/')
    disk_used = disk.used
    disk_total = disk.total
    
    # 网络信息
    net_io = Service.psutil.net_io_counters()
    network_receive_rate = net_io.bytes_recv
    network_send_rate = net_io.bytes_sent
    
    # 磁盘IO信息
    disk_io = Service.psutil.disk_io_counters()
    disk_read_rate = disk_io.read_bytes
    disk_write_rate = disk_io.write_bytes
    
    return {
        'cpu_percent': cpu_percent,
        'memory_used': memory_used,
        'memory_total': memory_total,
        'process_count': process_count,
        'thread_count': thread_count,
        'handle_count': 0,  # Windows上没有全局句柄数的直接API
        'disk_used': disk_used,
        'disk_total': disk_total,
        'network_receive_rate': network_receive_rate,
        'network_send_rate': network_send_rate,
        'disk_read_rate': disk_read_rate,
        'disk_write_rate': disk_write_rate
    }

def get_python_process_status():
    """获取当前Python进程状态信息"""
    current_process = Service.psutil.Process(os.getpid())
    
    # CPU使用率
    cpu_percent = current_process.cpu_percent()
    
    # 内存使用
    memory_info = current_process.memory_info()
    memory_used = memory_info.rss
    memory_total = Service.psutil.virtual_memory().total  # 总内存
    
    # 进程、线程、句柄数
    process_count = 1  # 当前进程
    thread_count = current_process.num_threads()
    handle_count = current_process.num_handles() if hasattr(current_process, 'num_handles') else 0
    
    # 磁盘使用 - 获取工作目录磁盘信息
    disk = Service.psutil.disk_usage(os.getcwd())
    disk_used = disk.used
    disk_total = disk.total
    
    # 网络信息 - 当前进程的网络使用
    # 由于Python进程可能没有网络连接，我们使用系统网络信息
    net_io = Service.psutil.net_io_counters()
    network_receive_rate = net_io.bytes_recv
    network_send_rate = net_io.bytes_sent
    
    # 磁盘IO信息 - 当前进程的磁盘IO
    try:
        io_counters = current_process.io_counters()
        disk_read_rate = io_counters.read_bytes
        disk_write_rate = io_counters.write_bytes
    except:
        disk_read_rate = 0
        disk_write_rate = 0
    
    return {
        'cpu_percent': cpu_percent,
        'memory_used': memory_used,
        'memory_total': memory_total,
        'process_count': process_count,
        'thread_count': thread_count,
        'handle_count': handle_count,
        'disk_used': disk_used,
        'disk_total': disk_total,
        'network_receive_rate': network_receive_rate,
        'network_send_rate': network_send_rate,
        'disk_read_rate': disk_read_rate,
        'disk_write_rate': disk_write_rate
    }

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

@app.route('/api/serverstatus/stop', methods=['POST'])
def api_serverstatus_stop():
    """停止当前服务"""
    try:
        # 在新线程中执行停止操作，避免阻塞当前请求
        def stop_service():
            Service.time.sleep(1)  # 给客户端响应时间
            os._exit(0)  # 立即退出
        
        thread = threading.Thread(target=stop_service)
        thread.daemon = True
        thread.start()
        
        return jsonify({'success': True, 'message': '停止服务命令已发送'})
        
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/serverstatus/restart', methods=['POST'])
def api_serverstatus_restart():
    """重启当前服务"""
    try:
        # 在新线程中执行重启操作，避免阻塞当前请求
        def restart_service():
            Service.time.sleep(1)  # 给客户端响应时间
            import subprocess
            subprocess.Popen(['python', 'main.py'])  # 重新启动main.py
            os._exit(0)  # 立即退出当前进程
        
        thread = threading.Thread(target=restart_service)
        thread.daemon = True
        thread.start()
        
        return jsonify({'success': True, 'message': '重启服务命令已发送'})
        
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500
    
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
    

import platform
import subprocess
import time

@app.route('/api/system/restart', methods=['POST'])
def api_restart_system():
    """重启系统"""
    try:
        system = platform.system()
        
        if system == "Windows":
            # Windows系统使用多种方法尝试重启
            # 首先尝试使用ctypes调用Windows API，这种方法在某些情况下更有效
            import ctypes
            import ctypes.wintypes
            
            # 获取当前进程的令牌
            try:
                token = ctypes.wintypes.HANDLE()
                token_privileges = ctypes.wintypes.DWORD()
                
                # 尝试通过Windows API发起重启
                if ctypes.windll.advpack.ShellExecuteW(None, "runas", "shutdown", "/r /t 0 /f", None, 1) > 32:
                    return jsonify({'success': True, 'message': '系统正在重启...'})
            except:
                pass  # 如果API调用失败，继续尝试其他方法
            
            # 方法1: 使用shutdown命令
            try:
                result = subprocess.run(
                    ["shutdown", "/r", "/t", "0", "/f"],  # 添加/f参数强制关闭运行的应用程序
                    capture_output=True, 
                    text=True,
                    timeout=10
                )
                if result.returncode == 0:
                    return jsonify({'success': True, 'message': '系统正在重启...'})
            except:
                pass  # 忽略异常，继续尝试其他方法
            
            # 方法2: 使用PowerShell
            try:
                result = subprocess.run(
                    ["powershell", "-Command", "Restart-Computer -Force"], 
                    capture_output=True, 
                    text=True,
                    timeout=10
                )
                if result.returncode == 0:
                    return jsonify({'success': True, 'message': '系统正在重启...'})
            except:
                pass  # 忽略异常，继续尝试其他方法
            
            # 方法3: 使用wmic
            try:
                result = subprocess.run(
                    ["wmic", "os", "where", "primary='true'", "call", "reboot"], 
                    capture_output=True, 
                    text=True,
                    timeout=10
                )
                if result.returncode == 0 or "ReturnValue = 0;" in result.stdout:
                    return jsonify({'success': True, 'message': '系统正在重启...'})
            except:
                pass  # 忽略异常，继续尝试其他方法
            
            # 如果所有方法都失败，返回错误
            return jsonify({'success': False, 'message': '无法执行重启命令，请确保以管理员身份运行此服务'}), 500
            
        elif system == "Linux" or system == "Darwin":  # Darwin是macOS
            # Linux/macOS系统使用reboot命令
            try:
                result = subprocess.run(
                    ["sudo", "reboot"], 
                    capture_output=True, 
                    text=True,
                    timeout=10
                )
                if result.returncode == 0:
                    return jsonify({'success': True, 'message': '系统正在重启...'})
                else:
                    return jsonify({'success': False, 'message': f'重启命令执行失败: {result.stderr}'}), 500
            except Exception as e:
                return jsonify({'success': False, 'message': f'重启系统时发生错误: {str(e)}'}), 500
        else:
            return jsonify({'success': False, 'message': f'不支持的操作系统: {system}'}), 400

    except Exception as e:
        return jsonify({'success': False, 'message': f'重启系统时发生错误: {str(e)}'}), 500

