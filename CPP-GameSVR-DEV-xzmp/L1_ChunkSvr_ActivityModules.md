# L1 ChunkSvr 活动模块索引

> ChunkSvr 管理的 16 个线上活动模块总览。每个模块由 luamodules/（配置+表结构）和 msgcenter/（业务逻辑+接口）两部分组成。

***

## 模块总览

| #  | 用户称呼                 | 代码模块名                  | 功能        | 消息ID范围        | MySQL表                                                              | Redis表                                                                                                                                                                                                | 使用PB                          | 缓存方式                | L2详情                                                                             |
| -- | -------------------- | ---------------------- | --------- | ------------- | ------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------- | ------------------- | -------------------------------------------------------------------------------- |
| 1  | tqwelfare            | WelfareTicket          | 福利页面/免费活动收纳页     | 450040-450059 | tblwelfareticket\_userhistory\_{M}, tblwelfareticket\_expiredrecord | rdswelfareticket\_user\_{M}(ZSET), rdswelfareticket\_active\_{M}, rdswelfareticket\_obtain\_{D}, rdswelfareticket\_consume\_{D}, rdswelfareticket\_userobtain\_{D}(HASH), rdswelfareticket\_goods\_\* | ✓ welfareticket.pb            | Redis直操作(rdsidx=3)  | [L2\_ChunkSvr\_WelfareTicket.md](L2_ChunkSvr_WelfareTicket.md)                   |
| 2  | tqcheckin            | TQCheckin              | 每日签到      | 450270-450279 | tbltqcheckin                                                        | —                                                                                                                                                                                                     | ✓                             | MySQL直操作            | [L2\_ChunkSvr\_TQCheckin.md](L2_ChunkSvr_TQCheckin.md)                           |
| 3  | tqluckyturntable     | TQLuckyTurnTable       | 幸运转盘    | 450710-450719 | —                                                                   | rdstqluckyturntable:{D}(HASH)                                                                                                                                                                         | ✓                             | Redis直操作(rdsidx=5)  | [L2\_ChunkSvr\_TQLuckyTurnTable.md](L2_ChunkSvr_TQLuckyTurnTable.md)             |
| 4  | special/shakegift    | ShakeGift              | 摇一摇     | 450430-450449 | tblshakegiftdata, tblshakegifttimes\_{D}                            | —                                                                                                                                                                                                     | ✓ shakegift.pb                | MySQL直操作            | [L2\_ChunkSvr\_ShakeGift.md](L2_ChunkSvr_ShakeGift.md)                           |
| 5  | tqtimelogin          | TQTimeLogin            | 定时登录    | 450700-450709 | —                                                                   | rdstqtimelogin\_user\_{D}(HASH)                                                                                                                                                                       | ✓                             | Redis直操作(rdsidx=5)  | [L2\_ChunkSvr\_TQTimeLogin.md](L2_ChunkSvr_TQTimeLogin.md)                       |
| 6  | tqdailyquestion      | TQDailyQuestion        | 每日问答/答题      | 450750-450759 | tbltqdailyquestion(userdata=BLOB/PB)                                | —                                                                                                                                                                                                     | ✓                             | MySQL直操作(PB序列化)     | [L2\_ChunkSvr\_TQDailyQuestion.md](L2_ChunkSvr_TQDailyQuestion.md)               |
| 7  | tqrelief             | TQRelief               | 低保模块      | 450280-450289 | —                                                                   | rdstqrelief\_user\_{D}(HASH), rdstqrelief\_dev\_{D}(HASH)                                                                                                                                             | ✓                             | Redis直操作(rdsidx=5)  | [L2\_ChunkSvr\_TQRelief.md](L2_ChunkSvr_TQRelief.md)                             |
| 8  | TQBrokeRecharge      | TQBrokeRecharge        | 复活礼包/局内破产礼包      | 450290-450299 | —                                                                   | rdstqbroke\_{userid}(HASH)                                                                                                                                                                            | ✓                             | Redis直操作(rdsidx=5)  | [L2\_ChunkSvr\_TQBrokeRecharge.md](L2_ChunkSvr_TQBrokeRecharge.md)               |
| 9  | tqdecoration         | TQDecorations          | 装扮系统      | 450810-450829 | sqlas\_tqdecoration(mainkey+data/BLOB)                              | rdsas\_tqdecoration:{mainkey}, rdsdirtycachelist:sqlas\_tqdecoration                                                                                                                                                                 | ✓ tqdecoration.pb             | lasynccache         | [L2\_ChunkSvr\_TQDecorations.md](L2_ChunkSvr_TQDecorations.md)                   |
| 10 | tqmonthcard          | TQMonthCard            | 月卡/周卡     | 450800-450809 | sqlas\_tqmonthcard(mainkey+data/BLOB)                               | rdsas\_tqmonthcard:{mainkey}, rdsdirtycachelist:sqlas\_tqmonthcard                                                                                                                                                                  | ✓ tqmonthcard.pb              | lasynccache         | [L2\_ChunkSvr\_TQMonthCard.md](L2_ChunkSvr_TQMonthCard.md)                       |
| 11 | tqvip                | TQVip                  | VIP等级/荣耀特权     | 450840-450849 | sqlas\_tqvip(mainkey+data/BLOB)                                     | rdsas\_tqvip:{mainkey}, rdsdirtycachelist:sqlas\_tqvip                                                                                                                                                                        | ✓ tqvip.pb                    | lasynccache         | [L2\_ChunkSvr\_TQVip.md](L2_ChunkSvr_TQVip.md)                                   |
| 12 | tqquickchargeV2      | QuickRechargeV2        | 快捷充值V2/补足金币    | 450740-450749 | sqlas\_quickrecharge(mainkey+data/BLOB), tbltqquickrechargeV2(位压旧表) | rdsas\_quickrecharge:{mainkey}, rdsdirtycachelist:sqlas\_quickrecharge                                                                                                                                                                | ✓ quickrecharge.pb            | lasynccache(兼容旧位压表) | [L2\_ChunkSvr\_QuickRechargeV2.md](L2_ChunkSvr_QuickRechargeV2.md)               |
| 13 | newplayerregister    | NewPlayerRegisterAward | 迎新礼包1/新手有礼   | 450260-450269 | tblnewplayerregisteraward                                           | —                                                                                                                                                                                                     | ✓                             | MySQL直操作            | [L2\_ChunkSvr\_NewPlayerRegisterAward.md](L2_ChunkSvr_NewPlayerRegisterAward.md) |
| 14 | TQNewPlayerDailyGift | TQNewPlayerDailyGift   | 新玩家每日礼包   | 450660-450669 | tbltqnewplayerdailygift                                             | —                                                                                                                                                                                                     | ✓                             | MySQL直操作            | [L2\_ChunkSvr\_TQNewPlayerDailyGift.md](L2_ChunkSvr_TQNewPlayerDailyGift.md)     |
| 15 | luckydiscountgift    | TQLuckyDiscountGift    | 幸运折扣礼包    | 450690-450699 | —                                                                   | rdstqldayleftcount\_user\_{D}(HASH), rdstqldayfreenum\_user\_{D}(HASH), rdstqlfakeexchangeid\_user\_{D}(HASH)                                                                                         | ✓                             | Redis直操作(rdsidx=5)  | [L2\_ChunkSvr\_TQLuckyDiscountGift.md](L2_ChunkSvr_TQLuckyDiscountGift.md)       |
| 16 | depositexchange      | NewDeposit             | 金币模块 | 450160-450259 | tblnewdeposit                                                       | —                                                                                                                                                                                                     | ✓ newdeposit.pb, pbTongbao.pb | MySQL直操作            | [L2\_ChunkSvr\_NewDeposit.md](L2_ChunkSvr_NewDeposit.md)                         |

<br />

## 缓存方式分类

| 方式              | 模块                                                                                                               | 说明                                    |
| --------------- | ---------------------------------------------------------------------------------------------------------------- | ------------------------------------- |
| **lasynccache** | TQDecorations, TQMonthCard, TQVip, QuickRechargeV2                                                               | 两级缓存(Redis→MySQL)，PB序列化，脏数据定时刷盘。C++内存层预留但未启用(key=nil) |
| **Redis直操作**    | WelfareTicket(rdsidx=3), TQLuckyTurnTable, TQTimeLogin, TQRelief, TQBrokeRecharge, TQLuckyDiscountGift(rdsidx=5) | 纯Redis存储，按日/月过期，无MySQL持久化             |
| **MySQL直操作**    | TQCheckin, TQDailyQuestion, ShakeGift, NewPlayerRegisterAward, TQNewPlayerDailyGift, NewDeposit                  | MySQL主存储                              |

***

## 模块间依赖

```
NewDeposit ←── 核心银两枢纽，几乎所有模块注入 imNewDepositOp
    │
    ├─→ TQCheckin, TQRelief, TQNewPlayerDailyGift, TQDailyQuestion, TQTimeLogin
    │     (注入 imNewDepositOp 增减银两)
    │
    ├─→ TQVip ←── VIP等级查询(imGetVipInfoByModule)
    │     │
    │     ├─→ TQRelief(VIP加成), TQLuckyTurnTable(特权次数), QuickRechargeV2(VIP加成)
    │     └─→ ShakeGift(VIP加成)
    │
    ├─→ TQProp ←── 道具枢纽
    │     ├─→ TQDecorations(imAddProps/imGetAllProps)
    │     ├─→ TQMonthCard(imAddProps/imGetAllProps/imLogProps)
    │     └─→ TQVip(imAddProps)
    │
    ├─→ WelfareTicket ←── 福利券
    │     └─→ TQLuckyDiscountGift, QuickRechargeV2 等(通过 imExchangeTicket 扣券)
    │
    └─→ LuaPayResult ←── 支付事件分发
          └─→ 所有充值类模块订阅支付回调
```

***

## 消息ID分配规则

- Lua模块消息ID起始: `MSGID_LUA_BEGIN = 450000`
- 每个模块分配 10-20 个ID的连续块
- 模块间通过注入 `im*` 函数通信，非正式接口协议

