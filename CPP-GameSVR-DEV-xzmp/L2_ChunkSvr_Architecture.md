# L2 ChunkSvr 构造原理 — C++/Lua 混合架构

> 解释 chunkSvr 为什么能调用 Lua 脚本、Lua 如何回调 C++ 代码和库、以及配合 MySQL/Redis 的三级缓存机制。

---

## 一、整体架构

chunkSvr 是一个 C++ Windows 服务，内部嵌入了 Lua 虚拟机作为业务逻辑层。C++ 负责网络通信、连接池管理和进程内缓存；Lua 负责所有活动模块的业务逻辑。两者通过一套 C API 桥接。

```
┌─────────────────────── C++ 进程 ───────────────────────┐
│                                                         │
│  TcySockSvr (网络层)                                    │
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
│  C++ 导出库 (dbcore / core / msgcore / core_extern)    │
│       ↑ Lua 通过这些库回调 C++                          │
│                                                         │
│  GameDBConnectPool / MyGameDbPoolV3 (MySQL连接池)       │
│  Redis Client (hiredis)                                 │
│  TcyLuaTableValue (进程内缓存, 跨重载持久)              │
└─────────────────────────────────────────────────────────┘
```

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

### 4.1 三级层次

```
L1: C++ 进程内缓存 (TcyLuaTableValue)
    │ 命中 → 直接返回 (纳秒级)
    │ 未命中 ↓
L2: Redis
    │ 命中 → PB解码 → 回填L1 → 返回 (毫秒级)
    │ 未命中 ↓
L3: MySQL (data BLOB)
    │ 命中 → PB解码 → 回填L2+L1 → 返回 (十毫秒级)
    │ 未命中 → 返回 nil
```

### 4.2 读取流程 — getcache

```lua
function getcache(entry, params, pbname)
    -- L1: C++ 进程内缓存
    if params.key then
        local cache = entry:getcache(params.key)
        if cache then return cache end
    end

    -- L2: Redis
    local redis_key = redistag .. ":" .. params.mainkey
    local res = entry:rdscmd("GET %s", redis_key)
    if res then
        if pbname then
            local cache = protobuf.decode(pbname, res)  -- PB解码
            if params.key then entry:setcache(params.key, cache) end  -- 回填L1
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
                -- 回填L1
                if params.key then entry:setcache(params.key, cache) end
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
        { "SET %s %b", pbdata }     -- %b = 二进制参数
    })

    -- 3. 标脏 (加入脏数据集合，等待异步刷盘到MySQL)
    entry:rdscmd("SADD rdsdirtycachelist:%s %d", params.mysql, params.mainkey)

    -- 4. 更新 C++ 进程内缓存
    if params.key then
        entry:setcache(params.key, cache)
    end
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
| TQDecorations | sqlas_tqdecoration | tqdecoration: | tqdecoration.DecorationCache |
| TQMonthCard | sqlas_tqmonthcard | tqmonthcard: | tqmonthcard.Cache |
| TQVip | sqlas_tqvip | tqvip: | tqvip.PlayerData |
| QuickRechargeV2 | sqlas_quickrecharge | quickrecharge: | quickrecharge.Cache |

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

### 6.1 MsgCenter 热重载

INI 文件中 `msgcenterversion` 递增时，每个线程下次访问 MsgCenter lua_State 会检测版本号变化，自动关闭旧状态、创建新状态、重新加载 `scripts/msgcenter/main.lua`。

### 6.2 Module 热重载

通过 `cmdcore.cmdcore_restart(name, path)`：
1. 创建新 Module 和新 lua_State
2. 将旧 Module 的 `m_cahce` (TcyLuaTableValue) 交换到新 Module
3. 注册新 Module，关闭旧 Module
4. 执行新脚本

模块的缓存数据跨重载保留，代码逻辑替换。

### 6.3 配置热更新

Module 通过 `core_extern.listenfilemod(path, seconds, callback_id)` 监听配置文件变更，变更时触发 callback 重新加载配置：
```lua
config = lconfigdata.createconfigdata("TQCheckinConfig.lua", function()
    lcoreex.mergeconfig("config", config.data)  -- 配置变更回调
end)
```

---

## 七、线程安全

| 机制 | 说明 |
|------|------|
| MsgCenter lua_State 线程局部 | `boost::thread_specific_ptr`，每个工作线程独立状态 |
| Module 数据读写锁 | `TcyRWType<Data>` (TcyRWLock) 保护模块映射 |
| Module 操作 strand 串行化 | `PlanaStaff` strand 确保定时器/文件监听回调不并发 |
| DB entry 防重入 | `entry_hold` 标志防止嵌套 DB 操作 |
