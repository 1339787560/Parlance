# L1 功能插件模块

## 模块职责

提供游戏内各业务功能模块，按功能独立划分。

## 插件目录结构

```
assets/plugins/
├── abtpay/           # 支付功能
├── bag/              # 背包系统
├── bankrupt/         # 破产系统
├── chat/             # 聊天功能
├── checkin/          # 签到系统
├── cmdecoration/     # 装饰系统
├── cmmonthcard/      # 月卡系统
├── common_skin/      # 公共皮肤
├── customerservice/  # 客服系统
├── division/         # 段位系统
├── dressgift/        # 时装礼物
├── email/            # 邮件系统
├── frdroom/          # 好友房
├── freefail/         # 免费救济
├── goldbank/         # 金币银行
├── hall/             # 大厅模块
├── joyfulgift/       # 欢乐折扣
├── leveldefine/      # 荣耀特权
├── login/            # 登录模块
├── luckyturntable/   # 幸运转盘
├── opinioncollect/   # 意见收集
├── personalinfo/     # 个人信息
├── relief/           # 救济系统
├── report/           # 举报系统
├── resurrect/        # 复活礼包
├── rules/            # 规则说明
├── rulesmake/        # 规则制定
├── setting/          # 设置模块
├── shake/            # 摇一摇
├── shop/             # 商城系统
├── task/             # 任务系统
├── timecountdown/    # 时间倒计时
├── timedlogin/       # 定时登录
├── tomorrowaward/    # 明日奖励
├── upgradenotice/    # 升级通知
├── vote/             # 投票系统
├── webactivity/      # 网页活动
└── welfare/          # 福利系统
```

## 核心插件说明

### 登录模块 (login/)

**职责**: 用户登录认证

**功能**:
- 账号登录
- 微信授权
- 游客登录
- Token 管理

### 大厅模块 (hall/)

**职责**: 游戏大厅

**功能**:
- 房间列表
- 快速匹配
- 创建房间
- 好友房入口

### 商城系统 (shop/)

**职责**: 虚拟商品购买

**功能**:
- 商品展示
- 购买流程
- 支付集成

### 好友房 (frdroom/)

**职责**: 私人房间管理

**功能**:
- 创建房间
- 邀请好友
- 规则设置
- 房间记录

### 聊天功能 (chat/)

**职责**: 玩家交流

**功能**:
- 文字聊天
- 表情发送
- 语音消息
- 快捷短语

### 任务系统 (task/)

**职责**: 任务管理

**功能**:
- 每日任务
- 成就系统
- 奖励领取

## 游戏内扩展模块

```
assets/game/extensions/
├── ChatPlugin/       # 游戏内聊天
├── HallPlugin/       # 游戏内大厅入口
├── SettingPlugin/    # 游戏内设置
└── WebactivityPlugin/ # 游戏内活动
```

## 插件开发规范

### 目录结构

```
plugin_name/
├── scripts/          # 脚本文件
├── res/              # 资源文件
│   ├── prefabs/      # 预制体
│   ├── textures/     # 纹理
│   └── audio/        # 音频
└── config/           # 配置文件
```

### 命名规范

- 插件目录: 小写字母，下划线分隔
- 脚本文件: PascalCase
- 预制体: 小写字母，下划线分隔

## 注意事项

1. **模块独立**: 插件间避免强耦合
2. **资源管理**: 插件资源独立管理
3. **事件通信**: 使用事件中心进行跨插件通信
