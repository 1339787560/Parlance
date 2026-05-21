# xzmo2 银子版血流场无法开局 — 根因分析报告

> 日期：2026-05-14 | 调查依据：onlineErrorBrief20260514.md

---

## 问题摘要

银子版血流场高级房（room 15787）玩家无法开局，机器人频繁进出房间，日对局数为零。日志出现 `EnterGame Failed`：Room 侧 table/chair 为 (-1,-1)，gamesvr 侧为 (4,1)。

---

## 架构相关方

| 组件 | 路径 | 角色 |
|------|------|------|
| roomsvrxzmo | `D:\Codlib\douque\xzmx\xzmoNewPC\branches\douque\deposit\roomsvrxzmo\` | 房间服：匹配、机器人调度、RangeAlloc |
| gamesvr | `D:\Codlib\douque\xzmx\xzmoNewPC\branches\douque\deposit\gamesvr\` | 游戏服：实际麻将逻辑 |
| RangeAlloc | `D:\Codlib\douque\jinbi\roomsvrxzmo\RangeAlloc\` | 段位匹配模块（仅 deposit 版） |
| 模板(RoomOpen) | `D:\LibraryVC12_P\RoomOpen\trunk\` | 房间服通用模板 |

---

## 关键调用链

```
Timer(100ms)
  → CMainOpenServer::DelayTimerThreadProc()    [MainOpenServer.cpp:670-732]
    → CRobotRoomData::CheckRangeAlloc()         [RobotRoomData.cpp:1090-1096]
      → CRoomRangeAlloc::Check()                [RoomRangeAlloc.hpp]
        → SetAllRandomTableLeave()              [清空所有 virtual table 玩家到排队状态]
        → SetQueueRandomPosition(player)        [重新分配真人玩家]
        → SetQueueRandomPosition(robot)         [重新分配机器人]
        → CallMoreRobot()                       [需要更多机器人 → LetRobotsJoin]
        → ClearWaitRobot()                      [清理超时未匹配的]

OnAskNewTable (玩家/机器人请求进入匹配队列)
  → CMainOpenServer::OnAskNewTable()            [MainOpenServer.cpp:60-155]
    → SetRandomTableLeave()                     [离开当前桌]
    → EnterProtectMatchQueue()                  [进入保护队列]
      → PutRobotQueque()                        [RoomRobotData.cpp:847-928]
        → m_pRangeAlloc->Add(pPlayer)           [如果 RangeAlloc 启用]
          → CRoomRangeAlloc::Add()              [RoomRangeAlloc.hpp]
            → if IS_BIT_SET(USER_TYPE_ROBOT) return TRUE  ← 关键！
```

---

## 根因：三段式死锁

### 第一段：RangeAlloc::Add() 吞掉机器人

`CRoomRangeAlloc::Add()` 对机器人直接返回 `TRUE`：

```cpp
BOOL CRoomRangeAlloc::Add(LPPLAYER lpPlayer)
{
    // ...
    if (IS_BIT_SET(lpPlayer->nUserType, USER_TYPE_ROBOT)) {
        return TRUE;  // ← 直接消费，不排队，不分配桌子
    }
    // ... 真人玩家加入 queue
}
```

机器人被标记为"已消费"，但**没有分配到具体桌子**，`nTableNO` 保持为之前的值（由 `SetRandomTableLeave` 设为 -1）。

### 第二段：机器人状态陷入 WAITING，无法被 CallMoreRobot 使用

`SetRandomTableLeave()` 将机器人状态设为 `PLAYER_STATUS_WAITING`。随后 `CRoomRangeAlloc::Check()` 的下一阶段 `CallMoreRobot()` 调用 `CheckRobotJoinEnable()`，该函数**只选取状态为 `PLAYER_STATUS_WALKAROUND` 的机器人**：

```cpp
// RobotRoomData.cpp:1059
if (pPlayer->nStatus != PLAYER_STATUS_WALKAROUND)
    continue;  // ← WAITING 状态的机器人被跳过
```

WAITING 机器人不可见 → 不会派发 → 真人填不满桌子 → 无法开局。

### 第三段：OnUserEnterGameOKVerified 检测到 table/chair 不一致

当机器人（仍带 nTableNO=-1 的状态）走完 EnterGame 协议，gamesvr 侧分配到实际桌子（如 table=4, chair=1），但 roomsvr 侧的 `pPlayer->nTableNO` 仍为 -1。`OnUserEnterGameOKVerified()` 检测到不匹配：

```cpp
// MainOpenServer.cpp:769-776
if (pPlayer->nTableNO != nTableNO) {
    // 这里 pPlayer->nTableNO == -1 (room 侧)
    // nTableNO == 4 (gamesvr 侧)
    LogWarning("EnterGame Failed. table,chair is changed ...");
    PostVerifyRoomTableChair();
    return FALSE;
}
```

→ 机器人被踢回 → 回到 WALKING 或 WAITING → 下一次定时器再次触发 → **无限循环**。

---

## 为什么重启能暂时解决

重启 roomsvr 清除所有内存状态。机器人重新上线时 `nStatus = PLAYER_STATUS_WALKAROUND`、`nTableNO = -1`。此时：
- `CallMoreRobot()` 能看到 WALKAROUND 机器人
- `LetRobotsJoin()` 给机器人分配真实桌子
- 游戏能正常开始

但随着机器人经过 `OnAskNewTable` 路径，又一次被 `RangeAlloc::Add()` 吞掉，状态变为 WAITING，死锁再次建立。

---

## 为什么只影响 15787 场

只有 `[Range_15787]` 配置了 `Enable=1`，其他房间未启用 RangeAlloc。没有 RangeAlloc 的房间使用 `PutRobotQueque()` 的正常流程——机器人被加入 `m_queueProtectRobot` 队列，后续 `CallMoreRobot()` 还能从队列中取出使用。

---

## 为什么血流月月出、血战没事

两种可能（需进一步验证）：

1. **对局时长差异**：血流（胡牌后继续）单局更短 → 机器人更快回到匹配池 → 更快经过 `OnAskNewTable` → 更快触发 RangeAlloc::Add 吞噬
2. **房间配置差异**：血流场房间参数（如最大人数、机器人需求比例、段位区间）与血战不同，导致对机器人需求的时间窗口更窄

---

## 稳定复现方案

### 前提条件
- deposit 版 roomsvrxzmo + gamesvr 部署环境
- RangeAllocConfig.ini 中 `[Range_15787]` 配置为：`Enable=1`, `Interval=1000`, `MaxFullRobotTable=2`, `Robot_Clear=2`
- 机器人池 20 个分配给 room 15787

### 复现步骤

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | 启动 roomsvrxzmo，确认机器人上线 | 机器人状态均为 WALKAROUND |
| 2 | 真人玩家进入房间，进入匹配队列 | 正常 OnAskNewTable → RangeAlloc::Add 吞掉机器人 |
| 3 | 持续观察 2-5 分钟 | 机器人状态变为 WAITING，不再被 CallMoreRobot 使用 |
| 4 | 检查日志 | 出现 "EnterGame Failed"、"SetRandomPosition ghost" 等警告 |
| 5 | 检查机器人状态 | 大部分机器人为 WAITING，少量为 SEATED/PLAYING |
| 6 | 重启 roomsvr | 问题暂时消失，机器人重新变为 WALKAROUND |

### 验证手段

1. **在 `CRoomRangeAlloc::Add()` 添加日志**：
   ```cpp
   if (IS_BIT_SET(lpPlayer->nUserType, USER_TYPE_ROBOT)) {
       LOG("RANGEALLOC: robot %d consumed, status=%d, tableNO=%d",
           lpPlayer->nUserID, lpPlayer->nStatus, lpPlayer->nTableNO);
       return TRUE;
   }
   ```

2. **在 `CheckRobotJoinEnable()` 添加统计**：
   ```cpp
   int nWalkCount = 0, nWaitCount = 0, nSeatCount = 0, nPlayCount = 0;
   // ... 遍历循环内统计各状态数量
   LOG("RANGEALLOC: robots walk=%d wait=%d seat=%d play=%d",
       nWalkCount, nWaitCount, nSeatCount, nPlayCount);
   ```

3. **预期验证结果**：
   - 刚启动时：walk 多、wait 少 → 能开局
   - 运行 5 分钟：walk 极少、wait 增加 → 开局困难
   - 运行 30 分钟：walk ≈ 0、wait 占绝大多数 → **完全死锁**

---

## 修复方向

| 方案 | 描述 | 侵入性 |
|------|------|--------|
| A. RangeAlloc::Add 不吞机器人 | 机器人也加入 queue 而非直接 return TRUE | 低 |
| B. CallMoreRobot 从 WAITING 机器人中选取 | 修改 CheckRobotJoinEnable 条件 | 低 |
| C. 关闭 RangeAlloc 或改为 Enable=0 | 立刻恢复，但损失段位匹配 | 无（运维） |
| D. 重写 RangeAlloc 调度逻辑 | 根本解决，但工程量大 | 高 |

**推荐短期方案**：方案 C（关）或方案 A（最小改动）。

---

## 关联文件索引

| 文件 | 路径 |
|------|------|
| MainOpenServer.cpp | `D:\LibraryVC12_P\RoomOpen\trunk\MainOpenServer.cpp` |
| RoomRangeAlloc.hpp | `D:\LibraryVC12_P\RoomOpen\trunk\robot\RoomRangeAlloc.hpp` |
| RobotRoomData.cpp (deposit) | `D:\Codlib\douque\xzmx\xzmoNewPC\branches\douque\deposit\roomsvrxzmo\robot\RobotRoomData.cpp` |
| RoomRobotData.cpp (template) | `D:\LibraryVC12_P\RoomOpen\trunk\robot\RoomRobotData.cpp` |
| roomOpenData.cpp (template) | `D:\LibraryVC12_P\RoomOpen\trunk\roomOpenData.cpp` |
| RangeAlloc | `D:\Codlib\douque\jinbi\roomsvrxzmo\RangeAlloc\` |
