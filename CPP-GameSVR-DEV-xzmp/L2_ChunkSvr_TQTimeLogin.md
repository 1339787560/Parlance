# L2 TQTimeLogin — 定时登录奖励

> 模块名: TQTimeLogin | 用户称呼: tqtimelogin | 消息ID: 450700-450709

---

## 功能

定时登录奖励：每天按配置时间段发放银两奖励，玩家在指定时间窗口内领取，通过 imNewDepositOp 发放。每日每用户仅一次，数据纯Redis按日过期。

---

## 存储

### MySQL

无

### Redis (rdsidx=5)

| Key格式 | 类型 | 过期 | 说明 |
|---------|------|------|------|
| rdstqtimelogin_user_{D} | HASH (userid→status) | 25h | 玩家当日领取状态 |

> {D}=日编号

---

## PB

| PB文件 | 消息类型 |
|--------|---------|
| (内嵌) | tqtimelogin.ReqInfo, tqtimelogin.ReqReward, tqtimelogin.RspInfo, tqtimelogin.RspReward |

---

## 对外接口

无导出函数，纯被动响应。

## 注入接口

| 接口 | 来源 | 说明 |
|------|------|------|
| imNewDepositOp(userid, reward) | NewDeposit | 领取奖励时发放银两 |

## 消息处理

| 消息ID | 处理函数 | 说明 |
|--------|---------|------|
| GR_TQTIMELOGIN_INFO_REQ | — | 查询定时登录信息 |
| GR_TQTIMELOGIN_REWARD_REQ | — | 领取定时登录奖励 |
