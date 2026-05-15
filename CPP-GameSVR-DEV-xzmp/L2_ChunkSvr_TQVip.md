# L2 TQVip — VIP等级系统

> 模块名: TQVip | 用户称呼: tqvip | 消息ID: 450840-450849

---

## 功能

VIP等级系统：RMB消费累积经验，经验达到阈值自动升级，不活跃玩家降级(demoteday)，每级可领取一次奖励(道具+银两)，升级动画状态跟踪。

---

## 存储

### MySQL (lasyncache)

| 表名 | 结构 | 说明 |
|------|------|------|
| sqlas_tqvip | mainkey(int PK), data(blob) | data = PB编码的 tqvip.PlayerData |

### Redis (lasyncache 代理)

| Key格式 | 类型 | 说明 |
|---------|------|------|
| tqvip:{mainkey} | STRING | PB编码缓存 |
| rdsdirtycachelist:sqlas_tqvip | SET | 脏数据集合 |

---

## PB

| PB文件 | 消息类型 |
|--------|---------|
| tqvip.pb | ReqInfo, RspInfo, ReqShowUpGradeAni, ReqTakeReward, RspTakeReward, RspPayResult, ReqLog, PlayerData(缓存序列化) |

---

## 对外接口

| 接口 | 说明 |
|------|------|
| onPayRmb(params) | RMB支付回调，增加VIP经验 |
| onTongbaoExchange(params) | 通宝兑换回调，增加VIP经验 |
| updateGrade(userid, price, tongbaoprice, newdepositnum) | 核心升级逻辑 |
| getVipGradeByUserid(userid) | 返回VIP等级 |
| getVipInfoByModule(name, userid) | 返回 grade, addcount, addnewdepositratio, nextgrade, nextaddcount, nextaddnewdepositratio |
| text_SetInfo(...) | 调试：设置VIP信息 |

## 注入接口

| 接口 | 来源 | 说明 |
|------|------|------|
| imNewDepositOp | NewDeposit | 发放VIP奖励银两 |
| imAddProps | TQProp | 发放VIP奖励道具 |

## 消息处理

| 消息ID | 处理函数 | 说明 |
|--------|---------|------|
| GR_TQVIP_REQINFO | — | 查询VIP信息 |
| GR_TQVIP_SHOWANI | — | 升级动画确认 |
| GR_TQVIP_REQGETREWARD | — | 领取等级奖励 |
| GR_TQVIP_PAYRESULT | — | 支付结果通知(转发assistSvr) |
| GR_TQVIP_REQLOG | — | VIP日志(转发otherchunk) |

## 被其他模块依赖

| 依赖模块 | 接口 | 说明 |
|----------|------|------|
| TQRelief | imGetVipInfoByModule | VIP加成比例 |
| TQLuckyTurnTable | imGetVipInfoByModule | 特权次数 |
| QuickRechargeV2 | imGetVipInfoByModule | VIP加成 |
| ShakeGift | imGetVipInfoByModule | VIP加成 |
| NewDeposit | imGetVipInfoByModule | VIP加成 |
