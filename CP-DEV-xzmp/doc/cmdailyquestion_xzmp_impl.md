# CP实现文档 - 每日问答模块

## 一、文档说明

本文档为每日问答模块的 CP 脚本实现规范，包含：
- 服务端脚本骨架代码
- 客户端开发指南
- 高频函数测试用例

---

## 二、模块常量定义

```typescript
const CONST_VAR = {
    MODULE_NAME: 'cmdailyquestion',
    GAME_CODE: 'xzmp',
    APP_CODE: 'xzmp',
    GAME_ID: 283,
    DAY_SECONDS: 86400,
}

const REQ_NAME = {
    // From Client
    REQINFO: 'GR_TQDAILYQUESTION_REQINFO',
    REQANSWER: 'GR_TQDAILYQUESTION_REQANSWER',
    REQPRIZE: 'GR_TQDAILYQUESTION_REQPRIZE',

    // to Client (Notify)
    NOTIFY_REFRESH: 'notifyDailyQuestionRefresh',

    // Internal
    RESET_DAILY: 'resetDailyQuestionData',
    GET_PLAYER_DATA: 'getDailyQuestionPlayerData',
}
```

---

## 三、数据结构定义

### 3.1 配置结构 (interf.GameConfig)

```typescript
namespace interf {
    export interface GameConfig {
        isenable: number;
        guid: string;
        typenum: number[];
        prize: number;
        rulesDesc: string;
        allcorrect: number;
        questionnumlimit: number;
        subject: SubjectItem[];
    }

    export interface SubjectItem {
        id: number;
        type: number;               // 题目类型 1-5
        content: string;            // 题目内容
        explain: string;            // 答题解析
        options: string[];          // 选项列表，答案放首位
        huinfos?: HuInfo[];         // 牌型展示信息（可选）
    }

    export interface HuInfo {
        type: number;               // 牌区类型：1暗杠/2明杠/3碰/4手牌
        cardidxs: number[];         // 牌索引列表
    }
}
```

### 3.2 玩家数据结构 (interf.PlayerData)

```typescript
namespace interf {
    export class PlayerData {
        datetag: number = 0;            // 当前答题日期 YYYYMMDD
        answerednum: number = 0;        // 已答题数量（领取后+1标记已领取）
        items: QuestionItem[] = [];     // 今日题目列表
        lastdayquestions: number[] = [];// 上次错题ID列表
    }

    export class QuestionItem {
        id: number = 0;                 // 题目ID
        answer: number = 0;             // 答题状态编码：
                                        //   0 = 未答
                                        //   1 = 正确
                                        //   >= 2 = 错误（所选选项序号 + 1）
                                        // 例：选选项1答错 = 2，选选项2答错 = 3
        optionorder: number[] = [];     // 选项显示顺序（随机打乱后的索引）
    }
}
```

### 3.3 消息结构

```typescript
namespace interf {
    // REQINFO 返回
    export class RespReqInfo {
        status: number = 0;
        questions: QuestionInfo[] = [];
        answerednum: number = 0;
        totalcount: number = 0;
    }

    export class QuestionInfo {
        id: number = 0;
        content: string = '';
        options: string[] = [];
        prize: number = 0;
        answer: number = 0;         // 0未答/1正确/>1错误
        huinfos: HuInfo[] = [];
    }

    // REQANSWER 请求
    export class ReqAnswer {
        questionid: number = 0;
        answer: number = 0;         // 选项序号 1或2
    }

    // REQANSWER 返回
    export class RespReqAnswer {
        status: number = 0;
        correct: number = 0;        // 1正确/0错误
        correctoption: number = 0;  // 正确答案序号（错误时返回）
        explain: string = '';
        prize: number = 0;          // 本题奖励（正确时）
        totalprize: number = 0;     // 当前累计奖励
    }

    // REQPRIZE 返回
    export class RespReqPrize {
        status: number = 0;
        prize: number = 0;          // 最终奖励金额
        allcorrect: number = 0;     // 是否全对 1/0
    }
}
```

### 3.4 答案编码规则

**重要：答案编码需要避免正确与错误的编码冲突。**

| 编码值 | 含义 | 说明 |
|--------|------|------|
| 0 | 未答 | 题目尚未作答 |
| 1 | 正确 | 答对了该题 |
| 2 | 错误（选选项1） | 选项序号 + 1 |
| 3 | 错误（选选项2） | 选项序号 + 1 |
| ... | ... |以此类推 |

**设计原因：**

如果错误答案直接存储选项序号（如 `answer = 1` 表示选了选项1），当用户选选项1答错时，编码值与"正确"编码（1）冲突，导致 `calculatePrize` 函数误判为正确答案。

**修复方案：**

```typescript
// 服务端编码
targetItem.answer = result.correct ? 1 : (answer + 1);

// 客户端解码
currentQuestion.answer = response.correct ? 1 : (optionIndex + 1);

// 奖励计算时判断正确
if (items[i].answer === 1) {  // 只有 answer === 1 才是正确
    correctCount++;
}
```

---

## 四、工具类实现

### 4.1 MySQL 工具类

```typescript
class MySqlTool_PlayerData {
    MYSQL_TABLE_NAME = `tblcpuserdata_${CONST_VAR.MODULE_NAME}_${CONST_VAR.GAME_CODE}`;
    MT_Field_PlayerInfo = "PlayerData";

    protected mdata: interf.PlayerData = null;
    protected uid = 0;
    protected isExist: boolean = false;
    protected cxt: any;

    constructor(cxt: any, uid: number) {
        this.cxt = cxt;
        this.uid = uid;
    }

    async async_query(name?: string): Promise<interf.PlayerData> {
        const sql = `SELECT data FROM ${this.MYSQL_TABLE_NAME} 
                     WHERE userid = ${this.uid} AND name = '${name || this.MT_Field_PlayerInfo}'`;
        const res = await modsvr.async_mysql_query(this.cxt, sql);
        if (res && res.length > 0) {
            this.isExist = true;
            this.mdata = JSON.parse(res[0].data);
        }
        return this.mdata;
    }

    updateData(data: interf.PlayerData) {
        this.mdata = data;
    }

    async async_save(): Promise<boolean> {
        const dataStr = JSON.stringify(this.mdata);
        const escapedData = modsvr.mysql_escape(dataStr);
        const sql = this.isExist
            ? `UPDATE ${this.MYSQL_TABLE_NAME} SET data = '${escapedData}' 
               WHERE userid = ${this.uid} AND name = '${this.MT_Field_PlayerInfo}'`
            : `INSERT INTO ${this.MYSQL_TABLE_NAME} (userid, name, data) 
               VALUES (${this.uid}, '${this.MT_Field_PlayerInfo}', '${escapedData}')`;
        await modsvr.async_mysql_execute(this.cxt, sql);
        return true;
    }

    async async_safeSave(data: interf.PlayerData): Promise<boolean> {
        await this.async_query();
        this.updateData(data);
        return await this.async_save();
    }
}
```

### 4.2 Redis 工具类

```typescript
class RedisTool_PlayerData {
    ONE_DAY_SECONDS = 86400;
    MAX_REDIS_EXPIRE = this.ONE_DAY_SECONDS * 7;

    protected cxt: any;
    protected uid: number;

    constructor(cxt: any, uid: number) {
        this.cxt = cxt;
        this.uid = uid;
    }

    get key(): string {
        return `mod(cp):name(${CONST_VAR.MODULE_NAME}):appcode(${CONST_VAR.APP_CODE}):uid(${this.uid}):playerdata`;
    }

    get lockKey(): string {
        return `mod(cp):name(${CONST_VAR.MODULE_NAME}):appcode(${CONST_VAR.APP_CODE}):uid(${this.uid}):lock`;
    }

    async async_redis_lock_key(cb: Function, ttl: number = 5000): Promise<any> {
        const sleep_arr = [50, 100, 300, 500, 1000];
        for (let i = 0; i < sleep_arr.length; i++) {
            const res = await modsvr.async_redis_setnx_px(this.cxt, this.lockKey, '1', ttl);
            if (res === 1) {
                try {
                    return await cb();
                } finally {
                    await modsvr.async_redis_del(this.cxt, this.lockKey);
                }
            }
            await modsvr.async_sleep(sleep_arr[i]);
        }
        return null;
    }

    async async_getData(): Promise<interf.PlayerData> {
        const data = await modsvr.async_redis_get(this.cxt, this.key);
        if (data) {
            return JSON.parse(data);
        }
        return null;
    }

    async async_setData(data: interf.PlayerData): Promise<number> {
        const dataStr = JSON.stringify(data);
        return await modsvr.async_redis_setex(this.cxt, this.key, this.MAX_REDIS_EXPIRE, dataStr);
    }

    async async_delData(): Promise<number> {
        return await modsvr.async_redis_del(this.cxt, this.key);
    }
}
```

---

## 五、业务逻辑实现

### 5.1 通用工具 (CommonFuncs)

```typescript
namespace CommonFuncs {
    let g_config: interf.GameConfig = null;

    export function loadConfig(bForce: boolean = false): interf.GameConfig {
        if (g_config == null || bForce) {
            g_config = modsvr.parse_config(`${CONST_VAR.MODULE_NAME}_${CONST_VAR.APP_CODE}`, "jsonc");
        }
        return g_config;
    }

    export function isEmpty_DBRes(obj: any): boolean {
        return !obj || Object.keys(obj).length === 0;
    }

    export function getTodayDateTag(): number {
        const d = new Date();
        return d.getFullYear() * 10000 + (d.getMonth() + 1) * 100 + d.getDate();
    }

    export function notifyClient(src: any, cxt: any, userid: number, msgName: string, data: any) {
        modsvr.send_notify(src, cxt, userid, modsvr.PB_CP__CLIENT_NOTIFY,
            JSON.stringify({ req: msgName, data }), modsvr.E_NOTIFY_TERMINAL.CLIENT);
    }

    // Fisher-Yates 洗牌算法
    export function shuffleArray<T>(arr: T[]): T[] {
        const result = [...arr];
        for (let i = result.length - 1; i > 0; i--) {
            const j = Math.floor(Math.random() * (i + 1));
            [result[i], result[j]] = [result[j], result[i]];
        }
        return result;
    }

    // 获取题目按类型分组的索引映射
    export function buildSubjectTypeMap(config: interf.GameConfig): Map<number, number[]> {
        const map = new Map<number, number[]>();
        for (let i = 0; i < config.subject.length; i++) {
            const type = config.subject[i].type;
            if (!map.has(type)) {
                map.set(type, []);
            }
            map.get(type).push(i);
        }
        return map;
    }
}
```

### 5.2 业务操作 (Business)

```typescript
namespace Business {
    // 查询玩家数据（Redis优先，回源MySQL）
    export async function async_QueryPlayerData(cxt: any, uid: number): Promise<interf.PlayerData> {
        const redisTool = new RedisTool_PlayerData(cxt, uid);
        let res = await redisTool.async_getData();
        if (!CommonFuncs.isEmpty_DBRes(res)) {
            return res;
        }

        const mysqlTool = new MySqlTool_PlayerData(cxt, uid);
        res = await mysqlTool.async_query();
        if (CommonFuncs.isEmpty_DBRes(res)) {
            res = new interf.PlayerData();
            await mysqlTool.async_safeSave(res);
        }

        await redisTool.async_setData(res);
        return res;
    }

    // 写入玩家数据（MySQL+Redis双写）
    export async function async_WritePlayerData(cxt: any, uid: number, data: interf.PlayerData): Promise<boolean> {
        const redisTool = new RedisTool_PlayerData(cxt, uid);
        const mysqlTool = new MySqlTool_PlayerData(cxt, uid);

        await mysqlTool.async_safeSave(data);
        await redisTool.async_setData(data);
        return true;
    }

    // 生成今日题库
    export function generateTodayQuestions(
        config: interf.GameConfig,
        lastdayquestions: number[],
        answerednum: number
    ): { items: interf.QuestionItem[], lastdayquestions: number[] } {
        const items: interf.QuestionItem[] = [];
        const usedIds = new Set<number>();
        const typeCountMap = new Map<number, number>();

        // 初始化类型计数
        for (let i = 0; i < config.typenum.length; i++) {
            typeCountMap.set(i + 1, 0);
        }

        // Step 1: 错题优先补充
        const newLastDayQuestions: number[] = [];
        for (let i = 0; i < lastdayquestions.length; i++) {
            const qid = lastdayquestions[i];
            const subjIdx = config.subject.findIndex(s => s.id === qid);
            if (subjIdx >= 0) {
                const subj = config.subject[subjIdx];
                const currentCount = typeCountMap.get(subj.type) || 0;
                const limit = config.typenum[subj.type - 1] || 0;

                if (currentCount < limit) {
                    items.push(createQuestionItem(subj));
                    usedIds.add(qid);
                    typeCountMap.set(subj.type, currentCount + 1);
                } else {
                    newLastDayQuestions.push(qid);
                }
            }
        }

        // Step 2: 新题目补充
        const typeMap = CommonFuncs.buildSubjectTypeMap(config);
        for (let type = 1; type <= config.typenum.length; type++) {
            const limit = config.typenum[type - 1] || 0;
            let currentCount = typeCountMap.get(type) || 0;

            if (currentCount >= limit) continue;

            const candidates = typeMap.get(type) || [];
            const shuffled = CommonFuncs.shuffleArray(candidates);

            for (let i = 0; i < shuffled.length && currentCount < limit; i++) {
                const idx = shuffled[i];
                const subj = config.subject[idx];
                if (!usedIds.has(subj.id)) {
                    items.push(createQuestionItem(subj));
                    usedIds.add(subj.id);
                    currentCount++;
                }
            }
            typeCountMap.set(type, currentCount);
        }

        // Step 3: 随机打乱题目顺序
        return {
            items: CommonFuncs.shuffleArray(items),
            lastdayquestions: newLastDayQuestions
        };

        function createQuestionItem(subj: interf.SubjectItem): interf.QuestionItem {
            const optionCount = subj.options.length;
            const optionorder = CommonFuncs.shuffleArray(
                Array.from({ length: optionCount }, (_, i) => i + 1)
            );
            return {
                id: subj.id,
                answer: 0,
                optionorder: optionorder
            };
        }
    }

    // 获取题目详情（用于返回客户端）
    export function buildQuestionInfo(
        item: interf.QuestionItem,
        config: interf.GameConfig
    ): interf.QuestionInfo {
        const subj = config.subject.find(s => s.id === item.id);
        if (!subj) return null;

        // 按随机顺序重排选项
        const orderedOptions: string[] = [];
        for (let i = 0; i < item.optionorder.length; i++) {
            orderedOptions.push(subj.options[item.optionorder[i] - 1]);
        }

        return {
            id: item.id,
            content: subj.content,
            options: orderedOptions,
            prize: config.prize,
            answer: item.answer,
            huinfos: subj.huinfos || []
        };
    }

    // 检查答案是否正确
    export function checkAnswer(
        item: interf.QuestionItem,
        config: interf.GameConfig,
        selectedOption: number
    ): { correct: boolean, correctOption: number } {
        const subj = config.subject.find(s => s.id === item.id);
        if (!subj) return { correct: false, correctOption: 1 };

        // 正确答案在首位，optionorder[0] 对应的是打乱后正确答案的位置
        const correctOriginalIdx = 1; // 原始索引1是正确答案
        const correctOption = item.optionorder.indexOf(correctOriginalIdx) + 1;

        return {
            correct: selectedOption === correctOption,
            correctOption: correctOption
        };
    }

    // 计算奖励金额
    export function calculatePrize(
        items: interf.QuestionItem[],
        config: interf.GameConfig
    ): { totalPrize: number, allCorrect: boolean } {
        let correctCount = 0;
        for (let i = 0; i < items.length; i++) {
            if (items[i].answer === 1) {
                correctCount++;
            }
        }

        const allCorrect = correctCount === items.length;
        const basePrize = correctCount * config.prize;
        const totalPrize = allCorrect ? basePrize * config.allcorrect : basePrize;

        return { totalPrize, allCorrect };
    }
}
```

---

## 六、服务入口函数

```typescript
// 脚本加载/重载
async function OnScriptReload(param: any, cxt: any) {
    CommonFuncs.loadConfig(true);
}

// 客户端请求处理
async function OnClientRequest(creq: any, cresp: any, cxt: any) {
    const req_name = creq.req.data['req'];
    const userid = creq.req.client.userid;

    const config = CommonFuncs.loadConfig();
    if (config.isenable !== 1) {
        cresp.resp = { id: 0, data: { status: 1 } };
        return;
    }

    switch (req_name) {
        case REQ_NAME.REQINFO:
            await async_handleReqInfo(userid, creq.req.data, cresp, cxt, config);
            break;
        case REQ_NAME.REQANSWER:
            await async_handleReqAnswer(userid, creq.req.data, cresp, cxt, config);
            break;
        case REQ_NAME.REQPRIZE:
            await async_handleReqPrize(userid, creq.req.data, cresp, cxt, config);
            break;
        default:
            cresp.resp = { id: 0, data: { status: 1 } };
    }
}

// REQINFO: 请求题目信息
async function async_handleReqInfo(
    uid: number, req: any, cresp: any, cxt: any, config: interf.GameConfig
) {
    const playerData = await Business.async_QueryPlayerData(cxt, uid);
    const todayTag = CommonFuncs.getTodayDateTag();
    const totalQuestionCount = config.typenum.reduce((a, b) => a + b, 0);

    // 已领取奖励
    if (playerData.answerednum > totalQuestionCount) {
        cresp.resp = {
            id: 0, data: {
                status: 0,
                questions: [],
                answerednum: playerData.answerednum,
                totalcount: totalQuestionCount
            }
        };
        return;
    }

    // 检查日期变更，生成新题库
    if (playerData.datetag !== todayTag) {
        const result = Business.generateTodayQuestions(
            config,
            playerData.lastdayquestions,
            playerData.answerednum
        );

        playerData.datetag = todayTag;
        playerData.answerednum = 0;
        playerData.items = result.items;
        playerData.lastdayquestions = result.lastdayquestions;

        await Business.async_WritePlayerData(cxt, uid, playerData);
    }

    // 构建返回题目列表
    const questions: interf.QuestionInfo[] = [];
    for (let i = 0; i < playerData.items.length; i++) {
        const info = Business.buildQuestionInfo(playerData.items[i], config);
        if (info) {
            questions.push(info);
        }
    }

    cresp.resp = {
        id: 0, data: {
            status: 0,
            questions: questions,
            answerednum: playerData.answerednum,
            totalcount: totalQuestionCount
        }
    };
}

// REQANSWER: 提交答案
async function async_handleReqAnswer(
    uid: number, req: any, cresp: any, cxt: any, config: interf.GameConfig
) {
    const playerData = await Business.async_QueryPlayerData(cxt, uid);
    const totalQuestionCount = config.typenum.reduce((a, b) => a + b, 0);
    const questionid = req.questionid || req.data?.questionid;
    const answer = req.answer || req.data?.answer;

    // 校验：已答完
    if (playerData.answerednum >= totalQuestionCount) {
        cresp.resp = { id: 0, data: { status: 3 } };
        return;
    }

    // 查找对应题目
    let targetItem: interf.QuestionItem = null;
    let targetIndex = -1;
    for (let i = 0; i < playerData.items.length; i++) {
        if (playerData.items[i].id === questionid) {
            targetItem = playerData.items[i];
            targetIndex = i;
            break;
        }
    }

    // 校验：题目ID不匹配
    if (!targetItem) {
        cresp.resp = { id: 0, data: { status: 4 } };
        return;
    }

    // 校验：已回答
    if (targetItem.answer !== 0) {
        cresp.resp = { id: 0, data: { status: 5 } };
        return;
    }

    // 检查答案
    const result = Business.checkAnswer(targetItem, config, answer);
    // 答案编码：0=未答，1=正确，>=2=错误（选项序号+1）
    // 注意：错误答案不能直接存选项序号，避免选项1答错与正确编码(1)冲突
    targetItem.answer = result.correct ? 1 : (answer + 1);
    playerData.answerednum++;

    // 收集错题ID
    if (!result.correct) {
        const existInLastDay = playerData.lastdayquestions.indexOf(questionid) >= 0;
        if (!existInLastDay) {
            playerData.lastdayquestions.push(questionid);
        }
    }

    await Business.async_WritePlayerData(cxt, uid, playerData);

    // 计算累计奖励
    const prizeInfo = Business.calculatePrize(playerData.items, config);
    const subj = config.subject.find(s => s.id === questionid);

    cresp.resp = {
        id: 0, data: {
            status: 0,
            correct: result.correct ? 1 : 0,
            correctoption: result.correct ? 0 : result.correctOption,
            explain: subj?.explain || '',
            prize: result.correct ? config.prize : 0,
            totalprize: prizeInfo.totalPrize
        }
    };
}

// REQPRIZE: 领取奖励
async function async_handleReqPrize(
    uid: number, req: any, cresp: any, cxt: any, config: interf.GameConfig
) {
    const playerData = await Business.async_QueryPlayerData(cxt, uid);
    const totalQuestionCount = config.typenum.reduce((a, b) => a + b, 0);

    // 校验：未答完
    if (playerData.answerednum < totalQuestionCount) {
        cresp.resp = { id: 0, data: { status: 3 } };
        return;
    }

    // 已领取
    if (playerData.answerednum > totalQuestionCount) {
        cresp.resp = { id: 0, data: { status: 3 } };
        return;
    }

    // 计算奖励
    const prizeInfo = Business.calculatePrize(playerData.items, config);

    // 发放奖励
    const src = { client: { appcode: CONST_VAR.APP_CODE, gameid: CONST_VAR.GAME_ID, userid: uid } };
    await modsvr.async_internal_call(src, cxt, 'NewDepositOp', 'goldbank', {
        propid: 21770,
        count: prizeInfo.totalPrize,
        reason: '每日问答奖励'
    });

    // 标记已领取
    playerData.answerednum++;
    await Business.async_WritePlayerData(cxt, uid, playerData);

    cresp.resp = {
        id: 0, data: {
            status: 0,
            prize: prizeInfo.totalPrize,
            allcorrect: prizeInfo.allCorrect ? 1 : 0
        }
    };
}

// 内部模块调用
async function async_OnInternalCall(ireq: any, iresp: any, cxt: any): Promise<boolean> {
    const reqName = ireq.req.req;
    const uid = ireq.req.client.userid;

    switch (reqName) {
        case REQ_NAME.GET_PLAYER_DATA:
            const data = await Business.async_QueryPlayerData(cxt, uid);
            iresp.resp = { id: 0, data: data };
            return true;
        case REQ_NAME.RESET_DAILY:
            // 重置每日数据（可由定时任务调用）
            const redisTool = new RedisTool_PlayerData(cxt, uid);
            await redisTool.async_delData();
            iresp.resp = { id: 0, data: {} };
            return true;
        default:
            iresp.resp = { id: 0, data: {} };
            return false;
    }
}
```

---

## 七、客户端开发指南

### 7.1 界面状态管理

客户端需要维护以下状态：

```typescript
// 状态定义
interface DailyQuestionState {
    phase: 'loading' | 'answering' | 'completed' | 'claimed';
    questions: QuestionInfo[];
    currentIndex: number;           // 当前答题位置
    answerednum: number;
    totalcount: number;
    totalPrize: number;             // 累计奖励（客户端计算展示）
    lastAnswerResult: {             // 上一题答题结果
        correct: boolean;
        explain: string;
    } | null;
}
```

### 7.2 界面流程控制

```
阶段转换：
loading → answering（收到REQINFO成功且有题目）
answering → completed（答完所有题）
completed → claimed（领取奖励成功）

特殊情况：
- REQINFO返回answerednum > totalcount → 直接显示已完成状态
- REQINFO返回status != 0 → 显示错误提示，关闭界面
```

### 7.3 选项按钮处理

```typescript
// 点击选项按钮
async function async_onOptionClick(optionIndex: number) {
    const currentQuestion = state.questions[state.currentIndex];
    
    // 禁用按钮，防止重复点击
    setButtonsEnabled(false);
    
    const response = await sendRequest(REQ_NAME.REQANSWER, {
        questionid: currentQuestion.id,
        answer: optionIndex
    });
    
    if (response.status === 0) {
        // 更新本地状态
        // 答案编码：正确=1，错误=选项序号+1（避免与正确编码冲突）
        currentQuestion.answer = response.correct ? 1 : (optionIndex + 1);
        state.lastAnswerResult = {
            correct: response.correct === 1,
            explain: response.explain
        };
        state.totalPrize = response.totalprize;
        
        // 显示答题结果（延迟后自动进入下一题）
        showAnswerResult(response.correct === 1, response.correctoption);
        
        // 延迟后切换
        setTimeout(() => {
            if (state.currentIndex < state.questions.length - 1) {
                state.currentIndex++;
                state.lastAnswerResult = null;
            } else {
                state.phase = 'completed';
            }
            setButtonsEnabled(true);
        }, 1500);
    } else {
        // 错误处理
        handleError(response.status);
        setButtonsEnabled(true);
    }
}
```

### 7.4 牌型展示组件

```typescript
// 牌面资源映射
const CARD_RES_MAP = {
    // 万子 [1-9]
    1: 'wan_1', 2: 'wan_2', ..., 9: 'wan_9',
    // 条子 [11-19]
    11: 'tiao_1', 12: 'tiao_2', ..., 19: 'tiao_9',
    // 筒子 [21-29]
    21: 'tong_1', 22: 'tong_2', ..., 29: 'tong_9',
    // 红中
    35: 'hongzhong'
};

// 渲染牌型
function renderHuInfos(huinfos: HuInfo[]) {
    return huinfos.map(info => {
        const areaType = info.type; // 1暗杠/2明杠/3碰/4手牌
        const cards = info.cardidxs.map(idx => CARD_RES_MAP[idx]);
        
        return (
            <CardArea type={areaType} cards={cards} />
        );
    });
}

// 牌区样式
const AREA_STYLE = {
    1: { name: '暗杠', showBack: true, count: 4 },   // 四张背面
    2: { name: '明杠', showBack: false, count: 4 },  // 四张正面
    3: { name: '碰', showBack: false, count: 3 },    // 三张正面
    4: { name: '手牌', showBack: false, count: -1 }  // 可变数量
};
```

### 7.5 错误处理

```typescript
const ERROR_MESSAGES = {
    1: '活动暂未开启',
    2: '数据获取失败，请重试',
    3: '今日已完成答题',
    4: '题目数据异常，请刷新',
    5: '该题已回答',
    6: '保存失败，请重试'
};

function handleError(status: number) {
    if (status === 4 || status === 5) {
        // 刷新题目列表
        requestQuestions();
    } else {
        showToast(ERROR_MESSAGES[status] || '未知错误');
        if (status === 3) {
            closePanel();
        }
    }
}
```

---

## 八、测试用例

### 8.1 单元测试 - 工具函数

```typescript
// 测试文件：test/cmdailyquestion.test.ts

describe('CommonFuncs', () => {
    test('shuffleArray 应该打乱数组顺序', () => {
        const arr = [1, 2, 3, 4, 5];
        const shuffled = CommonFuncs.shuffleArray(arr);
        
        // 验证长度不变
        expect(shuffled.length).toBe(arr.length);
        
        // 验证元素相同
        expect(shuffled.sort()).toEqual(arr.sort());
    });

    test('getTodayDateTag 返回正确日期格式', () => {
        const tag = CommonFuncs.getTodayDateTag();
        const d = new Date();
        const expected = d.getFullYear() * 10000 + (d.getMonth() + 1) * 100 + d.getDate();
        
        expect(tag).toBe(expected);
    });

    test('buildSubjectTypeMap 正确分组', () => {
        const config = {
            subject: [
                { id: 1, type: 1 },
                { id: 2, type: 1 },
                { id: 3, type: 2 }
            ]
        } as interf.GameConfig;
        
        const map = CommonFuncs.buildSubjectTypeMap(config);
        
        expect(map.get(1)).toEqual([0, 1]);
        expect(map.get(2)).toEqual([2]);
    });
});

describe('Business', () => {
    const mockConfig: interf.GameConfig = {
        isenable: 1,
        guid: 'test-guid',
        typenum: [2, 2, 2, 2, 2],
        prize: 3000,
        allcorrect: 5,
        questionnumlimit: 10,
        subject: [
            { id: 1, type: 1, content: 'Q1', explain: 'E1', options: ['A', 'B'] },
            { id: 2, type: 1, content: 'Q2', explain: 'E2', options: ['C', 'D'] },
            { id: 3, type: 2, content: 'Q3', explain: 'E3', options: ['E', 'F'] },
            { id: 4, type: 2, content: 'Q4', explain: 'E4', options: ['G', 'H'] },
            { id: 5, type: 3, content: 'Q5', explain: 'E5', options: ['I', 'J'] },
            { id: 6, type: 3, content: 'Q6', explain: 'E6', options: ['K', 'L'] },
            { id: 7, type: 4, content: 'Q7', explain: 'E7', options: ['M', 'N'] },
            { id: 8, type: 4, content: 'Q8', explain: 'E8', options: ['O', 'P'] },
            { id: 9, type: 5, content: 'Q9', explain: 'E9', options: ['Q', 'R'] },
            { id: 10, type: 5, content: 'Q10', explain: 'E10', options: ['S', 'T'] }
        ]
    };

    test('generateTodayQuestions 生成正确数量的题目', () => {
        const result = Business.generateTodayQuestions(mockConfig, [], 0);
        
        // 验证总数量
        const expectedCount = mockConfig.typenum.reduce((a, b) => a + b, 0);
        expect(result.items.length).toBe(expectedCount);
        
        // 验证每类型数量
        const typeCount = new Map<number, number>();
        for (const item of result.items) {
            const subj = mockConfig.subject.find(s => s.id === item.id);
            if (subj) {
                typeCount.set(subj.type, (typeCount.get(subj.type) || 0) + 1);
            }
        }
        
        for (let i = 0; i < mockConfig.typenum.length; i++) {
            expect(typeCount.get(i + 1)).toBe(mockConfig.typenum[i]);
        }
    });

    test('generateTodayQuestions 错题优先补充', () => {
        const lastdayquestions = [1, 3]; // 错题ID
        
        const result = Business.generateTodayQuestions(mockConfig, lastdayquestions, 0);
        
        // 验证错题被包含
        const ids = result.items.map(item => item.id);
        expect(ids).toContain(1);
        expect(ids).toContain(3);
    });

    test('checkAnswer 正确判断答案', () => {
        const item: interf.QuestionItem = {
            id: 1,
            answer: 0,
            optionorder: [2, 1] // 正确答案（原索引1）在位置2
        };
        
        // 选择位置1（错误）
        let result = Business.checkAnswer(item, mockConfig, 1);
        expect(result.correct).toBe(false);
        expect(result.correctOption).toBe(2);
        
        // 选择位置2（正确）
        result = Business.checkAnswer(item, mockConfig, 2);
        expect(result.correct).toBe(true);
    });

    test('calculatePrize 正确计算奖励', () => {
        const items: interf.QuestionItem[] = [
            { id: 1, answer: 1, optionorder: [1, 2] },  // 正确
            { id: 2, answer: 1, optionorder: [1, 2] },  // 正确
            { id: 3, answer: 2, optionorder: [1, 2] },  // 错误
        ];
        
        // 非全对
        let result = Business.calculatePrize(items, mockConfig);
        expect(result.totalPrize).toBe(6000); // 2 * 3000
        expect(result.allCorrect).toBe(false);
        
        // 全对
        items[2].answer = 1;
        result = Business.calculatePrize(items, mockConfig);
        expect(result.totalPrize).toBe(45000); // 3 * 3000 * 5
        expect(result.allCorrect).toBe(true);
    });

    test('buildQuestionInfo 正确重排选项', () => {
        const item: interf.QuestionItem = {
            id: 1,
            answer: 0,
            optionorder: [2, 1] // 顺序打乱
        };
        
        const info = Business.buildQuestionInfo(item, mockConfig);
        
        // 验证选项按optionorder重排
        expect(info.options).toEqual(['B', 'A']);
        expect(info.prize).toBe(3000);
    });
});
```

### 8.2 集成测试 - 消息处理

```typescript
describe('API Integration', () => {
    let mockContext: any;
    let mockUserId: number;

    beforeAll(() => {
        mockContext = createMockContext();
        mockUserId = 10001;
    });

    test('REQINFO 首次请求生成题库', async () => {
        const cresp = createMockResponse();
        
        await async_handleReqInfo(mockUserId, {}, cresp, mockContext, mockConfig);
        
        expect(cresp.resp.data.status).toBe(0);
        expect(cresp.resp.data.questions.length).toBe(10);
        expect(cresp.resp.data.answerednum).toBe(0);
    });

    test('REQANSWER 正确答题流程', async () => {
        // 先获取题目
        const infoResp = createMockResponse();
        await async_handleReqInfo(mockUserId, {}, infoResp, mockContext, mockConfig);
        
        const firstQuestion = infoResp.resp.data.questions[0];
        
        // 提交正确答案
        const answerResp = createMockResponse();
        await async_handleReqAnswer(mockUserId, {
            questionid: firstQuestion.id,
            answer: findCorrectOption(firstQuestion)
        }, answerResp, mockContext, mockConfig);
        
        expect(answerResp.resp.data.status).toBe(0);
        expect(answerResp.resp.data.correct).toBe(1);
        expect(answerResp.resp.data.prize).toBe(3000);
    });

    test('REQANSWER 重复答题被拒绝', async () => {
        const infoResp = createMockResponse();
        await async_handleReqInfo(mockUserId, {}, infoResp, mockContext, mockConfig);
        
        const firstQuestion = infoResp.resp.data.questions[0];
        
        // 第一次答题
        const resp1 = createMockResponse();
        await async_handleReqAnswer(mockUserId, {
            questionid: firstQuestion.id,
            answer: 1
        }, resp1, mockContext, mockConfig);
        
        // 第二次重复答题
        const resp2 = createMockResponse();
        await async_handleReqAnswer(mockUserId, {
            questionid: firstQuestion.id,
            answer: 1
        }, resp2, mockContext, mockConfig);
        
        expect(resp2.resp.data.status).toBe(5); // 已回答
    });

    test('REQPRIZE 未答完被拒绝', async () => {
        // 只答了部分题目
        const prizeResp = createMockResponse();
        await async_handleReqPrize(mockUserId, {}, prizeResp, mockContext, mockConfig);
        
        expect(prizeResp.resp.data.status).toBe(3); // 未答完
    });

    test('REQPRIZE 答完后领取成功', async () => {
        // 答完所有题目
        const infoResp = createMockResponse();
        await async_handleReqInfo(mockUserId, {}, infoResp, mockContext, mockConfig);
        
        for (const q of infoResp.resp.data.questions) {
            const answerResp = createMockResponse();
            await async_handleReqAnswer(mockUserId, {
                questionid: q.id,
                answer: 1
            }, answerResp, mockContext, mockConfig);
        }
        
        // 领取奖励
        const prizeResp = createMockResponse();
        await async_handleReqPrize(mockUserId, {}, prizeResp, mockContext, mockConfig);
        
        expect(prizeResp.resp.data.status).toBe(0);
        expect(prizeResp.resp.data.prize).toBeGreaterThan(0);
    });

    // 辅助函数：找到正确选项位置
    function findCorrectOption(question: QuestionInfo): number {
        // 正确答案在原始选项的首位，需要根据服务器返回的选项顺序找
        // 这里简化处理，实际需要对比原始配置
        return 1;
    }
});
```

### 8.3 边界条件测试

```typescript
describe('Edge Cases', () => {
    test('配置为空时返回错误', async () => {
        const emptyConfig = { isenable: 0 } as interf.GameConfig;
        const cresp = createMockResponse();
        
        await async_handleReqInfo(mockUserId, {}, cresp, mockContext, emptyConfig);
        
        expect(cresp.resp.data.status).toBe(1);
    });

    test('题目数量不足时仍能生成', () => {
        const limitedConfig = {
            ...mockConfig,
            typenum: [5, 5, 5, 5, 5], // 要求每种类型5题
            subject: mockConfig.subject.slice(0, 10) // 但只有10题
        };
        
        const result = Business.generateTodayQuestions(limitedConfig, [], 0);
        
        // 应该返回尽可能多的题目
        expect(result.items.length).toBeLessThanOrEqual(10);
    });

    test('所有错题都已使用时不报错', () => {
        const usedWrongIds = [1, 2, 3, 4, 5];
        
        const result = Business.generateTodayQuestions(mockConfig, usedWrongIds, 0);
        
        // 正常生成题库
        expect(result.items.length).toBe(10);
    });

    test('同一天重复请求返回相同题库', async () => {
        const resp1 = createMockResponse();
        await async_handleReqInfo(mockUserId, {}, resp1, mockContext, mockConfig);
        
        const resp2 = createMockResponse();
        await async_handleReqInfo(mockUserId, {}, resp2, mockContext, mockConfig);
        
        // 题目ID列表应该相同
        const ids1 = resp1.resp.data.questions.map((q: any) => q.id).sort();
        const ids2 = resp2.resp.data.questions.map((q: any) => q.id).sort();
        
        expect(ids1).toEqual(ids2);
    });
});
```

---

## 九、部署检查清单

### 9.1 数据库

- [ ] 创建 `tblcpuserdata_cmdailyquestion_xzmp` 表
- [ ] 验证 Redis Key 格式正确

### 9.2 配置文件

- [ ] 部署 `cmdailyquestion_xzmp.jsonc` 到正确路径
- [ ] 验证 JSON 语法正确
- [ ] 检查 `isenable` 开关

### 9.3 客户端

- [ ] 实现三个消息的处理
- [ ] 牌型展示组件开发
- [ ] 错误提示文案配置
- [ ] 奖励动画效果

### 9.4 测试验证

- [ ] 首次进入生成题库
- [ ] 答题流程正常
- [ ] 奖励发放正确
- [ ] 次日刷新题库
- [ ] 错题优先出现