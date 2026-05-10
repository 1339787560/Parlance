# xzms — 金币血流六红中 文档索引

> 版本象征名：**xzms** | 源码路径：`D:\Codlib\douque\xzmx\xzmsPC\branches\pve\zhong\`

---

## 版本定位

金币版四川麻将（血流六红中玩法）。关注重点：**金币接入**、**六红中玩法差异**。CP-DEV / Creator-Client-DEV 的积分内容与本版兼容。

---

## 继承链

```
CMainServer → CCommonBaseServer → CMJServer → CMyGameServer → CGameServer_WithFriend(好友房)
```
与 xzmo 同源，`CMyGameServer` 更大（~340行），含 PB 支持、模块管理器、本地 AI。详见 [TemplateDoc/L1_TemplateChain.md](../TemplateDoc/L1_TemplateChain.md)。

---

## 核心模块

| 模块 | 文件 | 说明 |
|------|------|------|
| 服务器基类 | `commonBase/CommonBaseServer.h` | 业务服务器基类、事件系统 |
| 麻将服务器 | `mj/MjServer.h` | 麻将操作处理（吃碰杠胡） |
| 游戏服务器(大) | `my/MyServer.h` | CMyGameServer（~340行），含 PB + 模块管理 |
| 好友房服务器 | `common/friendroom/CGameServer_WithFriend.h` | 好友房扩展 |
| 新金币模块 | `NewDepositModule.cpp` | 金币充值/消费 |
| 做牌模块 | `MakeCardNewModule.cpp` | 六红中做牌测试 |
| 本地 AI | `localai/LoaclAI.h` | AI 托管引擎 |
| 断线恢复 | `BrokenModel.cpp` | 金币不足断线 |
| 比赛模块 | `TQMatchModule.cpp` | 比赛匹配 |
| 摇礼物 | `ShakeGiftModule.cpp` | 金币摇礼物 |
| 节日活动 | `FestivalActivity.cpp` | 节日活动 |
| 积分兑换 | `ScoreExchange.cpp` | 金豆兑换 |
| 游戏服节点 | `GameSvrNodeClient.cpp` | 跨服通信 |

---

## 文档索引

| 文档 | 路径 | 说明 |
|------|------|------|
| 六红中玩法 | [L1_SixRedMiddle.md](L1_SixRedMiddle.md) | 六红中特殊规则、做牌模块、本地 AI、与血战差异 |
| 金币接入 | [L1_GoldCoin.md](L1_GoldCoin.md) | NewDepositModule、积分兑换、金币消费路径 |
| 好友房 | [L1_FriendRoom.md](L1_FriendRoom.md) | 好友房、断线恢复、跨服通信、PlayRecordUtils |
