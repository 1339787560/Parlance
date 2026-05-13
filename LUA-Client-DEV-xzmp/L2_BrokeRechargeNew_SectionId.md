# L2 复活礼包 (TQBrokeRechargeNew) — sectionid 匹配逻辑

> 来源：LUA 客户端 `MyGameBrokeChargeNewCtrl.lua` + chunk `TQMatchv2.lua`

## 核心问题

**宗师场 (roomlevel=5) 复活礼包是否区分 sectionid？**

**答案**：配置有 sectionid=1,2,3,4，但 chunk 的 matchRobotSections 最高只到 roomlevel=4。宗师场玩家实际都获得同一个 sectionid（默认值或 chunk 返回的最大值）。

## sectionid 数据流

| 服务 | 组件 | 关键代码 | 作用 |
|------|------|---------|------|
| chunk | `TQMatchv2.lua:getUserSectionID()` | 第 3164-3198 行 | 根据金币区间计算 sectionid |
| chunk | `TQMatchv2.lua:onUserRoomEnter()` | 第 776-785 行 | 返回 `rsp.sectionid` 给 gamesvr |
| gamesvr | `MakeCardNewModule.cpp` | 第 91 行 | 存入 `m_meddleData.m_nSectionID` |
| gamesvr | `MyTbl.cpp:FillupStartInfo()` | 第 3540 行 | 装入 `StartData.nSectionId[]` |
| gamesvr | `MyServer.cpp` | 第 11980 行 | 通过 protobuf 发送给客户端 |
| 客户端 | `BaseGameInfo.lua:getSectionId()` | 第 905 行 | 读取 `nSectionId[chairno+1]` |

## chunk 计算逻辑 (TQMatchv2.lua:3164-3198)

```lua
function TQMatchv2:getUserSectionID(configs, userType, roomLevel, deposit)
    local mysectionid = 1
    for k,v in ipairs(configs.matchRobotSections) do
        if v.userproperty == matchTypeConfigs[1].property and v.roomlevel == roomLevel then
            if deposit >= v.playersection.min and deposit < v.playersection.max then
                mysectionid = v.sectionid  -- 金币落在区间内
            end
            lastsectionid = v.sectionid   -- 记录最后一个
        end
    end
    -- 未匹配则返回 lastsectionid（最大值）
    return mysectionid
end
```

## matchRobotSections 配置 (TQMatchV2Config.lua)

最高配置到 roomlevel=4，没有 roomlevel=5：

| roomlevel | sectionid | 金币区间 (playersection.min ~ max) |
|-----------|-----------|-----------------------------------|
| 1 | 1 | 19,999 ~ 210,000 |
| 1 | 2 | 210,000 ~ 550,000 |
| 1 | 3 | 550,000 ~ 1,000,000 |
| 1 | 4 | 1,000,000 ~ 2,000,000 |
| 2 | 1 | 999,999 ~ 6,000,000 |
| 3 | 1 | 4,999,999 ~ ∞ |
| 4 | 1 | 49,999,999 ~ ∞ |

**宗师场 (roomlevel=5) 无匹配配置 → 返回默认值 1**。

## 客户端匹配逻辑 (MyGameBrokeChargeNewCtrl.lua:223-242)

```lua
function MyGameBrokeChargeNewCtrl:getPayConfig(payconfig)
    local gametype = self:getGameType()      -- 血流红中=3
    local roomLevel = self:getRoomLevel()    -- 宗师场=5
    local mysectionid = gameController:getGameInfoInstance():getSectionId(myChairNO)
    
    for j = 1, 3 do  -- 三档礼包
        for i, v in pairs(config.items) do
            if v.gametype == gametype and v.roomlevel == roomLevel and v.giftlevel == j then
                if v.sectionid <= mysectionid and v.sectionid >= maxsectionid then
                    payconfig[j] = v  -- 取 ≤ 玩家 sectionid 的最大配置
                end
            end
        end
    end
end
```

## 复活礼包配置 (TQBrokeRechargeNewConfig.lua)

宗师场 (roomlevel=5) 有 sectionid=1,2,3,4 四组：

| roomlevel | sectionid | giftlevel | fakeexchangeid | price |
|-----------|-----------|-----------|----------------|-------|
| 5 | 1 | 1 | 59 | 6800 |
| 5 | 1 | 2 | 60 | 12800 |
| 5 | 1 | 3 | 61 | 32800 |
| 5 | 2 | 1 | 62 | 6800 |
| 5 | 2 | 2 | 63 | 12800 |
| 5 | 2 | 3 | 64 | 32800 |
| 5 | 3 | 1 | 65 | 6800 |
| 5 | 3 | 2 | 66 | 12800 |
| 5 | 3 | 3 | 67 | 32800 |
| 5 | 4 | 1 | 68 | 6800 |
| 5 | 4 | 2 | 69 | 12800 |
| 5 | 4 | 3 | 70 | 32800 |

**实际效果**：宗师场玩家 sectionid 均为 1 → 只匹配 sectionid=1 的礼包组（fakeexchangeid 59/60/61）。

## 结论

| 房间等级 | sectionid 区分 | 实际匹配 |
|---------|---------------|---------|
| 初级场 (roomlevel=1) | 有 (1~4) | 按金币区间匹配 |
| 中级场 (roomlevel=2) | 有 (1~2) | 按金币区间匹配 |
| 高级场 (roomlevel=3) | 有 (1~4) | 按金币区间匹配 |
| 豪华场 (roomlevel=4) | 有 (1~4) | 按金币区间匹配 |
| 宗师场 (roomlevel=5) | **无** | chunk 无配置 → 默认 sectionid=1 → 只匹配 sectionid=1 的礼包 |

## 相关文件

| 文件 | 路径 | 说明 |
|------|------|------|
| 客户端控制器 | `ClientLua/src/trunk/src/app/game/my/brokeDialog/MyGameBrokeChargeNewCtrl.lua` | 礼包弹窗逻辑 |
| 客户端数据读取 | `ClientLua/src/trunk/src/app/game/base/BaseGameInfo.lua` | getSectionId() |
| chunk 匹配逻辑 | `gamechunksvr/Debug/scripts/msgcenter/TQMatchv2.lua` | getUserSectionID() |
| chunk 配置 | `gamechunksvr/Debug/TQMatchV2Config.lua` | matchRobotSections |
| 礼包配置 | `gamechunksvr/Debug/TQBrokeRechargeNewConfig.lua` | payconfig (roomlevel=5) |
| gamesvr 接收 | `gamesvr/MakeCardNewModule.cpp` | 存储 sectionid |
| gamesvr 发送 | `gamesvr/my/MyServer.cpp` | protobuf 发送 |