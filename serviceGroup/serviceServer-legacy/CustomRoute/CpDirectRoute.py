# -*- coding: utf-8 -*-
"""CP 直连查询路由（只读）— deposit 页 Creator 组「CP 数据」tab 的后端。

与 CpDataRoute.py 的区别（2026-09 改版）：
    旧  /api/cp-data/*      借道 125 环境 exec_script；client_request 还依赖 db9 五元组
                            (mod(pick):halllogon)。该通路 2026-08-17 事故后整体 503。
    新  /api/cp-data/direct/*  直连 CP 自己的 MySQL(modsvr283db) + redis(db10)，
                            不触 125、不读 db9、不依赖玩家是否登录过 —— 因此不会再
                            产生「无五元组记录」这类报错。

安全边界：本模块只读。mysql 仅 SELECT/COUNT，redis 仅 SCAN/TYPE/GET/HGETALL/
LRANGE/SMEMBERS/ZRANGE（见 CpUserData）。没有写端点 —— 若将来要开放改写，请沿用旧
CpDataRoute 受控写纪律（模块白名单 + key 归属校验 + 写前 redis/mysql 双快照），
不要在本模块直接开裸写。
"""
from flask import request, jsonify

from CommonTools.xzmpDB import CpUserData
from . import app

# 独立总开关（与旧 CpDataRoute.CP_ENABLED 解耦：旧通路停用不影响本通路）
CP_DIRECT_ENABLED = True

# 写开关：与只读查询解耦。出问题时单独关写、保留查 —— 排查期最有用的那一档。
CP_DIRECT_WRITE_ENABLED = True

MAX_USERID = 2 ** 31 - 1


def _parse_userid(raw):
    """解析并校验玩家ID。返回 (userid, err_response)。"""
    try:
        uid = int(raw)
    except (TypeError, ValueError):
        return None, (jsonify({'success': False, 'message': '玩家ID格式错误'}), 400)
    if uid <= 0 or uid > MAX_USERID:
        return None, (jsonify({'success': False, 'message': '玩家ID超出范围'}), 400)
    return uid, None


def _parse_appcode(raw):
    """解析并校验缩写（小写字母数字下划线）。返回 (appcode, err_response)。"""
    appcode = (raw or '').strip().lower()
    if not appcode:
        return None, (jsonify({'success': False, 'message': '缩写不能为空'}), 400)
    if not CpUserData._IDENT_RE.match(appcode):  # noqa: SLF001 —— 复用同一套标识符白名单
        return None, (jsonify({'success': False,
                               'message': '缩写格式错误（仅小写字母/数字/下划线）'}), 400)
    return appcode, None


@app.route('/api/cp-data/direct/appcodes', methods=['GET', 'POST'])
def api_cp_direct_appcodes():
    """可用缩写清单（从落盘表名派生）。无参数。"""
    if not CP_DIRECT_ENABLED:
        return jsonify({'success': False, 'message': 'CP 直连查询已关闭'}), 503
    try:
        return jsonify({'success': True, 'data': {'appcodes': CpUserData.list_appcodes()}})
    except Exception as e:  # noqa: BLE001
        return jsonify({'success': False, 'message': f'缩写清单获取失败: {e}'}), 500


@app.route('/api/cp-data/direct/modules', methods=['POST'])
def api_cp_direct_modules():
    """按 玩家ID + 缩写 列该玩家相关模块。

    body: {userid, appcode}
    返回 data: {userid, appcode, modules:[{module, redis_keys, redis_count,
                 mysql_table, mysql_rows}], warnings}
    模块并集口径：redis 有 key 或 mysql 有行即列出 —— 「缓存已过期只剩落盘」与
    「只有缓存未落盘」两种不一致都可见。
    """
    if not CP_DIRECT_ENABLED:
        return jsonify({'success': False, 'message': 'CP 直连查询已关闭'}), 503
    data = request.json or {}
    userid, err = _parse_userid(data.get('userid'))
    if err:
        return err
    appcode, err = _parse_appcode(data.get('appcode'))
    if err:
        return err
    try:
        return jsonify({'success': True,
                        'data': CpUserData.list_modules(userid, appcode)})
    except Exception as e:  # noqa: BLE001
        return jsonify({'success': False, 'message': f'模块查询失败: {e}'}), 500


def _parse_module(raw):
    """解析并校验模块名（复用同一套标识符白名单）。返回 (module, err_response)。"""
    module = (raw or '').strip().lower()
    if not CpUserData._IDENT_RE.match(module):  # noqa: SLF001
        return None, (jsonify({'success': False, 'message': f'模块名非法: {module}'}), 400)
    return module, None


@app.route('/api/cp-data/direct/module', methods=['POST'])
def api_cp_direct_module():
    """点开单个模块：列出其 redis 与 mysql 明细。

    body: {userid, appcode, module}
    返回 data: {module, userid, appcode,
                redis:[{key, type, func_info, value}...],
                mysql:{table, tables, exists, rows:[{name, data, createtime, updatetime}]},
                warnings}
    """
    if not CP_DIRECT_ENABLED:
        return jsonify({'success': False, 'message': 'CP 直连查询已关闭'}), 503
    data = request.json or {}
    userid, err = _parse_userid(data.get('userid'))
    if err:
        return err
    appcode, err = _parse_appcode(data.get('appcode'))
    if err:
        return err
    module, err = _parse_module(data.get('module'))
    if err:
        return err
    try:
        return jsonify({'success': True,
                        'data': CpUserData.module_detail(userid, appcode, module)})
    except Exception as e:  # noqa: BLE001
        return jsonify({'success': False, 'message': f'模块详情查询失败: {e}'}), 500


@app.route('/api/cp-data/direct/write-prepare', methods=['POST'])
def api_cp_direct_write_prepare():
    """受控写第一步：写前实时查询，回吐当前值作为编辑起点（只读，不改数据）。

    body: {userid, appcode, module, redisKey?, mysqlName?}
      redisKey / mysqlName 表示「用户点的是哪一侧」，决定编辑起点取哪侧的值；
      实际写入目标仍按各自存在性判定（存在即写），与点哪侧无关。

    返回 data: {redis:{key,exists,type,value,ttl}, mysql:{table,name,exists,data,...},
                targets:{redis,mysql}, startValue, startFrom, warnings}
      targets 就是「本次会写哪几侧」，前端据此提示用户。
    """
    if not CP_DIRECT_ENABLED:
        return jsonify({'success': False, 'message': 'CP 直连查询已关闭'}), 503
    data = request.json or {}
    userid, err = _parse_userid(data.get('userid'))
    if err:
        return err
    appcode, err = _parse_appcode(data.get('appcode'))
    if err:
        return err
    module, err = _parse_module(data.get('module'))
    if err:
        return err
    try:
        return jsonify({'success': True, 'data': CpUserData.prepare_write(
            userid, appcode, module,
            redis_key=(data.get('redisKey') or None),
            mysql_name=(data.get('mysqlName') or None))})
    except ValueError as e:
        return jsonify({'success': False, 'message': str(e)}), 400
    except Exception as e:  # noqa: BLE001
        return jsonify({'success': False, 'message': f'写入前查询失败: {e}'}), 500


@app.route('/api/cp-data/direct/write', methods=['POST'])
def api_cp_direct_write():
    """受控写第二步：写入。**存在即写** —— 两侧都在则双写，只剩一侧则只写该侧。

    body: {userid, appcode, module, value, redisKey?, mysqlName?}
    ⚠ 会真实修改玩家数据；调用前应已经过 write-prepare 让用户确认起点值。

    写前自动取快照（redis 改前值 + TTL / mysql 改前行），随响应返回 ——
    把 snapshot 的值原样回灌本端点即可撤回。

    返回 data: {written:{redis,mysql,mysqlAffected}, snapshot, warnings}
    """
    if not CP_DIRECT_ENABLED:
        return jsonify({'success': False, 'message': 'CP 直连查询已关闭'}), 503
    if not CP_DIRECT_WRITE_ENABLED:
        return jsonify({'success': False, 'message': 'CP 直连写入已关闭（查询不受影响）'}), 503
    data = request.json or {}
    userid, err = _parse_userid(data.get('userid'))
    if err:
        return err
    appcode, err = _parse_appcode(data.get('appcode'))
    if err:
        return err
    module, err = _parse_module(data.get('module'))
    if err:
        return err
    if 'value' not in data:
        return jsonify({'success': False, 'message': '缺少 value'}), 400
    try:
        return jsonify({'success': True, 'data': CpUserData.commit_write(
            userid, appcode, module, data.get('value'),
            redis_key=(data.get('redisKey') or None),
            mysql_name=(data.get('mysqlName') or None))})
    except ValueError as e:
        return jsonify({'success': False, 'message': str(e)}), 400
    except Exception as e:  # noqa: BLE001
        return jsonify({'success': False, 'message': f'写入失败: {e}'}), 500
