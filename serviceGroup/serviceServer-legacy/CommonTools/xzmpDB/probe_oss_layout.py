# -*- coding: utf-8 -*-
"""
OSS bucket tcgamelog 目录结构探测（只读、定向 ListObjects）。

凭据走 CredsManager.get_oss_creds()（db_creds.enc 的 oss 段），明文不进脚本。
不调 GetService/ListBuckets（仅针对 tcgamelog 单桶）。

用法：
    python CommonTools/xzmpDB/probe_oss_layout.py [--prefix PREFIX] [--depth N] [--max-keys N]
"""
import argparse

import oss2

from CredsManager import get_oss_creds


def _connect() -> oss2.Bucket:
    c = get_oss_creds()
    auth = oss2.Auth(c['access_key_id'], c['access_key_secret'])
    return oss2.Bucket(auth, c['endpoint'], c['bucket'])


def _list_one_level(bucket: oss2.Bucket, prefix: str, max_keys: int = 50):
    """带 delimiter='/' 的一次列举，返回 (common_prefixes, object_keys)。"""
    prefixes, keys = [], []
    for obj in oss2.ObjectIterator(
        bucket, prefix=prefix, delimiter='/', max_keys=max_keys
    ):
        if obj.is_prefix():
            prefixes.append(obj.key)
        else:
            keys.append((obj.key, obj.size))
    return prefixes, keys


def _human(n: int) -> str:
    for unit in ('B', 'KB', 'MB', 'GB'):
        if n < 1024:
            return f'{n:.1f}{unit}'
        n /= 1024
    return f'{n:.1f}TB'


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--prefix', default='', help='起始前缀（默认根）')
    ap.add_argument('--depth', type=int, default=2, help='向下钻几层')
    ap.add_argument('--max-keys', type=int, default=50, help='每层列举上限')
    ap.add_argument('--peek-prefix', default=None, help='直接列举此前缀下文件（看文件类型/命名）')
    args = ap.parse_args()

    bucket = _connect()
    print(f'[INFO] endpoint={get_oss_creds()["endpoint"]} bucket={get_oss_creds()["bucket"]}')

    if args.peek_prefix:
        prefixes, keys = _list_one_level(bucket, args.peek_prefix, args.max_keys)
        print(f'\n=== peek: {args.peek_prefix} （{len(keys)} files, {len(prefixes)} subdirs） ===')
        for k, sz in keys[:30]:
            print(f'  {_human(sz):>10}  {k}')
        if len(keys) > 30:
            print(f'  ... 共 {len(keys)} 个')
        return 0

    def walk(prefix: str, depth: int):
        if depth <= 0:
            return
        prefixes, keys = _list_one_level(bucket, prefix, args.max_keys)
        indent = '  ' * (args.depth - depth)
        print(f'{indent}[{prefix or "/"}] subdirs={len(prefixes)} files={len(keys)}')
        for k, sz in keys[:5]:
            print(f'{indent}  {_human(sz):>10}  {k}')
        if len(keys) > 5:
            print(f'{indent}  ... +{len(keys) - 5} more')
        # 钻前 5 个子前缀
        for p in prefixes[:5]:
            walk(p, depth - 1)

    walk(args.prefix, args.depth)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
