# L1 - SQL 速查

> 高频查询模板，按场景分组。替换 `<>` 占位符即可使用。game_id 默认 283。

---

## 对局查询

### 按游戏+日期查战绩

```sql
SELECT *
FROM dwd_game_combat_si
WHERE game_id = 283
  AND date = <yyyyMMdd>
LIMIT 2000
```

### 按玩家+日期查战绩

```sql
SELECT *
FROM dwd_game_combat_si
WHERE uid = <uid>
  AND date = <yyyyMMdd>
LIMIT 2000
```

### 按游戏+日期查胜率

```sql
SELECT
  game_id,
  COUNT(*) AS total,
  SUM(win) AS win_cnt,
  SUM(loss) AS loss_cnt,
  SUM(standoff) AS standoff_cnt,
  ROUND(CAST(SUM(win) AS DOUBLE) / COUNT(*), 4) AS win_rate
FROM dwd_game_combat_si
WHERE game_id = 283
  AND date = <yyyyMMdd>
GROUP BY game_id
```

### 按玩家+游戏查分数变动

```sql
SELECT
  uid,
  game_id,
  oldscore,
  scorediff,
  olddeposit,
  depositdiff,
  result_name
FROM dwd_game_combat_si
WHERE uid = <uid>
  AND game_id = 283
  AND date = <yyyyMMdd>
ORDER BY time_unix DESC
LIMIT 100
```

## 注意事项

- Presto 引擎：末尾不加 `;`
- VARCHAR 字段比较必须加引号（如 `game_id = 283`）
- `date` 为 INTEGER 分区字段，格式 yyyyMMdd（如 `20260511`）
- 建议加 `LIMIT` 防止返回过大结果集
