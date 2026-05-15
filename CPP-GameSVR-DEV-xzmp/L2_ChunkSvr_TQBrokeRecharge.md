# L2 TQBrokeRecharge — 破产充值

> 模块名: TQBrokeRecharge | 用户称呼: TQBrokeRecharge | 消息ID: 450290-450299

---

## 功能

破产充值：跟踪玩家每局输钱金额，充值时按当前亏损比例发放额外银两（最高losemax），发放后清除Redis记录。充值回调由 NewDeposit 支付事件触发。

---

## 存储

### MySQL

无

### Redis (rdsidx=5)

| Key格式 | 类型 | 过期 | 说明 |
|---------|------|------|------|
| rdstqbroke_{userid} | HASH (roomid→val, losecount→val) | 服务端设定 | 玩家亏损信息：roomid=房间ID, losecount=当前亏损额 |

---

## PB

| PB文件 | 消息类型 |
|--------|---------|
| (内嵌) | tqbrokerecharge.ReqInfo, tqbrokerecharge.RspInfo, tqbrokerecharge.ReqUpdateUserBrokeInfo, tqbrokerecharge.NotifyUserPayResult |

---

## 对外接口

| 接口 | 说明 |
|------|------|
| onPayResult(payresult, item, userdata) | 支付回调，返回 (true, NewDepositOPType.BROKEN, addcount) |

## 注入接口

无

## 消息处理

| 消息ID | 处理函数 | 说明 |
|--------|---------|------|
| GR_TQBROKERECHARGE_REQ | — | 查询破产充值信息 |
| GR_TQBROKERECHARGE_UPDATEUSERINFO | — | 更新玩家亏损信息(来自gameSvr) |
