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
- 填充 CAN_RECEIVED 状态（grade ≤ reqData.grade 的 status=0 → 1）
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
| `convert_xzmp.ts` | 迁移协调脚本（OnLogon + HTTP + 数据转换 + 分发 + 标记） | ~480 |

### 2.2 修改文件

| 文件 | 改动 | 预估行数 |
|------|------|---------|
| `leveldefine_xzmp.ts` | OnInternalCall 新增 `MIGRATION_WRITE_VIP_INFO` 分支；REQ_NAME 新增常量；TestTool 新增迁移单元测试 | ~105 |
| `cmmonthcard_xzmp.ts` | OnInternalCall 新增 `MIGRATION_WRITE_CARD_INFO` 分支；REQ_NAME 新增常量；TestTool 新增迁移单元测试 | ~70 |
| `cmnewplayerdailygift_xzmp.ts` | OnInternalCall 新增 `MIGRATION_WRITE_GIFT_INFO` 分支；REQ_NAME 新增常量；TestTool 新增迁移单元测试 | ~70 |

### 总增量：~520 行

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
    // 测试工具
    TEST_MIGRATION: 'testMigration',
    TEST_CHUNKSVR_HTTP: 'testChunkSvrHttp',
    TEST_CLEAR_MIGRATION_FLAG: 'testClearMigrationFlag',
    // 跨模块查询接口（其他模块获取迁移数据用）
    QUERY_MIGRATION_VIP_DATA: 'queryMigrationVipData',
    QUERY_MIGRATION_CARD_DATA: 'queryMigrationCardData',
    QUERY_MIGRATION_GIFT_DATA: 'queryMigrationGiftData',
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
    // 填充 CAN_RECEIVED: grade ≤ reqData.grade 的 status=0 → 1
    let grade = reqData.grade ?? 0;
    let minLen = Math.min(grade + 1, currentData.oneOffRewardStatusArray.length);
    for (let i = 0; i < minLen; i++) {
        if (currentData.oneOffRewardStatusArray[i].status === 0) {
            currentData.oneOffRewardStatusArray[i].status = 1; // CAN_RECEIVED
        }
    }

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

**TestTool 新增**：

```typescript
export async function async_testMigrationWriteVipInfo(cxt, userID) {
    // 1. 调用 convert_xzmp 查询接口获取迁移数据
    let src = { client: { appcode, gameid, userid: userID }, mods: [] };
    let queryReq = { id: 0, data: { req: 'queryMigrationVipData' } };
    let queryResp = { errs: [], resp: { id: 0, data: {} } };
    await modsvr.async_internal_call(src, cxt, 'convert', queryReq, queryResp, 5);
    
    let migrationData = queryResp.resp.data;
    // 2. 用获取到的数据调用本模块 OnInternalCall
    let ireq = {
        src: { client: { appcode, userid: userID, channelkey: 'tcyan', gameid } },
        req: { id: 0, data: { req: REQ_NAME.MIGRATION_WRITE_VIP_INFO, data: migrationData } },
        info: '',
    };
    let iresp = { errs: [], resp: { id: 0, data: {} } };
    await OnInternalCall(ireq, iresp, cxt ?? null);
    // 3. 验证处理结果
    // ...
}
```

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

**TestTool 新增**：

```typescript
export async function async_testMigrationWriteCardInfo(cxt, userID) {
    // 1. 调用 convert_xzmp 查询接口获取迁移数据
    // 2. 用获取到的数据调用本模块 OnInternalCall
    // 3. 验证处理结果
}
```

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

**TestTool 新增**：

```typescript
export async function async_testMigrationWriteGiftInfo(cxt, userID) {
    // 1. 调用 convert_xzmp 查询接口获取迁移数据
    // 2. 用获取到的数据调用本模块 OnInternalCall
    // 3. 验证处理结果
}
```

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

## 九、测试架构设计

### 9.1 总体架构

```
┌──────────────────────────────────────────────────────────┐
│                   测试流程总览                              │
│                                                          │
│  目标模块 (leveldefine/cmmonthcard/cmnewplayerdailygift)    │
│    │ 1. async_internal_call → convert.QUERY_MIGRATION_*   │
│    ▼                                                     │
│  convert_xzmp (查询接口)                                    │
│    │ 2. 尝试 chunkSvr HTTP 获取真实数据                     │
│    │ 3. 不可用时返回 mock 数据                              │
│    │ 4. 返回转换后数据（即 async_internal_call 的 payload）  │
│    ▼                                                     │
│  目标模块 (TestTool)                                       │
│    │ 5. 用获取到的数据构造 ireq，调用本模块 OnInternalCall   │
│    │ 6. 验证写入结果（resp.id=1 + 字段值匹配 + 逻辑正确）   │
│    │ 7. 本地调试通过后部署到 CP 服务                        │
│    ▼                                                     │
│  本地独立运行 (ts-node) 或 CP 内触发 (server.exec())        │
└──────────────────────────────────────────────────────────┘
```

### 9.2 convert_xzmp 查询接口

convert_xzmp 通过 `OnInternalCall` 暴露以下 3 个查询接口，供目标模块获取迁移数据：

| 接口名 | 消息名 | 返回数据结构 | 说明 |
|--------|--------|-------------|------|
| VIP 数据 | `queryMigrationVipData` | `{data:{grade,totalConsumeNum,totalAcquireNum,oneOffRewardStatusArray}, source}` | leveldefine 需要用到的等级/经验/奖励状态 |
| 月卡数据 | `queryMigrationCardData` | `{data:{monthCardInfo,weekCardInfo,redressUseTime}, source}` | cmmonthcard 需要用到的月卡/周卡/包赔数据 |
| 礼包数据 | `queryMigrationGiftData` | `{data:{giftInfo,skipReason}, source}` | cmnewplayerdailygift 需要用到的签到数据，含跳过原因 |

**数据来源策略**：

```typescript
// 伪代码逻辑
async function handleQuery(cxt, userid, moduleKey) {
    let config = loadConfig();
    let data = await async_chunkSvrHttp(cxt, config, moduleKey, userid);
    if (data !== null) {
        // chunkSvr 可用 → 返回真实转换数据
        let converted = convertData(data);
        return { data: converted, source: 'chunksvr' };
    } else {
        // chunkSvr 不可用 → 返回 mock 数据
        let mockData = generateMockData(moduleKey);
        return { data: mockData, source: 'mock' };
    }
}
```

**Mock 数据规格**：

| 模块 | 字段 | mock 值 | 说明 |
|------|------|---------|------|
| VIP | grade | 3 | 假设玩家等级 3 |
| VIP | totalConsumeNum | 5000 | 累计消耗 5000 |
| VIP | totalAcquireNum | 5000 | 累计获得 5000 |
| VIP | oneOffRewardStatusArray[0] | `{status:2, gotTime:now-1d}` | 首级已领取 |
| VIP | oneOffRewardStatusArray[1-15] | `{status:0, gotTime:0}` | 其余未领取 |
| 月卡 | monthCardInfo | `{BuyTime:now, EndTime:now+31d, type:1}` | 月卡 |
| 月卡 | weekCardInfo | `{BuyTime:now, EndTime:now+7d, type:2}` | 周卡 |
| 月卡 | redressUseTime | 20260518 | 上次包赔日期 |
| 礼包 | giftInfo | `{buyTime:now-2d, lastClaimDay:3, lastClaimDate:20260518}` | 已签到 3 天，未过期 |

### 9.3 目标模块测试流程

**步骤 1：调用 convert_xzmp 查询接口**

目标模块通过 `CommonFuncs.async_internal_call` 或 `modsvr.async_internal_call` 向 convert 模块发送查询消息：

```typescript
let src = {
    client: { appcode: 'xzmp', gameid: 283, userid: testUserID },
    mods: [],
};
let queryReq = {
    id: 0,
    data: { req: 'queryMigrationVipData' },
};
let queryResp = { errs: [], resp: { id: 0, data: {} } };
await modsvr.async_internal_call(src, cxt, 'convert', queryReq, queryResp, 5);

let migrationData = queryResp.resp.data;
// migrationData = { data: { grade, totalConsumeNum, ... }, source: 'chunksvr'|'mock' }
```

**步骤 2：用获取的数据构造 ireq 并调用 OnInternalCall**

```typescript
let ireq = {
    src: { client: { appcode, userid: testUserID, channelkey: 'tcyan', gameid } },
    req: { id: 0, data: { req: REQ_NAME.MIGRATION_WRITE_VIP_INFO, data: migrationData.data } },
    info: '',
};
let iresp = { errs: [], resp: { id: 0, data: {} } };
await OnInternalCall(ireq, iresp, cxt ?? null);
```

**步骤 3：验证处理结果**

验证内容：
- `iresp.resp.id === 1`：写入成功
- `iresp.resp.data.data` 中各字段值正确
- CAN_RECEIVED 填充逻辑正确（VIP 模块特有）
- `source` 字段区分数据来源（方便 debug）

### 9.4 本地调试流程

```
开发环境 (本地 PC)
  │
  ├── 可能没有 chunkSvr → mock 数据降级
  ├── 可能没有 Redis/MySQL → OnInternalCall 用 null context
  │
  ├── 1. cd cpscript/src/xzmp
  ├── 2. 修改测试 userID
  ├── 3. 运行: npx ts-node leveldefine_xzmp.ts
  │      （测试函数通过 main() 入口调用）
  │
  ├── 4. 观察日志输出 PASS/FAIL
  ├── 5. 修复问题 → 重复 3-4
  │
  └── 6. 本地通过后 → 部署到 CP 服务
       （在 CP 服务中验证真实 chunkSvr 数据）
```

**注意事项**：

1. 本地 debug 时 `cxt = null`，Redis/MySQL 操作使用 `null context`。CP 服务的 C++ 绑定在 `cxt = null` 时使用默认上下文，不影响基本读写测试。
2. 目标模块的测试函数不依赖 convert_xzmp 的集成测试结果，可以独立运行。
3. `source` 字段帮助区分当前测试使用的是真实数据还是 mock 数据。
4. 所有测试函数均放在各模块的 `TestTool` namespace 中，通过 `main()` 入口或 `OnInternalCall` 触发。

### 9.5 测试独立性保证

| 模块 | 测试函数 | 依赖 |
|------|----------|------|
| convert_xzmp | `async_testMigration` | chunkSvr HTTP (不可用则跳过) |
| convert_xzmp | `async_testChunkSvrHttp` | chunkSvr HTTP (不可用则跳过) |
| convert_xzmp | `async_testOnLogon` | chunkSvr HTTP |
| convert_xzmp | `async_clearMigrationFlag` | Redis |
| **leveldefine** | **`async_testMigrationWriteVipInfo`** | **convert_xzmp (查询接口) — 不可用时 mock 降级** |
| **cmmonthcard** | **`async_testMigrationWriteCardInfo`** | **convert_xzmp (查询接口) — 不可用时 mock 降级** |
| **cmnewplayerdailygift** | **`async_testMigrationWriteGiftInfo`** | **convert_xzmp (查询接口) — 不可用时 mock 降级** |

每个目标模块的测试先通过 `async_internal_call` 尝试从 convert_xzmp 获取数据。如果 convert_xzmp 不可达或无法提供数据，则使用本地的 mock 数据作为降级方案，确保测试在任何环境下都能运行。

***

*文档版本: v2.1*
*创建日期: 2026/05/18*
*更新日期: 2026/05/19*
*基于: 数据迁移.md v5.0*
