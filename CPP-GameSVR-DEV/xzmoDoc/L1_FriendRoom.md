# L1 好友房 — xzmo / xzms 共用

> 好友房功能通过 `CGameServer_WithFriend` 实现，继承于 `CMyGameServer`（虚拟继承）。

---

## 核心类

| 属性 | 值 |
|------|-----|
| 文件 | `common/friendroom/CGameServer_WithFriend.h` |
| 继承 | `virtual public CMyGameServer` |
| 实例化 | `_tmain` 非服务模式：`CGameServer_WithFriend mainServer(...)` |

---

## 覆写方法

| 方法 | 覆写行为 |
|------|----------|
| `OnRequest` | 新增好友房协议处理：`OnGetFRMultiBoutsInfo`, `OnCPSvrNotfiy`, `OnGetFriendRoomRule` |
| `OnNewTable` | 创建好友房桌子 |
| `OnGameWin` | 好友房结算 — 额外处理 FR 分数和奖励 |
| `OnClearTable` | 好友房桌子清理 |
| `OnGameEntered` | 好友房玩家进入记录 |
| `OnLeaveRoom` | 好友房离开处理 |
| `OnKickOffPlayer` | 好友房踢人 |
| `OnRoomSvrHWnd` | 好友房房间窗口注册 |
| `OnRoomTableChair` | 好友房桌位检测 |
| `OnTooManyAuto` / `OnTooManyBreak` | 好友房断线处理（带 FR 逻辑） |
| `TransmitGameResult` | 好友房结算下发 — 选桌时上报数据 |
| `GetMinPlayingDeposit` | 好友房最小底注计算 |
| `OnCustomNotify` | 好友房自定义通知 |
| `OnServerAutoPlay` | 好友房托管处理（含 bClockZero + robotDelay） |

---

## 好友房特有接口

| 接口 | 说明 |
|------|------|
| `FR_CloseSoloTable(pTable, nRoomID, nUserID, dwAbortFlag, ...)` | 解散好友房，计算 `nDepositDiffs` 和 `nWinFee` |
| `FR_ThinkExitSucceed(pTable, lpContext)` | 好友房协商解散成功 |
| `updateFrdRoomScore(table, score[])` | 更新好友房分数（`_tmain` 初始化时关联 `CMyGameServer::updateFrdRoomScore`） |
| `NotifyServiceFee(table)` | 发送服务费通知 |
| `TranslateGameRequest(module, notifyData, ...)` | 转发好友房请求到 CP 模块 |

---

## 好友房流程

```
创建好友房
  → CGameServer_WithFriend::OnNewTable()
  → OnRoomSvrHWnd()
      │
好友加入
  → OnGameEntered()
  → OnCustomNotify (选桌等自定义通知)
      │
游戏中
  → OnServerAutoPlay (托管)
  → OnTooManyAuto / OnTooManyBreak (断线)
      │
结算
  → OnGameWin() (FR 版：调用 updateFrdRoomScore → NotifyServiceFee)
  → TransmitGameResult() (FR 版：选桌时上报)
      │
协商解散 / 正常结束
  → FR_CloseSoloTable()
  → FR_ThinkExitSucceed()
      │
离开
  → OnLeaveRoom()
  → OnClearTable()
```

---

## 与普通模式差异

| 特性 | 普通模式 | 好友房模式 |
|------|---------|-----------|
| 桌子创建 | 系统匹配 | 玩家主动创建/好友加入 |
| 解散方式 | 正常结束或强制离开 | 协商解散 (FR_CloseSoloTable) |
| 服务费 | 无 | NotifyServiceFee |
| 结算 | 标准结算 | FR 结算 + updateFrdRoomScore |
| CP 转发 | 无 | TranslateGameRequest (转发到 CP 模块) |
| 数据上报 | — | RoomTableInfoMap (好友房信息缓存) |
