# L2 PBGameResult 上报字段说明
> 上报时机：开局收服务费、局内结算（胡牌或刮风下雨）、有玩家放弃复活、最终结算。
> ConstructPBGameResult 继承链各层上报字段明细。
> 对应服务：xzmo 金币版四川麻将（血流血战）

---

## 触发时机

ConstructPBGameResult 由 `TransmitGameResultExNew` → `TransmitGameResult` 触发，两个调用入口：

### 入口 1: PreSaveResult（局中结果上报）

**文件：** `jinbi\gamesvr\my\MyServer.cpp:5445`

| 触发场景 | 说明 |
|---------|------|
| 玩家胡牌 | 吃胡、自摸后立即上报 |
| 刮风下雨 | 补杠、暗杠、直杠后上报 |
| 其他人放弃复活 | OnGiveUpGame 导致的结果变更 |
| 换桌开局 | 开局收服务费 |

传参 `flag = PRE_RESULT`（`nResType = 0`），`result_idx` 自增，`final_result = 0`。

### 入口 2: CheckInGameResult（终局结果上报）

**文件：** `jinbi\gamesvr\my\MyServer.cpp:8917`

| 触发场景 | 说明 |
|---------|------|
| 血流结束（4人胡完或摸完牌墙） | 游戏正常结束 |
| 血战结束（只剩1人未胡） | 正常终局 |
| 所有人放弃 | OnGiveUpGame 全部放弃 |
| 房间解散/超时关服 | 强制终局 |

传参 `flag = FINAL_RESULT`（`nResType = 1`），`final_result = 1`。

### 调用链

```
PreSaveResult / CheckInGameResult
  └─ TransmitGameResultExNew  (CommonBaseServer.cpp:585)
       └─ 转换 GAME_RESULT_EXNEW → GAME_RESULT_EX
       └─ __super::TransmitGameResult  (CBaseServer, xygsvr.cpp:1197)
            └─ TransmitPBGameResult(pTable) 判断启用?
            └─ ConstructPBGameResult(...)     ← 调用点
            └─ PB_Serialize → 发送 PB_REFRESH_RESULT 给客户端
       └─ evTransmitGameResultWithFlag / evTransmitGameResultWhenGameWin
            └─ GameLogData::OnTransmitGameResultWithFlag     (日志落盘)
            └─ GameLogData::OnTransmitGameResultWhenGameWin  (DB记录)
```

### TransmitPBGameResult 开关

`CGameServer_WithFriend::TransmitPBGameResult`（CGameServer_WithFriend.cpp:259）从 ini 文件读取：

```cpp
BOOL CGameServer_WithFriend::TransmitPBGameResult(CTable* pTable) {
    return GetPrivateProfileInt("PBGameResult","Enable",TRUE, m_szIniFile);
}
```

默认启用。关闭时降级为旧协议 `GR_REFRESH_RESULT_EX`，不走 ConstructPBGameResult。

CGameServer_WithFriend 的 `TransmitGameResult` 重写（CGameServer_WithFriend.cpp:1096）还会在好友房已解散时拦截上报（返回 TRUE 假装成功）。

---

## 继承链总览

```
CBaseServer  (xyGame2.0\xygament\xygsvr.cpp:977)
  └─ CMJServer  (tcgMJ2.0 — 无 override，透传)
       └─ CMyGameServer  (jinbi\gamesvr\my\MyServer.cpp:1324)
            └─ CGameServer_WithFriend  (jinbi\common\friendroom\CGameServer_WithFriend.cpp:262)
```

调用顺序：CGameServer_WithFriend → CMyGameServer → CBaseServer，每层先调 `__super` 再追加/覆盖。

---

## Layer 1: CBaseServer（根实现）

**文件：** `xyGame2.0\trunk\xygament\xygsvr.cpp:977`

### 全局级字段（RefreshMutiResult）

| PB 字段 | C++ 来源 | 说明 |
|---------|----------|------|
| `roomid` | lpRefreshResult->nRoomID | 房间 ID |
| `gameid` | lpRefreshResult->nGameID | 游戏 ID |
| `clientid` | lpRefreshResult->nClientID | 客户端 ID |
| `flags` | lpRefreshResult->dwFlags | 标志位 |
| `tableno` | lpRefreshResult->nTableNO | 桌子号 |
| `starttime` | lpRefreshResult->dwStartTime | 开始时间戳 |
| `smallgameid` | lpRefreshResult->nSmallGameID | 子游戏 ID |
| `gamecode` | xygGameCodeFormDWORD(dwGameCode) | 游戏编码（字符串） |
| `serialno` | pTable->m_szSerialNO | 序列号 |
| `signlow` | pTable->m_dwSignLow | 签名低位 |
| `signhigh` | pTable->m_dwSignHigh | 签名高位 |

### 玩家级字段（gameresult[]）

| PB 字段 | C++ 来源 | 说明 |
|---------|----------|------|
| `userid` | lpGameResult[i].nUserID | 用户 ID |
| `roomid` | lpGameResult[i].nRoomID | 房间 ID |
| `tableno` | lpGameResult[i].nTableNO | 桌子号 |
| `chairno` | lpGameResult[i].nChairNO | 椅子号 |
| `gameid` | lpGameResult[i].nGameID | 游戏 ID |
| `basescore` | lpGameResult[i].nBaseScore | 基础分/豆 |
| `basedeposit` | lpGameResult[i].nBaseDeposit | 基础金币数 |
| `oldscore` | lpGameResult[i].nOldScore | 局前积分（金豆） |
| `olddeposit` | lpGameResult[i].nOldDeposit | 局前金币 |
| `experience` | lpGameResult[i].nExperience | 经验值 |
| `timecost` | lpGameResult[i].nTimeCost | 耗时 |
| `bout` | lpGameResult[i].nBout | 局数 |
| `breakoff` | lpGameResult[i].nBreakOff | 强退标记 |
| `win` | lpGameResult[i].nWin | 胜局 |
| `loss` | lpGameResult[i].nLoss | 负局 |
| `standoff` | lpGameResult[i].nStandOff | 平局 |
| `scorediff` | lpGameResult[i].nScoreDiff | 本局分差 |
| `depositdiff` | lpGameResult[i].nDepositDiff | 本局金币差 |
| `levelid` | lpGameResult[i].nLevelID | 等级 ID |
| `levelname` | lpGameResult[i].szLevelName | 等级名称 |
| `fee` | lpGameResult[i].nFee | 服务费 |
| `cut` | lpGameResult[i].nCut | 抽水 |
| `extra` | lpGameResult[i].nExtra | 扩展值 |
| `parentgameid` | lpGameResult[i].nParentGameId | 父游戏 ID |
| `parentgamecode` | ntohl(dwParentGameCode) | 父游戏编码（网络字节序转主机） |
| `usertype` | GetPlayer()->m_nUserType | 用户类型 |
| `add_info` | `{"magnification":%d}` winPoints[i] | 倍率 JSON |

### custom_info[]（每玩家）

| key | value | 条件 |
|-----|-------|------|
| `score_fee` | nScoreFee | 始终 |
| `sub_appcode` | ptrP->m_dwAppCode / gamecode | 始终 |
| `user_type(module)` | m_nPlayerTypes[i] | 始终 |
| `robot_provider(module)` | AI_GetAIProvider(i) | 仅机器人 |

---

## Layer 2: CMJServer（透传层）

**位置：** `tcgMJ2.0` 模板目录

不重写 ConstructPBGameResult，完全继承 CBaseServer 行为。

---

## Layer 3: CMyGameServer（金币版业务层）

**文件：** `jinbi\gamesvr\my\MyServer.cpp:1324`

### 执行顺序

1. 调用 `__super::ConstructPBGameResult`（→ CBaseServer）
2. `addScoreOverFlow(objRefreshResult)` — 设置 `score_overflow` 字段
3. 溢出预缓存：若 `oldscore + scorediff >= overflowLine`，调用 `m_boutDataCache.addPlayerBackBox(i, addCnt)`

### 覆盖字段

| PB 字段 | 新值 | 说明 |
|---------|------|------|
| `add_info` | `{"result_idx":%d,"final_result":%d}` | 覆盖 CBaseServer 的倍率(magnification) JSON，改为结果索引+终局标记 |

`result_idx` 来源：`InterlockedIncrement(&pGameTable->m_lResultIndex)`（自增序号）

`final_result` 来源：`pGameTable->IsGameWinFlag()`（1=终局, 0=中间局）

`score_overflow` 来源：addScoreOverFlow 函数写入（全局级字段）

### custom_info[] 追加（每玩家）

| key | value | 说明 |
|-----|-------|------|
| `room_currency_lower` | NewDepositModule::getRoomRange → nMinLimit | 房间最低限额 |
| `room_currency_upper` | NewDepositModule::getRoomRange → nMaxLimit | 房间最高限额 |
| `stash_score_balance` | m_boutDataCache.getPlayerBackBox(nCn) | 保险箱积分（金豆）余额 |
| `afk_turn_cnt` | m_boutDataCache.getPlayerAutoPlayTimes(nCn) | 托管次数 |
| `extend_content` | JSON: `{isover, isbroke, time_cost}` | 扩展信息 |

**extend_content JSON 字段：**

| 字段 | 类型 | 说明 |
|------|------|------|
| `isover` | int | 1=终局, 0=未结束 |
| `isbroke` | int | 1=金币为0, 0=有金币 |
| `time_cost` | int64 | 本局耗时（秒）|s

---

## Layer 4: CGameServer_WithFriend（好友房层）

**文件：** `jinbi\common\friendroom\CGameServer_WithFriend.cpp:262`

### 执行顺序

1. 调用 `__super::ConstructPBGameResult`（→ CMyGameServer → CBaseServer）
2. 判断 `IS_BIT_SET(GetGameOption(), ROOM_GO_MODSVR_FRIENDROOM)` — **仅好友房模式**执行以下操作

### 修改字段

| PB 字段 | 操作 | 说明 |
|---------|------|------|
| `scorediff` | 重置为 **0** | 隐藏真实分差，防止检查服拿到实际积分（金豆） |

### custom_info[] 追加（每玩家，仅好友房）

| key | value | 说明 |
|-----|-------|------|
| `mod(cp)` | JSON: 见下方 | 传给 CP 模块的好友房数据 |

**mod(cp) JSON 字段：**

| 字段 | 来源 | 说明 |
|------|------|------|
| `friendroom.thirdsex` | pPlayer->m_nThirdSex | 第三方性别 |
| `friendroom.thirdheadurl` | pPlayer->m_sHeadUrl | 第三方头像 URL |
| `friendroom.thirdname` | pPlayer->m_sThirdName | 第三方昵称 |
| `friendroom.roomnum` | pGameTable->m_nRoomNum | 好友房房间号 |
| `friendroom.scorediff` | m_nResultDiff[i][idx] | **缓存中的分差**（替代被清零的 scorediff） |
| `friendroom.playmode` | `"2mode_xl"` 或 `"3mode_xz"` | 玩法模式（血流/血战） |

> `idx = (curBount - 1) % MAX_RESULT_COUNT`，取当前局的缓存分差索引。

---

## 字段流向示意

```
CBaseServer 写入:
  roomid, gameid, ..., serialno, signlow, signhigh
  gameresult[]: userid, scorediff, depositdiff, ..., add_info=倍率
  custom_info[]: score_fee, sub_appcode, user_type, robot_provider
        │
        ▼
CMyGameServer 覆盖:
  add_info → {"result_idx":...,"final_result":...}    ★ 覆盖
  score_overflow                                      ★ 新增全局字段
  custom_info[]: room_currency_lower, room_currency_upper,
                 stash_score_balance, afk_turn_cnt,
                 extend_content({isover,isbroke,time_cost})
        │
        ▼
CGameServer_WithFriend 修改（仅好友房）:
  scorediff = 0                                        ★ 覆盖（清零）
  custom_info[]: mod(cp)                               ★ 新增
        │
        ▼
最终上报 PB 消息
```

---

## 关键设计点

1. **add_info 覆盖**：L1 写入倍率，L3 直接覆盖为 result_idx + final_result，L1 的倍率实际不生效
2. **scorediff 清零**：好友房模式 L4 将 scorediff 置 0，通过 `mod(cp).friendroom.scorediff` 传递缓存值，避免检查服记录真实分差
3. **溢出缓存**：L3 检测积分（金豆）超过上限时预缓存到 `m_boutDataCache`，避免竞态条件
4. **custom_info 累积**：每层追加不冲突，最终上报包含所有层的 custom_info
5. **playmode 区分**：好友房标记 "2mode_xl"（血流）或 "3mode_xz"（血战），CP 模块据此区分玩法