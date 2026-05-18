# L0 全局索引 - gamesvrDev

> 游戏服务工程师工作区全局索引

---

## 核心职责

负责 VS2013 下 C++ 游戏服务的编写，主要负责四川麻将游戏服务。

### 主要工作内容

1. **游戏服务开发** — 金币版/银子版四川麻将服务开发，游戏逻辑实现
2. **模板代码查阅** — tcGame/xyGame 模板、麻将/跑牌游戏基类
3. **问题排查** — 服务端 Bug 修复、性能优化、协议调试

---

## 技术栈

| 技术 | 说明 |
|------|------|
| C++ | 主要开发语言 |
| VS2013 | 开发环境 |
| TCP/UDP | 网络通信 |
| SVN | 版本控制 |

---

## 工作区索引

| 工作区 | 路径 | 说明 |
|--------|------|------|
| 金币版四川麻将（血流血战） | https://192.168.102.112/svn/xzmopc/branches/douque/jinbi (SVN) | 金币版服务代码 |
| 银子版四川麻将（血流血战） | D:\Codlib\douque\xzmx\xzmoNewPC\branches\douque\deposit | 银子版服务代码 |
| 金币版四川麻将（血流六红中） | D:\Codlib\douque\xzmx\xzmsPC\branches\pve\zhong | 金币六红中服务代码 |
| 模板源码 | D:\LibraryVC12_P | 通用模板库 |
| tcGame 模板 | D:\LibraryVC12_P\tcGame2.0\trunk | 通用游戏模板 |
| xyGame 模板 | D:\LibraryVC12_P\xyGame2.0\trunk | 通用游戏模板 |
| xyMJBase 模板 | D:\LibraryVC12_P\xyMJBase4.0\trunk | 麻将基础框架 |
| 麻将游戏基类 | D:\LibraryVC12_P\tcgMJ2.0\trunk | 四川麻将游戏框架 |
| 跑牌游戏基类 | D:\LibraryVC12_P\tcgSK2.0\trunk | 斗地主游戏框架 |

---

## 架构规约

1. **模板优先**：游戏服务大量使用模板简化业务层开发
2. **分离开发**：客户端、服务端业务代码与模板分离
3. **查阅模板**：如需了解库内实现逻辑，需查询相应模板代码

---

## 版本文档索引

> 三个游戏服务版本共用模板继承链，各自业务关注点不同。
> 原型文档与实现文档存放在对应版本的 `xxxxDoc/` 目录下。

| 目录 | 象征名 | 版本说明 | 文档重点 |
|------|--------|----------|----------|
| [xzmo2Doc/](xzmo2Doc/) | xzmo2 | 银子版四川麻将（血流血战） | 对局流程、活动内容 |
| [xzmoDoc/](xzmoDoc/) | xzmo | 金币版四川麻将（血流血战） | 游戏流程、金币接入、金币金豆兼容、好友房、结算流程 |
| [xzmsDoc/](xzmsDoc/) | xzms | 金币版四川麻将（血流六红中） | 金币接入、六红中玩法差异 |

---

---

## ⚠️ Encoding: GBK for C/C++ (MUST READ before editing .cpp/.h)

All `.c` `.cpp` `.h` `.hpp` files are GBK-encoded (code page 936). Writing UTF-8 corrupts Chinese comments.

**NEVER use Edit/Write/Read tools on C/C++ files.** Use these instead:

| Action | Tool | Method |
|--------|------|--------|
| Read | Bash | `python -c "import sys; f=open(sys.argv[1],'r',encoding='gbk'); print(f.read())" "<PATH>"` |
| Write | Bash | `cat <<'EOF' \| python -c "import sys; open(sys.argv[1],'w',encoding='gbk').write(sys.stdin.read())" "<PATH>"` |
| Edit | Bash | `python <<'PYEOF'\npath="PATH"\nold="""OLD"""\nnew="""NEW"""\nc=open(path,'r',encoding='gbk').read()\nassert old in c and c.count(old)==1, 'not unique'\nc=c.replace(old,new)\nopen(path,'w',encoding='gbk').write(c)\nPYEOF` |

All other file types (.ts/.js/.json/.md/.py) use standard tools (UTF-8).

---

## Test Execution

Test code written in `main()` entry, auto-runs only under `DEBUG` build. CPP compilation is heavyweight — ensure code quality is high before building.

Pattern — wrap test call with `#ifdef DEBUG`:

```cpp
int main() {
#ifdef DEBUG
    // TODO: TestTool::RunAllTests();  // or equivalent
    return 0;
#endif
    // normal server startup...
}
```

Flow: check if test hook exists in `main()` → if not, add one → compile DEBUG → run → verify output. See [CPPCompileAndRunHelp.md](CPPCompileAndRunHelp.md) for build & run instructions.

> ⚠️ **验证点**：确保 `#ifdef DEBUG` 块内测试通过后确实有 `return 0;`。实际源码可能使用 `execAllTest()` 模式，若通过后未 return 则会继续初始化服务。参见编译文档"陷阱 4"。

## 文档索引

| 文档 | 路径 | 说明 |
|------|------|------|
| 工作流 | [WorkFlow/CPP-GameSVR-DEV-xzmp_WorkFlow.md](../WorkFlow/CPP-GameSVR-DEV-xzmp_WorkFlow.md) | BDD 描述 — 启动后行为、编码规则、DEBUG 测试流程 |
| 编译调试指南 | [CPPCompileAndRunHelp.md](CPPCompileAndRunHelp.md) | VSCode + VS2013 编译、调试配置 |
| 模板继承链 | [TemplateDoc/L1_TemplateChain.md](TemplateDoc/L1_TemplateChain.md) | CMainServer → CMjServer/CMjTable → 各版本定制 |
| 礼包数据服务 | [L1_ChunkSvr.md](L1_ChunkSvr.md) | ChunkSvr — 金币版核心数据后端，管理活动配置/数据库更新/发奖 |
| 活动模块索引 | [L1_ChunkSvr_ActivityModules.md](L1_ChunkSvr_ActivityModules.md) | ChunkSvr 16个线上活动模块总览（MySQL/Redis/PB/缓存方式/依赖关系） |
| 构造原理 | [L2_ChunkSvr_Architecture.md](L2_ChunkSvr_Architecture.md) | ChunkSvr C++/Lua混合架构、C库导出、三级缓存、热重载、线程安全 |
| 运行机制 | [L2_ChunkSvr_Runtime.md](L2_ChunkSvr_Runtime.md) | scripts 目录运作、启动流程、消息分发、配置加载、跨节点通信 |

---

## 协作角色

| 协作角色 | 说明 |
|------|------|
| **CP-DEV-xzmp** | 新礼包服务、积分兑换 — 仅与 xzmo / xzms 金币版兼容 |
| **Creator-Client-DEV-xzmp** | 新客户端 — 仅与 xzmo / xzms 金币版兼容 |
| **LUA-Client-DEV-xzmp** | 旧版 Lua 客户端 — 与全部版本兼容（已停止开发） |

> **关键约束**：CP-DEV-xzmp 和 Creator-Client-DEV-xzmp 做的积分内容仅与金币版服务（xzmo、xzms）兼容，与银子版（xzmo2）无关。
