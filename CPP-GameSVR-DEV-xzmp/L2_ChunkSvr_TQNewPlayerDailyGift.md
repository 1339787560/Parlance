# L2 TQNewPlayerDailyGift — 新玩家每日礼包

> 模块名: TQNewPlayerDailyGift | 用户称呼: TQNewPlayerDailyGift | 消息ID: 450660-450669

---

## 功能

新玩家每日礼包：判断新玩家资格（基于局数），触发7天每日礼包弹窗，处理每日领取奖励，支付成功后初始化7天奖励数据并通知客户端。

---

## 存储

### MySQL

| 表名 | 结构 | 说明 |
|------|------|------|
| tbltqnewplayerdailygift | userid(int PK), newplayer(int), triggerdate(int), lastdate(int), receivedays(int), remaindays(int), awardday1-7(bigint) | newplayer=0未判断/1新手/2非新手; awarddayN=每日可领金额 |

### Redis

无

---

## PB

| PB文件 | 消息类型 |
|--------|---------|
| (内嵌) | tqnewplayerdailygift.ReqInfo, tqnewplayerdailygift.ReqPopFresh, tqnewplayerdailygift.ReqReceive, tqnewplayerdailygift.RspInfo, tqnewplayerdailygift.RspPopFresh, tqnewplayerdailygift.RspReceive, tqnewplayerdailygift.NtfTqNewPlayerGiftResult |

---

## 对外接口

| 接口 | 说明 |
|------|------|
| onPayResult(userid, fakeexchangeid, price, exchangeid) | 支付回调，返回 (true, TQNEWPLAYERDAILYGIFT_EXCHANGE, 0) |

## 注入接口

| 接口 | 来源 | 说明 |
|------|------|------|
| imNewDepositOp | NewDeposit | 发放每日奖励银两 |

## 消息处理

| 消息ID | 处理函数 | 说明 |
|--------|---------|------|
| GR_TQNEWPLAYERDAILYGIFT_REQINFO | — | 查询礼包信息 |
| GR_TQNEWPLAYERDAILYGIFT_POPRRESH | — | 弹窗刷新 |
| GR_TQNEWPLAYERDAILYGIFT_RECEIVE | — | 领取每日奖励 |
| GR_TQNEWPLAYERDAILYGIFT_PAYRESULT_NTF | — | 支付结果通知 |
