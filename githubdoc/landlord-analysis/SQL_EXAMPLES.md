# SQL 示例汇总

## 说明

本文档统一存放 `landlord-analysis` 项目的示例 SQL。

记录格式固定为：

- 查询表
- 用处
- SQL
- 备注

后续新增示例 SQL，统一追加到这份文件中。

### 当前执行环境约束

为保证示例 SQL 可以直接执行，统一遵守以下约定：

1. 由于权限限制，示例 SQL 不直接使用 `tcy_temp.xxx`，统一改写为可查询副本表 `temp_xxx`。
2. 涉及日期过滤或日期比较时，必须显式做日期转换。
3. 对 `dt` 这类日期字段，优先写成 `CAST(dt AS DATE)` 后再与 `DATE 'YYYY-MM-DD'` 比较。
4. 对 `reg_date` 这类在当前环境中按字符串处理的字段，也必须显式写成 `CAST(reg_date AS DATE)` 后再参与比较、关联或 `DATE_ADD`。

如果后续继续新增 SQL 示例，默认都按这套可执行约定来写，避免再次出现“表名可读但不可执行”或“日期类型不匹配”的问题。

---

## 示例 1：查询 `temp_dws_ddz_daily_game`

### 查询表

- `temp_dws_ddz_daily_game`

### 用处

统计指定时间范围内，APP 端真人用户在不同玩法下的对局量、人数、平均时长、胜率和平均倍数。

适用场景：

- 快速了解某段时间内各玩法整体表现
- 比较经典 / 不洗牌 / 癞子玩法的活跃度和胜负体验
- 检查对局表是否正常产出数据

### SQL

```sql
SELECT
    dt,
    play_mode,
    CASE play_mode
        WHEN 1 THEN '经典'
        WHEN 2 THEN '不洗牌'
        WHEN 3 THEN '癞子'
        WHEN 4 THEN '积分'
        WHEN 5 THEN '比赛'
        WHEN 6 THEN '好友房'
        ELSE '其他'
    END AS play_mode_name,
    COUNT(*) AS game_count,
    COUNT(DISTINCT uid) AS user_count,
    ROUND(AVG(timecost), 1) AS avg_timecost,
    ROUND(
        SUM(CASE WHEN result_id = 1 THEN 1 ELSE 0 END) * 100.0 / COUNT(*),
        2
    ) AS win_rate,
    ROUND(AVG(magnification), 2) AS avg_magnification
FROM temp_dws_ddz_daily_game
WHERE app_id = 1880053
  AND CAST(dt AS DATE) BETWEEN DATE '2026-04-01' AND DATE '2026-04-07'
  AND robot != 1
  AND group_id IN (6, 66, 8, 88, 33, 44, 77, 99)
GROUP BY dt, play_mode
ORDER BY dt, play_mode
```

### 备注

- 表名使用 `temp_dws_ddz_daily_game`，这是当前环境下可执行的副本表名。
- `CAST(dt AS DATE)`：这是当前环境下建议的日期过滤写法，避免日期类型不匹配。
- `robot != 1`：只看真人玩家。
- `group_id IN (6, 66, 8, 88, 33, 44, 77, 99)`：只看 APP 端用户。
- 如果只想看某一种玩法，可以追加条件，例如 `AND play_mode = 1`。
- 如果想看明细而不是聚合，可以去掉 `GROUP BY`，直接选择 `uid`、`game_datetime`、`resultguid`、`room_id`、`result_id` 等字段。

### 明细查询变体

用途：

查看某一天某个玩法下的真实对局明细，便于排查单局数据。

```sql
SELECT
    app_id,
    dt,
    uid,
    game_datetime,
    resultguid,
    room_id,
    play_mode,
    role,
    result_id,
    start_money,
    end_money,
    diff_money_pre_tax,
    magnification,
    real_magnification
FROM tcy_temp.dws_ddz_daily_game
WHERE app_id = 1880053
  AND CAST(dt AS DATE) = DATE '2026-04-01'
  AND play_mode = 1
  AND robot != 1
ORDER BY game_datetime
LIMIT 100;
```
