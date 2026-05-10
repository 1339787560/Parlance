# L1 网络通信模块

## 模块职责

负责与游戏服务器的通信、协议解析、消息分发。

## 主要文件路径

```
assets/game/scripts/network/
├── GameConnect.ts    # 网络连接管理 (110KB)
├── GameReqDef.ts     # 请求协议定义
└── GameStructs.ts    # 数据结构定义 (88KB)
```

## 核心类解析

### GameConnect.ts

**职责**: 网络连接管理、消息收发

**核心功能**:
- WebSocket 连接管理
- 消息序列化/反序列化
- 请求/响应匹配
- 心跳保活

### GameReqDef.ts

**职责**: 定义所有请求协议

**协议类型**:
- 登录认证
- 进入房间
- 游戏操作 (出牌、吃碰杠胡)
- 结算请求

### GameStructs.ts

**职责**: 定义游戏数据结构

**核心结构**:
- 玩家信息结构
- 牌局信息结构
- 结算信息结构

## 通信架构

```
Game.ts
    │
    ▼
GameConnect.send(req)
    │
    ▼
WebSocket → 服务器
    │
    ▼
GameConnect.onMessage(res)
    │
    ▼
eventCenter.emit(GameEvent.xxx)
    │
    ▼
各 Manager 处理
```

## 协议示例

### 出牌请求

```typescript
// 请求
GameReqDef.playCard(cardId: number)

// 响应
GameStructs.PlayCardResponse
```

### 吃碰杠请求

```typescript
// 请求
GameReqDef.cpgOperation(type: CPGType, cards: number[])

// 响应
GameStructs.CPGResponse
```

## 关键操作码

| 操作码 | 含义 |
|--------|------|
| MJ_OPE_PENG (1) | 碰 |
| MJ_OPE_GANG (2) | 杠 |
| MJ_OPE_CHI (3) | 吃 |
| MJ_OPE_HU (4) | 胡 |
| MJ_OPE_GUO (5) | 过 |
| MJ_OPE_TING (6) | 听 |

## 注意事项

1. **断线重连**: 游戏支持断线重连机制
2. **消息队列**: 保证消息顺序处理
3. **超时处理**: 网络超时的重试逻辑

## 业务术语

| 术语 | 含义 |
|------|------|
| req | Request 请求 |
| res | Response 响应 |
| WebSocket | 双向通信协议 |
