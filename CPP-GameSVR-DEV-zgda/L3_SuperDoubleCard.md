# L3 超级加倍卡详细说明

> 超级加倍卡（PROP_SUPERDOUBLE）— 斗地主对局中的4倍乘数道具，跨 ChunkSvr 存储/购买/生效。

---

## 1. 道具定义

| 属性 | 值 | 来源 |
|------|------|------|
| propId | `PROP_SUPERDOUBLE` = 2003 | zgdfchunksvr/PropInfo.h |
| propType | `PROP_TYPE_COUNT`（计数型） | 枚举，id≥2000 为计数型 |
| 商品ID | 33587 | common/shop/GameShop.cpp `DIRECT_GOODS` |
| 筹码价格 | 2000 | 同上，可被 GameShop API 动态更新 |

---

## 2. 存储位置

**zgdfchunksvr**（残局机器人数据服务），不是 zgda chunksvr。

DB表 `propInfo`（MSSQL）：

| 字段 | 类型 | 说明 |
|------|------|------|
| userId | int | 用户ID |
| propId | int | 道具ID（超级加倍=2003） |
| count | int | 数量（使用-1，赠送+n） |
| beginDate | int | 开始日期 YYYYMMDD |
| beginTime | int | 开始时间 HHMMSS |
| endDate | int | 结束日期 |
| endTime | int | 结束时间 |

SQL示例：
```sql
-- 查询
SELECT * FROM propInfo WHERE userId=? AND propId=2003
-- 全量
SELECT * FROM propInfo WHERE userId=? ORDER BY propId ASC
```

旧表兼容：`tblPropInfo` 仅存日期记牌器（propId=1），新道具统一走 `propInfo`。

---

## 3. 生效流程

```
客户端显示超级加倍按钮(price=2000)
  → 玩家点击 OnSuperDouble()
  → CGameShop::BuyGameShopDirectItems(userId, os=3, goodsId=33587, price=2000)
      → HTTP GameShop服务扣筹码
  → 购买成功
      → REQ_AuctionByDouble(2) → 游戏服务
      → 聊天栏提示 "已成功加倍，扣除X筹码"
  → 购买失败
      → 提示 "抱歉，您的加倍筹码不足，请先充值再操作"

游戏服务收到 GR_PLAYER_DOUBLE_REQ
  → zgdatbl.cpp OnPlayerDouble(chair, SUPER_DOUBLE=2)
  → m_PlayerDouble[chair] = 4

结算时(zgdatbl.cpp:956)
  gains = 底分 × 2^(春天+炸弹数)
  地主赢: 地主得分 = gains × m_PlayerDouble[地主] × (m_PlayerDouble[农民1] + m_PlayerDouble[农民2])
  地主输: 地主失分 = gains × m_PlayerDouble[地主] × (m_PlayerDouble[农民1] + m_PlayerDouble[农民2])
```

---

## 4. DoubleType 枚举

| 枚举值 | 名称 | m_PlayerDouble映射 | 含义 |
|--------|------|---------------------|------|
| 0 | NO_DOUBLE | 1 | 不加倍（默认1倍） |
| 1 | DOUBLE | 2 | 普通加倍（2倍） |
| 2 | SUPER_DOUBLE | 4 | 超级加倍（4倍） |
| 3 | DOUBLE_AND_SUPER | — | 同时允许普通和超级加倍选择 |

来源：common/zgda/zgdareq.h `enum class DoubleType`

---

## 5. 道具操作接口（zgdfchunksvr）

| 操作 | 方法 | 路径 |
|------|------|------|
| 查询数量 | `GetSinglePropInfo()` → `DB_GetSinglePropInfo` | zgdfchunksvr/PropInfo.cpp |
| 使用（-1） | `OnPropUse()` → `UseNormalCountProp()` | zgdfchunksvr/PropInfo.cpp:346 |
| 系统赠送 | `TakeSuperDouble(userID, count)` | zgdfchunksvr/PropInfo.cpp:637 |
| 赠送记录 | `RecordTakePropToLogServer(userID, PROP_SUPERDOUBLE, count, PROP_TAKE_GRANT)` | 同上 |
| 变动通知 | `NotifyOneUserPropChanged(userID, PROP_SUPERDOUBLE, diffCount)` | 跨服通知 |

---

## 6. 配置来源

游戏服务侧（INI文件，按roomID配置）：

```ini
[DoubleType]
<roomID> = 2   ; 该房间允许超级加倍(值=2表示仅超级加倍, 3表示普通+超级)

[SuperDoubleCost]
<roomID> = 500  ; 超级加倍默认扣筹码500(客户端通过GameShop购买为2000)
```

来源：zgdatbl.cpp `ReadDoubleCommonInfo()` → `GetPrivateProfileInt`

客户端侧收到 `GAME_START_INFO.nReserve[2]` = `m_nSuperDoubleCost`。

---

## 7. 跨服务关系

| 服务 | 角色 | 关键文件 |
|------|------|----------|
| **zgdasvr** | 游戏服务 — 加倍选择+结算生效 | common/zgdatbl.cpp, common/zgdatbl.h |
| **zgdfchunksvr** | 数据服务 — 道具存储/使用/赠送 | zgdfchunksvr/PropInfo.cpp, PropInfo.h |
| **GameShop HTTP** | 商城服务 — 筹码购买扣款 | common/shop/GameShop.cpp, GameShop.h |
| **客户端(zgda)** | UI交互 — 按钮展示+购买发起+数量展示 | zgda/MyGame.cpp:9185(OnSuperDouble) |

超级加倍卡道具数量由客户端通过 zgdfchunksvr 的 `GetAllPropInfo` 查询并在道具面板展示。