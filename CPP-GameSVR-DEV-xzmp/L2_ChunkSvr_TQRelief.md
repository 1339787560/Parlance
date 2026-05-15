# L2 TQRelief — 低保救济

> 模块名: TQRelief | 用户称呼: tqrelief | 消息ID: 450280-450289

---

## 功能

低保救济系统：玩家银两低于阈值时可领取救济金，每人每设备每日有限次，VIP等级有加成比例。领取后通知 TQMatchv2 模块。

---

## 存储

### MySQL

无

### Redis (rdsidx=5)

| Key格式 | 类型 | 过期 | 说明 |
|---------|------|------|------|
| rdstqrelief_user_{D} | HASH (userid→count) | 25h | 玩家当日领取次数 |
| rdstqrelief_dev_{D} | HASH (deviceid→count) | 25h | 设备当日领取次数 |

> {D}=日编号

---

## PB

| PB文件 | 消息类型 |
|--------|---------|
| (内嵌) | tqrelief.ReqInfo, tqrelief.ReqTakeRelief, tqrelief.RspInfo, tqrelief.RspTakeRelief |

---

## 对外接口

无导出函数，纯被动响应。

## 注入接口

| 接口 | 来源 | 说明 |
|------|------|------|
| imGetUserNewDeposit(userid) | NewDeposit | 查询当前银两余额(判断是否低于阈值) |
| imNewDepositOp(userid, prize, params) | NewDeposit | 发放救济银两(含VIP加成分裂) |
| imGetVipInfoByModule(moduleType, userid) | TQVip | 获取VIP等级和加成比例 |

## 跨模块调用

| 调用 | 说明 |
|------|------|
| TQMatchv2:onUserGetReleif({userid, roomid}) | 领取救济后通知匹配系统 |

## 消息处理

| 消息ID | 处理函数 | 说明 |
|--------|---------|------|
| GR_TQRELIEF_REQ | — | 查询救济信息 |
| GR_TQRELIEF_TAKE | — | 领取救济金 |
