# L2 TQCheckin — 每日签到

> 模块名: TQCheckin | 用户称呼: tqcheckin | 消息ID: 450270-450279

---

## 功能

每日签到系统：跟踪玩家连续签到天数，按轮转周期配置每日奖励，签到成功后通过 imNewDepositOp 发放银两。

---

## 存储

### MySQL

| 表名 | 结构 | 说明 |
|------|------|------|
| tbltqcheckin | userid(int PK), lastdate(int), checkday(int) | lastdate=上次签到日期, checkday=签到次数 |

### Redis

无

---

## PB

| PB文件 | 消息类型 |
|--------|---------|
| (内嵌) | tqcheckin.ReqInfo, tqcheckin.ReqDoCheckin, tqcheckin.RspInfo, tqcheckin.RspDoCheckin |

---

## 对外接口

无导出函数，纯被动响应。

## 注入接口

| 接口 | 来源 | 说明 |
|------|------|------|
| imNewDepositOp(userid, count) | NewDeposit | 签到成功后发放银两 |

## 消息处理

| 消息ID | 处理函数 | 说明 |
|--------|---------|------|
| GR_TQCHECKIN_REQ | — | 查询签到信息 |
| GR_TQCHECKIN_DOCHECKIN | — | 执行签到 |
