# -*- coding: utf-8 -*-
"""
向 db_creds.enc 追加 oss 段（AccessKey + Endpoint + Bucket）。

交互式 getpass 输入，明文不进脚本、不进终端回显、不进 shell 历史。
复用 CredsManager 的 Fernet 密钥（~/.xzmp_db_key）。

用法：
    python CommonTools/xzmpDB/add_oss_creds.py
"""
import getpass
import json
import os
import pathlib

from cryptography.fernet import Fernet

_THIS_DIR = pathlib.Path(__file__).resolve().parent
_KEY_PATH = pathlib.Path.home() / '.xzmp_db_key'
_ENC_PATH = _THIS_DIR / 'db_creds.enc'


def main() -> int:
    if not _KEY_PATH.exists():
        print(f'[ERR] 密钥文件不存在: {_KEY_PATH}')
        return 1
    if not _ENC_PATH.exists():
        print(f'[ERR] 加密凭据文件不存在: {_ENC_PATH}')
        return 1

    fernet = Fernet(_KEY_PATH.read_bytes().strip())
    creds = json.loads(fernet.decrypt(_ENC_PATH.read_bytes()).decode('utf-8'))

    print('=== 追加 OSS 凭据 ===')
    print(f'当前已有 role 段: {list(creds.keys())}')
    if 'oss' in creds:
        print(f'[WARN] oss 段已存在: bucket={creds["oss"].get("bucket")}, endpoint={creds["oss"].get("endpoint")}')
        ans = input('覆盖? [y/N]: ').strip().lower()
        if ans != 'y':
            print('已取消。')
            return 0

    access_key_id = os.environ.get('OSS_AK_ID') or getpass.getpass('AccessKeyID: ').strip()
    access_key_secret = os.environ.get('OSS_AK_SECRET') or getpass.getpass('AccessKeySecret (隐藏输入): ').strip()
    endpoint = os.environ.get('OSS_ENDPOINT') or (input('Endpoint (回车=oss-cn-hangzhou.aliyuncs.com): ').strip() or 'oss-cn-hangzhou.aliyuncs.com')
    bucket = os.environ.get('OSS_BUCKET') or (input('Bucket (回车=tcgamelog): ').strip() or 'tcgamelog')

    if not access_key_id or not access_key_secret:
        print('[ERR] AccessKeyID/Secret 不能为空。')
        return 2

    # 备份
    bak = _ENC_PATH.with_suffix('.enc.bak')
    bak.write_bytes(_ENC_PATH.read_bytes())

    creds['oss'] = {
        'access_key_id': access_key_id,
        'access_key_secret': access_key_secret,
        'endpoint': endpoint,
        'bucket': bucket,
    }
    _ENC_PATH.write_bytes(fernet.encrypt(json.dumps(creds, ensure_ascii=False, indent=2).encode('utf-8')))

    # 自检（不打印明文）
    check = json.loads(fernet.decrypt(_ENC_PATH.read_bytes()).decode('utf-8'))['oss']
    print('\n[OK] oss 段已写入。自检（脱敏）：')
    print(f'  endpoint = {check["endpoint"]}')
    print(f'  bucket   = {check["bucket"]}')
    print(f'  ak_id    = {check["access_key_id"][:6]}...{check["access_key_id"][-4:]}')
    print(f'  ak_secret= {"*" * (len(check["access_key_secret"]) - 2)}..')
    print(f'  备份: {bak}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
