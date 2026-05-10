# cmnewplayerdailygift 模块详情

## 基本信息

| 属性 | 值 |
|------|-----|
| 模块名 | cmnewplayerdailygift |
| 脚本文件 | cmnewplayerdailygift_xzmp.ts |
| 配置文件 | cmnewplayerdailygift_xzmp.jsonc |
| GAME_CODE | xzmp |
| GAME_ID | 283 |

## 功能概述

迎新礼包2 — 新手玩家充值后连续7天领取奖励。客户端判断玩家局数低于阈值时展示入口，玩家充值成功后立即发放第一天奖励，后续6天每日登录手动领取。过期判断基于自然日（购买当天为第0天，次日为第1天），超过 `checkindays` 自然日后礼包失效。

## 主要函数

### 客户端请求处理

| 消息名 | 说明 | 请求参数 | 响应数据 |
|--------|------|----------|----------|
| queryNewPlayerDailyGiftConfig | 查询配置和玩家状态 | 无 | `{ cfg, giftInfo }` 或 `{ error }` |
| claimDailyReward | 领取当日奖励 | 无 | `{ rewardDay, reward, giftInfo }` 或 `{ error }` |

### 服务端推送消息

| 消息名 | 说明 | 推送数据 |
|--------|------|----------|
| onNewPlayerDailyGiftPurchased | 充值成功，第一天奖励已发放 | `{ giftInfo, reward }` |

### 内部模块调用

无

### 其他回调

| 回调 | 说明 |
|------|------|
| OnScriptReload | 加载配置 |
| OnPayResult | 判断 exchangeid 匹配后，发放第一天奖励，记录购买时间和状态，推送通知客户端 |

## 数据结构

### GameConfig（配置）

```typescript
interface GameConfig {
    isenable: number;          // 开关，1启用，0禁用
    guid: string;              // 发奖唯一标识
    newuserbout: number;       // 新手判定局数上限（客户端判断用）
    limittime: number;         // 限时展示时间（秒），UI展示用
    checkindays: number;       // 签到总天数，超过此自然天数后礼包过期
    checkinPropID: number;     // 签到奖励道具ID（金币: 21770）
    checkinReward: number[];   // 7天奖励列表，索引0为第一天
    clientDesc: string;        // 客户端展示描述模板
    exchangeid: number;        // 兑换商品ID（用于 OnPayResult 匹配）
}
```

### UserData_NewPlayerDailyGiftInfo（玩家数据）

```typescript
class UserData_NewPlayerDailyGiftInfo {
    buyTime: number;           // 购买时间（秒级时间戳），0=未购买
    lastClaimDay: number;      // 已领取到第几天 (1=第一天, 2=第二天...)
    lastClaimDate: number;     // 上次领取日期（YYYYMMDD 格式，如 20260421）

    constructor() {
        this.buyTime = 0;
        this.lastClaimDay = 0;
        this.lastClaimDate = 0;
    }
}
```

### cp2Client_GiftInfo（推送给客户端的状态）

```typescript
interface cp2Client_GiftInfo {
    hasPurchased: boolean;
    buyTime: number;
    lastClaimDay: number;
    canClaimToday: boolean;    // 今日是否可领取
    remainingDays: number;     // 剩余可领取天数
}
```

未购买时 `giftInfo` 为 `null`。

## 依赖模块

无（独立模块）

## 消息号列表

| 常量名 | 值 | 方向 |
|--------|-----|------|
| QUERY_CONFIG | queryNewPlayerDailyGiftConfig | From Client |
| CLAIM_DAILY_REWARD | claimDailyReward | From Client |
| ON_PURCHASED | onNewPlayerDailyGiftPurchased | To Client |

## 存储结构

| 存储 | 标识 |
|------|------|
| MySQL 表 | `tblcpuserdata_cmnewplayerdailygift_xzmp`，name 字段: "NewPlayerDailyGiftInfo" |
| Redis Key | `mod(cp):name(cmnewplayerdailygift):appcode(xzmp):uid({uid}):NewPlayerDailyGiftInfo`，过期: 7天 |

## 核心流程

### 充值回调 (OnPayResult)

1. 过滤 `payinfoflag == 0` 的立即兑换消息
2. 检查 `exchangeid` 是否匹配配置
3. 检查是否已购买过（`buyTime > 0` 则忽略）
4. 发放第一天奖励（`checkinReward[0]`，道具ID 为 `checkinPropID`）
5. 设置 `buyTime`、`lastClaimDay = 1`、`lastClaimDate = 当前日期`
6. 构造 `cp2Client_GiftInfo`，推送 `ON_PURCHASED` 给客户端

### 每日签到 (claimDailyReward)

1. 检查是否已购买（`buyTime == 0`）
2. 检查是否已领取完所有奖励（`lastClaimDay >= checkinReward.length`）
3. 检查今日是否已领取（`lastClaimDate >= todayDate`）
4. 检查是否在有效期内（自然日天数差 < `checkindays`）
5. 计算下次领取天数：`nextRewardDay = lastClaimDay + 1`
6. 发放当日奖励（`checkinReward[nextRewardDay - 1]`）
7. 更新 `lastClaimDay = nextRewardDay`、`lastClaimDate = todayDate`
8. 返回 `{ rewardDay, reward, giftInfo }`

### 过期判断

使用自然日计算：购买当天为第0天，次日为第1天。
过期条件：`calcNaturalDaysPassed(buyTime) >= checkindays`

日期编码格式：`YYYYMMDD`（如 `20260422 = 2026*10000 + 4*100 + 22`）

## 错误码

| 错误信息 | 说明 |
|---------|------|
| 礼包未启用 | 配置 isenable = 0 |
| 未购买礼包 | 玩家未购买迎新礼包（buyTime = 0） |
| 已领取完所有奖励 | lastClaimDay >= checkinReward.length |
| 今日已领取 | lastClaimDate >= todayDate |
| 礼包已过期 | 自然日天数差 >= checkindays |
| 发放奖励失败 | 服务端发奖异常 |

## 常量定义

```typescript
const CONST_VAR = {
    MODULE_NAME: 'cmnewplayerdailygift',
    GAME_CODE: 'xzmp',
    APP_CODE: 'xzmp',
    GAME_ID: 283,
    DAY_SECONDS: 86400,
}
```