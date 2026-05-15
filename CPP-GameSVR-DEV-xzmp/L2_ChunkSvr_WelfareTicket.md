# L2 WelfareTicket — 福利券兑换

> 模块名: WelfareTicket | 用户称呼: tqwelfare | 消息ID: 450040-450059

---

## 功能

福利券(优惠券)系统：管理按月计的福利券余额（带过期机制）、商城商品兑换（金币/道具/实物）、福利券赠送（含每日熔合保护）、钉钉报警通知。

---

## 存储

### MySQL

| 表名 | 结构 | 说明 |
|------|------|------|
| tblwelfareticket_userhistory_{M} | id(AUTO_INCREMENT), userid, count, time(bigint), goodstype, goodscount, goodstime, name(varchar) | 玩家兑换历史，按月分表。KEY userid |
| tblwelfareticket_expiredrecord | userid, expireddate, count | 过期记录。PK (userid, expireddate) |

### Redis (rdsidx=3)

| Key格式 | 类型 | 过期 | 说明 |
|---------|------|------|------|
| rdswelfareticket_user_{M} | ZSET (userid→count) | 4个月 | 当月玩家福利券余额 |
| rdswelfareticket_active_{M} | STRING (count) | 4个月 | 当月可用总量 |
| rdswelfareticket_obtain_{D} | STRING (count) | 2天 | 当天产出 |
| rdswelfareticket_consume_{D} | STRING (count) | 2天 | 当天消耗 |
| rdswelfareticket_userobtain_{D} | HASH (userid→count) | 2天 | 玩家当天产出 |
| rdswelfareticket_goods_freshuse_{id} | STRING | — | 商品周期内使用数量 |
| rdswelfareticket_goods_limituse_{id} | STRING | — | 商品总使用数量 |
| rdswelfareticket_goods_lastdate_{id} | STRING | — | 商品定时器上次刷新时间 |
| rdswelfareticket_goods_daliy_use_{id}_{D} | STRING | 14天 | 商品每天消耗量 |

> {M}=月编号, {D}=日编号, {id}=商品ID

---

## PB

| PB文件 | 消息类型 |
|--------|---------|
| welfareticket.pb | QueryUserInfo, ReqSaveExpiredTickets, ReqGetGoodsStatus, ReqExchangeGoods, RspUserInfo, RspUserHistroy, RspGoodsStatus, RspExchangeGoods, RecordTicketUserInfos, NotifyUserTicket |

---

## 对外接口

| 接口 | 说明 |
|------|------|
| `exchangeTicket(userid, count, name, goodstype, goodscount, goodstime)` | 扣减福利券并记录交易 |
| `presentTicket(userid, count, name, needfuse)` | 赠送福利券，needfuse控制每日熔合保护 |

## 消息处理

| 消息ID | 处理函数 | 说明 |
|--------|---------|------|
| GR_WELFARETICKET_QUERY | — | 查询用户福利券信息 |
| GR_WELFARETICKET_GETUSERHISTORY | — | 获取兑换历史 |
| GR_WELFARETICKET_GETGOODSSTATUS | — | 获取商品库存状态 |
| GR_WELFARETICKET_EXCHANGEGOODS | — | 兑换商品 |
| GR_WELFARETICKET_SAVEEXPIREDTICKETS | — | 保存过期券记录 |
| GR_WELFARETICKET_TEST | — | 测试入口 |

## 主动发送

| 消息ID | 目标 | 说明 |
|--------|------|------|
| GR_WELFARETICKET_RECORDTICKETUSERINFO | otherchunk | 记录用户券变动 |
| GR_WELFARETICKET_CHANGE | assistSvr | 通知客户端券变更 |
