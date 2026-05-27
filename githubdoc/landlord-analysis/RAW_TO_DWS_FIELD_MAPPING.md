# 原始字段到 DWS 的精准映射

## 1. 说明

本文按“**原始源表字段** -> **直接生成的 DWS 表** -> **DWS 表作用**”整理。

为避免血缘混淆，本文将映射拆成两层：

1. **直接生成**
   原始字段直接出现在某张 DWS 的 `INSERT ... SELECT ...`、`JOIN`、`WHERE`、窗口函数或表达式中。
2. **间接影响**
   原始字段先进入上游 DWS，再被下游 DWS 消费。

如果你要查“某个原始字段最终影响了哪些分析表”，优先看“直接生成”，再顺着“间接影响链路”往下走。

---

## 2. 总体血缘总览

```text
olap_tcy_userapp_d_p_login1st
  -> dws_dq_daily_reg
     -> dws_dq_app_daily_reg
     -> dws_ddz_firstday_game

dwd_tcy_userlogin_si
  -> dws_dq_daily_login
     -> dws_dq_app_daily_reg

dim_channel_singletag_dict + dim_channel_category
  -> dws_channel_category_map
     -> dws_dq_app_daily_reg
     -> dws_dq_silver_logs

dwd_game_combat_si
  -> dws_ddz_daily_game
     -> dws_app_game_active
     -> dws_app_gamemode_active
     -> dws_ddz_app_game_stat
     -> dws_ddz_app_gamemode_stat
     -> dws_ddz_firstday_game
  -> dws_crazyddz_daily_game

dwd_silver_si
  -> dws_dq_silver_logs
  -> fin_flow_scene_dict（仅参与场景过滤）

dim_currency_op_config
  -> dq_currency_op_config
     -> dws_dq_silver_logs

dim_currency_guid_config
  -> dq_currency_guid_config
     -> dws_dq_silver_logs

dim_fin_flow_scene_dict
  -> fin_flow_scene_dict
```

---

## 3. 按原始源表拆解

## 3.1 `hive_catalog_cdh5.dm.olap_tcy_userapp_d_p_login1st`

### 直接生成

| 原始字段 | 生成的 DWS 表 | 去向 / 作用 | DWS 表作用 |
| ---- | ---- | ---- | ---- |
| `app_id` | `dws_dq_daily_reg` | 直接写入 `app_id` | 用户注册基础表，沉淀新增用户和注册时间 |
| `uid` | `dws_dq_daily_reg` | 直接写入 `uid` | 同上 |
| `dt` | `dws_dq_daily_reg` | 转成 `reg_date` | 同上 |
| `first_login_ts` | `dws_dq_daily_reg` | 转成 `reg_datetime` | 同上 |

### 间接影响

| 原始字段 | 间接影响的 DWS 表 | 影响方式 | DWS 表作用 |
| ---- | ---- | ---- | ---- |
| `app_id` / `uid` / `dt` / `first_login_ts` | `dws_dq_app_daily_reg` | 先进入 `dws_dq_daily_reg`，再补齐 APP 端维度 | APP 端注册宽表，留存分析的分母表 |
| `app_id` / `uid` / `dt` | `dws_ddz_firstday_game` | 通过 `reg_date = g.dt` 筛选“注册当天对局” | 新用户首日对局明细表 |

---

## 3.2 `tcy_dwd.dwd_tcy_userlogin_si`

### 直接生成

| 原始字段 | 生成的 DWS 表 | 去向 / 作用 | DWS 表作用 |
| ---- | ---- | ---- | ---- |
| `app_id` | `dws_dq_daily_login` | 直接写入 `app_id` | 用户每日登录聚合表，提供首登/末登/最频繁登录维度 |
| `uid` | `dws_dq_daily_login` | 直接写入 `uid` | 同上 |
| `dt` | `dws_dq_daily_login` | `DATE(dt)` -> `login_date`，`MIN(dt)` -> `first_login_time`，`MAX(dt)` -> `last_login_time` | 同上 |
| `time_unix` | `dws_dq_daily_login` | 配合 `MIN_BY` / `MAX_BY` 选首登、末登的维度值 | 同上 |
| `app_code` | `dws_dq_daily_login` | 生成 `first_app_code`、`last_app_code`、`most_freq_app_code`、`app_code_count` | 同上 |
| `channel_id` | `dws_dq_daily_login` | 生成 `first_channel_id`、`last_channel_id`、`most_freq_channel_id`、`channel_id_count` | 同上 |
| `group_id` | `dws_dq_daily_login` | 生成 `first_group_id`、`last_group_id`、`most_freq_group_id`、`group_id_count` | 同上 |

### 间接影响

| 原始字段 | 间接影响的 DWS 表 | 影响方式 | DWS 表作用 |
| ---- | ---- | ---- | ---- |
| `app_id` / `uid` / `dt` / `time_unix` / `app_code` / `channel_id` / `group_id` | `dws_dq_app_daily_reg` | 通过 `dws_dq_daily_login` 提供注册当天首登渠道、首登分端、首登版本、首日登录次数 | APP 端注册宽表，留存分析分母表 |

---

## 3.3 `tcy_dim.dim_channel_singletag_dict` + `hive_catalog_cdh5.dim.dim_channel_category`

### 直接生成

| 原始字段 | 生成的 DWS 表 | 去向 / 作用 | DWS 表作用 |
| ---- | ---- | ---- | ---- |
| `dim_channel_singletag_dict.channel_id` | `dws_channel_category_map` | 直接写入 `channel_id` | 渠道号到渠道分类的维表 |
| `dim_channel_singletag_dict.channel_type_id` | `dws_channel_category_map` | 作为 join 键 | 同上 |
| `dim_channel_category.channel_type_id` | `dws_channel_category_map` | 作为 join 键 | 同上 |
| `dim_channel_category.channel_category_id` | `dws_channel_category_map` | 直接写入 `channel_category_id` | 同上 |
| `dim_channel_category.channel_category_name` | `dws_channel_category_map` | 直接写入 `channel_category_name` | 同上 |
| `dim_channel_category.channel_category_tag_id` | `dws_channel_category_map` | 直接写入 `channel_category_tag_id` | 同上 |

### 间接影响

| 原始字段 | 间接影响的 DWS 表 | 影响方式 | DWS 表作用 |
| ---- | ---- | ---- | ---- |
| `channel_id`、`channel_category_id`、`channel_category_name`、`channel_category_tag_id` | `dws_dq_app_daily_reg` | 通过 `first_channel_id = channel_id` 补齐注册用户渠道分类 | APP 端注册宽表 |
| `channel_id`、`channel_category_name`、`channel_category_tag_id` | `dws_dq_silver_logs` | 通过 `s.channel_id = chn.channel_id` 补齐银子日志渠道分类 | 斗地主银子变动日志宽表 |

---

## 3.4 `tcy_dwd.dwd_game_combat_si`

这是项目里最关键的原始事实表，直接分出两条链：

1. `dws_ddz_daily_game`
2. `dws_crazyddz_daily_game`

### 3.4.1 直接生成 `dws_ddz_daily_game`

| 原始字段 | 生成的 DWS 字段 / 作用 | DWS 表作用 |
| ---- | ---- | ---- |
| `app_id` | `app_id` | 斗地主标准化对局明细表，是后续绝大多数 DWS 的基础事实表 |
| `dt` | `dt` | 同上 |
| `uid` | `uid` | 同上 |
| `time_unix` | `FROM_UNIXTIME(time_unix / 1000)` -> `game_datetime` | 同上 |
| `resultguid` | `resultguid` | 同上 |
| `timecost` | `timecost` | 同上 |
| `room_id` | `room_id`；并参与 `play_mode` 判定 | 同上 |
| `group_id` | `group_id`；并参与 `play_mode` 判定（区分比赛/积分） | 同上 |
| `basescore` | 参与生成 `room_base`、`real_magnification` | 同上 |
| `basedeposit` | 参与生成 `room_base`、`real_magnification` | 同上 |
| `score_fee` | 参与生成 `room_fee`、`diff_money_pre_tax`、`real_magnification` | 同上 |
| `fee` | 参与生成 `room_fee`、`diff_money_pre_tax`、`real_magnification` | 同上 |
| `room_currency_lower` | `room_currency_lower` | 同上 |
| `room_currency_upper` | `room_currency_upper` | 同上 |
| `robot` | `robot` | 同上 |
| `role` | `role` | 同上 |
| `chairno` | `chairno` | 同上 |
| `result_id` | `result_id` | 同上 |
| `oldscore` | 参与生成 `start_money` | 同上 |
| `olddeposit` | 参与生成 `start_money` | 同上 |
| `end_score` | 参与生成 `end_money` | 同上 |
| `end_deposit` | 参与生成 `end_money` | 同上 |
| `scorediff` | 参与生成 `diff_money_pre_tax`、`real_magnification` | 同上 |
| `depositdiff` | 参与生成 `diff_money_pre_tax`、`real_magnification` | 同上 |
| `cut` | `cut` | 同上 |
| `safebox_deposit` | `safebox_deposit` | 同上 |
| `magnification` | `magnification` | 同上 |
| `magnification_stacked` | `magnification_stacked` | 同上 |
| `magnification_subdivision` | 解析生成 `grab_landlord_bet`、`complete_victory_bet`、`bomb_bet` | 同上 |
| `channel_id` | `channel_id` | 同上 |
| `app_code` | `app_code` | 同上 |
| `game_id` | `game_id` | 同上 |

### 3.4.2 间接影响 `dws_ddz_daily_game` 下游 DWS

| 通过 `dws_ddz_daily_game` 间接影响的原始字段 | 下游 DWS 表 | 影响方式 | DWS 表作用 |
| ---- | ---- | ---- | ---- |
| `app_id`、`uid`、`dt`、`robot`、`group_id` | `dws_app_game_active` | 过滤 APP 真人用户后，按 `app_id + uid + dt` 去重 | 每日活跃用户表，用于整体留存 flag |
| `app_id`、`uid`、`dt`、`play_mode(room_id/group_id 派生)`、`robot`、`group_id` | `dws_app_gamemode_active` | 增加玩法维度去重 | 每日活跃用户×玩法表，用于同玩法留存 flag |
| `app_id`、`uid`、`dt`、`app_code`、`game_datetime(time_unix 派生)`、`result_id`、`timecost`、`magnification`、`real_magnification`、`bomb_bet`、`grab_landlord_bet`、`magnification_stacked`、`start_money`、`end_money`、`diff_money_pre_tax`、`room_fee`、`cut`、`room_id`、`play_mode`、`robot`、`group_id` | `dws_ddz_app_game_stat` | 按 `uid × dt × app_code` 聚合，计算局数、胜率、连胜连败、经济变化、高倍局等 | APP 端每日游戏行为统计宽表 |
| 上述同一批字段，再加 `play_mode` 维度 | `dws_ddz_app_gamemode_stat` | 按 `uid × dt × app_code × play_mode` 聚合 | 按玩法拆分的每日游戏行为宽表 |
| `dws_ddz_daily_game` 的全部标准化字段 + `dws_dq_daily_reg.reg_date` 匹配条件 | `dws_ddz_firstday_game` | 通过 `reg_date = g.dt` 仅保留注册当日对局 | 新用户首日对局明细表 |

### 3.4.3 直接生成 `dws_crazyddz_daily_game`

| 原始字段 | 生成的 DWS 字段 / 作用 | DWS 表作用 |
| ---- | ---- | ---- |
| `resultguid` | 分组主键；筛选目标对局 | 疯狂斗地主对局聚合表，解决单局多轮结算问题 |
| `uid` | 分组主键 | 同上 |
| `app_id` | `app_id` | 同上 |
| `game_id` | `game_id` | 同上 |
| `dt` | `DATE(dt)` -> `game_date` | 同上 |
| `date` | 作为候选 `resultguid` 与跨天范围过滤条件 | 同上 |
| `app_code` | `app_code` | 同上 |
| `group_id` | `group_id` | 同上 |
| `channel_id` | `channel_id` | 同上 |
| `room_id` | `room_id` | 同上 |
| `basedeposit` | `room_base` | 同上 |
| `fee` | `room_fee`；同时参与候选局与结算判定 | 同上 |
| `chairno` | `chairno` | 同上 |
| `robot` | `robot` | 同上 |
| `time_unix` | 生成 `start_datetime`、`end_datetime`；参与排序 | 同上 |
| `olddeposit` | `start_money`；并参与 `end_money` 计算 | 同上 |
| `depositdiff` | 生成 `game_win_loss`、`end_money`、`game_deposit_gdp`、`game_deposit_diff`、`total_deposit_diff`、`deposit_diff_path` | 同上 |
| `result_id` | 推导 `final_result_id`；参与排序 | 同上 |
| `cut` | 生成 `is_escape`；参与结算判定 | 同上 |
| `magnification` | 生成 `total_magnification`、`deposit_magnification_path` | 同上 |
| `timecost` | 生成 `total_time_cost` | 同上 |

> 注：`dws_crazyddz_daily_game` 的构建 SQL 使用了 `date` 字段做候选局过滤，而原始说明文档主要展示的是 `dt`。这里按实际构建 SQL 记录。

---

## 3.5 `tcy_dwd.dwd_silver_si`

### 直接生成

| 原始字段 | 生成的 DWS 表 | 去向 / 作用 | DWS 表作用 |
| ---- | ---- | ---- | ---- |
| `app_id` | `dws_dq_silver_logs` | `app_id`；同时参与和配置表 join | 斗地主银子变动日志宽表 |
| `dt` | `dws_dq_silver_logs` | 转成 `dt` 日期 | 同上 |
| `uid` | `dws_dq_silver_logs` | `uid` | 同上 |
| `app_code` | `dws_dq_silver_logs` | `app_code` | 同上 |
| `game_id` | `dws_dq_silver_logs` | `game_id`；同时作为过滤条件 | 同上 |
| `date_time` | `dws_dq_silver_logs` | `date_time` | 同上 |
| `op_id` | `dws_dq_silver_logs` | `op_id`；同时参与 `dq_currency_op_config` join | 同上 |
| `op_name` | `dws_dq_silver_logs` | `op_name` | 同上 |
| `op_type_id` | `dws_dq_silver_logs` | `op_type_id` | 同上 |
| `op_type_name` | `dws_dq_silver_logs` | `op_type_name` | 同上 |
| `silver_diff` | `dws_dq_silver_logs` | `silver_diff` | 同上 |
| `silver_deposit` | `dws_dq_silver_logs` | `silver_deposit` | 同上 |
| `silver_amount` | `dws_dq_silver_logs` | `silver_amount` | 同上 |
| `silver_balance` | `dws_dq_silver_logs` | `silver_balance` | 同上 |
| `silver_initial` | `dws_dq_silver_logs` | `silver_initial` | 同上 |
| `group_id` | `dws_dq_silver_logs` | `group_id` | 同上 |
| `channel_id` | `dws_dq_silver_logs` | `channel_id`；同时参与 `dws_channel_category_map` join | 同上 |
| `source_guid` | `dws_dq_silver_logs` | `source_guid`；同时参与 `dq_currency_guid_config` join | 同上 |
| `fin_flow_scn_id` | `fin_flow_scene_dict` | 仅用于子查询筛选有效 `scene_id` | 金流场景维表 |

### 间接影响

| 原始字段 | 间接影响的 DWS 表 | 影响方式 | DWS 表作用 |
| ---- | ---- | ---- | ---- |
| `channel_id` | `dws_dq_silver_logs` | 经 `dws_channel_category_map` 补齐 `channel_category_name` / `channel_category_tag_id` | 斗地主银子日志宽表 |
| `op_id`、`app_id` | `dws_dq_silver_logs` | 经 `dq_currency_op_config` 补齐 `settlement_type` | 同上 |
| `source_guid`、`app_id` | `dws_dq_silver_logs` | 经 `dq_currency_guid_config` 补齐 `guid_title` / `guid_type` | 同上 |

---

## 3.6 `hive_catalog_cdh5.dwd.dim_currency_op_config`

### 直接生成

| 原始字段 | 生成的 DWS 表 | 去向 / 作用 | DWS 表作用 |
| ---- | ---- | ---- | ---- |
| `app_id` | `dq_currency_op_config` | `app_id` | 货币操作类型配置维表 |
| `op_id` | `dq_currency_op_config` | `op_id` | 同上 |
| `op_name` | `dq_currency_op_config` | `op_name` | 同上 |
| `settlement_type` | `dq_currency_op_config` | `settlement_type` | 同上 |

### 间接影响

| 原始字段 | 间接影响的 DWS 表 | 影响方式 | DWS 表作用 |
| ---- | ---- | ---- | ---- |
| `app_id`、`op_id`、`settlement_type` | `dws_dq_silver_logs` | 通过 `s.app_id = op.app_id AND s.op_id = op.op_id` 补齐 `settlement_type` | 斗地主银子日志宽表 |

---

## 3.7 `hive_catalog_cdh5.dwd.dim_currency_guid_config`

### 直接生成

| 原始字段 | 生成的 DWS 表 | 去向 / 作用 | DWS 表作用 |
| ---- | ---- | ---- | ---- |
| `app_id` | `dq_currency_guid_config` | `app_id` | 货币奖池配置维表 |
| `guid` | `dq_currency_guid_config` | `guid` | 同上 |
| `guid_title` | `dq_currency_guid_config` | `guid_title` | 同上 |
| `guid_type` | `dq_currency_guid_config` | `guid_type` | 同上 |

### 间接影响

| 原始字段 | 间接影响的 DWS 表 | 影响方式 | DWS 表作用 |
| ---- | ---- | ---- | ---- |
| `app_id`、`guid`、`guid_title`、`guid_type` | `dws_dq_silver_logs` | 通过 `s.app_id = gc.app_id AND s.source_guid = gc.guid` 补齐奖池标题和类型 | 斗地主银子日志宽表 |

---

## 3.8 `hive_catalog_cdh5.dwd.dim_fin_flow_scene_dict`

### 直接生成

| 原始字段 | 生成的 DWS 表 | 去向 / 作用 | DWS 表作用 |
| ---- | ---- | ---- | ---- |
| `scene_id` | `fin_flow_scene_dict` | `scene_id`；并作为白名单来源 | 金流场景维表 |
| `scene_name` | `fin_flow_scene_dict` | `scene_name` | 同上 |
| `scene_remark` | `fin_flow_scene_dict` | `scene_remark` | 同上 |
| `fin_flow_type_id` | `fin_flow_scene_dict` | `fin_flow_type_id` | 同上 |
| `fin_flow_type_name` | `fin_flow_scene_dict` | `fin_flow_type_name` | 同上 |
| `fin_flow_type_remark` | `fin_flow_scene_dict` | `fin_flow_type_remark` | 同上 |

### 过滤参与字段

| 参与过滤的原始字段 | 生成的 DWS 表 | 作用 |
| ---- | ---- | ---- |
| `dwd_silver_si.fin_flow_scn_id` | `fin_flow_scene_dict` | 只保留银子日志中真实出现过的场景 ID |
| `dwd_silver_si.app_id` | `fin_flow_scene_dict` | 限定斗地主应用 |
| `dwd_silver_si.dt` | `fin_flow_scene_dict` | 限定统计时间范围 |

---

## 4. 按 DWS 表反查其直接原始来源

| DWS 表 | 直接原始来源 | 表作用 |
| ---- | ---- | ---- |
| `dws_dq_daily_reg` | `olap_tcy_userapp_d_p_login1st` | 用户注册基础表 |
| `dws_dq_daily_login` | `dwd_tcy_userlogin_si` | 用户每日登录聚合表 |
| `dws_channel_category_map` | `dim_channel_singletag_dict` + `dim_channel_category` | 渠道分类映射维表 |
| `dws_dq_app_daily_reg` | 无“单一原始表”直接生成；由 `dws_dq_daily_reg` + `dws_dq_daily_login` + `dws_channel_category_map` 组合生成 | APP 端注册宽表 |
| `dws_ddz_daily_game` | `dwd_game_combat_si` | 斗地主标准化对局明细表 |
| `dws_app_game_active` | 无单一原始表直接生成；直接上游是 `dws_ddz_daily_game` | 整体留存活跃 flag 表 |
| `dws_app_gamemode_active` | 无单一原始表直接生成；直接上游是 `dws_ddz_daily_game` | 同玩法留存活跃 flag 表 |
| `dws_ddz_app_game_stat` | 无单一原始表直接生成；直接上游是 `dws_ddz_daily_game` | APP 端每日行为统计宽表 |
| `dws_ddz_app_gamemode_stat` | 无单一原始表直接生成；直接上游是 `dws_ddz_daily_game` | 按玩法拆分的每日行为宽表 |
| `dws_ddz_firstday_game` | 无单一原始表直接生成；直接上游是 `dws_ddz_daily_game` + `dws_dq_daily_reg` | 新用户首日对局明细表 |
| `dws_dq_silver_logs` | `dwd_silver_si` + `dws_channel_category_map` + `dq_currency_op_config` + `dq_currency_guid_config` | 斗地主银子变动日志宽表 |
| `dws_crazyddz_daily_game` | `dwd_game_combat_si` | 疯狂斗地主多轮对局聚合表 |
| `dq_currency_op_config` | `dim_currency_op_config` | 货币操作类型配置维表 |
| `dq_currency_guid_config` | `dim_currency_guid_config` | 货币奖池配置维表 |
| `fin_flow_scene_dict` | `dim_fin_flow_scene_dict` + `dwd_silver_si.fin_flow_scn_id` 过滤 | 金流场景维表 |

---

## 5. 最重要的结论

如果只抓主链路，整个项目最核心的原始字段血缘只有 4 条：

1. `olap_tcy_userapp_d_p_login1st` 的注册字段 -> `dws_dq_daily_reg`
2. `dwd_tcy_userlogin_si` 的登录字段 -> `dws_dq_daily_login`
3. `dwd_game_combat_si` 的对局字段 -> `dws_ddz_daily_game`
4. `dwd_silver_si` 的银子流水字段 -> `dws_dq_silver_logs`

其中最关键的事实中间表是：

- `dws_ddz_daily_game`

因为它继续派生出了：

- `dws_app_game_active`
- `dws_app_gamemode_active`
- `dws_ddz_app_game_stat`
- `dws_ddz_app_gamemode_stat`
- `dws_ddz_firstday_game`

如果后续你要做字段血缘排查，优先从 `dwd_game_combat_si -> dws_ddz_daily_game` 这条链开始看，价值最高。
