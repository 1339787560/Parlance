# SQL 新手文档

## 1. 这份文档讲什么

这是一份面向 SQL 初学者的入门文档，结合 `landlord-analysis` 项目的实际场景，说明以下几类操作是如何完成的：

1. 单表查询
2. 多表关联查询
3. 聚合统计查询
4. 建表
5. 用 `INSERT INTO ... SELECT ...` 生成中间表
6. DWS 场景下常见的增量更新方式

本文默认你看到的是类似 StarRocks / Hive 风格的 SQL。

为了让示例更贴近你当前可执行的环境，本文统一采用以下约定：

1. 原文档中的 `tcy_temp.xxx` 示例表，统一改写为你可查询的副本表 `temp_xxx`
2. `reg_date` 在你的环境中按 `VARCHAR` 处理，因此凡是涉及日期比较、`DATE_ADD`、与 `DATE` 字段关联时，都显式写成 `CAST(reg_date AS DATE)`
3. `dt` 在当前可执行环境中也建议显式写成 `CAST(dt AS DATE)` 后再参与日期过滤或日期比较，避免类型不匹配
4. 凡是新的示例 SQL，默认优先给出“当前环境可直接执行”的版本，而不是原始文档里的逻辑表名版本

---

## 2. 先理解 SQL 在做什么

可以把 SQL 理解成“从表里取数据，并按要求加工”的语言。

最常见的工作流是：

```text
原始表
  ↓ 过滤
  ↓ 选择字段
  ↓ 关联其他表
  ↓ 聚合统计
  ↓ 结果输出
```

例如在这个项目里：

- 从注册表里取新增用户
- 关联登录表判断次日有没有回来
- 关联对局表分析首日行为
- 最终得到留存率、胜率、连败等指标

---

## 3. 单表查询是怎么完成的

## 3.1 最基础：查询整张表的部分字段

```sql
SELECT
    uid,
    reg_date,
    reg_datetime
FROM temp_dws_dq_daily_reg
WHERE app_id = 1880053
  AND CAST(reg_date AS DATE) BETWEEN DATE '2026-02-10' AND DATE '2026-02-12';
```

这条 SQL 做了三件事：

1. 从 `temp_dws_dq_daily_reg` 这张表读取数据
2. 只保留 `uid`、`reg_date`、`reg_datetime` 三列
3. 只保留 `app_id = 1880053` 且日期在范围内的数据

### 常见语法解释

- `SELECT`：要取哪些列
- `FROM`：从哪张表取
- `WHERE`：筛选条件

---

## 3.2 给字段起别名

```sql
SELECT
    uid AS user_id,
    reg_date AS register_date
FROM temp_dws_dq_daily_reg
WHERE app_id = 1880053;
```

`AS` 的作用是重命名输出列，方便阅读结果。

---

## 3.3 对字段做简单计算

```sql
SELECT
    uid,
    start_money,
    end_money,
    end_money - start_money AS diff_money
FROM temp_dws_ddz_firstday_game
WHERE app_id = 1880053
  AND dt = '2026-02-10';
```

这类写法常用于：

- 计算输赢
- 计算时长
- 计算金额差

---

## 3.4 用 `CASE WHEN` 做分类

```sql
SELECT
    uid,
    CASE
        WHEN reg_group_id IN (8, 88) THEN 'iOS'
        WHEN reg_group_id IN (6, 66, 33, 44, 77, 99) THEN 'Android'
        ELSE '其他'
    END AS platform
FROM temp_dws_dq_app_daily_reg
WHERE app_id = 1880053;
```

`CASE WHEN` 可以把原始字段映射成分析维度，是分析 SQL 里最常见的语法之一。

---

## 4. 聚合查询是怎么完成的

聚合的意思是：把多行数据汇总成统计结果。

常见聚合函数：

- `COUNT(*)`：统计行数
- `COUNT(DISTINCT uid)`：统计去重用户数
- `SUM(x)`：求和
- `AVG(x)`：平均值
- `MAX(x)`：最大值
- `MIN(x)`：最小值

## 4.1 按日期统计新增用户数

```sql
SELECT
    reg_date,
    COUNT(DISTINCT uid) AS reg_user_count
FROM temp_dws_dq_daily_reg
WHERE app_id = 1880053
  AND CAST(reg_date AS DATE) BETWEEN DATE '2026-02-10' AND DATE '2026-02-15'
GROUP BY reg_date
ORDER BY reg_date;
```

### 这里发生了什么

1. 先筛选出目标日期的数据
2. 按 `reg_date` 分组
3. 每组统计去重用户数

### 常见语法解释

- `GROUP BY`：按哪些字段分组
- `ORDER BY`：结果按什么顺序排列

---

## 4.2 按平台统计用户数

```sql
SELECT
    CASE
        WHEN reg_group_id IN (8, 88) THEN 'iOS'
        WHEN reg_group_id IN (6, 66, 33, 44, 77, 99) THEN 'Android'
        ELSE '其他'
    END AS platform,
    COUNT(DISTINCT uid) AS user_count
FROM temp_dws_dq_app_daily_reg
WHERE app_id = 1880053
GROUP BY
    CASE
        WHEN reg_group_id IN (8, 88) THEN 'iOS'
        WHEN reg_group_id IN (6, 66, 33, 44, 77, 99) THEN 'Android'
        ELSE '其他'
    END;
```

这类 SQL 的目标是把明细数据“压缩成报表统计”。

---

## 5. 多表查询是怎么完成的

多表查询的核心是 `JOIN`。

可以把它理解为：根据某些共同字段，把两张表拼起来。

常见类型：

- `INNER JOIN`：两边都匹配到才保留
- `LEFT JOIN`：保留左表全部数据，右表匹配不到就补 `NULL`

---

## 5.1 `INNER JOIN`：只保留匹配成功的数据

```sql
SELECT
    g.uid,
    g.dt,
    r.reg_date
FROM temp_dws_ddz_daily_game g
INNER JOIN temp_dws_dq_daily_reg r
    ON r.app_id = g.app_id
    AND r.uid = g.uid
    AND CAST(r.reg_date AS DATE) = g.dt
WHERE g.app_id = 1880053;
```

这条 SQL 表示：

- 先看对局表 `g`
- 再找注册表 `r`
- 只有当 `app_id`、`uid`、`日期` 都匹配上时，才保留这行

这正是 `dws_ddz_firstday_game` 的核心思路：筛出“注册当天的对局”。

---

## 5.2 `LEFT JOIN`：保留左表全部数据

```sql
SELECT
    r.uid,
    r.reg_date,
    l.login_date
FROM temp_dws_dq_app_daily_reg r
LEFT JOIN temp_dws_dq_daily_login l
    ON l.app_id = r.app_id
    AND l.uid = r.uid
    AND l.login_date = DATE_ADD(CAST(r.reg_date AS DATE), INTERVAL 1 DAY)
WHERE r.app_id = 1880053;
```

这条 SQL 用来判断：

- 每个注册用户
- 次日是否有登录记录

如果右表 `l` 没匹配到，`login_date` 就会是 `NULL`。

这就是留存分析最常见的写法。

### 为什么留存分析常用 `LEFT JOIN`

因为我们必须保留“没有回来的人”，否则分母会被吃掉，留存率就算错了。

---

## 6. 多表聚合查询是怎么完成的

这类 SQL 最常见于留存分析。

## 6.1 计算次留

```sql
SELECT
    r.reg_date,
    COUNT(DISTINCT r.uid) AS reg_users,
    COUNT(DISTINCT CASE
        WHEN l.login_date = DATE_ADD(CAST(r.reg_date AS DATE), INTERVAL 1 DAY) THEN r.uid
    END) AS retained_users,
    ROUND(
        COUNT(DISTINCT CASE
            WHEN l.login_date = DATE_ADD(CAST(r.reg_date AS DATE), INTERVAL 1 DAY) THEN r.uid
        END) * 100.0 / COUNT(DISTINCT r.uid),
        2
    ) AS day1_rate
FROM temp_dws_dq_app_daily_reg r
LEFT JOIN temp_dws_dq_daily_login l
    ON l.app_id = r.app_id
    AND l.uid = r.uid
    AND l.login_date = DATE_ADD(CAST(r.reg_date AS DATE), INTERVAL 1 DAY)
WHERE r.app_id = 1880053
  AND r.is_login_log_missing = 0
GROUP BY r.reg_date
ORDER BY r.reg_date;
```

### 这类 SQL 的思路

1. 左表 `r` 提供“分母”，也就是注册用户
2. 右表 `l` 提供“分子候选”，也就是次日是否登录
3. 用 `CASE WHEN` 只统计真正回来的用户
4. 分子除以分母，得到留存率

---

## 6.2 关联行为表分析留存

```sql
SELECT
    CASE
        WHEN g.game_count IS NULL OR g.game_count = 0 THEN '0局'
        WHEN g.game_count = 1 THEN '1局'
        WHEN g.game_count BETWEEN 2 AND 5 THEN '2-5局'
        ELSE '6局+'
    END AS game_count_group,
    COUNT(DISTINCT r.uid) AS user_count,
    ROUND(
        COUNT(DISTINCT CASE
            WHEN l.login_date = DATE_ADD(CAST(r.reg_date AS DATE), INTERVAL 1 DAY) THEN r.uid
        END) * 100.0 / COUNT(DISTINCT r.uid),
        2
    ) AS day1_rate
FROM temp_dws_dq_app_daily_reg r
LEFT JOIN temp_dws_ddz_app_game_stat g
    ON g.app_id = r.app_id
    AND g.uid = r.uid
    AND g.dt = CAST(r.reg_date AS DATE)
LEFT JOIN temp_dws_dq_daily_login l
    ON l.app_id = r.app_id
    AND l.uid = r.uid
    AND l.login_date = DATE_ADD(CAST(r.reg_date AS DATE), INTERVAL 1 DAY)
WHERE r.app_id = 1880053
  AND r.is_login_log_missing = 0
GROUP BY 1
ORDER BY 1;
```

这条 SQL 的意思是：

- 用注册表提供用户集合
- 用行为统计表提供“首日玩了几局”
- 用登录表提供“次日是否回来”
- 最后按“首日对局数分层”输出留存率

这就是典型的“多表聚合分析 SQL”。

---

## 7. 用 `WITH` 写复杂 SQL

当 SQL 很复杂时，通常先把中间结果拆成几段，这时会用到 `WITH`，也叫 CTE。

## 7.1 例子

```sql
WITH reg_users AS (
    SELECT
        app_id,
        uid,
        reg_date
    FROM temp_dws_dq_app_daily_reg
    WHERE app_id = 1880053
),
next_day_login AS (
    SELECT
        app_id,
        uid,
        login_date
    FROM temp_dws_dq_daily_login
)
SELECT
    r.reg_date,
    COUNT(DISTINCT r.uid) AS reg_users,
    COUNT(DISTINCT CASE
        WHEN l.login_date = DATE_ADD(CAST(r.reg_date AS DATE), INTERVAL 1 DAY) THEN r.uid
    END) AS retained_users
FROM reg_users r
LEFT JOIN next_day_login l
    ON l.app_id = r.app_id
    AND l.uid = r.uid
GROUP BY r.reg_date;
```

### 为什么要用 `WITH`

优点有三个：

1. SQL 更容易读
2. 中间逻辑更容易检查
3. 多段逻辑更容易复用

---

## 8. 建表是怎么完成的

建表用 `CREATE TABLE`。

## 8.1 一个基础建表示例

```sql
CREATE TABLE temp_example_user_stat (
  `app_id` int NOT NULL COMMENT "应用ID",
  `uid` int NOT NULL COMMENT "用户ID",
  `dt` date NOT NULL COMMENT "日期",
  `game_count` int NULL COMMENT "对局数"
) ENGINE=OLAP
DUPLICATE KEY(`app_id`, `uid`, `dt`)
COMMENT "示例用户统计表"
PARTITION BY RANGE(`dt`) (
    START ("2026-01-01") END ("2027-01-01") EVERY (INTERVAL 1 DAY)
)
DISTRIBUTED BY HASH(`uid`) BUCKETS 8
PROPERTIES (
    "replication_num" = "1",
    "compression" = "LZ4"
);
```

### 这些部分分别是什么意思

- 列定义：表有哪些字段、字段类型是什么
- `ENGINE=OLAP`：使用 OLAP 引擎
- `DUPLICATE KEY`：表的明细主键模式
- `COMMENT`：表说明
- `PARTITION BY RANGE(dt)`：按日期分区
- `DISTRIBUTED BY HASH(uid)`：按 `uid` 分桶
- `PROPERTIES`：存储和分区配置

---

## 8.2 什么时候需要建表

一般有三种情况：

1. 做新的分析中间表
2. 做新的聚合宽表
3. 为了提升查询性能，把高频逻辑提前算好

比如：

- `dws_ddz_daily_game`
- `dws_ddz_app_game_stat`
- `dws_app_game_active`

都属于这种场景。

---

## 9. 如何把查询结果写入新表

这一步通常用：

```sql
INSERT INTO ... SELECT ...
```

## 9.1 最常见模式

```sql
INSERT INTO temp_example_user_stat
SELECT
    app_id,
    uid,
    dt,
    COUNT(*) AS game_count
FROM temp_dws_ddz_daily_game
WHERE app_id = 1880053
GROUP BY app_id, uid, dt;
```

这条 SQL 的意思是：

1. 从 `dws_ddz_daily_game` 取数据
2. 统计每个用户每天的对局数
3. 把结果写入 `temp_example_user_stat`

这就是中间表生成最典型的方式。

---

## 9.2 项目里的真实模式：从原始对局表生成 DWS

```sql
INSERT INTO temp_dws_ddz_daily_game
SELECT
    IFNULL(app_id, 1880053),
    dt,
    uid,
    FROM_UNIXTIME(time_unix / 1000) AS game_datetime,
    resultguid,
    timecost,
    room_id,
    CASE
        WHEN room_id IN (742,420,4484,12074,6314,11168,10336,16445) THEN 1
        WHEN room_id IN (421,22039,22040,22041,22042) THEN 2
        WHEN room_id IN (13176,13177,13178) THEN 3
        ELSE 0
    END AS play_mode
FROM temp_dwd_game_combat_si
WHERE game_id = 53;
```

这不是简单复制数据，而是在写入前做了加工：

- 时间格式转换
- 玩法分类映射
- 字段统一

这就是“建 DWS 表”的典型方式。

---

## 10. 如何生成聚合宽表

聚合宽表通常来源于明细表，通过 `GROUP BY` 生成。

## 10.1 示例：用户每日行为统计表

```sql
INSERT INTO temp_dws_ddz_app_game_stat
SELECT
    app_id,
    uid,
    dt,
    app_code,
    COUNT(*) AS game_count,
    SUM(timecost) AS total_play_seconds,
    ROUND(AVG(timecost), 1) AS avg_game_seconds,
    COUNT(CASE WHEN result_id = 1 THEN 1 END) AS win_count,
    COUNT(CASE WHEN result_id = 2 THEN 1 END) AS lose_count,
    ROUND(COUNT(CASE WHEN result_id = 1 THEN 1 END) * 100.0 / COUNT(*), 2) AS win_rate
FROM temp_dws_ddz_daily_game
WHERE robot != 1
  AND group_id IN (6, 66, 8, 88, 33, 44, 77, 99)
GROUP BY app_id, uid, dt, app_code;
```

### 这里的关键思路

- 原表是一局一行
- 目标表是“一天一个用户一行”
- 所以必须 `GROUP BY app_id, uid, dt, app_code`

这是“明细变宽表”的核心方法。

---

## 11. 常见 SQL 模板

## 11.1 查单表明细

```sql
SELECT
    col1,
    col2
FROM table_name
WHERE 条件;
```

## 11.2 查聚合统计

```sql
SELECT
    group_col,
    COUNT(*) AS cnt
FROM table_name
WHERE 条件
GROUP BY group_col;
```

## 11.3 两表关联

```sql
SELECT
    a.col1,
    b.col2
FROM table_a a
LEFT JOIN table_b b
    ON a.id = b.id;
```

## 11.4 建表

```sql
CREATE TABLE table_name (
    col1 int,
    col2 varchar(32)
);
```

## 11.5 查询结果写入表

```sql
INSERT INTO table_name
SELECT ...
FROM source_table;
```

---

## 12. 新手最容易犯的错误

## 12.1 忘记写分区条件

例如大表按日期分区，却没有写 `WHERE dt = ...` 或 `WHERE dt BETWEEN ...`，会导致扫全表。

---

## 12.2 用错 `JOIN`

- 应该保留全量用户时，用成了 `INNER JOIN`
- 结果把没登录、没对局的用户过滤掉了

留存分析里通常优先考虑 `LEFT JOIN`。

---

## 12.3 `COUNT(uid)` 和 `COUNT(DISTINCT uid)` 混淆

- `COUNT(uid)`：统计行数
- `COUNT(DISTINCT uid)`：统计去重用户数

做用户分析时，很多场景必须用 `COUNT(DISTINCT uid)`。

---

## 12.4 聚合字段没写进 `GROUP BY`

错误示意：

```sql
SELECT reg_date, uid, COUNT(*)
FROM temp_dws_dq_daily_reg
GROUP BY reg_date;
```

这里 `uid` 没聚合，也没在 `GROUP BY` 里，通常会报错或产生不符合预期的结果。

---

## 12.5 没处理 `NULL`

例如：

```sql
CASE WHEN g.game_count = 0 THEN '0局' END
```

如果 `g.game_count` 是 `NULL`，这条判断不会命中。

更稳妥的写法是：

```sql
CASE
    WHEN g.game_count IS NULL OR g.game_count = 0 THEN '0局'
END
```

---

## 13. 在这个项目里，建议按什么顺序学 SQL

建议从简单到复杂：

1. 先学单表 `SELECT ... FROM ... WHERE ...`
2. 再学 `GROUP BY`
3. 再学 `LEFT JOIN`
4. 再学 `CASE WHEN`
5. 再学 `INSERT INTO ... SELECT ...`
6. 最后学 `WITH`、窗口函数、连续分组等复杂写法

如果结合本项目，建议阅读顺序是：

1. `dws_dq_daily_reg`
2. `dws_dq_daily_login`
3. `dws_dq_app_daily_reg`
4. `dws_ddz_daily_game`
5. `dws_ddz_app_game_stat`
6. `docs/retention/retention-global.md`

这样会比较容易理解“原始表 -> DWS -> 分析 SQL”的完整链路。

---

## 14. 一句话总结

SQL 的本质就是：

- 从表里取数据
- 按条件过滤
- 和别的表拼起来
- 做统计
- 必要时把结果再写回一张新表

在这个项目里，单表查询、多表聚合、建表、生成 DWS 中间表，本质上都是这一套流程的不同复杂度版本。
