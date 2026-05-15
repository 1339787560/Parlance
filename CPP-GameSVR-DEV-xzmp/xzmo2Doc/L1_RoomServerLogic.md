# L1 房间服运行逻辑 — xzmo2 (银子血流血战)

> 源码路径：`D:\Codlib\douque\jinbi\roomsvrxzmo\` | 基类路径：`D:\LibraryVC12_P\`

---

## 1. 房间服代码架构

### 1.1 进程模型

roomsvrxzmo 以 Windows NT 服务运行，入口为 `CMainService`（[Service.h](d:\Codlib\douque\jinbi\roomsvrxzmo\Service.h#L3-L25)）：

```
CMainService (NT Service wrapper)
  └── CRobotMainServer m_MainServer  // 主服务器对象
```

服务生命周期：
- `OnInit()` → 启动 `m_MainServer`
- `Run()` → 消息循环
- `OnStop()` → 关闭 `m_MainServer`

### 1.2 类继承链

**服务器类链**（处理消息、逻辑）：

```
CBaseSockServer                          // 网络层
  └── CSockOpenServer                    // 开放房间专用请求处理
        └── CSockServer (jinbi)          // 注册管理命令、日志回调
```

```
CMainBaseServer                          // 核心服务器逻辑
  └── CMainOpenServer                    // 开放房间：玩家进出、开局、换桌
        └── CRobotMainServer (jinbi)     // 机器人管理、RangeAlloc 定时器
```

**房间数据类链**（存储状态）：

```
CBaseRoomData                            // 基础：玩家/桌子映射、座位分配
  └── CRoomOpenData                      // 开放房间：开局、移动桌子、机器人接口
        └── CRobotRoomData (jinbi)       // 机器人管理、RangeAlloc 集成、配置
              └── CRoomData (jinbi)      // 空壳，仅继承
```

**关键引用关系**：
- `CRobotMainServer` 持有 `CRobotRoomData*` 指针
- `CRobotRoomData` 内含 `CRangeAlloc m_RangeAlloc` 成员
- `CRobotRoomData` 在 `m_mapTable` 中管理 `TABLE` 结构体

### 1.3 消息处理路径

客户端请求 → 网络层 → `OnRequest` 分流（[SockOpenServer.cpp:24-78](d:\LibraryVC12_P\RoomOpen\trunk\SockOpenServer.cpp#L24-L78)）：

```
CSockOpenServer::OnRequest()
  ├── MR_XZ_RESUME              → OnXzResume()           // 断线重连
  ├── MR_GET_ROOM_INFO          → OnGetRoomInfo()         // 获取房间信息
  ├── MR_GET_SEATED_AND_START   → OnGetSeatedAndStart()   // 入座并开局
  ├── MR_GET_NEWTABLE_EX        → OnGetNewTableEx()       // 换桌
  └── default                   → CBaseSockServer::OnRequest()
```

**重要**：`MR_GET_SEATED_AND_START` 是玩家进入房间的主要入口。

Windows 消息路径（跨进程通信，`PostMessage`）：

```
CMainBaseServer::OnWndProc()
  ├── WM_GTR_ASKNEWTABLE       → OnAskNewTable()     // 玩家凑齐4人点开始
  ├── WM_GTR_CLOSESOLOTABLE    → OnCloseSoloTable()  // 游戏服通知结算完成
  ├── WM_GTR_GAMEBOUTEND       → OnGameBoutEnd()     // 牌局结束
  ├── WM_GTR_USERBOUTEND       → OnUserBoutEnd()     // 单玩家结束
  └── WM_GTR_STARTINWAIT       → OnWndMsgStartInWait() // 等待中开始
```

参考：[Server.cpp:1271-1298](d:\LibraryVC12_P\RoomBasic\trunk\Server.cpp#L1271-L1298)（`OnWndProc` 消息分发）

### 1.4 线程模型

初始化时创建的线程（[MainServer.cpp:109-115](d:\Codlib\douque\jinbi\roomsvrxzmo\MainServer.cpp#L109-L115)）：

| 线程 | 用途 |
|------|------|
| `CreateTimerThread` | 定时器 |
| `CreatePulseThread` | 心跳 |
| `CreateMessageThread` | 消息处理 |
| `CreateStatThread` | 统计 |
| `CreateServerPulseThread` | 服务器心跳 |
| `CreateDelayThread` | 延迟任务 |
| `CreateRobotThread` | 机器人（配置启用时） |

此外，`CRobotMainServer::Initialize` 创建了 `evp().loopTimer` 每 100ms 调用 `CheckRangeAlloc()`（[RobotMainServer.cpp:48-50](d:\Codlib\douque\jinbi\roomsvrxzmo\RobotMainServer.cpp#L48-L50)）。

---

## 2. 房间服可控配置及效果

### 2.1 INI 配置文件

主配置文件：[roomsvrxzmo.ini](d:\Codlib\douque\jinbi\roomsvrxzmo\roomsvrxzmo.ini)

#### `[listen]` — 监听配置

| 键 | 示例值 | 说明 |
|----|--------|------|
| `port` | `30629` | 房间服监听端口 |
| `clientid` | `283041` | 客户端ID，用于标识服类型 |

#### `[Robot]` — 机器人配置

| 键 | 示例值 | 说明 |
|----|--------|------|
| `RecoveBoutNum_Room<ID>` | `1` | 指定房间机器人累积多少局后回收 |
| `RecoveHowLong_Room<ID>` | `600` | 指定房间机器人空转超时(秒)后回收 |

#### `[server]` — 服务器标识

| 键 | 说明 |
|----|------|
| `startup_time` | 启动时间（自动写入） |

#### `[PlayerNum]` — 人数上报

| 键 | 默认值 | 说明 |
|----|--------|------|
| `FreshRule` | 30秒 | 向 chunk 服上报房间人数的间隔 |

#### `[PrivateRoom]` — 私人房配置

| 键 | 说明 |
|----|------|
| `ModeType` | 模式类型 |
| `ModeMoneyDiff` | 金币差异限制 |
| `ModeWinsDiff` | 胜场差异限制 |

#### `[fixtable]` — 固定桌子

格式为 `{tableNO}=1`，启用固定的桌子号列表。不同的桌子可以被指定为固定桌（用于特定功能或测试）。

#### `[PreTables]` — 预分配表数

格式 `{roomID}={count}`，指定每个房间的预分配表数量（默认4）。

#### `[RandomDen]` — 随机匹配分母

格式 `{roomID}={denominator}`，控制"多桌优先" vs "少桌优先"的概率。`1/nRandomDen` 概率走多桌优先。

参考：[RobotRoomData.cpp:237-238](d:\Codlib\douque\jinbi\roomsvrxzmo\RobotRoomData.cpp#L237-L238)

#### `[TableDeposit<RoomID>]` — 按银子分段分桌

配置格式：
```
Count=N
0={beginChair}|{endChair}|{minDeposit}
1={beginChair}|{endChair}|{minDeposit}
...
```

每个区间定义了一个桌子范围及其对应的最低存款要求。参考 [roomsvrxzmo.ini:50-75](d:\Codlib\douque\jinbi\roomsvrxzmo\roomsvrxzmo.ini#L50-L75)。

#### `[opentime<RoomID>]` — 限时开放

| 键 | 说明 |
|----|------|
| `begindate`/`enddate` | 开放日期范围 |
| `begin0`/`end0` | 每日开放时间段 |

#### `[RoomCard]` — 房卡

| 键 | 说明 |
|----|------|
| `Enable` | 是否启用房卡 |

#### `[OnlineServer]` — 在线服

| 键 | 说明 |
|----|------|
| `Name`/`Name1`/`Name2` | 在线服地址 |
| `Port` | 在线服端口 |

#### `[kickoff]` — 踢出配置

| 键 | 说明 |
|----|------|
| `mode` | 踢出模式 |
| `elapse` | 检测间隔(秒) |
| `timing` | 超时时间(秒) |
| `deadtime` | 死亡时间(秒) |
| `static` | 是否静态检测 |

### 2.2 动态配置（config center）

`CRobotMainServer::InitRoomConfig()` 启动时从 config center 拉取 `TQRoomConfig`（[RobotMainServer.cpp:59-76](d:\Codlib\douque\jinbi\roomsvrxzmo\RobotMainServer.cpp#L59-L76)）。

配置变更时通过 `RoomNodeClient::OnConfigCenterNotify` 热更新（[RoomNodeClient.cpp:116-149](d:\Codlib\douque\jinbi\roomsvrxzmo\RoomNodeClient.cpp#L116-L149)），通过 `CRobotRoomData::SetRoomConfig` 应用到对应房间。

`RoomConfigItem` 至少包含 `roomid`、`high`(最高存款)、`low`(最低存款)（[RobotRoomData.cpp:741-753](d:\Codlib\douque\jinbi\roomsvrxzmo\RobotRoomData.cpp#L741-L753)）。

### 2.3 机器人配置

[robotConfig.ini](d:\Codlib\douque\jinbi\roomsvrxzmo\robotConfig.ini)：

| 段 | 说明 |
|----|------|
| `[enable]` | 房间ID=1 启用机器人 |
| `[robotMap]` | 机器人ID→名称映射 |

### 2.4 RangeAlloc 配置

`RangeAllocConfig.ini`（与 roomsvrxzmo.exe 同目录），段名 `Range_{roomID}`：

| 键 | 默认值 | 说明 |
|----|--------|------|
| `Enable` | `FALSE` | 是否启用 RangeAlloc 匹配模式 |
| `MaxRange` | `0` | 最大匹配范围段数，0=禁用 |
| `Interval` | `1000` | 匹配检查间隔(毫秒) |
| `UppRange` | `3000` | 向上扩展等待时间(毫秒) |
| `LowRange` | `4000` | 向下扩展等待时间(毫秒) |
| `AllRange` | `8000` | 全范围扩展等待时间(毫秒) |
| `Robot_1` | `5000` | 第一阶段允许机器人阈值(毫秒) |
| `Robot_2` | `7000` | 第二阶段阈值 |
| `Robot_3` | `10000` | 第三阶段阈值 |
| `MaxFullRobotTable` | `0` | 最大全机器人桌子数 |
| `FixMatch` | `0` | 固定人数匹配模式(>0时启用) |
| `Range_N` | `{amount}` | 第N段匹配的金额门槛 |

参考：[RangeAlloc.hpp:130-135](d:\Codlib\douque\jinbi\roomsvrxzmo\RangeAlloc\RangeAlloc.hpp#L130-L135)

---

## 3. 匹配逻辑细节

### 3.1 匹配流程总览

从玩家进入房间到开局的总过程：

```
玩家进入房间
  → Hall → roomsvr 验证
  → CBaseSockServer::OnRequest(MR_GET_SEATED_AND_START)
    → 检查是否可以入座
    → GetRandomPosition()         ← 选择桌子和椅子
    → SetRandomPosition()         ← 入座（nPlayerCount++）
    → 等待其他玩家凑齐
    → ...（玩家符合条件后进入 waiting 状态）
    → OnAskNewTable()             ← 凑齐4人，点击"开始"
      → IsFullTable()?          ← 检查是否满4人
      → YES: SendRandomPlaying() → CommitTPS() → PostStartSoloTable()
```

### 3.2 从入座到等待

玩家进入房间后，消息通过 `MR_GET_SEATED_AND_START` 处理（[SockOpenServer.cpp:48](d:\LibraryVC12_P\RoomOpen\trunk\SockOpenServer.cpp#L48)）。

核心流程在 `OnUserEnterGameOK`（[MainOpenServer.cpp:460-534](d:\LibraryVC12_P\RoomOpen\trunk\MainOpenServer.cpp#L460-L534)）：

```cpp
// 1. 验证状态
if(!lpRoomData->IsNeedRoomCard() && pPlayer->nStatus != PLAYER_STATUS_SEATED)
    return FALSE;

// 2. 设置等待状态
pPlayer->nStatus = PLAYER_STATUS_WAITING;

// 3. 随机房间 → 重排
if(lpRoomData->IsRandomRoom() && pPlayer->nTableNO < g_nTeamTableBegin)
{
    SetRandomTableLeave(lpRoomData, pPlayer);  // 离开旧随机位
    lpRoomData->GetRandomPosition(pPlayer, &PP);  // 选新桌
    lpRoomData->SetRandomPosition(pPlayer, pTable, &PP);  // 入座
    
    if(lpRoomData->IsFullTable(pTable))  // 满4人立即开局
    {
        SendRandomPlaying(...);
        CommitTPS(PS_PLAYING);
        PostStartSoloTable(...);
    }
}
```

### 3.3 选桌策略：GetRandomPosition

`CRobotRoomData::GetRandomPosition()` 实现了完整的选桌逻辑（[RobotRoomData.cpp:96-254](d:\Codlib\douque\jinbi\roomsvrxzmo\RobotRoomData.cpp#L96-L254)）：

**步骤 1**：读取配置（RANDOM_CONFIG）

```cpp
RANDOM_CONFIG rc;
BOOL bRangeConfig = ReadRangeRandomConfig(this, &rc);
if (!bRangeConfig)
    rc.nFixTable = GetPrivateProfileInt("FixTable", roomStr, 0, ini);
if (!bRangeConfig)
    rc.nMaxPreTables = GetPrivateProfileInt("PreTables", roomStr, 4, ini);
if (!bRangeConfig)
    rc.nMinRandomPlayer = GetPrivateProfileInt("MinRandomPlayer", roomStr, 1, ini);
```

**步骤 2**：机器人走 `RangeAlloc.ForbidRange`，真人走完整禁止检查（[RobotRoomData.cpp:163-202](d:\Codlib\douque\jinbi\roomsvrxzmo\RobotRoomData.cpp#L163-L202)）

真人玩家触发的禁止检查（按顺序）：

| 检查 | 函数 | 说明 |
|------|------|------|
| RangeAlloc 禁止 | `ForbidRange` | 按银子范围匹配 |
| 同俱乐部禁止 | `ForbidSameClub` | 联赛房间禁用同俱乐部 |
| 同IP禁止 | `ForbidSameIP` | 禁止同IP坐一桌 |
| 同局域网禁止 | `ForbidSameLAN` | 禁止同局域网 |
| 同密码禁止 | `ForbidSamePwd` | 禁止同机器码 |
| IP互斥 | `ForbidMutexIP` | IP冲突禁止 |
| IP组互斥 | `ForbidMutexIPGroup` | IP组冲突禁止 |
| 微经验禁止 | `ForbidMicroExperience` | 游戏时间过短 |
| 小经验禁止 | `ForbidSmallExperience` | 游戏时间较短 |
| 硬件互斥 | `ForbidMutexHard` | 禁止同硬件ID |
| 卷ID互斥 | `ForbidVolumeID` | 禁止同卷ID |
| 同时段禁止 | `ForbidSameTime` | 同IP同时段 |

**步骤 3**：如果所有有效桌都被禁止，降级到可用桌的最后一张

**步骤 4**：随机选择——`1/nRandomDen` 概率走"加入最多人桌"，否则走"加入最少人桌"

```cpp
int nMode = xyGetRandomDigit(rc.nRandomDen - 1);
if (nMode == 0 || bFixTable)  // 1/n 概率
    JoinMax(nPreTables, pp, nFromTableNO);  // 加入最多人桌
else
    if (!JoinMin(nPreTables, pp, nMaxPreTables2, nFromTableNO))
        JoinMax(nPreTables, pp, nFromTableNO);  // 回退
```

- `JoinMax`：尽量把玩家放进已有最多人的桌，加速凑齐
- `JoinMin`：尽量把玩家放进最少人的桌，平衡分布

### 3.4 开局流程

玩家凑齐 4 人后，客户端发消息触发 `OnAskNewTable`（[MainOpenServer.cpp:60-155](d:\LibraryVC12_P\RoomOpen\trunk\MainOpenServer.cpp#L60-L155)）：

简化流程：

```cpp
BOOL CMainOpenServer::OnAskNewTable(DWORD dwRoomTableChair, int nUserID)
{
    // 1. 校验玩家状态
    // 2. 获取座位（GetRandomPosition）
    // 3. 入座（SetRandomPosition）
    
    // 4. 检查是否满4人
    if (lpRoomData->IsFullTable(pTable))
    {
        TABLE* pNewTable = NULL;
        lpRoomData->SendRandomPlaying(pTable, &PP, pNewTable);  // 移动表
        OverSeeUserData(nUserID, "OnAskNewTable::CommitTPS");
        lpRoomData->CommitTPS(pNewTable, PS_PLAYING);            // 状态→PLAYING
        LOG_INFO("TableNo %d Start Solo", PP.nTableNO);
        lpRoomData->PostStartSoloTable(pNewTable);              // 通知gamesvr
    }
}
```

### 3.5 RangeAlloc 匹配（银子版核心）

`CRangeAlloc` 是银子版 roomsvrxzmo 的**核心匹配模块**（[RangeAlloc.hpp](d:\Codlib\douque\jinbi\roomsvrxzmo\RangeAlloc\RangeAlloc.hpp)）。

**设计目标**：根据玩家的存款（deposit）进行范围匹配，避免千万富翁和低保户同桌。

**触发时机**：`CRobotMainServer::CheckRangeAlloc()` 每 **100ms** 遍历所有房间调用 `CRangeAlloc::Check()`（[RangeAlloc.cpp:5-39](d:\Codlib\douque\jinbi\roomsvrxzmo\RangeAlloc\RangeAlloc.cpp#L5-L39)）。

**每次 Check 的执行流程**：

```
Check(lpRoomData, bForce)
  │
  ├── 1. SetAllRandomTableLeave(lpRoomData, curr, player, robot)
  │     └── 遍历所有等待桌上的玩家，全部离座
  │         真人加入 player 队列，机器人加入 robot 队列
  │         队列按等待时间降序排列，同等待时间按 deposit 降序
  │
  ├── 2. SetQueueRandomPosition(lpRoomData, curr, player)
  │     └── 按等待时间从长到短，遍历 player 队列：
  │           GetRandomPosition → SetRandomPosition → 入座
  │           如果某桌满4人 → 开局
  │
  ├── 3. SetQueueRandomPosition(lpRoomData, curr, robot)
  │     └── 同样的逻辑处理机器人队列
  │
  ├── 4. CallMoreRobot(lpRoomData, curr)
  │     └── 检查是否需要在空桌上加入更多机器人
  │
  └── 5. ClearWaitRobot(lpRoomData, curr)
        └── 清理等待过久的机器人
```

**核心范围匹配逻辑**（`ForbidRange`，[RangeAlloc.hpp:490-558](d:\Codlib\douque\jinbi\roomsvrxzmo\RangeAlloc\RangeAlloc.hpp#L490-L558)）：

```
每个玩家有 base_range（基于 deposit 计算）
每个桌子有 range_begin / range_end（基于首座玩家）
如果两个范围不重叠 → 禁止该桌
```

`GetBaseRange(deposit)`（[RangeAlloc.hpp:450-462](d:\Codlib\douque\jinbi\roomsvrxzmo\RangeAlloc\RangeAlloc.hpp#L450-L462)）通过 `Range_N` 配置确定玩家的范围段：

```
deposit < Range_1 → base_range = 1
deposit < Range_2 → base_range = 2
deposit < Range_3 → base_range = 3
...
```

`GetRange(wait_time, base_range)`（[RangeAlloc.hpp:464-488](d:\Codlib\douque\jinbi\roomsvrxzmo\RangeAlloc\RangeAlloc.hpp#L464-L488)）根据等待时间动态扩展范围：

```
wait_time >= UppRange(3000ms) → range_end + 1    // 向上扩展
wait_time >= LowRange(4000ms) → range_begin - 1   // 向下扩展
wait_time >= AllRange(8000ms) → 全范围            // 所有桌均可
```

**新玩家特殊处理**：新玩家（配置 `new_player` 段的 `userid` 和 `bout` 限制）只能匹配到其他新玩家的桌，防止高手虐新手（[RangeAlloc.hpp:166-200](d:\Codlib\douque\jinbi\roomsvrxzmo\RangeAlloc\RangeAlloc.hpp#L166-L200)）。

---

## 4. 机器人 vs 真人匹配差异

### 4.1 机器人生命周期

机器人由 `CRobotRoomData` 管理，存储在 `m_mapUIdRobot`（TUIdRobotMap）中。

**机器人来源**：
- 启动时从 config center 加载机器人列表
- 通过 CRobotRoomData::LetRobotsJoin 等接口加入游戏
- 机器人在 WALKAROUND 状态等待被分配

参考 [RobotRoomData.cpp:326-363](d:\Codlib\douque\jinbi\roomsvrxzmo\RobotRoomData.cpp#L326-L363)

### 4.2 匹配流程差异

**1. 选桌阶段（GetRandomPosition）差异**：

| 环节 | 真人 | 机器人 |
|------|------|--------|
| RangeAlloc 禁止 | `ForbidRange()` — 按 deposit 范围 | `ForbidRange()` — 同上 |
| 同IP/同LAN/同PWD | **检查全部** | **跳过** |
| 经验检查 | 检查 Micro/Small Experience | **跳过** |
| 硬件互斥 | 检查 MutexHard/VolumeID | **跳过** |
| 同时段禁止 | 检查 SameTime | **跳过** |

参考 [RobotRoomData.cpp:163-202](d:\Codlib\douque\jinbi\roomsvrxzmo\RobotRoomData.cpp#L163-L202)

**2. 机器人召唤时机**（`CallMoreRobot`，[RangeAlloc.hpp:324-368](d:\Codlib\douque\jinbi\roomsvrxzmo\RangeAlloc\RangeAlloc.hpp#L324-L368)）：

```cpp
// 条件：桌未满 + 当前机器人数 < 允许的机器人数 + 机器人 < 真人数量
if (!lpRoomData->IsFullTable(lpTable)
    && robot_count < CanMakeRobotCount(...)
    && robot_count < pTable->th.nPlayerCount)
{
    LetRobotsJoin(..., 1);  // 召唤1个机器人
}
```

机器人数量上限由 `CanMakeRobotCount` 根据等待时间阶梯决定（[RangeAlloc.hpp:217-255](d:\Codlib\douque\jinbi\roomsvrxzmo\RangeAlloc\RangeAlloc.hpp#L217-L255)）：

| 等待时间 | 允许机器人数 |
|----------|-------------|
| < Robot_1 (5s) | 0 |
| < Robot_2 (7s) | 1 |
| < Robot_3 (10s) | 2 |
| ≥ Robot_3 + rand(3s) | 3（满） |

**3. 开局判断差异**：

在 `OnUserEnterGameOKSoloCB`（[RobotMainServer.cpp:142-189](d:\Codlib\douque\jinbi\roomsvrxzmo\RobotMainServer.cpp#L142-L189)）中：

```cpp
// 未启用 RangeAlloc 时
if (!RangeAlloc.Enable()) {
    // 如果只有机器人在桌 → 让机器人离开
    if (IS_BIT_SET(pPlayer->nUserType, USER_TYPE_ROBOT) 
        && GetTruePlayerCount(pTable) == 0)
    {
        PostRobotLeave(pPlayer->nUserID);
        return FALSE;
    }
    if (IsFullTable(pTable))  // 满4人 → 开局
        SendRandomPlaying(...);
}
else {
    if (IsFullTable(pTable))
        CheckRangeAlloc(TRUE);  // 触发RangeAlloc重排
}
```

启用 RangeAlloc 时，机器人和真人统一由 `CheckRangeAlloc` 处理，不再区别对待。

### 4.3 机器人回收

机器人回收机制（超时和局数）：

| 机制 | 函数 | 说明 |
|------|------|------|
| 机器人数上限 | `CheckRobotJoinEnable` | 检查 `m_mapUIdRobot` 中空闲机器人数量 |
| 超时回收 | `CRobotRoomData::KickRobotByTimeout` | 超过指定秒数未开始游戏的机器人被踢 |
| 局数回收 | `RecoveBoutNum_Room<ID>` (INI) | 机器人打满指定局数后回收 |
| 空表全机器人踢出 | `CRobotRoomData::CheckStartTable` | 全机器人桌 → 发送 `PostGameWin` 强制结束 |
| 空转清理 | `ClearWaitRobot` (RangeAlloc) | 等待过久的机器人被叫离座位 |

参考：[RobotRoomData.cpp:290-324](d:\Codlib\douque\jinbi\roomsvrxzmo\RobotRoomData.cpp#L290-L324)

### 4.4 机器人归属

机器人离开时调用 `LetRobotLeave`（[RobotRoomData.cpp:365-373](d:\Codlib\douque\jinbi\roomsvrxzmo\RobotRoomData.cpp#L365-L373)）：

```cpp
std::string CRobotRoomData::LetRobotLeave(int nUserId)
{
    auto ret = __super::LetRobotLeave(nUserId);  // 基类清理
    if (ret.empty()) {
        CRobotInfoManager::ReleaseRobot(nUserId);  // 释放机器人资源
    }
    return ret;
}
```

---

## 5. 房间服与游戏服之间的通信

### 5.1 通信方式

roomsvr 和 gamesvr 是**两个独立进程**，通信方式：

1. **文件共享**：roomsvr 写 `.tmp` 文件到共享目录
2. **PostMessage**：roomsvr 向 gamesvr 窗口发 Windows 消息通知

roomsvr 通过 `GetGameSvrFolder()` 获取 gamesvr 目录路径，写入 `solo/{roomID}_{tableNO}.tmp` 文件。

参考：[RobotRoomData.cpp:623-638](d:\Codlib\douque\jinbi\roomsvrxzmo\RobotRoomData.cpp#L623-L638)

### 5.2 开局流程

```
OnAskNewTable()  → 凑齐4人点开始
    │
    ├── SendRandomPlaying()       // [roomOpenData.cpp:959-1017]
    │   ├── GetFreeTableNO()      // 找空闲STATIC桌
    │   ├── MoveRandomTable()     // 全量拷贝TABLE，原表清零
    │   ├── PostPlayerPosition()  // 通知玩家座次
    │   └── NotifyRoomPlayers(GR_SOLORANDOM_PLAYING) // 通知开始
    │
    ├── CommitTPS(PS_PLAYING)     // 状态提交到持久层
    │
    └── PostStartSoloTable()      // [RobotRoomData.cpp:556-647]
        ├── 构造 START_SOLOTABLE 消息
        │   ├── 生成唯一签名(dwSignLow/dwSignHigh)
        │   └── 填充玩家信息(SOLO_PLAYER数组)
        │
        ├── 写文件: solo/{roomID}_{tableNO}.tmp
        │   └── CreateFile(OPEN_ALWAYS) → WriteFile → CloseHandle
        │
        ├── PostMessage(hGameSvrWnd, WM_RTG_STARTSOLOTABLE, roomID, tableNO)
        │   └── gamesvr 收到后读取 .tmp 文件
        │
        ├── TableStart(tableNO)    // 记录开局时间戳
        │
        └── NotifyServer(PB_GAME_STARTUP)  // 上报数据
```

**关键细节**：`MoveRandomTable`（[roomOpenData.cpp:911-957](d:\LibraryVC12_P\RoomOpen\trunk\roomOpenData.cpp#L911-L957)）：

```cpp
// 1. 遍历 nPlayerAry[0..nPlayerCount-1]，移动玩家到新表
for(int i = 0; i < pTable->th.nPlayerCount; i++) {
    Lookup(pTable->nPlayerAry[i]) → 找到玩家
    SetChairLeave() → 旧桌离座
    更新玩家 nTableNO/nChairNO
}

// 2. memcpy 全量拷贝 TABLE 结构到新表
memcpy(pNewTable, pTable, sizeof(TABLE));
pNewTable->th.nTableNO = nNewTableNO;

// 3. 原表清零
ZeroMemory(pTable, sizeof(TABLE));
pTable->th.nTableNO = nOldTableNO;
```

### 5.3 退出流程（正常结算）

```
GameSvr 麻将打完 → 结算完成
    │
    ├── PostMessage(hRoomSvrWnd, WM_GTR_GAMEBOUTEND, ...)
    │
    ├── OnGameBoutEnd()  // roomsvr 侧
    │
    └── 结算完成 → GameSvr 向 roomsvr 发 WM_GTR_CLOSESOLOTABLE
        │
        └── OnCloseSoloTable(nRoomID, nTableNO)  // [Server.cpp:2515-2603]
            │
            ├── 1. 校验：table 存在且状态为 PLAYING
            │
            ├── 2. 找第一个 PLAYING 状态的玩家
            │
            ├── 3. CommitTPS(PS_WALKAROUND)  // 状态改为散步
            │
            ├── 4. SetTableAsEmptyOrLeave()  // [RoomDef.cpp:596-655]
            │   ├── SetRandomTableLeave()     // 清理随机位
            │   ├── 如果是 PLAYING 状态：
            │   │   ├── 所有玩家 nStatus = WALKAROUND, nTableNO = -1, nChairNO = -1
            │   │   ├── nPlayerCount = 0
            │   │   ├── memset nPlayerAry = 0
            │   │   ├── memset nVisitorAry = 0
            │   │   └── nStatus = TABLE_STATUS_STATIC  ← 桌子可复用
            │   └── 其他状态：SetChairLeave 单玩家离座
            │
            ├── 5. NotifyRoomPlayers(GR_SOLOTABLE_CLOSED)  // 通知玩家
            │
            └── 6. 房卡房间：REMOVE_ONE_PLAYER（非房卡房间跳过）
```

**重要**：银子场 `IsNeedRoomCard()` 返回 FALSE，所以第 6 步的 REMOVE_ONE_PLAYER 被跳过。玩家状态在 `SetTableAsEmptyOrLeave` 中被设为 WALKAROUND 但保留在房间中。

### 5.4 中途退出/强退流程

#### 玩家在等待阶段退出

```
OnUserLeaveGameOK() / OnUserLeaveGameOKVerified()
    │
    ├── SetCommonTableLeave()    // 清理普通座位
    ├── SetRandomTableLeave()    // 清理随机座位
    │                            // 清除 nPlayerAry 条目，nPlayerCount--
    ├── CommitTPS_SOLO(PS_WALKAROUND)  // 散步状态
    ├── NotifyRoomPlayers(GR_PLAYER_LEAVETABLE)
    └── pPlayer->nStatus = WALKAROUND
        nTableNO = -1
        nChairNO = -1
```

参考：[MainOpenServer.cpp:543-653](d:\LibraryVC12_P\RoomOpen\trunk\MainOpenServer.cpp#L543-L653)

#### 玩家断线

断线检测通过 `KickDeadTable` 定时器（3秒间隔）完成，[KickDeadTable.cpp](d:\Codlib\douque\jinbi\roomsvrxzmo\KickDeadTable.cpp)：

```cpp
void KickDeadTable::OnTimerFresh()
{
    // 遍历所有房间的所有 PLAYING 状态桌子
    for (auto it : lpRoomData->m_mapTable)
    {
        TABLE* table = it.second;
        if (table->th.nStatus != TABLE_STATUS_PLAYING)
            continue;
        if (now - table->nStartupTime < timeout)  // 默认3600秒
            continue;
        
        // 踢出断线的 PLAYING 玩家
        for (int i = 0; i < MAX_CHAIR_COUNT; i++)
        {
            KickOffRoomPlayer(&context, lpRoomData, nUserID, FALSE);
        }
    }
}
```

`KickOffRoomPlayer` 内部调用 `RemoveOnePlayer` 彻底从房间中移除玩家，并通知其他组件。

#### 游戏进行中强退（GameSvr 处理）

```
玩家强退 → GameSvr 检测到断线
    → PostMessage(hRoomSvrWnd, WM_GTR_USERBOUTEND, ...)
    
玩家重连 → GameSvr 恢复游戏
    → 继续牌局
```

### 5.5 关键窗口句柄流

```
roomsvr 启动 → FindGameSvrWindow() → 找到 gamesvr 窗口句柄
    │
    └── 开局：PostMessage(hGameSvrWnd, WM_RTG_STARTSOLOTABLE)
    └── 机器人离开：PostMessage(hGameSvrWnd, WM_RTG_ROBOT_LEAVE)
    └── 全机器人桌：PostMessage(hGameSvrWnd, WM_RTG_ROBOT_GAMEWIN)
```

`FindGameSvrWindow`（[roomOpenData.cpp:946-949](d:\LibraryVC12_P\RoomOpen\trunk\roomOpenData.cpp#L946-L949)）：

```cpp
if(IsSoloRoom()) {
    pTable->hGameSvrWnd = FindGameSvrWindow();  // 查找gamesvr窗口
}
```

### 5.6 状态提交流程（CommitTPS）

```cpp
// 提交到持久层（状态机）
lpRoomData->CommitTPS(pNewTable, PS_PLAYING);     // 桌子状态→游戏中
lpRoomData->CommitTPS_SOLO(nUserID, ... , PS_WAITING);    // 玩家状态→等待中
lpRoomData->CommitTPS_SOLO(nUserID, ... , PS_WALKAROUND); // 玩家状态→散步
```

`CommitTPS` 是真正的状态持久化入口，对应业务层的提交操作。参考 [roomdata.h](d:\LibraryVC12_P\RoomBasic\trunk\roomdata.h) 中的声明。

### 5.7 节点通信（NodeClient）

roomsvr 通过 `RoomNodeClient` 与 **chunk 服**（中心节点）通信：

| 方向 | 接口 | 用途 |
|------|------|------|
| roomsvr→chunk | `ReqPlayerEnterRoom` | 玩家进入房间通知 |
| roomsvr→chunk | `ReqPlayerLeaveRoom` | 玩家离开房间通知 |
| roomsvr→chunk | `NotifyPlayerNumToChunk` | 定时上报房间人数 |
| chunk→roomsvr | `OnNewDepositUpdate` | 玩家存款变更通知 |
| chunk→roomsvr | `OnConfigCenterNotify` | 配置变更通知 |
| roomsvr→chunk | `GetUserNewDeposit` | 查询玩家存款 |
| roomsvr→chunk | `GetTQRoomConfig` | 获取房间配置 |

参考：[RoomNodeClient.cpp](d:\Codlib\douque\jinbi\roomsvrxzmo\RoomNodeClient.cpp)

---

## 附录：关键数据结构

### TABLE 结构

```cpp
struct TABLE {
    TABLEHEAD th;        // 状态、人数、桌号
    int nPlayerAry[4];   // 座位上的玩家ID（0=空）
    int dwIPAddrs[4];    // 玩家IP
    DWORD nStartupTime;  // 游戏开始时间
    DWORD nFirstStartTime; // 第一个入座时间
    DWORD nLatestStartTime; // 最近入座时间
    HWND hGameSvrWnd;    // gamesvr窗口句柄
    // ... 更多字段
};
```

### TABLEHEAD 结构

```cpp
struct TABLEHEAD {
    int nTableNO;        // 桌号
    int nStatus;         // TABLE_STATUS_STATIC(0) / TABLE_STATUS_PLAYING(1)
    int nPlayerCount;    // 当前人数（含幽灵条目风险）
    // ... 
};
```

### 关键房间属性判断

| 函数 | 判断依据 | 备注 |
|------|---------|------|
| `IsRandomRoom()` | `roomdata.dwRoomDataEx & 0x01` | 随机匹配房间 |
| `IsSoloRoom()` | `roomdata.dwRoomDataEx & 0x02` | 独立房间（非牌桌） |
| `IsNeedRoomCard()` | `roomdata.dwRoomDataEx & 0x20` | 房卡房间 |
| `IsDarkRoom()` | `roomdata.dwRoomDataEx & 0x04` | 暗房 |
| `IsCloakingRoom()` | `roomdata.dwRoomDataEx & 0x1000` | 隐身房间 |

参考：[roomdata.h](d:\LibraryVC12_P\RoomBasic\trunk\roomdata.h) 中的 Is* 方法。

### 配置读取优先级

复杂的配置读取顺序：

1. `TQRoomConfig`（config center 远程配置）→ 优先
2. `RangeAllocConfig.ini`（独立配置文件）→ 部分覆盖
3. `roomsvrxzmo.ini`（主 INI 文件）→ 回退

`RANDOM_CONFIG` 可用于覆盖 INI 配置（通过 `ReadRangeRandomConfig`）。参考：[RobotRoomData.cpp:118-138](d:\Codlib\douque\jinbi\roomsvrxzmo\RobotRoomData.cpp#L118-L138)
