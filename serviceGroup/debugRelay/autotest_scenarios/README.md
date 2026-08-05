# Autotest Scenario Schema

> 客户端对局自动化测试 — scenario policy 格式规范（debugRelay `/scenarios/{name}.json` + `/api/autotest` toggle 托管）。

## 文件位置

- scenario JSON：`autotest_scenarios/<name>.json`（debugRelay 进程目录下，启动 `mkdir(exist_ok=True)`）
- 做牌牌局标识库：`makecard_scenarios/<name>.json`（C3 牌局标识符，scenario.makecard_id 引用此库；test.ini 片段 + 元信息）

## ScenarioPolicy 顶层字段

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `name` | string | ✅ | scenario 标识，与文件名同步 |
| `desc` | string | — | 人类可读描述（配套 test.ini / 四家手牌 / 验证目标） |
| `makecard_id` | string | — | 引用 `makecard_scenarios/<id>.json`（C3 牌局标识符） |
| `phases` | object | — | **新格式（推荐）**：分阶段脚本，见下 |
| `rules` | Rule[] | — | **旧格式（兼容）**：单 rules 数组 + `when.myChair` 过滤；无 phases 时 fallback |
| `expect` | object | — | 终局断言声明（relay 侧 T4 expect 双层断言用） |
| `enabled` | bool | — | 运行时标记（DebugPlugin 设，false=不激活） |

> 新格式优先：`phases.inBout.chairs` 存在时按 chairs 显式四家分发；否则回退 `rules` + `when.myChair`。

## phases（C10 进房可扩展）

```json
"phases": {
  "enterRoom": { "chairs": { ... } },   // 预留：进房自动化（本期不激活）
  "inBout":    { "chairs": { "0": [...], "1": [...], "2": [...], "3": [...] } }
}
```

本期只激活 `inBout`。`enterRoom` 解析不报错，留扩展位。

## Rule 结构

```json
{
  "when": {
    "myChair":   0,            // 旧格式用；新格式按 chairs key 自动定位
    "gangBtn":   true,         // 杠按钮可点（暗杠/明杠/碰杠）
    "huBtn":     true,         // 胡按钮可点
    "leftCount": 80,           // 牌堆剩余张数（精确匹配）
    "needThrow": true,         // 当前轮到自己出牌
    "dingque":   true,         // 局前定缺阶段
    "card":      21            // 杠/出牌目标 cardidx（shape*10+value，一筒=21 九筒=29 一万=1）
  },
  "do":     "gang",            // dingque | gang | hu | guo | throw | peng | chi | pass
  "once":   true,              // true=每局只触发一次（默认）；false=可重触发（dingque/throw 用）
  "_fired": false              // 运行时状态（_onBoutStart 重置）；落档时省略
}
```

### do 枚举

| 动作 | 行为 | 典型 once |
|---|---|---|
| `dingque` | emit `onAutoFixMiss`（客户端推荐定缺） | false（每局局前） |
| `gang` | 走 `_doGang(cardidx)`：暗杠指定 cardidx 直选 `sendAnGangCard`，绕选择 UI | true |
| `hu` | 调 `mgr.onBtnHuClicked()` | true |
| `guo` | 调 `mgr.onBtnGuoClicked()`（过牌/让杠让胡） | false |
| `throw` | 走 `_doThrow(cardidx)`：scenario 指定 cardidx → 定缺张 → 非红中首张 → 首张兜底 | false |
| `peng` | 调 `mgr.onBtnPengClicked()` | true |
| `chi` | 调 `mgr.onBtnChiClicked()` | true |
| `pass` | 占位（不做操作，等其他规则） | — |

### cardidx 映射（encoding B，权威）

`shape = cardid / 36`（万 0-35 / 条 36-71 / 筒 72-107 / 红中 108-113）
`value = cardid % 9 + 1`
`cardidx = shape * 10 + value`

| 牌张 | cardidx | cardids（4 副本步长 9） |
|---|---|---|
| 一万 | 1 | 0, 9, 18, 27 |
| 九万 | 9 | 8, 17, 26, 35 |
| 一条 | 11 | 36, 45, 54, 63 |
| 九条 | 19 | 44, 53, 62, 71 |
| 一筒 | 21 | 72, 81, 90, 99 |
| 九筒 | 29 | 80, 89, 98, 107 |
| 红中 | 31 (shape=3) | 108-113（xzms 六红中 114 张；xzmo 血流血战无红中 108 张） |

## expect（T4 双层断言）

`expect` 块声明终局断言条件，relay 侧 `/api/autotest/report` 拉服务端 combatdata.log + flow.log grep 实际值 + merge 客户端 arm_state，逐条 pass/fail。

```json
"expect": {
  "gang_gen_multiple_nonzero": true,         // combat log 杠倍数非零
  "round_end": "hu_chair0",                  // 终局胡家
  "chair0_angang_card": 21,                  // chair0 暗杠目标 cardidx
  "action_summary_angang_bit_set": true      // action_summary_bits 位 4 (CDC_ACTION_ANGANG_BIT) 置 1
}
```

> 当前支持 key 见 `/api/autotest/report` 实现（gang_gen_multiple / hand_cards 一致性 / round_uuid 命中 / arm 四家聚合）。

## 示例（gang_ang_shbar 摘要）

```json
{
  "name": "gang_ang_shbar",
  "makecard_id": "test_bak_sdd_gang",
  "phases": { "inBout": { "chairs": {
    "0": [
      { "when": { "dingque": true }, "do": "dingque", "once": false },
      { "when": { "gangBtn": true, "card": 21 }, "do": "gang", "once": true },
      { "when": { "huBtn": true }, "do": "hu", "once": true },
      { "when": { "needThrow": true }, "do": "throw", "once": false }
    ],
    "1": [
      { "when": { "dingque": true }, "do": "dingque", "once": false },
      { "when": { "gangBtn": true }, "do": "guo", "once": false },
      { "when": { "huBtn": true }, "do": "guo", "once": false },
      { "when": { "needThrow": true }, "do": "throw", "once": false }
    ],
    "2": [ /* 同 chair1 */ ],
    "3": [ /* 同 chair1 */ ]
  } } },
  "expect": { "gang_gen_multiple_nonzero": true, "round_end": "hu_chair0" }
}
```

## 三铁律（build 必守）

1. **零参与**：业务 manager（OperateBtnsManager 等）不含 test 代码；全在 `assets/game/scripts/autotest/AutotestPlayer.ts`
2. **动态挂载**：DebugPlugin `addComponent('AutotestPlayer')` by ccclass 字符串（免 import 游戏包）；Game 场景 Canvas
3. **进房 phases 可扩展**：scenario `phases.enterRoom` 预留，本期 `inBout`

## 跨包通信

- DebugPlugin → AutotestPlayer：`globalThis.__testSeq`（DebugPlugin fetch scenario 后挂）
- AutotestPlayer → DebugPlugin：`globalThis.__debugBus.emit("Debug_AutotestArm", {chair, ok, rules_count})`
- debugRelay eval 入口：`globalThis.__autotestStatus()`（AutotestPlayer.getStatus 暴露 hand+armed+chair）
