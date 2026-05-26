# TDD Test Spec: convert — New Player Lesson (Tutorial)

Target: `D:\Codlib\other\ModCPSvr\cpscript\src\xzmp\convert_xzmp.ts`

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

**Test A1** — `TQNEWPLAYERLESSON === 0x20`
**Test A2** — `ALL_DONE === 0x3F` (all 6 bits combined)
**Test A3** — bit 5 does not overlap any existing bit

---

## 2. MigrationResult Interface

Extend:

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

**Test A4** — default response omits `newPlayerLesson` when nBout = 0 and bit not set
**Test A5** — response includes `newPlayerLesson` with `{ isCompleted: true, rewardGold: N }` when bit is set

---

## 3. OnGameResult — Tutorial Completion Detection

Currently: `function OnGameResult(mgr: modsvr.multi_gameresult, cxt: modsvr.context): void { }`

**Requirement:** After each game result, detect if the player completed tutorial.

```typescript
async function OnGameResult(mgr: modsvr.multi_gameresult, cxt: modsvr.context): Promise<void> {
    let config = CommonFuncs.loadConfig();
    if (config.isenable == 0) return;

    let userid = mgr.base.userid;
    let flags = await CommonFuncs.async_getMigrationFlags(cxt, userid);
    if (flags & MIGRATION_BIT.TQNEWPLAYERLESSON) return;     // already completed
    if (flags & MIGRATION_BIT.ALL_DONE) return;

    let bout = mgr.usergameresult?.bout ?? 0;
    if (bout < 1) return;                                     // still 0 bouts, not a real game

    // nBout > 0 → player just finished a real game session
    // → mark tutorial as completed (they no longer need tutorial)
    await processTutorialCompletion(src, cxt, userid, flags);
}
```

**Test B1** — nBout = 0 after game result → no action, bit unchanged
**Test B2** — nBout > 0 AND bit already set → no action (early return)
**Test B3** — nBout > 0 AND bit NOT set → call `processTutorialCompletion`, bit set to 1
**Test B4** — `ALL_DONE` already set → early return, no-op
**Test B5** — config.isenable = 0 → early return, no-op

---

## 4. processTutorialCompletion Logic

```typescript
async function processTutorialCompletion(
    src: modsvr.source, cxt: modsvr.context, userid: number, flags: number
): Promise<void> {
    // 1. Send reward
    let config = CommonFuncs.loadConfig();
    let rewardGold = config.newPlayerLessonReward ?? 0;
    let rewardSuccess = false;
    if (rewardGold > 0) {
        rewardSuccess = await Business.async_sendGoldCoin_super(src, cxt, userid, rewardGold);
    }

    // 2. Set bit
    let newFlags = flags | MIGRATION_BIT.TQNEWPLAYERLESSON;
    await CommonFuncs.async_setMigrationFlags(cxt, userid, newFlags);

    // 3. Push to client
    // Need src from OnGameResult context — challenge here is that
    // OnGameResult doesn't provide src directly like OnLogon does
    // Resolution: push through client notification or handle in OnLogon
}
```

**Test C1** — rewardGold > 0 → `async_sendGoldCoin_super` called with correct amount
**Test C2** — rewardGold = 0 → skip reward, still mark bit
**Test C3** — reward fails (async_sendGoldCoin_super returns false) → bit still set (graceful degradation)
**Test C4** — bit flag written to persistence (`async_setMigrationFlags` called with OR'd bit)

### Challenge: src in OnGameResult

`OnGameResult` receives `mgr: modsvr.multi_gameresult` — does it contain `src`? 
If not, alternative approaches:

- **Option 1**: Defer notification to next `OnLogon` (OnLogon already checks bits and pushes)
- **Option 2**: Store completion in DB, `OnLogon` reads it and pushes to client
- **Option 3**: Use `modsvr` notification to client if src is derivable

**Recommendation: Option 1 + 2.** In `processTutorialCompletion`, only write the bit + reward. Do NOT push from OnGameResult. The next OnLogon will detect the bit, skip the tutorial path, and push the updated `newPlayerLesson` in the migration result.

**Test C5** — after `processTutorialCompletion`, next OnLogon returns `newPlayerLesson: { isCompleted: true, rewardGold: N }`

---

## 5. OnLogon — Extended for Tutorial

Current OnLogon flow (line 125-204). Insert after gold coin migration (after line 172):

```typescript
// 5. tutorial (bit 5) — check bout, auto-mark old players
if ((flags & MIGRATION_BIT.TQNEWPLAYERLESSON) === 0) {
    let bout = (logon as any).usergameinfo?.bout ?? 0;
    if (bout > 0) {
        // Player already has game records → auto-mark as completed
        // Optionally send reward for very first-time migration catch
        flags = flags | MIGRATION_BIT.TQNEWPLAYERLESSON;
    }
}
```

**Test D1** — nBout = 0, bit not set → bit unchanged (player is new, needs tutorial)
**Test D2** — nBout > 0, bit not set → bit set to 1 (auto-mark old/played player)
**Test D3** — nBout > 0, bit already set → bit unchanged (idempotent)
**Test D4** — bit set in flags variable, participated in the final `async_setMigrationFlags` write (line 197-199)

### Notification to Client in OnLogon

After the final flags write (line 197-199), extend `result` before pushing:

```typescript
// After line 199, before line 202-203:
result.newPlayerLesson = {
    isCompleted: (flags & MIGRATION_BIT.TQNEWPLAYERLESSON) !== 0,
    rewardGold: config.newPlayerLessonReward ?? 0,
};
```

**Test D5** — when bit set, `result.newPlayerLesson.isCompleted === true`
**Test D6** — when bit not set, `result.newPlayerLesson.isCompleted === false`
**Test D7** — `result.newPlayerLesson.rewardGold === config.newPlayerLessonReward`

---

## 6. Config — newPlayerLessonReward

In `convert_xzmp.jsonc`, add config field:

```jsonc
{
    "isenable": 1,
    "guid": "convert_xzmp",
    // ... existing fields ...
    "newPlayerLessonReward": 100000   // NEW: gold coins rewarded on tutorial completion
}
```

**Test E1** — config parses `newPlayerLessonReward` correctly
**Test E2** — missing field defaults to 0 (no reward)

---

## 7. Full Integration Scenarios

### Scenario 1: Truly New Player

1. Player with nBout=0, no tutorial bit → logs in
2. OnLogon runs: bit not set, bout=0 → bit stays 0
3. OnLogon pushes `{ flags: 0, ... }` (no newPlayerLesson field, or with isCompleted=false)
4. Client knows: player needs tutorial
5. → **Pass**

### Scenario 2: Tutorial Complete (New Player Plays First Game)

1. Player with nBout=0 enters tutorial (singleplayer room)
2. Tutorial plays out, game ends
3. nBout becomes 1 (game server records it)
4. OnGameResult fires: bout=1, bit not set
5. processTutorialCompletion: send reward 100000, set bit 5
6. Player logs in next time:
7. OnLogon: bit already set → skip tutorial
8. OnLogon pushes `{ newPlayerLesson: { isCompleted: true, rewardGold: 100000 } }`
9. → **Pass**

### Scenario 3: Legacy Player (Already Played Before Tutorial Feature)

1. Player with nBout=50, no tutorial bit → logs in
2. OnLogon runs: bit not set, bout=50 > 0
3. Auto-mark: bit set to 1 (no reward — they already have their gold)
4. OnLogon pushes `{ newPlayerLesson: { isCompleted: true, rewardGold: 0 } }`
5. → **Pass**

### Scenario 4: Player Crashes Mid-Tutorial

1. Player with nBout=0, bit not set → enters tutorial
2. Killed at stage 5 of 14 (game not finished, no game result)
3. nBout still 0
4. OnGameResult never fires
5. Player logs in again:
6. OnLogon: bout=0, bit not set → bit unchanged
7. Client gets isCompleted=false
8. Tutorial re-enters from beginning
9. → **Pass**

### Scenario 5: Player Crashes Right After Game Ends But Before Reward

1. Player finishes tutorial → game result written → nBout becomes 1
2. OnGameResult: bout=1, bit not set → processTutorialCompletion called
3. Reward sent successfully → bit written to DB
4. Client crashes before receiving notification
5. Player logs in again:
6. OnLogon: bit already set → skip
7. Client gets isCompleted=true
8. → **Pass**

### Scenario 6: Config Disables Tutorial

1. `config.newPlayerLessonReward = 0` or feature flag off
2. OnLogon/OnGameResult: path skipped
3. → **Pass**
