# -*- coding: utf-8 -*-
"""
xzmp/zgda 数据库凭据解密器。

密钥（明文）位于用户主目录 ~/.xzmp_db_key，不入仓库；
加密后的凭据位于同目录 db_creds.enc，可入仓库（Fernet 加密，平台无关）。

凭据结构示例：
    {
        "xzmp": {
            "chunk":    {host, port, user, password, database},   # CD0 MAIN chunk DB
            "chunklog": {host, port, user, password, database},   # CD1 GAME chunklog DB
            "redis":    {host, port, password, db}
        },
        "zgda": { ... }
    }
"""
import json
import os
import pathlib

from cryptography.fernet import Fernet

_THIS_DIR = pathlib.Path(__file__).resolve().parent
_KEY_PATH = pathlib.Path(os.environ.get('XZMP_DB_KEY_PATH', pathlib.Path.home() / '.xzmp_db_key'))
_ENC_PATH = _THIS_DIR / 'db_creds.enc'


def _load_fernet() -> Fernet:
    if not _KEY_PATH.exists():
        raise FileNotFoundError(
            f'密钥文件不存在: {_KEY_PATH}。'
            f'请先用 cryptography.fernet.Fernet.generate_key() 生成并写入该路径。'
        )
    return Fernet(_KEY_PATH.read_bytes().strip())


def load_creds() -> dict:
    """解密并返回完整的凭据字典。"""
    if not _ENC_PATH.exists():
        raise FileNotFoundError(f'加密凭据文件不存在: {_ENC_PATH}')
    f = _load_fernet()
    return json.loads(f.decrypt(_ENC_PATH.read_bytes()).decode('utf-8'))


def get_db_creds(role: str = 'xzmp', target: str = 'chunklog') -> dict:
    """取某角色某目标库的连接参数。

    target 取值：xzmp -> 'chunk' | 'chunklog'；zgda -> 'chunk'（sqlserver）。
    """
    creds = load_creds()
    if role not in creds:
        raise KeyError(f'未知 role: {role}; 可用: {list(creds.keys())}')
    if target not in creds[role]:
        raise KeyError(f'role {role} 无 target={target}; 可用: {list(creds[role].keys())}')
    return creds[role][target]


def get_redis_creds(role: str = 'xzmp') -> dict:
    creds = load_creds()
    if role not in creds:
        raise KeyError(f'未知 role: {role}; 可用: {list(creds.keys())}')
    if 'redis' not in creds[role]:
        raise KeyError(f'role {role} 未配置 redis')
    return creds[role]['redis']


def get_oss_creds() -> dict:
    """取 oss 段（access_key_id / access_key_secret / endpoint / bucket）。
    顶层独立段（非 role 维度），由 add_oss_creds.py 写入。"""
    creds = load_creds()
    if 'oss' not in creds:
        raise KeyError('未配置 oss 段; 请先运行 CommonTools/xzmpDB/add_oss_creds.py')
    return creds['oss']


if __name__ == '__main__':
    # 自检：打印结构（不打印明文密码）
    data = load_creds()
    for role, group in data.items():
        print(f'[{role}]')
        for k, v in group.items():
            if isinstance(v, dict):
                safe = {kk: ('***' if 'password' == kk else vv) for kk, vv in v.items()}
                print(f'  {k}: {safe}')
