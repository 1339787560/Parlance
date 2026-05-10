# xzmo — 金币血流血战 文档索引

> 版本象征名：**xzmo** | 源码路径：SVN `branches/douque/jinbi`

---

## 版本定位

金币版四川麻将（血流血战玩法）。关注重点：**游戏流程**、**金币接入**、**金币金豆兼容**、**好友房**、**结算流程**。活动内容大部分为 Lua 兼容型，不太重要。CP-DEV-xzmp / Creator-Client-DEV-xzmp 的积分内容与本版兼容。

---

## 继承链

```
CMainServer → CCommonBaseServer → CMJServer → CMyGameServer → CGameServer_WithFriend(好友房)
```
比银版多一层好友房扩展，使用 `GAME_RESULT_EXNEW` 支持金币。详见 [TemplateDoc/L1_TemplateChain.md](../TemplateDoc/L1_TemplateChain.md)。

---

## 核心模块

| 模块 | 文件 | 说明 |
|------|------|------|
| 服务器基类 | `commonBase/CommonBaseServer.h` | 业务服务器基类、事件系统 |
| 麻将服务器 | `mj/MjServer.h` | 麻将操作处理（吃碰杠胡） |
| 好友房服务器 | `common/friendroom/CGameServer_WithFriend.h` | 好友房扩展 |

---

## 文档索引

| 文档 | 路径 | 说明 |
|------|------|------|
| 游戏流程 | [L1_GameFlow.md](L1_GameFlow.md) | 生命周期、与银版差异、货币体系概览 |
| 金币接入 | [L1_GoldCoin.md](L1_GoldCoin.md) | NewDepositModule、金币金豆兼容、房间配置 |
| 好友房 | [L1_FriendRoom.md](L1_FriendRoom.md) | CGameServer_WithFriend、FR 流程、与普通模式差异 |
| 结算流程 | [L1_Settlement.md](L1_Settlement.md) | GAME_RESULT_EXNEW、PB 序列化、GameLogData 记录 |
