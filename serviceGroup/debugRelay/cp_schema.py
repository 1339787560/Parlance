# -*- coding: utf-8 -*-
"""CP client_request 测试面 schema — 模块 -> req 清单 + 参数样例。

来源
----
原为 serviceServer-legacy/CustomRoute/CpDataRoute.py 的 CP_REQ_SCHEMA
(2026-08-14 从 cpscript/src/xzmp/<module>_xzmp.ts 的 OnClientRequest 全分支反推,
13 模块 43 req)；**该文件已于 2026-09-22 随旧 exec_script 通路整体退役删除**，
本文件即该 schema 的唯一真相源。

为什么搬到 debugRelay
---------------------
旧通路 POST /api/cp-data/request 依赖 db9 halllogon 五元组: 玩家必须先用客户端在
125 登录过, 且 appcode 与最后登录包一致, 否则必报「无 halllogon 记录」; 该通路已
**整体退役删除** (2026-09-22, CpDataRoute.py 连同前端两个 hidden tab 一并摘除)。

新通路经 debugRelay 代码通道打到**已连接的客户端**, 由客户端
ct.CommonCPInterFace.client_request 自动填全局登录态 src, 天然通过 CheckRequest,
不需要 db9, 也不需要 relay 侧重新实现 protobuf。

字段
----
params  = 参数样例默认值 (dict: 名称 -> 示例值); UI 用它预填表单, 非强校验
ro      = True 只读 / False 写操作 (发奖/扣次数/购买)
          写操作会真改玩家数据 -> UI 标 [写], 只应用测试账号
desc    = 用途说明

红线
----
req 名大小写敏感 (以 cpscript REQ_NAME 常量为准, 如 queryRunTurntable 而非
runTurnTable); 名字错不报错但 resp 为空 —— 白名单只是防呆, 不做名称纠正。
"""

# ---- 模块 -> req 清单 (单一真相源; 新增模块/req 只改这里) ----
CP_REQ_SCHEMA = {
    'award': [
        {'req': 'queryAdVideoCfg', 'params': {}, 'ro': True, 'desc': '看视频礼包配置'},
        {'req': 'queryReliefConfig', 'params': {}, 'ro': True, 'desc': '低保配置'},
        {'req': 'queryReliefTakeCount', 'params': {}, 'ro': True, 'desc': '低保已领次数'},
        {'req': 'queryDressGiftCfg', 'params': {}, 'ro': True, 'desc': '装饰礼包配置 (运营未开返空)'},
        {'req': 'queryNextDayConfig', 'params': {}, 'ro': True, 'desc': '明日奖励配置 (注意大小写 NextDay)'},
        {'req': 'queryPayGiftPackCfg', 'params': {}, 'ro': True, 'desc': '礼包配置'},
        {'req': 'takeEvaluateReward', 'params': {}, 'ro': False, 'desc': '领取评价奖励 [写]'},
        {'req': 'takeAdVideoGift_v2', 'params': {}, 'ro': False, 'desc': '领取看视频礼包 [写]'},
        {'req': 'takeReliefReward_v2', 'params': {'takeParam': '', 'registerTime': 0, 'subscribe': 0}, 'ro': False,
         'desc': '领取低保奖励 [写]'},
        {'req': 'takeBackHallReward', 'params': {}, 'ro': False, 'desc': '领取返回大厅礼包 [写]'},
        {'req': 'takeDressGiftReward', 'params': {}, 'ro': False, 'desc': '领取装饰礼包 [写]'},
        {'req': 'takeOptionChooseReward', 'params': {'optionKey': ''}, 'ro': False, 'desc': '领取问卷选择礼包 [写]'},
        {'req': 'takeNextDayReward', 'params': {'dayKey': ''}, 'ro': False, 'desc': '领取明日奖励 [写]'},
    ],
    'cmdailyquestion': [
        {'req': 'GR_TQDAILYQUESTION_REQINFO', 'params': {}, 'ro': True, 'desc': '每日问答玩家信息'},
        {'req': 'GR_TQDAILYQUESTION_REQCONFIG', 'params': {}, 'ro': True, 'desc': '每日问答配置'},
        {'req': 'GR_TQDAILYQUESTION_REQANSWER', 'params': {'questionid': 1, 'answer': 0}, 'ro': False,
         'desc': '提交答题 [写]'},
        {'req': 'GR_TQDAILYQUESTION_REQPRIZE', 'params': {}, 'ro': False, 'desc': '领取答题奖励 [写]'},
    ],
    'cmdecoration': [
        {'req': 'queryCMDecorationConfig', 'params': {}, 'ro': True, 'desc': '装扮配置'},
        {'req': 'queryChangeDecoration', 'params': {}, 'ro': True, 'desc': '已使用装饰'},
        {'req': 'queryUserListsHeadFrameInfo', 'params': {'userIDList': [1040720, 0, 0, 0]}, 'ro': True,
         'desc': '多玩家装扮信息 (userIDList 必传)'},
        {'req': 'queryChangeDecoration_use', 'params': {'itemUUID': 0}, 'ro': False,
         'desc': '使用装饰 (源码 queryChangeDecoration + itemUUID 分支) [写]'},
    ],
    'cmmonthcard': [
        {'req': 'queryCMMonthCardConfig', 'params': {}, 'ro': True, 'desc': '周月卡配置'},
    ],
    'cmnewplayerdailygift': [
        {'req': 'queryNewPlayerDailyGiftConfig', 'params': {}, 'ro': True, 'desc': '迎新每日礼包配置'},
        {'req': 'claimDailyReward', 'params': {}, 'ro': False, 'desc': '领取每日礼包奖励 [写]'},
    ],
    'cmquickrecharge': [
        {'req': 'queryCMQuickRechargeConfig', 'params': {}, 'ro': True, 'desc': '补足金币配置'},
        {'req': 'buySpecialGift', 'params': {'gametype': 1, 'roomlevel': 1, 'giftlevel': 1}, 'ro': False,
         'desc': '购买特惠礼包校验 [写]'},
        {'req': 'markSpecialGiftPurchased', 'params': {'gametype': 1, 'roomlevel': 1, 'giftlevel': 1}, 'ro': False,
         'desc': '标记特惠礼包已购买 [写]'},
    ],
    'cmremoteconfig': [
        {'req': 'queryRemoteConfig', 'params': {}, 'ro': True, 'desc': '选房策略远端配置'},
        {'req': 'debugRemoteConfig', 'params': {}, 'ro': False, 'desc': '调试远端配置 [写]'},
    ],
    'convert': [
        {'req': 'queryTutorialState', 'params': {}, 'ro': True, 'desc': '新手引导迁移状态'},
        {'req': 'claimTutorialReward', 'params': {}, 'ro': False, 'desc': '领取引导奖励 [写]'},
        {'req': 'clearMigrationFlag', 'params': {}, 'ro': False, 'desc': '清迁移标记 (仅125/888) [写]'},
        {'req': 'clearMigrationTargets', 'params': {}, 'ro': False, 'desc': '清迁移模块数据 (仅125/888) [写]'},
        {'req': 'runLegacyMigration', 'params': {}, 'ro': False,
         'desc': '造「旧版迁移态」账号：走一次新版迁移后把状态写成 0x7F(不含 bit7) (仅125/888) [写]；跑完 CP 会 notifyClient 刷新界面'},
        {'req': 'clearMigrationCache', 'params': {}, 'ro': False,
         'desc': '清 chunkSvr 侧「已推送」去重缓存 (仅125/888) [写]；由 CP 转调 chunkSvr 内网接口，客户端不直连'},
        {'req': 'clearMigrationBoth', 'params': {}, 'ro': False,
         'desc': '【原子】清两侧迁移状态 = CP 迁移标记 + chunkSvr 推送缓存，使玩家回到「未迁移」态 (仅125/888) [写]'},
        {'req': 'queryScoreAccount', 'params': {'userID': 1174730}, 'ro': True,
         'desc': '查玩家积分账户「携带(手中) + 保险箱(后备箱)」(仅125/888)；userID 可省(省=查登录玩家)；核对迁移补差基准'},
    ],
    'goldbank': [
        {'req': 'queryGoldBankInfo', 'params': {}, 'ro': True, 'desc': '金库信息'},
    ],
    'joyfulgift': [
        {'req': 'queryJoyFulGiftCfg', 'params': {'gametype': 1, 'roomlevel': 1, 'giftlevel': 1}, 'ro': True,
         'desc': '欢乐礼包配置 (三参必传)'},
    ],
    'leveldefine': [
        {'req': 'queryLevelDefineConfig', 'params': {}, 'ro': True, 'desc': '等级定义配置'},
        {'req': 'reqTakeOneOffReward', 'params': {'getLevelID': 1}, 'ro': False,
         'desc': '领取等级一次性奖励 (getLevelID 必传) [写]'},
    ],
    'luckyturntable': [
        {'req': 'queryLuckyTurntableConfig', 'params': {}, 'ro': True, 'desc': '幸运转盘配置+剩余次数'},
        {'req': 'queryRunTurntable', 'params': {'useCount': 1}, 'ro': False,
         'desc': '转转盘 (useCount 必传, 消耗次数发奖; 注意 req 名大小写 queryRunTurntable) [写]'},
    ],
    'resurrect': [
        {'req': 'queryConfig_resurrect', 'params': {'roomID': 694, 'channelkey': 'tcyan'}, 'ro': True,
         'desc': '复活礼包配置'},
        {'req': 'queryLeftTakeCount_resurrect', 'params': {'roomID': 694, 'channelkey': 'tcyan'}, 'ro': True,
         'desc': '免费复活剩余次数 (roomID 参与逻辑)'},
        {'req': 'queryShowList_resurrect', 'params': {'roomID': 694, 'channelkey': 'tcyan'}, 'ro': True,
         'desc': '复活展示列表'},
        {'req': 'takeReward_resurrect', 'params': {'roomID': 694, 'channelkey': 'tcyan'}, 'ro': False,
         'desc': '使用免费复活 (扣次数+发奖; 注意 req 名 takeReward_resurrect) [写]'},
    ],
}

# 命名空间前缀: Test 面板 / agent 按 `cp.<module>.<req>` 寻址, 与 debug-index 的 ns.fn 形状一致
CP_NS_PREFIX = 'cp'

_REQUIRED_KEYS = ('req', 'params', 'ro', 'desc')


def find_req(module: str, req: str):
    """白名单查找。返回 entry dict 或 None。"""
    entries = CP_REQ_SCHEMA.get((module or '').strip())
    if not entries:
        return None
    name = (req or '').strip()
    return next((e for e in entries if e['req'] == name), None)


def cp_namespaces() -> dict:
    """归一化成 /api/debug-index 的 namespaces 形状, 供 Test 面板与 agent 复用。

    形状: {'cp.<module>': {'<req>': {env,arity,desc,category,ro,params}}}
    - arity = 命名参数个数 (UI 显示「⚙ 有参数 N」徽标)
    - params 为 dict (命名参数 -> 样例默认值), 与 debug-index 的位置参数数组区分:
      UI 见 dict 走命名表单, 见数组走位置表单
    """
    out = {}
    for module, entries in CP_REQ_SCHEMA.items():
        ns = f'{CP_NS_PREFIX}.{module}'
        members = {}
        for e in entries:
            params = e['params']
            members[e['req']] = {
                'env': 'both',
                'arity': len(params),
                'desc': e['desc'],
                'category': module,          # 子分类 = 模块名
                'ro': e['ro'],
                'params': params,
            }
        out[ns] = members
    return out


def cp_catalog() -> dict:
    """GET /api/cp/modules 的返回体 (与 /api/debug-index 同构, 便于前端/agent 共用解析)。"""
    ns = cp_namespaces()
    return {
        'ok': True,
        'scope': 'cp',
        'namespaces': ns,
        'count': sum(len(v) for v in ns.values()),
        'namespace_count': len(ns),
        'categories': list(CP_REQ_SCHEMA.keys()),   # 模块顺序即子分类展示顺序
    }


def validate() -> list:
    """schema 自检 (单测/启动期用)。返回错误字符串列表, 空 = 健康。"""
    errs = []
    seen_modules = set()
    if not CP_REQ_SCHEMA:
        errs.append('schema 为空')
    for module, entries in CP_REQ_SCHEMA.items():
        if module in seen_modules:
            errs.append(f'模块重复: {module}')
        seen_modules.add(module)
        if not isinstance(entries, list) or not entries:
            errs.append(f'模块 {module} 无 req 清单')
            continue
        seen_reqs = set()
        for i, e in enumerate(entries):
            if not isinstance(e, dict):
                errs.append(f'{module}[{i}] 不是 dict')
                continue
            for k in _REQUIRED_KEYS:
                if k not in e:
                    errs.append(f'{module}[{i}] 缺字段 {k}')
            req = e.get('req')
            if not isinstance(req, str) or not req:
                errs.append(f'{module}[{i}] req 非空字符串')
            elif req in seen_reqs:
                errs.append(f'{module} req 重复: {req}')
            else:
                seen_reqs.add(req)
            if not isinstance(e.get('params'), dict):
                errs.append(f'{module}.{req} params 应为 dict')
            if not isinstance(e.get('ro'), bool):
                errs.append(f'{module}.{req} ro 应为 bool')
            if not isinstance(e.get('desc'), str) or not e.get('desc'):
                errs.append(f'{module}.{req} desc 应为非空字符串')
    return errs
