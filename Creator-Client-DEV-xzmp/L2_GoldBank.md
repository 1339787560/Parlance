# L2 金库系统 (GoldBank) — 客户端全流程解析

## 概述

**插件名**: goldbank  
**目录**: `assets/plugins/goldbank/`  
**功能**: 金豆金库 + 银子保险箱，支持存取、等级权限、自动存取、密码保护

## 核心架构

```
GoldBankPlugin.ts         插件入口 — 注册视图、Socket 处理器、Data Reducer
GoldBankConfig.ts         常量/配置/Protocol Buffer 声明/Serializer 声明
GoldBankHelp.ts           静态工具函数
SafeBoxException.ts       保险箱异常处理

view/
├── GoldBankViewCtrl.ts   视图控制器 — 数据源、Action 路由
├── GoldBankView.ts       主视图 — 金库界面 UI、档位计算
├── GoldBankInputView.ts  自定义金额输入界面
├── GoldBankQAView.ts     Q&A 规则弹窗
├── GoldBankSaveInPanel.ts 超携带上限自动存入提示面板
├── GoldBankSaveOrTakeItem.ts 快捷存取档位 item
├── GoldBankNode.ts       大厅/结算槽位节点
├── SafeBoxInputCtrl.ts   保险箱密码视图控制器
├── SafeBoxInputPwdLayer.ts 保险箱密码输入层
└── SafeBoxNumPad.ts      保险箱数字键盘

action/
├── action_querygoldbankbalance.ts    查询金库余额
├── action_getgoldbankbalance.ts      从本地 DataStore 读取余额
├── action_querysafeboxinfo.ts        查询保险箱信息
├── action_putscoretobank.ts          金豆存入金库
├── action_takescorefrombank.ts       从金库取出金豆
├── action_putdeposittobox.ts         银子存入保险箱
├── action_takedepositfrombox.ts      从保险箱取银(含密码)
├── action_getrndkey.ts               获取 rndKey(密码验证用)
└── con_checkgoldbanktimevalid.ts     检测金库有效期条件
```

## 双货币系统

| 货币 | 系统名 | 通信方式 | 存取操作 |
|------|--------|----------|----------|
| 金豆 (GoldBean) | GoldBank | Protobuf (PB) | Action_PutScoreToBank / Action_TakeScoreFromBank |
| 银子 (Deposit) | SafeBox / 保险箱 | Serializer | Action_PutDepositToBox / Action_TakeDepositFromBox |

根据 `ct.getGameCurrencyType()` 判断当前货币类型，路由到对应操作。

## 初始化流程

```
GoldBankPlugin.onInit()
├── 注册 4 个视图 (addPopupView)
│   ├── GoldBankView (遮罩, 不可点击关闭)
│   ├── GoldBankInputView (无遮罩, 可点击关闭)
│   ├── GoldBankQAView (遮罩, 可点击关闭)
│   └── GoldBankSaveInPanel (遮罩, 可点击关闭)
├── 注册 Socket 处理器
│   ├── PB_CP__CLIENT_NOTIFY → ntfMsgFromCP (等级变化通知)
│   └── PB_NOTIFY__NTF_REWARD → ntfRewardMessage (道具奖励通知)
└── 启动时查询
    ├── GoldBankHelp.queryGoldBankCfg() → 获取配置 + 玩家等级信息
    └── GoldBankHelp.queryGoldBankBalance() → 查询余额
```

## Data Reducer 状态树

```
state = {
    [DataType.CfgInfo]: null,           // goldBankCfg 配置
    [DataType.Balance]: 0,              // 余额
    [DataType.RndKey]: 0,               // 保险箱随机密钥
    [DataType.HasSecurePwd]: false,     // 是否设置了安全密码
    [DataType.HasSecurePwdInGame]: false,
    [DataType.PlayerLevelInfo]: null,   // 玩家等级信息(来自 CP)
}
```

## 金库配置 (goldBankCfg)

| 字段 | 说明 |
|------|------|
| `boutlimit` | 局数限制 |
| `freelimit` | 免费次数限制 |
| `oncesavelimit` | 单次存入上限 |
| `savelowlimit` | 单次存入下限 |
| `takelowlimit` | 单次取出下限 |
| `maxReserveNum` | 最大携带限制(自动存触发阈值) |
| `minReserveNum` | 最小携带限制(自动取目标值) |
| `startdate/enddate` | 活动有效期 |
| `quickSaveArray` | 快捷存取比例数组(0~1) |
| `ruleText` | 规则文本 |
| `wxios.freelimit` | 微信 iOS 专用免费次数 |

## 主视图 (GoldBankView) — 界面逻辑

### 初始化 onLoad
- 读取 quickSaveArray 长度(最多5个)，创建对应数量的快捷档位预制体

### 数据更新 onUpdateView
- **Wealth 变更**: 更新玩家携带数、余额、档位信息
- **PlayerLevelInfo 变更**: 
  - 显示等级 `LV.{grade}`
  - 计算当前等级可存上限 / 下一级可存上限
  - 降级提示(红字)
  - 富文本展示下一级提示
- **PageView 变更**: 
  - 切换存入/取出分页标记
  - 更新携带上限提示文字

### 档位计算 (updateItemInfo)
```
可用档位 = quickSaveArray.filter(每个比例 => {
    金额 = ceil((携带 + 余额) * 比例)
    (金额 >= 下限) && (存: 金额+余额 <= 最大存入限制)
})
```

### 快捷档位可见性 (GoldBankSaveOrTakeItem.updateGoldBeanNumber)
每个档位按条件判断隐藏/显示：
- **存入状态**: 存入后携带 >= 最小携带
- **取出状态**: 取出后携带 <= 最大携带
- **超出上限**: 显示"全部"或限制值
- **上一档已不满足**: 所有后续档位隐藏

### 视图切换
- `onClickSaveCurry` → tabId=0 (存入)
- `onClickTakeCurry` → tabId=1 (取出)
- 缓存 tabId 到 UserCache

## 存取流程

### 快捷存取
```
点击档位 → GoldBankSaveOrTakeItem.onClickSaveOrTake()
  ├── 存入: postAction(ACT_Req_SaveGoldBean, value)
  └── 取出: postAction(ACT_Req_TakeGoldBean, value)
```

### 自定义输入
```
点击输入框 → popupInputView() 弹 GoldBankInputView
  ├── 数字键盘输入 → judgeIsLegalSaveNum() / judgeLegalGetNum() 校验
  ├── 存入校验: 单次上下限 / 携带上下限 / 权限上限 / 不超携带
  ├── 取出校验: 单次下限 / 携带上限 / 余额充足
  └── 确认 → postAction 路由到 ViewCtrl
```

### ViewCtrl Action 路由
```
ACT_Req_SaveGoldBean  → GoldBankHelp.saveToGoldBean()
ACT_Req_TakeGoldBean  → GoldBankHelp.takeFromGoldBean()
ACT_Change_Page       → 更新 tabId + 缓存

GoldBankHelp 根据货币类型路由到对应 Action:
  金豆: Action_PutScoreToBank / Action_TakeScoreFromBank
  银子: Action_PutDepositToBox / Action_TakeDepositFromBox
```

### Action 流程

#### 金豆存入 (Action_PutScoreToBank)
```
1. 校验: moveScore > 0, 携带 >= moveScore
2. 区分大厅/游戏内 → 拼装不同 PB 参数
3. hallSocket/gameSocket.sendRequest(PB_SAVE_BACKSCORE)
4. 成功回调:
   - syncBoxAndUserInfo: 更新本地余额 + 携带 + reportPlayerBalance
   - 提示"金币存入成功~"
5. 失败: SafeBoxException.dealwithException
```

#### 金豆取出 (Action_TakeScoreFromBank)
```
1. 校验: moveScore > 0, 余额 >= moveScore
2. 区分大厅/游戏内 → 拼装不同 PB 参数
3. hallSocket/gameSocket.sendRequest(PB_TAKE_BACKSCORE)
4. 成功回调: 同步余额 + 提示 "金币取出成功~"
5. 失败: SafeBoxException.dealwithException
```

#### 银子存入 (Action_PutDepositToBox)
```
1. 校验: moveDeposit > 0, 携带 >= moveDeposit
2. Serializer → sendRequest(TRANSFER_DEPOSIT)
3. 成功: 同步余额 + 提示 "存银成功~"
4. 失败: SafeBoxException.dealwithException
```

#### 银子取出 (Action_TakeDepositFromBox)
```
1. checkCanDirectTakeDeposit:
   - 无密码 或 缓存有密码 → 直接取
   - 有密码无缓存 → 弹出密码框
2. tryTakeDeposit:
   - 计算 keyResult (rndKey + pwd 复杂运算)
   - 区分大厅/游戏内 → 不同 Serializer
3. 密码错误 → 清缓存 → 重新弹出密码框
4. rndKey 为空 → 运行 Action_GetRndKey → 重试
5. 成功: 同步余额 + 提示 "取银成功~"
```

## 自动存取

### 自动存入 (checkNeedAutoSave)
- 触发时机: 金库界面打开后 500ms
- 条件: 玩家携带 > maxReserveNum
- 行为: 存入 excess = min(超出量, oncesavelimit-1)
- 递归: 存入成功后 100ms 再次检测

### 自动取出 (autoTakeGoldBean)
- 触发时机: 定时器 25ms 轮询
- 条件: 余额>0, 携带<minReserveNum, 余额足够补到minReserveNum, 在大厅
- 行为: 取出 minReserveNum - 携带 (现已被注释关闭)

## 保险箱密码系统

### 数据结构
- `HasSecurePwd` / `HasSecurePwdInGame`: 是否有密码
- `RndKey`: 服务端下发的随机密钥
- `SafeBoxPwdKey` (UserCache): 缓存密码

### 密码验证 (calculateKeyResult)
```
1. 校验密码长度 8~16 位
2. base = rndKey/10000 + rndKey%10000
3. 密码每4位截取 → parseInt → 累加到 nResult
4. 返回 nResult 作为 keyResult 发给服务端
```

### 关键错误码
| 错误码 | 含义 | 处理 |
|--------|------|------|
| 60029 | 密码连续错误 | 提示后清除密码缓存 |
| 60001 | rndKey 为空 | 获取 rndKey 后重试 |
| 60086 | 单日取银上限 | 提示"请明天再来" |
| 60095 | 月度取银上限 | 提示"超过每月限额" |
| 60070 | 局数不足 | 提示至少玩 N 局才能转出 |
| 60071 | 时长不足 | 提示至少玩 N 分钟才能转出 |

## 等级权限系统

### 数据来源
- **CP 推送**: `ntfMsgFromCP` → `AT_PlayerLevelInfo` (PLAYER_LEVEL_INFO)
- **本地备用**: `LevelDefinePlugin` 的 `LevelDefine_PlayerLevelInfo`

### 等级特权层级
```
LevelDefineConfig → levelContent[levelid] → privilege → goldbank.maxSaveLimit
```

### 计算
- `getCurLevelMaxSaveIn()`: 取当前等级 goldbank.maxSaveLimit
- `getNextLevelMaxSaveIn()`: 取下一级 goldbank.maxSaveLimit（-1 表示无限制）
- `PLAYER_LEVEL_INFO_LOCAL`: 直接存储已计算的 curLevelDepositNum / nextLevelDepositNum

### 降级机制
- `userDegradeNum` > 0 时显示降级提示 → "消耗任意通宝恢复至 Lv.X"

## 20260523 新增 Property 清单

> 注释标注"20260523 add"的代码已声明但**尚未在现有逻辑中接入**，为 UI 重做预留。

### GoldBankView.ts (界面重构)
```typescript
Spr_LevelIcon: Sprite        // 等级精灵图（声明为 Sprite 但类型写成 Label）
lab_inputTips: Label         // 输入框占位文本（"请输入存入金额"/"请输入取出金额"）
lab_curryAfterOp: Label      // 存取后携带-数量
Title_curryAfterOp: Label    // 存取后携带-标题
lab_backNumAfterOp: Label    // 存取后保险箱余额
btn_ensureOp: Button         // 确认存入按钮
btn_takeOp: Button           // 确认取出按钮
```

### GoldBankSaveOrTakeItem.ts (档位 item)
```typescript
labRatio: Label              // 存取比例展示（如"存 50%"）
```

### 集成要点
- 这些 property 已在 `@property` 装饰器中声明，绑定到预制体节点
- 未在 `onUpdateView` / `updateItemInfo` 等更新函数中使用
- `btn_ensureOp`/`btn_takeOp` 替代原 `nodeSaveToggle`/`nodeTakeToggle` 的交互
- `lab_inputTips` 替代固定输入框提示
- `lab_curryAfterOp`/`lab_backNumAfterOp` 展示操作后金额预估

## Slot 挂载

| Slot 名称 | 使用的预制体 | 位置 |
|-----------|-------------|------|
| `g_startmanager` | GoldBankNodeResult | 游戏桌面 |
| `Hall_Bottom` | GoldBankHallNode | 大厅底部 |
| `Game_Result_Activity` | GoldBankNodeResult | 游戏结算 |
| 其他 | GoldBankNode | 通用 |

## 20260523 修改计划 (已与策划确认)

### 交互流程

```
点击快捷档位 / 全部按钮 → 更新输入框文本 + 操作后预览值
点击输入框 → 弹 GoldBankInputView(数字键盘) → 粗校验+自动调整 → 关闭 → 回填输入框 + 预览值
点击 btn_ensureSaveOp / btn_ensureTakeOp → 终校验 → 自动调整到最近合法值 → 执行 → toast(自动调整时)
```

### 按钮角色

| 按钮 Property | 改名前 | Tab 可见性 | 点击行为 |
|---|---|---|---|
| `Btn_saveall` | 新加 | 存入 Tab | 输入框设为最大可存金额 |
| `Btn_takeall` | 新加 | 取出 Tab | 输入框设为最大可取金额 |
| `btn_ensureSaveOp` | `btn_ensureOp` | 存入 Tab | 执行存入(含校验调整) |
| `btn_ensureTakeOp` | `btn_takeOp` | 取出 Tab | 执行取出(含校验调整) |
| `Spr_LevelIcon` | 原类型 `Label`→`Sprite` | 始终 | 等级精灵图实时刷新 |

### 校验规则

**输入框粗校验**(GoldBankInputView 确认后):
- 超出携带/特权上限 → 自动调至最小值(cap)

**确认按钮终校验**:
- **存入**: `实际值 = clamp(输入值, savelowlimit, min(oncesavelimit, 携带-minReserveNum, 等级上限-余额))`
- **取出**: `实际值 = clamp(输入值, takelowlimit, min(余额, maxReserveNum-携带))`
- 下限不满足 → toast 提示; 合法但被调整 → 执行+toast "已自动调整至合法数值"

### 界面调整

- `Title_curryAfterOp` 文本: 存入 Tab→"存后剩余(携带)", 取出 Tab→"取后剩余(携带)"
- 输入框值变化时同步更新 `lab_curryAfterOp` / `lab_backNumAfterOp`

### 等级图标

- 在 `onUpdateView` 中 `PlayerLevelInfo` 变更时触发
- 路径: `extern/leveldefineIcon/lv{userGrade}` → `ct.SpriteFrameCache.getSpriteFrame`
- 尺寸: 等级≥3 → Size(68,60), 其他 → Size(60,60)

## 已知局限

1. `GoldBankView.onUpdateView` 中 `FieldWealth` 被检查两次，第二次检查实际未生效
2. ~~`GoldBankView:63` — `Spr_LevelIcon` 类型声明有误，已在 20260523 修改中修复~~
3. `GoldBankInputView.onUpdateView` 中的 tabId 缓存读取有 BUG 注释："二级页面唤起时 tabID 常为 0，但实际应为 1"
4. 自动取出 (autoTakeGoldBean) 代码中的定时器逻辑已被注释关闭
5. `showPwdNumPad` 方法已被注释，密码框弹出功能不可用
6. ~~20260523 新增 property 未接入 — 已在 20260523 修改中实现~~
