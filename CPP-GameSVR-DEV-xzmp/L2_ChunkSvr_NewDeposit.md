# L2 NewDeposit — 银两(新存款)核心

> 模块名: NewDeposit | 用户称呼: depositexchange | 消息ID: 450160-450259

---

## 功能

银两(新存款)核心模块：管理玩家银两余额，处理银两兑换（首次兑换+系数公式）、对局结算（含金钟罩/包赔特殊逻辑）、RMB充值回调、通宝兑换、跨服消息查询/操作。提供 export_* 接口供其他模块增减银两并自动记录流水和通知。

---

## 存储

### MySQL

| 表名 | 结构 | 说明 |
|------|------|------|
| tblnewdeposit | userid(int PK), newdeposit(bigint unsigned) | 玩家银两余额 |

### Redis

无（通过C++内存缓存管理玩家余额）

---

## PB

| PB文件 | 消息类型 |
|--------|---------|
| newdeposit.pb | ReqUserNewDeposit, ReqExchangeDeposit, ReqGameResult, ReqConfig, RspUserNewDeposit, RspExchangeDeposit, RspConfig, NotifyUserNewDepositUpdate, NotifyUserNewDepositUpdateList, NotifyNewDepositPayResult, GameResultFailed, ReqNewDepositOpRecord, ReqNewDepositOpRecordMultiple, ReqSaveExchangeRecord, ReqNewDepositPayResultRecord, ReqMsgPackGetUserInfo, ReqMsgPackRobotNewDepositOP, RspMsgPackGetUserInfo, RspMsgPackRobotNewDepositOP |
| pbTongbao.pb | exchange, TongBaoExchangeRecord |

---

## 对外接口

| 接口 | 说明 |
|------|------|
| addMoudleCallback(mname, mcallback) | 注册模块回调(充值事件) |
| addChargeCallback(mname, mcallback) | 注册充值回调 |
| addTongbaoCallback(mname, mcallback) | 注册通宝回调 |
| addNewDepositDiffEvent(cb) | 注册银两变动事件 |
| addShopRmbEvent(cb) | 注册RMB商城事件 |
| OnPayResult(payresult) | 支付结果处理 |
| export_getnewdeposit(userid) | 获取玩家银两余额 |
| export_setnewdepositExchange(userid) | 设置兑换标记 |
| export_newdepositOp(userid, opcount, optype, notnotify, params) | **核心接口**：增减银两，自动记录流水+通知 |
| export_newdepositOpSet(userid, opcount, optype, roomid) | 批量增减银两(含roomid) |

## 注入接口

| 接口 | 来源 | 说明 |
|------|------|------|
| imGetPayOrder | PayOrder | 获取支付订单 |
| imGetTongbaoParams | PayOrder | 获取通宝参数 |
| imGetUserInfo | UserData | 获取用户信息 |
| imUseRedress | TQGameController | 使用免赔 |
| imGetVipInfoByModule | TQVip | VIP加成信息 |

## 消息处理

| 消息ID | 说明 |
|--------|------|
| GR_NEWDEPOSIT_GETINFO | 查询银两余额 |
| GR_NEWDEPOSIT_EXCHANGE | 银两兑换 |
| GR_NEWDEPOSIT_RESULT | 对局结算 |
| GR_NEWDEPOSIT_CONFIG | 查询配置 |
| GR_NEWDEPOSIT_TONGBAO_EXCHANGE | 通宝兑换 |
| GR_NEWDEPOSIT_MSGPACK_GETDEPOSIT | 跨服查询余额(msgpack) |
| GR_NEWDEPOSIT_ROBOT_OP | 机器人银两操作 |
| GR_NEWDEPOSIT_ROBOT_OP_SET | 机器人银两批量操作 |

## 主动发送

| 消息ID | 目标 | 说明 |
|--------|------|------|
| GR_NEWDEPOSIT_UPDATE | assistSvr | 银两变更通知 |
| GR_NEWDEPOSIT_UPDATE_EX | assistSvr | 扩展变更通知 |
| GR_NEWDEPOSIT_PAYRESULT | assistSvr | 支付结果通知 |
| GR_NEWDEPOSIT_OP_RECORD | otherchunk | 银两操作流水记录 |
| GR_NEWDEPOSIT_OP_RECORD_MULTIPLE | otherchunk | 批量流水记录 |
| GR_NEWDEPOSIT_EXCHANGE_RECORD | otherchunk | 兑换记录 |
| GR_NEWDEPOSIT_PAYRESULT_RECORD | otherchunk | 支付流水 |
| GR_NEWDEPOSIT_GAMERESULT_FAILED | gameSvr | 结算失败通知 |
| GR_TONGBAO_EXCHANGE_INNER | — | 通宝兑换内部消息 |
| GR_TONGBAOEXCHANGE_RECORD | otherchunk | 通宝兑换记录 |

## 被其他模块依赖

几乎所有活动模块通过注入 `imNewDepositOp` 或注册 moudleCallback/chargeCallback/tongbaoCallback 与此模块交互。
