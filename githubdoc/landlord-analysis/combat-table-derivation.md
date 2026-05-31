# 战绩表衍生文档

## 1. 文档范围

本文围绕 `landlord-analysis` 项目中的原始战绩表，整理以下内容：

- 原始战绩表的表名与业务内容
- 由原始战绩表产生的主要衍生表
- 每张衍生表的分析含义
- 每张衍生表对外提供、并被重点依赖的字段

本文只关注“战绩 / 对局结果”这一条数据链路。

核心参考文档：

- [raw/dwd_game_combat_si.md](../raw/dwd_game_combat_si.md)
- [dws/dws_ddz_daily_game.md](../dws/dws_ddz_daily_game.md)
- [dws/dws_ddz_firstday_game.md](../dws/dws_ddz_firstday_game.md)
- [dws/dws_ddz_app_game_stat.md](../dws/dws_ddz_app_game_stat.md)
- [dws/dws_ddz_app_gamemode_stat.md](../dws/dws_ddz_app_gamemode_stat.md)
- [dws/dws_app_game_active.md](../dws/dws_app_game_active.md)
- [dws/dws_app_gamemode_active.md](../dws/dws_app_gamemode_active.md)
- [dws/dws_crazyddz_daily_game.md](../dws/dws_crazyddz_daily_game.md)
- [RAW_TO_DWS_FIELD_MAPPING.md](./RAW_TO_DWS_FIELD_MAPPING.md)

## 2. 原始战绩表

### 2.1 表名

- 库名：`tcy_dwd`
- 表名：`dwd_game_combat_si`
- 全名：`tcy_dwd.dwd_game_combat_si`

### 2.2 这张表存的是什么

`dwd_game_combat_si` 是原始对局战绩日志表，按“单局中的单个玩家”记录对局结果。

在本项目中：

- `game_id = 53` 表示标准斗地主对局数据
- `game_id = 521` 表示疯狂斗地主对局数据

它是整个项目中战绩分析使用的最底层事实来源。在进入 DWS 层之前，玩法、货币字段、倍数字段都还保留原始游戏侧结构。

### 2.3 原始字段的主要业务含义

原始战绩表可以分为五组核心字段。

#### A. 基础标识与时间字段

- `dt`：对局日期，原始格式如 `20260408`
- `time_unix`：毫秒级对局时间戳
- `resultguid`：本局战绩唯一 ID
- `uid`：玩家 ID
- `app_id`：应用 ID
- `app_code`：应用编码
- `game_id`：游戏 ID

分析含义：

- 确定日分区
- 标识单局记录
- 将战绩日志关联到用户、应用、游戏维度

#### B. 玩法与房间字段

- `room_id`
- `group_id`
- `channel_id`
- `room_currency_lower`
- `room_currency_upper`

分析含义：

- 识别玩法
- 区分 PC / APP / 小游戏端
- 区分渠道来源
- 评估房间门槛和携带货币压力

#### C. 胜负与角色字段

- `role`
- `chairno`
- `result_id`
- `robot`
- `timecost`

分析含义：

- 判断地主 / 农民角色
- 判断胜负
- 过滤机器人
- 分析局时长与潜在稳定性问题

#### D. 货币字段

银子玩法字段：

- `basedeposit`
- `fee`
- `olddeposit`
- `end_deposit`
- `depositdiff`

积分玩法字段：

- `basescore`
- `score_fee`
- `oldscore`
- `end_score`
- `scorediff`

附加字段：

- `cut`
- `safebox_deposit`

分析含义：

- 表示底注、服务费、局前货币、局后货币和本局输赢变化
- 支撑经济压力、破产风险、房间门槛等分析

#### E. 倍数字段

- `magnification`
- `magnification_stacked`
- `magnification_subdivision`

分析含义：

- 表示理论总倍数
- 表示个人加倍情况
- 以 JSON 保留更细的公共倍数明细，包括：
  - `grab_landlord_bet`
  - `complete_victory_bet`
  - `bomb_bet`

## 3. 为什么需要衍生

原始战绩表信息很全，但不适合高频直接分析。

主要问题有：

- 不同玩法使用不同货币字段
- 玩法需要通过 `room_id` 和 `group_id` 推导
- 倍数字段嵌在 JSON 里
- 首日分析需要筛出注册当天对局
- 留存分析需要轻量活跃标记表
- 用户日行为分析需要先聚合

因此，项目在 `dwd_game_combat_si` 之上构建了一层 DWS 中间层。

## 4. 衍生总览

核心衍生链路如下：

```text
tcy_dwd.dwd_game_combat_si
  -> tcy_temp.dws_ddz_daily_game
     -> tcy_temp.dws_app_game_active
     -> tcy_temp.dws_app_gamemode_active
     -> tcy_temp.dws_ddz_app_game_stat
     -> tcy_temp.dws_ddz_app_gamemode_stat
     -> tcy_temp.dws_ddz_firstday_game

tcy_dwd.dwd_game_combat_si
  -> tcy_temp.dws_crazyddz_daily_game
```

## 5. 衍生表 1：`tcy_temp.dws_ddz_daily_game`

### 5.1 表含义

这是项目里最核心的战绩衍生表。

它把原始斗地主战绩标准化成统一结构，使下游分析不需要再分别处理银子场、积分场、比赛场、好友房等不同玩法的异构字段。

### 5.2 来源

- 直接来源：`tcy_dwd.dwd_game_combat_si`
- 过滤条件：`game_id = 53`

### 5.3 分析含义

这张表主要解决五件事：

1. 将 `room_id` 和 `group_id` 映射为 `play_mode`
2. 统一银子和积分玩法的货币字段
3. 将原始时间戳转换为分析友好的时间字段
4. 从 JSON 中提取倍数字段
5. 计算 `real_magnification`

它是后续绝大多数战绩分析表的基础事实表。

### 5.4 重点字段

#### 标识与时间

- `app_id`
- `dt`
- `uid`
- `game_datetime`
- `resultguid`

用途：

- 按用户按天分析
- 做首局排序
- 追踪单局明细

#### 玩法与分端

- `room_id`
- `play_mode`
- `group_id`
- `app_code`
- `game_id`

用途：

- 分玩法比较
- 客户端分端分析
- APP 端过滤

#### 胜负与角色

- `result_id`
- `role`
- `chairno`
- `robot`
- `timecost`

用途：

- 胜负分析
- 地主 / 农民体验分析
- 机器人过滤
- 对局时长分析

#### 经济

- `room_base`
- `room_fee`
- `start_money`
- `end_money`
- `diff_money_pre_tax`
- `cut`
- `safebox_deposit`
- `room_currency_lower`
- `room_currency_upper`

用途：

- 净输赢分析
- 房间门槛压力分析
- 破产风险分析
- 逃跑罚没分析

#### 倍数

- `magnification`
- `magnification_stacked`
- `real_magnification`
- `grab_landlord_bet`
- `complete_victory_bet`
- `bomb_bet`

用途：

- 首局体验分析
- 高倍风险分析
- 炸弹 / 春天 / 抢地主体验分析

## 6. 衍生表 2：`tcy_temp.dws_app_game_active`

### 6.1 表含义

这是一张从战绩事实表衍生出来的轻量活跃表。

它只记录“某个真实 APP 用户在某天是否打过局”。

### 6.2 来源

- 直接上游：`tcy_temp.dws_ddz_daily_game`

### 6.3 分析含义

这张表不是为了看详细战绩，而是为了做留存 flag。

典型用途：

- 次留
- 7 留
- 30 留

### 6.4 重点字段

- `app_id`
- `uid`
- `dt`

其上游过滤逻辑依赖：

- `robot`
- `group_id`

## 7. 衍生表 3：`tcy_temp.dws_app_gamemode_active`

### 7.1 表含义

这张表是在 `dws_app_game_active` 的基础上保留玩法维度。

它记录“某个真实 APP 用户在某天是否玩过某个玩法”。

### 7.2 来源

- 直接上游：`tcy_temp.dws_ddz_daily_game`

### 7.3 分析含义

它用于“同玩法留存”，而不是整体留存。

典型用途：

- 经典玩法用户留存
- 不洗牌玩法用户留存
- 癞子玩法用户留存

### 7.4 重点字段

- `app_id`
- `uid`
- `play_mode`
- `dt`

其上游过滤逻辑依赖：

- `robot`
- `group_id`

## 8. 衍生表 4：`tcy_temp.dws_ddz_app_game_stat`

### 8.1 表含义

这张表把战绩明细聚合到 `uid x dt x app_code` 粒度。

它是一张 APP 端用户“日行为统计表”。

### 8.2 来源

- 直接上游：`tcy_temp.dws_ddz_daily_game`

### 8.3 分析含义

这张表把明细战绩转换成用户日行为指标，用于留存分析和体验分析。

典型分析问题：

- 用户首日打了多少局
- 用户首日打了多久
- 用户首日胜率如何
- 用户首日连败是否严重
- 用户首日经济压力有多大
- 用户是否尝试了多个玩法

### 8.4 主要衍生字段

#### 投入度

- `game_count`
- `total_play_seconds`
- `avg_game_seconds`
- `mode_count`
- `play_modes`

含义：

- 用户当天玩了多少
- 是否形成持续投入
- 是否探索多个玩法

#### 胜负体验

- `win_count`
- `lose_count`
- `win_rate`
- `max_win_streak`
- `max_lose_streak`

含义：

- 衡量首日成功 / 失败体验
- 识别强烈的连败流失风险

#### 倍数与风险

- `avg_magnification`
- `max_magnification`
- `avg_real_magnification`
- `high_multi_games`
- `high_multi_wins`
- `high_multi_losses`

含义：

- 衡量倍数压力
- 判断高风险房间或高波动对局是否驱动流失

#### 经济

- `total_diff_money`
- `money_valley`

含义：

- 量化首日净经济变化
- 量化当天资金最低谷

#### 稳定性 / 异常行为

- `escape_count`

含义：

- 识别逃跑相关异常行为或体验不稳定现象

### 8.5 它依赖的上游字段

这张聚合表主要依赖这些上游战绩字段：

- `app_id`
- `uid`
- `dt`
- `app_code`
- `game_datetime`
- `result_id`
- `timecost`
- `magnification`
- `real_magnification`
- `bomb_bet`
- `grab_landlord_bet`
- `magnification_stacked`
- `start_money`
- `end_money`
- `diff_money_pre_tax`
- `room_fee`
- `cut`
- `room_id`
- `play_mode`
- `robot`
- `group_id`

## 9. 衍生表 5：`tcy_temp.dws_ddz_app_gamemode_stat`

### 9.1 表含义

这张表是 `dws_ddz_app_game_stat` 的“按玩法拆分版”。

它把战绩行为聚合到 `uid x dt x app_code x play_mode` 粒度。

### 9.2 来源

- 直接上游：`tcy_temp.dws_ddz_daily_game`

### 9.3 分析含义

当“用户日整体统计”太粗，不足以区分玩法差异时，就需要这张表。

典型分析问题：

- 经典玩法是否比不洗牌更留人
- 某个玩法的炸弹体验是否更极端
- 某个玩法是否更容易产生连败

### 9.4 主要字段

它的指标家族与 `dws_ddz_app_game_stat` 基本一致，只是额外保留了 `play_mode` 这个一等分组维度。

重点字段：

- `app_id`
- `uid`
- `dt`
- `app_code`
- `play_mode`
- `game_count`
- `total_play_seconds`
- `avg_game_seconds`
- `win_count`
- `lose_count`
- `win_rate`
- `max_win_streak`
- `max_lose_streak`
- `avg_magnification`
- `max_magnification`
- `avg_real_magnification`
- `high_multi_games`
- `high_multi_wins`
- `high_multi_losses`
- `total_diff_money`
- `money_valley`
- `escape_count`

## 10. 衍生表 6：`tcy_temp.dws_ddz_firstday_game`

### 10.1 表含义

这是一张从标准化战绩事实表中筛出来的“首日快照表”。

它只保留“用户注册当天发生的对局”。

### 10.2 来源

- 直接上游：`tcy_temp.dws_ddz_daily_game`
- 注册日过滤条件来自：`tcy_temp.dws_dq_daily_reg`

### 10.3 分析含义

这是新用户首日体验分析中最重要的一张表。

典型分析问题：

- 用户的首局是什么
- 用户首日打了多少局
- 用户首日胜率如何
- 用户是否遇到了炸弹、高倍局、重度亏损
- 用户首局选择了什么玩法

### 10.4 重点字段

这张表保留了 `dws_ddz_daily_game` 的完整标准化战绩结构，包括：

- `app_id`
- `dt`
- `uid`
- `game_datetime`
- `resultguid`
- `timecost`
- `room_id`
- `play_mode`
- `room_base`
- `room_fee`
- `robot`
- `role`
- `chairno`
- `result_id`
- `start_money`
- `end_money`
- `diff_money_pre_tax`
- `cut`
- `safebox_deposit`
- `magnification`
- `magnification_stacked`
- `real_magnification`
- `grab_landlord_bet`
- `complete_victory_bet`
- `bomb_bet`
- `channel_id`
- `group_id`
- `app_code`
- `game_id`

注册日过滤依赖：

- `r.app_id = g.app_id`
- `r.uid = g.uid`
- `r.reg_date = g.dt`

## 11. 衍生表 7：`tcy_temp.dws_crazyddz_daily_game`

### 11.1 表含义

这是疯狂斗地主专用的战绩衍生表。

它不是简单从原始战绩表中过滤出来，而是为了解决另一类游戏逻辑问题：一局游戏可能有多轮结算，也可能跨天。

### 11.2 来源

- 直接来源：`tcy_dwd.dwd_game_combat_si`
- 过滤条件：`game_id = 521`

### 11.3 分析含义

这张表的目标是把疯狂斗地主的一整局从多条原始结算记录中还原出来。

典型分析需求：

- 还原完整对局
- 汇总多轮倍数
- 还原完整资金变化路径
- 推断最终胜负结果
- 处理跨天对局完整性

### 11.4 重点字段

- `resultguid`
- `uid`
- `app_id`
- `game_id`
- `game_date`
- `app_code`
- `group_id`
- `channel_id`
- `room_id`
- `room_base`
- `room_fee`
- `chairno`
- `robot`
- `start_datetime`
- `start_money`
- `end_datetime`
- `end_money`
- `final_result_id`
- `is_escape`
- `settle_count`
- `total_magnification`
- `game_deposit_gdp`
- `game_deposit_diff`
- `total_deposit_diff`
- `total_time_cost`
- `deposit_diff_path`
- `deposit_magnification_path`

## 12. 下游价值最高的原始字段

如果只跟踪最重要的一批原始战绩字段，优先看这些：

### 12.1 标识与关联键

- `app_id`
- `uid`
- `dt`
- `resultguid`
- `time_unix`

### 12.2 玩法判定字段

- `room_id`
- `group_id`
- `app_code`
- `game_id`

### 12.3 胜负与体验字段

- `result_id`
- `role`
- `robot`
- `timecost`
- `chairno`

### 12.4 经济字段

- `basedeposit`
- `basescore`
- `fee`
- `score_fee`
- `olddeposit`
- `oldscore`
- `end_deposit`
- `end_score`
- `depositdiff`
- `scorediff`
- `cut`
- `safebox_deposit`
- `room_currency_lower`
- `room_currency_upper`

### 12.5 倍数字段

- `magnification`
- `magnification_stacked`
- `magnification_subdivision`

这些字段驱动了项目里几乎所有主要战绩衍生表。

## 13. 建议阅读顺序

如果要快速理解整条战绩血缘链路，推荐按这个顺序看：

1. `dwd_game_combat_si`
2. `dws_ddz_daily_game`
3. `dws_ddz_firstday_game`
4. `dws_ddz_app_game_stat`
5. `dws_ddz_app_gamemode_stat`
6. `dws_app_game_active`
7. `dws_app_gamemode_active`
8. `dws_crazyddz_daily_game`

## 14. 一句话总结

`tcy_dwd.dwd_game_combat_si` 是原始战绩事实表，`tcy_temp.dws_ddz_daily_game` 是标准化后的核心战绩表，其余衍生表分别服务于首日体验分析、留存 flag 计算、用户日行为统计、玩法对比分析，以及疯狂斗地主的整局还原。
