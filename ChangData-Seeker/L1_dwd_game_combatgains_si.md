# L1 - dwd_game_combatgains_si

> 战绩明细准实时表

## 表信息

| 属性 | 值 |
|------|----|
| 表名 | dwd_game_combatgains_si |
| 类型 | 事实表 |
| 更新频率 | 准实时 |

## 字段列表

| 字段名 | 中文名 | 类型 | 说明 |
|--------|--------|------|------|
| trigger_id | 结算标识 | VARCHAR | |
| time_unix | 操作时间 | BIGINT | |
| uid | 用户ID | BIGINT | |
| dt | 日期 | INTEGER | 分区字段 |
| game_id | 游戏ID | INTEGER | |
| room | 房间号 | INTEGER | |
| date | 事件日期 | INTEGER | |
| time | 事件时间 | INTEGER | |
| resultguid | 战绩ID | VARCHAR | |
| game_code | 游戏缩写 | VARCHAR | |
| game_name | 游戏名称 | VARCHAR | |
| startguid | 配桌ID | VARCHAR | |
| tableno | 桌号 | INTEGER | |
| chairno | 椅子号 | INTEGER | |
| from_app_id | 入口应用ID | BIGINT | |
| from_app_code | 入口应用缩写 | VARCHAR | |
| basescore | 基础积分 | BIGINT | |
| oldscore | 初始积分 | BIGINT | |
| scorediff | 积分变化 | BIGINT | |
| basedeposit | 基础银两 | BIGINT | |
| olddeposit | 初始银两 | BIGINT | |
| depositdiff | 银两变化 | BIGINT | |
| experience | 经验值(分钟) | INTEGER | |
| timecost | 耗时(秒) | INTEGER | |
| bout | 回合数 | INTEGER | |
| breakoff | 断线次数 | INTEGER | |
| win | 胜 | INTEGER | |
| loss | 负 | INTEGER | |
| standoff | 平 | INTEGER | |
| fee | 服务费 | INTEGER | |
| cut | 逃跑扣费 | INTEGER | |
| user_type | 用户类型 | INTEGER | |
| channel_id | 渠道ID | INTEGER | |
| channel_name | 渠道名称 | VARCHAR | |
| group_id | 大厅组号 | INTEGER | |
| system | system | VARCHAR | |
| history_win | 历史胜局数 | INTEGER | |
| history_loss | 历史负局数 | INTEGER | |
| history_standoff | 历史平局数 | INTEGER | |
| small_game_id | 小游戏ID | INTEGER | |
| wait_time | 配桌时间(秒) | BIGINT | |
| app_code | 应用缩写 | VARCHAR | |
| magnification | 理论倍数 | INTEGER | |
| deposit_limit | 携银区间 | VARCHAR | |
| robot | 机器人 | INTEGER | |
| safebox_deposit | 保险箱银两余额 | BIGINT | |
| rules | 规则牌代号 | VARCHAR | |
| game_type | 游戏子玩法 | VARCHAR | |
| special_cards | 特殊牌代号 | VARCHAR | |
| start_cards | 起始牌代号 | VARCHAR | |
| role | 对局角色 | INTEGER | |
| bankruptcy | 破产 | INTEGER | |
| end_deposit | 结束携银 | BIGINT | |
| rules_cards_name | 规则牌名称 | VARCHAR | |
| special_cards_name | 特殊牌名称 | VARCHAR | |
| start_cards_name | 起始牌名称 | VARCHAR | |
| score_fee | 服务费积分 | BIGINT | |
| silver_extra | 额外银两 | BIGINT | |
| silver_balance | 银子余额 | BIGINT | |
| result_name | 对局结果名称 | VARCHAR | |
| app_id | 应用ID | INTEGER | |
| app_name | 应用名称 | VARCHAR | |
| from_app_name | 入口应用名称 | VARCHAR | |
| robot_name | 机器人名称 | VARCHAR | |
| role_name | 角色名称 | VARCHAR | |
| result_id | 对局结果ID | INTEGER | |
| stash_score_balance | 后备箱积分余额 | BIGINT | |
| stash_deposit_balance | 后备箱银子余额 | BIGINT | |
| magnification_stacked | 加倍倍率 | INTEGER | |
| end_score | 结束积分 | BIGINT | |
| afk_turn_cnt | 托管手数 | BIGINT | |
| turn_cnt | 总手数 | BIGINT | |
| ip | IP地址 | VARCHAR | |
| package_type_id | 包类型ID | INTEGER | |
| from_app_vers | 入口应用版本号 | VARCHAR | |
| app_vers | 应用版本号 | VARCHAR | |
| game_vers | 游戏版本号 | VARCHAR | |
| os_type_id | 操作系统类型ID | INTEGER | |
| promotion_code | 推广代号 | VARCHAR | |
| fpid | 设备指纹(新) | VARCHAR | |
| device_idf | 设备身份标识 | VARCHAR | |
| ct_open_id | | VARCHAR | |
| package_name | | VARCHAR | |
| ct_app_id | | VARCHAR | |
| screen_resolution | 屏幕分辨率(<宽>,<高>) | VARCHAR | |
| os_name | 操作系统名称 | VARCHAR | |
| device_name | 设备型号 | VARCHAR | |
| language | 用户语言设置 | VARCHAR | |
| carrier_id | 网络运营商代号 | INTEGER | |
| external_app_id | 外部应用ID | VARCHAR | |
| click_id | 点击ID | VARCHAR | |
| user_agent | UserAgent | VARCHAR | |
| network_type_id | 网络类型ID(新) | INTEGER | |
| enter_app_type_id | 启动方式ID | INTEGER | |
| media_sdk | | VARCHAR | |
| sub_package_id | | VARCHAR | |
| di_sdk_vers | | VARCHAR | |
| storage_unix | 存储时间戳 | BIGINT | |
| collect_points | 抓分数 | BIGINT | |
| mirrorguid | 镜像对局ID | VARCHAR | |
| play_type | 对局类型 | VARCHAR | |
| room_currency_lower | 房间下限 | BIGINT | |
| room_currency_upper | 房间上限 | BIGINT | |
| total_kills | 总击杀数 | BIGINT | |
| magnification_subdivision | 倍数场景细分 | VARCHAR | |
| robot_provider | 机器人提供方 | INTEGER | |
| extend_content | 扩展信息 | VARCHAR | |
