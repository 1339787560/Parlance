# CPP-GameSVR-DEV-xzmp 工作流

## 启动顺序

场景：新会话开始
前提 用户打开新的 CPP-GameSVR-DEV-xzmp 会话
当 第一条消息到达时
那么 角色静默执行以下启动流程：
- `curl GET /list` → 发现角色文件夹
- `curl GET /get?path=COMMON.md` → 公共规则
- `curl GET /get?path=CPP-GameSVR-DEV-xzmp/L0_Index.md` → L0 索引
- 等待用户确认三个子版本（xzmo/xzmo2/xzms）之一，未确认不加载 L1/L2
- 根据确认的版本和 L0 索引按需加载对应 L1/L2
- 全程不向用户报告启动步骤

## 修改 C++ 代码

场景：用户要求修改 C++ 源文件
前提 角色已完成启动
且 任务涉及 .cpp 或 .h 文件
当 用户说"修改文件 Y 中的函数 X"
那么 角色识别文件类型 (.cpp/.h) → **必须使用 GBK 编码**
且 通过 Bash 使用 gbk_read/gbk_write/gbk_edit（python -c 指定 encoding='gbk'）
且 绝对不使用 Edit/Write/Read 工具操作 C/C++ 文件
且 不确定时重新拉取 L0 的"Encoding: GBK"节获取精确命令
且 修改完成后用 gbk_read 验证内容

场景：用户要求创建新的 .cpp 文件
前提 角色已完成启动
当 用户说"创建新文件 Y.cpp"
那么 角色通过 Bash 使用 gbk_write，内容通过 python 管道传入
且 如适用则包含 `#ifdef DEBUG` 测试钩子

## 执行测试

场景：用户要求运行测试
前提 角色已完成启动
当 用户说"测试"或"运行测试"
那么 角色加载 BestPractices（`curl GET /get?path=common/AI_Tool_BestPractices.md`）
且 重新拉取 L0 的"Test Execution"节
且 检查 `main()` 是否已有 `#ifdef DEBUG` 测试钩子
    - 已有 → 编译 DEBUG 并运行
    - 缺失 → 先添加测试钩子，再编译 DEBUG 并运行
且 验证输出

## 编译

场景：用户要求编译
前提 角色已完成启动
当 用户说"编译"或"构建"
那么 角色重新拉取 L0 获取编译指南参考
且 按照 CPPCompileAndRunHelp.md 中的说明操作
且 报告编译结果

## 设计新功能

场景：用户提出新的游戏功能
前提 角色已完成启动
当 用户说"我需要功能 X"
那么 角色加载 BestPractices（`curl GET /get?path=common/AI_Tool_BestPractices.md`）
且 追问需求细节
且 提出 2-3 个方案选项，考虑：
    - 模板继承链影响
    - 影响哪个版本（xzmo/xzms/xzmo2）
    - 所有新 C++ 文件使用 GBK 编码
    - 是否包含 `#ifdef DEBUG` 测试钩子
且 等待用户指示
