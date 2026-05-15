# L2 ShakeGift — 摇一摇宝箱

> 模块名: ShakeGift | 用户称呼: special/shakegift | 消息ID: 450430-450449

---

## 功能

摇一摇宝箱：对局结束后累计局数触发摇奖次数，摇出随机宝箱（按权重+房间ID配置），宝箱有倒计时过期机制，支持放弃宝箱、RMB/通宝购买。_1版本增加VIP加成和合集包价格体系。

---

## 存储

### MySQL

| 表名 | 结构 | 说明 |
|------|------|------|
| tblshakegiftdata | userid(int PK), boutnum(int), boutroomid(int), treasureid(int), triggertime(int), discount(float), original(float), rewardnum(float), countdown(int), special(int) | 玩家匹配数据 |
| tblshakegifttimes_{D} | userid(int PK), times(int) | 按日分表，每日摇奖次数 |

### Redis

无

---

## PB

| PB文件 | 消息类型 |
|--------|---------|
| shakegift.pb | ReqShakeGiftData, ReqShake, ReqGiveUpGift, NtfBoutFinish, RspShakeGiftData, RspShake, RspGiveUpGift, NtfShakeGiftPayResult, NtfShakeGiftBout |

---

## 对外接口

| 接口 | 说明 |
|------|------|
| onPayResult(payresult, item, userdata) | RMB支付回调，返回 (true, NewDepositOPType, addcount) |
| onTongbaoPay(userid, fakeexchangeid, price, exchangeid) | 通宝支付回调 |

## 注入接口

| 接口 | 来源 | 说明 |
|------|------|------|
| imGetVipInfoByModule | TQVip | _1版本获取VIP加成信息 |

## 消息处理

| 消息ID | 处理函数 | 说明 |
|--------|---------|------|
| GR_SHAKEGIFT_UERDATA_REQ | — | 查询宝箱数据 |
| GR_SHAKEGIFT_SHAKE_REQ | — | 执行摇一摇 |
| GR_SHAKEGIFT_GIVEUP_REQ | — | 放弃宝箱 |
| GR_SHAKEGIFT_GAMERESULT_NTF | — | 对局结果通知(累计局数) |
| GR_SHAKEGIFT_UERDATA_REQ_1 | — | _1版本查询 |
| GR_SHAKEGIFT_SHAKE_REQ_1 | — | _1版本摇一摇 |

## 主动发送

| 消息ID | 目标 | 说明 |
|--------|------|------|
| GR_SHAKEGIFT_PAYRESULT_NTF | assistSvr | 支付结果通知 |
| GR_SHAKEGIFT_BOUT_NTF | assistSvr | 局数变化通知 |
