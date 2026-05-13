# L1 - dwd_game_combat_si

> 战绩明细表(准实时)

## 表信息

| 属性 | 值 |
|------|----|
| 表名 | dwd_game_combat_si |
| 类型 | 事实表 |
| 更新频率 | 准实时 |
| SQL 引擎 | Presto — 末尾不加 `;`，VARCHAR 字段比较需加引号 |

## 字段列表

| 字段名 | 中文名 | 类型 | 分区 | 主键 | 说明 |
|--------|--------|------|:----:|:----:|------|
| trigger_id | | VARCHAR | 否 | 否 | |
| time_unix | | BIGINT | 否 | 否 | 时间戳字段 |
| uid | | BIGINT | 否 | 否 | 可见字段 |
| date | 123 | INTEGER | 是 | 否 | 日期 |
| time | | INTEGER | 否 | 否 | |
| game_id | 游戏ID | INTEGER | 否 | 否 | |
| game_code | | VARCHAR | 否 | 否 | |
| game_name | | VARCHAR | 否 | 否 | 你好在吗 |
| resultguid | | VARCHAR | 否 | 否 | |
| startguid | | VARCHAR | 否 | 否 | |
| tableno | | INTEGER | 否 | 否 | |
| chairno | | INTEGER | 否 | 否 | |
| room_id | | INTEGER | 否 | 否 | |
| from_app_id | 入口应用ID | BIGINT | 否 | 否 | |
| from_app_code | | VARCHAR | 否 | 否 | |
| basescore | | BIGINT | 否 | 否 | |
| oldscore | | BIGINT | 否 | 否 | |
| scorediff | | BIGINT | 否 | 否 | |
| basedeposit | | BIGINT | 否 | 否 | |
| olddeposit | | BIGINT | 否 | 否 | |
| depositdiff | | BIGINT | 否 | 否 | |
| experience | | INTEGER | 否 | 否 | |
| timecost | | INTEGER | 否 | 否 | |
| bout | | INTEGER | 否 | 否 | |
| breakoff | | INTEGER | 否 | 否 | |
| win | | INTEGER | 否 | 否 | |
| loss | | INTEGER | 否 | 否 | |
| standoff | | INTEGER | 否 | 否 | |
| fee | | INTEGER | 否 | 否 | |
| cut | | INTEGER | 否 | 否 | |
| user_type | | INTEGER | 否 | 否 | |
| channel_id | | INTEGER | 否 | 否 | |
| channel_name | | VARCHAR | 否 | 否 | |
| group_id | | INTEGER | 否 | 否 | |
| system | | VARCHAR | 否 | 否 | |
| history_win | | INTEGER | 否 | 否 | |
| history_loss | | INTEGER | 否 | 否 | |
| history_standoff | | INTEGER | 否 | 否 | |
| small_game_id | | INTEGER | 否 | 否 | |
| wait_time | | BIGINT | 否 | 否 | |
| app_code | | VARCHAR | 否 | 否 | |
| magnification | | INTEGER | 否 | 否 | |
| deposit_limit | | VARCHAR | 否 | 否 | |
| robot | | INTEGER | 否 | 否 | |
| safebox_deposit | | BIGINT | 否 | 否 | |
| rules | 规则说明 | VARCHAR | 否 | 否 | |
| game_type | | VARCHAR | 否 | 否 | |
| special_cards | | VARCHAR | 否 | 否 | |
| start_cards | | VARCHAR | 否 | 否 | |
| role | | INTEGER | 否 | 否 | |
| bankruptcy | 是否破产 | INTEGER | 否 | 否 | |
| end_deposit | | BIGINT | 否 | 否 | |
| rules_cards_name | | VARCHAR | 否 | 否 | |
| special_cards_name | | VARCHAR | 否 | 否 | |
| start_cards_name | | VARCHAR | 否 | 否 | |
| score_fee | | BIGINT | 否 | 否 | |
| silver_extra | | BIGINT | 否 | 否 | |
| silver_balance | | BIGINT | 否 | 否 | |
| result_name | 对局结果名称 | VARCHAR | 否 | 否 | |
| app_id | 应用ID | INTEGER | 否 | 否 | 应用ID的备注 |
| app_name | 应用名称 | VARCHAR | 否 | 否 | |
| from_app_name | 入口应用名称 | VARCHAR | 否 | 否 | |
| robot_name | | VARCHAR | 否 | 否 | |
| role_name | | VARCHAR | 否 | 否 | |
| result_id | 对局结果 | INTEGER | 否 | 否 | |
| stash_score_balance | | BIGINT | 否 | 否 | |
| stash_deposit_balance | | BIGINT | 否 | 否 | |
| magnification_stacked | | INTEGER | 否 | 否 | |
| end_score | | BIGINT | 否 | 否 | |
| afk_turn_cnt | | BIGINT | 否 | 否 | |
| turn_cnt | | BIGINT | 否 | 否 | |
| ip | | VARCHAR | 否 | 否 | |
| package_type_id | | INTEGER | 否 | 否 | |
| from_app_vers | | VARCHAR | 否 | 否 | |
| app_vers | | VARCHAR | 否 | 否 | |
| game_vers | | VARCHAR | 否 | 否 | |
| os_type_id | | INTEGER | 否 | 否 | |
| promotion_code | | VARCHAR | 否 | 否 | |
| fpid | | VARCHAR | 否 | 否 | |
| device_idf | | VARCHAR | 否 | 否 | |
| ct_open_id | | VARCHAR | 否 | 否 | |
| package_name | | VARCHAR | 否 | 否 | |
| ct_app_id | | VARCHAR | 否 | 否 | |
| screen_resolution | | VARCHAR | 否 | 否 | |
| os_name | | VARCHAR | 否 | 否 | |
| device_name | | VARCHAR | 否 | 否 | |
| language | | VARCHAR | 否 | 否 | |
| carrier_id | | INTEGER | 否 | 否 | |
| external_app_id | | VARCHAR | 否 | 否 | |
| click_id | | VARCHAR | 否 | 否 | |
| user_agent | | VARCHAR | 否 | 否 | |
| network_type_id | | INTEGER | 否 | 否 | |
| enter_app_type_id | | INTEGER | 否 | 否 | |
| media_sdk | | VARCHAR | 否 | 否 | |
| sub_package_id | | VARCHAR | 否 | 否 | |
| di_sdk_vers | | VARCHAR | 否 | 否 | |
| storage_unix | | BIGINT | 否 | 否 | |
| total_kills | | BIGINT | 否 | 否 | |
| mirrorguid | | VARCHAR | 否 | 否 | |
| collect_points | | BIGINT | 否 | 否 | |
| room_currency_upper | | BIGINT | 否 | 否 | |
| room_currency_lower | | BIGINT | 否 | 否 | |
| play_type | | VARCHAR | 否 | 否 | |
| message_content | | VARCHAR | 否 | 否 | |
| magnification_subdivision | | VARCHAR | 否 | 否 | |
