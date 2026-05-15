# L2 TQDecorations — 装扮系统

> 模块名: TQDecorations | 用户称呼: tqdecoration | 消息ID: 450810-450829

---

## 功能

装扮系统：管理玩家装饰品（头像、桌面皮肤、牌背），处理信息查询、记录更新、自动赠送免费默认装扮、机器人进房时分配随机加权头像。

---

## 存储

### MySQL (lasyncache)

| 表名 | 结构 | 说明 |
|------|------|------|
| sqlas_tqdecoration | mainkey(int PK), data(blob) | data = PB编码的 tqdecoration.DecorationCache |

### Redis (lasyncache 代理)

| Key格式 | 类型 | 说明 |
|---------|------|------|
| tqdecoration:{mainkey} | STRING | PB编码缓存，lasyncache 管理 |
| rdsdirtycachelist:sqlas_tqdecoration | SET | 脏数据集合，定时刷盘到MySQL |

---

## PB

| PB文件 | 消息类型 |
|--------|---------|
| tqdecoration.pb | ReqInfo, RspInfo, ReqDecorationUpdate, NtfRobotEnter, DecorationCache(缓存序列化) |

---

## 对外接口

| 接口 | 说明 |
|------|------|
| getDecorationRecord(userid) | 返回 isOK, record — 获取玩家装扮记录 |
| getHeadConfigByID / getTableConfigByID / getCardConfigByID / getDecorationConfigByID | 配置查询辅助函数 |

## 注入接口

| 接口 | 来源 | 说明 |
|------|------|------|
| imAddProps | TQProp | 添加道具(装扮发放) |
| imGetAllProps | TQProp | 获取玩家全部道具 |

## 消息处理

| 消息ID | 处理函数 | 说明 |
|--------|---------|------|
| GR_TQDECORATIONS_REQINFO | — | 查询装扮信息 |
| GR_TQDECORATIONS_UPDATERECORD_REQ | — | 更新装扮记录 |
| GR_TQDECORATIONS_ROBOTENTER_NTF | — | 机器人进房通知(分配随机头像) |
