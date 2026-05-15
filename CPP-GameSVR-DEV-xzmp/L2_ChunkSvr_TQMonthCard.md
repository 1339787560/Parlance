# L2 TQMonthCard — 月卡/周卡

> 模块名: TQMonthCard | 用户称呼: tqmonthcard | 消息ID: 450800-450809

---

## 功能

月卡/周卡系统：处理购买激活（时长叠加）、每日银两+道具发放、补赔特权刷新、卡过期检查、道具日志记录。

---

## 存储

### MySQL (lasyncache)

| 表名 | 结构 | 说明 |
|------|------|------|
| sqlas_tqmonthcard | mainkey(int PK), data(blob) | data = PB编码的 tqmonthcard.Cache |

### Redis (lasyncache 代理)

| Key格式 | 类型 | 说明 |
|---------|------|------|
| tqmonthcard:{mainkey} | STRING | PB编码缓存 |
| rdsdirtycachelist:sqlas_tqmonthcard | SET | 脏数据集合 |

---

## PB

| PB文件 | 消息类型 |
|--------|---------|
| tqmonthcard.pb | ReqInfo, RspInfo, Cache(缓存序列化), NotifyPay |

---

## 对外接口

| 接口 | 说明 |
|------|------|
| onPayResult(payresult, item, orderinfo) | 支付回调，处理月卡/周卡购买 |
| getPrivilegeCount(userid, privilegeName) | 返回 hasPrivilege, count — 查询月卡特权次数 |
| testChangeDays(userid, type, timenum) | 调试：修改卡天数 |

## 注入接口

| 接口 | 来源 | 说明 |
|------|------|------|
| imAddProps | TQProp | 添加道具(每日道具发放) |
| imGetAllProps | TQProp | 获取玩家全部道具 |
| imLogProps | TQProp | 记录道具日志 |

## 消息处理

| 消息ID | 处理函数 | 说明 |
|--------|---------|------|
| GR_TQMONTHCARD_REQINFO | — | 查询月卡/周卡信息 |

## 被其他模块依赖

| 依赖模块 | 接口 | 说明 |
|----------|------|------|
| TQLuckyTurnTable | imGetPrivilegeCount | 查询月卡特权额外抽奖次数 |
