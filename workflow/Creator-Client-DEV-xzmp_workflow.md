# Creator-Client-DEV-xzmp 工作流

## 启动顺序

场景：新会话开始
前提 用户打开新的 Creator-Client-DEV-xzmp 会话
当 第一条消息到达时
那么 角色静默执行以下启动流程：
- `curl GET /list` → 发现角色文件夹
- `curl GET /get?path=COMMON.md` → 公共规则
- `curl GET /get?path=Creator-Client-DEV-xzmp/L0_Index.md` → L0 索引
- 根据 L0 索引按需加载 L1/L2
- 全程不向用户报告启动步骤

## 修改代码

场景：用户要求修改 TS/UI 脚本
前提 角色已完成启动
且 任务涉及 .ts 文件（CocosCreator）
当 用户说"修改组件 X"
那么 角色识别文件类型 (.ts) → UTF-8，标准工具
且 重新拉取 L0 获取相关模块文档
且 直接进行代码修改
且 不加载 BestPractices（直改，无设计决策）

## 执行测试

场景：用户要求运行测试
前提 角色已完成启动
当 用户说"测试模块 X"
那么 角色加载 BestPractices（`curl GET /get?path=common/AI_Tool_BestPractices.md`）
且 重新拉取 L0 的"Test Execution"节
且 告知用户：测试通过 CocosCreator 引擎中的场景按钮触发
且 告诉用户需要点击哪些测试入口
且 等待用户操作并反馈结果

## 设计新功能

场景：用户提出新的 UI 功能或插件
前提 角色已完成启动
当 用户说"我需要一个 X 插件"
那么 角色加载 BestPractices（`curl GET /get?path=common/AI_Tool_BestPractices.md`）
且 追问需求细节
且 提出 2-3 个方案选项，考虑：
    - 插件架构模式（Plugin → ViewCtrl → Help → View → Def）
    - 事件驱动通信
    - MVC 模式，基于现有基类
    - 必须暴露测试入口
且 等待用户指示
