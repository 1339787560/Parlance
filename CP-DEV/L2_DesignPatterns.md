---
name: cpscript-design-patterns
description: 描述 cpscript 项目的核心设计模式、数据存储规范和模块通信约定
---

# cpscript 服务脚本设计模式与规范

## 项目定位

cpscript 是游戏 CP 服务脚本目录，每个脚本文件对应一个独立的功能模块（如等级系统、月卡、复活礼包等）。

## 核心设计模式

### 1. 模块常量定义（CONST_VAR）

每个模块顶义定义模块基本信息：

```typescript
const CONST_VAR = {
    MODULE_NAME: 'leveldefine',      // 模块名，用于配置加载和内部调用
    LEVEL_CONFIG_NAME: 'leveldefine', // 依赖的其他模块名（可选）

    // 数据存储相关的都用 GAME_CODE
    GAME_CODE: 'xzmp',
    // 配置相关的都用 APP_CODE
    APP_CODE: 'xzmp',
    GAME_ID: 283,
    DAY_SECONDS: 86400,
}
```

**规则：**
- `GAME_CODE` 用于数据库表名、Redis Key 的构造
- `APP_CODE` 用于配置文件名的构造
- 两者通常相同，但语义不同

### 2. 消息名称常量（REQ_NAME）

集中管理所有本模块使用的消息名：

```typescript
const REQ_NAME = {
    // From Client
    QUERY_CONFIG: 'queryLevelDefineConfig',
    // to Module（其他模块可调用）
    UPDATE_REDIS: 'updateRedisPlayerLevelInfo',
    // from Module（接收其他模块调用）
    FORCE_UPDATE_CONFIG: 'forceUpdateLevelConfig',
    // to Client
    NOTIFY_LEVEL_CHANGE: 'notifyPlayerLevelChange',
}
```

### 3. 数据工具类模式

每个模块通常有两类工具：**自管理工具** 和 **跨模块工具**。

#### MySQL 工具类（以玩家为单位存储 JSON）

```typescript
class MySqlTool_PlayerLevelInfo {
    MYSQL_TABLE_NAME = `tblcpuserdata_${CONST_VAR.MODULE_NAME}_${CONST_VAR.GAME_CODE}`;
    MT_Field_PlayerInfo = "PlayerLevelInfo";  // name 字段值

    protected mdata: interf.MySqlData = null;
    protected uid = 0;
    protected isExist: boolean = false;

    async async_query(name?: string): Promise<Object> {
        // 查询逻辑，MySQL 一行存储一个玩家的 JSON
        // 通过 userid + name 字段定位数据
    }

    updateData(data: Object) { this.mdata = data; }

    async async_save(): Promise<boolean> {
        // INSERT 或 UPDATE（根据 isExist）
        // 使用 mysql.escape() 防止 SQL 注入
    }

    async async_safeSave(data: Object) {
        // query -> updateData -> save 的标准流程
        await this.async_query();
        this.updateData(data);
        await this.async_save();
    }
}
```

**MySQL 表结构：**
```sql
CREATE TABLE tblcpuserdata_${MODULE_NAME}_${GAME_CODE} (
    userid BIGINT,
    name VARCHAR(64),   -- 区分同一表中的不同数据结构
    data TEXT,         -- JSON 存储
    PRIMARY KEY (userid, name)
);
```

#### Redis 工具类

```typescript
class RedisTool_PlayerLevelInfo {
    ONE_DAY_SECONDS = 86400;
    MAX_REDIS_EXPIRE = this.ONE_DAY_SECONDS * 7;  // 缓存 7 天

    // Key 格式
    get key(): string {
        return `mod(cp):name(${CONST_VAR.MODULE_NAME}):appcode(${CONST_VAR.APP_CODE}):uid(${this.uid}):${this.FUNC_INFO}`;
    }

    get lockKey(): string {
        return `mod(cp):name(${CONST_VAR.MODULE_NAME}):appcode(${CONST_VAR.APP_CODE}):uid(${this.uid}):lock`;
    }

    // 分布式锁模式
    async async_redis_lock_key(key: string, cb: Function, ttl?: number) {
        const sleep_arr = [50, 100, 300, 500, 1000];  // 重试间隔
        // SET NX PX 原子加锁
        // 失败则 sleep 后重试
    }

    async async_getData(): Promise<T> {
        // GET key，JSON.parse 返回
    }

    async async_setData(data: T): Promise<number> {
        // SET key + EXPIRE
    }
}
```

**Redis Key 格式：**
```
mod(cp):name(${MODULE_NAME}):appcode(${APP_CODE}):uid(${uid}):${FUNC_INFO}
```

#### 双写模式

```typescript
// 标准查询：Redis 优先，查不到走 MySQL
async function async_QueryPlayerLevelInfo(cxt, userid): Promise<T> {
    let redisTool = new RedisTool_PlayerLevelInfo(cxt, userid);
    let res = await redisTool.async_getData();
    if (!isEmpty_DBRes(res)) return res;

    // MySQL 查询
    let mysqlTool = new MySqlTool_PlayerLevelInfo(cxt, userid);
    res = await mysqlTool.async_query();
    if (isEmpty_DBRes(res)) {
        res = new DefaultData();
        await mysqlTool.async_safeSave(res);
    }
    // 写回 Redis
    await redisTool.async_setData(res);
    return res;
}

// 标准写入：MySQL + Redis
async function async_WritePlayerInfo(cxt, userid, data) {
    let mysqlTool = new MySqlTool_PlayerLevelInfo(cxt, userid);
    await mysqlTool.async_safeSave(data);

    let redisTool = new RedisTool_PlayerLevelInfo(cxt, userid);
    await redisTool.async_setData(data);
}
```

### 4. 跨模块数据访问

**原则：模块不直接访问其他模块的 MySQL/Redis，而是通过内部调用委托。**

```typescript
// 其他模块的 MySqlTool_xxx_other 实际上是通过内部调用让目标模块执行写入
class MySqlTool_PlayerLevelInfo_other {
    OTHER_MODULE_NAME = CONST_VAR.LEVEL_CONFIG_NAME;

    async async_save(): Promise<void> {
        let src = { client: { appcode: CONST_VAR.APP_CODE, gameid: CONST_VAR.GAME_ID, userid: 0 }, mods: [] };
        await CommonFuncs.async_internal_call(src, cxt,
            REQ_NAME.UPDATE_MYSQL_PLAYERLEVELINFO,
            this.OTHER_MODULE_NAME,
            { data: this.mdata }
        );
    }
}
```

### 5. 业务命名空间（Business）

```typescript
namespace Business {
    // 查询类：组合 Redis + MySQL 查询
    export async function async_QueryXxx(cxt, userid): Promise<T> { }

    // 写入类：MySQL + Redis 双写
    export async function async_WriteXxx(cxt, userid, data): Promise<void> { }

    // 业务操作类
    export async function async_DoSomething(cxt, userid, params): Promise<Result> { }
}
```

### 6. 通用功能命名空间（CommonFuncs）

```typescript
namespace CommonFuncs {
    // 配置加载（全局缓存，支持 force 刷新）
    export let g_config: ConfigType = null;
    export function loadConfig(bForce: boolean = false): ConfigType {
        if (g_config == null || bForce) {
            g_config = modsvr.parse_config(`${CONST_VAR.MODULE_NAME}_${CONST_VAR.APP_CODE}`, "json");
        }
        return g_config;
    }

    // 判空（MySQL 空结果）
    export function isEmpty_DBRes(obj: Object): boolean {
        return !obj || Object.keys(obj).length === 0;
    }

    // 客户端通知
    export function notifyClient(src, cxt, userid, msgName, data) {
        modsvr.send_notify(src, cxt, userid, modsvr.PB_CP__CLIENT_NOTIFY,
            JSON.stringify({ req: msgName, data }), modsvr.E_NOTIFY_TERMINAL.CLIENT);
    }

    // 内部模块调用
    export async function async_internal_call(src, cxt, msgName, moduleName, data) {
        // 标准内部调用格式
    }

    // 等级计算工具
    export function getPlayerLevelNumByExp(exp: number): number { }
    export function getPlayerLevelDataByLevel(levelid: number): LevelItem { }
}
```

### 7. 配置数据结构（interf）

```typescript
namespace interf {
    // 游戏配置
    export interface GameConfig {
        isenable: number;
        guid: string;
        // 其他配置字段...
    }

    // 玩家数据结构
    export class UserData_PlayerLevelInfo {
        totalAcquireNum: number;
        totalConsumeNum: number;
        lastLogonTime: number;
        userDegradeNum: number;
        // 其他字段...
    }
}
```

## 服务脚本回调函数

标准入口点：

```typescript
// 脚本加载/重载时调用
async function OnScriptReload(param, cxt) {
    CommonFuncs.loadConfig(true);
}

// 充值回调
async function OnPayResult(pay, cxt) { }

// 客户端请求
async function OnClientRequest(creq, cresp, cxt) {
    let req_name = creq.req.data['req'];
    if (req_name == REQ_NAME.QUERY_CONFIG) {
        // 处理...
    }
}

// 游戏服务请求
function OnGameRequest(greq, gresp, cxt): boolean { }

// 内部模块调用
async function OnInternalCall(ireq, iresp, cxt): Promise<boolean> { }
```

## 模块间通信规范

1. **通过 `async_internal_call`**：模块 A 调用模块 B 的 `OnInternalCall`
2. **消息格式**：
   ```typescript
   {
       req: "消息名",
       modulename: "调用方模块名",
       data: { /* 业务数据 */ }
   }
   ```
3. **响应格式**：
   ```typescript
   iresp.resp = { id: 0, data: {} };
   ```

## 最佳实践

1. **配置使用全局变量缓存**，通过 `bForce` 参数控制是否强制刷新
2. **工具类方法全部 async化**，调用方使用 `await`
3. **MySQL 使用 INSERT ON DUPLICATE KEY UPDATE** 或先查再写
4. **Redis 操作加锁**，防止并发写入导致数据不一致
5. **大额发奖分批处理**，如超过 20 亿金币时分多次发放
6. **日志使用环境过滤**，仅在测试环境（125/888）输出
7. **跨模块数据委托**，不直接操作其他模块的存储
8. **默认值使用类构造函数**，保证每次返回完整默认结构
