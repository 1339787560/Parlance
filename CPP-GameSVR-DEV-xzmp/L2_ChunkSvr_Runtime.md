# L2 ChunkSvr 运行时 — scripts 目录运作机制

> 解释 chunkSvr.exe 启动后，scripts 目录下的文件如何被加载、初始化、协作运转。

---

## 一、启动流程

### 1.1 INI 配置入口

`xzmochunksvr.ini` 中 `[luascripts]` 段定义 Lua 启动参数：

```ini
[luascripts]
msgcenterversion=835          # MsgCenter 版本号，递增触发热重载
startcmdscript=scripts/usercmd/serverupdate.lua  # 启动时执行的运维脚本
usercmdenable=0               # 运维命令开关（0=关闭，1=开启后执行 cmdscript）
cmdscript=PropTestTool.lua    # usercmdenable=1 时执行的脚本名
```

### 1.2 C++ 启动序列

```
C++ MainServer::OnInit()
  │
  ├─ 创建 MsgCenter lua_State（持久）
  │     luaL_loadfile("scripts/msgcenter/main.lua")
  │     lua_pcall() → 执行 main.lua
  │
  ├─ 创建 Module lua_State（按 serverupdate.lua 的 moduleupdatemap）
  │     cmdcore.cmdcore_start(name, script)
  │
  └─ 启动完成，监听端口
```

---

## 二、scripts 目录结构

```
server_chunk/scripts/
│
├─ msgcenter/           # MsgCenter 业务层（处理客户端请求）
│   ├─ main.lua         # 入口：加载所有模块、im*注入、消息分发
│   ├─ lmsgdef.lua      # 消息ID定义、PB schema 注册
│   ├─ Utils.lua        # 跨节点通信工具
│   ├─ lcoreex1.lua     # MsgCenter 专用配置缓存（版本追踪）
│   ├─ TQVip.lua        # VIP 模块业务逻辑
│   ├─ TQMonthCard.lua  # 月卡模块业务逻辑
│   ├─ NewDeposit.lua   # 金币模块业务逻辑
│   └─ ...              # 其他 40+ 业务模块
│
├─ luamodules/          # Module 配置层（定时器、文件监听、缓存初始化）
│   ├─ lconfigdata.lua  # 配置加载（热更新支持）
│   ├─ lcoreex.lua      # 定时器、文件监听（仅 usercmd 上下文可用）
│   ├─ TQVip.lua        # VIP 配置加载 + 定时器
│   ├─ AsynCacheDirtyCheck.lua  # 脏队列刷盘定时器
│   └─ ...              # 其他 40+ 模块配置层
│
├─ usercmd/             # 运维命令脚本
│   ├─ serverupdate.lua # 热重载脚本（moduleupdatemap + 版本递增）
│   ├─ start_test.lua   # 测试入口
│   ├─ lcmdcore.lua     # cmdcore Lua 包装
│   └─ ...
│
├─ pb/                  # Protobuf schema 文件
│   ├─ tqvip.pb
│   ├─ tqmonthcard.pb
│   └─ ...
│
├─ lcore.lua            # 日志封装（core 模块）
├─ lmsgcore.lua         # 消息编解码（msgcore 模块）
├─ ldbcore.lua          # DB 操作封装（dbcore 模块）
├─ lasyncache.lua       # 三级缓存实现
├─ ltimeutils.lua       # 时间工具
├─ functions.lua        # 通用函数（clone、split 等）
├─ protobuf.lua         # PB 编解码库
└─ lnodedef.lua         # 节点ID定义
```

---

## 三、MsgCenter 运行机制

### 3.1 main.lua 初始化流程

```lua
-- scripts/msgcenter/main.lua 结构

-- 1. 加载基础设施模块
local utils = require "scripts.msgcenter.Utils"
local lcore = require "scripts.lcore"
local lmsgcore = require "scripts.lmsgcore"
local lmsgdef = require "scripts.msgcenter.lmsgdef"

-- 2. 加载所有业务模块（40+）
local ExchangeCenter = require "scripts.msgcenter.ExchangeCenter"
local TQVip = require "scripts.msgcenter.TQVip"
local TQMonthCard = require "scripts.msgcenter.TQMonthCard"
-- ... 其他模块

-- 3. 创建消息分发器
local msgCener = { callbacklist = {} }

-- 4. 各模块注册消息 handler
TQVip:initmsg(msgCener)     -- 注册 VIP 相关消息
TQMonthCard:initmsg(msgCener)
-- ...

-- 5. im* 跨模块注入（monkey-patch）
NewDeposit.imGetPayOrder = function(...) return PayOrder:export_getpayorder(...) end
TQCheckin.imNewDepositOp = function(...) return NewDeposit:export_newdepositOp(...) end
TQMonthCard.imAddProps = function(...) return TQProp:addProps(...) end
-- ...

-- 6. 定义入口函数 main(udctx, udreq)
function main(udctx, udreq)
    xpcall(function()
        local lmsgpack = lmsgcore.makeMsgPack(udctx, udreq)
        msgCener:notify(lmsgpack)
    end, function(err)
        lcore.logwarn("%s", debug.traceback(err, 3))
    end)
end
```

### 3.2 消息分发器 — msgCener

```lua
-- 注册消息 handler
msgCener:register(msgid, func, pbname, nodemsg)
  -- msgid: 消息ID（如 450840 = GR_TQVIP_REQINFO）
  -- func: 处理函数，接收 (msgpack, decoded_pb_table)
  -- pbname: PB 类型名，用于解码请求体
  -- nodemsg: 是否为节点间消息（需额外解码 MsgPack wrapper）

-- 分发消息
msgCener:notify(lmsgpack)
  │
  ├─ 提取 lmsgpack.req.nRequest
  ├─ 查找 callbacklist[nRequest]
  ├─ 对每个注册的 handler：
  │     ├─ 解码 PB：msgpack:request2pb(pbname)
  │     └─ 调用：func(msgpack, decoded_table)
  └─ xpcall 包装，错误时打印完整 traceback
```

**注意**：同一消息ID可注册多个 handler，按注册顺序依次调用。

### 3.3 消息ID分配（lmsgdef.lua）

| 消息ID范围 | 模块 |
|-----------|------|
| 450160-450259 | NewDeposit（金币，59 个ID） |
| 450260-450269 | NewPlayerRegisterAward |
| 450270-450279 | TQCheckin |
| 450280-450289 | TQRelief |
| 450800-450809 | TQMonthCard |
| 450840-450849 | TQVip |
| ... | 其他模块 |

lmsgdef.lua 同时注册所有 PB schema：

```lua
protobuf.register_file("scripts/pb/tqvip.pb")
protobuf.register_file("scripts/pb/tqmonthcard.pb")
-- ...
```

---

## 四、Module 运行机制

### 4.1 配置加载 — lconfigdata.lua

```lua
-- 创建配置对象（带版本追踪）
config = lconfigdata.createconfigdata("TQMonthCardConfig.lua", function(newconfig)
    -- 文件变更时的回调
    lcoreex.mergeconfig("config", config.data, config.version)
end)

-- config 结构：{ data, path, version }
-- data: Lua table（配置内容）
-- version: 版本号（每次热更新递增）
```

**工作原理**：

1. `require("TQMonthCardConfig.lua")` 加载配置文件
2. `lcoreex.listenfilemod(path, 60, callback)` 注册文件监听（每 60 秒检查）
3. 文件变更时触发 callback，重新 require 并递增 version
4. 配置数据写入 `core_extern.write_config(key, data)` —— 存入 TcyLuaTableValue

### 4.2 定时器与文件监听 — lcoreex.lua

**仅 Module lua_State 可用**（MsgCenter 用 `lcoreex1.lua`，只有配置读取）。

```lua
-- 一次性定时器
lcoreex.starttimer(function()
    -- 60秒后执行
end, 60)

-- 循环定时器
local switch = { stop = false }
lcoreex.startlooptimer(function()
    if switch.stop then return end
    -- 每 60 秒执行一次
end, 60)

-- 停止：switch.stop = true

-- 文件变更监听
lcoreex.listenfilemod("TQMonthCardConfig.lua", 60, callback_id)
-- 每 60 秒检查文件 mtime，变更时触发 _TcyCallbackFunc_(callback_id)
```

### 4.3 跨模块数据共享

Module 的配置数据存入 TcyLuaTableValue 后，MsgCenter 可通过 `core_extern1.read_config(module_name)` 读取：

```lua
-- MsgCenter 中读取 Module 的配置
local vip_config = core_extern1.read_config("TQVip")
local monthcard_config = core_extern1.read_config("TQMonthCard")
```

**这就是 luamodules 和 msgcenter 的连接点**——配置层在 Module 中加载和热更新，业务层在 MsgCenter 中读取使用。

---

## 五、热重载完整流程

### 5.1 serverupdate.lua 触发

```
运维命令触发或启动时执行 serverupdate.lua
  │
  ├─ scriptupdate=true ?
  │     └─ core_minizip.minizip_unzip("scripts.zip")  // 解压新脚本
  │
  ├─ 遍历 moduleupdatemap（55 个模块）
  │     ├─ cmdcore.cmdcore_restart(name, script)
  │     │     ├─ 成功 → loginfo("xxx restart")
  │     │     └─ 失败 → cmdcore_stop + cmdcore_start（降级）
  │     └─ 每个模块独立 lua_State，缓存通过 swap 迁移
  │
  ├─ scriptupdate=true ?
  │     ├─ version = core_getiniint("luascripts", "msgcenterversion", 0)
  │     ├─ version = version + 1
  │     └─ core_writeiniint("luascripts", "msgcenterversion", version)
  │
  └─ 完成
```

### 5.2 MsgCenter 渐进式重建

各工作线程在下一条消息处理时检测版本变化，独立重建：

```
getMsgCenterLuaState()
  │
  ├─ INI msgcenterversion != cached_version ?
  │     ├─ lua_close(old_L)
  │     ├─ lua_open() + 注册 C 库
  │     ├─ luaL_loadfile("scripts/msgcenter/main.lua")
  │     ├─ lua_pcall() → 所有模块重新 require
  │     └─ cached_version = new_version
  │
  └─ 返回 lua_State
```

---

## 六、跨节点通信

### 6.1 Utils.lua 工具

```lua
-- 通知 assist 服务器
utils.notifyassit(msgid, userid, msgdata, pbname)

-- 广播所有用户
utils.notifyallusers(msgid, msgdata, pbname)

-- 发送到其他 chunk
utils.notifyotherchunk(msgid, msg, pbname)

-- 发送到 game 服务器
utils.notifygamesvr(msgid, msg, pbname)

-- 按 roomid 定向发送（查节点映射）
utils.notifynodemsgbyroomid(msgid, msg, pbname, roomid)
```

### 6.2 节点定义 — lnodedef.lua

```lua
ChunkSvr = 0
GameServer1-6 = 10-15
RoomServer1-6 = 20-25
RobotTool1-4 = 31-34
ChunkLog = 30

-- roomid → {game, room, robot} 映射
getNodeByRoomID(roomid) → {game_node, room_node, robot_node}
```

---

## 七、运行时数据流

```
TCP 消息到达 C++
  │
  ├─ nRequest 属于业务消息？
  │     └─ 路由到 MsgCenter lua_State
  │           │
  │           ▼
  │       C++ 调用 main(udctx, udreq)
  │           │
  │           ▼
  │       lmsgcore.makeMsgPack() → {req={nRequest, pDataPtr}, ctx={...}}
  │           │
  │           ▼
  │       msgCener:notify(msgpack)
  │           │
  │           ▼
  │       callbacklist[nRequest] → handler(pb_table)
  │           │
  │           ├─ 业务逻辑处理
  │           ├─ 调用 im* 注入函数（跨模块）
  │           ├─ dbcore 操作 MySQL/Redis
  │           └─ msgcore.sendrespone() 回包
  │
  └─ nRequest 属于运维命令？
      └─ 路由到 CmdScript lua_State
            │
            ▼
        doUserCmdScript(cmdscript)
            │
            └─ 执行后销毁 lua_State
```

---

## 八、关键文件速查

| 文件 | 作用 |
|------|------|
| `msgcenter/main.lua` | 入口、模块加载、im*注入、消息分发 |
| `msgcenter/lmsgdef.lua` | 消息ID定义、PB schema 注册 |
| `msgcenter/Utils.lua` | 跨节点通信工具 |
| `msgcenter/lcoreex1.lua` | MsgCenter 配置缓存（版本追踪） |
| `luamodules/lconfigdata.lua` | 配置加载 + 热更新 |
| `luamodules/lcoreex.lua` | 定时器、文件监听（Module专用） |
| `luamodules/AsynCacheDirtyCheck.lua` | 脏队列刷盘定时器 |
| `usercmd/serverupdate.lua` | 热重载脚本 |
| `lmsgcore.lua` | 消息编解码封装 |
| `lcore.lua` | 日志封装 |
| `lasyncache.lua` | 三级缓存实现 |
| `AsynCacheConfig.lua` | 缓存配置（MySQL→Redis 映射） |
| `lnodedef.lua` | 节点ID定义 |