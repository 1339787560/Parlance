# -*- coding: utf-8 -*-
"""
Lua ChunkSvr 数据管理器（xzmp 金币/装扮/迎新礼包等老版本数据）。
直接读写 chunk283db 中 Lua 游戏服务器使用的表：
    sqlas_tqprop          -> protobuf tqprops.PropsCache
    sqlas_tqdecoration    -> protobuf tqdecoration.DecorationCache
    tbltqnewplayerdailygift -> 普通关系表
"""
import json
import os
import re

import mysql.connector
import requests
from datetime import datetime, timedelta

from .DBConnector import get_mysql_connection, get_redis_connection
from . import tqdecoration_pb2, tqprops_pb2

# 无限期时间戳，见 TQProp.lua
INFINITETIME = 99999999999999


def _gettimenum(dt_obj=None):
    if dt_obj is None:
        dt_obj = datetime.now()
    v = dt_obj.second
    v += dt_obj.minute * 100
    v += dt_obj.hour * 10000
    v += dt_obj.day * 1000000
    v += dt_obj.month * 100000000
    v += dt_obj.year * 10000000000
    return v

_LUA_CONFIG_ROOT = os.environ.get(
    'XZMP_LUA_CONFIG_ROOT',
    r'D:\Codlib\douque\xzmx\xzmoNewPC\trunk\gamechunksvr\Debug'
)


def _get_chunksvr_url():
    """获取 ChunkSvr Lua HTTP 接口地址。

    优先级：
      1. config.json 中的 chunkSvrHttpUrl 字段
      2. 环境变量 CHUNKSVR_HTTP_URL
      3. 默认 http://localhost:60463/v1.0/chunkluareq
    """
    config_path = os.path.join(os.getcwd(), 'config.json')
    try:
        if os.path.exists(config_path):
            with open(config_path, 'r', encoding='utf-8') as f:
                cfg = json.load(f)
            url = cfg.get('chunkSvrHttpUrl')
            if url:
                return url
    except Exception as e:
        print(f'读取 chunkSvrHttpUrl 配置失败: {e}')
    return os.environ.get(
        'CHUNKSVR_HTTP_URL',
        'http://localhost:60463/v1.0/chunkluareq'
    )


def _read_text(path):
    for enc in ('utf-8', 'gbk', 'latin-1'):
        try:
            with open(path, 'r', encoding=enc) as f:
                return f.read()
        except UnicodeDecodeError:
            continue
    raise UnicodeDecodeError(f'无法解码文件: {path}')


def _extract_section(text, section_name):
    """从 Lua 配置中提取 `section_name = { ... }` 的内容（支持一层嵌套）。"""
    start_marker = re.search(rf'\b{section_name}\s*=\s*\{{', text)
    if not start_marker:
        return ''
    i = start_marker.end()
    depth = 1
    while i < len(text) and depth > 0:
        c = text[i]
        if c == '{':
            depth += 1
        elif c == '}':
            depth -= 1
        i += 1
    return text[start_marker.end():i - 1]


def _parse_timenum(t):
    """把 Lua ltimeutils.gettimenum 格式的整数解析为 datetime。"""
    if not t or t == INFINITETIME:
        return None
    v = int(t)
    year = v // 10000000000
    v %= 10000000000
    month = v // 100000000
    v %= 100000000
    day = v // 1000000
    v %= 1000000
    hour = v // 10000
    v %= 10000
    minute = v // 100
    second = v % 100
    return datetime(year, month, day, hour, minute, second)


def _current_timenum():
    return _gettimenum(datetime.now())


def _getdatenum(dt_obj=None):
    """YYYYMMDD 整数，对应 Lua ltimeutils.getdatenum。"""
    if dt_obj is None:
        dt_obj = datetime.now()
    return dt_obj.year * 10000 + dt_obj.month * 100 + dt_obj.day


class NewPlayerGiftConfig:
    """加载 TQNewPlayerDailyGiftConfig.lua，提供 keepday 与每日奖励金额。"""
    def __init__(self, config_root=_LUA_CONFIG_ROOT):
        path = os.path.join(config_root, 'TQNewPlayerDailyGiftConfig.lua')
        self.keepday = 7
        self.awarditems = []
        if not os.path.exists(path):
            return
        text = _read_text(path)
        m = re.search(r'newplayergiftkeepday\s*=\s*(\d+)', text)
        if m:
            self.keepday = int(m.group(1))
        for m in re.finditer(r'awardcount\s*=\s*(\d+)', text):
            self.awarditems.append(int(m.group(1)))
        if len(self.awarditems) < 7:
            self.awarditems += [0] * (7 - len(self.awarditems))


def _parse_lua_entry_block(block_text):
    """从 `{ id=1, propid=10001, ... }` 块中解析 key/value。"""
    entry = {}
    for key, val in re.findall(r'\b(\w+)\s*=\s*([^,\n]+)', block_text):
        val = val.strip()
        if val.startswith('"') and val.endswith('"'):
            entry[key] = val[1:-1]
        else:
            try:
                entry[key] = int(val)
            except ValueError:
                entry[key] = val
    return entry


class DecorationConfig:
    """加载 Lua 装扮配置，建立 propid -> 装扮元信息的映射。"""
    _TYPE_SECTIONS = {
        'headlist': ('head', 1, '头像'),
        'tablelist': ('table', 2, '牌桌'),
        'cardlist': ('card', 3, '牌背'),
    }

    def __init__(self, config_root=_LUA_CONFIG_ROOT):
        self.config_root = config_root
        self._prop_map = {}
        self._id_map = {}
        self._defaults = {
            'headmale': 1,
            'headfemale': 2,
            'table': 102,
            'card': 202,
        }
        self._load()

    def _load(self):
        decoration_path = os.path.join(self.config_root, 'TQDecorationsConfig.lua')
        props_path = os.path.join(self.config_root, 'TQPropsConfig.lua')

        # 先加载 propid -> 名称
        prop_names = {}
        if os.path.exists(props_path):
            text = _read_text(props_path)
            for m in re.finditer(
                r'\w+\s*=\s*\{\s*id\s*=\s*(\d+)\s*,\s*name\s*=\s*"([^"]+)"',
                text
            ):
                prop_names[int(m.group(1))] = m.group(2)

        # 再加载装饰配置
        if not os.path.exists(decoration_path):
            return

        text = _read_text(decoration_path)

        # 解析默认装备
        defaults_match = re.search(
            r'defaultsrecord\s*=\s*\{(.*?)\}', text, re.S
        )
        if defaults_match:
            self._defaults = _parse_lua_entry_block(defaults_match.group(1))

        for section, (type_key, type_id, type_label) in self._TYPE_SECTIONS.items():
            inner = _extract_section(text, section)
            for block in re.finditer(r'\{(.*?)\}', inner, re.S):
                entry = _parse_lua_entry_block(block.group(1))
                decoration_id = entry.get('id')
                propid = entry.get('propid')
                if not decoration_id or not propid:
                    continue
                meta = {
                    'decoration_id': decoration_id,
                    'propid': propid,
                    'type_key': type_key,
                    'type_id': type_id,
                    'type_label': type_label,
                    'name': prop_names.get(propid, '未知装扮'),
                    'relatedmodule': entry.get('relatedmodule', ''),
                }
                self._prop_map[propid] = meta
                self._id_map[decoration_id] = meta

    def by_propid(self, propid):
        return self._prop_map.get(propid)

    def by_id(self, decoration_id):
        return self._id_map.get(decoration_id)

    @property
    def defaults(self):
        return self._defaults


class TQPropManager:
    """管理 sqlas_tqprop / rdsas_tqprop:{uid}。"""
    def __init__(self):
        self.mysql_table = 'sqlas_tqprop'
        self.redis_table = 'rdsas_tqprop'

    def get_props_data(self, user_id):
        message = self._redis_get(user_id)
        if message is None:
            message = self._mysql_get(user_id)
        return message

    def set_props_data(self, user_id, message):
        res = True
        res &= self._redis_set(user_id, message)
        res &= self._mysql_set(user_id, message)
        return res

    def _redis_key(self, user_id):
        return f'{self.redis_table}:{user_id}'

    def _redis_get(self, user_id):
        conn = get_redis_connection()
        if conn is None:
            return None
        data = conn.get(self._redis_key(user_id))
        if not data:
            return None
        msg = tqprops_pb2.PropsCache()
        msg.ParseFromString(data)
        return msg

    def _redis_set(self, user_id, message):
        try:
            conn = get_redis_connection()
            if conn is None:
                return False
            conn.set(self._redis_key(user_id), message.SerializeToString())
            return True
        except Exception as e:
            print(f'设置道具数据到 Redis 失败: {e}')
            return False

    def _mysql_get(self, user_id):
        conn = None
        cursor = None
        try:
            conn = get_mysql_connection()
            if conn is None:
                return None
            cursor = conn.cursor()
            cursor.execute(f'SELECT * FROM {self.mysql_table} WHERE mainkey = %s', (user_id,))
            row = cursor.fetchone()
            if row and row[1]:
                msg = tqprops_pb2.PropsCache()
                msg.ParseFromString(row[1])
                return msg
            return None
        except mysql.connector.Error as err:
            print(f'获取道具数据失败: {err}')
            return None
        finally:
            if cursor:
                cursor.close()
            if conn:
                conn.close()

    def _mysql_set(self, user_id, message):
        conn = None
        cursor = None
        try:
            conn = get_mysql_connection()
            if conn is None:
                return False
            cursor = conn.cursor()
            pb_data = message.SerializeToString()
            cursor.execute(f'SELECT COUNT(*) FROM {self.mysql_table} WHERE mainkey = %s', (user_id,))
            exists = cursor.fetchone()[0]
            if exists:
                cursor.execute(
                    f'UPDATE {self.mysql_table} SET data = %s WHERE mainkey = %s',
                    (pb_data, user_id)
                )
            else:
                cursor.execute(
                    f'INSERT INTO {self.mysql_table} (mainkey, data) VALUES (%s, %s)',
                    (user_id, pb_data)
                )
            conn.commit()
            return True
        except mysql.connector.Error as err:
            print(f'设置道具数据失败: {err}')
            if conn:
                conn.rollback()
            return False
        finally:
            if cursor:
                cursor.close()
            if conn:
                conn.close()


class TQDecorationManager:
    """管理 sqlas_tqdecoration / rdsas_tqdecoration:{uid}。"""
    def __init__(self):
        self.mysql_table = 'sqlas_tqdecoration'
        self.redis_table = 'rdsas_tqdecoration'

    def get_decoration_cache(self, user_id):
        msg = self._redis_get(user_id)
        if msg is None:
            msg = self._mysql_get(user_id)
        return msg

    def set_decoration_cache(self, user_id, message):
        res = True
        res &= self._redis_set(user_id, message)
        res &= self._mysql_set(user_id, message)
        return res

    def _redis_key(self, user_id):
        return f'{self.redis_table}:{user_id}'

    def _redis_get(self, user_id):
        conn = get_redis_connection()
        if conn is None:
            return None
        data = conn.get(self._redis_key(user_id))
        if not data:
            return None
        msg = tqdecoration_pb2.DecorationCache()
        msg.ParseFromString(data)
        return msg

    def _redis_set(self, user_id, message):
        try:
            conn = get_redis_connection()
            if conn is None:
                return False
            conn.set(self._redis_key(user_id), message.SerializeToString())
            return True
        except Exception as e:
            print(f'设置装扮数据到 Redis 失败: {e}')
            return False

    def _mysql_get(self, user_id):
        conn = None
        cursor = None
        try:
            conn = get_mysql_connection()
            if conn is None:
                return None
            cursor = conn.cursor()
            cursor.execute(f'SELECT * FROM {self.mysql_table} WHERE mainkey = %s', (user_id,))
            row = cursor.fetchone()
            if row and row[1]:
                msg = tqdecoration_pb2.DecorationCache()
                msg.ParseFromString(row[1])
                return msg
            return None
        except mysql.connector.Error as err:
            print(f'获取装扮数据失败: {err}')
            return None
        finally:
            if cursor:
                cursor.close()
            if conn:
                conn.close()

    def _mysql_set(self, user_id, message):
        conn = None
        cursor = None
        try:
            conn = get_mysql_connection()
            if conn is None:
                return False
            cursor = conn.cursor()
            pb_data = message.SerializeToString()
            cursor.execute(f'SELECT COUNT(*) FROM {self.mysql_table} WHERE mainkey = %s', (user_id,))
            exists = cursor.fetchone()[0]
            if exists:
                cursor.execute(
                    f'UPDATE {self.mysql_table} SET data = %s WHERE mainkey = %s',
                    (pb_data, user_id)
                )
            else:
                cursor.execute(
                    f'INSERT INTO {self.mysql_table} (mainkey, data) VALUES (%s, %s)',
                    (user_id, pb_data)
                )
            conn.commit()
            return True
        except mysql.connector.Error as err:
            print(f'设置装扮数据失败: {err}')
            if conn:
                conn.rollback()
            return False
        finally:
            if cursor:
                cursor.close()
            if conn:
                conn.close()


class CostumeManager:
    """装扮查询入口：整合道具表与已装备表。"""
    def __init__(self, config_root=_LUA_CONFIG_ROOT):
        self.config = DecorationConfig(config_root)
        self.prop_manager = TQPropManager()
        self.decoration_manager = TQDecorationManager()

    def query_costume(self, user_id):
        props = self.prop_manager.get_props_data(user_id)
        cache = self.decoration_manager.get_decoration_cache(user_id)

        # 已装备装扮
        equipped = {}
        if cache and cache.HasField('record'):
            equipped = {
                'head': cache.record.headid,
                'table': cache.record.tableid,
                'card': cache.record.cardtypeid,
            }
        else:
            defaults = self.config.defaults
            equipped = {
                'head': defaults.get('headmale', 1),
                'table': defaults.get('table', 102),
                'card': defaults.get('card', 202),
                'is_default': True,
            }

        # 给已装备 ID 补充 propid
        equipped_with_prop = {}
        for slot, dec_id in equipped.items():
            if slot == 'is_default':
                continue
            meta = self.config.by_id(dec_id)
            equipped_with_prop[slot] = {
                'decoration_id': dec_id,
                'propid': meta['propid'] if meta else 0,
                'name': meta['name'] if meta else '未知',
                'type_label': meta['type_label'] if meta else slot,
            }

        # 已拥有装扮
        owned = []
        current = _current_timenum()
        if props:
            for item in props.items:
                meta = self.config.by_propid(item.propid)
                if not meta:
                    continue
                entry = {
                    'propid': item.propid,
                    'decoration_id': meta['decoration_id'],
                    'type_key': meta['type_key'],
                    'type_label': meta['type_label'],
                    'name': meta['name'],
                    'relatedmodule': meta['relatedmodule'],
                }

                if item.HasField('commoninfo') and item.commoninfo.HasField('timeitem'):
                    expire = item.commoninfo.timeitem.expiredate
                    entry['expiredate'] = expire
                    entry['expire_datetime'] = _parse_timenum(expire).isoformat() if _parse_timenum(expire) else None
                    if expire == INFINITETIME:
                        entry['time_limited'] = False
                        entry['permanent'] = True
                    else:
                        entry['time_limited'] = True
                        entry['permanent'] = False
                        entry['expired'] = expire <= current
                else:
                    entry['time_limited'] = False
                    entry['permanent'] = True

                owned.append(entry)

        return {
            'user_id': user_id,
            'equipped': equipped_with_prop,
            'owned': owned,
        }


class TQNewPlayerGiftManager:
    """管理 tbltqnewplayerdailygift。"""
    TABLE = 'tbltqnewplayerdailygift'

    def __init__(self, config_root=_LUA_CONFIG_ROOT):
        self.config = NewPlayerGiftConfig(config_root)

    def get_gift(self, user_id):
        conn = None
        cursor = None
        try:
            conn = get_mysql_connection()
            if conn is None:
                return None
            cursor = conn.cursor()
            cursor.execute(f'SELECT * FROM {self.TABLE} WHERE userid = %s', (user_id,))
            row = cursor.fetchone()
            if not row:
                return None
            columns = [d[0] for d in cursor.description]
            return dict(zip(columns, row))
        except mysql.connector.Error as err:
            print(f'获取迎新礼包数据失败: {err}')
            return None
        finally:
            if cursor:
                cursor.close()
            if conn:
                conn.close()

    def set_receivedays(self, user_ids, receivedays, target_lastdate=None):
        """设置玩家已领天数。

        target_lastdate:
            None  -> 沿用旧语义：receivedays>0 时 lastdate=今日（即"当日已领 N 天"状态）
            0     -> 未领取状态（仅在 receivedays=0 时有意义）
            正整数 -> 显式指定最后领取日期(YYYYMMDD)。传昨日 + receivedays=X-1 即"第 X 天可领"。
        """
        return self._upsert(user_ids, receivedays=receivedays, cancel=False,
                            target_lastdate=target_lastdate)

    def cancel_gift(self, user_ids):
        return self._upsert(user_ids, receivedays=0, cancel=True)

    def _refresh_chunksvr_cache(self, user_id, receivedays, cancel, lastdate=0):
        """调用 ChunkSvr Lua HTTP 接口刷新迎新礼包内存缓存。"""
        url = _get_chunksvr_url()
        payload = {
            'req': 'setnewplayerdailygift',
            'nUserID': user_id,
            'receivedays': receivedays,
            'cancel': bool(cancel),
        }
        if lastdate:
            payload['lastdate'] = lastdate
        try:
            resp = requests.post(url, json=payload, timeout=5)
            resp.raise_for_status()
            return True, None
        except requests.exceptions.RequestException as e:
            msg = f'请求 ChunkSvr 缓存刷新失败: {e}'
            print(msg)
            return False, msg
        except Exception as e:
            msg = f'刷新 ChunkSvr 缓存异常: {e}'
            print(msg)
            return False, msg

    def _build_full_row(self, receivedays, target_lastdate=None):
        """构造一份完整、有效的迎新礼包数据：今天购买，保留 keepday 天，已领 receivedays 天。

        target_lastdate 非 None 时覆盖 lastdate（用于构造"第 X 天可领"等非默认状态）。
        """
        today = _getdatenum()
        keepday = self.config.keepday
        awards = self.config.awarditems
        if target_lastdate is not None:
            lastdate = target_lastdate
        else:
            lastdate = today if receivedays > 0 else 0
        # triggerdate 按 lastdate 推算：购买日 = 最后签到日 - (已签天数-1)；无签到记录则 today
        if lastdate and receivedays > 0:
            ldate = datetime.strptime(str(lastdate), "%Y%m%d").date()
            triggerdate = int((ldate - timedelta(days=receivedays - 1)).strftime("%Y%m%d"))
        else:
            triggerdate = today
        return {
            'newplayer': 1,
            'triggerdate': triggerdate,
            'lastdate': lastdate,
            'receivedays': receivedays,
            'remaindays': keepday,
            'awardday1': awards[0], 'awardday2': awards[1], 'awardday3': awards[2],
            'awardday4': awards[3], 'awardday5': awards[4], 'awardday6': awards[5],
            'awardday7': awards[6],
        }

    def _upsert(self, user_ids, receivedays, cancel, target_lastdate=None):
        results = {}
        conn = None
        cursor = None
        try:
            conn = get_mysql_connection()
            if conn is None:
                for uid in user_ids:
                    results[uid] = '失败：数据库连接失败'
                return results
            cursor = conn.cursor()

            today = _getdatenum()
            awards = self.config.awarditems

            successful_uids = []
            for uid in user_ids:
                try:
                    cursor.execute(
                        f'SELECT newplayer, triggerdate FROM {self.TABLE} WHERE userid = %s',
                        (uid,)
                    )
                    row = cursor.fetchone()
                    purchased = row is not None and row[1] and row[1] != 0

                    if cancel:
                        # 取消：标记为非新手，清空所有礼包字段
                        if row is not None:
                            cursor.execute(
                                f'''UPDATE {self.TABLE} SET
                                    newplayer = 2, triggerdate = 0, lastdate = 0,
                                    receivedays = 0, remaindays = 0,
                                    awardday1 = 0, awardday2 = 0, awardday3 = 0, awardday4 = 0,
                                    awardday5 = 0, awardday6 = 0, awardday7 = 0
                                    WHERE userid = %s''',
                                (uid,)
                            )
                        else:
                            cursor.execute(
                                f'''INSERT INTO {self.TABLE}
                                    (userid, newplayer, triggerdate, lastdate, receivedays, remaindays,
                                     awardday1, awardday2, awardday3, awardday4, awardday5, awardday6, awardday7)
                                    VALUES (%s, 2, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0)''',
                                (uid,)
                            )
                    else:
                        if purchased:
                            # 已购买：仅推进领取天数与领取日期，保留原购买日期与奖励配置
                            if target_lastdate is not None:
                                new_lastdate = target_lastdate
                            else:
                                new_lastdate = today if receivedays > 0 else 0
                            cursor.execute(
                                f'''UPDATE {self.TABLE} SET
                                    newplayer = 1, receivedays = %s, lastdate = %s
                                    WHERE userid = %s''',
                                (receivedays, new_lastdate, uid)
                            )
                        else:
                            # 未购买：初始化完整礼包状态
                            full = self._build_full_row(receivedays, target_lastdate=target_lastdate)
                            if row is not None:
                                cursor.execute(
                                    f'''UPDATE {self.TABLE} SET
                                        newplayer = %s, triggerdate = %s, lastdate = %s,
                                        receivedays = %s, remaindays = %s,
                                        awardday1 = %s, awardday2 = %s, awardday3 = %s, awardday4 = %s,
                                        awardday5 = %s, awardday6 = %s, awardday7 = %s
                                        WHERE userid = %s''',
                                    (full['newplayer'], full['triggerdate'], full['lastdate'],
                                     full['receivedays'], full['remaindays'],
                                     full['awardday1'], full['awardday2'], full['awardday3'], full['awardday4'],
                                     full['awardday5'], full['awardday6'], full['awardday7'], uid)
                                )
                            else:
                                cursor.execute(
                                    f'''INSERT INTO {self.TABLE}
                                        (userid, newplayer, triggerdate, lastdate, receivedays, remaindays,
                                         awardday1, awardday2, awardday3, awardday4, awardday5, awardday6, awardday7)
                                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)''',
                                    (uid, full['newplayer'], full['triggerdate'], full['lastdate'],
                                     full['receivedays'], full['remaindays'],
                                     full['awardday1'], full['awardday2'], full['awardday3'], full['awardday4'],
                                     full['awardday5'], full['awardday6'], full['awardday7'])
                                )
                    results[uid] = '成功'
                    successful_uids.append(uid)
                except mysql.connector.Error as err:
                    results[uid] = f'失败：{err}'

            conn.commit()

            # MySQL 事务已提交、行锁释放后，再通知 ChunkSvr 刷新缓存，避免死锁
            for uid in successful_uids:
                try:
                    if cancel:
                        lastdate = 0
                    elif target_lastdate is not None:
                        lastdate = target_lastdate
                    else:
                        lastdate = today if receivedays > 0 else 0
                    ok, err = self._refresh_chunksvr_cache(uid, receivedays, cancel, lastdate)
                    if not ok:
                        results[uid] = f'成功但缓存刷新失败：{err}'
                except Exception as e:
                    results[uid] = f'成功但缓存刷新失败：{e}'
        except Exception as e:
            print(f'批量更新迎新礼包失败: {e}')
            if conn:
                conn.rollback()
        finally:
            if cursor:
                cursor.close()
            if conn:
                conn.close()

        return results


def test_costume():
    mgr = CostumeManager()
    print(mgr.query_costume(440624))


def test_gift():
    mgr = TQNewPlayerGiftManager()
    print(mgr.get_gift(440624))
    print(mgr.set_receivedays([440624], 3))


if __name__ == '__main__':
    test_costume()
    test_gift()
