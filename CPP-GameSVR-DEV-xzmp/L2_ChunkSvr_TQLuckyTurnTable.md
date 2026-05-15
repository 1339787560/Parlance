# L2 TQLuckyTurnTable — 幸运转盘抽奖

> 模块名: TQLuckyTurnTable | 用户称呼: tqluckyturntable | 消息ID: 450710-450719

---

## 功能

幸运转盘抽奖：按权重随机抽取奖品，每日抽奖次数限制，月卡特权额外次数，抽中后通过 imNewDepositOp 发放银两。

---

## 存储

### MySQL

无

### Redis (rdsidx=5)

| Key格式 | 类型 | 过期 | 说明 |
|---------|------|------|------|
| rdstqluckyturntable:{D} | HASH (field→value) | 25h | 当日全局数据: daydrawcount, dayaddcount, dayaddcountflag |

> {D}=日编号

---

## PB

| PB文件 | 消息类型 |
|--------|---------|
| (内嵌) | tqluckyturntable.ReqInfo, tqluckyturntable.ReqDrawPrize, tqluckyturntable.RspInfo, tqluckyturntable.RspDrawPrize, tqluckyturntable.NotifyDrawPrize |

---

## 对外接口

无导出函数，纯被动响应。

## 注入接口

| 接口 | 来源 | 说明 |
|------|------|------|
| imNewDepositOp(userid, count, params) | NewDeposit | 抽奖后发放银两 |
| imGetPrivilegeCount(userid, key) | TQMonthCard | 检查月卡特权额外抽奖次数 |

## 消息处理

| 消息ID | 处理函数 | 说明 |
|--------|---------|------|
| GR_TQLUCKTURNTABLE_REQ | — | 查询转盘信息 |
| GR_TQLUCKTURNTABLE_DRAWPRIZE | — | 执行抽奖 |
