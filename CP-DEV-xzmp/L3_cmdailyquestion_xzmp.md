# cmdailyquestion 模块详情

## 基本信息

| 属性 | 值 |
|------|-----|
| 模块名 | cmdailyquestion |
| 脚本文件 | cmdailyquestion_xzmp.ts |
| 配置文件 | cmdailyquestion_xzmp.jsonc |
| GAME_CODE | xzmp |
| GAME_ID | 283 |

## 功能概述

每日问答 — 玩家每日答题获取金币奖励，错题次日优先复习。每日0点刷新题库，5种题型各2题共10题，每题2选项随机顺序。答对每题获3000金币，全对额外5倍加成。每日只能答一次，领奖后当日不可再答。

## 主要函数

### 客户端请求处理

| 消息名 | 说明 | 请求参数 | 响应数据 |
|--------|------|----------|----------|
| GR_TQDAILYQUESTION_REQINFO | 获取今日题目 | 无 | `{ status, questions, answerednum, totalcount }` |
| GR_TQDAILYQUESTION_REQANSWER | 提交答案 | `{ questionid, answer }` | `{ status, correct, correctoption, explain, prize, totalprize }` |
| GR_TQDAILYQUESTION_REQPRIZE | 领取奖励 | 无 | `{ status, prize, allcorrect }` |

### 服务端推送消息

| 消息名 | 说明 | 推送数据 |
|--------|------|----------|
| notifyDailyQuestionRefresh | 每日刷新通知 | 无 |

### 内部模块调用

| 消息名 | 说明 |
|--------|------|
| getDailyQuestionPlayerData | 获取玩家数据 |
| resetDailyQuestionData | 重置每日数据（定时任务调用） |

### 其他回调

| 回调 | 说明 |
|------|------|
| OnScriptReload | 加载配置 |

## 数据结构

### GameConfig（配置）

```typescript
interface GameConfig {
    isenable: number;              // 开关，1启用/0禁用
    guid: string;                  // 发奖兑换ID
    typenum: number[];             // 各类型题目数量 [2,2,2,2,2]
    prize: number;                 // 每题答对奖励金额
    rulesDesc: string;             // 规则描述
    allcorrect: number;            // 全对额外奖励倍数
    questionnumlimit: number;      // 每日题目上限（预留）
    subject: SubjectItem[];        // 题目列表
}

interface SubjectItem {
    id: number;                    // 题目唯一标识
    type: number;                  // 题目类型 1-5
    content: string;               // 题目内容
    explain: string;               // 答题解析
    options: string[];             // 选项列表，答案放首位
    huinfos?: HuInfo[];            // 牌型展示信息（可选）
}

interface HuInfo {
    type: number;                  // 牌区类型：1暗杠/2明杠/3碰/4手牌
    cardidxs: number[];            // 牌索引列表
}
```

### PlayerData（玩家数据）

```typescript
class PlayerData {
    datetag: number;               // 当前答题日期 YYYYMMDD
    answerednum: number;           // 已答题数量（领取后+1标记已领取）
    items: QuestionItem[];         // 今日题目列表
    lastdayquestions: number[];    // 上次错题ID列表
}

class QuestionItem {
    id: number;                    // 题目ID
    answer: number;                // 答题状态：0未答/1正确/>2错误(选项序号+1)
    optionorder: number[];         // 选项显示顺序（随机打乱后的索引）
}
```

### 答案编码规则

| 编码值 | 含义 |
|--------|------|
| 0 | 未答 |
| 1 | 正确 |
| >=2 | 错误（所选选项序号+1，避免与正确编码1冲突） |

## 依赖模块

无（独立模块）

## 消息号列表

| 常量名 | 值 | 方向 |
|--------|-----|------|
| REQINFO | GR_TQDAILYQUESTION_REQINFO | From Client |
| REQANSWER | GR_TQDAILYQUESTION_REQANSWER | From Client |
| REQPRIZE | GR_TQDAILYQUESTION_REQPRIZE | From Client |
| NOTIFY_REFRESH | notifyDailyQuestionRefresh | To Client |
| RESET_DAILY | resetDailyQuestionData | Internal |
| GET_PLAYER_DATA | getDailyQuestionPlayerData | Internal |

## 存储结构

| 存储 | 标识 |
|------|------|
| MySQL 表 | tblcpuserdata_cmdailyquestion_xzmp，name 字段: "PlayerData" |
| Redis Key | mod(cp):name(cmdailyquestion):appcode(xzmp):uid({uid}):playerdata，过期: 7天 |
| Redis Lock | mod(cp):name(cmdailyquestion):appcode(xzmp):uid({uid}):lock，TTL: 5秒 |

## 核心流程

### 进入界面 (REQINFO)

1. 查询玩家数据（Redis优先，miss回源MySQL）
2. 检查日期变更 → 生成新题库
3. 错题优先补充：lastdayquestions按类型配额填充
4. 新题补充：按typenum配额随机选题
5. 最终随机打乱题目顺序
6. 构建返回题目列表（选项按optionorder重排）

### 答题 (REQANSWER)

1. 校验已答完/题目ID/已回答
2. checkAnswer判断正确性
3. 编码answer：正确=1，错误=选项序号+1
4. 错题记入lastdayquestions
5. 计算累计奖励calculatePrize
6. 返回答题结果+解析+奖励

### 领奖 (REQPRIZE)

1. 校验答完所有题
2. calculatePrize计算最终奖励
3. 调用goldbank发放奖励（propid=21770）
4. answerednum++标记已领取

### 奖励计算

- 基础奖励 = 答对数 × prize
- 全对加成 = 基础奖励 × allcorrect
- 全对示例：10题全对 = 30000 × 5 = 150000

### 错题复习

昨日答错题目ID记入lastdayquestions，次日生成题库时按类型配额优先填充错题，超出配额的错题继续保留。

## 牌型展示

部分题目含huinfos字段，展示麻将牌型。牌索引映射：

| 范围 | 牌面 |
|------|------|
| [1,9] | 1万-9万 |
| [11,19] | 1条-9条 |
| [21,29] | 1筒-9筒 |
| [35] | 红中 |

牌区类型：1暗杠/2明杠/3碰/4手牌

## 错误码

| status | 说明 |
|--------|------|
| 0 | 成功 |
| 1 | 配置不存在/模块未启用 |
| 2 | 玩家数据获取失败 |
| 3 | 已答完(REQANSWER) / 未答完(REQPRIZE) / 已领取 |
| 4 | 题目ID不匹配 |
| 5 | 题目已回答 |
| 6 | 持久化存储失败 |

## 常量定义

```typescript
const CONST_VAR = {
    MODULE_NAME: 'cmdailyquestion',
    GAME_CODE: 'xzmp',
    APP_CODE: 'xzmp',
    GAME_ID: 283,
    DAY_SECONDS: 86400,
}
```
