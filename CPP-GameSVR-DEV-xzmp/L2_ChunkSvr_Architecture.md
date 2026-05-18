# L2 ChunkSvr 构造原理 — C++/Lua 混合架构

> 解释 chunkSvr 为什么能调用 Lua 脚本、Lua 如何回调 C++ 代码和库、以及配合 MySQL/Redis 的三级缓存机制。

---

## 一、整体架构

chunkSvr 是一个 C++ Windows 服务，内部嵌入了 Lua 虚拟机作为业务逻辑层。C++ 负责网络通信、连接池管理和进程内缓存；Lua 负责所有活动模块的业务逻辑。两者通过一套 C API 桥接。

```
┌─────────────────────── C++ 进程 ───────────────────────┐
│                                                         │
│  TcySockSvr (TCP网络层)                                 │
│       │ TCP 收到消息                                    │
│       ▼                                                 │
│  TcyMsgCenter (消息中心)                                │
│       │ evMsgFilter 事件                                │
│       ▼                                                 │
│  TcyMsg2LuaScripts (C++/Lua 桥接层)                     │
│       │                                                 │
│       ├─→ MsgCenter lua_State (线程局部, per-thread)    │
│       │       │                                         │
│       │       ▼ main(context, request)                  │
│       │       └─→ 各模块 handler                        │
│       │                                                 │
│       ├─→ Module lua_State × N (独立, 带定时器/文件监听)│
│       │       └─→ luamodules/*.lua (配置+表结构)        │
│       │                                                 │
│       └─→ CmdScript lua_State (临时, 运行即销毁)        │
│                                                         │
│  HttpServerModule (HTTP网络层, libevent evhttp)         │
│       │ POST /v1.0/chunkluareq                         │
│       │ JSON → OnHttpLuaReq → MsgCenter lua_State      │
│       ▼                                                 │
│  C++ 导出库 (dbcore / core / msgcore / core_extern)    │
│       ↑ Lua 通过这些库回调 C++                          │
│                                                         │
│  GameDBConnectPool / MyGameDbPoolV3 (MySQL连接池)       │
│  Redis Client (hiredis)                                 │
│  TcyLuaTableValue (进程内缓存, 跨重载持久)              │
└─────────────────────────────────────────────────────────┘
```

### 1.1 HTTP 服务

chunkSvr 内嵌 `HttpServerModule`（基于 libevent evhttp），提供 HTTP → Lua 透传网关。仅一条路由，CP 脚本和外部工具可通过 HTTP 调用任意 Lua 模块的 `OnHttpLuaReq`。

| 属性 | 值 |
|------|-----|
| 默认端口 | 9080（INI `[HttpServerModule] port` 可配） |
| 线程数 | 1（INI `[HttpServerModule] threadcount` 可配） |
| 源码 | `HttpServerModule.h/.cpp` (3K) |
| 依赖 | libevent (evhttp) |

#### 路由

| Method | Path | 处理 |
|--------|------|------|
| POST | `/v1.0/chunkluareq` | JSON body → `MainServer::m_msgCenter.OnHttpLuaReq(strInput)` → Lua 消息分发 |
| 其他 | 任意 | 404 Not Found |

#### 请求格式

```json
POST /v1.0/chunkluareq
Content-Type: application/json

{
  "nRequest": 450160,
  "nUserID": 12345,
  ...  // 其他字段按 Lua 模块要求传入
}
```

#### 响应格式

Lua 处理后的 JSON 结果，HTTP 200 返回。Lua 异常时返回 `{"err": "..."}`。

#### 实测（本地部署）

| 请求 | 结果 |
|------|------|
| `GET /` | 404 |
| `GET /v1.0/chunkluareq` | 404（仅 POST 注册） |
| `POST /v1.0/chunkluareq {}` | 200 `{"err":"attempt to call a nil value"}` |
| `PUT/DELETE /v1.0/chunkluareq` | 404 |

#### 注意

- INI 未配置 `[HttpServerModule]` 段时，使用硬编码默认值（port=9080, threadcount=1）
- HTTP 请求走独立线程池（evhttp），与 TCP 消息处理的 MsgCenter lua_State 不是同一个线程局部状态，需注意 Lua 全局变量的线程安全性

---

## 二、为什么能调用 Lua 脚本

### 2.1 Lua 虚拟机初始化

C++ 在启动时通过 `lua_open()` 创建 Lua 虚拟机，加载标准库和自研 C 库，然后执行入口脚本 `scripts/msgcenter/main.lua`。

```cpp
// TcyMsg2LuaScripts::getMsgCenterLuaState() 伪代码
lua_State* L = lua_open();
luaL_openlibs(L);              // 标准库
luaopen_dbcore(L);             // MySQL + Redis + 缓存
luaopen_protobuf_c(L);         // protobuf 编解码
luaopen_msgcore(L);            // 消息收发
luaopen_core(L);               // INI配置 + 日志
luaopen_core_extern1(L);       // 跨模块缓存读取 + 充值查询
luaopen_core_cjson(L);         // JSON
lua_setglobal(L, "_TcyMsg2LuaScripts_");  // 存储 this 指针
luaL_dofile(L, "scripts/msgcenter/main.lua");  // 执行入口
```

### 2.2 三种 Lua 上下文

| 上下文 | 创建时机 | 生命周期 | 用途 | 加载的额外库 |
|--------|---------|---------|------|-------------|
| **MsgCenter** | 每个工作线程首次访问时惰性创建 | 线程局部，版本号变更时重建 | 消息分发入口 | core_extern1 (跨模块读缓存) |
| **Module** | cmdcore_start(name, path) | 持久，直到 cmdcore_stop 或热重载 | 单个活动模块的配置+定时器+文件监听 | core_extern (定时器/缓存/文件监听) |
| **CmdScript** | doUserCmdScript() | 临时，执行后立即销毁 | 运维命令 | cmdcore (启动/停止/重载模块) |

### 2.3 消息从 C++ 到 Lua 的流转

```
TCP 数据包到达
    │
    ▼
TcyMsgCenter 触发 evMsgFilter 事件
    │
    ▼
TcyMsg2LuaScripts::OnMsgFilterMsg(context, request, done)
    │
    ▼
获取线程局部 MsgCenter lua_State
    │
    ▼
lua_getglobal(L, "main")           // 压入 Lua 函数
lua_pushlightuserdata(L, context)  // 压入 C++ 指针
lua_pushlightuserdata(L, request)  // 压入 C++ 指针
lua_pcall(L, 2, 0, 0)             // 调用 main(context, request)
    │
    ▼
Lua 侧 main.lua:
  local udctx = msgcore.packcontext(context)   -- C++ 指针 → Lua table
  local udreq = msgcore.packrequest(request)   -- C++ 指针 → Lua table
  msgcenter:notify(udctx, udreq)               -- 按 nRequest 分发到各模块 handler
```

---

## 三、Lua 如何回调 C++ 代码和库

C++ 通过 `luaL_register` 将 C 静态函数注册为 Lua 库，Lua 脚本像调用普通 Lua 函数一样调用它们。

### 3.1 六大导出库

#### dbcore — 数据库操作

| Lua 调用 | C++ 实现 | 说明 |
|----------|---------|------|
| `dbcore.mysql_dbentry(keys, callback)` | 获取连接池连接，创建 entry 上下文，调用 Lua callback | 所有 DB 操作的入口 |
| `dbcore.mysql_excute(entry, sql)` | 执行原始 SQL | 建表/INSERT/UPDATE |
| `dbcore.mysql_excute_1(entry, sql, cb)` | 执行 SQL，ResultSet 传给 Lua cb | SELECT 查询 |
| `dbcore.mysql_transaction(entry, cb)` | 开启事务，执行 Lua cb，失败则回滚 | |
| `dbcore.rds_select(entry, idx)` | 选择 Redis DB 编号 | |
| `dbcore.rds_cmd(entry, cmd)` | 执行单条 Redis 命令 | 返回 (result, ok) |
| `dbcore.rds_cmds(entry, cmds)` | 批量执行 Redis 命令 | |
| `dbcore.entry_setcache(entry, key, val)` | 写入 C++ 进程内缓存 | |
| `dbcore.entry_getcache(entry, key)` | 读取 C++ 进程内缓存 | |

#### core — 基础工具

| Lua 调用 | C++ 实现 | 说明 |
|----------|---------|------|
| `core.core_log(level, msg)` | 日志输出 (TRACE/DEBUG/INFO/WARN/ERROR) | |
| `core.core_getiniint(area, key, default)` | 读取 INI 配置整数 | |
| `core.core_getinistr(area, key, default)` | 读取 INI 配置字符串 | |
| `core.core_writeiniint/str(...)` | 写入 INI 配置 | |
| `core.core_getcurrentdir()` | 获取工作目录 | |

#### msgcore — 消息收发

| Lua 调用 | C++ 实现 | 说明 |
|----------|---------|------|
| `msgcore.packrequest(ptr)` | REQUEST* → Lua table {nRequest, pDataPtr, nRepeated} | |
| `msgcore.packcontext(ptr)` | CONTEXT_HEAD* → Lua table {hSocket, lTokenID, ...} | |
| `msgcore.sendrespone(req, ctx)` | Lua table → C++ 结构 → gImSendResponse → TCP 回包 | |
| `msgcore.notifyassit(req)` | → gImNotifyAssit → 通知 assistSvr | |
| `msgcore.msg2otherchunk(req)` | → gImMsg2OtherChunk → 转发其他 chunk | |
| `msgcore.msg2gamesvr(req)` | → gImMsg2GameSvr → 转发 gameSvr | |
| `msgcore.sendnotify2node(dest, msgid, data)` | → gImSendNotifyToNode | |
| `msgcore.sendrequest2node(dest, msgid, data)` | → gImSendRequestToNodeWait | 请求-响应模式 |

#### core_extern — 模块扩展 (Module lua_State 专用)

| Lua 调用 | C++ 实现 | 说明 |
|----------|---------|------|
| `core_extern.staff_timer(seconds, callback_id)` | 在模块 strand 上设定时器，触发时调用 `_TcyCallbackFunc_(callback_id)` | |
| `core_extern.write_config([subkey], value)` | 写入模块持久缓存 (TcyLuaTableValue) | 热重载后数据不丢 |
| `core_extern.read_config([subkey])` | 读取模块持久缓存 | |
| `core_extern.listenfilemod(path, seconds, callback_id)` | 监听文件修改，变更时调用 `_TcyCallbackFunc_(callback_id)` | 配置热更新 |
| `core_extern.removefilemod(path)` | 取消文件监听 | |

#### core_extern1 — 消息中心扩展 (MsgCenter lua_State 专用)

| Lua 调用 | C++ 实现 | 说明 |
|----------|---------|------|
| `core_extern1.read_config(module_name [, subkey])` | 按名称读取其他模块的缓存 | 跨模块数据共享 |
| `core_extern1.onqurry_playercharge(userid, days)` | 查询玩家充值金额 | |

#### protobuf.c — Protobuf 编解码

| Lua 调用 | 说明 |
|----------|------|
| `_env_new()` | 创建 pbc 环境 |
| `_env_register(env, buffer)` | 注册 .proto schema |
| `_rmessage_new(env, typename, data)` | 解码：二进制 → 读取消息对象 |
| `_rmessage_integer/string/real(msg, key, idx)` | 按字段名读取解码后的值 |
| `_wmessage_new(env, typename)` | 编码：创建写入消息对象 |
| `_wmessage_integer/string/real(msg, key, val)` | 按字段名写入值 |
| `_wmessage_buffer_string(msg)` | 获取编码后的二进制字符串 |
| `_decode(env, decode_fn, table, typename, data)` | 回调式解码到 Lua table |
| `_pattern_pack/unpack(...)` | 结构化 pack/unpack |

### 3.2 三种回调模式

**模式1: Lua → C++ 直接调用**
```lua
-- Lua 脚本直接调用注册的 C 函数
local r = dbcore.mysql_excute(entry, "SELECT ...")
```

**模式2: C++ → Lua 回调 (DB操作)**
```lua
-- Lua 传入 function，C++ 在合适时机回调
dbcore.mysql_dbentry(keys, function(entry)
    -- C++ 获取连接后回调此函数，传入 entry 指针
    local res = dbcore.mysql_excute_1(entry, sql, function(resultSet)
        -- C++ 执行查询后回调，传入结果集
        while dbcore.mysql_resultset_next(resultSet) do
            local val = dbcore.mysql_resultset_getint(resultSet, "userid")
        end
    end)
end)
```

**模式3: 定时器/文件监听回调**
```lua
-- Lua 注册 callback_id，C++ 定时器/文件变更触发时回调 _TcyCallbackFunc_
core_extern.staff_timer(60, 1)  -- 60秒后触发 callback_id=1

function _TcyCallbackFunc_(callback_id)
    if callback_id == 1 then
        -- 处理定时器逻辑
    end
end
```

---

## 四、三级缓存机制 (lasyncache)

### 4.1 两级缓存（实际生效）

> **重要**：代码框架预留了三级缓存（C++内存→Redis→MySQL），但当前所有 lasynccache 模块的 `packCacheParams` 均硬编码 `key = nil`，导致 `getcache` 中 `if params.key then` 永远跳过 C++ 进程内缓存。实际生效的只有两级：Redis → MySQL。C++ 进程内缓存层未参与数据读取路径。

```
L1: C++ 进程内缓存 (TcyLuaTableValue)
    │ ⚠️ 所有模块 key=nil，此层被跳过
    │
L2: Redis
    │ 命中 → PB解码 → 返回 (毫秒级)
    │ 未命中 ↓
L3: MySQL (data BLOB)
    │ 命中 → PB解码 → 回填L2 → 返回 (十毫秒级)
    │ 未命中 → 返回 nil
```

这也解释了为什么 xzmpDB 等外部工具只需写 Redis + MySQL 即可生效——无需操作 C++ 缓存，因为它根本不参与读取路径。

### 4.2 读取流程 — getcache

> 注意：`params.key` 始终为 nil，C++ 缓存层被跳过。

```lua
function getcache(entry, params, pbname)
    -- L1: C++ 进程内缓存 (params.key=nil → 跳过)

    -- L2: Redis (key由AsynCacheConfig.mysqlregeister定义: sqlas_xxx → rdsas_xxx)
    local redis_key = Config.mysqlregeister[params.mysql] .. ":" .. params.mainkey
    local res = entry:rdscmd("GET %s", redis_key)
    if res then
        if pbname then
            local cache = protobuf.decode(pbname, res)  -- PB解码
        end
        return cache
    end

    -- L3: MySQL
    local sql = "SELECT data FROM " .. params.mysql .. " WHERE mainkey=" .. params.mainkey
    entry:sqlexcute1(sql, function(res)
        if res:next() then
            local data = res:getstr("data")
            if pbname then
                local cache = protobuf.decode(pbname, data)  -- PB解码
                -- 回填L2 (Redis)
                entry:rdscmd("SET %s %s", redis_key, protobuf.encode_1(pbname, cache))
                entry:rdscmd("EXPIRE %s %d", redis_key, rediscachetimeout)
                return cache
            end
        end
    end)
end
```

### 4.3 写入流程 — setcache

```lua
function setcache(entry, params, cache, pbname)
    -- 1. PB序列化
    local pbdata = protobuf.encode_1(pbname, cache)

    -- 2. 写入 Redis
    entry:rdscmd1argarry({
        { "SET %s %b", pbdata }
    })

    -- 3. 标脏 (加入脏数据集合，等待异步刷盘到MySQL)
    entry:rdscmd("SADD rdsdirtycachelist:%s %d", params.mysql, params.mainkey)

    -- 4. C++ 进程内缓存 (params.key=nil → 跳过)
end
```

### 4.4 脏数据异步刷盘

```
写入时: SET Redis + SADD 脏集合
           │
           │ 定时器触发
           ▼
    renameDirtyTable()
           │ 原子重命名: rdsdirtycachelist:xxx → rdsdirtycachelist_tmp:xxx
           │ (新写入进入新的 rdsdirtycachelist，不受影响)
           ▼
    syncDirtyRedisCache()
           │ SSCAN rdsdirtycachelist_tmp:xxx
           │ 逐个: GET Redis值 → INSERT ... ON DUPLICATE KEY UPDATE MySQL
           │ 成功: DEL rdsdirtycachelist_tmp:xxx
           │ 失败: PERSIST (移除TTL，保证数据不丢，下次重试)
```

### 4.5 使用 lasynccache 的模块

| 模块 | MySQL表名 | Redis Key前缀 | PB缓存类型 |
|------|----------|--------------|-----------|
| TQDecorations | sqlas_tqdecoration | rdsas_tqdecoration: | tqdecoration.DecorationCache |
| TQMonthCard | sqlas_tqmonthcard | rdsas_tqmonthcard: | tqmonthcard.Cache |
| TQVip | sqlas_tqvip | rdsas_tqvip: | tqvip.PlayerData |
| QuickRechargeV2 | sqlas_quickrecharge | rdsas_quickrecharge: | quickrecharge.Cache |

---

## 五、模块间通信机制

### 5.1 注入式接口 (im* 函数)

模块间不直接调用，而是在 main.lua 初始化时通过注入 `im*` 函数指针连接：

```lua
-- main.lua 初始化片段
local TQRelief = require "scripts.msgcenter.TQRelief"
TQRelief.imGetUserNewDeposit = NewDeposit.export_getnewdeposit
TQRelief.imNewDepositOp = NewDeposit.export_newdepositOp
TQRelief.imGetVipInfoByModule = TQVip.getVipInfoByModule
```

这实质是 monkey-patch：先创建空函数占位，再由 main.lua 用真实实现替换。

### 5.2 事件回调 (moudleCallback/chargeCallback/tongbaoCallback)

NewDeposit 作为银两枢纽，提供事件注册机制：

```lua
-- 充值类模块注册支付回调
NewDeposit.addMoudleCallback("TQBrokeRecharge", TQBrokeRecharge.onPayResult)
NewDeposit.addChargeCallback("QuickRechargeV2", QuickRechargeV2.onPayResult)
NewDeposit.addTongbaoCallback("TQLuckyDiscountGift", TQLuckyDiscountGift.onTongbaoExchange)
```

当支付事件到达时，NewDeposit 遍历已注册的回调，触发对应的业务逻辑。

### 5.3 跨模块缓存读取

MsgCenter 的 Lua 上下文可以通过 `core_extern1.read_config(module_name)` 读取任何 Module 的持久缓存，无需模块间直接引用。

---

## 六、热重载机制

chunkSvr 有两套 lua_State，对应两套热重载机制：

```
MsgCenter lua_State (per-thread, 多实例) ←── 版本号检测，渐进式重建
Module  lua_State   (全局单实例)         ←── 命令式重启，原子切换
```

### 6.1 MsgCenter 热重载

#### 检测机制

每条 TCP 消息处理前，`getMsgCenterLuaState()` 检查版本号：

```cpp
int version = GetLuaMsgCenterVersion();  // 读 INI [luascripts] msgcenterversion
if (version != tL->version || !tL->L) {
    // 版本变化 → 重建当前线程的 lua_State
}
```

- 版本号来自 INI 文件，每次热更时递增
- 检测在消息处理路径中，不占用额外线程或定时器

#### 重建流程

```
getMsgCenterLuaState() 检测版本变化
  │
  ├─ lua_close(old_L)           // 销毁旧 lua_State（所有全局变量、注册函数释放）
  ├─ lua_open()                  // 创建新 lua_State
  ├─ luaopen_dbcore/core/msgcore/core_extern1/cjson  // 注册 C++ 导出库
  ├─ luaL_loadfile("scripts/msgcenter/main.lua")     // 加载入口脚本
  ├─ lua_pcall(L, 0, 0, 0)      // 执行入口脚本（require 所有子脚本）
  ├─ lua_setglobal("_TcyMsg2LuaScripts_", this)      // 存储 C++ 指针
  └─ 更新 tL->version = version  // 缓存新版本号
```

**渐进式生效**：每个工作线程独立检测、独立重建。线程 A 重建完用新脚本，线程 B 可能还在用旧脚本——直到 B 处理下一条消息时触发检测。不是原子切换，而是逐线程过渡。

**失败保护**：加载失败时丢弃新 lua_State，保留旧 lua_State 继续服务。

**注意**：MsgCenter 无 TcyLuaTableValue 缓存——重建后所有 Lua 全局变量从 `main.lua` 重新初始化，之前运行时动态修改的 Lua 变量丢失。

### 6.2 Module 热重载

#### 触发方式

通过运维命令（CmdScript）执行 `serverupdate.lua`：

```lua
-- serverupdate.lua 核心逻辑
cmdcore.cmdcore_restart("TQVip", "scripts/luamodules/TQVip.lua")
-- restart 失败时降级：
-- cmdcore.cmdcore_stop("TQVip")
-- cmdcore.cmdcore_start("TQVip", "scripts/luamodules/TQVip.lua")
```

CmdScript 由 TCP 运维命令触发，C++ 创建临时 lua_State 执行脚本，执行后销毁。

#### C++ 实现 — `cmdcore_restart`

```cpp
l_cmdcore_restart(lua_State* L)
  │
  ├─ 从 m_data->luaModules 查找旧 Module
  ├─ 创建新 Module + 新 lua_State
  │     lua_open()
  │     luaopen_dbcore/core/msgcore/core_extern/cjson  // extern, 非 extern1
  │     luaL_loadfile(script)  // 仅加载，未执行
  │
  ├─ 写锁保护下替换模块映射
  │     RWTYPE_GETWRITEVAL(m_data, data)
  │     data->luaModules[name] = newm  // 新请求立即路由到新 Module
  │
  ├─ 缓存数据迁移（关键步骤）
  │     auto wcacheold = m->m_cahce.writeGuard()
  │     auto wcachenew = newm->m_cahce.writeGuard()
  │     wcachenew->m_data.swap(wcacheold->m_data)  // std::map swap，O(1)
  │
  ├─ 异步销毁旧 Module
  │     m->clearLuaModule()  // post async task: lua_close(old_L)
  │
  ├─ 设置新 Module 全局环境
  │     lua_setglobal("_TcyMsg2LuaScripts_", this)
  │     lua_setglobal("_ModuleName_", name)
  │
  └─ lua_pcall(L, 0, 0, 0)  // 执行新脚本
       │ 失败 → eraseLuaModule + clearLuaModule → 返回 nil
```

**原子切换**：Module lua_State 全局单实例，写锁保护替换，重启立即对所有线程生效。

**缓存持久化**：`m_cahce` (TcyLuaTableValue) 存储在 C++ 进程内存中，不属于任何 lua_State。重启时通过 `std::map::swap` 从旧 Module 转移到新 Module，数据零丢失。

**降级方案**：`restart` 失败时回退到 `stop + start`。`start` 不迁移缓存，`stop` 销毁缓存——降级方案会导致缓存数据丢失。

### 6.3 TcyLuaTableValue — 跨重载的数据持久层

```cpp
struct TcyLuaTableValue {
    using Key = boost::variant<double, SStr>;  // SStr = shared_ptr<string>，字符串驻留
    using Var  = boost::variant<double, string, bool, TcyLuaTableValue>;
    using Type = std::map<Key, Var>;
    Type m_data;  // C++ 进程内存，不受 lua_State 生命周期影响
};
```

- Lua 通过 `core_extern.write_config(key, val)` 写入，`core_extern.read_config(key)` 读取
- 数据存储在 C++ 侧的 `std::map` 中，lua_State 只是引用
- lua_State 销毁重建后，通过相同 key 重新访问同一份数据
- 读写受 `TcyRWType<TcyLuaTableValue>` (读写锁) 保护，线程安全

### 6.4 配置热更新

Module 通过 `core_extern.listenfilemod(path, seconds, callback_id)` 监听配置文件变更，变更时触发 callback 重新加载配置：
```lua
config = lconfigdata.createconfigdata("TQCheckinConfig.lua", function()
    lcoreex.mergeconfig("config", config.data)  -- 配置变更回调
end)
```

### 6.5 完整热更操作步骤

```
1. 部署新 Lua 文件到 server_chunk/scripts/
2. 打包 scripts.zip（如使用 scriptupdate=true 模式）
3. 执行运维命令 serverupdate.lua：
   a. 解压 scripts.zip（如 scriptupdate=true）
   b. cmdcore_restart 每个 Module（moduleupdatemap 列表）
   c. 递增 INI [luascripts] msgcenterversion
4. 各工作线程处理下条消息时自动重建 MsgCenter lua_State
5. 无需停服、无需重编 C++
```

---

## 七、线程安全

| 机制 | 说明 |
|------|------|
| MsgCenter lua_State 线程局部 | `boost::thread_specific_ptr`，每个工作线程独立状态 |
| Module 数据读写锁 | `TcyRWType<Data>` (TcyRWLock) 保护模块映射 |
| Module 操作 strand 串行化 | `PlanaStaff` strand 确保定时器/文件监听回调不并发 |
| DB entry 防重入 | `entry_hold` 标志防止嵌套 DB 操作 |
