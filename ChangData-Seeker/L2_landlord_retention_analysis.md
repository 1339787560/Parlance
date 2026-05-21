# L2 — 斗地主 APP 新增用户留存分析

> 分析对象：同城游·斗地主 APP 端 2026-02-10 ~ 2026-04-16 新增用户（87,980 人）
> 口径：留存分母 = 当日新增 APP 端用户数，分子 = 第 N 日有任一登录记录的用户数
> 源文档：`ExternDoc/landlord-analysis/`（完整 SQL 与数据报表目录）

---

## 一、分析框架

三层递进分析，每层独立文档，数据交叉印证：

```
全局层 (retention-global.md)         ← 全体新增用户，登录留存
    ├── 分玩法层 (retention-by-mode.md)    ← 经典/不洗牌/癞子，对局留存
    └── 分客户端层 (retention-by-client-lang.md)  ← Cocos-Lua/Creator，登录留存
```

| 层级 | 留存口径 | 覆盖维度 | 核心问题 |
|------|----------|----------|----------|
| 全局层 | 登录留存 | 渠道/设备/版本/时段 + 对局数/胜率/连败/经济/倍数 | 整体留存水平，首日行为因子影响力排序 |
| 分玩法层 | 对局留存（同玩法） | 经典/不洗牌/癞子 × 倍数/胜率/对局数/炸弹/经济 | 玩法间留存差异，玩法内因子规律 |
| 分客户端层 | 登录留存 | Cocos-Lua vs Cocos-Creator × 平台/渠道/登录次数/对局时长 | 版本间留存差异，技术归因诊断 |

---

## 二、所用数据表

### 2.1 核心表（留存分析三支柱）

| 表名 | 库 | 粒度 | 关键字段 | 作用 |
|------|---|------|----------|------|
| `dws_dq_app_daily_reg` | `tcy_temp` | uid（一个用户一行） | `reg_date`, `reg_app_code`, `reg_group_id`, `channel_category_name`, `first_day_login_cnt`, `is_login_log_missing` | **留存分母** — APP 端注册用户宽表，含渠道/版本/平台/登录次数 |
| `dws_dq_daily_login` | `tcy_temp` | uid × login_date | `login_date`, `first_app_code`, `first_channel_id`, `first_group_id`, `login_count` | **留存分子** — 每日登录聚合，关联判断 N 日是否回归 |
| `dws_ddz_app_game_stat` | `tcy_temp` | uid × dt × app_code | `game_count`, `win_rate`, `max_lose_streak`, `total_diff_money`, `money_valley`, `high_multi_games`, `high_multi_wins`, `high_multi_losses`, `escape_count`, `avg_magnification`, `avg_game_seconds` | **首日行为因子** — 对局数/胜率/连败/经济/倍数/高倍/逃跑/时长 |

### 2.2 首日对局明细表

| 表名 | 库 | 粒度 | 关键字段 | 作用 |
|------|---|------|----------|------|
| `dws_ddz_firstday_game` | `tcy_temp` | resultguid × uid（对局级） | `play_mode`(1=经典/2=不洗牌/3=癞子), `result_id`(1=胜/2=负), `role`(1=地主/2=农民), `room_base`, `magnification`, `bomb_bet`, `grab_landlord_bet`, `timecost`, `diff_money_pre_tax`, `start_money`, `end_money`, `robot` | **分玩法/首局分析** — 玩法映射、首局胜负、角色偏好、炸弹/倍数明细、对手构成 |

### 2.3 原始层与维表

| 表名 | 库 | 说明 |
|------|---|------|
| `olap_tcy_userapp_d_p_login1st` | `hive_catalog_cdh5.dm` | 游戏用户首次注册登录信息表（UID → first_login_ts） |
| `dwd_tcy_userlogin_si` | `tcy_dwd` | 玩家登录日志明细（分钟级），`dws_dq_daily_login` 的源表 |
| `dwd_game_combat_si` | — | 原始对局战绩日志，`dws_ddz_daily_game` → `dws_ddz_firstday_game` 的源 |
| `dws_channel_category_map` | `tcy_temp` | 渠道号 → 渠道分类映射（官方/渠道/小游戏） |
| `dim_channel_singletag_dict` | `tcy_dim` | 渠道分类标签维表 |
| `dim_channel_category` | `hive_catalog_cdh5.dim` | 渠道分类维表 |

### 2.4 玩法映射关系（留存分析中用到的 room_id 判定）

```
经典(play_mode=1): room_id IN (742,420,4484,12074,6314,11168,10336,16445)
不洗牌(play_mode=2): room_id IN (421,22039,22040,22041,22042)
癞子(play_mode=3):   room_id IN (13176,13177,13178)
比赛(play_mode=5):   room_id=11534 AND group_id IN APP/小游戏端
```

### 2.5 维度字段约定

| 维度 | 分类逻辑 | 用于 |
|------|----------|------|
| Android | `reg_group_id IN (6,66,33,44,77,99)` | 平台留存 |
| iOS | `reg_group_id IN (8,88)` | 平台留存 |
| Cocos-Lua | `reg_app_code = 'zgda'` | 客户端版本留存 |
| Cocos-Creator | `reg_app_code = 'zgdx'` | 客户端版本留存 |
| 渠道分类标签 | 1=官方, 2=渠道, 3=小游戏 | 渠道质量分层 |

---

## 三、SQL 模式与分类

全部 SQL 见 `docs/retention/` 目录下的三份分析文档。

### 3.1 留存计算模板（通用 CTE 模式）

```sql
-- 核心模式：reg LEFT JOIN login（分子留存判定）
SELECT
    r.*,
    COUNT(DISTINCT CASE WHEN l.login_date = DATE_ADD(r.reg_date, INTERVAL 1 DAY) THEN r.uid END)
      * 100.0 / COUNT(DISTINCT r.uid) AS day1_rate,
    COUNT(DISTINCT CASE WHEN l.login_date = DATE_ADD(r.reg_date, INTERVAL 6 DAY) THEN r.uid END)
      * 100.0 / COUNT(DISTINCT r.uid) AS day7_rate
FROM tcy_temp.dws_dq_app_daily_reg r
LEFT JOIN tcy_temp.dws_dq_daily_login l
    ON l.app_id = r.app_id AND l.uid = r.uid
    AND l.login_date IN (DATE_ADD(r.reg_date, INTERVAL 1 DAY), DATE_ADD(r.reg_date, INTERVAL 6 DAY))
WHERE r.app_id = 1880053
  AND r.reg_date BETWEEN '2026-02-10' AND '2026-05-10'
  AND r.is_login_log_missing = 0
GROUP BY ...;
```

**关键注意事项**：
- 使用 `LEFT JOIN` 保留"零活跃"用户（否则 0 局用户被排除）
- 登录表关联用 `IN` 列出目标天数，避免膨胀
- `is_login_log_missing = 0` 过滤日志缺失的数据

### 3.2 用户属性视角 SQL 分组

| 维度 | 分组 CASE WHEN 模式 |
|------|-------------------|
| 渠道 | `CASE WHEN channel_category_name IN ('OPPO','IOS','vivo','华为','咪咕','官方(非CPS)','荣耀') THEN ... ELSE '其他' END` |
| 平台 | `CASE WHEN reg_group_id IN (8,88) THEN 'iOS' WHEN ... IN (6,66,33,44,77,99) THEN 'Android' ELSE '其他' END` |
| 客户端 | `CASE reg_app_code WHEN 'zgda' THEN 'Cocos-Lua' WHEN 'zgdx' THEN 'Cocos-Creator' ELSE '其他' END` |
| 注册时段 | `CASE WHEN HOUR(reg_datetime) BETWEEN 0 AND 5 THEN '凌晨' ... END` |

### 3.3 首日行为因子分组模板（常用于 LEFT JOIN 到 dws_ddz_app_game_stat）

| 因子 | 分组逻辑（CASE WHEN） | 分桶数 |
|------|----------------------|--------|
| 对局数 | 0局 / 1局 / 2-5局 / 6-10局 / 10+局 | 5 |
| 胜率 | <30% / 30-50% / 50-70% / ≥70% | 4 |
| 连败 | 无连败 / 1-2 / 3-5 / 6-9 / 10+ | 5 |
| 银两变化 | 巨亏/大亏/小亏/小赚/大赚/巨赚 | 6 |
| 破产 | money_valley ≤ 1000 | 2 |
| 倍数 | ≤6 / 6-12 / 12-24 / 24-48 / 48+ | 5 |
| 高倍经历 | 未经历 / 仅赢 / 仅输 / 有赢有输 | 4 |
| 首局胜负 | `MIN_BY(result_id, game_datetime)` 取首局 | 3（含无对局） |
| 角色偏好 | `SUM(CASE WHEN role=1 THEN 1)/game_count` 判定 | 4 |

### 3.4 分玩法 SQL 特殊处理

分玩法层基于 `dws_ddz_firstday_game`（首日对局明细），使用 `play_mode` 字段聚合：

```sql
-- 同玩法留存 vs 整体留存 双口径
SELECT
    CASE g.play_mode WHEN 1 THEN '经典' WHEN 2 THEN '不洗牌' WHEN 3 THEN '癞子' END AS play_mode,
    COUNT(DISTINCT r.uid) AS user_count,
    -- 同玩法留存：分子也在该玩法有对局
    ROUND(COUNT(DISTINCT CASE WHEN l.login_date = DATE_ADD(r.reg_date, INTERVAL 1 DAY)
              AND g2.play_mode = g.play_mode THEN r.uid END) * 100.0 / COUNT(DISTINCT r.uid), 2) AS same_mode_d1,
    -- 整体留存：分子只需登录
    ROUND(COUNT(DISTINCT CASE WHEN l.login_date = DATE_ADD(r.reg_date, INTERVAL 1 DAY)
              THEN r.uid END) * 100.0 / COUNT(DISTINCT r.uid), 2) AS overall_d1
FROM tcy_temp.dws_dq_app_daily_reg r
LEFT JOIN tcy_temp.dws_ddz_firstday_game g ON ... AND g.play_mode IN (1,2,3)
LEFT JOIN tcy_temp.dws_dq_daily_login l ON ...;
```

### 3.5 分客户端语言 SQL 特殊处理

基于 `dws_dq_app_daily_reg.reg_app_code` 和 `dws_dq_daily_login.first_app_code`：

```sql
-- 版本切换分析
SELECT
    CASE r.reg_app_code WHEN 'zgda' THEN 'Cocos-Lua' WHEN 'zgdx' THEN 'Cocos-Creator' END AS reg_version,
    CASE
        WHEN login1.first_app_code IS NULL THEN 'X: 首日无登录'
        WHEN login1.first_app_code = r.reg_app_code THEN 'A: 未切换'
        ELSE 'B: 已切换'
    END AS switch_status,
    COUNT(DISTINCT r.uid) AS user_count,
    ROUND(COUNT(DISTINCT CASE WHEN l.login_date = DATE_ADD(r.reg_date, INTERVAL 1 DAY)
              THEN r.uid END) * 100.0 / COUNT(DISTINCT r.uid), 2) AS day1_rate
FROM tcy_temp.dws_dq_app_daily_reg r
LEFT JOIN tcy_temp.dws_dq_daily_login login1
    ON login1.app_id = r.app_id AND login1.uid = r.uid AND login1.login_date = r.reg_date
LEFT JOIN tcy_temp.dws_dq_daily_login l ON ...;
```

---

## 四、核心结论

### 4.1 整体留存基线

| 指标 | 加权平均 | 日粒度区间 |
|------|---------|-----------|
| 次留（Day+1） | **22.49%** | 19.13% ~ 32.37% |
| 3 留（Day+2） | **16.40%** | 13.46% ~ 24.72% |
| 7 留（Day+6） | **10.91%** | 8.41% ~ 18.62% |

### 4.2 首日行为因子影响力排序（从强到弱）

| 优先级 | 因子 | 关键数据 | 结论 |
|--------|------|---------|------|
| **P0** | 首日对局数/时长 | 10局+次留34.90% vs 1局9.57%；30分钟+次留44.86% | 最强留存杠杆，69.9%用户未达10局 |
| **P0** | 连败长度 | 连胜3+次留31.76% vs 连败2局仅4.80% | 毁灭性流失预警，阈值2局 |
| **P1** | 胜率（倒U形） | 30-50%最优(29.34%)；<30%(14.29%)；≥70%(18.64%) | 新人需保护在30-60%区间 |
| **P1** | 渠道质量 | 咪咕次留仅5.34%（基线1/4） | 低质渠道需降级 |
| **P2** | 首局胜负 | 首局胜24.90% vs 首局负20.14%（+4.76pp） | 温和影响，非核心杠杆 |
| — | 经济变化/破产 | 巨亏组留存高（倒置关联，"玩得多才亏得多"） | 现有破产阈值过宽松，无诊断价值 |
| — | 逃跑 | 新增用户100%无逃跑 | 新手不通过逃跑表达流失，此指标无信号价值 |

### 4.3 分玩法层发现

| 玩法 | 用户占比 | 同玩法次留 | 整体次留 | 特征 |
|------|---------|-----------|---------|------|
| 经典 | 85.5% | 17.81% | 22.59% | 默认入口，倍数倒U型(12-48x最优) |
| **不洗牌** | 11.0% | **20.56%** | **25.92%** | **留存最高**，倍数单调递增(越高越好) |
| 癞子 | 3.5% | 15.01% | 25.40% | 尝鲜型，1局即走占33.7%，同玩法忠诚度低 |

- **多玩法探索是留存放大器**：3种玩法次留33.23% vs 单玩法21.69%
- **10局+阈值普适**：三玩法10局+次留均在29-33%
- **癞子的问题**：不是绝对值低，而是"玩法忠诚度低"+"1局即走比例高"
- **不洗牌是潜力股**：留存三玩法之首，但规模仅为经典的13%

### 4.4 分客户端语言层发现

| 版本 | 用户数 | 次留 | 7留 |
|------|-------|------|-----|
| Cocos-Creator（新版） | 5,192 | **26.46%** | **11.94%** |
| Cocos-Lua（老版） | 82,753 | 21.81% | 9.82% |

- **84%的差异来自分布效应**：Creator 81%用户是iOS，iOS本身留存高
- **控制平台后**：Android上Creator 25.97% vs Lua 22.07%（+3.9pp）
- **最强异常信号**：Lua iOS次留仅11.32%（vs Creator iOS 26.58%），差距2.3倍
- **Lua长局性能退化**：Lua 30min+组对局时长155s（Creator仅84s）
- **行为规律版本间一致**：对局数/胜率/倍数等因子在两版本内峰值位置和单调性完全一致

### 4.5 高危信号组合

| 组合 | 预计留存 | 优先级 |
|------|---------|--------|
| **连败≥3 + 银子亏损 + 高倍输** | <10% | P0 |
| **首局负 + 地主 + 高倍局** | <15% | P0 |
| **0局/1局 + 登录次数≥3** | <15%（疑似闪退） | P0 |
| **咪咕渠道新用户** | 5.34% | P0 |

---

## 五、SQL 查询速查

| 查询目标 | 核心表 | 文档位置 |
|---------|--------|---------|
| 渠道留存基线 | `dws_dq_app_daily_reg` + `dws_dq_daily_login` | retention-global.md §2.1 |
| 平台留存 | 同上 + `reg_group_id` CASE | retention-global.md §2.2 |
| 客户端版本留存 | 同上 + `reg_app_code` CASE | retention-global.md §2.3 |
| 首日对局数×留存 | 同上 + `dws_ddz_app_game_stat` | retention-global.md §3.1 |
| 首日胜率×留存 | 同上 + `dws_ddz_app_game_stat` | retention-global.md §3.2 |
| 连败×留存 | 同上 + `max_lose_streak` | retention-global.md §3.3 |
| 银两变化×留存 | 同上 + `total_diff_money` | retention-global.md §3.4 |
| 破产×留存 | 同上 + `money_valley` | retention-global.md §3.5 |
| 高倍局×留存 | 同上 + `high_multi_games/wins/losses` | retention-global.md §3.6 |
| 首局胜负×留存 | `dws_ddz_firstday_game`(MIN_BY) | retention-global.md §4.2 |
| 玩法对比留存 | `dws_ddz_firstday_game.play_mode` | retention-by-mode.md §2.1 |
| 玩法数量×留存 | `dws_ddz_firstday_game`(COUNT DISTINCT play_mode) | retention-by-mode.md §3.2 |
| 版本×平台留存 | `dws_dq_app_daily_reg` + `dws_dq_daily_login` | retention-by-client-lang.md §2.4 |
| 登录次数检测 | `dws_dq_app_daily_reg.first_day_login_cnt` | retention-by-client-lang.md §3.1 |
| 对局时长分布 | `dws_ddz_firstday_game.timecost` | retention-by-client-lang.md §3.3 |
| 1局用户对手构成 | `dws_ddz_firstday_game` + `dws_ddz_daily_game`(robot) | retention-deepdive-sql.md Q1.1 |
| 咪咕渠道下钻 | `dws_dq_app_daily_reg`(channel='咪咕') | retention-deepdive-sql.md Q3 |
| 破产+补助分析 | `dws_ddz_app_game_stat` + `dws_dq_silver_logs` | retention-deepdive-sql.md Q4 |

---

## 六、关键发现与行动建议

### 6.1 P0（强数据支撑，立即执行）

1. **新手连败保护**：连败2局触发匹配降难度/安慰银子（基于连败2局次留仅4.80%）
2. **咪咕渠道降级/切断**：留存仅5.34%，为基线的1/4
3. **Lua iOS适配排查**：iOS上次留11.32%，与Creator差2.3倍

### 6.2 P1（需A/B测试或端上埋点）

4. **首日阶梯任务**：3/5/10局累计奖励，突破"69.9%用户未达10局"瓶颈
5. **胜率调控**：匹配确保新手首日胜率30-60%
6. **玩法探索引导**：经典用户推荐尝试不洗牌（不洗牌留存最高）
7. **端上埋点区分主动冷启与崩溃重启**（当前多次登录组留存反而高，无法确定是否为闪退）

### 6.3 P2（待补数据分析）

8. 玩法×客户端二维交叉分析（检验两类差异是否独立）
9. 修复L-09版本切换数据口径（当前全量"未切换"不合理）
10. 首日仅1局用户专项拆解（归因于"缺继续玩的钩子"而非首局体验）

---

## 七、源文档参考

| 文档 | 路径（相对 ChangData-Seeker） | 说明 |
|------|------------------------------|------|
| 分析框架 | `../ExternDoc/landlord-analysis/docs/retention/retention-analysis-framework.md` | 四视角+影响力金字塔+高危信号 |
| 全局层SQL | `../ExternDoc/landlord-analysis/docs/retention/retention-global.md` | 20+条SQL，含用户属性和行为因子 |
| 分玩法SQL | `../ExternDoc/landlord-analysis/docs/retention/retention-by-mode.md` | 玩法映射+玩法内因子+三维交叉 |
| 分客户端SQL | `../ExternDoc/landlord-analysis/docs/retention/retention-by-client-lang.md` | 版本对比+稳定性信号诊断 |
| 下钻SQL | `../ExternDoc/landlord-analysis/docs/retention/retention-deepdive-sql.md` | 4个专项下钻（1局/Lua iOS/咪咕/破产） |
| 全局报告 | `../ExternDoc/landlord-analysis/report/retention-global-report.md` | 完整结论+数据表 |
| 分玩法报告 | `../ExternDoc/landlord-analysis/report/retention-by-mode-report.md` | 玩法间差异化结论 |
| 分客户端报告 | `../ExternDoc/landlord-analysis/report/retention-by-client-lang-report.md` | 版本归因诊断 |
| 数据说明 | `../ExternDoc/landlord-analysis/README-data.md` | 全局字段+平台分组+渠道分类 |
| 表定义(原始) | `../ExternDoc/landlord-analysis/raw/` | ODS源表说明 |
| 表定义(DWS) | `../ExternDoc/landlord-analysis/dws/` | DWS中间表说明 |

---

> 整合日期：2026-05-21
> 数据版本：2026-02-10 ~ 2026-04-16 cohort
> 源项目：`ExternDoc/landlord-analysis/`
