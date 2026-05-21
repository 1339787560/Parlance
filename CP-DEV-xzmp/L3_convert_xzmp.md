# L3 数据迁移 convert_xzmp

> 协调模块，负责 chunkSvr → CP 在线懒迁移。触发时机：玩家登录 OnLogon。

---

## 模块定位

convert_xzmp 是迁移协调器，不存储业务数据，只管理迁移流程和标记。通过 HTTP 从 chunkSvr 拉取旧数据，转换格式后递交给目标模块（leveldefine / cmmonthcard / cmnewplayerdailygift）写入。

---

## 文件结构

| 文件 | 说明 |
|------|------|
| convert_xzmp.ts | 主脚本（迁移协调） |
| convert_xzmp.jsonc | 配置（chunkSvr 地址、超时、目标模块名、请求名映射） |

---

## 架构

```
                ┌─────────────────────┐
                │   convert_xzmp.ts   │
                │   (迁移协调模块)       │
                │                     │
                │  OnLogon 入口        │
                │  分布式锁保护         │
                │  检查迁移标记          │
                │  积分补偿(直接发放)    │
                │  金币迁移(HTTP+发放)  │
                │  HTTP 拉取 chunkSvr  │
                │  数据格式转换          │
                │  递交数据给目标模块     │
                │  置位迁移标记          │
                │  推送结果给客户端      │
                └──────┬──────────────┘
                       │ async_internal_call
          ┌────────────┼────────────────┐
          ▼            ▼                ▼
 ┌────────────┐ ┌────────────┐  ┌──────────────────┐
 │ leveldefine │ │ cmmonthcard│  │cmnewplayerdailygift│
 │            │ │            │  │                    │
 │ 新增消息:   │ │ 新增消息:   │  │ 新增消息:           │
 │ MIGRATION_ │ │ MIGRATION_ │  │ MIGRATION_WRITE_  │
 │ WRITE_VIP_ │ │ WRITE_CARD │  │ GIFT_INFO         │
 │ INFO       │ │ _INFO      │  │                    │
 └────────────┘ └────────────┘  └────────────────────┘
```

---

## 迁移标记

| 位 | 模块 | 标记含义 | 幂等性 |
|----|------|---------|--------|
| bit 0 (0x01) | 荣耀特权 TQVip | VIP 等级与奖励记录已迁移 | 幂等（覆盖写入） |
| bit 1 (0x02) | 周月卡 TQMonthCard | 月卡/周卡时间已迁移 | 幂等（覆盖写入） |
| bit 2 (0x04) | 迎新礼包 TQNewPlayerDailyGift | 签到剩余数据已迁移 | 幂等（覆盖写入） |
| bit 3 (0x08) | 积分补偿 | 负积分已补偿 | **非幂等**（重复发放积分偏多） |
| bit 4 (0x10) | 金币迁移 | 金币→积分已发放 | **非幂等**（同上） |

- `0x1F (31)` = 全部迁移完成
- `0` = 未迁移任何模块

### 标记存储

| 存储 | Key/表 | TTL |
|------|--------|-----|
| Redis | `mod(cp):name(convert):appcode(xzmp):uid({uid}):ChunksvrMigrationFlag` | 30 天 |
| MySQL | `tblcpuserdata_convert_xzmp`，name=`ChunksvrMigrationFlag`，data=`{"flags":N}` | 永久 |

读取优先级：Redis → MySQL fallback → 默认值 0。MySQL 读到后回填 Redis。

---

## OnLogon 流程

```
1. 检查 isenable 开关
2. 获取分布式锁（key: ...:migrationLock, TTL: 10s）
   锁失败 → 跳过（另一个 OnLogon 正在执行迁移）
3. 读取迁移标记
4. 积分补偿 (bit 3) — 非幂等，即时持久化
   score < 0 → async_sendGoldCoin_super(|score|) → 置位
   score ≥ 0 → 仅置位
5. 金币迁移 (bit 4) — 非幂等，即时持久化
   HTTP 拉取 newdeposit → async_sendGoldCoin_super → 置位
6. VIP 迁移 (bit 0) — 幂等
7. 月卡迁移 (bit 1) — 幂等
8. 礼包迁移 (bit 2) — 幂等
9. 幂等标记合并写入（flags 有变化时一次性写 Redis+MySQL）
10. 推送 migrationResult_convert_xzmp 给客户端
11. 释放锁
```

### 并发安全

- 分布式锁保证同一玩家同时只有一个迁移在执行
- 非幂等操作（积分补偿、金币迁移）完成后立即持久化标记，防止崩溃重复发放
- 幂等操作合并为末尾一次写入，减少 IO

---

## 数据映射

### 积分补偿 (bit 3)

| 来源 | 条件 | 动作 |
|------|------|------|
| `logon.usergameinfo.score` | score < 0 | 发放 \|score\| 积分，置位 bit 3 |
| | score ≥ 0 | 直接置位 bit 3 |

不依赖 chunkSvr HTTP，数据来自 OnLogon 回调参数。

### 金币迁移 (bit 4)

| chunkSvr 接口 | 返回字段 | CP 目标 | 转换 |
|--------------|---------|--------|------|
| `querynewdeposit` | newdeposit | leveldefine 积分 | 等量发放，分批 ≤2B/批 |

### 荣耀特权 (bit 0)

| chunkSvr 字段 | CP 字段 | 转换 |
|--------------|--------|------|
| `grade` | → `PlayerLevelData`（由 leveldefine 计算） | 直接映射 |
| `experience` | `totalConsumeNum` | 经验→消耗量 |
| `experience` | `totalAcquireNum` | 与 totalConsumeNum 一致 |
| `rewardstatus` | `oneOffRewardStatusArray` | Lua 1基→CP 0基索引；值 1→status:2(RECEIVED),gotTime=迁移时间戳；值 0→status:0,gotTime=0 |
| `maxgrade`, `maxexperience`, `datetag`, `lastshowanigrade` | — | 忽略 |

空数据（grade=0 且 experience=0 且 rewardstatus=[]）→ 跳过，让 CP 初始化。

### 周月卡 (bit 1)

| chunkSvr 字段 | CP 字段 | 转换 |
|--------------|--------|------|
| `monthcard.starttime` | `monthCardInfo.BuyTime` | 直拷（YYYYMMDDHHmmSS 格式整数） |
| `monthcard.endtime` | `monthCardInfo.EndTime` | 直拷 |
| `weekcard.starttime` | `weekCardInfo.BuyTime` | 直拷 |
| `weekcard.endtime` | `weekCardInfo.EndTime` | 直拷 |
| `monthcardRedress.datetag` / `weekcardRedress.datetag` | `redressUseTime` | 直拷（YYYYMMDD），优先月卡 |

空数据（两张卡均为空对象）→ 跳过。

### 迎新礼包 (bit 2)

| chunkSvr 字段 | CP 字段 | 转换 |
|--------------|--------|------|
| `triggerdate` | `buyTime` | `ymdToEpoch`（YYYYMMDD → epoch 秒） |
| `receivedays` | `lastClaimDay` | 直拷 |
| `lastdate` | `lastClaimDate` | 直拷（YYYYMMDD 格式） |
| `newplayer` | — | 判断用：0=未购买→跳过，1=已购买→写入 |
| `remaindays`, `awarditems` | — | 丢弃 |

无论是否过期都写入 giftInfo，防止二次购买。

---

## chunkSvr HTTP 接口

端点：`POST http://{chunkSvrIP}:9080/v1.0/chunkluareq`

| 请求名 | 请求体 | 返回字段 |
|--------|--------|---------|
| `querynewdeposit` | `{"req":"querynewdeposit","nUserID":xxx}` | nUserID, newdeposit |
| `querytqvip` | `{"req":"querytqvip","nUserID":xxx}` | nUserID, grade, experience, maxgrade, maxexperience, rewardstatus, datetag, lastshowanigrade |
| `querytqmonthcard` | `{"req":"querytqmonthcard","nUserID":xxx}` | nUserID, monthcard{starttime,endtime,datetag}, weekcard{...}, monthcardRedress?, weekcardRedress? |
| `querynewplayerdailygift` | `{"req":"querynewplayerdailygift","nUserID":xxx}` | nUserID, newplayer, triggerdate, lastdate, receivedays, remaindays, awarditems |
| `setnewplayerdailygift` | `{"req":"setnewplayerdailygift","nUserID":xxx,...}` | 测试接口，设置玩家迎新礼包状态 |

响应格式：`{"err": null, "ret": "{...JSON字符串...}"}`

### 环境配置

| 环境 | chunkSvr IP | `get_svrenv()` 返回值 |
|------|------------|---------------------|
| 125 | 192.168.102.53 | `"125"` |
| 888 | 120.26.104.186 | `"888"` |
| 正式 | 116.62.36.4 | 其他值 |

配置项：`chunkSvrHttpUrls`（按环境 key-value），`getChunkSvrUrl()` 根据 `modsvr.get_svrenv()` 选地址。

---

## 客户端推送

消息名：`migrationResult_convert_xzmp`

```typescript
{
    flags: number;               // 迁移标记位掩码 (0-31)
    levelInfo: UserData_PlayerLevelInfo | null;
    monthCardInfo: CMMONTHCARD_INFO | null;
    giftInfo: UserData_NewPlayerDailyGiftInfo | null;
}
```

`null` = 该模块本次未迁移。推送数据为原始存储格式，与客户端查询接口返回的加工后格式不同。建议客户端收到推送后对非 null 模块重新发起查询请求。

详见 [迁移结果推送消息文档](doc/迁移结果推送消息文档.md)。

---

## 跨模块查询接口

目标模块测试时通过 `async_internal_call` 向 convert 查询迁移数据：

| 消息名 | 返回 | 说明 |
|--------|------|------|
| `queryMigrationVipData` | `{data, source}` | VIP 迁移数据，source=chunksvr/mock |
| `queryMigrationCardData` | `{data, source}` | 月卡迁移数据 |
| `queryMigrationGiftData` | `{data, source}` | 礼包迁移数据 |
| `queryTestGiftScenario` | `{data, source:'test'}` | 礼包测试场景（scenario=1未购买/2已购买未过期/3已过期） |

chunkSvr 不可用时自动降级为 mock 数据。

---

## 降级策略

| 场景 | 处理 |
|------|------|
| chunkSvr 不可达（超时/连接失败） | 不置位标记，下次登录重试 |
| chunkSvr 返回 err 非 null | 不置位，下次重试 |
| chunkSvr 返回空数据（零值） | 置位标记（视为已迁移空数据） |
| 目标模块写入失败 | 不置位该模块标记，下次重试 |
| async_sendGoldCoin_super 失败 | 不置位 bit 3/4，下次重试 |
| 获取分布式锁失败 | 跳过本次迁移，下次登录重试 |

---

## 目标模块改动

### leveldefine_xzmp.ts

- `REQ_NAME` 新增 `MIGRATION_WRITE_VIP_INFO`
- `OnInternalCall` 新增分支：写入 totalConsumeNum/totalAcquireNum/oneOffRewardStatusArray，填充 CAN_RECEIVED
- `TestTool` 新增 `async_testMigrationWriteVipInfo`

### cmmonthcard_xzmp.ts

- `REQ_NAME` 新增 `MIGRATION_WRITE_CARD_INFO`
- `OnInternalCall` 新增分支：写入 monthCardInfo/weekCardInfo/redressUseTime
- `TestTool` 新增 `async_testMigrationWriteCardInfo`

### cmnewplayerdailygift_xzmp.ts

- `REQ_NAME` 新增 `MIGRATION_WRITE_GIFT_INFO`
- `OnInternalCall` 新增分支：写入 buyTime/lastClaimDay/lastClaimDate
- `TestTool` 新增 `async_testMigrationWriteGiftInfo`

---

## chunkSvr Lua 改动

### TQNewPlayerDailyGift.lua

新增 2 个 HTTP handler：

| 请求名 | 说明 | 参数 |
|--------|------|------|
| `querynewplayerdailygift` | 查询礼包数据 | nUserID |
| `setnewplayerdailygift` | 设置礼包数据（测试用） | nUserID, newplayer?, triggerdate?, lastdate?, receivedays?, remaindays? |

---

## 测试

| 函数 | 说明 |
|------|------|
| `TestTool.async_testMigration` | 逐模块测试迁移 |
| `TestTool.async_testChunkSvrHttp` | 测试 chunkSvr HTTP 连通性 |
| `TestTool.async_clearMigrationFlag` | 清除测试玩家迁移标记 |
| `TestTool.async_testOnLogon` | OnLogon 集成测试 |
| `TestTool.async_testGiftScenario` | 迎新礼包场景测试 |

运行：修改 `TEST_ONLY_USERID` → `main()` → `async_execAllTest()`

---

## 关键实现细节

- `async_sendGoldCoin_super`：分批发放，每批 ≤2B（20亿），大额自动拆分
- `convertRewardStatus`：Lua 1基 int[] → CP 0基 {status,gotTime}[]，兼容空表 `{}`
- `ymdToEpoch`：支持 8 位 YYYYMMDD（补全为 000000）和 14 位 YYYYMMDDHHmmSS
- 月卡 BuyTime/EndTime 保持 YYYYMMDDHHmmSS 整数格式（与 cmmonthcard 的 getTimeNum 格式一致），不做 epoch 转换

---

*文档版本: v1.0*
*创建日期: 2026/05/20*
