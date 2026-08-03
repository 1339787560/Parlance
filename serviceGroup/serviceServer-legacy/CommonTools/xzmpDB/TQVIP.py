# --- Start of block to handle direct execution for relative imports ---
if __name__ == '__main__':
    import sys
    import os

    current_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.abspath(os.path.join(current_dir, '..', '..'))
    if project_root not in sys.path:
        sys.path.insert(0, project_root)
    
    __package__ = "CommonTools.xzmpDB"

import collections
try:
    collections.MutableMapping
except AttributeError:
    import collections.abc
    collections.MutableMapping = collections.abc.MutableMapping

try:
    collections.MutableSequence
except AttributeError:
    import collections.abc
    collections.MutableSequence = collections.abc.MutableSequence

import mysql.connector
from .DBConnector import get_mysql_connection, get_redis_connection
from . import tqvip_pb2 
from datetime import datetime, timedelta # 导入 datetime 和 timedelta

try:
    from dateutil.relativedelta import relativedelta
except ImportError:
    relativedelta = None
    print("Warning: 'python-dateutil' library not found. Month/Year addition will be less precise.")

class timeUtil:
    def gettimenum(dt_obj=None):
        """
        将 datetime 对象转换为 Lua ltimeutils.gettimenum 格式的整数。
        格式: 年月日时分秒 (例如: 20260313103045)
        """
        if dt_obj is None:
            dt_obj = datetime.now()

        v = dt_obj.second
        v += dt_obj.minute * 100
        v += dt_obj.hour * 10000
        v += dt_obj.day * 1000000
        v += dt_obj.month * 100000000
        v += dt_obj.year * 10000000000
        return v

    def getdatenum(dt_obj=None):
        """
        将 datetime 对象转换为 Lua ltimeutils.getdatenum 格式的整数。
        格式: 年月日 (例如: 20260313)
        """
        if dt_obj is None:
            dt_obj = datetime.now()
        
        v = dt_obj.day
        v += dt_obj.month * 100
        v += dt_obj.year * 10000
        return v

    def add_time_to_timenum(timenum_val, years=0, months=0, days=0):
        """
        在 gettimenum 格式的整数上增加年、月、日，并返回新的 gettimenum 格式整数。
        """
        dt_obj = timeUtil.parse_timenum(timenum_val)

        if relativedelta and (years != 0 or months != 0):
            # 使用 relativedelta 处理年和月，更精确
            dt_obj += relativedelta(years=years, months=months)
        elif years != 0 or months != 0:
            # 如果没有 relativedelta，则进行简单的月/年加法，可能不精确
            # 简单的月份加法，可能导致日期溢出，例如 1月31日 + 1个月 = 2月31日 (无效)
            # 这里为了简化，只处理天数，年和月需要更复杂的逻辑或 dateutil
            print("Warning: 'python-dateutil' not installed. Month/Year addition might be inaccurate.")
            # 简单的年/月加法，不处理日期溢出
            dt_obj = dt_obj.replace(year=dt_obj.year + years)
            dt_obj = dt_obj.replace(month=dt_obj.month + months) # 这里的月份加法可能导致错误

        if days != 0:
            dt_obj += timedelta(days=days)
        
        return timeUtil.gettimenum(dt_obj)

    def parse_datenum(datenum_val):
        """
        将 getdatenum 格式的整数解析回 datetime 对象 (只包含日期部分)。
        """
        year = datenum_val // 10000
        datenum_val %= 10000
        month = datenum_val // 100
        datenum_val %= 100
        day = datenum_val

        return datetime(year, month, day)

    def parse_timenum(timenum_val):
        """
        将 gettimenum 格式的整数解析回 datetime 对象。
        """
        year = timenum_val // 10000000000
        timenum_val %= 10000000000
        month = timenum_val // 100000000
        timenum_val %= 100000000
        day = timenum_val // 1000000
        timenum_val %= 1000000
        hour = timenum_val // 10000
        timenum_val %= 10000
        minute = timenum_val // 100
        timenum_val %= 100
        second = timenum_val

        return datetime(year, month, day, hour, minute, second)


def _encode_varint(value):
    """Encode an integer as protobuf varint bytes."""
    buf = bytearray()
    while value > 0x7F:
        buf.append((value & 0x7F) | 0x80)
        value >>= 7
    buf.append(value & 0x7F)
    return bytes(buf)


def _serialize_vip_non_packed(vip_message):
    """
    Serialize TQVip_PlayerData with rewardstatus in non-packed format.

    Python protobuf library uses packed encoding for repeated int32 (field 5),
    but the Lua C protobuf parser expects non-packed format (each element with
    its own tag). This function:
    1. Clears rewardstatus from the PB message
    2. Serializes the rest normally
    3. Appends rewardstatus elements in non-packed format (tag 0x28 + varint per element)
    """
    # Save rewardstatus, clear it from the message temporarily
    rewardstatus_values = list(vip_message.rewardstatus)
    vip_message.ClearField('rewardstatus')

    # Serialize the rest (without rewardstatus)
    base_bytes = vip_message.SerializeToString()

    # Restore rewardstatus on the PB object (so callers don't see side effects)
    for v in rewardstatus_values:
        vip_message.rewardstatus.append(v)

    # Append rewardstatus in non-packed format: tag=0x28 (field 5, wire type 0=varint)
    rewardstatus_bytes = bytearray()
    for v in rewardstatus_values:
        rewardstatus_bytes += b'\x28' + _encode_varint(v)

    return base_bytes + bytes(rewardstatus_bytes)


# 读：先 redis，后 mysql
# 写：redis + mysql 双写。
class TQVIPManager:
    def __init__(self):
        self.mysql_tbl_name = "sqlas_tqvip"
        self.redis_tbl_name = "rdsas_tqvip"

    def get_vip_data(self,user_id):
        """
        获取 VIP 数据。
        先从 Redis 中获取，如果未找到则从 MySQL 中获取。
        """
        vip_message = self._redis_get_vip_data(user_id)
        if vip_message is None:
            vip_message = self._mysql_get_vip_data(user_id)
        return vip_message

    def set_vip_data(self,user_id,vip_message):
        """
        设置 VIP 数据。
        先将数据存储到 Redis 中，然后异步更新到 MySQL。
        """
        res = True
        res &= self._redis_set_vip_data(user_id, vip_message)
        # 异步更新到 MySQL
        res &= self._mysql_set_vip_data(user_id, vip_message)
        return res

    # 位于 5 号桶
    def _redis_get_vip_data(self, user_id):
        """
        从 Redis 中获取 VIP 数据。
        返回解析后的 PB 对象，或者 None 如果未找到。
        """
        conn = get_redis_connection()
        if conn is None:
            return None

        vip_key = f"rdsas_tqvip:{user_id}"
        vip_data = conn.get(vip_key)
        if vip_data:
            vip_message = tqvip_pb2.TQVip_PlayerData()
            vip_message.ParseFromString(vip_data)
            return vip_message
        return None

    def _redis_set_vip_data(self, user_id, vip_message):
        """
        将 VIP 数据存储到 Redis 中。
        vip_message 应该是 tqvip_pb2.TQVip_PlayerData 对象。
        """
        try:
            conn = get_redis_connection()
            if conn is None:
                return False

            vip_key = f"rdsas_tqvip:{user_id}"
            # 序列化 PB 对象为字节数据
            # 修复: Lua C 层 protobuf 解析器不支持 packed repeated int32，
            # 需要手动将 rewardstatus 字段改为 non-packed 格式（每个元素独立 tag+value）
            pb_data = _serialize_vip_non_packed(vip_message)
            conn.set(vip_key, pb_data)
            return True
        except Exception as e:
            print(f"设置 VIP 数据到 Redis 失败: {e}")
            return False

    def _mysql_get_vip_data(self, user_id):
        """
        根据 user_id 从 sqlas_tqvip 表中获取 VIP 数据。
        返回解析后的 PB 对象，或者 None 如果未找到。
        """
        conn = None
        cursor = None
        try:
            conn = get_mysql_connection()
            if conn is None:
                return None

            cursor = conn.cursor()
            query = f"SELECT * FROM {self.mysql_tbl_name} WHERE mainkey = %s"
            cursor.execute(query, (user_id,))
            result = cursor.fetchone()

            if result:
                # 返回解析后的 PB 对象
                vip_message = tqvip_pb2.TQVip_PlayerData()
                vip_message.ParseFromString(result[1])
                return vip_message
            return None
        except mysql.connector.Error as err:
            print(f"获取 VIP 数据失败: {err}")
            return None
        finally:
            if cursor:
                cursor.close()
            if conn:
                conn.close()

    def _mysql_set_vip_data(self, user_id, vip_message):
        """
        根据 user_id 更新或插入 VIP 数据。
        vip_message 应该是 tqvip_pb2.TQVip_PlayerData 对象。
        """
        conn = None
        cursor = None
        try:
            conn = get_mysql_connection()
            if conn is None:
                return False

            cursor = conn.cursor()
            # 序列化 PB 对象为字节数据（non-packed rewardstatus，兼容 Lua C 解析器）
            pb_data = _serialize_vip_non_packed(vip_message)

            # 检查是否存在该 user_id 的记录
            check_query = f"SELECT COUNT(*) FROM {self.mysql_tbl_name} WHERE mainkey = %s"
            cursor.execute(check_query, (user_id,))
            exists = cursor.fetchone()[0]

            if exists:
                # 更新现有记录
                update_query = f"UPDATE {self.mysql_tbl_name} SET data = %s WHERE mainkey = %s"
                cursor.execute(update_query, (pb_data, user_id))
            else:
                # 插入新记录
                insert_query = f"INSERT INTO {self.mysql_tbl_name} (mainkey, data) VALUES (%s, %s)"
                cursor.execute(insert_query, (user_id, pb_data))

            conn.commit()
            return True
        except mysql.connector.Error as err:
            print(f"设置 VIP 数据失败: {err}")
            if conn:
                conn.rollback()
            return False
        finally:
            if cursor:
                cursor.close()
            if conn:
                conn.close()

class TQMonthCardManager:
    def __init__(self):
        self.table_name = "sqlas_tqmonthcard" # 假设月卡数据存储在名为 sqlas_tqmonthcard 的表中
        self.redis_tbl_name = "rdsas_tqmonthcard"
        
    def get_month_card_data(self,user_id):
        """
        获取月卡数据。
        先从 Redis 中获取，如果未找到则从 MySQL 中获取。
        """
        month_card_message = self._redis_get_month_card_data(user_id)
        if month_card_message is None:
            month_card_message = self._mysql_get_month_card_data(user_id)
        return month_card_message

    def set_month_card_data(self, user_id, month_card_message):
        """
        设置月卡数据。
        先将数据存储到 Redis 中，然后异步更新 MySQL。
        month_card_message 应该是 tqvip_pb2.TQMonthCard_Cache 对象。
        """
        res = True
        res &= self._redis_set_month_card_data(user_id, month_card_message)
        # 异步更新 MySQL
        res &= self._mysql_set_month_card_data(user_id, month_card_message)
        return res

    def _redis_set_month_card_data(self, user_id, month_card_message):
        """
        将月卡数据存储到 Redis 中。
        month_card_message 应该是 tqvip_pb2.TQMonthCard_Cache 对象。
        """
        try:
            conn = get_redis_connection()
            if conn is None:
                return False

            month_card_key = f"{self.redis_tbl_name}:{user_id}"
            # 序列化 PB 对象为字节数据
            pb_data = month_card_message.SerializeToString()
            conn.set(month_card_key, pb_data)
            return True
        except Exception as e:
            print(f"设置月卡数据到 Redis 失败: {e}")
            return False

    def _redis_get_month_card_data(self, user_id):
        """
        根据 user_id 从 Redis 中获取月卡数据。
        返回解析后的 PB 对象，或者 None 如果未找到。
        """
        conn = get_redis_connection()
        if conn is None:
            return None

        month_card_key = f"{self.redis_tbl_name}:{user_id}"
        month_card_data = conn.get(month_card_key)
        if month_card_data:
            month_card_message = tqvip_pb2.TQMonthCard_Cache()
            month_card_message.ParseFromString(month_card_data)
            return month_card_message
        return None

    def _mysql_get_month_card_data(self, user_id):
        """
        根据 user_id 从 sqlas_tqmonthcard 表中获取月卡数据。
        返回解析后的 PB 对象，或者 None 如果未找到。
        """
        conn = None
        cursor = None
        try:
            conn = get_mysql_connection()
            if conn is None:
                return None

            cursor = conn.cursor()
            query = f"SELECT * FROM {self.table_name} WHERE mainkey = %s"
            cursor.execute(query, (user_id,))
            result = cursor.fetchone()

            if result:
                # 返回解析后的 PB 对象
                month_card_message = tqvip_pb2.TQMonthCard_Cache()
                month_card_message.ParseFromString(result[1])
                return month_card_message
            return None
        except mysql.connector.Error as err:
            print(f"获取月卡数据失败: {err}")
            return None
        finally:
            if cursor:
                cursor.close()
            if conn:
                conn.close()

    def _mysql_set_month_card_data(self, user_id, month_card_message):
        """
        根据 user_id 更新或插入月卡数据。
        month_card_message 应该是 tqvip_pb2.TQMonthCard_Cache 对象。
        """
        conn = None
        cursor = None
        try:
            conn = get_mysql_connection()
            if conn is None:
                return False

            cursor = conn.cursor()
            # 序列化 PB 对象为字节数据
            pb_data = month_card_message.SerializeToString()

            # 检查是否存在该 user_id 的记录
            check_query = f"SELECT COUNT(*) FROM {self.table_name} WHERE mainkey = %s"
            cursor.execute(check_query, (user_id,))
            exists = cursor.fetchone()[0]

            if exists:
                # 更新现有记录
                update_query = f"UPDATE {self.table_name} SET data = %s WHERE mainkey = %s"
                cursor.execute(update_query, (pb_data, user_id))
            else:
                # 插入新记录
                insert_query = f"INSERT INTO {self.table_name} (mainkey, data) VALUES (%s, %s)"
                cursor.execute(insert_query, (user_id, pb_data))

            conn.commit()
            return True
        except mysql.connector.Error as err:
            print(f"设置月卡数据失败: {err}")
            if conn:
                conn.rollback()
            return False
        finally:
            if cursor:
                cursor.close()
            if conn:
                conn.close()

class TQPropManager:
    def __init__(self):
        self.redis_tbl_name = "rdsas_tqprop"
        self.table_name = "sqlas_tqprop"
    
    def get_prop_data(self, user_id):
        """
        获取道具数据。
        先从 Redis 中获取，如果未找到则从 MySQL 中获取。
        """
        prop_message = self._redis_get_prop_data(user_id)
        if prop_message is None:
            prop_message = self._mysql_get_prop_data(user_id)
        return prop_message

    def set_prop_data(self, user_id, prop_message):
        """
        设置道具数据。
        先将数据存储到 Redis 中，然后异步更新 MySQL。
        prop_message 应该是 tqvip_pb2.PropsCache 对象。
        """
        res = True
        res &= self._redis_set_prop_data(user_id, prop_message)
        # 异步更新 MySQL
        res &= self._mysql_set_prop_data(user_id, prop_message)
        return res

    def _redis_set_prop_data(self, user_id, prop_message):
        """
        将道具数据存储到 Redis 中。
        prop_message 应该是 tqvip_pb2.PropsCache 对象。
        """
        try:
            conn = get_redis_connection()
            if conn is None:
                return False

            prop_key = f"{self.redis_tbl_name}:{user_id}"
            # 序列化 PB 对象为字节数据
            pb_data = prop_message.SerializeToString()
            conn.set(prop_key, pb_data)
            return True
        except Exception as e:
            print(f"设置道具数据到 Redis 失败: {e}")
            return False

    def _redis_get_prop_data(self, user_id):
        """
        根据 user_id 从 Redis 中获取道具数据。
        返回解析后的 PB 对象，或者 None 如果未找到。
        """
        conn = get_redis_connection()
        if conn is None:
            return None

        prop_key = f"{self.redis_tbl_name}:{user_id}"
        prop_data = conn.get(prop_key)
        if prop_data:
            prop_message = tqvip_pb2.PropsCache()
            prop_message.ParseFromString(prop_data)
            return prop_message
        return None

    def _mysql_get_prop_data(self, user_id):
        """
        根据 user_id 从 sqlas_tqprop 表中获取道具数据。
        返回解析后的 PB 对象，或者 None 如果未找到。
        """
        conn = None
        cursor = None
        try:
            conn = get_mysql_connection()
            if conn is None:
                return None

            cursor = conn.cursor()
            query = f"SELECT * FROM {self.table_name} WHERE mainkey = %s"
            cursor.execute(query, (user_id,))
            result = cursor.fetchone()

            if result:
                # 返回解析后的 PB 对象
                prop_message = tqvip_pb2.PropsCache()
                prop_message.ParseFromString(result[1])
                return prop_message
            return None
        except mysql.connector.Error as err:
            print(f"获取道具数据失败: {err}")
            return None
        finally:
            if cursor:
                cursor.close()
            if conn:
                conn.close()

    def _mysql_set_prop_data(self, user_id, prop_message):
        """
        根据 user_id 更新或插入道具数据。
        prop_message 应该是 tqvip_pb2.PropsCache 对象。
        """
        conn = None
        cursor = None
        try:
            conn = get_mysql_connection()
            if conn is None:
                return False

            cursor = conn.cursor()
            # 序列化 PB 对象为字节数据
            pb_data = prop_message.SerializeToString()

            # 检查是否存在该 user_id 的记录
            check_query = f"SELECT COUNT(*) FROM {self.table_name} WHERE mainkey = %s"
            cursor.execute(check_query, (user_id,))
            exists = cursor.fetchone()[0]

            if exists:
                # 更新现有记录
                update_query = f"UPDATE {self.table_name} SET data = %s WHERE mainkey = %s"
                cursor.execute(update_query, (pb_data, user_id))
            else:
                # 插入新记录
                insert_query = f"INSERT INTO {self.table_name} (mainkey, data) VALUES (%s, %s)"
                cursor.execute(insert_query, (user_id, pb_data))

            conn.commit()
            return True
        except mysql.connector.Error as err:
            print(f"设置道具数据失败: {err}")
            if conn:
                conn.rollback()
            return False
        finally:
            if cursor:
                cursor.close()
            if conn:
                conn.close()

def test_TQVIPData(user_id, vip_message):
    # vip_message = tqvip_pb2.TQVip_PlayerData()
    # vip_message.ParseFromString(bytes.fromhex("20004000080010003800180030999AD209"))
    # print(f"解析后的 VIP 数据: {vip_message}")
    
    manager = TQVIPManager()
    test_user_id = user_id

    # --- 示例：获取 VIP 数据 ---
    retrieved_vip_message = manager.get_vip_data(test_user_id)
    if retrieved_vip_message:
        print(f"用户 {test_user_id} 的 VIP 数据获取成功。")
        print(f"解析后的 VIP 数据: {retrieved_vip_message}")
    else:
        print(f"未找到用户 {test_user_id} 的 VIP 数据。")

    # 创建一个 VIP PB 消息
    vip_message = tqvip_pb2.TQVip_PlayerData()
    vip_message.experience = 84810
    vip_message.grade = 8
    vip_message.maxexperience = 84810
    vip_message.maxgrade = 8
    vip_message.rewardstatus.append(1)                                   # 等级1的奖励已领取A
    vip_message.datetag = timeUtil.getdatenum(datetime.now())            # 示例时间戳
    vip_message.lastshowanigrade = 8
    vip_message.isdemoteani = 0

    if manager.set_vip_data(test_user_id, vip_message):
        print(f"用户 {test_user_id} 的 VIP 数据设置成功。")
    else:
        print(f"用户 {test_user_id} 的 VIP 数据设置失败。")

def test_TQMonthCardData(user_id):
    manager = TQMonthCardManager()
    test_user_id = user_id

    PB_DATA = "0A2E0A1508D9CBD40910DDED91C6D3CD04189EABACF5D3CD04121508D9CBD40910E6ED91C6D3CD0418A68DBDC9D3CD04"
    month_card_cache = tqvip_pb2.TQMonthCard_Cache()
    month_card_cache.ParseFromString(bytes.fromhex(PB_DATA))
    print(f"解析后的月卡数据: {month_card_cache}")

    print(f"\n--- 示例：TQMonthCardManager 操作 (用户ID: {test_user_id}) ---")

    # 1. 尝试获取月卡数据
    retrieved_month_card_message = manager.get_month_card_data(test_user_id)
    if retrieved_month_card_message:
        print(f"用户 {test_user_id} 的月卡数据获取成功。")
        print(f"解析后的月卡数据: {retrieved_month_card_message}")
    else:
        print(f"未找到用户 {test_user_id} 的月卡数据。")

    # 2. 创建并设置新的月卡数据
    print(f"正在为用户 {test_user_id} 设置新的月卡数据...")
    month_card_cache = tqvip_pb2.TQMonthCard_Cache()

    # 设置月卡信息
    month_card_cache.player.monthcard.datetag = timeUtil.getdatenum(datetime.now()) # 使用 getdatenum
    month_card_cache.player.monthcard.starttime = timeUtil.gettimenum(datetime.now())
    month_card_cache.player.monthcard.endtime = timeUtil.add_time_to_timenum(timeUtil.gettimenum(datetime.now()), days=30) # 30天后

    # 设置周卡信息
    month_card_cache.player.weekcard.datetag = timeUtil.getdatenum(datetime.now()) # 使用 getdatenum
    month_card_cache.player.weekcard.starttime = timeUtil.gettimenum(datetime.now())   
    month_card_cache.player.weekcard.endtime = timeUtil.add_time_to_timenum(timeUtil.gettimenum(datetime.now()), days=7) # 7天后

    if manager.set_month_card_data(test_user_id, month_card_cache):
        print(f"用户 {test_user_id} 的月卡数据设置成功。")
    else:
        print(f"用户 {test_user_id} 的月卡数据设置失败。")

    # 3. 再次获取月卡数据，验证是否已保存
    print(f"再次获取用户 {test_user_id} 的月卡数据进行验证...")
    verified_month_card_message = manager.get_month_card_data(test_user_id)
    if verified_month_card_message:
        print(f"验证成功！获取到的月卡数据: {verified_month_card_message}")
        # 可以进一步断言数据是否与设置的一致
        assert verified_month_card_message.player.monthcard.datetag == timeUtil.getdatenum(datetime.now())
        print("数据一致性验证通过。")
    else:
        print(f"验证失败！未找到用户 {test_user_id} 的月卡数据。")

def test_TQPropData(user_id):
    vip_message = tqvip_pb2.PropsCache()
    vip_message.ParseFromString(bytes.fromhex("0A1708914E1212121008FFFFE883B1DE1610E0BBBCEEC1CC040A1708924E1212121008FFFFE883B1DE1610E0BBBCEEC1CC040A1708934E1212121008FFFFE883B1DE1610E0BBBCEEC1CC040A1708944E1212121008FFFFE883B1DE1610E0BBBCEEC1CC040A1708954E1212121008FFFFE883B1DE1610E0BBBCEEC1CC040A1708964E1212121008FFFFE883B1DE1610E0BBBCEEC1CC040A1708974E1212121008FFFFE883B1DE1610E0BBBCEEC1CC040A1708984E1212121008FFFFE883B1DE1610E0BBBCEEC1CC040A1708F54E1212121008FFFFE883B1DE1610E0BBBCEEC1CC040A1708F64E1212121008FFFFE883B1DE1610E0BBBCEEC1CC040A1708F74E1212121008FFFFE883B1DE1610E0BBBCEEC1CC040A1708DA4F1212121008FFFFE883B1DE1610E0BBBCEEC1CC040A1708F94E1212121008FFFFE883B1DE1610AABCBCEEC1CC040A1708DD4F1212121008FFFFE883B1DE1610AABCBCEEC1CC04"))
    print(f"解析后的 VIP 数据: {vip_message}")

    manager = TQPropManager()
    test_user_id = user_id

    print(f"\n--- 示例：TQPropManager 操作 (用户ID: {test_user_id}) ---")

    # 1. 尝试获取道具数据
    retrieved_prop_message = manager.get_prop_data(test_user_id)
    if retrieved_prop_message:
        print(f"用户 {test_user_id} 的道具数据获取成功。")
        print(f"解析后的道具数据: {retrieved_prop_message}")
    else:
        print(f"未找到用户 {test_user_id} 的道具数据。")

    # 2. 创建并设置新的道具数据
    print(f"正在为用户 {test_user_id} 设置新的道具数据...")
    prop_cache = tqvip_pb2.PropsCache()
    
    # 假设我们有一个道具 ID 为 1001，数量为 5
    prop_data = prop_cache.props.add()
    prop_data.prop_id = 1001
    prop_data.count = 5

    prop_data = prop_cache.props.add()
    prop_data.prop_id = 1002
    prop_data.count = 10

    if manager.set_prop_data(test_user_id, prop_cache):
        print(f"用户 {test_user_id} 的道具数据设置成功。")
    else:
        print(f"用户 {test_user_id} 的道具数据设置失败。")

    # 3. 再次获取道具数据，验证是否已保存
    print(f"再次获取用户 {test_user_id} 的道具数据进行验证...")
    verified_prop_message = manager.get_prop_data(test_user_id)
    if verified_prop_message:
        print(f"验证成功！获取到的道具数据: {verified_prop_message}")
        # 可以进一步断言数据是否与设置的一致
        assert len(verified_prop_message.props) == 2
        assert verified_prop_message.props[0].prop_id == 1001
        assert verified_prop_message.props[0].count == 5
        print("数据一致性验证通过。")
    else:
        print(f"验证失败！未找到用户 {test_user_id} 的道具数据。")

def test_timenum():
    print("\n--- 测试 gettimenum 和 add_time_to_timenum ---")
    now = datetime.now()
    timenum_now = timeUtil.gettimenum(now)
    print(f"当前时间: {now}")
    print(f"gettimenum 格式: {timenum_now}")

    parsed_dt = parse_timenum(timenum_now)
    print(f"解析回 datetime: {parsed_dt}")
    assert now.year == parsed_dt.year and \
           now.month == parsed_dt.month and \
           now.day == parsed_dt.day and \
           now.hour == parsed_dt.hour and \
           now.minute == parsed_dt.minute and \
           now.second == parsed_dt.second, "解析失败！"
    print("解析验证成功！")

    # 增加时间
    future_timenum = timeUtil.add_time_to_timenum(timenum_now, years=1, months=2, days=5)
    future_dt = parse_timenum(future_timenum)
    print(f"增加 1 年 2 月 5 天后的时间 (timenum): {future_timenum}")
    print(f"增加 1 年 2 月 5 天后的时间 (datetime): {future_dt}")

    # 验证增加后的时间
    expected_future_dt = now + relativedelta(years=1, months=2, days=5) if relativedelta else now + timedelta(days=5) # 简化验证
    print(f"预期增加后的时间 (datetime): {expected_future_dt}")
    # 注意：如果未安装 dateutil，直接比较可能不准确，因为月份加法逻辑不同
    if relativedelta:
        assert future_dt.year == expected_future_dt.year and \
               future_dt.month == expected_future_dt.month and \
               future_dt.day == expected_future_dt.day, "增加时间验证失败！"
        print("增加时间验证成功！")
    else:
        print("由于未安装 'python-dateutil'，年/月增加的验证可能不精确。")

if __name__ == '__main__' :
    # test_TQVIPData(1040720, None)
    # test_TQMonthCardData(1040720)
    test_TQPropData(1040720)
    