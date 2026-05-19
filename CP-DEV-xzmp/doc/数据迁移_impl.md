# 数据迁移实现文档 — chunkSvr → CP

> 基于: [数据迁移.md](数据迁移.md) v5.0 产品设计文档

***

## 一、模块职责划分

```
                    ┌─────────────────────┐
                    │   convert_xzmp.ts   │
                    │   (迁移协调模块)       │
                    │                     │
                    │  OnLogon 入口        │
                    │  检查迁移标记          │
                    │  积分补偿(直接发放)    │
                    │  金币迁移(HTTP+发放)  │
                    │  HTTP 拉取 chunkSvr  │
                    │  数据格式转换          │
                    │  递交数据给目标模块     │
                    │  置位迁移标记          │
                    │  返回结果给客户端      │
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

### convert_xzmp（协调模块）

**职责**：
- OnLogon 入口，检查迁移标记（Redis + MySQL）
- HTTP 请求 chunkSvr 拉取 4 模块数据
- chunkSvr JSON → CP 数据结构转换
- 积分补偿：`async_sendGoldCoin_super` 发放 |score| 抵消负数
- 金币迁移：`async_sendGoldCoin_super` 发放 newdeposit 等量积分
- 将转换后数据通过 `async_internal_call` 递交给各目标模块
- 接收目标模块返回结果，置位迁移标记
- 全部模块处理完毕后返回结果给客户端
- **不直接操作**目标模块的 MySQL/Redis

### leveldefine_xzmp（目标模块）

**新增职责**：
- 接收 `MIGRATION_WRITE_VIP_INFO` 内部调用
- 写入 VIP 等级 + rewardstatus 数据
- 执行 `updateRewardList()` 自动填充 CAN_RECEIVED 状态
- 写入 MySQL + Redis
- 返回成功/失败

### cmmonthcard_xzmp（目标模块）

**新增职责**：
- 接收 `MIGRATION_WRITE_CARD_INFO` 内部调用
- 写入月卡/周卡 BuyTime/EndTime
- 写入 redressUseTime 包赔数据
- 写入 MySQL + Redis
- 返回成功/失败

### cmnewplayerdailygift_xzmp（目标模块）

**新增职责**：
- 接收 `MIGRATION_WRITE_GIFT_INFO` 内部调用
- 写入 buyTime / lastClaimDay / lastClaimDate
- 写入 MySQL + Redis
- 返回成功/失败

***

## 二、文件增量清单

### 2.1 新增文件

| 文件 | 说明 | 预估行数 |
|------|------|---------|
| `convert_xzmp.jsonc` | 迁移模块配置（chunkSvr URL、超时、迁移标记 key 等） | ~20 |
| `convert_xzmp.ts` | 迁移协调脚本（OnLogon + HTTP + 数据转换 + 分发 + 标记） | ~350 |

### 2.2 修改文件

| 文件 | 改动 | 预估行数 |
|------|------|---------|
| `leveldefine_xzmp.ts` | OnInternalCall 新增 `MIGRATION_RESET_AND_WRITE_INFO` 分支；REQ_NAME 新增常量；返回写入后最新数据 | ~45 |
| `cmmonthcard_xzmp.ts` | OnInternalCall 新增 `MIGRATION_WRITE_CARD_INFO` 分支；REQ_NAME 新增常量；返回写入后最新数据 | ~35 |
| `cmnewplayerdailygift_xzmp.ts` | OnInternalCall 新增 `MIGRATION_WRITE_GIFT_INFO` 分支；REQ_NAME 新增常量；返回写入后最新数据 | ~30 |

### 总增量：~470 行

***

## 三、convert_xzmp.jsonc 设计

```jsonc
{
    "isenable": 1,
    "guid": "JC_CONVERT_XZMP_MIGRATION_001",
    // chunkSvr HTTP 配置
    "chunkSvrHttpUrl": "http://127.0.0.1:9080/v1.0/chunkluareq",
    "chunkSvrHttpTimeout": 2,          // 秒
    // 迁移标记
    "migrationFlagRedisKey": "xzmp_chunksvr_migrated",  // Redis key 前缀，实际 key = {prefix}:{userid}
    "migrationFlagRedisTTL": 0,         // 0 = 永久
    // 目标模块名
    "targetModules": {
        "leveldefine": "leveldefine",
        "cmmonthcard": "cmmonthcard",
        "cmnewplayerdailygift": "cmnewplayerdailygift"
    },
    // HTTP 请求名
    "chunkSvrReqNames": {
        "newdeposit": "querynewdeposit",
        "tqvip": "querytqvip",
        "tqmonthcard": "querytqmonthcard",
        "newplayerdailygift": "querynewplayerdailygift"
    }
}
```

***

## 四、convert_xzmp.ts 设计

### 4.1 常量与类型

```typescript
const CONST_VAR = {
    MODULE_NAME: 'convert',
    GAME_CODE: 'xzmp',
    APP_CODE: 'xzmp',
    GAME_ID: 283,
};

const REQ_NAME = {
    // 内部调用 → 目标模块
    MIGRATION_WRITE_VIP_INFO: 'migrationWriteVipInfo',
    MIGRATION_WRITE_CARD_INFO: 'migrationWriteCardInfo',
    MIGRATION_WRITE_GIFT_INFO: 'migrationWriteGiftInfo',
    // 推送 → 客户端
    MIGRATION_RESULT: 'migrationResult_convert_xzmp',
};

// 迁移标记位
const MIGRATION_BIT = {
    TQVIP: 0x01,                // bit 0
    TQMONTHCARD: 0x02,          // bit 1
    TQNEWPLAYERDAILYGIFT: 0x04, // bit 2
    SCORE_COMPENSATE: 0x08,     // bit 3 — 积分补偿
    GOLD_COIN: 0x10,            // bit 4 — 金币迁移
    ALL_DONE: 0x1F,             // 31
};

// chunkSvr 返回数据接口
interface ChunkSvrNewDeposit { nUserID: number; newdeposit: number; }
interface ChunkSvrTQVip { nUserID: number; grade: number; experience: number; maxgrade: number; maxexperience: number; rewardstatus: number[]; datetag: number; lastshowanigrade: number; }
interface ChunkSvrCardInfo { starttime: number; endtime: number; datetag: number; }
interface ChunkSvrMonthCard { nUserID: number; monthcard: ChunkSvrCardInfo; weekcard: ChunkSvrCardInfo; monthcardRedress?: { datetag: number; gettime: number; endtime: number; }; weekcardRedress?: { datetag: number; gettime: number; endtime: number; }; }
interface ChunkSvrNewPlayerDailyGift { nUserID: number; newplayer: number; triggerdate: number; lastdate: number; receivedays: number; remaindays: number; awarditems: number[]; }
```

### 4.2 OnLogon 主流程

```typescript
async function OnLogon(logon: modsvr.logon, cxt: modsvr.context): Promise<void> {
    let userid = logon.userid;
    let src = { client: { appcode: CONST_VAR.APP_CODE, gameid: CONST_VAR.GAME_ID, userid }, mods: [] };
    let config = CommonFuncs.loadConfig();

    // 1. 检查迁移标记
    let flags = CommonFuncs.getMigrationFlags(cxt, userid);
    if (flags === MIGRATION_BIT.ALL_DONE) return; // 已全部迁移

    // 收集迁移结果，用于推送给客户端
    let migrationResult = {
        flags: flags,
        levelInfo: null as any,
        monthCardInfo: null as any,
        giftInfo: null as any,
    };

    // 2. 积分补偿（bit 3）— 先行
    if ((flags & MIGRATION_BIT.SCORE_COMPENSATE) === 0) {
        let score = logon.usergameinfo?.score ?? 0;
        if (score < 0) {
            let result = await migrateScoreCompensate(src, cxt, userid, flags, score);
            if (result) { flags = result.flags; }
        } else {
            // 积分 ≥ 0 直接置位
            flags = flags | MIGRATION_BIT.SCORE_COMPENSATE;
            CommonFuncs.setMigrationFlags(cxt, userid, flags);
        }
    }

    // 3. 金币迁移（bit 4）— 随后
    if ((flags & MIGRATION_BIT.GOLD_COIN) === 0) {
        let bout = logon.usergameinfo?.bout ?? 0;
        if (bout >= 1) {
            let result = await migrateGoldCoin(src, cxt, userid, flags, config);
            if (result) { flags = result.flags; }
        } else {
            // 无局数玩家直接置位 bit 4
            flags = flags | MIGRATION_BIT.GOLD_COIN;
            CommonFuncs.setMigrationFlags(cxt, userid, flags);
        }
    }

    // 4. VIP 迁移（bit 0）
    if ((flags & MIGRATION_BIT.TQVIP) === 0) {
        let result = await migrateTQVip(src, cxt, userid, flags, config);
        if (result) { flags = result.flags; migrationResult.levelInfo = result.levelInfo; }
    }

    // 5. 月卡迁移（bit 1）
    if ((flags & MIGRATION_BIT.TQMONTHCARD) === 0) {
        let result = await migrateTQMonthCard(src, cxt, userid, flags, config);
        if (result) { flags = result.flags; migrationResult.monthCardInfo = result.monthCardInfo; }
    }

    // 6. 迎新礼包迁移（bit 2）
    if ((flags & MIGRATION_BIT.TQNEWPLAYERDAILYGIFT) === 0) {
        let result = await migrateNewPlayerDailyGift(src, cxt, userid, flags, config);
        if (result) { flags = result.flags; migrationResult.giftInfo = result.giftInfo; }
    }

    // 7. 推送迁移结果给客户端
    migrationResult.flags = flags;
    modsvr.notify_client(src, cxt, REQ_NAME.MIGRATION_RESULT, migrationResult);
}
```

### 4.3 核心迁移函数

#### 积分补偿 migrateScoreCompensate

```typescript
async function migrateScoreCompensate(src, cxt, userid, flags, score: number): Promise<{flags: number} | null> {
    // 发放 |score| 积分抵消负数
    let compensateAmount = Math.abs(score);
    let success = await Business.async_sendGoldCoin_super(src, cxt, userid, compensateAmount);
    if (!success) return null; // 发放失败，不置位，下次重试

    // 置位 bit 3
    let newFlags = flags | MIGRATION_BIT.SCORE_COMPENSATE;
    CommonFuncs.setMigrationFlags(cxt, userid, newFlags);

    return { flags: newFlags };
}
```

#### 金币迁移 migrateGoldCoin

```typescript
async function migrateGoldCoin(src, cxt, userid, flags, config): Promise<{flags: number} | null> {
    // HTTP 拉取
    let data = await chunkSvrHttp<ChunkSvrNewDeposit>(cxt, config, 'newdeposit', userid);
    if (!data) return null; // chunkSvr 不可达，不置位，下次重试

    // 发放等量积分
    let success = await Business.async_sendGoldCoin_super(src, cxt, userid, data.newdeposit);
    if (!success) return null; // 发放失败，不置位，下次重试

    // 置位 bit 4
    let newFlags = flags | MIGRATION_BIT.GOLD_COIN;
    CommonFuncs.setMigrationFlags(cxt, userid, newFlags);

    return { flags: newFlags };
}
```

#### VIP 迁移 migrateTQVip

```typescript
async function migrateTQVip(src, cxt, userid, flags, config): Promise<{flags: number, levelInfo: any} | null> {
    let data = await chunkSvrHttp<ChunkSvrTQVip>(cxt, config, 'tqvip', userid);
    if (!data) return null;

    // 转换 rewardstatus: Lua 1基 → CP 0基, 值 1→status:2
    let oneOffRewardStatusArray = convertRewardStatus(data.rewardstatus);

    // 通过 leveldefine 内部调用写入
    let resp = await CommonFuncs.async_internal_call(
        src, cxt, REQ_NAME.MIGRATION_WRITE_VIP_INFO,
        config.targetModules.leveldefine,
        {
            grade: data.grade,
            totalConsumeNum: data.experience,
            totalAcquireNum: data.experience,
            oneOffRewardStatusArray,
        }
    );
    if (resp.resp.id !== 1) return null;

    let newFlags = flags | MIGRATION_BIT.TQVIP;
    CommonFuncs.setMigrationFlags(cxt, userid, newFlags);

    return { flags: newFlags, levelInfo: resp.resp.data.data };
}
```

#### 月卡迁移 migrateTQMonthCard

```typescript
async function migrateTQMonthCard(src, cxt, userid, flags, config): Promise<{flags: number, monthCardInfo: any} | null> {
    let data = await chunkSvrHttp<ChunkSvrMonthCard>(cxt, config, 'tqmonthcard', userid);
    if (!data) return null;

    // YYYYMMDDHHmmSS → epoch 秒
    let monthCard = data.monthcard && Object.keys(data.monthcard).length > 0 ? {
        BuyTime: ymdToEpoch(data.monthcard.starttime),
        EndTime: ymdToEpoch(data.monthcard.endtime),
        type: 1,
    } : null;

    let weekCard = data.weekcard && Object.keys(data.weekcard).length > 0 ? {
        BuyTime: ymdToEpoch(data.weekcard.starttime),
        EndTime: ymdToEpoch(data.weekcard.endtime),
        type: 2,
    } : null;

    // 包赔数据
    let redressUseTime = 0;
    if (data.monthcardRedress?.datetag) redressUseTime = data.monthcardRedress.datetag;
    else if (data.weekcardRedress?.datetag) redressUseTime = data.weekcardRedress.datetag;

    let resp = await CommonFuncs.async_internal_call(
        src, cxt, REQ_NAME.MIGRATION_WRITE_CARD_INFO,
        config.targetModules.cmmonthcard,
        { monthCardInfo: monthCard, weekCardInfo: weekCard, redressUseTime }
    );
    if (resp.resp.id !== 1) return null;

    let newFlags = flags | MIGRATION_BIT.TQMONTHCARD;
    CommonFuncs.setMigrationFlags(cxt, userid, newFlags);

    return { flags: newFlags, monthCardInfo: resp.resp.data.data };
}
```

#### 迎新礼包迁移 migrateNewPlayerDailyGift

```typescript
async function migrateNewPlayerDailyGift(src, cxt, userid, flags, config): Promise<{flags: number, giftInfo: any} | null> {
    let data = await chunkSvrHttp<ChunkSvrNewPlayerDailyGift>(cxt, config, 'newplayerdailygift', userid);
    if (!data) return null;

    // 未充值 → 置位（CP 端按新用户处理）
    if (data.newplayer === 0) {
        let newFlags = flags | MIGRATION_BIT.TQNEWPLAYERDAILYGIFT;
        CommonFuncs.setMigrationFlags(cxt, userid, newFlags);
        return { flags: newFlags, giftInfo: null };
    }

    // 判断签到有效期: triggerdate + checkindays
    let giftConfig = CommonFuncs.loadGiftConfig(); // 读 cmnewplayerdailygift 配置
    let triggerDateNum = data.triggerdate;          // YYYYMMDD
    let nowDateNum = getDateNum();                  // 当前 YYYYMMDD
    let daysPassed = dateDiff(triggerDateNum, nowDateNum);
    let isExpired = daysPassed >= giftConfig.checkindays;

    if (isExpired) {
        // 已过期 → 置位，不写入数据
        let newFlags = flags | MIGRATION_BIT.TQNEWPLAYERDAILYGIFT;
        CommonFuncs.setMigrationFlags(cxt, userid, newFlags);
        return { flags: newFlags, giftInfo: null };
    }

    // 未过期 → 迁移签到数据
    let giftInfo = {
        buyTime: ymdToEpoch(triggerDateNum),    // YYYYMMDD → epoch
        lastClaimDay: data.receivedays,          // 直拷
        lastClaimDate: data.lastdate,            // 直拷
    };

    let resp = await CommonFuncs.async_internal_call(
        src, cxt, REQ_NAME.MIGRATION_WRITE_GIFT_INFO,
        config.targetModules.cmnewplayerdailygift,
        { giftInfo }
    );
    if (resp.resp.id !== 1) return null;

    let newFlags = flags | MIGRATION_BIT.TQNEWPLAYERDAILYGIFT;
    CommonFuncs.setMigrationFlags(cxt, userid, newFlags);

    return { flags: newFlags, giftInfo: resp.resp.data.data };
}
```

### 4.4 工具函数

```typescript
// chunkSvr HTTP 请求
async function chunkSvrHttp<T>(cxt, config, moduleKey, userid): Promise<T | null> {
    let reqName = config.chunkSvrReqNames[moduleKey];
    let body = JSON.stringify({ req: reqName, nUserID: userid });
    let resp = await http.async_post(cxt, config.chunkSvrHttpUrl,
        { "Content-Type": "application/json" }, body, config.chunkSvrHttpTimeout);
    if (!resp || !http.is_succeed(resp.status)) return null;
    let outer = JSON.parse(resp.body);
    if (outer.err) return null;
    if (!outer.ret) return {} as T; // 空数据，视为已迁移空数据
    return JSON.parse(outer.ret);
}

// rewardstatus 转换: Lua 1基 int[] → CP 0基 {status,gotTime}[]
function convertRewardStatus(rewardstatus: number[]): { status: number; gotTime: number }[] {
    let result = [];
    let nowTs = Math.floor(Date.now() / 1000);
    for (let grade = 0; grade < 16; grade++) {
        let luaValue = rewardstatus[grade + 1] ?? 0; // Lua 1基索引
        result.push({
            status: luaValue === 1 ? 2 : 0,  // 1=已领取 → 2=RECEIVED; 0=未领取 → 0
            gotTime: luaValue === 1 ? nowTs : 0,
        });
    }
    return result;
}

// YYYYMMDDHHmmSS → epoch 秒
function ymdToEpoch(ymd: number): number {
    let str = ymd.toString();
    let year = parseInt(str.substring(0, 4));
    let month = parseInt(str.substring(4, 6)) - 1;
    let day = parseInt(str.substring(6, 8));
    let hour = str.length >= 10 ? parseInt(str.substring(8, 10)) : 0;
    let minute = str.length >= 12 ? parseInt(str.substring(10, 12)) : 0;
    let second = str.length >= 14 ? parseInt(str.substring(12, 14)) : 0;
    return Math.floor(new Date(year, month, day, hour, minute, second).getTime() / 1000);
}

// 迁移标记读写
namespace CommonFuncs {
    function getMigrationRedisKey(userid: number): string {
        return `xzmp_chunksvr_migrated:${userid}`;
    }

    function getMigrationFlags(cxt, userid): number {
        let key = getMigrationRedisKey(userid);
        let r = redis.command({ cmd: 'GET', args: [key] });
        if (r && r[0] != 'nil' && r[0].length > 0) {
            return parseInt(r[0]);
        }
        // Redis miss → 查 MySQL（待实现，按 CP 统一表结构）
        return 0;
    }

    function setMigrationFlags(cxt, userid, flags: number): void {
        let key = getMigrationRedisKey(userid);
        redis.command({ cmd: 'SET', args: [key, flags.toString()] });
        // 双写 MySQL（待实现）
    }
}
```

***

## 五、目标模块改动设计

### 5.1 leveldefine_xzmp.ts

**REQ_NAME 新增**：

```typescript
MIGRATION_WRITE_VIP_INFO: 'migrationWriteVipInfo',
```

**OnInternalCall 新增分支**：

```typescript
else if (req_name == REQ_NAME.MIGRATION_WRITE_VIP_INFO) {
    let reqData = req_data.data;
    let redisTool = new RedisTool_PlayerLevelInfo(cxt, userid);
    let currentData = await redisTool.async_getData();

    if (!currentData) {
        currentData = new interf.UserData_PlayerLevelInfo();
        currentData.oneOffRewardStatusArray = Array.from({length: 16}, () => ({status: 0, gotTime: 0}));
    }

    // 写入 VIP 数据
    currentData.totalConsumeNum = reqData.totalConsumeNum;
    currentData.totalAcquireNum = reqData.totalAcquireNum;
    currentData.oneOffRewardStatusArray = reqData.oneOffRewardStatusArray;
    // updateRewardList 自动填充 CAN_RECEIVED 状态
    Business.updateRewardList(currentData);

    // 写入 MySQL + Redis
    let ret = await Business.async_WritePlayerLevelInfo(cxt, userid, currentData);
    if (ret !== 0) {
        iresp.resp.id = 0;
        iresp.resp.data = { msg: "error" };
    } else {
        // 返回写入后的最新数据
        let latestData = await new RedisTool_PlayerLevelInfo(cxt, userid).async_getData();
        iresp.resp.id = 1;
        iresp.resp.data = { msg: "ok", data: latestData };
    }
}
```

**预估增量**: ~40 行（REQ_NAME 常量 + OnInternalCall 分支）

### 5.2 cmmonthcard_xzmp.ts

**REQ_NAME 新增**：

```typescript
MIGRATION_WRITE_CARD_INFO: 'migrationWriteCardInfo',
```

**OnInternalCall 新增分支**：

```typescript
else if (req_name == REQ_NAME.MIGRATION_WRITE_CARD_INFO) {
    let reqData = req_data.data;
    let cardInfo = new interf.CMMONTHCARD_INFO();

    // 月卡
    if (reqData.monthCardInfo) {
        cardInfo.monthCardInfo = reqData.monthCardInfo as interf._CARD_INFO;
    }
    // 周卡
    if (reqData.weekCardInfo) {
        cardInfo.weekCardInfo = reqData.weekCardInfo as interf._CARD_INFO;
    }
    // 包赔
    cardInfo.redressUseTime = reqData.redressUseTime ?? 0;

    // 写入 MySQL + Redis
    let mysqlTool = new MySqlTool_CMMonthCardInfo(cxt, userid);
    let redisTool = new RedisTool_CMMonthCardInfo(cxt, userid);
    await Business.async_GeneralWriteInfo(mysqlTool, redisTool, cardInfo);

    // 返回写入后的最新数据
    let latestData = await new RedisTool_CMMonthCardInfo(cxt, userid).async_getData();
    iresp.resp.id = 1;
    iresp.resp.data = { msg: "ok", data: latestData };
}
```

**预估增量**: ~30 行

### 5.3 cmnewplayerdailygift_xzmp.ts

**REQ_NAME 新增**：

```typescript
MIGRATION_WRITE_GIFT_INFO: 'migrationWriteGiftInfo',
```

**OnInternalCall 新增分支**：

```typescript
else if (req_name == REQ_NAME.MIGRATION_WRITE_GIFT_INFO) {
    let reqData = req_data.data;
    let giftInfo = reqData.giftInfo as interf.UserData_NewPlayerDailyGiftInfo;

    // 写入 MySQL + Redis
    await Business.async_WriteGiftInfo(cxt, userid, giftInfo);

    // 返回写入后的最新数据
    let latestData = await new RedisTool_NewPlayerDailyGiftInfo(cxt, userid).async_getData();
    iresp.resp.id = 1;
    iresp.resp.data = { msg: "ok", data: latestData };
}
```

**预估增量**: ~25 行

***

## 六、迁移标记 MySQL 双写方案

迁移标记使用 CP 统一表（每游戏一张表），`name` 字段区分：

```
表名: tblcpuserdata_xzmp
字段: userid, name, data
name = 'ChunksvrMigrationFlag'
data = '{"flags": 31}'  // JSON 存储位掩码整数
```

**写入时机**：每次 `setMigrationFlags` 时，同时写入 Redis + MySQL。

**读取优先级**：Redis → MySQL → 默认值 0。

**MySQL 操作**：复用 `INSERT ... ON DUPLICATE KEY UPDATE` 模式（与 award 模块一致）：

```typescript
async function async_saveMigrationFlag(cxt, userid, flags: number) {
    let sql = `INSERT INTO tblcpuserdata_xzmp (userid, name, data)
        VALUES (${userid}, 'ChunksvrMigrationFlag', '${mysql.escape(JSON.stringify({flags}))}')
        ON DUPLICATE KEY UPDATE data = VALUES(data)`;
    await mysql.async_execute(cxt, sql);
}
```

***

## 七、迁移结果数据流

目标模块写入后**返回最新数据**给 convert 模块，convert 模块汇总所有模块结果后**一次性推送**给客户端：

```
目标模块 OnInternalCall
  → 写入 MySQL + Redis
  → RedisTool.async_getData() 读回最新数据
  → iresp.resp.data = { msg: "ok", data: latestData }

convert 模块 OnLogon
  → 收集: levelInfo / monthCardInfo / giftInfo
  → 汇总: flags + 各模块最新数据
  → modsvr.notify_client(src, cxt, "migrationResult_convert_xzmp", migrationResult)

客户端
  → 收到 migrationResult
  → 更新本地缓存: levelInfo → 更新特权面板; monthCardInfo → 更新月卡面板; giftInfo → 更新礼包面板
```

**客户端推送格式**：

```typescript
{
    flags: number,               // 当前迁移标记位掩码 (0-31)
    levelInfo: UserData_PlayerLevelInfo | null,
    monthCardInfo: CMMONTHCARD_INFO | null,
    giftInfo: UserData_NewPlayerDailyGiftInfo | null,
}
```

- `null` 表示该模块本次未迁移（已迁移或失败），客户端不变更该模块缓存
- 非 `null` 表示该模块刚迁移成功，客户端应立即更新对应模块数据

**测试优势**：所有迁移结果集中在 convert 模块的 `migrationResult` 推送中，客户端只需监听一个消息即可获取全量更新。也可通过日志查看 `flags` 和各模块数据，判断迁移是否成功及数据是否正确。

***

## 八、关键实现细节

### 8.1 积分补偿与金币迁移的顺序

1. 积分补偿（bit 3）：`async_sendGoldCoin_super(|score|)` — 抵消负积分
2. 金币迁移（bit 4）：HTTP 拉取 newdeposit → `async_sendGoldCoin_super(newdeposit)` — 发放等量积分
3. 各自独立置位，失败不置位，下次登录重试

积分补偿先行确保玩家积分归零后，金币迁移发放的积分不会与负积分冲突。

### 8.2 chunkSvr 返回空数据的处理

chunkSvr 对不存在用户返回零值/空表（不报错）。此时：
- newdeposit=0 → 发放 0 积分，置位 bit 4
- rewardstatus=[] → 空数组转换后全为 `{status:0, gotTime:0}`，置位 bit 0
- monthcard/weekcard={} → 空表，不写入月卡数据，置位 bit 1
- newplayer=0 → 未充值，置位 bit 2

### 8.3 迁移标记位更新

每次置位操作同时写入 Redis 和 MySQL。Redis 用 SET（无 TTL），MySQL 用 INSERT ON DUPLICATE KEY UPDATE。

### 8.4 rewardstatus 空表 {} 处理

Lua 空表 `{}` 在 JSON 序列化后为 `{}`（空对象）或 `[]`（空数组）。转换函数需兼容两种格式：

```typescript
function convertRewardStatus(rewardstatus: any): { status: number; gotTime: number }[] {
    let arr: number[] = [];
    if (Array.isArray(rewardstatus)) {
        arr = rewardstatus;
    } else if (typeof rewardstatus === 'object' && rewardstatus !== null) {
        // 空 {} → 全零数组
        arr = [];
    }
    // ... 后续转换
}
```

***

## 九、实现顺序建议

| 步骤 | 内容 | 依赖 |
|------|------|------|
| 1 | 创建 `convert_xzmp.jsonc` 配置文件 | 无 |
| 2 | 创建 `convert_xzmp.ts` 骨架（常量、类型、OnLogon 空壳） | 步骤 1 |
| 3 | 修改 `leveldefine_xzmp.ts` OnInternalCall | 无 |
| 4 | 修改 `cmmonthcard_xzmp.ts` OnInternalCall | 无 |
| 5 | 修改 `cmnewplayerdailygift_xzmp.ts` OnInternalCall | 无 |
| 6 | 实现 `convert_xzmp.ts` 迁移标记读写 | 步骤 2 |
| 7 | 实现 `convert_xzmp.ts` HTTP 拉取 + 数据转换 | 步骤 6 |
| 8 | 实现 `convert_xzmp.ts` 各模块迁移函数 | 步骤 7 |
| 9 | 集成测试（单玩家全流程验证） | 步骤 3-8 |
| 10 | 迁移完成后 `convert_xzmp.ts` 可删除（一次性逻辑） | 步骤 9 |

步骤 3-5 可并行开发，互不依赖。

***

*文档版本: v2.0*
*创建日期: 2026/05/18*
*更新日期: 2026/05/19*
*基于: 数据迁移.md v5.0*
