# L2 TQLuckyDiscountGift — 幸运折扣礼包

> 模块名: TQLuckyDiscountGift | 用户称呼: luckydiscountgift | 消息ID: 450690-450699

---

## 功能

幸运折扣礼包：按权重随机折扣商品，支持平台包/合集包两种价格，管理每日免费刷新次数和每日购买剩余次数，通宝购买后刷新下一轮折扣并通知结果。

---

## 存储

### MySQL

无

### Redis (rdsidx=5)

| Key格式 | 类型 | 过期 | 说明 |
|---------|------|------|------|
| rdstqldayleftcount_user_{D} | HASH (userid→dayleftcount) | 25h | 玩家当日购买剩余次数 |
| rdstqldayfreenum_user_{D} | HASH (userid→freenum) | 25h | 玩家当日免费刷新次数 |
| rdstqlfakeexchangeid_user_{D} | HASH (userid→fakeexchangeid) | 25h | 玩家当前折扣商品exchangeid |

> {D}=日编号

---

## PB

| PB文件 | 消息类型 |
|--------|---------|
| (内嵌) | tqluckydiscountgift.ReqLuckyDiscountGiftInfo, tqluckydiscountgift.ReqGetFreeDiscount, tqluckydiscountgift.RspLuckyDiscountGiftInfo, tqluckydiscountgift.RspGetDiscount, tqluckydiscountgift.NtfTongBaoExchangeResult |

---

## 对外接口

| 接口 | 说明 |
|------|------|
| onTongbaoExchange(userid, fakeexchangeid, price, exchangeid) | 通宝购买回调，返回 (true, TQLUCKYDISCOUNTGIFT_EXCHANGE, cur_prize) |

## 注入接口

| 接口 | 来源 | 说明 |
|------|------|------|
| imNewDepositOp | NewDeposit | 发放银两 |
| imGetUserCharge | UserData | 获取用户充值金额 |

## 消息处理

| 消息ID | 处理函数 | 说明 |
|--------|---------|------|
| GR_TQLUCKYDISCOUNTGIFT_CONFIG_REQ | — | 查询折扣礼包配置 |
| GR_TQLUCKYDISCOUNTGIFT_GET_DISCOUNT_REQ | — | 获取/刷新折扣 |
| GR_TQLUCKYDISCOUNTGIFT_PAYRESULT_NTF | — | 支付结果通知 |
