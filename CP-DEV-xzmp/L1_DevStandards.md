# L1 开发规范

> CP 脚本开发必须遵守的编码规则、回调模式、数据规范和测试规范。

---

## 1. 编码规则

### 1.1 禁止数组高级函数式方法

禁止使用 `filter`、`map`、`reduce`、`forEach`、`find`、`some`、`every` 等，一律使用 `for` 循环。

```typescript
// ✗ 禁止
let result = arr.filter(x => x > 0).map(x => x * 2);

// ✓ 正确
let result = [];
for (let i = 0; i < arr.length; i++) {
    if (arr[i] > 0) {
        result.push(arr[i] * 2);
    }
}
```

### 1.2 异步函数标记

- 自定义异步函数必须使用 `async_` 前缀，调用时必须加 `await`
- CP 脚本回调**无需**加 `async_` 前缀：`OnScriptReload`、`OnClientRequest`、`OnInternalCall`、`OnGameRequest`、`OnGameResult`、`OnSubGameResult`、`OnPayResult`、`OnCurrencyExchange`、`OnLogon`、`OnDistributedTimer`

```typescript
// ✓ 自定义异步函数
export async function async_QueryXxxInfo(cxt, userid) { ... }
let data = await async_QueryXxxInfo(cxt, userid);

// ✓ CP 回调不加 async_ 前缀
function OnPayResult(src, cxt, payinfoflag, exchangeid, rmb, orderid, paytime) { ... }
function OnClientRequest(src, cxt, creq, cresp) { ... }
```

### 1.3 模块独立性

- 每个礼包脚本独立，不依赖其他礼包脚本
- 公用功能放置在 `predefine` 目录
- 跨模块数据访问必须通过 `async_internal_call`，禁止直接读写其他模块的数据库

### 1.4 import 限制

CP 服务不支持分文件编写代码，import 是通过文本替换实现的。所有代码最终合并到单文件执行。

---

## 2. 数据存储规范

### 2.1 MySQL

- 表名格式：`tblcpuserdata_{MODULE_NAME}_{GAME_CODE}`
- 行定位：`userid` + `name` 字段
- 数据字段：`data`（TEXT，JSON 格式）
- 允许读任意表，**禁止写其他 gameid 的表**
- 数据库操作通过封装结构 `MySqlTool`、`RedisTool` 完成；如需操作其他模块的数据库，封装为 `MySqlTool_Xxx_Other`、`RedisTool_Xxx_Other`

### 2.2 Redis

- Key 格式：`mod(cp):name({MODULE_NAME}):appcode({APP_CODE}):uid({uid}):{FUNC_INFO}`
- 过期时间：默认 7 天，总数量不为常数的 key **必须**携带过期时间
- 允许读任意 key，**禁止写其他 gameid 的 key**

### 2.3 双写模式

查询：Redis 优先，miss 则查 MySQL 并回写 Redis。

```typescript
async function async_QueryXxxInfo(cxt, userid) {
    let redisTool = new RedisTool_XxxInfo(cxt, userid);
    let res = await redisTool.async_getData();
    if (!isEmpty_DBRes(res)) return res;

    let mysqlTool = new MySqlTool_XxxInfo(cxt, userid);
    res = await mysqlTool.async_query();
    if (isEmpty_DBRes(res)) {
        res = new DefaultData();
        await mysqlTool.async_safeSave(res);
    }
    await redisTool.async_setData(res);
    return res;
}
```

写入：MySQL + Redis 双写。

```typescript
async function async_WriteXxxInfo(cxt, userid, data) {
    let mysqlTool = new MySqlTool_XxxInfo(cxt, userid);
    await mysqlTool.async_safeSave(data);
    let redisTool = new RedisTool_XxxInfo(cxt, userid);
    await redisTool.async_setData(data);
}
```

---

## 3. 回调模式

### 3.1 OnPayResult — 支付成功回调

典型流程：过滤立即兑换消息 → 匹配 exchangeid → 防重复 → 发奖 → 更新数据库 → 通知客户端。

```typescript
function OnPayResult(src, cxt, payinfoflag, exchangeid, rmb, orderid, paytime) {
    // 1. 过滤立即兑换（payinfoflag == 0 为立即兑换，非实际支付）
    if (payinfoflag == 0) return;

    // 2. 匹配本模块的兑换商品ID
    let cfg = loadConfig();
    if (cfg.exchangeid != exchangeid) return;

    // 3. 获取玩家数据，防重复
    let data = await Business.async_QueryXxxInfo(cxt, src.client.userid);
    if (data.hasPurchased) return;

    // 4. 发放奖励
    let rewardResult = await async_send_reward(src, cxt, src.client.userid,
        cfg.propID, cfg.reward, cfg.guid);
    if (rewardResult != modsvr.E_ERROR.SUCCESS) {
        return;
    }

    // 5. 更新玩家数据
    data.hasPurchased = true;
    data.buyTime = Math.floor(Date.now() / 1000);
    await Business.async_WriteXxxInfo(cxt, src.client.userid, data);

    // 6. 通知客户端
    let giftInfo = buildToClientGiftInfo(data, cfg);
    CommonFuncs.notifyClient(src, cxt, src.client.userid,
        CONST_VAR.ON_PURCHASED, { giftInfo, reward: cfg.reward });
}
```

关键点：
- `payinfoflag == 0` 必须过滤，否则会重复处理
- `exchangeid` 用于匹配本模块的商品，不匹配则忽略
- 防重复检查必须在发奖之前
- 发奖失败不应更新数据库状态

### 3.2 OnClientRequest — 客户端请求处理

典型流程：从 creq 获取玩家信息和请求名 → 分支处理 → 设置 cresp 响应。

```typescript
function OnClientRequest(src, cxt, creq, cresp) {
    let userid = src.client.userid;
    let reqName = creq.req;
    let reqData = creq.data || {};

    if (reqName == CONST_VAR.QUERY_CONFIG) {
        let cfg = loadConfig();
        if (!cfg || cfg.isenable == 0) {
            cresp.resp = JSON.stringify({ error: "礼包未启用" });
            return;
        }
        let data = await Business.async_QueryXxxInfo(cxt, userid);
        let playerInfo = buildToClientPlayerInfo(data, cfg);
        cresp.resp = JSON.stringify({ cfg, playerInfo });

    } else if (reqName == CONST_VAR.CLAIM_REWARD) {
        let cfg = loadConfig();
        let data = await Business.async_QueryXxxInfo(cxt, userid);

        let checkResult = checkCanClaim(data, cfg);
        if (checkResult.error) {
            cresp.resp = JSON.stringify({ error: checkResult.error });
            return;
        }

        let rewardResult = await async_send_reward(src, cxt, userid,
            cfg.propID, cfg.reward, cfg.guid);
        if (rewardResult != modsvr.E_ERROR.SUCCESS) {
            cresp.resp = JSON.stringify({ error: "发放奖励失败" });
            return;
        }
        updateClaimState(data);
        await Business.async_WriteXxxInfo(cxt, userid, data);

        let playerInfo = buildToClientPlayerInfo(data, cfg);
        cresp.resp = JSON.stringify({ rewardDay: data.lastClaimDay, reward: cfg.reward, playerInfo });

    } else {
        cresp.resp = JSON.stringify({ error: "未知请求" });
    }
}
```

关键点：
- `creq.req` 为消息名，`creq.data` 为请求数据
- `cresp.resp` 必须赋值为 `JSON.stringify(...)` 的字符串
- 业务校验失败直接返回错误，不执行写操作

---

## 4. 大额金币分批发奖

超过 20 亿金币时必须分批发奖，该函数在模块脚本中自行实现（非 modsvr 提供）。

```typescript
export async function async_sendGoldCoin_super(src, cxt, userid, goldCoinNum: number, guid: string) {
    const twoBillion = 2000000000;
    let count = Math.floor(goldCoinNum / twoBillion);
    let finalCount = goldCoinNum % twoBillion;
    for (let i = 0; i <= count; i++) {
        let rewardCount = (i == count) ? finalCount : twoBillion;
        if (rewardCount <= 0) continue;
        await async_send_reward(src, cxt, userid, 21770, rewardCount, guid);
    }
}
```

- 道具ID `21770` 为金币道具
- 分批上限 2,000,000,000（20 亿）
- 最后一批为余数，可能小于 20 亿

---

## 5. 测试编写规范

### 5.1 基本结构

测试代码放在 `namespace TestTool` 中，入口为 `async function main()`，调用 `async_execAllTest()`。

```typescript
namespace TestTool {
    const testResults: { name: string; passed: boolean; detail?: string }[] = [];

    function assertEqual(testName: string, expected: any, actual: any) {
        let passed = (expected === actual);
        testResults.push({
            name: testName,
            passed,
            detail: passed ? "" : `期望: ${expected}, 实际: ${actual}`
        });
    }

    function printResults() {
        let passCount = 0;
        let failCount = 0;
        for (let i = 0; i < testResults.length; i++) {
            let r = testResults[i];
            if (r.passed) {
                passCount++;
                console.log(`  PASS: ${r.name}`);
            } else {
                failCount++;
                console.log(`  FAIL: ${r.name} — ${r.detail}`);
            }
        }
        console.log(`\n结果: ${passCount} passed, ${failCount} failed, ${testResults.length} total`);
    }

    function makeSrc(userid: number) {
        return {
            client: { appcode: CONST_VAR.APP_CODE, gameid: CONST_VAR.GAME_ID, userid },
            mods: []
        };
    }

    async function test_queryConfig() {
        let src = makeSrc(10001);
        let creq = { req: CONST_VAR.QUERY_CONFIG, data: {} };
        let cresp = { resp: "" };
        OnClientRequest(src, null, creq, cresp);

        let result = JSON.parse(cresp.resp);
        assertEqual("queryConfig 返回配置", true, result.cfg != null);
        assertEqual("queryConfig 返回玩家信息", true, result.playerInfo != null);
    }

    async function test_onPayResult() {
        let src = makeSrc(10001);
        let cfg = loadConfig();
        OnPayResult(src, null, 1, cfg.exchangeid, 600, "order_001", Date.now());

        let data = await Business.async_QueryXxxInfo(null, 10001);
        assertEqual("支付后已购买", true, data.hasPurchased);
    }

    export async function async_execAllTest() {
        console.log("===== TestTool 开始 =====");
        await test_queryConfig();
        await test_onPayResult();
        printResults();
        console.log("===== TestTool 结束 =====");
    }
}

export async function main() {
    await TestTool.async_execAllTest();
}
```

### 5.2 编写要点

1. **模拟客户端请求**：构造 `src`（含 userid）、`creq`（含 req/data）、`cresp`（空 resp），直接调用 `OnClientRequest`
2. **模拟支付回调**：构造 `src` + 支付参数，直接调用 `OnPayResult`
3. **伪造数据**：不便修改的数据（如其他模块数据）可绕过正常流程，直接构造测试所需的中间状态
4. **断言方式**：`assertEqual(testName, expected, actual)` 记录每个用例的期望与实际结果
5. **不中断执行**：遇到失败用例仅记录，继续执行后续用例
6. **结果汇总**：所有用例执行完毕后，统一打印 PASSED/FAILED 及汇总统计
