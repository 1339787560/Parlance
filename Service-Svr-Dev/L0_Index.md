# L0 全局索引 - serviceSvrDev

> 综合体工具工程师工作区全局索引

---

## 核心职责

负责编写 Python Flask + 前端 HTML/CSS/JS，提供 HTTP API 工具和可视化工具。

---

## 技术栈

| 技术 | 说明 |
|------|------|
| Python | 后端语言 |
| Flask | Web 框架 |
| HTML/CSS/JS | 前端技术 |
| Git | 版本控制 |

---

## 工作区索引

| 工作区 | 路径 | 说明 |
|--------|------|------|
| 工作区 | D:\Codlib\VscodeCodlib\Python\serviceServer | 主目录 |
| A2A工作区 | D:\Codlib\VscodeCodlib\Python\serviceServer\src\A2AFile | Agent 协作系统 |
| 路由部分 | D:\Codlib\VscodeCodlib\Python\serviceServer\CustomRoute | Flask 路由 |
| Flask模板 | D:\Codlib\VscodeCodlib\Python\serviceServer\CustomRoute\templates | HTML 模板 |
| 通用工具 | D:\Codlib\VscodeCodlib\Python\serviceServer\CommonTools | 工具库 |

---

## 架构规约

1. **路由分离**：路由代码在 CustomRoute/，模板在 templates/
2. **工具复用**：通用工具放在 CommonTools/
3. **A2A 维护**：负责维护 Agent 协作系统

---

## 文档索引

| 文档 | 路径 | 说明 |
|------|------|------|
| 角色描述 | [serviceSvrDev.md](serviceSvrDev.md) | 角色职责、工作范围、协作关系 |
| roomsvr 故障验证 | [故障验证_roomsvr高级场开局失败.md](故障验证_roomsvr高级场开局失败.md) | 三个 Bug 的单元测试/集成测试规范，用于验证修复 |
| 线上故障分析 | [onlineErrorBrief20260514.md](onlineErrorBrief20260514.md) | roomsvr 高级场开局失败线上日志分析 |

---

## 协作角色

- **gamesvrDev** - 游戏服务相关问题
- **clientDev** - 客户端相关问题
- **CPDev** - 礼包服务相关问题
