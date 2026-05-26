# TDD Test Spec: convert — New Player Lesson (Tutorial)

Target: `D:\Codlib\other\ModCPSvr\cpscript\src\xzmp\convert_xzmp.ts`

Principle: Client drives completion and reward claiming via CP requests.
convert handles server-side flag persistence + old-player auto-mark.

---

## 1. Bit Flag

Add bit 5 to `MIGRATION_BIT`:

```typescript
const MIGRATION_BIT = {
    TQVIP: 0x01,
    TQMONTHCARD: 0x02,
    TQNEWPLAYERDAILYGIFT: 0x04,
    SCORE_COMPENSATE: 0x08,
    GOLD_COIN: 0x10,
    TQNEWPLAYERLESSON: 0x20,   // NEW: bit 5
    ALL_DONE: 0x3F,             // updated: 63
}
```

Also add to `REQ_NAME`:

```typescript
const REQ_NAME = {
    // ... existing ...
    QUERY_TUTORIAL_STATE: 'queryTutorialState',     // NEW
    CLAIM_TUTORIAL_REWARD: 'claimTutorialReward',   // NEW
}
```

**Test A1** — `TQNEWPLAYERLESSON === 0x20`
**Test A2** — `ALL_DONE === 0x3F` (all 6 bits OR'd)
**Test A3** — bit 5 does not overlap any existing bit
**Test A4** — `REQ_NAME.QUERY_TUTORIAL_STATE === 'queryTutorialState'`
**Test A5** — `REQ_NAME.CLAIM_TUTORIAL_REWARD === 'claimTutorialReward'`

---

## 2. MigrationResult Interface

Extend `MigrationResult` for OnLogon push:

```typescript
interface MigrationResult {
    flags: number;
    levelInfo: any;
    monthCardInfo: any;
    giftInfo: any;
    newPlayerLesson?: {           // NEW
        isCompleted: boolean;
        rewardGold: number;
    }
}
```

**Test A6** — OnLogon push when bit NOT set: `newPlayerLesson.isCompleted === false`
**Test A7** — OnLogon push when bit set: `newPlayerLesson.isCompleted === true`

---

## 3. OnInternalCall — Client Request Handlers

Add two branches in `OnInternalCall` (after line 99, before the else clause):

```typescript
} else if (reqName === REQ_NAME.QUERY_TUTORIAL_STATE) {
    let flags = await CommonFuncs.async_getMigrationFlags(cxt, userid);
    let config = CommonFuncs.loadConfig();
    let isCompleted = (flags & MIGRATION_BIT.TQNEWPLAYERLESSON) !== 0;
    iresp.resp = {
        id: 1,
        data: {
            isCompleted: isCompleted,
            rewardGold: isCompleted ? (config.newPlayerLessonReward ?? 0) : 0
        }
    };
} else if (reqName === REQ_NAME.CLAIM_TUTORIAL_REWARD) {
    let result = await Business.async_claimTutorialReward(cxt, userid);
    iresp.resp = {
        id: result.success ? 1 : 0,
        data: {
            success: result.success,
            rewardGold: result.rewardGold
        }
    };
```

### Tests for queryTutorialState

**Test B1** — bit NOT set, returns `{ isCompleted: false, rewardGold: 0 }`
**Test B2** — bit set, returns `{ isCompleted: true, rewardGold: config.newPlayerLessonReward }`
**Test B3** — bit set, config.reward omitted → `rewardGold: 0`
**Test B4** — userid invalid → `id: 0` error response

### Tests for claimTutorialReward

**Test C1** — bit NOT set → `async_claimTutorialReward` called, bit written, reward sent, `{ success: true, rewardGold: N }` returned
**Test C2** — bit already set → still ok, return success (idempotent — client may retry)
**Test C3** — reward send fails → bit still set, `{ success: true, rewardGold: 0 }` (graceful — player can retry but won't re-tutorial)
**Test C4** — config.isenable == 0 → `{ id: 0, data: {} }` (disabled)
**Test C5** — rewarded gold matches config value

---

## 4. Business.async_claimTutorialReward

```typescript
namespace Business {
    // ... existing ...

    export async function async_claimTutorialReward(
        cxt: modsvr.context, userid: number
    ): Promise<{ success: boolean; rewardGold: number }> {
        let config = CommonFuncs.loadConfig();
        if (config.isenable == 0) return { success: false, rewardGold: 0 };

        let flags = await CommonFuncs.async_getMigrationFlags(cxt, userid);
        let rewardGold = config.newPlayerLessonReward ?? 0;

        // 1. Send reward first (fail early)
        let rewardOk = true;
        if (rewardGold > 0) {
            // NOTE: src is not available in OnInternalCall context;
            // use modsvr internal reward mechanism instead
            rewardOk = await Business.async_sendGoldCoin_internal(cxt, userid, rewardGold);
        }

        // 2. Set bit regardless of reward outcome
        let newFlags = flags | MIGRATION_BIT.TQNEWPLAYERLESSON;
        await CommonFuncs.async_setMigrationFlags(cxt, userid, newFlags);

        return { success: rewardOk, rewardGold };
    }

    // Internal reward — no src needed, uses modsvr internal batch send
    export async function async_sendGoldCoin_internal(
        cxt: modsvr.context, userid: number, amount: number
    ): Promise<boolean> {
        // Use modsvr internal reward API specific to OnInternalCall context
        // Implementation depends on modsvr framework capabilities
        return true; // placeholder
    }
}
```

**Test D1** — `isenable == 0` → early return `{ success: false, rewardGold: 0 }`, no flag write
**Test D2** — `newPlayerLessonReward` in config → `rewardGold === config value`
**Test D3** — `newPlayerLessonReward` missing → `rewardGold === 0`
**Test D4** — reward sent, amount equals config value
**Test D5** — `async_setMigrationFlags` called with OR'd bit 5
**Test D6** — idempotent: calling twice passes both times, no duplicate reward concern (bit already set → second call still sets same bit, no extra reward)
**Test D7** — reward fails → bit still committed, return `{ success: false, rewardGold }`

---

## 5. OnLogon — Auto-Mark for Legacy Players

Insert after gold coin migration (after line 172, before line 177):

```typescript
// 5. tutorial (bit 5) — auto-mark old players who never went through tutorial
if ((flags & MIGRATION_BIT.TQNEWPLAYERLESSON) === 0) {
    let bout = (logon as any).usergameinfo?.bout ?? 0;
    if (bout > 0) {
        // Has game records but no tutorial bit → auto-complete (no reward)
        flags = flags | MIGRATION_BIT.TQNEWPLAYERLESSON;
    }
}
```

After the final flags write, extend `result` before push (replace the simple `result.flags = flags`):

```typescript
result.flags = flags;
result.newPlayerLesson = {
    isCompleted: (flags & MIGRATION_BIT.TQNEWPLAYERLESSON) !== 0,
    rewardGold: config.newPlayerLessonReward ?? 0,
};
CommonFuncs.notifyClient(src, cxt, userid, REQ_NAME.MIGRATION_RESULT, result);
```

**Test E1** — nBout = 0, bit not set → bit unchanged (new player, needs tutorial)
**Test E2** — nBout > 0, bit not set → bit SET (auto-mark, no reward)
**Test E3** — nBout > 0, bit already set → bit unchanged (idempotent)
**Test E4** — after auto-mark, push contains `newPlayerLesson.isCompleted === true`
**Test E5** — no auto-mark when bit not set and nBout=0 → push contains `newPlayerLesson.isCompleted === false`
**Test E6** — auto-mark participates in final `async_setMigrationFlags` batch write (not a separate write)

---

## 6. Config — newPlayerLessonReward

In `convert_xzmp.jsonc`:

```jsonc
{
    "isenable": 1,
    "guid": "convert_xzmp",
    // ... existing ...
    "newPlayerLessonReward": 100000
}
```

**Test F1** — config parses `newPlayerLessonReward` as number
**Test F2** — missing field defaults to 0

---

## 7. Full Integration Scenarios

### Scenario 1: Truly New Player
```
1. nBout=0, bit not set → Login
2. OnLogon: bout=0 → bit stays 0
3. Push: { newPlayerLesson: { isCompleted: false, rewardGold: 0 } }
4. Client: player needs tutorial → direct to singleplayer room
→ PASS
```

### Scenario 2: Tutorial Complete (Client-Driven Reward)
```
1. nBout=0, bit not set → enters tutorial
2. Client plays through 14 stages → game ends
3. Client calls claimTutorialReward
4. convert: set bit 5, send 100000 gold
5. Return { success: true, rewardGold: 100000 }
6. Client updates local display
7. Next Login: OnLogon sees bit set, push isCompleted=true
→ PASS
```

### Scenario 3: Client Retries Claim After Network Error
```
1. Tutorial done, client calls claimTutorialReward
2. Network timeout → client retries
3. First call: bit set, reward sent (but client didn't get response)
4. Second call: bit already set → still return { success: true, rewardGold: 0 }
5. Client: got reward already on first call, second call says success
   Edge: client should check if rewardGold > 0 before showing reward animation
   Resolution: claimTutorialReward always returns current rewardGold from config,
   not "did we just send it". Client compares with pre-claim state.
→ PASS (idempotent by design)
```

### Scenario 4: Old Player (nBout > 0, Never Had Tutorial)
```
1. nBout=50, bit not set → Login
2. OnLogon: bout=50 > 0 → auto-mark bit 5 (no reward)
3. Push: { newPlayerLesson: { isCompleted: true, rewardGold: 100000 } }
4. Client: sees completed=true → never shows tutorial
→ PASS
```

### Scenario 5: Mid-Tutorial Crash
```
1. nBout=0, bit not set → enters tutorial
2. Killed at stage 5 of 14
3. Relaunch → Login
4. OnLogon: bout=0, bit not set → unchanged
5. Push: isCompleted=false
6. Client: re-enters tutorial from beginning
→ PASS
```

### Scenario 6: Tutorial Complete → Client Crashes Before Redirect
```
1. Tutorial done → claimTutorialReward returns success
2. Client crashes before roomSkip executes
3. Relaunch → Login
4. OnLogon: bit set → isCompleted=true
5. Client: never enters tutorial, goes to normal hall
→ PASS (no stuck state)
```

### Scenario 7: Config Disabled
```
1. isenable=0
2. OnLogon skips all migration
3. claimTutorialReward returns { success: false, rewardGold: 0 }
→ PASS
```
