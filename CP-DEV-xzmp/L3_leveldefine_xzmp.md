# L3 等级模块 leveldefine_xzmp

> 核心模块，被 goldbank、award、joyfulgift、resurrect 等模块引用。

---

## 模块定位

等级模块管理玩家经验值与等级关系，提供降级/恢复机制和一次性奖励发放。是充值→特权体系的核心枢纽。

---

## 文件结构

| 文件 | 说明 |
|------|------|
| leveldefine_xzmp.ts | 主脚本 |
| leveldefine_xzmp.jsonc | 等级配置（0~15级） |
| leveldefine_xzmp.jsonc.used | 配置备份 |
| leveldefine_xzmp_withCardBack.jsonc | 含牌背的配置变体 |

---

## 核心机制

### 等级计算

- 经验源：`totalConsumeNum`（消耗通宝累计）
- 映射：`getPlayerLevelNumByExp(exp)` → 遍历 `levelContent` 找 `experience <= exp` 的最高 `levelid`
- 显示等级：`trueLevelid = rawLevelid - userDegradeNum`

### 降级

- 条件：每 `degradeDays=7` 天未登录降1级
- 计算：`calcUserDegradeNum(lastLoginTime, curTime, 7)` = `floor(离线秒数 / 7天秒数)`
- 保底：`degradeToLowestLimit=1`，确保显示等级 >= 1
- 存储：`userDegradeNum` 字段累计降级数

### 降级恢复

- 触发：消耗任意通宝（OnPayResult 中 `pay.gamegoodsid.exchangeid` 在 `ExchangeIDMap` 内）
- 动作：`userDegradeNum = 0`，等级恢复到经验对应的历史最高
- 客户端动画：`animStatus=2`（降级恢复）
- 前提：exchangeID 必须在 ExchangeIDMap 中，否则直接 return 不恢复

### 一次性奖励

- 状态：`NOT_RECEIVED(0)` → `CAN_RECEIVED(1)` → `RECEIVED(2)`
- 存储：`oneOffRewardStatusArray[levelid]`
- 可领取条件：原等级（rawLevelid + userDegradeNum）>= levelID 且 status == CAN_RECEIVED
- 降级恢复时：按 `trueLevelid` 更新可领取范围

---

## 数据结构

### UserData_PlayerLevelInfo

| 字段 | 类型 | 说明 |
|------|------|------|
| totalAcquireNum | number | 充值通宝累计 |
| totalConsumeNum | number | 消耗通宝累计（决定等级的经验值） |
| lastAcquireTime | number/string | 上次充值时间（秒级时间戳） |
| lastConsumeTime | number/string | 上次消耗时间 |
| lastLogonTime | number/string | 上次登录时间 |
| userDegradeNum | number | 累计降级数 |
| oneOffRewardStatusArray | {status, gotTime}[] | 各等级奖励领取状态 |

### LevelDefineConfig（jsonc）

| 字段 | 说明 |
|------|------|
| rmb2experience | 人民币→经验汇率（100） |
| degradeDays | 降级间隔天数（7） |
| degradeToLowestLimit | 降级保底等级（1） |
| ExchangeIDMap | exchangeID→人民币价格映射 |
| ExchangeIDMap2 | 各模块加赠配置（shop/resurrect/joyfulgift） |
| relateModule | 依赖本模块的模块列表 |
| levelContent | 各等级配置（experience/privilege/rewards） |

---

## 关键回调

| 回调 | 说明 |
|------|------|
| OnPayResult | 充值/消耗通宝入口。区分 acquireTongBao（充值）和 consumeTongBao（消耗） |
| OnClientRequest | 客户端查询配置、领取一次性奖励 |
| OnInternalCall | 跨模块更新 Redis/MySQL 玩家等级数据 |
| OnScriptReload | 脚本重载，通知 relateModule 更新配置 |

---

## 消息名

| 消息 | 方向 | 说明 |
|------|------|------|
| playerLevelChange | → otherModule | 玩家经验/等级变化通知 |
| forceUpdateLevelConfig | → relateModule | 强制更新等级配置缓存 |
| updateRedisPlayerLevelInfo | → otherModule | 更新 Redis 等级数据 |
| updateMysqlPlayerLevelInfo | → otherModule | 更新 MySQL 等级数据 |
| queryLevelDefineConfig | ← client | 查询等级配置 |
| reqTakeOneOffReward | ← client | 领取一次性奖励 |
| notifyShopLevelAddition | → client | 商城附赠金币通知 |
| notifyPlayerLevelChange_leveldefine | → client | 等级变化通知 |

---

## 特权体系

各等级 privilege 分三类：

| 类型 | 说明 | 示例 |
|------|------|------|
| isNew | 本级新增特权 | lv1: shopRedouble=2 |
| isUpdate | 本级更新数值 | lv1: reliefRedouble=2 |
| plain | 前级已有，本级不变 | lv2: resurrectHigh=2 |

特权类型：shopRedouble、resurrectLow/High/Redouble、reliefCount/Redouble、joyfulCount/Redouble、goldbank.maxSaveLimit

---

## 已知问题

### 降级保底逻辑

`degradeToLowestLimit=1` 在以下场景行为与预期不完全一致：

1. **等级0玩家不受保底保护**：curLevel=0 时 `Math.max(0-1, 0)=0`，userDegradeNum=0，显示等级仍为0
2. **等级1玩家不降级**：curLevel=1 时 `Math.max(1-1, 0)=0`，userDegradeNum=0，虽显示等级=1符合预期，但降级数被清零，消耗通宝时 isDegrade=false，不会触发恢复动画

### 降级恢复前提

消耗通宝恢复需 exchangeID 在 ExchangeIDMap 中。不在映射表中的通宝消耗会直接 return，不会恢复等级。

---

## 数据存储

| 存储 | 命名 |
|------|------|
| MySQL表 | tblcpuserdata_leveldefine_xzmp |
| MySQL字段名 | PlayerLevelInfo |
| Redis键 | mod(cp):name(leveldefine):appcode(xzmp):uid({uid}):PlayerLevelInfo |
| Redis过期 | 7天 |

读写顺序：MySQL → Redis。写时先 MySQL safeSave 再 Redis setData。