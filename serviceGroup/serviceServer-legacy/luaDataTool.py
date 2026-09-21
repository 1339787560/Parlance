#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""luaDataTool.py —— Lua 侧玩家数据（荣耀特权 / 周卡 / 月卡 / 装扮 / 迎新礼）CLI 桥接。

**为什么存在**：这 5 条端点要读写**游戏库**（MySQL + protobuf 记录），实现全在 Python
CommonTools（`CredsManager` 解凭据 / `DBConnector` 连库 / `TQVIP.py` / `LuaDataManager.py`
/ `tqvip_pb2.py`）。Rust 侧没有 mysql/redis/protobuf 依赖，二次实现凭据解密与 protobuf
读写风险大且会分叉，故沿用本仓既有做法（同 `spideorder.rs` 起 `python spideOnlineLog.py`）：
**把 HTTP 面留给 Rust，把数据层留给 Python**。

**调用契约**（Rust `routes/money.rs` 以子进程调用）：
    python luaDataTool.py <action>        # 参数：stdin 的 JSON 对象
    stdout（单行 JSON）:
        {"ok": true,  "body": {...}}                       # 成功，body = 原 Flask 响应体
        {"ok": false, "status": 400|500, "message": "..."}  # 失败，沿用原状态码与文案
    action ∈ set-tqvip | set-weekcard | set-monthcard | query-costume | set-newplayer-gift

**与 legacy 的关系**：各 action 是 `CustomRoute/ServiceRoute.py` 同名路由体的**逐条搬运**
（校验、文案、状态码、数据调用序列一致），唯一差异是「入参来自 stdin」而非 `request.json`、
「出参打印 JSON」而非 `jsonify`。**改动本文件请同步 ServiceRoute.py 对应路由体**，反之亦然。

**分工**：需求侧的**廉价校验**（字段存在性、正整数、范围）由 Rust 侧先行拦截并返回同样的
文案；本文件仍保留原样校验作为兜底（直接调用本脚本时行为与原 Flask 路由一致）。
"""

import json
import os
import sys
import traceback
from datetime import datetime, timedelta

# stdout 必须是 UTF-8：调用方（Rust）按 UTF-8 解析 JSON，而 Windows 管道默认可能落到
# ANSI 代码页（cp936），中文文案会变成非 UTF-8 字节导致解析失败。
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:  # pragma: no cover - 老解释器/异常环境
    pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 数据层依赖：缺依赖时不直接崩，留成 JSON 错误让 Rust 侧能转成可读文案
IMPORT_ERROR = None
try:
    from CommonTools.xzmpDB.TQVIP import TQVIPManager, TQMonthCardManager, timeUtil
    import CommonTools.xzmpDB.tqvip_pb2 as tqvip_pb2
    from CommonTools.xzmpDB.LuaDataManager import (
        CostumeManager,
        TQNewPlayerGiftManager,
        _getdatenum,
    )
    from CommonTools.xzmpDB.DBConnector import get_mysql_connection, get_redis_connection
except Exception as e:  # pragma: no cover - 环境问题分支
    IMPORT_ERROR = "%s: %s" % (type(e).__name__, e)


class BadRequest(Exception):
    """携带原 400 文案与状态码的校验失败。"""

    def __init__(self, message, status=400):
        super(BadRequest, self).__init__(message)
        self.message = message
        self.status = status


# ---------------------------------------------------------------- 荣耀特权
# 与 chunkSvr TQVipConfig.lua configs.grade[].experience 单级阈值求和一致
# 与 leveldefine_xzmp.jsonc levelContent[].experience 累计阈值一致
TQVIP_GRADE_THRESHOLDS = [
    0, 100, 600, 1600, 4600, 9600, 19600, 39600,
    79600, 159600, 309600, 609600, 1209600, 2209600, 4209600, 7209600,
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


def h_set_tqvip(data):
    """设置荣耀特权数据。经验决定等级，上次登录时间决定 datetag，上次展示动画等级同步为当前等级。"""
    user_ids = data.get("userIds")
    experience = data.get("experience")
    last_login_date = data.get("lastLoginDate")
    isdemoteani = data.get("isdemoteani")
    rewardstatus = data.get("rewardstatus")  # 已领取一次性奖励的等级下标数组

    if not all([user_ids, experience is not None, last_login_date is not None, isdemoteani is not None]):
        raise BadRequest("参数不完整")
    try:
        experience = int(experience)
        if experience < 0:
            raise ValueError
    except (ValueError, TypeError):
        raise BadRequest("经验值必须是非负整数")

    grade = calc_tqvip_grade(experience)
    # experience 是累计经验，chunkSvr Lua 的 experience 字段语义为级内进度。
    # 拆出级内经验写入，符合 Lua checkGrade 语义（级内 < 下一级阈值则不触发升级）。
    in_grade_exp = calc_tqvip_in_grade_exp(experience, grade)

    # 解析上次登录时间 -> datetag（YYYYMMDD 格式）
    try:
        if isinstance(last_login_date, int) and not isinstance(last_login_date, bool):
            datetag = last_login_date
        elif isinstance(last_login_date, str):
            dt = datetime.fromisoformat(last_login_date.replace(" ", "T"))
            datetag = timeUtil.getdatenum(dt)
        else:
            datetag = timeUtil.getdatenum(datetime.now())
    except (ValueError, TypeError):
        raise BadRequest("上次登录时间格式错误")

    manager = TQVIPManager()
    results = {}
    for user_id in user_ids:
        vip_message = manager.get_vip_data(user_id)
        if not vip_message:
            vip_message = tqvip_pb2.TQVip_PlayerData()  # 不存在则新建

        vip_message.experience = in_grade_exp
        vip_message.grade = grade
        vip_message.maxexperience = in_grade_exp
        vip_message.maxgrade = grade
        vip_message.lastshowanigrade = grade
        vip_message.isdemoteani = isdemoteani
        vip_message.datetag = datetag

        # rewardstatus: 前端已按当前等级构建完整数组，长度 = grade+1，1=已领取，0=未领取
        if rewardstatus is not None:
            vip_message.ClearField("rewardstatus")
            provided = list(rewardstatus)[: grade + 1]
            provided += [0] * (grade + 1 - len(provided))
            vip_message.rewardstatus.extend(provided)
        # 未传入时不做修改，保留玩家原有已领取状态

        if manager.set_vip_data(user_id, vip_message):
            results[user_id] = "成功"
        else:
            results[user_id] = "失败"

    return {
        "success": True,
        "message": "荣耀特权设置请求已提交",
        "results": results,
        "computedGrade": grade,
        "inGradeExperience": in_grade_exp,
        "datetag": datetag,
    }


# ---------------------------------------------------------------- 周卡 / 月卡
def _set_card(data, which):
    user_ids = data.get("userIds")
    days = data.get("days")
    if not all([user_ids, days is not None]):
        raise BadRequest("参数不完整")

    manager = TQMonthCardManager()
    results = {}
    for user_id in user_ids:
        cache = manager.get_month_card_data(user_id)
        if not cache:
            cache = tqvip_pb2.TQMonthCard_Cache()  # 不存在则新建

        card = getattr(cache.player, which)
        card.datetag = timeUtil.getdatenum(datetime.now())
        card.starttime = timeUtil.gettimenum(datetime.now())
        card.endtime = timeUtil.add_time_to_timenum(timeUtil.gettimenum(datetime.now()), days=days)

        if manager.set_month_card_data(user_id, cache):
            results[user_id] = "成功"
        else:
            results[user_id] = "失败"

    label = "周卡" if which == "weekcard" else "月卡"
    return {"success": True, "message": "%s设置请求已提交" % label, "results": results}


def h_set_weekcard(data):
    """设置周卡数据。"""
    return _set_card(data, "weekcard")


def h_set_monthcard(data):
    """设置月卡数据。"""
    return _set_card(data, "monthcard")


# ---------------------------------------------------------------- 装扮查询
def h_query_costume(data):
    """查询 Lua 版本玩家装扮（已拥有 + 时限 + 已装备）。"""
    user_id = data.get("userId")
    if not user_id:
        raise BadRequest("参数不完整")
    try:
        user_id = int(user_id)
        if user_id <= 0:
            raise ValueError
    except (ValueError, TypeError):
        raise BadRequest("玩家ID格式错误")

    manager = CostumeManager()
    return {"success": True, "data": manager.query_costume(user_id)}


# ---------------------------------------------------------------- 迎新礼包
def h_set_newplayer_gift(data):
    """设置/取消 Lua 版本玩家迎新礼包状态。"""
    user_ids = data.get("userIds")
    cancel = data.get("cancel", False)

    if not user_ids or not isinstance(user_ids, list):
        raise BadRequest("参数不完整")

    valid_user_ids = []
    for uid in user_ids:
        try:
            uid = int(uid)
            if uid > 0:
                valid_user_ids.append(uid)
        except (ValueError, TypeError):
            continue

    if not valid_user_ids:
        raise BadRequest("请输入有效的玩家ID列表")

    manager = TQNewPlayerGiftManager()
    if cancel:
        results = manager.cancel_gift(valid_user_ids)
        message = "取消迎新礼包请求已提交"
    else:
        receivable_day = data.get("receivableDay")
        receivedays = data.get("receivedays")

        if receivable_day is not None:
            # "第 X 天可领" 模式：玩家可立即领取第 X 天奖励
            # -> receivedays = X-1, lastdate = 昨日(YYYYMMDD)
            try:
                receivable_day = int(receivable_day)
                if receivable_day < 1 or receivable_day > 7:
                    raise ValueError
            except (ValueError, TypeError):
                raise BadRequest("可领天数必须是 1-7 的整数")
            target_receivedays = receivable_day - 1
            yesterday = _getdatenum(datetime.now() - timedelta(days=1))
            results = manager.set_receivedays(
                valid_user_ids, target_receivedays, target_lastdate=yesterday
            )
            message = "迎新礼包设置请求已提交（第 %d 天可领）" % receivable_day
        else:
            if receivedays is None:
                raise BadRequest("参数不完整")
            try:
                receivedays = int(receivedays)
                if receivedays < 0 or receivedays > 7:
                    raise ValueError
            except (ValueError, TypeError):
                raise BadRequest("领取天数必须是 0-7 的整数")
            results = manager.set_receivedays(valid_user_ids, receivedays)
            message = "迎新礼包设置请求已提交"

    return {"success": True, "message": message, "results": results}


# ---------------------------------------------------------------- 探针清理（仅 CLI）
# 用途：e2e 用「不存在的 uid」探针往游戏库/缓存落数据后，按 uid 清干净（幂等）。
#
# **安全边界（重要）**：这是删除原语，**故意不接入任何 Rust 路由 / HTTP 面**——只能命令行调，
# 且必须显式 `confirm: true`。它按 uid 删下面这些表该玩家的行与对应 redis key，不碰其它数据。
# 表名与主键列来自各 Manager 的落点（TQVIP.py `mysql_tbl_name` / LuaDataManager.py `TABLE`）。
PROBE_TABLES = [
    ("sqlas_tqvip", "mainkey"),
    ("sqlas_tqmonthcard", "mainkey"),
    ("sqlas_tqprop", "mainkey"),
    ("sqlas_tqdecoration", "mainkey"),
    ("tbltqnewplayerdailygift", "userid"),
]
PROBE_REDIS_KEYS = [
    "rdsas_tqvip",
    "rdsas_tqmonthcard",
    "rdsas_tqprop",
    "rdsas_tqdecoration",
]


def h_cleanup_probe(data):
    """按 uid 清理探针数据（仅 CLI 用，见上方安全边界）。"""
    if not data.get("confirm"):
        raise BadRequest("cleanup-probe 需显式 confirm: true")
    raw_ids = data.get("userIds") or []
    uids = []
    for u in raw_ids:
        try:
            uids.append(int(u))
        except (ValueError, TypeError):
            continue
    if not uids:
        raise BadRequest("cleanup-probe 需提供 userIds")

    deleted = {}
    conn = get_mysql_connection()
    if conn is None:
        raise BadRequest("MySQL 连接不可用")
    try:
        cur = conn.cursor()
        for table, pk in PROBE_TABLES:
            total = 0
            for uid in uids:
                try:
                    cur.execute("DELETE FROM %s WHERE %s = %%s" % (table, pk), (uid,))
                    total += cur.rowcount or 0
                except Exception as e:
                    deleted["%s(%s)" % (table, uid)] = "err: %s" % e
            deleted[table] = total
        conn.commit()
    finally:
        try:
            conn.close()
        except Exception:
            pass

    rconn = get_redis_connection()
    if rconn is not None:
        for base in PROBE_REDIS_KEYS:
            n = 0
            for uid in uids:
                n += int(rconn.delete("%s:%s" % (base, uid)) or 0)
            deleted[base] = n
    else:
        deleted["redis"] = "连接不可用"

    return {"success": True, "deleted": deleted, "userIds": uids}


HANDLERS = {
    "set-tqvip": (h_set_tqvip, "设置荣耀特权时发生错误"),
    "set-weekcard": (h_set_weekcard, "设置周卡时发生错误"),
    "set-monthcard": (h_set_monthcard, "设置月卡时发生错误"),
    "query-costume": (h_query_costume, "查询装扮失败"),
    "set-newplayer-gift": (h_set_newplayer_gift, "设置迎新礼包失败"),
    # 仅 CLI：探针数据清理（不接 HTTP 面）
    "cleanup-probe": (h_cleanup_probe, "清理探针数据失败"),
}


def main(argv):
    action = argv[1] if len(argv) > 1 else ""
    if IMPORT_ERROR:
        print(json.dumps({
            "ok": False,
            "status": 500,
            "message": ("luaDataTool 环境不可用（缺依赖？）: %s；"
                        "该脚本必须用带 mysql/redis/protobuf 的解释器运行"
                        "（Rust 侧可用环境变量 SERVICESVR_PYTHON 指定）" % IMPORT_ERROR),
        }, ensure_ascii=False))
        return 0

    entry = HANDLERS.get(action)
    if entry is None:
        print(json.dumps({
            "ok": False,
            "status": 400,
            "message": "不支持的动作: %s（可选 %s）" % (action, ", ".join(sorted(HANDLERS))),
        }, ensure_ascii=False))
        return 0

    handler, err_prefix = entry
    try:
        raw = sys.stdin.read()
        data = json.loads(raw) if raw.strip() else {}
        if not isinstance(data, dict):
            raise BadRequest("参数不是 JSON 对象")
    except BadRequest as e:
        print(json.dumps({"ok": False, "status": e.status, "message": e.message}, ensure_ascii=False))
        return 0
    except Exception as e:
        print(json.dumps({
            "ok": False, "status": 400, "message": "参数 JSON 解析失败: %s" % e,
        }, ensure_ascii=False))
        return 0

    try:
        body = handler(data)
        print(json.dumps({"ok": True, "body": body}, ensure_ascii=False))
    except BadRequest as e:
        print(json.dumps({"ok": False, "status": e.status, "message": e.message}, ensure_ascii=False))
    except Exception as e:
        # 对应 legacy 各路由的 `except Exception` 分支：500 + "<动作>时发生错误: <e>"
        traceback.print_exc(file=sys.stderr)
        print(json.dumps({
            "ok": False, "status": 500, "message": "%s: %s" % (err_prefix, e),
        }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
