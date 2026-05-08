# cmquickrecharge 模块详情

## 基本信息

| 属性 | 值 |
|------|-----|
| 模块名 | cmquickrecharge |
| 脚本文件 | cmquickrecharge_xzmp.ts |
| 配置文件 | cmquickrecharge_xzmp.jsonc |
| GAME_CODE | xzmp |
| GAME_ID | 283 |

## 功能概述

当玩家金币不足时（点击房间入口或本局游戏结束时），弹出补足金币界面，展示两种可购买礼包。每个礼包携带一个特惠礼包，仅当玩家在指定天数内充值金额达到阈值时激活。特惠礼包一经激活永久有效，但每个组合仅能购买一次。若玩家特权等级高于 `levelNotShow`，客户端不展示该礼包。

## 主要函数

### 客户端请求处理

| 消息名 | 说明 | 请求参数 | 响应数据 |
|--------|------|----------|----------|
| queryCMQuickRechargeConfig | 查询补足金币配置及玩家状态 | 无 | `{ cfg, playerInfo }` |
| buySpecialGift | 购买特惠礼包校验（仅校验，不执行购买） | `{ gametype, roomlevel, giftlevel }` | `{ result }` |
| markSpecialGiftPurchased | 标记特惠礼包已购买（客户端支付成功后调用） | `{ gametype, roomlevel, giftlevel }` | `{ result, key, status }` |

### 服务端推送消息

| 消息名 | 说明 | 推送数据 |
|--------|------|----------|
| playerInfoChange_cmquickrecharge_xzmp | 玩家补足金币信息变化通知 | `{ playerInfo }` |

### 内部模块调用

| 消息名 | 说明 | 方向 |
|--------|------|------|
| forceUpdateLevelConfig | 等级配置变更，强制更新等级配置缓存 | From Module (leveldefine) |
| updateRedisPlayerLevelInfo | 更新玩家等级信息到 Redis | To Module (leveldefine) |
| updateMysqlPlayerLevelInfo | 更新玩家等级信息到 MySQL | To Module (leveldefine) |

### 其他回调

| 回调 | 说明 |
|------|------|
| OnScriptReload | 加载配置并执行缺省填充（渠道→玩法层级填充） |
| OnPayResult | 更新充值流水，检查特惠激活条件，推送状态变化 |

## 数据结构

### GameConfig（配置）

```typescript
interface GameConfig {
    isenable: number;
    guid: string;
    RMB2TongbaoRatio: number;
    payconfig: PayConfig;
}

interface PayConfig {
    default: GameTypeConfig;
    gametype4?: GameTypeConfig;  // 血流六红中
    gametype5?: GameTypeConfig;  // 血流成河
    gametype6?: GameTypeConfig;  // 血战到底
}

interface GameTypeConfig {
    roomlevel1: RoomLevelConfig;
    roomlevel3: RoomLevelConfig;
    roomlevel4: RoomLevelConfig;
    roomlevel5: RoomLevelConfig;
}

interface RoomLevelConfig {
    levelNotShow: number;
    default: GiftLevelConfigs;
    wxan?: GiftLevelConfigs;
    wxios?: GiftLevelConfigs;
    tcyan?: GiftLevelConfigs;
    tcyios?: GiftLevelConfigs;
    mergean?: GiftLevelConfigs;
}

interface GiftLevelConfigs {
    giftlevel1: GiftConfig;
    giftlevel2: GiftConfig;
}

interface GiftConfig {
    price: number;
    propID: number;
    propcount: number;
    exchangeid: number;
    specialoffer: SpecialOffer;
}

interface SpecialOffer {
    price: number;
    propcount: number;
    exchangeid: number;
    chargedays: number;
    charge: number;
}
```

### QuickRechargeInfo（玩家数据）

```typescript
class QuickRechargeInfo {
    specialGiftStatus: { [key: number]: number };  // 特惠礼包状态
    payFlow: PayFlowItem[];                        // 充值流水（滑动窗口，保留90天）

    constructor() {
        this.specialGiftStatus = {};
        this.payFlow = [];
    }
}

class PayFlowItem {
    time: number;       // 时间戳（秒）
    amount: number;     // 充值金额（RMB分）
}
```

### 客户端响应结构

```typescript
class cp2Client_QueryConfig {
    cfg: GameConfig;
    playerInfo: {
        specialGiftStatus: { [key: number]: number };
    };
}

class cp2Client_BuySpecialGift {
    result: number;    // 0:可以购买, <0:错误码
}

class cp2Client_MarkPurchased {
    result: number;    // 0:成功, -1:失败
    key: number;       // 特惠礼包编码 key
    status: number;    // 更新后的状态
}
```

## 依赖模块

- **leveldefine** — 读取等级配置、跨模块读写玩家等级信息

## 消息号列表

| 常量名 | 值 | 方向 |
|--------|-----|------|
| QUERY_CONFIG | queryCMQuickRechargeConfig | From Client |
| BUY_SPECIAL_GIFT | buySpecialGift | From Client |
| MARK_PURCHASED | markSpecialGiftPurchased | From Client |
| PLAYER_INFO_CHANGE | playerInfoChange_cmquickrecharge_xzmp | To Client |
| UPDATE_REDIS_PLAYERLEVELINFO | updateRedisPlayerLevelInfo | To Module (leveldefine) |
| UPDATE_MYSQL_PLAYERLEVELINFO | updateMysqlPlayerLevelInfo | To Module (leveldefine) |
| FORCE_UPDATE_LEVEL_CONFIG | forceUpdateLevelConfig | From Module (leveldefine) |

## 特惠礼包 Key 编码

编码公式：`key = gametype * 100 + roomlevel * 10 + giftlevel`

| 状态值 | 常量 | 说明 |
|--------|------|------|
| 0 | NOT_PURCHASED | 未购买（未激活） |
| 1 | CAN_PURCHASE | 可购买（已激活） |
| 2 | PURCHASED | 已购买 |

## 存储结构

| 存储 | 标识 |
|------|------|
| MySQL 表 | `tblcpuserdata_cmquickrecharge_xzmp`，name 字段: "QuickRechargeInfo" |
| Redis Key | `mod(cp):name(cmquickrecharge):appcode(xzmp):uid({uid}):QuickRechargeInfo`，过期: 7天 |

## 核心流程

### 充值回调 (OnPayResult)

1. 检查配置是否启用
2. 更新玩家充值流水（金额单位：RMB分，滑动窗口保留90天）
3. 遍历所有玩法、房间等级、礼包等级组合
4. 获取渠道配置（优先渠道配置，无则用 default）
5. 检查是否满足特惠激活条件（`chargedays` 天内充值 >= `charge` 元）
6. 满足条件则激活对应 key 的特惠礼包
7. 推送玩家状态变化给客户端

### 购买特惠礼包流程

1. 客户端请求 `buySpecialGift` → CP 校验（仅校验，不更新状态）
2. 校验通过 → 客户端发起支付
3. 支付成功 → 客户端调用 `markSpecialGiftPurchased`
4. CP 更新购买状态为 PURCHASED
5. CP 推送玩家状态变化给客户端

### 配置缺省填充 (OnScriptReload)

1. **内层填充**：对每个玩法，用房间等级下的 `default` 渠道配置填充缺省的渠道配置（wxan/wxios/tcyan/tcyios/mergean）
2. **外层填充**：用 `default` 玩法配置填充缺省的 `gametype4/5/6`

判断为空的条件：对象不存在、无任何属性、或所有属性值都是空对象。

## 错误码

| 错误码 | 说明 |
|--------|------|
| 0 | 可以购买 |
| -1 | 模块未启用 |
| -2 | 礼包已购买 |
| -3 | 礼包未激活 |