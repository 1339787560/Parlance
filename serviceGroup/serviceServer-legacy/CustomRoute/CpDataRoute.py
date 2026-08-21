# -*- coding: utf-8 -*-
"""CP 数据查询路由 — 125 环境 exec_script 只读代理 (redis / mysql / 用户模块数据)。

技术依据: cpscript/cp_data.py (2026-08-14 实测全通):
  - POST {cp_host}/api/mod(cp)/exec_script, JSON body {src:{client:{appcode},mods:["client"]},script,info}
  - redis.command 返回值外裹一层数组: SCAN 游标取 r[0][0] (raw r[0] 塞 args 炸 RedisCammand parse)
  - mysql.async_execute(cxt, sql) cxt 必传; rows={affected:-1,rows:[{fields:[...]}...]}
  - 用完 redis SELECT 回 db8 (CP 业务默认)

安全约束: 只读测试面 — SQL 仅允许 SELECT, redis 仅允许读类命令。
"""
import json
import re
import urllib.request

from flask import request, jsonify
from . import app

# ---- CP 测试面总开关 (2026-08-17 暂关: CP redis 连接事故排查期, 停发 exec_script 全通路) ----
# False = 全部 /api/cp-data/* 端点 503 拒绝 (不触 125); 恢复 = True 后 cwd_infoserver_reload()
CP_ENABLED = False

CP_HOST = "http://192.168.1.125:65505"
DEFAULT_APPCODE = "xzmp"
DEFAULT_DB_BACK = "8"

# ---- protobuf wire format (client_request 构造, 移植自 cpscript/test_cp_client_request.py) ----

def _varint(v):
    buf = bytearray()
    while v > 0x7f:
        buf.append((v & 0x7f) | 0x80)
        v >>= 7
    buf.append(v & 0x7f)
    return bytes(buf)

def _tag(fn, wt):
    return _varint((fn << 3) | wt)

def _ld(fn, data):
    if isinstance(data, str):
        data = data.encode("utf-8")
    return _tag(fn, 2) + _varint(len(data)) + data

def _vint(fn, v):
    return _tag(fn, 0) + _varint(v)

def _pb_fields(raw):
    """yield (field_no, wire_type, value) — protobuf 裸遍历"""
    i, n = 0, len(raw)
    def varint(i):
        v, s = 0, 0
        while True:
            x = raw[i]; i += 1
            v |= (x & 0x7f) << s
            if not x & 0x80: return v, i
            s += 7
    while i < n:
        tagv, i = varint(i)
        fn, wt = tagv >> 3, tagv & 7
        if wt == 0:
            val, s2 = 0, 0
            while True:
                x = raw[i]; i += 1
                val |= (x & 0x7f) << s2
                if not x & 0x80: break
                s2 += 7
            yield fn, wt, val
        elif wt == 2:
            ln, s3 = 0, 0
            while True:
                x = raw[i]; i += 1
                ln |= (x & 0x7f) << s3
                if not x & 0x80: break
                s3 += 7
            yield fn, wt, raw[i:i + ln]
            i += ln
        else:
            raise ValueError(f"wire_type {wt} not handled")

# 允许的 redis 命令白名单 (只读; SCAN 单独走游标遍历; *_ALL 带范围参数全量读)
REDIS_RO_OPS = {"GET", "HGET", "HGETALL", "HMGET", "HKEYS", "HLEN", "SMEMBERS",
                "LRANGE", "ZSCORE", "TYPE", "TTL", "STRLEN",
                "ZRANGE_ALL", "LRANGE_ALL"}

# mysql rows {fields:[...]} 形状 -> 标准 row dict (首行列名)
def _rows_to_dicts(raw):
    if not isinstance(raw, dict):
        return raw
    rows = raw.get("rows") or []
    out_cols = None
    out = []
    for row in rows:
        fields = row.get("fields") if isinstance(row, dict) else None
        if fields is None:
            continue
        if out_cols is None:
            out_cols = fields  # 首行 = 列名
            continue
        out.append(dict(zip(out_cols, fields)))
    return out


def _exec_script(script, appcode=DEFAULT_APPCODE, timeout=15):
    """跑 JS, 返回 script 返回值 (双层 JSON 已剥)。异常抛 RuntimeError(带原因)。
    超时即抛 (urlopen timeout), 不重试 — 服务不可达时快速回撤。"""
    req = {"src": {"client": {"appcode": appcode}, "mods": ["client"]},
           "script": script, "info": "luckyturntable"}
    r = urllib.request.Request(f"{CP_HOST}/api/mod(cp)/exec_script",
        data=json.dumps(req).encode(), method="POST",
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            raw = resp.read()
    except Exception as e:
        raise RuntimeError(f"exec_script 请求失败: {e}")
    ret = _exec_ret_string(raw)
    if ret is None:
        raise RuntimeError("ExecScriptResp 无 ret — script 可能抛异常 (检查命令/参数)")
    v = json.loads(ret)
    if isinstance(v, str):
        v = json.loads(v)
    if isinstance(v, list) and len(v) == 1 and isinstance(v[0], (str, dict, list)):
        inner = v[0]
        if isinstance(inner, str):
            try:
                inner = json.loads(inner)
            except Exception:
                pass
        v = inner
    return v


def _exec_ret_string(raw):
    """protobuf 裸解析 ExecScriptResp, 取 field 2 (wt2) 字符串。"""
    i, n = 0, len(raw)
    def varint(i):
        v, s = 0, 0
        while True:
            x = raw[i]; i += 1
            v |= (x & 0x7f) << s
            if not x & 0x80: return v, i
            s += 7
    while i < n:
        tagv, i = varint(i)
        fn, wt = tagv >> 3, tagv & 7
        if wt == 2:
            ln, i = varint(i)
            if fn == 2: return raw[i:i+ln].decode("utf-8", "replace")
            i += ln
        elif wt == 0:
            _, i = varint(i)
    return None


def _with_db(db, body_js):
    """生成 try/finally 包裹的 redis script: 切 db -> body -> finally 复位 db8。
    SELECT 是连接级状态, script 中途抛异常若不复位 -> 连接带错误 db 归还连接池, 污染 CP 业务。
    (2026-08-17 CP redis 连接事故根因; finally 保证任何异常路径都复位)"""
    return (
        '(function(){'
        f'  redis.command({{"cmd":"SELECT","args":["{db}"]}});'
        '  try {'
        f'    {body_js}'
        '  } finally {'
        f'    redis.command({{"cmd":"SELECT","args":["{DEFAULT_DB_BACK}"]}});'
        '  }'
        '})()'
    )


def _redis_query(db, key, op):
    """redis 读。通配符自动 SCAN; HGETALL 转 dict; 白名单外命令拒。"""
    db = str(db)
    if op != "SCAN" and any(c in key for c in "*?["):
        op = "SCAN"
    if op == "SCAN":
        body = (
            'var cur="0", keys=[], r;'
            'do { r=redis.command({"cmd":"SCAN","args":[cur,"MATCH",%s,"COUNT","500"]})[0];'
            '     cur=r[0]; keys=keys.concat(r[1]); } while(cur!=="0");'
            'return JSON.stringify(keys);' % json.dumps(key)
        )
        return _exec_script(_with_db(db, body))
    if op not in REDIS_RO_OPS:
        raise RuntimeError(f"redis 命令 {op} 不在只读白名单")
    if op == "HGETALL":
        # 防御: string 型 key 跑 HGETALL 会拆成字符对 flat 数组 -> dict(zip) 产垃圾; 先 TYPE 校验
        t = _exec_script(_with_db(db,
            'var t=redis.command({"cmd":"TYPE","args":[%s]}); return JSON.stringify(t);' % json.dumps(key)))
        t = t[0] if isinstance(t, list) and t else t
        if t != 'hash':
            return {'__error__': f'key 类型为 {t}, HGETALL 仅适用于 hash (string 请用 GET)'}
        flat = _exec_script(_with_db(db,
            'var h=redis.command({"cmd":"HGETALL","args":[%s]}); return JSON.stringify(h);' % json.dumps(key)))
        if not flat:
            return None
        return dict(zip(flat[0::2], flat[1::2]))
    # 范围全量读 (_ALL 后缀映射真实命令 + 0 -1)
    # args 序列化: 单元素 -> "key"; 多元素 -> "key", "0", "-1" (逗号拼接, 不能 JSON 数组嵌套)
    real_op, extra_args = op, []
    if op == "ZRANGE_ALL" or op == "LRANGE_ALL":
        real_op, extra_args = op[:-4], ["0", "-1"]
    args_js = ", ".join(json.dumps(a) for a in [key] + extra_args)
    body = 'var v=redis.command({"cmd":%s,"args":[%s]}); return JSON.stringify(v);' % (json.dumps(real_op), args_js)
    return _exec_script(_with_db(db, body))


_SQL_RO_RE = re.compile(r"^\s*(select|explain|show|desc|describe)\b", re.I)

# 模块双写能力: 有 mysql 落盘表 (tblcpuserdata_<mod>_<appcode>) 的模块 (SHOW TABLES 实测 2026-08-14)
# redis+mysql 都有 -> 支持双写; 仅 redis -> 单写
CP_DUAL_WRITE_MODULES = {
    'cmdailyquestion', 'cmdecoration', 'cmmonthcard', 'cmnewplayerdailygift',
    'cmquickrecharge', 'leveldefine',
    # award/joyfulgift: redis hash 型 (当日 date key), mysql 表未见 -> 单写
    # luckyturntable/resurrect/convert/goldbank/friendroom: 仅 redis -> 单写
}

# 模块 redis key 类型 (读模式): string 型整值 JSON 可改; hash 型暂不开放修改
CP_STRING_KEY_MODULES = {
    'cmdailyquestion', 'cmdecoration', 'cmmonthcard', 'cmnewplayerdailygift',
    'cmquickrecharge', 'leveldefine', 'luckyturntable', 'resurrect', 'convert',
}

# 模块配置名清单 (parse_config 名 = <模块>_<appcode>, 2026-08-14 14/14 实测存在)
CP_MODULES = ["award", "cmdailyquestion", "cmdecoration", "cmmonthcard", "cmnewplayerdailygift",
              "cmquickrecharge", "cmremoteconfig", "convert", "friendroom", "goldbank",
              "joyfulgift", "leveldefine", "luckyturntable", "resurrect"]


@app.route('/api/cp-data/config', methods=['POST'])
def api_cp_data_config():
    """模块配置直读。{module, appcode?=xzmp} — 模块 VM 内 modsvr.parse_config, 不走 OnClientRequest, 零副作用。"""
    if not CP_ENABLED:
        return jsonify({'success': False, 'message': 'CP 测试面已暂时关闭 (CP redis 连接事故排查期)'}), 503
    try:
        data = request.json or {}
        module = (data.get('module') or '').strip()
        appcode = (data.get('appcode', DEFAULT_APPCODE) or '').strip()
        if module not in CP_MODULES:
            return jsonify({'success': False, 'message': f'未知模块 {module}, 可选: {", ".join(CP_MODULES)}'}), 400
        if not re.fullmatch(r'[a-z]+', appcode):
            return jsonify({'success': False, 'message': 'appcode 格式错误'}), 400
        cfg_name = f"{module}_{appcode}"
        script = ('(function(){ try { var c = modsvr.parse_config(%s, "json");'
                  ' return JSON.stringify(c === null || c === undefined ? null : c); }'
                  ' catch(e) { return JSON.stringify("ERR:" + e.message); } })()' % json.dumps(cfg_name))
        v = _exec_script(script, appcode=appcode, timeout=30)
        if isinstance(v, str) and v.startswith("ERR:"):
            return jsonify({'success': False, 'message': v[4:]}), 500
        return jsonify({'success': True, 'data': {'config': cfg_name, 'content': v}})
    except RuntimeError as e:
        return jsonify({'success': False, 'message': str(e)}), 500
    except Exception as e:
        return jsonify({'success': False, 'message': f'配置查询失败: {e}'}), 500

@app.route('/api/cp-data/redis', methods=['POST'])
def api_cp_data_redis():
    """redis 只读查询。{db, key, op?} — key 含通配符自动 SCAN 列 key。"""
    if not CP_ENABLED:
        return jsonify({'success': False, 'message': 'CP 测试面已暂时关闭 (CP redis 连接事故排查期)'}), 503
    try:
        data = request.json or {}
        db = data.get('db', 10)
        key = (data.get('key') or '').strip()
        op = (data.get('op') or 'HGETALL').upper()
        if not key:
            return jsonify({'success': False, 'message': 'key 不能为空'}), 400
        v = _redis_query(db, key, op)
        return jsonify({'success': True, 'data': v})
    except RuntimeError as e:
        return jsonify({'success': False, 'message': str(e)}), 500
    except Exception as e:
        return jsonify({'success': False, 'message': f'redis 查询失败: {e}'}), 500


@app.route('/api/cp-data/mysql', methods=['POST'])
def api_cp_data_mysql():
    """mysql 只读查询 (仅 SELECT/EXPLAIN/SHOW/DESC)。{sql}。
    注意: 查不存在的表会触发 CP 钉钉报警, 前端已隐去此面板, 仅接口保留。"""
    if not CP_ENABLED:
        return jsonify({'success': False, 'message': 'CP 测试面已暂时关闭 (CP redis 连接事故排查期)'}), 503
    try:
        data = request.json or {}
        sql = (data.get('sql') or '').strip().rstrip(';')
        if not sql:
            return jsonify({'success': False, 'message': 'sql 不能为空'}), 400
        if not _SQL_RO_RE.match(sql):
            return jsonify({'success': False, 'message': '仅允许只读 SQL (SELECT/EXPLAIN/SHOW/DESC)'}), 400
        # 二次防御: 语句内禁分号 (多语句注入面)
        if ';' in sql:
            return jsonify({'success': False, 'message': '禁止多语句'}), 400
        script = '(async function(cxt){ return await mysql.async_execute(cxt, %s) })' % json.dumps(sql)
        raw = _exec_script(script, timeout=30)
        return jsonify({'success': True, 'data': _rows_to_dicts(raw)})
    except RuntimeError as e:
        return jsonify({'success': False, 'message': str(e)}), 500
    except Exception as e:
        return jsonify({'success': False, 'message': f'mysql 查询失败: {e}'}), 500


@app.route('/api/cp-data/modules', methods=['POST'])
def api_cp_data_modules():
    """列用户全部模块数据。{userid, appcode?=xzmp, fetch?=true}。
    redis db10 双 pattern (userid()/uid() 两种命名) + TYPE 分派读值;
    mysql tblcpuserdata_<module>_<appcode> 落盘数据联查。"""
    if not CP_ENABLED:
        return jsonify({'success': False, 'message': 'CP 测试面已暂时关闭 (CP redis 连接事故排查期)'}), 503
    try:
        data = request.json or {}
        userid = data.get('userid')
        try:
            userid = int(userid)
            if userid <= 0:
                raise ValueError
        except (ValueError, TypeError):
            return jsonify({'success': False, 'message': '玩家ID格式错误'}), 400
        appcode = data.get('appcode', DEFAULT_APPCODE)
        db = data.get('db', 10)

        # 双 pattern 扫 (award/joyfulgift 用 userid(), 其余模块用 uid())
        pats = [f"mod(cp):*appcode({appcode})*userid({userid})*",
                f"mod(cp):*appcode({appcode})*uid({userid})*"]
        keys = []
        for p in pats:
            keys.extend(_redis_query(db, p, "SCAN") or [])
        keys = sorted(set(keys))

        # 一次 script 批量 TYPE (数组收集; dict 收集在 quickjs 下翻车)
        types = []
        if keys:
            parts = ''.join(
                ' out.push(redis.command({"cmd":"TYPE","args":[%s]}));' % json.dumps(k)
                for k in keys)
            types = _exec_script(_with_db(db,
                'var out=[]; %s return JSON.stringify(out);' % parts)) or []

        modules = []
        for k, t in zip(keys, types):
            t = t[0] if isinstance(t, list) and t else t  # TYPE 返裹数组
            parts = k.split(":")
            modules.append({'module': parts[1] if len(parts) > 1 else k, 'key': k, 'type': t})

        result = {'modules': modules, 'detail': {}}
        if data.get('fetch', True):
            for m in modules:
                key, t = m['key'], m['type']
                if t == 'hash':
                    result['detail'][key] = _redis_query(db, key, 'HGETALL')
                elif t == 'string':
                    v = _redis_query(db, key, 'GET')
                    # string 值常为 JSON, 尝试解析
                    if isinstance(v, str):
                        try:
                            v = json.loads(v)
                        except Exception:
                            pass
                    result['detail'][key] = v
                elif t == 'zset':
                    result['detail'][key] = _redis_query(db, key, 'ZRANGE_ALL')
                elif t == 'set':
                    result['detail'][key] = _redis_query(db, key, 'SMEMBERS')
                elif t == 'list':
                    result['detail'][key] = _redis_query(db, key, 'LRANGE_ALL')
                else:
                    result['detail'][key] = f'(type={t}, 未拉取)'

        # mysql 落盘数据联查: tblcpuserdata_<module>_<appcode>
        # 先 SHOW TABLES 拿真实表清单, 只查确定存在的表 — 查不存在表会触发钉钉报警 (MySql ErrCode:1146)
        mysql_data = {}
        mod_names = sorted({m['module'].replace('name(', '').rstrip(')') for m in modules})
        if mod_names:
            script = '(async function(cxt){ return await mysql.async_execute(cxt, "SHOW TABLES") })'
            existing = set()
            for row in (_rows_to_dicts(_exec_script(script, timeout=5)) or []):
                for v in (row.values() if isinstance(row, dict) else []):
                    if isinstance(v, str) and v.startswith('tblcpuserdata_'):
                        existing.add(v)
            for mod in mod_names:
                table = f"tblcpuserdata_{mod}_{appcode}"
                if table not in existing:
                    continue  # 表不存在直接跳过, 不发查询
                sql = f"SELECT name, data FROM {table} WHERE userid = {int(userid)}"
                script = '(async function(cxt){ return await mysql.async_execute(cxt, %s) })' % json.dumps(sql)
                rows = _rows_to_dicts(_exec_script(script, timeout=5))
                if rows:
                    for r in rows:
                        try:
                            r['data'] = json.loads(r['data'])
                        except Exception:
                            pass
                    mysql_data[table] = rows
        result['mysql'] = mysql_data
        return jsonify({'success': True, 'data': result})
    except RuntimeError as e:
        return jsonify({'success': False, 'message': str(e)}), 500
    except Exception as e:
        return jsonify({'success': False, 'message': f'模块查询失败: {e}'}), 500


@app.route('/api/cp-data/write', methods=['POST'])
def api_cp_data_write():
    """数据修改 (受控写)。{userid, appcode?, module, key, value, dualWrite?}。
    - redis: string 型整值 JSON 替换 + EXPIRE 86400 (镜像业务 async_setData)
    - dualWrite=true 且模块在 CP_DUAL_WRITE_MODULES: 同步 UPDATE tblcpuserdata_<module>_<appcode>
      (name = key 尾段 FUNC_INFO; data 列 = JSON)
    - 写前自动快照原值 (redis + mysql 双快照) 供撤回
    - hash 型 key / 无归属校验失败 / mysql 直改绕过模块名 均拒绝"""
    if not CP_ENABLED:
        return jsonify({'success': False, 'message': 'CP 测试面已暂时关闭 (CP redis 连接事故排查期)'}), 503
    try:
        data = request.json or {}
        userid = data.get('userid')
        appcode = data.get('appcode', DEFAULT_APPCODE)
        module = (data.get('module') or '').strip()
        key = (data.get('key') or '').strip()
        value = data.get('value')
        dual_write = bool(data.get('dualWrite'))
        if not key:
            return jsonify({'success': False, 'message': 'key 不能为空'}), 400
        try:
            userid = int(userid)
            if userid <= 0:
                raise ValueError
        except (ValueError, TypeError):
            return jsonify({'success': False, 'message': '玩家ID格式错误'}), 400
        # 安全: key 归属该玩家 + mod(cp) 前缀 + 模块名匹配
        if not key.startswith(f'mod(cp):name({module}):') or \
                (f'uid({userid})' not in key and f'userid({userid})' not in key):
            return jsonify({'success': False,
                'message': f'key 必须归属模块 {module} 且玩家 {userid} (mod(cp) 前缀): {key}'}), 400
        if module not in CP_STRING_KEY_MODULES:
            return jsonify({'success': False,
                'message': f'模块 {module} 非标准 string 型 redis key, 修改未开放'}), 400
        if dual_write and module not in CP_DUAL_WRITE_MODULES:
            return jsonify({'success': False,
                'message': f'模块 {module} 无 mysql 落盘, 不支持双写'}), 400

        db = '10'
        # ---- 快照 redis 原值 ----
        orig_raw = _exec_script(_with_db(db,
            'var g=redis.command({"cmd":"GET","args":[%s]}); return JSON.stringify(g);' % json.dumps(key)))
        orig = orig_raw[0] if isinstance(orig_raw, list) and orig_raw else orig_raw
        if orig == 'nil':
            orig = None
        elif isinstance(orig, str):
            try:
                orig = json.loads(orig)
            except Exception:
                pass

        # ---- mysql 快照 + 双写 ----
        mysql_before = None
        mysql_updated = False
        table = f"tblcpuserdata_{module}_{appcode}"
        # FUNC_INFO = key 最后一段 (uid(N):<FUNC_INFO>); redis key 尾段常带 ')' 需剥
        func_info = key.rsplit(':', 1)[-1].rstrip(')')
        if dual_write:
            # mysql 快照
            sql_sel = f"SELECT data FROM {table} WHERE userid={userid} AND name='{func_info}'"
            script_sel = '(async function(cxt){ return await mysql.async_execute(cxt, %s) })' % json.dumps(sql_sel)
            rows = _rows_to_dicts(_exec_script(script_sel, timeout=5))
            if rows:
                d0 = rows[0].get('data')
                if isinstance(d0, str):
                    try:
                        d0 = json.loads(d0)
                    except Exception:
                        pass
                mysql_before = d0
            # mysql 写 (UPDATE, affected=0 说明无该行 — 不 INSERT, 保持业务落盘节奏)
            val_str = json.dumps(value, ensure_ascii=False).replace("'", "''")
            sql_upd = f"UPDATE {table} SET data='{val_str}' WHERE userid={userid} AND name='{func_info}'"
            script_upd = '(async function(cxt){ return await mysql.async_execute(cxt, %s) })' % json.dumps(sql_upd)
            up = _exec_script(script_upd, timeout=5) or {}
            affected = up.get('affected', 0) if isinstance(up, dict) else 0
            mysql_updated = affected > 0
            if affected <= 0:
                mysql_before = '__NO_ROW__'  # 标记: mysql 无该行, 双写实际只落了 redis

        # ---- redis 写 ----
        val_str = json.dumps(value, ensure_ascii=False)
        r = _exec_script(_with_db(db,
            'var r=redis.command({"cmd":"set","args":[%s, %s]}, {"cmd":"EXPIRE","args":[%s, "86400"]});'
            'return JSON.stringify(r);' % (json.dumps(key), json.dumps(val_str), json.dumps(key))))

        snapshot = {'db': db, 'key': key, 'before': orig, 'module': module,
                    'mysqlBefore': mysql_before, 'mysqlTable': table if dual_write else None,
                    'dualWrite': dual_write}
        return jsonify({'success': True, 'data': {
            'snapshot': snapshot,
            'redisSet': r, 'mysqlUpdated': mysql_updated}})
    except RuntimeError as e:
        return jsonify({'success': False, 'message': str(e)}), 500
    except Exception as e:
        return jsonify({'success': False, 'message': f'写入失败: {e}'}), 500


# ---- 客户端模拟请求 (client_request + db9 五元组自动取) ----
# req schema: 模块 -> [req 项] — 参数从 *_xzmp.ts OnClientRequest 反推 (2026-08-14 全分支)
# ro=False = 写操作 (发奖/扣次数/购买), 前端标警示后放行
CP_REQ_SCHEMA = {
    'award': [
        {'req': 'queryAdVideoCfg', 'params': {}, 'ro': True, 'desc': '看视频礼包配置'},
        {'req': 'queryReliefConfig', 'params': {}, 'ro': True, 'desc': '低保配置'},
        {'req': 'queryReliefTakeCount', 'params': {}, 'ro': True, 'desc': '低保已领次数'},
        {'req': 'queryDressGiftCfg', 'params': {}, 'ro': True, 'desc': '装饰礼包配置 (运营未开返空)'},
        {'req': 'queryNextDayConfig', 'params': {}, 'ro': True, 'desc': '明日奖励配置 (注意大小写 NextDay)'},
        {'req': 'queryPayGiftPackCfg', 'params': {}, 'ro': True, 'desc': '礼包配置'},
        {'req': 'takeEvaluateReward', 'params': {}, 'ro': False, 'desc': '领取评价奖励 [写]'},
        {'req': 'takeAdVideoGift_v2', 'params': {}, 'ro': False, 'desc': '领取看视频礼包 [写]'},
        {'req': 'takeReliefReward_v2', 'params': {'takeParam': '', 'registerTime': 0, 'subscribe': 0}, 'ro': False,
         'desc': '领取低保奖励 [写]'},
        {'req': 'takeBackHallReward', 'params': {}, 'ro': False, 'desc': '领取返回大厅礼包 [写]'},
        {'req': 'takeDressGiftReward', 'params': {}, 'ro': False, 'desc': '领取装饰礼包 [写]'},
        {'req': 'takeOptionChooseReward', 'params': {'optionKey': ''}, 'ro': False, 'desc': '领取问卷选择礼包 [写]'},
        {'req': 'takeNextDayReward', 'params': {'dayKey': ''}, 'ro': False, 'desc': '领取明日奖励 [写]'},
    ],
    'cmdailyquestion': [
        {'req': 'GR_TQDAILYQUESTION_REQINFO', 'params': {}, 'ro': True, 'desc': '每日问答玩家信息'},
        {'req': 'GR_TQDAILYQUESTION_REQCONFIG', 'params': {}, 'ro': True, 'desc': '每日问答配置'},
        {'req': 'GR_TQDAILYQUESTION_REQANSWER', 'params': {'questionid': 1, 'answer': 0}, 'ro': False,
         'desc': '提交答题 [写]'},
        {'req': 'GR_TQDAILYQUESTION_REQPRIZE', 'params': {}, 'ro': False, 'desc': '领取答题奖励 [写]'},
    ],
    'cmdecoration': [
        {'req': 'queryCMDecorationConfig', 'params': {}, 'ro': True, 'desc': '装扮配置'},
        {'req': 'queryChangeDecoration', 'params': {}, 'ro': True, 'desc': '已使用装饰'},
        {'req': 'queryUserListsHeadFrameInfo', 'params': {'userIDList': [1040720, 0, 0, 0]}, 'ro': True,
         'desc': '多玩家装扮信息 (userIDList 必传)'},
        {'req': 'queryChangeDecoration_use', 'params': {'itemUUID': 0}, 'ro': False,
         'desc': '使用装饰 (源码 queryChangeDecoration + itemUUID 分支) [写]'},
    ],
    'cmmonthcard': [
        {'req': 'queryCMMonthCardConfig', 'params': {}, 'ro': True, 'desc': '周月卡配置'},
    ],
    'cmnewplayerdailygift': [
        {'req': 'queryNewPlayerDailyGiftConfig', 'params': {}, 'ro': True, 'desc': '迎新每日礼包配置'},
        {'req': 'claimDailyReward', 'params': {}, 'ro': False, 'desc': '领取每日礼包奖励 [写]'},
    ],
    'cmquickrecharge': [
        {'req': 'queryCMQuickRechargeConfig', 'params': {}, 'ro': True, 'desc': '补足金币配置'},
        {'req': 'buySpecialGift', 'params': {'gametype': 1, 'roomlevel': 1, 'giftlevel': 1}, 'ro': False,
         'desc': '购买特惠礼包校验 [写]'},
        {'req': 'markSpecialGiftPurchased', 'params': {'gametype': 1, 'roomlevel': 1, 'giftlevel': 1}, 'ro': False,
         'desc': '标记特惠礼包已购买 [写]'},
    ],
    'cmremoteconfig': [
        {'req': 'queryRemoteConfig', 'params': {}, 'ro': True, 'desc': '选房策略远端配置'},
        {'req': 'debugRemoteConfig', 'params': {}, 'ro': False, 'desc': '调试远端配置 [写]'},
    ],
    'convert': [
        {'req': 'queryTutorialState', 'params': {}, 'ro': True, 'desc': '新手引导迁移状态'},
        {'req': 'claimTutorialReward', 'params': {}, 'ro': False, 'desc': '领取引导奖励 [写]'},
        {'req': 'clearMigrationFlag', 'params': {}, 'ro': False, 'desc': '清迁移标记 (仅125/888) [写]'},
        {'req': 'clearMigrationTargets', 'params': {}, 'ro': False, 'desc': '清迁移模块数据 (仅125/888) [写]'},
    ],
    'goldbank': [
        {'req': 'queryGoldBankInfo', 'params': {}, 'ro': True, 'desc': '金库信息'},
    ],
    'joyfulgift': [
        {'req': 'queryJoyFulGiftCfg', 'params': {'gametype': 1, 'roomlevel': 1, 'giftlevel': 1}, 'ro': True,
         'desc': '欢乐礼包配置 (三参必传)'},
    ],
    'leveldefine': [
        {'req': 'queryLevelDefineConfig', 'params': {}, 'ro': True, 'desc': '等级定义配置'},
        {'req': 'reqTakeOneOffReward', 'params': {'getLevelID': 1}, 'ro': False,
         'desc': '领取等级一次性奖励 (getLevelID 必传) [写]'},
    ],
    'luckyturntable': [
        {'req': 'queryLuckyTurntableConfig', 'params': {}, 'ro': True, 'desc': '幸运转盘配置+剩余次数'},
        {'req': 'queryRunTurntable', 'params': {'useCount': 1}, 'ro': False,
         'desc': '转转盘 (useCount 必传, 消耗次数发奖; 注意 req 名大小写 queryRunTurntable) [写]'},
    ],
    'resurrect': [
        {'req': 'queryConfig_resurrect', 'params': {'roomID': 694, 'channelkey': 'tcyan'}, 'ro': True,
         'desc': '复活礼包配置'},
        {'req': 'queryLeftTakeCount_resurrect', 'params': {'roomID': 694, 'channelkey': 'tcyan'}, 'ro': True,
         'desc': '免费复活剩余次数 (roomID 参与逻辑)'},
        {'req': 'queryShowList_resurrect', 'params': {'roomID': 694, 'channelkey': 'tcyan'}, 'ro': True,
         'desc': '复活展示列表'},
        {'req': 'takeReward_resurrect', 'params': {'roomID': 694, 'channelkey': 'tcyan'}, 'ro': False,
         'desc': '使用免费复活 (扣次数+发奖; 注意 req 名 takeReward_resurrect) [写]'},
    ],
}


def _fetch_halllogon(userid):
    """读 db9 halllogon hash -> ClientInfo dict。无记录返 None。"""
    flat = _exec_script(_with_db('9',
        'var h=redis.command({"cmd":"HGETALL","args":[%s]}); return JSON.stringify(h);'
        % json.dumps(f"mod(pick):halllogon:userid({userid}):hash")))
    if not flat:
        return None
    return dict(zip(flat[0::2], flat[1::2]))


def _build_client_info(h):
    """halllogon hash -> ClientInfo protobuf bytes (字段号对齐 pbstruct.ts HallPB.ClientInfo)。"""
    b = b""
    b += _vint(1, int(h["gameid"]))          # gameid
    b += _ld(2, h["appcode"])                # appcode
    b += _vint(4, int(h["userid"]))          # userid
    b += _ld(5, h["username"])               # username
    b += _ld(6, h["hardid"])                 # hardid
    b += _ld(7, h["uniqueid"])               # uniqueid
    b += _vint(8, int(h["channelid"]))       # channelid
    b += _ld(9, h["gameversion"])            # gameversion
    b += _vint(10, int(h["groupid"]))        # groupid
    if h.get("appid") and h["appid"] != "0":
        b += _vint(11, int(h["appid"]))      # appid
    b += _ld(12, h["channelkey"])            # channelkey
    b += _ld(13, "20241101")                 # templateversion (不校验)
    b += _ld(14, h.get("nickname", h["username"]))  # nickname
    return b


def _parse_client_resp(raw):
    """GameClientResp{errs=1, resp=2(Request{id=1,data=2})} 或 202 ErrorInfoOnly"""
    out = {'errs': [], 'resp': None}
    for fn, wt, val in _pb_fields(raw):
        if fn == 1:
            e = {}
            for f2, _, v2 in _pb_fields(val):
                if f2 == 1: e['code'] = v2
                elif f2 == 2: e['errMsg'] = v2.decode('utf-8', 'replace')
                elif f2 == 3: e['line'] = v2
            out['errs'].append(e)
        elif fn == 2:
            r = {}
            for f2, wt2, v2 in _pb_fields(val):
                if f2 == 1: r['id'] = v2
                elif f2 == 2: r['data'] = v2.decode('utf-8', 'replace')
            out['resp'] = r
    return out


@app.route('/api/cp-data/request', methods=['POST'])
def api_cp_data_request():
    """客户端模拟请求。{module, req, params{}, userid, appcode?} — db9 自动取五元组构造 src。
    只读 schema 白名单内的 req; 写操作 (takeReward 等) 不开放。"""
    if not CP_ENABLED:
        return jsonify({'success': False, 'message': 'CP 测试面已暂时关闭 (CP redis 连接事故排查期)'}), 503
    try:
        data = request.json or {}
        module = (data.get('module') or '').strip()
        req_name = (data.get('req') or '').strip()
        params = data.get('params') or {}
        userid = data.get('userid')
        appcode = data.get('appcode', DEFAULT_APPCODE)

        # schema 白名单校验
        schema_mods = CP_REQ_SCHEMA.get(module)
        if not schema_mods:
            return jsonify({'success': False, 'message': f'模块 {module} 未登记 req schema'}), 400
        entry = next((s for s in schema_mods if s['req'] == req_name), None)
        if not entry:
            return jsonify({'success': False, 'message': f'req {req_name} 不在白名单'}), 400

        try:
            userid = int(userid)
            if userid <= 0:
                raise ValueError
        except (ValueError, TypeError):
            return jsonify({'success': False, 'message': '玩家ID格式错误'}), 400

        # db9 五元组
        h = _fetch_halllogon(userid)
        if not h:
            return jsonify({'success': False,
                'message': f'userid {userid} 无 db9 halllogon 记录 (未登录?) — 先用客户端登录一次'}), 400
        if appcode != h.get('appcode'):
            return jsonify({'success': False,
                'message': f'appcode {appcode} 与 halllogon 记录 {h.get("appcode")} 不符 (db9 只存最后登录包)'}), 400

        # GameClientReq{src=1, req=2, info=3}
        src_inner = _ld(1, _build_client_info(h)) + _ld(2, "client")
        src = _ld(1, src_inner)
        payload = dict(params)
        payload['req'] = req_name
        req_inner = _vint(1, 0) + _ld(2, json.dumps(payload))
        body = src + _ld(2, req_inner) + _ld(3, module)

        r = urllib.request.Request(f"{CP_HOST}/api/mod(cp)/client_request",
            data=body, method="POST")
        r.add_header("Content-Type", "application/octet-stream")
        try:
            with urllib.request.urlopen(r, timeout=15) as resp:
                status, raw = resp.status, resp.read()
        except urllib.error.HTTPError as e:
            status, raw = e.code, e.read()

        parsed = _parse_client_resp(raw) if raw else {'errs': [], 'resp': None}
        resp_data = parsed.get('resp', {}) or {}
        d = resp_data.get('data')
        if isinstance(d, str):
            try:
                d = json.loads(d)
            except Exception:
                pass
        return jsonify({'success': True, 'data': {
            'httpStatus': status, 'respId': resp_data.get('id'), 'data': d, 'errs': parsed['errs']}})
    except RuntimeError as e:
        return jsonify({'success': False, 'message': str(e)}), 500
    except Exception as e:
        return jsonify({'success': False, 'message': f'模拟请求失败: {e}'}), 500
