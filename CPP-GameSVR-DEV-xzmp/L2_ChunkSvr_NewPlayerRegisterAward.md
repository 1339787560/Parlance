# L2 NewPlayerRegisterAward — 新玩家注册奖励

> 模块名: NewPlayerRegisterAward | 用户称呼: newplayerregister | 消息ID: 450260-450269

---

## 功能

新玩家注册奖励：一次性奖励，首次请求时发放 config.awardcount 银两并触发兑换流程，后续请求返回 awarded=false。

---

## 存储

### MySQL

| 表名 | 结构 | 说明 |
|------|------|------|
| tblnewplayerregisteraward | userid(int PK), awarded(int) | awarded=0未领取, 1已领取 |

### Redis

无

---

## PB

| PB文件 | 消息类型 |
|--------|---------|
| (内嵌) | newplayerregisteraward.ReqInfo, newplayerregisteraward.RspInfo |

---

## 对外接口

无导出函数，纯被动响应。

## 注入接口

| 接口 | 来源 | 说明 |
|------|------|------|
| imNewDepositOp(userid, count) | NewDeposit | 发放注册奖励银两 |
| imNewdepositExchange(userid) | NewDeposit | 触发兑换流程 |

## 消息处理

| 消息ID | 处理函数 | 说明 |
|--------|---------|------|
| GR_NEWPLAYER_REGISTER_AWARD_REQ | — | 查询/领取注册奖励 |
