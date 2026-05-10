# L1 公共接口参考

> 快速参考：我要做 X，该调什么、怎么调。

---

## 1. 发奖接口

### 单次发奖

```typescript
await modsvr.async_send_reward(src, cxt, target, r, timeout?, related_guid?): Promise<E_ERROR>
```

- `r`: `reward` 对象，务必填写 `propid`/`count`/`guid`
- `r.status`: 发奖后自动更新（NOT=0 → ING=1 → SUCCEED=2）
- 返回 `E_ERROR`，发奖状态通过 `r.status` 读取

### 批量发奖（优先使用）

```typescript
await modsvr.async_batch_send_reward(src, cxt, target, rewards, guid, timeout?, related_guid?): Promise<E_ERROR>
```

- `rewards`: `reward[]`，每个元素的 `guid` 会自动设置为传入的 `guid` 参数
- 服务器内部做并发优化，复数奖励时应优先使用批量接口
- 发奖状态通过每个 `rewards[i].status` 读取

### reward 结构

```typescript
interface reward {
    propid: number;          // 道具ID
    count: number;           // 数量
    status?: E_REWARD_STATUS; // 发奖后自动填充
    guid?: string;           // 防重复标识
    expire?: number;
    to?: E_REWARD_TO;        // GAME=0/BACK=1/SAFE=2
}
```

### 大额金币

超过 20 亿金币时必须分批发奖，实现方式见 [L1_DevStandards.md — 大额金币分批发奖](L1_DevStandards.md#4-大额金币分批发奖)。

---

## 2. 通知客户端

### 推送消息

```typescript
modsvr.send_notify(src, cxt, target, msgid, data, terminal): boolean
```

- `msgid`: 协议号，通常使用 `modsvr.PB_CP__CLIENT_NOTIFY`
- `data`: `string | Uint8Array`，需手动 `JSON.stringify`
- `terminal`: `E_NOTIFY_TERMINAL.CLIENT` (=0)

### 常用封装

```typescript
// 脚本中常见的 notifyClient 封装
function notifyClient(src, cxt, userid, msgName, data) {
    modsvr.send_notify(src, cxt, userid, modsvr.PB_CP__CLIENT_NOTIFY,
        JSON.stringify({ req: msgName, data }), modsvr.E_NOTIFY_TERMINAL.CLIENT);
}
```

### 客户端收到的数据格式

```typescript
{ req: msgName, data: { ... } }
```

---

## 3. 通知其他模块

### 内部模块调用

```typescript
await modsvr.async_internal_call(src, cxt, name, req, resp, timeout?): Promise<E_ERROR>
```

- `name`: 目标模块名（MODULE_NAME）
- `req`: `{ req: "消息名", modulename: "调用方模块名", data: {...} }`
- `resp`: `{ errs: errinfo[], resp: { id: number, data: object } }`
- `resp.resp.id`: 1=成功，0=失败

### 构造 src

```typescript
let src = {
    client: { appcode: CONST_VAR.APP_CODE, gameid: CONST_VAR.GAME_ID, userid: 0 },
    mods: []
};
```

### 广播到所有模块线程

```typescript
modsvr.internal_broadcast(src, name, req): E_ERROR
```

- 与 `async_internal_call` 不同，广播会通知所有目标模块线程
- `async_internal_call` 只会通知其中一个线程

---

## 4. 配置读取

### 解析为对象

```typescript
let config = modsvr.parse_config(name, ext);   // 私有配置（config 目录）
let config = modsvr.parse_common(name, ext);   // 公共配置（common 目录）
```

- `name`: 配置名，如 `cmquickrecharge_xzmp`
- `ext`: 扩展名，如 `"jsonc"`
- 返回解析后的对象

### 读取原始字符串

```typescript
let str = modsvr.get_config(name, ext);    // 私有配置
let str = modsvr.get_common(name, ext);    // 公共配置
```

### 常用封装

```typescript
let g_config = null;
function loadConfig(bForce = false) {
    if (g_config == null || bForce) {
        g_config = modsvr.parse_config(`${CONST_VAR.MODULE_NAME}_${CONST_VAR.APP_CODE}`, "jsonc");
    }
    return g_config;
}
```

---

## 5. 数据库操作

### MySQL

```typescript
// 查询
let res = await mysqlTool.async_query(name?);
// 写入（先查再写，INSERT 或 UPDATE）
await mysqlTool.async_safeSave(data);
```

- 表名格式：`tblcpuserdata_{MODULE_NAME}_{GAME_CODE}`
- 行定位：`userid` + `name` 字段
- 数据字段：`data`（TEXT，JSON 格式）
- 判空：`isEmpty_DBRes(res)` — `!obj || Object.keys(obj).length === 0`
- 防 SQL 注入：内部使用 `mysql.escape()`

### Redis

```typescript
// 读取
let res = await redisTool.async_getData();
// 写入（自动设置过期时间）
await redisTool.async_setData(data);
```

- Key 格式：`mod(cp):name({MODULE_NAME}):appcode({APP_CODE}):uid({uid}):{FUNC_INFO}`
- 过期时间：默认 7 天，总数量不为常数的 key 必须携带过期时间
- 允许读任意 key，不允许写其他 gameid 的 key

### 双写模式

标准查询/写入流程详见 [L1_DevStandards.md — 双写模式](L1_DevStandards.md#23-双写模式)。

---

## 6. 分布式锁

```typescript
await redisTool.async_redis_lock_key(key, callback, ttl?);
```

- 底层：SET NX PX 原子加锁
- 失败重试：间隔 50/100/300/500/1000ms
- `key`: 通常使用 `redisTool.lockKey`
- `ttl`: 可选，默认使用 `MAX_REDIS_EXPIRE`

---

## 其他常用接口

| 接口 | 签名 | 说明 |
|------|------|------|
| 获取客户端信息 | `modsvr.get_clientinfo(userid): source` | 获取玩家 source，用于构造 src |
| 判断在线 | `modsvr.check_online(userid): boolean` | 检查玩家是否在线 |
| 异步获取昵称 | `await modsvr.async_get_nickname(src, cxt, userid, timeout?)` | 单个 number→string，数组→object |
| 异步获取头像 | `await modsvr.async_get_portrait(src, cxt, userid, timeout?)` | 同上 |
| 异步发送邮件 | `await modsvr.async_send_mail(src, cxt, userids, title, content, expire, rewards, guid, timeout?)` | userids 支持 number 或 number[] |
| 发送日志 | `modsvr.send_log(src, cxt, target, log)` | 埋点日志 |
| 获取当前环境 | `modsvr.get_svrenv(): string` | 返回如 "125"（测试环境） |
| 获取当前模块名 | `modsvr.module_name(): string` | 从脚本文件名解析 |
| 获取当前缩写 | `modsvr.get_appcode(): string` | 从脚本文件名解析，如 "xzmp" |
| 获取当前 gameid | `modsvr.get_gameid(): number` | 从服务获取 |
