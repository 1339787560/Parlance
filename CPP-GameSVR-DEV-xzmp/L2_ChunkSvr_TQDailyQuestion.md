# L2 TQDailyQuestion — 每日答题

> 模块名: TQDailyQuestion | 用户称呼: tqdailyquestion | 消息ID: 450750-450759

---

## 功能

每日答题系统：基于等级的题库，连续答对升级，答错降级，全部答对有倍率加成。玩家动态数据用PB序列化后以BLOB存入MySQL。

---

## 存储

### MySQL

| 表名 | 结构 | 说明 |
|------|------|------|
| tbltqdailyquestion | userid(int PK), userdata(blob) | userdata = PB编码的 tqdailyquestion.Player |

### Redis

无

---

## PB

| PB文件 | 消息类型 |
|--------|---------|
| (内嵌) | tqdailyquestion.ReqInfo, tqdailyquestion.ReqAnswer, tqdailyquestion.ReqPrize, tqdailyquestion.RspInfo, tqdailyquestion.RspAnswer, tqdailyquestion.RspPrize, tqdailyquestion.Player(DB持久化), tqdailyquestion.NotifyPrize |

---

## 对外接口

无导出函数，纯被动响应。

## 注入接口

| 接口 | 来源 | 说明 |
|------|------|------|
| imNewDepositOp(userid, totalPrize, params) | NewDeposit | 领取奖品时发放银两 |

## 消息处理

| 消息ID | 处理函数 | 说明 |
|--------|---------|------|
| GR_TQDAILYQUESTION_REQINFO | — | 查询答题信息 |
| GR_TQDAILYQUESTION_REQANSWER | — | 提交答案 |
| GR_TQDAILYQUESTION_REQPRIZE | — | 领取奖品 |
