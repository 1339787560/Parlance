# xzmo2 — 银子血流血战 文档索引

> 版本象征名：**xzmo2** | 源码路径：`D:\Codlib\douque\xzmx\xzmoNewPC\branches\douque\deposit\`

---

## 版本定位

银子版四川麻将（血流血战玩法）。关注重点：**对局流程**、**活动内容**。与 CP-DEV-xzmp / Creator-Client-DEV-xzmp 的积分内容无关。

---

## 继承链

```
CMainServer → CCommonBaseServer → CMJServer → CMyGameServer
```
无好友房层，无金币系统。详见 [TemplateDoc/L1_TemplateChain.md](../TemplateDoc/L1_TemplateChain.md)。

---

## 核心模块

| 模块 | 文件 | 说明 |
|------|------|------|
| 服务器基类 | `commonBase/CommonBaseServer.h` | 业务服务器基类、事件系统 |
| 麻将服务器 | `mj/MjServer.h` | 麻将操作处理（吃碰杠胡） |
| 活动：百变双蛋 | `commonBase/DoubleEggDelegate.cpp` | 双蛋活动 |
| 活动：连胜 | `WinStreakModule.cpp` | 连胜活动 |
| 活动：每日首胜 | `DailyFirstWinModule.cpp` | 每日首胜奖励 |
| 活动：新手抽奖 | `commonBase/NoviceLotteryDelegate.cpp` | 新手抽奖 |
| 活动：排行榜 | `Ranklist.cpp` | 排行榜 |
| 任务模块 | `my/MyTaskDelegate.h` | 任务系统 |
| 微信任务 | `my/MyWxTaskDelegate.h` | 微信任务 |
| 宝箱模块 | `commonBase/TreasureDelegate.h` | 宝箱系统 |
| 道具加成 | `commonBase/PropsAddtion.cpp` | 道具加成 |
| 换房模块 | `SwitchRoomModule.cpp` | 房间切换 |
| 游戏日志 | `GameLogData.cpp` | 埋点日志 |
| 数据记录 | `DataRecord.cpp` | 数据统计 |
| 胡牌判定 | `../common/mj/GameHuUnitsMaker.h` | 胡牌单元构造 |

---

## 文档索引

| 文档 | 路径 | 说明 |
|------|------|------|
| 对局流程 | [L1_GameFlow.md](L1_GameFlow.md) | 生命周期、事件路由、模块注册顺序 |
| 活动系统 | [L1_ActivitySystem.md](L1_ActivitySystem.md) | 所有活动模块详解与通用模式 |
| 房间服务器 | [L1_RoomServerLogic.md](L1_RoomServerLogic.md) | roomsvr 架构、配置、匹配、机器人、与 gamesvr 通信 |
