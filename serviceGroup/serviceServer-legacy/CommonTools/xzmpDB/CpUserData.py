# -*- coding: utf-8 -*-
"""CP 用户数据直连访问层 — 只读查询 + 受控写 + 清空。

为什么要直连：原 CP 测试面（/api/cp-data/*）借道 125 环境 exec_script，client_request
还需 db9 五元组（mod(pick):halllogon:userid(X):hash）。该通路 2026-08-17 因 CP redis
连接事故整体暂关，且「依赖五元组」的链路在无人登录时必报错。本模块改走直连，
只用 CP 平台自己的两个库，不触 125、不读 db9。

数据源（凭据见 db_creds.enc 的 cp 段）：

    MySQL   tblcpuserdata_<module>_<appcode>   PK(userid, name)，data 列 JSON
    Redis   db10  mod(cp):name(<module>):appcode(<appcode>):uid(<userid>):<FUNC_INFO>
                  mod(cp):name(<module>):appcode(<appcode>):userid(<userid>):<FUNC_INFO>

    db10 = 用户模块数据；db8 = 模块配置（本项目不用，留待扩展）。

读写边界：
    读 —— mysql 仅 SELECT / COUNT；redis 仅 SCAN / TYPE / GET / HGETALL / HKEYS /
          HLEN / SMEMBERS / LRANGE / ZRANGE。
    写 —— prepare_write / commit_write（存在即写，见「受控写」段）；clear_module
          （整模块 redis+mysql 两侧清空，见「清空」段）。两者都只动上述表与 key。

环境限制：CP redis 为 3.0.7（不支持 RESP3），故显式 protocol=2。
"""
import json
import re

import mysql.connector
import redis

from . import CredsManager

TABLE_PREFIX = 'tblcpuserdata_'
DEFAULT_REDIS_DB = 10  # CP 用户模块数据

# 标识符白名单：模块名/缩写只允许小写字母数字下划线（防 SQL 注入拼表名）
_IDENT_RE = re.compile(r'^[a-z0-9_]{1,64}$')

# mod(cp):name(<module>):appcode(<appcode>):<rest>
_KEY_RE = re.compile(r'^mod\(cp\):name\(([^)]+)\):appcode\(([^)]+)\):(.+)$')
# rest 段里的 uid(<n>) 或 userid(<n>)
_UID_IN_KEY_RE = re.compile(r'\b(?:uid|userid)\((\d+)\)')


# ---------------------------------------------------------------- 连接

def _mysql_conn():
    """CP 用户数据 MySQL 连接（调用方负责 close）。"""
    c = CredsManager.get_db_creds('cp', 'mysql')
    return mysql.connector.connect(
        host=c['host'], port=int(c['port']), user=c['user'],
        password=c['password'], database=c['database'],
        connection_timeout=10,
    )


def _redis_conn(db=DEFAULT_REDIS_DB):
    """CP redis 连接（调用方负责 close）。protocol=2：CP redis 3.0.7 不支持 RESP3/HELLO。"""
    c = CredsManager.get_redis_creds('cp')
    return redis.Redis(
        host=c['host'], port=int(c['port']), password=c['password'],
        db=int(db if db is not None else c.get('db', DEFAULT_REDIS_DB)),
        protocol=2, socket_connect_timeout=10, socket_timeout=20,
        decode_responses=True,
    )


def _ident(name, what='标识'):
    """校验标识符（模块名/缩写），非法即抛 —— 表名靠它拼接。"""
    if not name or not _IDENT_RE.match(str(name)):
        raise ValueError(f'{what} 非法: {name!r}（仅允许小写字母/数字/下划线）')
    return str(name)


# ---------------------------------------------------------------- 元数据

def _fetch_tables() -> list:
    """全部 tblcpuserdata_* 表名（升序）。"""
    conn = _mysql_conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT TABLE_NAME FROM information_schema.TABLES "
                    "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME LIKE %s "
                    "ORDER BY TABLE_NAME", (TABLE_PREFIX + '%',))
        rows = [r[0] for r in cur.fetchall()]
        cur.close()
        return rows
    finally:
        conn.close()


def list_appcodes() -> list:
    """从落盘表名派生缩写清单。

    两种命名都要支持（否则会漏）：
        tblcpuserdata_<module>_<appcode>   常规，如 tblcpuserdata_leveldefine_xzmp
        tblcpuserdata_<appcode>            appcode-only 表（friendroom 用），如 tblcpuserdata_xzmx
    """
    out = set()
    for t in _fetch_tables():
        rest = t[len(TABLE_PREFIX):]
        if not rest:
            continue
        appcode = rest.rsplit('_', 1)[-1]
        if _IDENT_RE.match(appcode):
            out.add(appcode)
    return sorted(out)


def _tables_for(appcode) -> list:
    """按缩写筛表，返回 [(module|None, table)]。

    module=None 表示 appcode-only 表（tblcpuserdata_<appcode>）：它的「模块名」不在
    表名里，而由行的 name 列决定（实测 xzmp 该表 name 恒为 'friendroom'）。调用方
    对这类表需按 name 分组，不能假定一表一模块。
    """
    _ident(appcode, '缩写')
    out = []
    for t in _fetch_tables():
        rest = t[len(TABLE_PREFIX):]
        if rest == appcode:
            out.append((None, t))
        elif rest.endswith('_' + appcode):
            module = rest[:-(len(appcode) + 1)]
            if module and _IDENT_RE.match(module):
                out.append((module, t))
    return out


# ---------------------------------------------------------------- redis 读

def _redis_keys(conn, userid, appcode) -> list:
    """扫该玩家在该缩写下的全部 CP 模块 key（兼容 uid()/userid() 两种命名）。"""
    keys = set()
    for pat in (f'mod(cp):*appcode({appcode})*uid({userid})*',
                f'mod(cp):*appcode({appcode})*userid({userid})*'):
        cur = 0
        while True:
            cur, batch = conn.scan(cursor=cur, match=pat, count=500)
            keys.update(batch)
            if cur == 0:
                break
    return sorted(keys)


def _redis_value(conn, key):
    """按 TYPE 分派读值。未知类型返回占位说明。"""
    t = conn.type(key)
    if t == 'string':
        raw = conn.get(key)
        try:
            return t, json.loads(raw)
        except (TypeError, ValueError):
            return t, raw
    if t == 'hash':
        return t, conn.hgetall(key)
    if t == 'list':
        return t, conn.lrange(key, 0, -1)
    if t == 'set':
        return t, sorted(conn.smembers(key))
    if t == 'zset':
        return t, conn.zrange(key, 0, -1, withscores=True)
    return t, f'(type={t}，未拉取)'


def _module_of(key):
    """key -> (module, appcode)；不匹配返回 (None, None)。"""
    m = _KEY_RE.match(key)
    return (m.group(1), m.group(2)) if m else (None, None)


# ---------------------------------------------------------------- 主查询

def list_modules(userid, appcode, redis_db=DEFAULT_REDIS_DB) -> dict:
    """按 玩家ID + 缩写 列该玩家相关模块（redis 与 mysql 双源合并）。

    返回:
        {
          'userid': int, 'appcode': str,
          'modules': [{'module', 'redis_keys': [key...],
                       'mysql_table': str|None, 'mysql_rows': int}, ...],
          'warnings': [str...],
        }

    模块并集口径：redis 有 key 或 mysql 有行，任一命中即列出 —— 这样「缓存已过期、
    只剩落盘」与「只有缓存、尚未落盘」两种情况都看得见（双轨不一致是本页的主要用途）。
    """
    uid = int(userid)
    _ident(appcode, '缩写')
    warnings = []
    per_module = {}

    # --- redis 侧 ---
    try:
        r = _redis_conn(redis_db)
        try:
            for k in _redis_keys(r, uid, appcode):
                module, _ac = _module_of(k)
                if not module:
                    warnings.append(f'key 格式未识别，已跳过: {k}')
                    continue
                per_module.setdefault(module, {'redis_keys': [], 'mysql_rows': 0})
                per_module[module]['redis_keys'].append(k)
        finally:
            r.close()
    except Exception as e:  # noqa: BLE001 —— 单源失败不吞掉另一半结果
        warnings.append(f'redis 查询失败: {e}')

    # --- mysql 侧 ---
    try:
        conn = _mysql_conn()
        try:
            cur = conn.cursor()
            for module, table in _tables_for(appcode):
                if module is None:
                    # appcode-only 表：模块名在 name 列，按 name 分组才知有几个模块
                    cur.execute(f'SELECT name, COUNT(*) FROM `{table}` '
                                f'WHERE userid = %s GROUP BY name', (uid,))
                    hits = cur.fetchall()
                else:
                    cur.execute(f'SELECT COUNT(*) FROM `{table}` WHERE userid = %s', (uid,))
                    n = cur.fetchone()[0]
                    hits = [(module, n)] if n else []
                for mod, n in hits:
                    if not n or not _IDENT_RE.match(str(mod)):
                        continue
                    per_module.setdefault(mod, {'redis_keys': [], 'mysql_rows': 0})
                    per_module[mod]['mysql_rows'] += n
                    per_module[mod]['mysql_table'] = table
            cur.close()
        finally:
            conn.close()
    except Exception as e:  # noqa: BLE001
        warnings.append(f'mysql 查询失败: {e}')

    modules = []
    for module in sorted(per_module):
        d = per_module[module]
        modules.append({
            'module': module,
            'redis_keys': d['redis_keys'],
            'redis_count': len(d['redis_keys']),
            'mysql_table': d.get('mysql_table') or f'{TABLE_PREFIX}{module}_{appcode}',
            'mysql_rows': d['mysql_rows'],
        })
    return {'userid': uid, 'appcode': appcode, 'modules': modules, 'warnings': warnings}


def module_detail(userid, appcode, module, redis_db=DEFAULT_REDIS_DB) -> dict:
    """点开单个模块：列出该模块的 redis 与 mysql 明细。

    返回:
        {'module', 'userid', 'appcode',
         'redis': [{'key', 'type', 'value', 'func_info'}...],
         'mysql': {'table', 'exists': bool, 'rows': [{'name', 'data', 'createtime', 'updatetime'}]},
         'warnings': [...]}
    """
    uid = int(userid)
    _ident(appcode, '缩写')
    _ident(module, '模块名')
    warnings = []
    redis_items = []

    try:
        r = _redis_conn(redis_db)
        try:
            for k in _redis_keys(r, uid, appcode):
                mod_in_key, _ac = _module_of(k)
                if mod_in_key != module:
                    continue
                t, v = _redis_value(r, k)
                redis_items.append({
                    'key': k,
                    'type': t,
                    'func_info': _KEY_RE.match(k).group(3) if _KEY_RE.match(k) else '',
                    'value': v,
                })
        finally:
            r.close()
    except Exception as e:  # noqa: BLE001
        warnings.append(f'redis 查询失败: {e}')

    mysql_out = {'table': f'{TABLE_PREFIX}{module}_{appcode}', 'tables': [],
                 'exists': False, 'rows': []}
    try:
        # 候选表: ① 模块专表 <module>_<appcode> ② appcode-only 表(须再按 name=<module> 过滤)
        candidates = [(t, False) for m, t in _tables_for(appcode) if m == module]
        candidates += [(t, True) for m, t in _tables_for(appcode) if m is None]
        if not candidates:
            warnings.append(f'表不存在，已跳过 mysql 查询: {mysql_out["table"]}')
        else:
            conn = _mysql_conn()
            try:
                cur = conn.cursor(dictionary=True)
                for table, by_name in candidates:
                    sql = (f'SELECT name, data, createtime, updatetime '
                           f'FROM `{table}` WHERE userid = %s')
                    params = [uid]
                    if by_name:
                        sql += ' AND name = %s'
                        params.append(module)
                    cur.execute(sql + ' ORDER BY name', params)
                    rows = cur.fetchall()
                    for row in rows:
                        d = row.get('data')
                        if isinstance(d, (str, bytes)):
                            try:
                                row['data'] = json.loads(d)
                            except (TypeError, ValueError):
                                pass  # 保持原字符串，前端照样能展示
                        for k in ('createtime', 'updatetime'):
                            if row.get(k) is not None:
                                row[k] = str(row[k])
                        row['table'] = table
                    if rows:
                        mysql_out['exists'] = True
                        mysql_out['table'] = table
                        mysql_out['tables'].append(table)
                        mysql_out['rows'].extend(rows)
                cur.close()
            finally:
                conn.close()
    except Exception as e:  # noqa: BLE001
        warnings.append(f'mysql 查询失败: {e}')

    return {'module': module, 'userid': uid, 'appcode': appcode,
            'redis': redis_items, 'mysql': mysql_out, 'warnings': warnings}


# ---------------------------------------------------------------- 受控写
#
# 写入门槛（产品口径）：**存在即写** —— redis / mysql 各判各的存在性；
#   两侧都在 -> 双写；只剩一侧 -> 只写该侧；两侧都无 -> 拒绝（本页不支持新建）。
#
# 写法镜像业务侧（见 cpscript/src/xzmp/*_xzmp.ts），不可自创：
#   redis 按 key 类型分派：
#     string -> SET key <JSON.stringify(data)>；    业务见 leveldefine.async_setData
#     hash   -> HMSET key f v ... (+HDEL 删字段)；  业务见 award.recordAwardTime（hmset + expire）
#   ⚠ 绝不可对 hash 用 SET —— 会把整个 hash 冲成一个字符串，字段全丢。
#   ⚠ Redis 3.0.7 不支持多字段 HSET（4.0 才有），必须走 HMSET。
#   ⚠ TTL：SET 会清 TTL，须写前读原 TTL、写后再 EXPIRE 还原。各模块 TTL 不同
#      （cmdailyquestion 2 天 / leveldefine 7 天 / convert 30 天 / award 当日键 1 天 …，
#        见各自 MAX_REDIS_EXPIRE），**绝不能用常数覆盖**。
#   mysql: INSERT INTO t (userid,name,data) VALUES (...) ON DUPLICATE KEY UPDATE data=VALUES(data)
#          —— 原子 upsert，规避 SELECT-then-INSERT 的 1062 竞态。
#             name 列取值按模块/类不同（PlayerLevelInfo / PersistData / ChunksvrMigrationFlag …），
#             一律沿用库里查出来的真实 name，**不要自己拼**。
#
# 已知取舍（ponytail: 测试面直写，不参与业务分布式锁）：
#   业务侧 async_setData 走 `:lock` 分布式锁；本模块直写**不加锁**，理论上可与业务写并发。
#   测试面可接受（旧 CpDataRoute 同样如此）。要上生产须改走业务请求通道，而非直连。


def _maybe_json(v):
    """BLOB/str 尝试 JSON 解码；失败原样返回（前端仍可展示）。"""
    if isinstance(v, (str, bytes)):
        try:
            return json.loads(v)
        except (TypeError, ValueError):
            return v
    return v


def _str_or_none(v):
    return None if v is None else str(v)


def _assert_redis_key_owner(key, uid, appcode, module):
    """校验 redis key 归属（模块 / 缩写 / 玩家）。不符抛 ValueError。受控写与清空共用。"""
    m, ac = _module_of(key)
    if m != module or ac != appcode:
        raise ValueError(f'key 不归属 模块 {module} / 缩写 {appcode}: {key}')
    hit = _UID_IN_KEY_RE.search(key)
    if not hit or hit.group(1) != str(uid):
        raise ValueError(f'key 不归属玩家 {uid}: {key}')


def _redis_write_target(r, key, uid, appcode, module) -> dict:
    """校验 redis key 归属，返回 {key, exists, type, value, ttl}。归属不符抛 ValueError。"""
    _assert_redis_key_owner(key, uid, appcode, module)
    if not r.exists(key):
        return {'key': key, 'exists': False}
    t, v = _redis_value(r, key)
    return {'key': key, 'exists': True, 'type': t, 'value': v, 'ttl': r.ttl(key)}


def _mysql_write_targets(uid, appcode, module, name=None) -> list:
    """该玩家该模块的 mysql 候选行 [(table, row)]。

    候选表口径与 module_detail 一致：模块专表 <module>_<appcode>，以及 appcode-only
    表（后者按 name=<module> 过滤，friendroom 属此类）。
    """
    out = []
    conn = _mysql_conn()
    try:
        cur = conn.cursor(dictionary=True)
        for m, t in _tables_for(appcode):
            if m == module:
                cur.execute(f'SELECT name, data, createtime, updatetime FROM `{t}` '
                            f'WHERE userid = %s ORDER BY name', (uid,))
            elif m is None:
                cur.execute(f'SELECT name, data, createtime, updatetime FROM `{t}` '
                            f'WHERE userid = %s AND name = %s ORDER BY name', (uid, module))
            else:
                continue
            for row in cur.fetchall():
                if name and row.get('name') != name:
                    continue
                out.append((t, row))
        cur.close()
    finally:
        conn.close()
    return out


def prepare_write(userid, appcode, module, redis_key=None, mysql_name=None,
                  redis_db=DEFAULT_REDIS_DB) -> dict:
    """写前实时查询：定位本次要写的两侧，并回吐当前值作为编辑起点。

    调用方传 redis_key / mysql_name 表示「用户点的是哪一侧」，决定编辑起点取值；
    但**写入目标始终按各自的存在性判定**（与点击哪侧无关）。

    返回 {'redis','mysql','targets','startValue','startFrom','warnings'}
    """
    uid = int(userid)
    _ident(appcode, '缩写')
    _ident(module, '模块名')
    warnings = []
    redis_t = mysql_t = None

    # redis 侧
    try:
        r = _redis_conn(redis_db)
        try:
            keys = [redis_key] if redis_key else \
                [k for k in _redis_keys(r, uid, appcode) if _module_of(k)[0] == module]
            if keys:
                redis_t = _redis_write_target(r, keys[0], uid, appcode, module)
        finally:
            r.close()
    except Exception as e:  # noqa: BLE001 —— 单侧失败不吞掉另一侧结论
        warnings.append(f'redis 探测失败: {e}')

    # mysql 侧
    try:
        rows = _mysql_write_targets(uid, appcode, module, name=mysql_name)
        if rows:
            table, row = rows[0]
            mysql_t = {'table': table, 'name': row.get('name'), 'exists': True,
                       'data': _maybe_json(row.get('data')),
                       'createtime': _str_or_none(row.get('createtime')),
                       'updatetime': _str_or_none(row.get('updatetime'))}
    except Exception as e:  # noqa: BLE001
        warnings.append(f'mysql 探测失败: {e}')

    r_ok = bool((redis_t or {}).get('exists'))
    m_ok = bool((mysql_t or {}).get('exists'))
    if not r_ok and not m_ok:
        raise ValueError('该玩家在此模块下 redis 与 mysql 均无记录，无可修改数据（本页不支持新建）')

    # 编辑起点：用户点哪侧就以哪侧为准；未指定时 ml 侧优先，否则 redis
    if mysql_name and m_ok:
        start, start_from = mysql_t.get('data'), 'mysql'
    elif r_ok:
        start, start_from = redis_t.get('value'), 'redis'
    else:
        start, start_from = mysql_t.get('data'), 'mysql'

    return {'userid': uid, 'appcode': appcode, 'module': module,
            'redis': redis_t, 'mysql': mysql_t,
            'targets': {'redis': r_ok, 'mysql': m_ok},
            'startValue': start, 'startFrom': start_from,
            'warnings': warnings}


def commit_write(userid, appcode, module, value, redis_key=None, mysql_name=None,
                 redis_db=DEFAULT_REDIS_DB) -> dict:
    """受控写：只写存在的那一侧（两侧都在则双写）。写前取快照，返回值供撤回。

    抛 ValueError 表示参数/归属不合法或无可写目标；单侧失败抛异常且不回滚另一侧
    （测试面取舍；返回值里 warnings 会说明）。
    """
    uid = int(userid)
    _ident(appcode, '缩写')
    _ident(module, '模块名')
    if value is None:
        raise ValueError('待写入的值不能为空')

    pre = prepare_write(uid, appcode, module, redis_key=redis_key,
                        mysql_name=mysql_name, redis_db=redis_db)
    payload = json.dumps(value, ensure_ascii=False)
    written = {'redis': False, 'mysql': False, 'mysqlAffected': 0}
    snapshot = {'userid': uid, 'appcode': appcode, 'module': module, 'ts': None}
    warnings = list(pre.get('warnings') or [])

    # --- redis: 按 key 类型分派 + 还原原 TTL ---
    #   string -> SET 整值替换（业务 async_setData 的写法）
    #   hash   -> HMSET 字段级 + HDEL 删字段（业务 recordAwardTime 等的写法：hmset + expire）
    #   ⚠ 不可对 hash 用 SET —— 会把整个 hash 冲成一个字符串，字段全丢。
    #   ⚠ Redis 3.0.7 不支持多字段 HSET（4.0 才有），必须走 HMSET。
    rt = pre.get('redis') or {}
    if rt.get('exists'):
        r = _redis_conn(redis_db)
        try:
            key = rt['key']
            ktype = rt.get('type')
            ttl = r.ttl(key)                 # SET 会清 TTL，先取；写后统一还原
            before = rt.get('value')
            if ktype == 'string':
                r.set(key, payload)
                how = 'SET'
            elif ktype == 'hash':
                if not isinstance(value, dict):
                    raise ValueError('该 redis key 为 hash 型，值必须是 JSON 对象（字段名 -> 字段值）')
                new_map = {str(f): ('' if v is None else
                                    (v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)))
                           for f, v in value.items()}
                old_map = before if isinstance(before, dict) else {}
                changed = {f: v for f, v in new_map.items() if old_map.get(f) != v}
                removed = [f for f in old_map if f not in new_map]
                if changed:
                    args = []
                    for f, v in changed.items():
                        args += [f, v]
                    r.execute_command('HMSET', key, *args)
                if removed:
                    r.execute_command('HDEL', key, *removed)
                how = f'HMSET({len(changed)})+HDEL({len(removed)})'
            else:
                raise ValueError(f'redis key 类型 {ktype} 暂不支持修改（仅 string / hash）')
            if isinstance(ttl, int) and ttl > 0:
                r.expire(key, ttl)           # 保留业务原 TTL（各模块 1~30 天不等）
            snapshot['redis'] = {'key': key, 'type': ktype,
                                 'before': before, 'ttl': ttl, 'how': how}
            written['redis'] = True
        finally:
            r.close()

    # --- mysql: 原子 upsert ---
    mt = pre.get('mysql') or {}
    if mt.get('exists'):
        table, name = mt['table'], mt['name']
        conn = _mysql_conn()
        try:
            cur = conn.cursor()
            cur.execute(
                f'INSERT INTO `{table}` (userid, name, data) VALUES (%s, %s, %s) '
                f'ON DUPLICATE KEY UPDATE data = VALUES(data)',
                (uid, name, payload))
            written['mysqlAffected'] = cur.rowcount  # 1=插入 2=更新 0=值与原来相同
            conn.commit()
            cur.close()
        finally:
            conn.close()
        snapshot['mysql'] = {'table': table, 'name': name, 'before': mt.get('data')}
        written['mysql'] = True

    if not written['redis'] and not written['mysql']:
        raise ValueError('无写入目标（redis 与 mysql 均不存在）')

    return {'userid': uid, 'appcode': appcode, 'module': module,
            'written': written, 'snapshot': snapshot, 'warnings': warnings}


# ---------------------------------------------------------------- 清空
#
# 「模块」在本页是 redis + mysql 的**并集**（任一侧有数据即列出，见 list_modules）。所以
# 「让该模块消失」必须两侧一起清 —— 只清一侧的话，重新查询还会把该模块列出来。
#
# 安全纪律沿用受控写那套：模块名/缩写先过标识符白名单（表名靠它拼）；redis 每个 key 先过
# 归属校验再 DEL；mysql 只删候选表（模块专表 / appcode-only 表按 name 过滤）里该玩家的行。
#
# 不可逆：本操作无快照、无回滚（未要求）。删前的计数随响应返回，供调用方核对。

def clear_module(userid, appcode, module, redis_db=DEFAULT_REDIS_DB) -> dict:
    """清空该玩家在该模块下的数据 —— redis key 与 mysql 行**两侧都清**。

    返回 {'userid','appcode','module','cleared':{'redis','mysql'},'keys','tables'}
    （keys = 被删的 redis key 列表；tables = [{'table','rows'}...]）。

    两侧都无数据时抛 ValueError（无可清空内容）；任一侧失败抛 RuntimeError（已删的另一
    侧不回滚，重试即可续清 —— DEL / DELETE 各自原子）。
    """
    uid = int(userid)
    _ident(appcode, '缩写')
    _ident(module, '模块名')
    keys = []
    tables = []
    errors = []

    # --- redis: 先逐 key 校验归属（不符即抛，不会误删别人的 key），再一次性 DEL ---
    try:
        r = _redis_conn(redis_db)
        try:
            keys = [k for k in _redis_keys(r, uid, appcode)
                    if _module_of(k) == (module, appcode)]
            for k in keys:
                _assert_redis_key_owner(k, uid, appcode, module)
            if keys:
                r.delete(*keys)
        finally:
            r.close()
    except Exception as e:  # noqa: BLE001 —— 单侧失败不吞掉另一侧结论
        errors.append(f'redis 清空失败: {e}')

    # --- mysql: 候选表里该玩家的行 ---
    try:
        conn = _mysql_conn()
        try:
            cur = conn.cursor()
            for m, t in _tables_for(appcode):
                if m == module:
                    cur.execute(f'DELETE FROM `{t}` WHERE userid = %s', (uid,))
                elif m is None:
                    # appcode-only 表（friendroom 用）：模块名在 name 列，按 name 过滤
                    cur.execute(f'DELETE FROM `{t}` WHERE userid = %s AND name = %s',
                                (uid, module))
                else:
                    continue
                if cur.rowcount and cur.rowcount > 0:
                    tables.append({'table': t, 'rows': int(cur.rowcount)})
            conn.commit()
            cur.close()
        finally:
            conn.close()
    except Exception as e:  # noqa: BLE001
        errors.append(f'mysql 清空失败: {e}')

    if errors:
        raise RuntimeError('；'.join(errors))
    if not keys and not tables:
        raise ValueError('该玩家在此模块下 redis 与 mysql 均无数据，无需清空')

    return {'userid': uid, 'appcode': appcode, 'module': module,
            'cleared': {'redis': len(keys),
                        'mysql': sum(t['rows'] for t in tables)},
            'keys': keys, 'tables': tables}


if __name__ == '__main__':
    # 自检：脱库跑一遍真实玩家（默认 uid 取 db10 实际存在的一条）
    import sys
    uid = int(sys.argv[1]) if len(sys.argv) > 1 else 1177149
    app = sys.argv[2] if len(sys.argv) > 2 else 'xzmp'
    print('appcodes:', list_appcodes())
    res = list_modules(uid, app)
    print(json.dumps(res, ensure_ascii=False, indent=2))
    if res['modules']:
        first = res['modules'][0]['module']
        print(f'--- detail: {first} ---')
        print(json.dumps(module_detail(uid, app, first), ensure_ascii=False, indent=2))
