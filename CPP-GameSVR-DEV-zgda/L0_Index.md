# L0 全局索引 - gamesvrDev (斗地主)

> 斗地主游戏服务工程师工作区全局索引

---

## 核心职责

负责 VS2013 下 C++ 斗地主游戏服务及相关礼包、配置、残局机器人服务的编写与维护。

### 主要工作内容

1. **斗地主游戏服务开发** — 金币版斗地主游戏逻辑实现
2. **礼包服务维护** — 斗地主礼包数据服务（ChunkSvr 同架构）
3. **配置中心维护** — 斗地主配置中心服务
4. **残局机器人服务** — 斗地主残局辅助机器人服务
5. **问题排查** — 服务端 Bug 修复、性能优化、协议调试

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
| 斗地主游戏+礼包服务 | D:\Codlib\douque\zdga\svr\trunk | 主要工作目录 — 游戏逻辑+ChunkSvr礼包 |
| 配置中心 | D:\Codlib\douque\zdga\zgdb\trunk | 配置中心服务 |
| 残局机器人服务 | D:\Codlib\douque\zdga\zgdf\trunk\zgdfassitsvr | 残局辅助机器人 |
| 模板源码 | D:\LibraryVC12_P | 通用模板库 |
| tcGame 模板 | D:\LibraryVC12_P\tcGame2.0\trunk | 通用游戏模板 |
| xyGame 模板 | D:\LibraryVC12_P\xyGame2.0\trunk | 通用游戏模板 |
| 跑牌游戏基类 | D:\LibraryVC12_P\tcgSK2.0\trunk | 斗地主游戏框架 |

---

## 架构规约

1. **模板优先**：游戏服务大量使用模板简化业务层开发，服务端模板与川麻一致
2. **分离开发**：客户端、服务端业务代码与模板分离
3. **查阅模板**：如需了解库内实现逻辑，需查询相应模板代码

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

Flow: check if test hook exists in `main()` → if not, add one → compile DEBUG → run → verify output.

> ⚠️ **验证点**：确保 `#ifdef DEBUG` 块内测试通过后确实有 `return 0;`。实际源码可能使用 `execAllTest()` 模式，若通过后未 return 则会继续初始化服务。

---

## 文档索引

| 文档 | 路径 | 说明 |
|------|------|------|
| 工作流 | [WorkFlow/CPP-GameSVR-DEV-zgda_WorkFlow.md](../WorkFlow/CPP-GameSVR-DEV-zgda_WorkFlow.md) | BDD 描述 — 启动后行为、编码规则、DEBUG 测试流程 |
| 礼包数据服务 | [L1_ChunkSvr.md](L1_ChunkSvr.md) | ChunkSvr 44个模块总览 — 付费礼包/订阅/活动/竞技/道具/辅助 |
| 超级加倍卡 | [L3_SuperDoubleCard.md](L3_SuperDoubleCard.md) | 超级加倍卡道具定义、存储、购买、生效全链路 |

---

## 协作角色

| 协作角色 | 说明 |
|------|------|
| **CP-DEV-xzmp** | 礼包服务、积分兑换（川麻侧） |
| **CPP-GameSVR-DEV-xzmp** | 川麻游戏服务（模板共享） |

---

## 注意事项

- 服务端模板与川麻（xzmp）一致，可参考 CPP-GameSVR-DEV-xzmp 的模板继承链文档
- 斗地主使用跑牌游戏基类（tcgSK），与川麻的麻将基类（tcgMJ）不同