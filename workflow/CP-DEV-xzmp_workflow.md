# CP-DEV-xzmp 工作流

## 启动顺序

场景：新会话开始
前提 用户打开新的 CP-DEV-xzmp 会话
当 第一条消息到达时
那么 角色静默执行以下启动流程：
- `curl GET /list` → 发现角色文件夹
- `curl GET /get?path=COMMON.md` → 公共规则
- `curl GET /get?path=CP-DEV-xzmp/L0_Index.md` → L0 索引
- 根据 L0 索引按需加载 L1/L2
- 全程不向用户报告启动步骤

## 直接修改代码

场景：用户要求修改现有 TS 脚本
前提 角色已完成启动
且 任务涉及 .ts 文件
当 用户说"修改文件 Y 中的函数 X"
那么 角色识别文件类型 (.ts) → UTF-8，标准工具
且 重新拉取 L0 的"Test Execution"节获取测试命令
且 直接进行代码修改
且 不加载 BestPractices（直改，无设计决策）

场景：用户要求修改 C++ 文件
前提 角色已完成启动
且 任务涉及 .cpp/.h 文件
当 用户说"修改文件 Y 中的函数 X"
那么 角色识别文件类型 (.cpp) → **必须使用 GBK 编码**
且 使用 gbk_read/gbk_write/gbk_edit 通过 Bash 操作
且 绝对不使用 Edit/Write/Read 工具操作 C/C++ 文件
且 不确定时重新拉取 L0 的"Encoding: GBK"节

## 执行测试

场景：用户要求运行测试
前提 角色已完成启动
当 用户说"测试模块 X"
那么 角色加载 BestPractices（`curl GET /get?path=common/AI_Tool_BestPractices.md`）
且 重新拉取 L0 的"Test Execution"节获取精确命令
且 执行：`NODE_TLS_REJECT_UNAUTHORIZED=0 node --loader ts-node/esm node_modules/ts-node/dist/bin.js src/xzmp/<module>.ts`
且 报告结果给用户

## 设计新功能

场景：用户提出新功能需求
前提 角色已完成启动
当 用户说"我需要一个 X 模块"
那么 角色加载 BestPractices（`curl GET /get?path=common/AI_Tool_BestPractices.md`）
且 追问需求细节
且 提出 2-3 个方案选项
且 等待用户指示后再实现
