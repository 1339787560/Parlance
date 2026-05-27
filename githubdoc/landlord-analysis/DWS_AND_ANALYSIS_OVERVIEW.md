# landlord-analysis 项目说明

## 0. 表命名规范是什么？为什么有 `olap_`、`dwd_`、`dws_`？

这个项目里，文档明确写出来的数据库表命名规范主要有两类前缀：

- `dws_`：DWS 层中间表
- `dwd_`：DWD 层明细表

这代表的是数据仓库分层，而不是单纯的命名喜好。

### 0.1 `dwd_` 是什么

`DWD` 可以理解为 **Data Warehouse Detail**，即“明细层”。

这类表通常直接承接业务日志或事实明细，特点是：

- 粒度细
- 行数大
- 更接近原始业务行为
- 更适合作为下游加工输入

项目中的例子：

- `dwd_game_combat_si`：原始对局日志
- `dwd_tcy_userlogin_si`：原始登录日志
- `dwd_silver_si`：原始银子流水日志

### 0.2 `dws_` 是什么

`DWS` 可以理解为 **Data Warehouse Service**，即“服务层 / 汇总服务层”。

这类表是在 `dwd_` 基础上做清洗、统一、聚合后的中间层，特点是：

- 口径更统一
- 查询更高效
- 更适合直接写分析 SQL
- 专门为留存、行为分析、报表服务

项目中的例子：

- `dws_ddz_daily_game`
- `dws_ddz_app_game_stat`
- `dws_dq_app_daily_reg`
- `dws_app_game_active`

### 0.3 `olap_` 又是什么

`olap_` 不是这个项目自己定义的 DWS / DWD 分层前缀，而是**上游已有表**的命名。

项目里的例子：

- `olap_tcy_userapp_d_p_login1st`

它位于上游库：

- `hive_catalog_cdh5.dm.olap_tcy_userapp_d_p_login1st`

这说明它不是项目自己在 `tcy_temp` 下构建的中间表，而是外部已有的 OLAP / DM 风格产物，这个项目只是把它拿来作为源表使用。

### 0.4 为什么会同时出现三种前缀

因为这个项目的数据不是从单一层级来的，而是混合使用了：

1. 上游已有结果表
   例如 `olap_` 表
2. 上游原始明细事实表
   例如 `dwd_` 表
3. 项目自己构建的分析中间层
   例如 `dws_` 表

所以整体链路大致是：

```text
上游现成表（olap_）
        ↓
原始明细表（dwd_）
        ↓
项目中间层（dws_）
        ↓
分析 SQL / 报告
```

### 0.5 一眼怎么看懂表名

可以粗略把表名理解成：

```text
<层级前缀>_<业务域缩写>_<主题>_<粒度/特征>
```

例如：

- `dwd_game_combat_si`
  - `dwd`：明细层
  - `game_combat`：对局战绩主题
  - `si`：明细/增量类后缀

- `dws_ddz_daily_game`
  - `dws`：服务层
  - `ddz`：斗地主
  - `daily_game`：每日对局

- `dws_dq_app_daily_reg`
  - `dws`：服务层
  - `dq`：业务域缩写
  - `app_daily_reg`：APP 端每日注册宽表

### 0.6 为什么这种命名有用

核心作用是让人一眼知道这张表该怎么用：

- 看到 `dwd_`：知道它是底层明细，适合做加工，不适合反复直接分析
- 看到 `dws_`：知道它是分析友好的中间层，适合直接关联和聚合
- 看到 `olap_`：知道它多半是外部已有结果表，不一定遵循本项目自建规则

## 1. dws 是什么？作用是什么？

在 `landlord-analysis` 项目里，`dws` 不是某一张表，而是一层数据仓库中间层，可以理解成“汇总/服务层”。它位于原始表 `raw` 和分析 SQL / 报告之间，项目文档里也直接称其为 “DWS 中间表层”。

它的核心作用有四个：

1. **统一分析口径**

   将斗地主不同玩法中的异构字段统一成一致的分析字段。例如：
   - 统一货币字段：`start_money`、`end_money`、*`diff_money_pre_tax`*
   - 统一房间字段：`room_base`、`room_fee`
   - 将 `room_id` 映射为 `play_mode`
   - 将 JSON 字段 `magnification_subdivision` 拆成独立列：`grab_landlord_bet`、`complete_victory_bet`、`bomb_bet`
2. **预聚合，提升查询效率**

   原始登录表、对局表粒度很细，直接做留存分析和行为分析成本很高。DWS 会预先聚合成更适合分析的粒度，例如：
   - `uid × login_date`
   - `uid × dt × app_code`
   - `uid × dt × app_id`
3. **生成分析专用快照和活跃标记**

   比如：
   - `dws_ddz_firstday_game`：只保留注册当日对局
   - `dws_app_game_active`：只保留“当日是否有对局”
   - `dws_app_gamemode_active`：只保留“当日是否在某玩法有对局”
   这些表本质上是在为留存计算和分玩法分析服务。
4. **为 StarRocks 的高频分析做性能优化**

   这些 DWS 表普遍采用：
   - 按天分区
   - 按 `uid` hash 分桶
   - `colocate_with = group_daily_data`
   明显是为了提高大规模留存分析、行为分析、关联查询的性能。

## 2. 作者分析斗地主数据的思路，作用是什么，依赖哪些关键字段？

作者的分析主线可以概括为：

- **四个分析视角**
- **三个分析层级**
- **若干专项下钻**

### 2.1 四个核心分析视角

#### 视角一：用户属性视角

作用：看“谁更容易留存/流失”。

典型分析内容：

- 渠道分类留存
- iOS / Android 留存对比
- Cocos-Lua / Cocos-Creator 客户端留存对比
- 注册时段差异

关键字段：

- `channel_category_name`
- `channel_category_tag_id`
- `reg_group_id`
- `reg_app_code`
- `reg_datetime`
- `login_date`

#### 视角二：投入度视角

作用：看“用户首日玩了多少”对后续留存的影响。这是作者最强调的一条主线。

典型分析内容：

- 首日对局数分层
- 首日总时长 / 平均时长
- 首日体验是否形成“继续玩”的行为惯性
- 是否尝试多个玩法

关键字段：

- `game_count`
- `total_play_seconds`
- `avg_game_seconds`
- `play_modes`
- `mode_count`

#### 视角三：胜负体验视角

作用：看“输赢体验是否影响用户流失”。

典型分析内容：

- 首日胜率
- 连败长度
- 首局胜负
- 地主 / 农民角色偏好
- 炸弹、高倍局、抢地主倍数等体验因子

关键字段：

- `win_rate`
- `result_id`
- `max_lose_streak`
- `role`
- `magnification`
- `real_magnification`
- `bomb_bet`
- `grab_landlord_bet`
- `complete_victory_bet`

#### 视角四：经济状态视角

作用：看“银子压力、破产风险、房间门槛”是否驱动流失。

典型分析内容：

- 首日净输赢
- 破产状态判断
- 高倍局输赢经历
- 房间底注压力
- 携银和房间门槛的匹配问题

关键字段：

- `total_diff_money`
- `money_valley`
- `start_money`
- `end_money`
- `room_base`
- `room_fee`
- `high_multi_games`
- `high_multi_wins`
- `high_multi_losses`

### 2.2 三个分析层级

#### 第一层：全局层分析

作用：建立整体留存基线，给所有影响因子排序，找最重要的流失驱动因素。

主要依赖表：

- `dws_dq_app_daily_reg`
- `dws_dq_daily_login`
- `dws_ddz_app_game_stat`
- `dws_ddz_firstday_game`

典型问题：

- 整体新增留存水平如何？
- 首日对局数、胜率、连败、经济变化，谁最影响留存？

#### 第二层：分玩法层分析

作用：比较不同玩法的留存差异，并分析玩法内部的驱动因子差异。

主要分析玩法：

- 经典
- 不洗牌
- 癞子

主要依赖字段：

- `play_mode`
- `room_id`
- `magnification`
- `result_id`
- `bomb_bet`
- `game_count`
- `win_rate`

进一步分析内容：

- 哪个玩法更留人
- 同玩法留存 vs 整体留存
- 各玩法内部“倍数、胜率、局数、炸弹体验”的差异
- 首局选了什么玩法
- 用户是否多玩法探索

这里的核心辅助表是：

- `dws_ddz_firstday_game`
- `dws_app_gamemode_active`

#### 第三层：分客户端层分析

作用：比较 Cocos-Lua 与 Cocos-Creator 客户端差异，并尝试识别稳定性问题。

主要依赖字段：

- `reg_app_code`
- `first_app_code`
- `app_code`
- `first_day_login_cnt`
- `escape_count`
- `timecost`
- `reg_group_id`

典型分析内容：

- 不同客户端的 Day1 / Day7 留存差异
- 分平台看 Lua 和 Creator 的差异
- 首日登录次数是否异常偏高（疑似闪退 / 掉线）
- 对局时长是否异常（疑似卡顿 / 网络问题）
- 是否存在版本切换行为

这里的关注点已经不只是“产品玩法”，而是“技术实现是否影响留存”。

### 2.3 作者的总体分析方法论

如果把作者的方法抽象一下，大概是这样：

1. 先做**全局基线**
2. 再找**高相关因素**
3. 再做**多维交叉组合**
4. 最后做**专项下钻**

专项下钻大致包括：

- 1 局用户为什么走
- 某些客户端是否有稳定性问题
- 某些渠道是否流量质量差
- 破产后是否领取补助

## 3. dws 是如何创建的？

这个项目里的 DWS 创建方式非常明确：

- **先建表**
- **再按来源表增量导入**
- **按依赖顺序逐层生成**

核心操作文档是：

- `ExternDoc/landlord-analysis/ops/daily_data_ops.md`
- `ExternDoc/landlord-analysis/ops/modify_data_ops.md`

### 3.1 DWS 的基础来源

项目里的 DWS 主要来自四类源表：

1. 注册源表
   - `hive_catalog_cdh5.dm.olap_tcy_userapp_d_p_login1st`
2. 登录源表
   - `tcy_dwd.dwd_tcy_userlogin_si`
3. 对局源表
   - `tcy_dwd.dwd_game_combat_si`
4. 渠道维表源
   - `tcy_dim.dim_channel_singletag_dict`
   - `hive_catalog_cdh5.dim.dim_channel_category`

### 3.2 各核心 DWS 表的创建链路

#### 1. `dws_channel_category_map`

作用：把 `channel_id` 映射到渠道分类。

来源：

- `dim_channel_singletag_dict`
- `dim_channel_category`

生成方式：

```sql
INSERT INTO tcy_temp.dws_channel_category_map
SELECT
    t1.channel_id,
    ANY_VALUE(t2.channel_category_id),
    ANY_VALUE(t2.channel_category_name),
    ANY_VALUE(t2.channel_category_tag_id)
FROM tcy_dim.dim_channel_singletag_dict t1
INNER JOIN hive_catalog_cdh5.dim.dim_channel_category t2
    ON t1.channel_type_id = t2.channel_type_id
GROUP BY t1.channel_id;
```

#### 2. `dws_dq_daily_reg`

作用：生成最基础的“用户注册表”。

来源：

- `olap_tcy_userapp_d_p_login1st`

生成方式：

```sql
INSERT INTO tcy_temp.dws_dq_daily_reg
SELECT
    app_id,
    uid,
    str_to_date(CAST(dt AS STRING), '%Y%m%d'),
    FROM_UNIXTIME(first_login_ts / 1000) AS reg_datetime
FROM hive_catalog_cdh5.dm.olap_tcy_userapp_d_p_login1st
WHERE app_id = 1880053;
```

#### 3. `dws_dq_daily_login`

作用：把分钟级登录日志聚合成“用户-天”粒度，并产出首登、末登、最频繁登录等维度。

来源：

- `tcy_dwd.dwd_tcy_userlogin_si`

核心生成逻辑：

- `MIN(dt)` -> 首次登录时间
- `MIN_BY(app_code, time_unix)` -> 首次登录版本
- `MIN_BY(channel_id, time_unix)` -> 首次登录渠道
- `COUNT(DISTINCT ...)` -> 当日接触渠道数、分端数、版本数
- `COUNT(1)` -> 当日登录次数

#### 4. `dws_dq_app_daily_reg`

作用：在注册表基础上补齐 APP 端分析维度，生成“APP 端注册用户宽表”。

依赖：

- `dws_dq_daily_reg`
- `dws_dq_daily_login`
- `dws_channel_category_map`

生成逻辑：

- 从注册表拿 `uid`、`reg_date`
- 关联注册当天登录记录拿 `first_channel_id`、`first_group_id`、`first_app_code`
- 关联渠道维表拿 `channel_category_name`
- 生成 `is_login_log_missing`
- 生成 `first_day_login_cnt`

这张表是绝大多数留存分析的分母表。

#### 5. `dws_ddz_daily_game`

作用：这是整个斗地主分析最核心的一张事实中间表，把原始对局表标准化为统一结构。

来源：

- `tcy_dwd.dwd_game_combat_si`

主要转换逻辑：

1. 过滤出斗地主数据
   - `game_id = 53`
2. 将 `room_id` 映射为 `play_mode`
   - 经典 = 1
   - 不洗牌 = 2
   - 癞子 = 3
   - 积分 = 4
   - 比赛 = 5
   - 好友房 = 6
3. 统一不同玩法的货币字段
   - `basedeposit / basescore` -> `room_base`
   - `fee / score_fee` -> `room_fee`
   - `olddeposit / oldscore` -> `start_money`
   - `end_deposit / end_score` -> `end_money`
   - `depositdiff + fee / scorediff + score_fee` -> `diff_money_pre_tax`
4. 解析 JSON 倍数字段
   - `grab_landlord_bet`
   - `complete_victory_bet`
   - `bomb_bet`
5. 计算实际倍数
   - `real_magnification`

这张表之后衍生出大多数分析表。

#### 6. `dws_app_game_active`

作用：生成“用户在某天是否有对局”的轻量活跃表，用于整体留存 flag 计算。

依赖：

- `dws_ddz_daily_game`

逻辑：

- 过滤 APP 端
- 过滤机器人
- 按 `app_id, uid, dt` 去重

#### 7. `dws_app_gamemode_active`

作用：生成“用户在某天是否在某玩法有对局”的活跃表，用于同玩法留存。

依赖：

- `dws_ddz_daily_game`

逻辑：

- 过滤 APP 端
- 过滤机器人
- 保留 `play_mode`
- 按 `app_id, uid, play_mode, dt` 去重

#### 8. `dws_ddz_app_game_stat`

作用：把对局明细进一步聚合成“用户-天-客户端版本”粒度，用于首日行为分析。

依赖：

- `dws_ddz_daily_game`

生成内容包括：

- `game_count`
- `total_play_seconds`
- `avg_game_seconds`
- `win_count`
- `lose_count`
- `win_rate`
- `max_win_streak`
- `max_lose_streak`
- `avg_magnification`
- `high_multi_games`
- `high_multi_wins`
- `high_multi_losses`
- `total_diff_money`
- `money_valley`
- `escape_count`
- `play_modes`

这里面连胜连败是通过窗口函数和连续分组逻辑算出来的。

#### 9. `dws_ddz_firstday_game`

作用：从全量对局表里抽取“注册当天对局”，专门用于新用户首日行为分析。

依赖：

- `dws_ddz_daily_game`
- `dws_dq_daily_reg`

实现方式：

```sql
INSERT INTO tcy_temp.dws_ddz_firstday_game
SELECT ...
FROM tcy_temp.dws_ddz_daily_game g
INNER JOIN tcy_temp.dws_dq_daily_reg r
    ON r.app_id = g.app_id
    AND r.uid = g.uid
    AND r.reg_date = g.dt;
```

本质上它就是：

- 先有全量对局表
- 再通过 `reg_date = dt` 筛出注册当日对局

### 3.3 DWS 的推荐创建顺序

结合文档中的依赖关系，推荐顺序如下：

1. `dws_channel_category_map`
2. `dws_dq_daily_reg`
3. `dws_dq_daily_login`
4. `dws_dq_app_daily_reg`
5. `dws_ddz_daily_game`
6. `dws_app_game_active`
7. `dws_app_gamemode_active`
8. `dws_ddz_app_game_stat`
9. `dws_ddz_app_gamemode_stat`
10. `dws_ddz_firstday_game`

如果只关注这次留存分析最核心的链路，可以进一步压缩成：

```text
olap_tcy_userapp_d_p_login1st
    ↓
dws_dq_daily_reg

dwd_tcy_userlogin_si
    ↓
dws_dq_daily_login
    ↓
dws_dq_app_daily_reg

dwd_game_combat_si
    ↓
dws_ddz_daily_game
    ↓
├── dws_app_game_active
├── dws_app_gamemode_active
├── dws_ddz_app_game_stat
└── dws_ddz_firstday_game
```

### 3.4 一句话总结

这个项目里的 DWS，本质上是在做三件事：

1. 把原始注册、登录、对局数据整理干净
2. 把斗地主相关字段统一成适合分析的结构
3. 把高频分析需要的留存、首日行为、玩法、客户端维度提前算好

所以作者后续的分析 SQL，大多数都是在 DWS 上直接做留存统计和分组分析，而不是回头反复扫原始明细表。
