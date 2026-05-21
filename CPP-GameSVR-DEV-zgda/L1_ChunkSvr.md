# L1 ChunkSvr 活动模块索引 - 斗地主

> ChunkSvr 核心数据后端，管理活动配置/数据库更新/发奖。44个模块，按功能分组索引。

---

## 架构概览

- **请求路由**：`OnRequest()` 按 `GR_XXX` 命令ID分发
- **单例模式**：所有模块 `GetInstance()` 全局单例
- **发奖统一**：`GiveAward()` → `RewardManager` → HTTP → 外部奖励系统
- **数据策略**：新模块 Redis-first；旧模块 `CDBCache<TKey,TVal>` 内存缓存 + MSSQL
- **配置格式**：CSV（概率/奖励表）+ JSON（复杂结构/多层级配置）

---

## A. 付费礼包模块（10）

| 模块 | 类名 | 源文件 | 功能 | 数据存储 | 配置 |
|------|------|--------|------|----------|------|
| 破产救济包 | CBankruptPackage | BankruptPackage.cpp/.h | 输光后打折购筹码，RFM定价 | Redis `BankruptInfo:{uid}` | INI |
| 破产包V2 | CBankruptPackageV2 | BankruptPackageV2.cpp/.h | 多平台(TCY/Android/iOS)分档 | Redis `BankruptV2:{uid}` | INI |
| 破产赠送 | CBankruptcyGift | BankruptcyGift.cpp/.h, BankruptcyGiftReq.h | 按房间分层赠送，限购次数 | Redis `BankruptcyGift_{type}:{uid}` | BankruptcyGift.json |
| 首充奖励 | CFirstRechargeModule | FirstRecharge.cpp/.h | 首充额外奖励，多渠道多档 | Redis `FirstRecharge:{uid}:{exchangeID}`, `FirstRechargePrice:{uid}` | INI |
| 新手礼包 | CNovicePackage | NovicePackage.cpp/.h, NovicePackageReq.h | 14天登录领奖(银币/兑换物/记牌器/抽奖) | DB `tblNovicePackage`(uid,packageID,recordDate,isVeteran,registerDate) | NovicePackage.csv, NovicePackageReward.csv |
| 幸运充值包 | CLuckyChargePack | LuckyChargePack.cpp/.h, LuckyChargePackReq.h | RFM推荐策略，AB测试 | Redis `LuckyCP:{uid}:common`, `LuckyCP:{uid}:sole:{os}` | LuckyChargePack.json |
| 付费礼包组 | CPayPackageModule | PayPackageModule.cpp/.h, PayPackageModuleReq.h | 多礼包成组，跟踪已购 | Redis `PayPackage:{uid}` | JSON |
| 输局回血包 | CLosebackPackage | LosebackPackage.cpp/.h, LosebackPackageReq.h | 连败后推送，7天限购，rangeIndex分档 | DB `LosebackPackage`, `PayResultInfo`; Redis `LosePackageInfo:{uid}` | LosebackPackage.csv, LosebackPackagePay.json |
| 每日福袋 | CDailyLuckBag | DailyLuckBag.cpp/.h | 每天一个随机折扣包，充值历史推荐 | Redis `DailyLuckBag:{uid}` | JSON |
| 连胜礼包 | CSerialWin | SerialWin.cpp/.h, SerialWinReq.h | 连胜推送，按金额/等级分档 | Redis `SerialWin:{uid}` | SerialWin.json |

---

## B. 订阅类模块（2）

| 模块 | 类名 | 源文件 | 功能 | 数据存储 | 配置 |
|------|------|--------|------|----------|------|
| 月卡 | CMonthCard | MonthCard.cpp/.h, MonthCardReq.h | 周/月双轨奖励，shopItemId购买 | Redis `MonthCard:{uid}` | MonthCard.json |
| 周签到 | CWeekCheckIn | WeekCheckIn.cpp/.h, WeekCheckInReq.h | 打局获签到权，连签1/3/5/7天概率加权奖励 | Redis `WeekCheckIn:{uid}` | JSON |

---

## C. 活动类模块（9）

| 模块 | 类名 | 源文件 | 功能 | 数据存储 | 配置 |
|------|------|--------|------|----------|------|
| 翻翻乐 | CFanFanLe | FanFanLe.cpp/.h, FanFanLeReq.h | 翻牌配对小游戏(对子/顺/同花/三条/同花顺) | DB `tblFanFanle`(uid,nTime,nCount,nChance,nType,nCardIndex/Type 0-2) | FanFanLe.csv, HitFanFanLe.csv |
| 宝藏竞赛 | CTreasureRace | TreasureRace.cpp/.h, TreasureRaceReq.h | 免费+付费抽奖，加权概率表 | DB `tblTreasureRaceUseFirst`, `tblTreasureRaceCount`; Redis `TreasureRace:{uid}` | JSON |
| 种树浇水 | CSaveTree | SaveTree.cpp/.h, SaveTreeReq.h | 任务获水滴→浇水→分级奖励 | DB缓存; Redis `SaveTree:*` | SaveTree.json, SaveTreeTaskDetail.json |
| 存钱罐 | CMoneyBox | MoneyBox.cpp/.h, MoneyBoxReq.h | 存筹码获额外回报，多平台分级 | Redis `MoneyBox:{uid}:{playerType}` | MoneyBox.json |
| 集卡活动 | CCollectionCardsModule | CollectionCardsModule.cpp/.h, CollectionCardsModuleReq.h | 打局获随机卡(概率由房间配置)，集齐兑换 | Redis `CollectionCards:{uid}:{activityID}` | JSON |
| 对局抽奖 | CBoutLotteryModule | BoutLotteryModule.cpp/.h | 打局获抽奖券，多房间多奖池 | DB `tblBoutLotteryInfo`, `tblBoutLotteryInfoRecord`(uid,timeDate,boutType,awardType,awardNum) | JSON |
| 充值抽奖 | CRechargeLottery | RechargeLottery.cpp/.h | RFM策略(正常/未充/已充/特殊)，AB测试 | Redis `RechargeLottery:{uid}` | RechargeLottery.json |
| 广告奖励 | CShopAdReward | ShopAdReward.cpp/.h, ShopAdRewardReq.h | 看广告获免费道具，每项每日限次 | Redis `ShopAdReward:{uid}` | ShopAdReward.json |
| 评分引导 | CAppStoreReview | AppStoreReViewModule.cpp/.h | 控制AppStore评分弹窗频率/次数 | Redis `AppStoreReview:{uid}` | JSON |

---

## D. 竞技类模块（4）

| 模块 | 类名 | 源文件 | 功能 | 数据存储 | 配置 |
|------|------|--------|------|----------|------|
| 斗地主赛事 | CDDZMatch | DDZMatch.cpp/.h, DDZMatchReq.h | 免费/付费报名，排名奖励 | DB `tblDDZMatchFreeInfo`, `tblDDZMatchSignInfo` | JSON/CSV |
| 等级赛 | CLevelMatch | LevelMatch.cpp/.h, LevelMatchReq.h | 赛季制积分升降级 | Redis sorted set `LevelMatch:{seasonID}` | LevelMatch.json, LevelMatchSeasonReward.json |
| 竞技场V2 | CArenaNew | ArenaNew.cpp/.h, ArenaNewReq.h | 周排行，等级+排名双轨奖励 | Redis sorted set `ArenaNew:*` | ArenaConfig.json, ArenaNewRankReward.csv 等 |
| 残局挑战 | CFinalPhaseModule | FinalPhaseModule.cpp/.h | 能量制3级渐进，免费/付费能量 | Redis `FinalPhase:{uid}` | JSON |

---

## E. 核心系统模块（7）

| 模块 | 类名 | 源文件 | 功能 | 数据存储 | 配置 |
|------|------|--------|------|----------|------|
| 道具库存 | CProp | Prop.cpp/.h, PropReq.h | 记牌器/窥底卡/兑换道具/入场券/话费卡 | DB `tblPropInfo`(uid,propType,propId,daysOrCounts), `tblActivityChance`; Redis `CardMaster:{uid}`, `PeerBottom:{uid}` | INI |
| 游戏商店 | CGameShop | GameShop.cpp/.h, GameShopReq.h | 购买道具→转换propId（超级加倍卡商品ID=33587） | Redis | JSON |
| 积分换银+救济 | CScore2Sliver | Score2Sliver.cpp/.h, Score2SliverReq.h | 积分转筹码，破产免费救济 | Redis `Relief_HardID:{date}:{hardID}`, `Relief_UserID:{date}:{uid}` | INI |
| 窥底/桌费 | CPeerBottom | PeerBottom.cpp/.h, PeerBottomReq.h | 分房间分平台(PC/Android/iOS)定价 | Redis `PeerBottom:{uid}:{date}` | PeerBottom.json |
| 任务系统 | CTaskModule | TaskModule.cpp/.h | 日/周任务(打局/赢/地主胜/农民胜/充值/登录) | Redis `Task:{uid}:{guid}` | JSON |
| 入场守卫 | CEnterRoomGuard | EnterRoomGurad.cpp/.h, EnterRoomGuradReq.h | 低局数玩家限制进高级房间 | Redis `EnterRoomGuard:{uid}` | EnterRoomGuard.json |
| 自动补筹码 | CautoReplenishDeposit | AutoReplenishDeposit.cpp/.h | 余额低自动购，分房间配置 | Redis `AutoReplenish:{uid}:{roomID}` | JSON |

---

## F. 辅助模块（6）

| 模块 | 类名 | 源文件 | 功能 |
|------|------|--------|------|
| 表情系统 | CActemoji | Actemoji.cpp/.h, ActemojiReq.h | 购买/免费表情，DB `tblActEmojiOwnInfo`, `tblActEmojiFreeInfo` |
| 条件引导 | CConditionGuid | ConditionGuid.cpp/.h | 条件触发引导提示 |
| 奖励分发 | CRewardManager | RewardManager.cpp/.h | HTTP发奖调度 → 外部奖励系统 |
| 操作日志 | COperationLog | OperationLog.cpp/.h | DB操作日志 |
| 广播 | CBroadCast | BroadCast.cpp/.h | 通知广播 |
| 事件通知 | CMyEventNotifier | MyEventNotifier.cpp/.h | zmq跨服通知(如机器人数据更新) |

---

## G. 基础设施文件

| 文件 | 作用 |
|------|------|
| Server.cpp/.h | 初始化所有模块，路由请求 |
| Main.cpp/.h | 入口点 |
| SockSvr.cpp/.h | TCP/UDP网络连接 |
| DBCache.h | 模板化内存缓存层 `CDBCache<TKey,TVal>` |
| DBCommon.cpp/.h | DB连接/关闭/SQL |
| ChunkDef.h | 命令ID定义、协议范围 |
| RedisMgrPool.cpp/.h | Redis连接池 |
| ConfigManagerSys.cpp/.h | 系统级配置管理 |
| zgdachunksvr.ini | 服务器配置(DB连接/端口) |

---

## 数据库表汇总

| 表名 | 模块 | 关键字段 |
|------|------|----------|
| tblNovicePackage | CNovicePackage | uid, packageID, recordDate, isVeteran, registerDate |
| tblFanFanle | CFanFanLe | uid, nTime, nCount, nChance, nType, nCardIndex0/1/2, nCardType0/1/2 |
| tblPropInfo | CProp | uid, propType, propId, daysOrCounts |
| tblActivityChance | CProp | uid, givePropUID |
| tblGameBoutInfo | CGameBehavior | uid, 对局统计 |
| tblDDZMatchFreeInfo | CDDZMatch | uid, 免费赛信息 |
| tblDDZMatchSignInfo | CDDZMatch | uid, 报名状态 |
| tblTreasureRaceUseFirst | CTreasureRace | uid, useFirst |
| tblTreasureRaceCount | CTreasureRace | uid, count |
| tblActEmojiOwnInfo | CActemoji | uid, emojiId, count |
| tblActEmojiFreeInfo | CActemoji | uid, freeInfo |
| tblBoutLotteryInfo | CBoutLotteryModule | uid, 抽奖信息 |
| tblBoutLotteryInfoRecord | CBoutLotteryModule | uid, timeDate, boutType, awardType, awardNum |
| LosebackPackage | CLosebackPackage | uid, rangeIndex, hitInfo |
| PayResultInfo | CLosebackPackage | uid, payResults |
| tblUserPreferData | CUserPreferDataManager | uid, prefer0..N |
| tblHost | DBOperate | VolumeID, status |

---

## 术语表

| 术语 | 含义 |
|------|------|
| RFM | Recency-Frequency-Monetary 用户付费推荐策略 |
| AB测试 | 多方案并行对比测试 |
| rangeIndex | 输局回血包的分档索引 |
| shopItemId | 商城道具ID |
| exchangeID | 兑换ID（充值→道具映射） |
| playerType | 平台类型(PC/Android/iOS/TCY) |
| CDBCache | 模板化内存缓存层，周期性清除 |
| GiveAward | 统一发奖接口 → RewardManager → HTTP |
| GR_XXX | 模块命令ID宏，用于请求路由分发 |
| sorted set | Redis有序集合，用于排行榜/赛季排名 |
| Bout | 一局/一场对局 |
| Deposit | 筹码/银币余额 |
| PeerBottom | 窥底（看对手牌）功能 |
| FinalPhase | 残局挑战模式 |
| RPA Shop | 机器人流程自动化商店 |