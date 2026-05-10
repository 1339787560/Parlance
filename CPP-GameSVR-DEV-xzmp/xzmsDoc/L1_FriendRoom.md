# L1 好友房 — xzms (金币血流六红中)

> 与 xzmo 共用 `CGameServer_WithFriend`。核心好友房逻辑见 [xzmoDoc/L1_FriendRoom.md](../xzmoDoc/L1_FriendRoom.md)。

## xzms 特有差异

xzms 中 `CGameServer_WithFriend` 位于 `common/friendroom/CGameServer_WithFriend.h`，与 xzmo 同源。

### 断线恢复 (BrokenModel)

| 属性 | 值 |
|------|-----|
| 文件 | `gamesvr/BrokenModel.cpp` |
| 事件 | `evPlayerNewDepositNotEnough` (金币不足断线) |
| 说明 | 好友房中金币不足时触发断线恢复流程 |

```cpp
auto brokenModule = GetEntity().assign<BrokenModel>();
mainSvr->evPlayerNewDepositNotEnough += delegate(brokenModule, &BrokenModel::OnPlayerBroken);
```

### 跨服节点通信 (GameSvrNodeClient)

| 属性 | 值 |
|------|-----|
| 文件 | `gamesvr/GameSvrNodeClient.cpp` |
| 说明 | 好友房需要跨游戏服通信，`GameSvrNodeClient` 负责服务间消息传递 |
| 初始化 | `g_node = gameSvrNodeClient.get()` (全局指针) |
| 注册事件 | `evRegisterOk` → `NewDepositModule::OnNodeRegsiterOK` |

### PlayRecordUtils (好友房工具)

xzms 版本的 `GameLogData.h` 中包含 `PlayRecordUtils`，定义了：
- `GetUserResultMultipe(table, chairno)` — 获取玩家结算倍数
- `GetUserDepositOpValue(table, chairno)` — 获取玩家金币操作值
- `GetIsHuaZhu(table, chairno)` — 判断是否花猪
- `GetIsDajiao(table, chairno)` — 判断是否大脚
- `TableDesposit/TableDespositLine` — 桌子底注配置解析
