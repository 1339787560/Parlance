# cmnewplayerdailygift_xzmp 需求原型文档

## 模块概述

| 属性 | 值 |
|------|-----|
| 模块名称 | cmnewplayerdailygift |
| 功能 | 迎新礼包2 - 新手玩家充值后连续7天领取奖励 |
| 游戏代码 | xzmp |
| 游戏ID | 283 |

## 业务流程

```
┌─────────────────────────────────────────────────────────────┐
│                      迎新礼包流程                            │
├─────────────────────────────────────────────────────────────┤
│  1. 客户端判断玩家局数 < newuserbout，展示礼包入口            │
│  2. 玩家充值成功 → OnPayResult → 立即发放第一天奖励           │
│  3. 后续6天，玩家每日登录后手动领取当日奖励                   │
│  4. 7天后（或超过checkindays天）礼包失效，不再展示           │
└─────────────────────────────────────────────────────────────┘
```

## 配置项说明

| 字段 | 类型 | 说明 |
|------|------|------|
| isenable | number | 开关，1启用，0禁用 |
| guid | string | 发奖唯一标识 |
| newuserbout | number | 新手判定局数上限（客户端判断用） |
| limittime | number | 限时展示时间（秒），仅供客户端UI展示 |
| checkindays | number | 签到总天数，玩家必须在此天数内领完奖励 |
| checkinPropID | number | 签到奖励道具ID（金币: 21770） |
| checkinReward | number[] | 7天奖励列表，索引0为第一天奖励 |
| clientDesc | string | 客户端展示描述模板 |
| exchangeid | number | 充值商品ID（待配置） |

## 数据存储结构

### 玩家数据 (UserData_NewPlayerDailyGiftInfo)

```typescript
class UserData_NewPlayerDailyGiftInfo {
    buyTime: number;           // 购买时间（秒级时间戳）
    lastClaimDay: number;      // 已领取到第几天 (0-6)，0表示仅领取第一天
    lastClaimDate: number;     // 上次领取日期（格式：YYYYMMDD）
}
```

### 存储位置

| 存储 | Key/表名格式 |
|------|-------------|
| MySQL | `tblcpuserdata_cmnewplayerdailygift_xzmp` |
| Redis | `mod(cp):name(cmnewplayerdailygift):appcode(xzmp):uid(${uid}):NewPlayerDailyGiftInfo` |

## 消息定义

### 客户端请求 (OnClientRequest)

| 消息名 | 说明 | 请求参数 | 响应数据 |
|--------|------|----------|----------|
| queryNewPlayerDailyGiftConfig | 查询配置和状态 | 无 | `{ cfg, giftInfo }` |
| claimDailyReward | 领取当日奖励 | 无 | `{ rewardDay, reward }` |

### 服务端推送 (to Client)

| 消息名 | 说明 | 数据内容 |
|--------|------|----------|
| onNewPlayerDailyGiftPurchased | 充值成功，第一天奖励已发放 | `{ giftInfo, reward }` |

**推送数据结构：**
```typescript
{
    giftInfo: {
        hasPurchased: boolean;
        buyTime: number;
        lastClaimDay: number;       // 0，第一天已领取
        canClaimToday: boolean;     // false，今日已领取
        remainingDays: number;      // 6，剩余可领取天数
    },
    reward: {
        propId: number,
        propCount: number
    }
}
```

## 接口详细设计

### 1. 查询配置接口

**请求：**
```typescript
{
    req: "queryNewPlayerDailyGiftConfig"
}
```

**响应：**
```typescript
{
    cfg: {
        isenable: number;
        guid: string;
        newuserbout: number;
        limittime: number;
        checkindays: number;
        checkinPropID: number;
        checkinReward: number[];
        clientDesc: string;
    },
    giftInfo: {
        hasPurchased: boolean;      // 是否已购买
        buyTime: number;            // 购买时间（秒级时间戳）
        lastClaimDay: number;       // 已领取到第几天 (0-6)
        canClaimToday: boolean;     // 今日是否可领取
        remainingDays: number;      // 剩余可领取天数
    } | null                        // 未购买时为 null
}
```

### 2. 领取当日奖励接口

**请求：**
```typescript
{
    req: "claimDailyReward"
}
```

**响应（成功）：**
```typescript
{
    id: 1,
    data: {
        rewardDay: number,          // 领取的是第几天的奖励 (2-7)
        reward: {
            propId: number,         // 道具ID
            propCount: number       // 道具数量
        }
    }
}
```

**响应（失败）：**
```typescript
{
    id: 0,
    data: {
        error: string               // 错误原因
    }
}
```

**失败场景：**
- 未购买礼包
- 今日已领取
- 已超过有效期（checkindays天）
- 已领取完所有奖励

### 3. 充值回调 (OnPayResult)

**处理逻辑：**
1. 判断 exchangeid 是否匹配配置的兑换商品
2. 检查是否已购买过（防止重复）
3. 发放第一天奖励（checkinReward[0]）
4. 记录购买时间和状态
5. 推送消息通知客户端（包含 giftInfo 和奖励信息）

## 核心业务逻辑

### 签到天数计算

```typescript
// 购买当天为第1天，后续每天可领取第2-7天奖励
// 判断是否为新的一天：比较 lastClaimDate 与当前日期
function isNewDay(lastClaimDate: number): boolean {
    return getDateNum() > lastClaimDate;
}

// 计算当前应领取第几天的奖励
function calcCurrentRewardDay(buyTime: number, lastClaimDay: number): number {
    return lastClaimDay + 1;  // 上次领到第N天，下次领第N+1天
}

// 检查是否在有效期内
function isValidPeriod(buyTime: number, checkindays: number): boolean {
    let daysPassed = calcDaysPassed(buyTime);
    return daysPassed < checkindays;
}
```

### 发奖逻辑

```typescript
// 参考月卡模块的 async_batch_send_reward
async function sendReward(src, cxt, userid, propId, propCount, guid): Promise<boolean> {
    let rewardList = [{ propid: propId, count: propCount }];
    await modsvr.async_batch_send_reward(src, cxt, userid, rewardList, guid);
    // 检查发放状态...
}
```

## 边界条件处理

| 场景 | 处理方式 |
|------|----------|
| 玩家重复购买 | 忽略，不重复发放第一天奖励 |
| 玩家跨越日期登录 | 允许领取当天奖励，但不补签之前的奖励 |
| 玩家超过有效期请求 | 返回错误，提示礼包已过期 |
| 配置 isenable = 0 | 所有接口返回空数据或错误 |
| 大额金币发放（>20亿） | 参考 `async_sendGoldCoin_super` 分批发送 |

## 工具类设计

### MySqlTool_NewPlayerDailyGiftInfo

```typescript
class MySqlTool_NewPlayerDailyGiftInfo {
    MYSQL_TABLE_NAME = `tblcpuserdata_cmnewplayerdailygift_xzmp`;
    MT_Field_PlayerInfo = "NewPlayerDailyGiftInfo";

    async async_query(): Promise<Object>;
    async async_save(): Promise<boolean>;
    async async_safeSave(data: Object): Promise<void>;
}
```

### RedisTool_NewPlayerDailyGiftInfo

```typescript
class RedisTool_NewPlayerDailyGiftInfo {
    MAX_REDIS_EXPIRE = 86400 * 7;  // 缓存7天

    get key(): string;
    get lockKey(): string;

    async async_getData(): Promise<UserData_NewPlayerDailyGiftInfo>;
    async async_setData(data: UserData_NewPlayerDailyGiftInfo): Promise<number>;
}
```

## 常量定义

```typescript
const CONST_VAR = {
    MODULE_NAME: 'cmnewplayerdailygift',
    GAME_CODE: 'xzmp',
    APP_CODE: 'xzmp',
    GAME_ID: 283,
    DAY_SECONDS: 86400,
}

const REQ_NAME = {
    // From Client
    QUERY_CONFIG: 'queryNewPlayerDailyGiftConfig',
    CLAIM_DAILY_REWARD: 'claimDailyReward',

    // to Client (推送)
    ON_PURCHASED: 'onNewPlayerDailyGiftPurchased',
}
```

## 待确认事项

1. **exchangeid 配置**：需要后续补充具体的兑换商品ID
2. **是否支持多个迎新礼包**：同一玩家能否购买多个不同档位的迎新礼包？
3. **数据清理策略**：过期数据是否需要定时清理？

---

*文档版本: v1.0*
*创建日期: 2026/04/21*
