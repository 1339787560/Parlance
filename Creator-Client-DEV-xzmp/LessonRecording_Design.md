# 新手引导录制与导入系统 — 设计文档

## 1. 概述

目标：录制真实联机对局的所有网络消息（send/recv），导出明文 JSON，丝滑导入 `buildLessonStages()` 生成精确的新手引导数据。

```mermaid
flowchart LR
    A[联机对局] --> B[录制系统]
    B --> C[JSON 导出]
    C --> D[buildLessonStages]
    D --> E[LessonStage[]]
    E --> F[教程回放]
```

## 2. 录制系统

### 2.1 触发条件

- `GameInfo.isDebugEnv()` = true 时自动启用
- 跟随 `onEnterGameOK` 事件启动，`onGameWin` / `onPresaveResult(nFlag=0)` 时停止

### 2.2 文件结构

新建 `CMNPLessonRecorder.ts`，单例模式。

```typescript
class CMNPLessonRecorder {
    private static _inst: CMNPLessonRecorder;
    private _recording = false;
    private _startTime = 0;
    private _events: RecordedEvent[] = [];

    static getInstance(): CMNPLessonRecorder;

    start(): void;        // onEnterGameOK 时调用
    stop(): void;         // 游戏结束时调用
    dump(): void;         // console.log JSON

    recordSend(msgID: number, msgName: string, data: any): void;
    recordRecv(msgID: number, msgName: string, data: any): void;
    getJSON(): string;
}
```

### 2.3 数据格式

```typescript
interface RecordedEvent {
    ts: number;           // 相对 onEnterGameOK 的毫秒数
    dir: 'send' | 'recv';
    msgID: number;
    msgName: string;      // 如 "MJ_GR_CARDS_THROW"
    data: any;            // 反序列化后的明文 JS 对象
}

interface RecordingJSON {
    version: 1;
    playerChairNO: number;
    startedAt: number;    // 占位，始终为 0
    events: RecordedEvent[];
}
```

### 2.4 接收消息录制点

在 `GameSocket.ts` 中，**重写 `addHandler`**，包装原始回调。在调用原始 ntf handler 前，先反序列化并录制：

```typescript
addHandler(respondID: number, callback: Function, target?: unknown) {
    const wrapped = (body: ArrayBuffer) => {
        // 录制：使用 schema 映射反序列化
        const schema = RECV_SCHEMA_MAP[respondID];
        if (schema && this._recorder?.isRecording()) {
            const bs = new ct.BinaryStream(body);
            const data = schema.isPB
                ? ct.deserializepb(bs, schema.name)
                : ct.deserialize(bs, schema.name);
            this._recorder.recordRecv(respondID, msgNameMap[respondID], data);
        }
        // 原始调用
        callback(body);
    };
    return super.addHandler(respondID, wrapped, target);
}
```

### 2.5 发送消息录制点

在 `GameSocket.ts` 中，**重写 `sendRequest`**，先录制再发送：

```typescript
sendRequest(msgID: number, body: ArrayBuffer, callback?: Function) {
    const schema = SEND_SCHEMA_MAP[msgID];
    if (schema && this._recorder?.isRecording()) {
        const bs = new ct.BinaryStream(body);
        const data = schema.isPB
            ? ct.deserializepb(bs, schema.name)
            : ct.deserialize(bs, schema.name);
        this._recorder.recordSend(msgID, msgNameMap[msgID], data);
    }
    return super.sendRequest(msgID, body, callback);
}
```

### 2.6 Schema 映射表

从 GameConnect.ts 的 ntf handler 和 send 方法中提取。两个映射：

```typescript
// 接收消息 schema（来自 addHandler + ntf* handler 里的 deserializepb/deserialize 调用）
const RECV_SCHEMA_MAP: Record<number, { name: string; isPB: boolean }> = {
    [GameReqDef.MJ_GR_CARDS_THROW]:          { name: "CARDS_THROW_WITHFAN", isPB: false },
    [GameReqDef.MJ_GR_CARD_CAUGHT]:          { name: "CARD_CAUGHT_MJ", isPB: false },
    [GameReqDef.GR_SYSTEMMSG]:               { name: "SYSTEMMSG", isPB: false },
    [GameReqDef.GR_PRE_SAVE_RESULT]:         { name: "XZMSdef.PB_PRE_SAVE_RESULT", isPB: true },
    [GameReqDef.MJ_GR_GAME_WIN]:             { name: "XZMSdef.GAME_WIN_RESULT", isPB: true },
    [GameReqDef.GR_PLAYING_DEPOSIT_NOT_ENOUGH]: { name: "XZMSdef.PB_GIVEUP_INFO", isPB: true },
    [GameReqDef.GR_MJ_QUERY_HUINFO]:         { name: "XZMSdef.RspHuInfo", isPB: true },
    [GameReqDef.GR_MJ_QUERY_TINGINFO]:       { name: "XZMSdef.RspTingInfo", isPB: true },
    // ... 完整列表从 GameConnect.ts 逐一提取
};

// 发送消息 schema（来自 send* 方法里的 ct.serialize/ct.serializepb 调用）
const SEND_SCHEMA_MAP: Record<number, { name: string; isPB: boolean }> = {
    [GameReqDef.MJ_GR_THROW_CARDS]:           { name: "THROW_CARDS", isPB: false },
    [GameReqDef.MJ_GR_HU_CARD]:               { name: "HU_CARD", isPB: false },
    [GameReqDef.MJ_GR_CHI_CARD]:              { name: "CHI_CARD", isPB: false },
    [GameReqDef.MJ_GR_PENG_CARD]:             { name: "PENG_CARD", isPB: false },
    [GameReqDef.GR_EXCHANGE_CARDS]:           { name: "EXCHANGE_CARDS", isPB: false },
    [GameReqDef.GR_AUCTION_BANKER]:           { name: "AUCTION_BANKER", isPB: false },
    // ... 完整列表从 GameConnect.ts 逐一提取
};
```

### 2.7 msgID→名称映射

枚举 `GameReqDef` 反向映射：

```typescript
const msgNameMap: Record<number, string> = {};
for (const key of Object.keys(GameReqDef)) {
    msgNameMap[GameReqDef[key as keyof typeof GameReqDef]] = key;
}
```

### 2.8 导出与访问

```typescript
// GameInfo 中暴露
getRecordingJSON(): string | null {
    return CMNPLessonRecorder.getInstance().getJSON();
}

// 调试断点命中时调用
GameInfo.dumpRecording();
// 或在 GameConnect 中加键盘快捷键打印
```

## 3. 导入系统

### 3.1 JSON → LessonStage[]

```typescript
// 新增函数，位于 CMNewPlayerLessonData.ts
export function buildLessonStagesFromRecording(json: RecordingJSON): LessonStage[] {
    const stages: LessonStage[] = [];
    const events = json.events.sort((a, b) => a.ts - b.ts);

    // 阶段划分策略：按消息类型自然分组
    // enter → exchange3 → dingque → play
    let currentStage: LessonStage | null = null;
    // ... 遍历 events，按消息类型分组构建 stages
    // recv → NOTIFY
    // send (chair != 0) → auto-play
    // send (chair == 0) → WAIT_PLAYER_ACTION

    return stages;
}
```

### 3.2 时间处理

- 录制时间戳仅用于**确定消息顺序**
- 实际延迟使用现有 `genServerDelay()` / `genPlayerDelay()` 替代
- 部分关键操作间隔可用录制时间差 `events[i+1].ts - events[i].ts` 作为参考

### 3.3 并行阶段处理

换三张 / 定缺等并行阶段，录制数据中表现为：
```
send(玩家提交换三张) → ntfExchange3Cards(玩家A) → ntfExchange3Cards(玩家B)
→ ntfExchange3Cards(玩家C) → ntfExchange3Finished
```

导入时识别为 parallel stage，`waitForAll: 4`。

## 4. 使用流程

```
Step 1: 测试环境下 4 账号开打，每个客户端录制
Step 2: 取出 chairNO=0 的录制 JSON
Step 3: 提供 JSON 给开发者（console 打印 / 文件）
Step 4: buildLessonStagesFromRecording(json) → LessonStage[]
Step 5: 以此数据替换现有 LessonData
```

## 5. 待实现文件清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `CMNPLessonRecorder.ts` | 新建 | 录制器单例 |
| `GameSocket.ts` | 修改 | 加 `addHandler` wrap + `sendRequest` override |
| `GameConnect.ts` | 修改 | `onEnterGameOK` 处启停录制器 |
| `CMNewPlayerLessonData.ts` | 新增 | `buildLessonStagesFromRecording()` |
| `GameInfo.ts` | 修改 | 暴露录制数据访问 + dump |
