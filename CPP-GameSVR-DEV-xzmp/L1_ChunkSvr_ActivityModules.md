# L1 ChunkSvr 活动模块索引

> ChunkSvr 管理的 18 个线上活动模块总览。每个模块由 luamodules/（配置+表结构）和 msgcenter/（业务逻辑+接口）两部分组成。

---

## 模块总览

| # | 模块名 | 功能 | 消息ID范围 | MySQL表 | Redis表 | 使用PB | 缓存方式 | L2详情 |
|---|--------|------|-----------|---------|---------|--------|----------|--------|
| 1 | tqwelfare | 福利券兑换 | 450040-450059 | tblwelfareticket_userhistory_{M}, tblwelfareticket_expiredrecord | rdswelfareticket_user_{M}(ZSET), rdswelfareticket_active_{M}, rdswelfareticket_obtain_{D}, rdswelfareticket_consume_{D}, rdswelfareticket_userobtain_{D}(HASH), rdswelfareticket_goods_* | ✓ welfareticket.pb | Redis直操作(rdsidx=3) | [L2_ChunkSvr_tqwelfare.md](L2_ChunkSvr_tqwelfare.md) |
| 2 | tqcheckin | 每日签到 | 450270-450279 | tbltqcheckin | — | ✓ | MySQL直操作 | [L2_ChunkSvr_tqcheckin.md](L2_ChunkSvr_tqcheckin.md) |
| 3 | tqluckyturntable | 幸运转盘抽奖 | 450710-450719 | — | rdstqluckyturntable:{D}(HASH) | ✓ | Redis直操作(rdsidx=5) | [L2_ChunkSvr_tqluckyturntable.md](L2_ChunkSvr_tqluckyturntable.md) |
| 4 | special | 摇一摇宝箱 | 450430-450449 | tblshakegiftdata, tblshakegifttimes_{D} | — | ✓ shakegift.pb | MySQL直操作 | [L2_ChunkSvr_special.md](L2_ChunkSvr_special.md) |
| 5 | tqtimelogin | 定时登录奖励 | 450700-450709 | — | rdstqtimelogin_user_{D}(HASH) | ✓ | Redis直操作(rdsidx=5) | [L2_ChunkSvr_tqtimelogin.md](L2_ChunkSvr_tqtimelogin.md) |
| 6 | tqdailyquestion | 每日答题 | 450750-450759 | tbltqdailyquestion(userdata=BLOB/PB) | — | ✓ | MySQL直操作(PB序列化) | [L2_ChunkSvr_tqdailyquestion.md](L2_ChunkSvr_tqdailyquestion.md) |
| 7 | tqrelief | 低保救济 | 450280-450289 | — | rdstqrelief_user_{D}(HASH), rdstqrelief_dev_{D}(HASH) | ✓ | Redis直操作(rdsidx=5) | [L2_ChunkSvr_tqrelief.md](L2_ChunkSvr_tqrelief.md) |
| 8 | TQBrokeRecharge | 破产充值 | 450290-450299 | — | rdstqbroke_{userid}(HASH) | ✓ | Redis直操作(rdsidx=5) | [L2_ChunkSvr_TQBrokeRecharge.md](L2_ChunkSvr_TQBrokeRecharge.md) |
| 9 | tqdecoration | 装扮系统 | 450810-450829 | sqlas_tqdecoration(mainkey+data/BLOB) | rdsdirtycachelist:sqlas_tqdecoration | ✓ tqdecoration.pb | lasynccache | [L2_ChunkSvr_tqdecoration.md](L2_ChunkSvr_tqdecoration.md) |
| 10 | tqmonthcard | 月卡/周卡 | 450800-450809 | sqlas_tqmonthcard(mainkey+data/BLOB) | rdsdirtycachelist:sqlas_tqmonthcard | ✓ tqmonthcard.pb | lasynccache | [L2_ChunkSvr_tqmonthcard.md](L2_ChunkSvr_tqmonthcard.md) |
| 11 | tqvip | VIP等级 | 450840-450849 | sqlas_tqvip(mainkey+data/BLOB) | rdsdirtycachelist:sqlas_tqvip | ✓ tqvip.pb | lasynccache | [L2_ChunkSvr_tqvip.md](L2_ChunkSvr_tqvip.md) |
| 12 | tqquickchargeV2 | 快捷充值V2 | 450740-450749 | sqlas_quickrecharge(mainkey+data/BLOB), tbltqquickrechargeV2(位压旧表) | rdsdirtycachelist:sqlas_quickrecharge | ✓ quickrecharge.pb | lasynccache(兼容旧位压表) | [L2_ChunkSvr_tqquickchargeV2.md](L2_ChunkSvr_tqquickchargeV2.md) |
| 13 | fakeExchangeid | 兑换中心 | 450001-450019 | tblExchangeCenterUserStatue, tblExchangeCenterUserLotteryLimit_{D}, tblExchangeCenterDeviceLotteryLimit_{D} | exchangeuserlottery_{userid}(防重入锁,20s) | ✓ exchangecenter.pb | MySQL直操作+Redis锁(rdsidx=3) | [L2_ChunkSvr_fakeExchangeid.md](L2_ChunkSvr_fakeExchangeid.md) |
| 14 | newplayerregister | 新玩家注册奖励 | 450260-450269 | tblnewplayerregisteraward | — | ✓ | MySQL直操作 | [L2_ChunkSvr_newplayerregister.md](L2_ChunkSvr_newplayerregister.md) |
| 15 | TQNewPlayerDailyGift | 新玩家每日礼包 | 450660-450669 | tbltqnewplayerdailygift | — | ✓ | MySQL直操作 | [L2_ChunkSvr_TQNewPlayerDailyGift.md](L2_ChunkSvr_TQNewPlayerDailyGift.md) |
| 16 | luckydiscountgift | 幸运折扣礼包 | 450690-450699 | — | rdstqldayleftcount_user_{D}(HASH), rdstqldayfreenum_user_{D}(HASH), rdstqlfakeexchangeid_user_{D}(HASH) | ✓ | Redis直操作(rdsidx=5) | [L2_ChunkSvr_luckydiscountgift.md](L2_ChunkSvr_luckydiscountgift.md) |
| 17 | shakegift | 摇一摇宝箱(shakegift) | 450430-450449 | tblshakegiftdata, tblshakegifttimes_{D} | — | ✓ shakegift.pb | MySQL直操作 | [L2_ChunkSvr_special.md](L2_ChunkSvr_special.md) |
| 18 | depositexchange | 银两(新存款)核心 | 450160-450259 | tblnewdeposit | — | ✓ newdeposit.pb, pbTongbao.pb | MySQL直操作 | [L2_ChunkSvr_depositexchange.md](L2_ChunkSvr_depositexchange.md) |

> **注**: #4 special 和 #17 shakegift 是同一模块的不同命名，消息ID共用 450430-450449。

---

## 缓存方式分类

| 方式 | 模块 | 说明 |
|------|------|------|
| **lasynccache** | tqdecoration, tqmonthcard, tqvip, tqquickchargeV2 | 三级缓存(C++内存→Redis→MySQL)，PB序列化，脏数据定时刷盘 |
| **Redis直操作** | tqwelfare(rdsidx=3), tqluckyturntable, tqtimelogin, tqrelief, TQBrokeRecharge, luckydiscountgift(rdsidx=5) | 纯Redis存储，按日/月过期，无MySQL持久化 |
| **MySQL直操作** | tqcheckin, tqdailyquestion, special, newplayerregister, TQNewPlayerDailyGift, depositexchange | MySQL主存储，部分模块辅以Redis做日级缓存 |
| **混合** | fakeExchangeid | MySQL+Redis锁(防重入) |

---

## 模块间依赖

```
depositexchange(NewDeposit) ←── 核心银两枢纽，几乎所有模块注入 imNewDepositOp
    │
    ├─→ tqcheckin, tqrelief, TQNewPlayerDailyGift, tqdailyquestion, tqtimelogin
    │     (注入 imNewDepositOp 增减银两)
    │
    ├─→ tqvip ←── VIP等级查询(imGetVipInfoByModule)
    │     │
    │     ├─→ tqrelief(VIP加成), tqluckyturntable(特权次数), tqquickchargeV2(VIP加成)
    │     └─→ special(shakegift VIP加成)
    │
    ├─→ TQProp ←── 道具枢纽
    │     ├─→ tqdecoration(imAddProps/imGetAllProps)
    │     ├─→ tqmonthcard(imAddProps/imGetAllProps/imLogProps)
    │     └─→ tqvip(imAddProps)
    │
    ├─→ tqwelfare ←── 福利券
    │     └─→ fakeExchangeid(imExchangeTicket 扣券)
    │
    ├─→ fakeExchangeid ←── 兑换中心
    │     └─→ tqquickchargeV2(imGetExchangeID)
    │
    └─→ LuaPayResult ←── 支付事件分发
          └─→ 所有充值类模块订阅支付回调
```

---

## 消息ID分配规则

- Lua模块消息ID起始: `MSGID_LUA_BEGIN = 450000`
- 每个模块分配 10-20 个ID的连续块
- 模块间通过注入 `im*` 函数通信，非正式接口协议