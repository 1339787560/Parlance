# -*- coding: utf-8 -*-
"""
向 db_creds.enc 追加 cp 段（CP 平台直连凭据：MySQL modsvr283db + CP redis）。

背景：原 CP 测试面（/api/cp-data/*）借道 125 环境 exec_script，且 client_request 需 db9
五元组（halllogon）。2026-09 起改走直连，本脚本登记直连凭据。

凭据结构（写入后）：
    {
        "xzmp":    {chunk, chunklog, redis},
        "zgda":    {...},
        "cp":      {"mysql": {host,port,user,password,database},
                    "redis": {host,port,password,db}},
        "oss":     {...}
    }

明文不进脚本、不进终端回显、不进 shell 历史：优先读环境变量，缺失则 getpass 交互输入。
复用 CredsManager 的 Fernet 密钥（~/.xzmp_db_key）。

用法：
    # 交互式
    python CommonTools/xzmpDB/add_cp_creds.py

    # 或经环境变量（非交互）
    set CP_MYSQL_HOST=... & set CP_MYSQL_USER=... & ...
    python CommonTools/xzmpDB/add_cp_creds.py
"""
import getpass
import json
import os
import pathlib

from cryptography.fernet import Fernet

_THIS_DIR = pathlib.Path(__file__).resolve().parent
_KEY_PATH = pathlib.Path(os.environ.get('XZMP_DB_KEY_PATH', pathlib.Path.home() / '.xzmp_db_key'))
_ENC_PATH = _THIS_DIR / 'db_creds.enc'


def _ask(label, env_key, default=''):
    """env 优先 -> getpass 隐藏输入 -> 明文 input 带默认值。"""
    v = os.environ.get(env_key)
    if v:
        return v.strip()
    if default:
        got = input(f'{label} (回车={default}): ').strip()
        return got or default
    return getpass.getpass(f'{label} (隐藏输入): ').strip()


def main() -> int:
    if not _KEY_PATH.exists():
        print(f'[ERR] 密钥文件不存在: {_KEY_PATH}')
        return 1
    if not _ENC_PATH.exists():
        print(f'[ERR] 加密凭据文件不存在: {_ENC_PATH}')
        return 1

    fernet = Fernet(_KEY_PATH.read_bytes().strip())
    creds = json.loads(fernet.decrypt(_ENC_PATH.read_bytes()).decode('utf-8'))

    print('=== 追加 CP 直连凭据 (mysql + redis) ===')
    print(f'当前已有段: {list(creds.keys())}')
    if 'cp' in creds:
        cur = creds['cp']
        print(f'[WARN] cp 段已存在: mysql={cur.get("mysql", {}).get("host")} '
              f'redis={cur.get("redis", {}).get("host")}:{cur.get("redis", {}).get("port")}')
        if (input('覆盖? [y/N]: ').strip().lower()) != 'y':
            print('已取消。')
            return 0

    print('\n--- MySQL (CP 用户数据 modsvr283db) ---')
    my_host = _ask('MySQL host', 'CP_MYSQL_HOST')
    my_port = _ask('MySQL port', 'CP_MYSQL_PORT', '3306')
    my_user = _ask('MySQL user', 'CP_MYSQL_USER')
    my_pwd = _ask('MySQL password', 'CP_MYSQL_PASSWORD')
    my_db = _ask('MySQL database', 'CP_MYSQL_DB', 'modsvr283db')

    print('\n--- Redis (CP 模块数据) ---')
    r_host = _ask('Redis host', 'CP_REDIS_HOST')
    r_port = _ask('Redis port', 'CP_REDIS_PORT', '10057')
    r_pwd = _ask('Redis password', 'CP_REDIS_PASSWORD')
    r_db = _ask('Redis db', 'CP_REDIS_DB', '10')

    missing = [n for n, v in (('mysql.host', my_host), ('mysql.user', my_user),
                              ('mysql.password', my_pwd), ('redis.host', r_host),
                              ('redis.password', r_pwd)) if not v]
    if missing:
        print(f'[ERR] 以下必填项为空: {", ".join(missing)}')
        return 2

    # 备份（加密态备份，仍是密文）
    bak = _ENC_PATH.with_suffix('.enc.bak')
    bak.write_bytes(_ENC_PATH.read_bytes())

    creds['cp'] = {
        'mysql': {
            'host': my_host,
            'port': int(my_port),
            'user': my_user,
            'password': my_pwd,
            'database': my_db,
            '_comment': 'CP 用户数据落盘库 (tblcpuserdata_<module>_<appcode>)',
        },
        'redis': {
            'host': r_host,
            'port': int(r_port),
            'password': r_pwd,
            'db': int(r_db),
            '_comment': 'CP 模块数据 redis (db10 = 用户模块 key; db8 = config)',
        },
    }
    _ENC_PATH.write_bytes(
        fernet.encrypt(json.dumps(creds, ensure_ascii=False, indent=2).encode('utf-8')))

    # 自检：回读全量，确认其他段仍可解密（防把已有凭据写坏）
    check = json.loads(fernet.decrypt(_ENC_PATH.read_bytes()).decode('utf-8'))
    print('\n[OK] cp 段已写入。自检（脱敏）：')
    print(f'  mysql = {my_user}@{my_host}:{my_port}/{my_db}  pwd={"*" * 6}')
    print(f'  redis = {r_host}:{r_port} db={r_db}  pwd={"*" * 6}')
    print(f'  其他段完整性: {sorted(check.keys())}')
    for role in ('xzmp', 'zgda'):
        if role in check:
            print(f'    [{role}] targets = {sorted(k for k in check[role])}')
    print(f'  备份: {bak}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
