# L1 ChunkSvr — 礼包数据服务中心

> 金币版（xzmo/xzms）核心数据后端。管理所有 Lua 活动模块的配置获取、数据库更新和发奖，其他所有金币版服务（房间服、游戏服、assistSvr）均依赖该模块。

---

## 架构定位

```
assistSvr (Lua客户端接入层)
    │
    ├─ 请求转发 ──→ chunkSvr (数据处理/发奖/配置)
    │                      │
    │                      ├─→ MySQL (chunkdb / chunk283db)
    │                      ├─→ Redis
    │                      └─→ LuaScripts (活动配置热更新)
    │
    ├─ gameSvr (游戏逻辑服)
    └─ roomSvr (房间管理服)
```

| 属性 | 值 |
|------|-----|
| 源码 | `branches/douque/jinbi/gamechunksvr/` |
| 部署 | `D:\game\xzmo\server_chunk\` |
| 监听端口 | `60465` (ini 可配) |
| 数据库 | chunkdb (主库)、chunk283db (游戏扩展库) |
| 缓存 | Redis (192.168.1.209:10064) |
| 服务名 | `TCY {GAME_CLIENT}ChunkSvr Service` |
| 启动方式 | Windows 服务，由 `CAssitService` 框架管理 |

---

## 模块一览

| 模块 | 文件 | 说明 |
|------|------|------|
| **MainServer** | `MainServer.h/.cpp` | 核心网络服务，继承 `TcySockSvr`，管理连接/DB/消息分发 |
| **CPredefine** | `Predefine.h/.cpp` | 全局预定义：端口、服务名、产品信息、ini 读写 |
| **TaskModule** | `TaskModule.h/.cpp` (59K) | 任务系统 — 每日任务/成就，含数据库定时刷新 |
| **NewTaskModule** | `NewTaskModule.h/.cpp` (43K) | 新版任务系统 |
| **WxTaskModule** | `WxTaskModule.h/.cpp` (28K) | 微信相关任务 |
| **CheckinModule** | `CheckinModule.h/.cpp` (53K) | 签到模块 |
| **DoubleEggModule** | `DoubleEggModule.h/.cpp` (52K) | 砸金蛋活动 |
| **TreasureModule** | `TreasureModule.h/.cpp` (27K) | 寻宝活动 |
| **MonthCard** | `MonthCard.h/.cpp` (15K) | 月卡 |
| **MonthWeekModule** | `MonthWeekModule.h/.cpp` (9K) | 月周卡 |
| **NewFirstChargeModule** | `NewFirstChargeModule.h/.cpp` (25K) | 首充活动 |
| **DailyRecharge** | `DailyRecharge.h/.cpp` (35K) | 每日充值 |
| **TimeLimitChargeModule** | `TimeLimitChargeModule.h/.cpp` (25K) | 限时充值活动 |
| **BrokeChargeModule** | `BrokeChargeModule.h/.cpp` (13K) | 破产充值 |
| **PropsSystemModule** | `PropsSystemModule.h/.cpp` (49K) | 道具系统 — 道具发放/扣减管理 |
| **NoviceLotteryModule** | `NoviceLotteryModule.h/.cpp` (43K) | 新手抽奖 |
| **SafeBoxFirstCheckinModule** | `SafeBoxFirstCheckinModule.h/.cpp` (9K) | 保险箱首次签到 |
| **ReliefModule** | `ReliefModule.h/.cpp` (7K) | 救济金 |
| **PlayerInfoModule** | `PlayerInfoModule.h/.cpp` (5K) | 玩家基本信息查询 |
| **PlayerLogon** | `PlayerLogon.h/.cpp` (3K) | 玩家登录处理 |
| **ConfigManagerModule** | `ConfigManagerModule.h/.cpp` (4K) | 配置管理 — 服务端参数热更新 |
| **RechargeDataModule** | `RechargeDataModule.h/.cpp` (7K) | 充值数据记录与查询 |
| **ResultRestore** | `ResultRestore.h/.cpp` (23K) | 结算恢复 — 断线重连后恢复玩家数据 |
| **RobotPlayerData** | `RobotPlayerData.h/.cpp` (9K) | 机器人玩家数据 |
| **BroadToMobile** | `BroadToMobile.h/.cpp` (1K) | 移动端广播通知 |
| **JsonConfigModule** | `JsonConfigModule.h/.cpp` (3K) | JSON 配置加载 |
| **GameDBConnectPool** | `GameDBConnectPool.h/.cpp` (4K) | 旧版 DB 连接池(8连接) |
| **MyGameDbPoolV3** | `MyGameDbPoolV3.h/.cpp` (8K) | 新版 DB 连接池(12连接) |
| **TcyMsg2LuaScripts** | `luascripts/TcyMsg2LuaScripts.h/.cpp` (19K) | Lua 脚本消息转发引擎 |
| **lexport_funcs** | `luascripts/lexport_funcs.h/.cpp` (31K) | Lua 导出函数 — C++ 注册给 Lua 调用的接口 |
| **pbc-lua** | `luascripts/pbc-lua.h/.cpp` (27K) | protobuf Lua 绑定 |
| **SimpleSubClient** | `SimpleSubClient.h/.cpp` (9K) | 简单子客户端通信 |
| **ChunkLogSockClient** | `ChunkLogSockClient.h/.cpp` (1K) | 日志 socket 客户端 |
| **HttpServerModule** | `HttpServerModule.h/.cpp` (3K) | HTTP 服务模块 |
| **TQDataCenterApi** | `TQDataCenterApi.h/.cpp` (3K) | 数据中心 API |
| **FileSystemWatcher** | `FileSystemWatcher.h/.cpp` (3K) | 文件系统监控(配置热加载) |
| **TestNode / NodeCenter** | `TestNode.h/.cpp`, `../common/nodeservice/` | 节点服务注册与发现 |

---

## 通信架构

### 外部连接

| 连接对象 | 方式 | 说明 |
|----------|------|------|
| gameSvr | TCP (TcySockSvr) | 接收游戏服请求：金币查询、结算推送、道具发放 |
| assistSvr | TCP (TcySockSvr) | 接收 Lua 客户端→assistSvr 转发的数据请求 |
| roomSvr | TCP (TcySockSvr) | 房间配置同步 |
| OnlineServer | TCP 客户端 (61420) | 在线服务器状态同步 |
| TrankGame | TCP 客户端 (30691) | 跨服跳转 |

### Lua 脚本通信

`TcyMsg2LuaScripts` 负责将 C++ 层的消息派发给 Lua 脚本处理，`lexport_funcs` 导出 C++ 接口供 Lua 调用（DB 操作、配置读取、发奖等）。

Lua 脚本位于 `luascripts/` 目录，部署后同步到 `server_chunk/scripts/`，支持热更新。

### 数据库

| 库名 | 用途 |
|------|------|
| chunkdb | 主库：玩家签到、任务、充值、月卡等核心业务数据 |
| chunk283db | 扩展库：道具、活动、抽奖等扩展数据 |

---

## 关键业务流程

### 启动流程
```
Main → CAssitService::OnInit()
  → MainServer::Initialize()
    → ReadChunkDBConfig()        // 读取 DB 配置
    → InitChunkDB()              // 初始化 DB 连接池
    → initComponent()            // 注册所有模块
    → Lua 脚本引擎初始化
    → NodeCenter 注册
    → 开始监听端口
```

### 消息处理
```
TCP 接收请求 → MainServer 校验客户端
  → 分发到对应模块处理 (TaskModule / CheckinModule / ...)
    → 模块处理业务逻辑（可调用 DB / Lua / Redis）
      → 通过 MainServer 回复结果
```

---

## Lua 活动配置脚本

部署目录 `server_chunk/scripts/` 包含大量活动配置 Lua 脚本（50+），覆盖：

| 类别 | 脚本 |
|------|------|
| 充值 | `TQBrokeRechargeNewConfig.lua`, `QuickRechargeV2Config.lua`, `TQLuckyDiscountGiftConfig.lua` |
| 签到 | `TQCheckinConfig.lua`, `ShakeGiftConfig.lua` |
| 抽奖 | `TQLuckyTurntableConfig.lua` |
| 任务 | `TQMatchConfig.lua` (V1/V2/V3) |
| 月卡 | `TQMonthCardConfig.lua` |
| 新人 | `NewPlayerConfig.lua`, `NewPlayerAward.lua` |
| 装饰 | `TQDecorationsConfig.lua` |
| 引导 | `TQGuideConfig.lua` |

---

## 依赖关系

> assistSvr → chunkSvr：assistSvr 将 Lua 客户端请求转发给 chunkSvr 处理。
> gameSvr → chunkSvr：gameSvr 依赖 chunkSvr 完成金币操作、道具发放和结算恢复。
> roomSvr → chunkSvr：roomSvr 从 chunkSvr 同步房间配置。
