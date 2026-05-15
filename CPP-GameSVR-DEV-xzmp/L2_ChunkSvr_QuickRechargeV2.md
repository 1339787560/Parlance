# L2 QuickRechargeV2 — 快捷充值V2

> 模块名: QuickRechargeV2 | 用户称呼: tqquickchargeV2 | 消息ID: 450740-450749

---

## 功能

快捷充值V2：基于累计充值历史触发特惠礼包，位压标记(one-time-purchase)确保每档只买一次，VIP加成比例影响银两发放，支付后拆分为基础+VIP加成两条记录。

---

## 存储

### MySQL (lasyncache + 旧位压表)

| 表名 | 结构 | 说明 |
|------|------|------|
| sqlas_quickrecharge | mainkey(int PK), data(blob) | data = PB编码的 quickrecharge.Cache (新缓存) |
| tbltqquickrechargeV2 | userid(int PK), limit_trigger_1_1(int), limit_buy_1_1(int), limit_trigger_2_1(int), limit_buy_2_1(int), limit_trigger_3_1(int), limit_buy_3_1(int) | 旧位压表：二进制bit位标记触发/购买状态。读取时自动迁移到PB缓存 |

### Redis (lasyncache 代理)

| Key格式 | 类型 | 说明 |
|---------|------|------|
| quickrecharge:{mainkey} | STRING | PB编码缓存 |
| rdsdirtycachelist:sqlas_quickrecharge | SET | 脏数据集合 |

---

## 位压表说明

```
bit = (roomlevel - 1) * 2 + (giftlevel - 1)
hashid = (bit / 32) + 1
gametype: 血战1, 血流2, 六红中3
limit_trigger_{gametype}_{hashid}: 触发状态位压
limit_buy_{gametype}_{hashid}: 购买状态位压
```

---

## PB

| PB文件 | 消息类型 |
|--------|---------|
| quickrecharge.pb | QueryInfo, RspInfo, Cache(缓存序列化), NotifyPayResult |

---

## 对外接口

| 接口 | 说明 |
|------|------|
| onPayResult(userid, fakeexchangeid) | 支付回调 |
| onGetPriceToTqMatch(fakeexchangeid) | 返回基础价格(供匹配系统) |
| getExchangeID() | 返回exchange ID |

## 注入接口

| 接口 | 来源 | 说明 |
|------|------|------|
| imGetExchangeID | ExchangeCenter | 获取兑换ID |
| imGetUserCharge | UserData | 获取用户充值金额 |
| imGetVipInfoByModule | TQVip | VIP加成信息 |

## 消息处理

| 消息ID | 处理函数 | 说明 |
|--------|---------|------|
| GR_QUICKRECHARGEV2_REQINFO | — | 查询快捷充值信息 |
| GR_QUICKRECHARGEV2_NOTIFYPAY | — | 支付结果通知 |
