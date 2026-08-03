import mysql.connector
import redis

from . import CredsManager


def get_mysql_connection(target='chunklog', role='xzmp'):
    """
    获取 MySQL 连接。

    target:
        'chunklog' -> xzmp chunk283db（CD1 GAME，deposit/TQVIP 等业务表，默认值，向后兼容）
        'chunk'    -> xzmp chunkdb（CD0 MAIN，玩家 chunk 主数据）
    role:
        'xzmp'（默认）/ 'zgda' 等；zgda 暂未启用（sqlserver）。
    """
    try:
        c = CredsManager.get_db_creds(role=role, target=target)
        conn = mysql.connector.connect(
            host=c['host'],
            user=c['user'],
            password=c['password'],
            port=int(c['port']),
            database=c['database'],
        )
        return conn
    except mysql.connector.Error as err:
        print(f"数据库连接失败 ({role}/{target}): {err}")
        return None


def test_connect_mysql():
    conn = get_mysql_connection()
    if conn:
        print("成功连接到数据库！")
        conn.close()
        print("数据库连接已关闭。")
    else:
        print("无法连接到数据库。")


def get_redis_connection(db=None, role='xzmp'):
    """
    获取 Redis 连接。

    db: 显式指定 db 编号；None -> 使用 creds 中的默认 db（xzmp=5）。
    """
    try:
        c = CredsManager.get_redis_creds(role=role)
        conn = redis.Redis(
            host=c['host'],
            port=int(c['port']),
            password=c['password'],
            db=int(db) if db is not None else int(c.get('db', 0)),
        )
        return conn
    except redis.RedisError as err:
        print(f"Redis 连接失败: {err}")
        return None


def test_connect_redis():
    conn = get_redis_connection()
    if conn:
        print("成功连接到 Redis！")
    else:
        print("无法连接到 Redis。")

    conn.close()
    print("Redis 连接已关闭。")


if __name__ == '__main__':
    # 示例用法
    test_connect_mysql()
    test_connect_redis()
