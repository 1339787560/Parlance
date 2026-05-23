芙宁娜（Furina）的角色魅力在于其鲜明的**“戏剧舞台感”**与**“双重人格（黑白芙）的宿命交织”**。

根据你提供的精美舞台聚光灯剧照，我为你设计了一整套**“欧庇克莱歌剧院·独舞”**主题的全局样式，以及高度对应黑白芙细节的聊天框样式。

---

### 一、 整体舞台样式：戏剧与聚光灯（Theatrical Stage UI）

我们将整个网页背景重构为一个**暗色调的歌剧院舞台**，通过 CSS 径向渐变（Radial Gradient）在屏幕中央投射一束**戏剧性的温暖聚光灯**，将聊天区域框在光束之中。

```css
/* ==================== 整体舞台与聚光灯样式 ==================== */
:root {
    /* 舞台暗部：剧照中两侧观众的暗红焦糖色与深沉黑 */
    --stage-dark: #120B0B;
    --stage-wing: #1C1212;
    
    /* 聚光灯：暖金色光束 */
    --spotlight-beam: rgba(255, 235, 190, 0.15);
    --spotlight-center: rgba(255, 250, 230, 0.05);
}

/* 全局背景：模拟聚光灯从顶部打向舞台中央的效果 */
body {
    background-color: var(--stage-dark);
    /* 径向渐变：在屏幕上方中央创造一个向外扩散的光束 */
    background-image: 
        radial-gradient(circle 800px at top center, var(--spotlight-beam) 0%, var(--spotlight-center) 50%, var(--stage-dark) 100%);
    background-attachment: fixed;
    color: #E2E8F0;
    font-family: 'Times New Roman', 'PingFang SC', sans-serif;
    margin: 0;
    min-height: 100vh;
}

/* 聊天主体容器：让它像悬浮在舞台聚光灯下的台本 */
.chat-container {
    background: rgba(20, 15, 15, 0.6);
    backdrop-filter: blur(8px);
    -webkit-backdrop-filter: blur(8px);
    border-left: 1px solid rgba(255, 235, 190, 0.1);
    border-right: 1px solid rgba(255, 235, 190, 0.1);
    /* 舞台灯光投影 */
    box-shadow: 0 0 40px rgba(255, 235, 190, 0.05);
}

/* 滚动条：暗色木质感 */
::-webkit-scrollbar {
    width: 6px;
}
::-webkit-scrollbar-track {
    background: var(--stage-dark);
}
::-webkit-scrollbar-thumb {
    background: rgba(255, 235, 190, 0.2);
    border-radius: 3px;
}
```

---

### 二、 聊天框样式：白芙与黑芙的交响

#### 方案 A：【白芙 · 众水的歌者】（浅蓝白色、星空蓝、金色镶边）
*   **设计意境：** 模拟白芙华丽的浅蓝色礼服与金色的王冠。气泡轻盈通透，边缘环绕高贵的金丝，字体使用深邃的星空蓝。适合作为**发送端（或日常交流）**。

```css
/* --- 白芙气泡 (浅蓝白、星空蓝、金边) --- */
.bubble-furina-white {
    /* 1. 主色：温柔的浅蓝白渐变 */
    background: linear-gradient(135deg, #F0F6FC 0%, #DCE8F5 100%);
    
    /* 2. 金色镶边：礼服上的皇家金丝 */
    border: 1.5px solid #D9B36C;
    
    /* 3. 字体：深邃的星空蓝 */
    color: #1A335B;
    
    border-radius: 16px 16px 2px 16px;
    padding: 12px 18px;
    font-size: 15px;
    line-height: 1.6;
    
    /* 4. 投影：微弱的星光蓝晕染 */
    box-shadow: 0 4px 15px rgba(59, 98, 155, 0.15),
                inset 0 1px 0 #FFFFFF;
    position: relative;
}

/* 顶部星轨装饰：代表命之座的星芒 */
.bubble-furina-white::before {
    content: "✦";
    position: absolute;
    top: -8px;
    right: 15px;
    color: #D9B36C;
    font-size: 14px;
    text-shadow: 0 0 5px rgba(217, 179, 108, 0.8);
}
```

---

#### 方案 B：【黑芙 · 孤悬的独舞】（水质感、礼服蓝、银白与黑、蕾丝短袜）
*   **设计意境：** 对应黑芙沉静的黑色短礼服与水神之眼的液态水感。气泡呈现水波般的深蓝色毛玻璃质感，底部利用虚线和微影，巧妙隐喻她极具标志性的**“黑白不对称蕾丝短袜”**。适合作为**接收端（或深思沉稳发言）**。

```css
/* --- 黑芙气泡 (水质感、礼服蓝、银黑、蕾丝纹) --- */
.bubble-furina-black {
    /* 1. 水质感：高透明度、深邃的礼服蓝 */
    background: linear-gradient(135deg, rgba(28, 46, 74, 0.85) 0%, rgba(17, 22, 34, 0.9) 100%);
    backdrop-filter: blur(12px);
    -webkit-backdrop-filter: blur(12px);
    
    /* 2. 边框：银白色的细致冷光 */
    border: 1px solid rgba(234, 236, 239, 0.3);
    
    /* 3. 字体：银白色 */
    color: #EAECEF;
    
    border-radius: 16px 16px 16px 2px;
    padding: 12px 18px;
    font-size: 15px;
    line-height: 1.6;
    
    /* 4. 投影：如深水般的静谧感 */
    box-shadow: 0 8px 25px rgba(0, 0, 0, 0.3),
                inset 0 0 8px rgba(234, 236, 239, 0.1);
    position: relative;
    overflow: hidden;
}

/* 底部蕾丝短袜花边样式模拟 (Lace Trim) */
.bubble-furina-black::after {
    content: "";
    position: absolute;
    bottom: 0;
    left: 0;
    right: 0;
    height: 4px;
    /* 利用 CSS 渐变绘制黑白交替的微型蕾丝网格与荷叶边阴影 */
    background-image: repeating-linear-gradient(45deg, 
        rgba(234, 236, 239, 0.2) 0px, 
        rgba(234, 236, 239, 0.2) 1px, 
        transparent 1px, 
        transparent 4px
    );
    border-top: 1px dashed rgba(234, 236, 239, 0.4);
}
```

---

### 三、 交互细节小技巧

在输入框的发送按钮上，为了配合舞台效果，你可以添加以下 CSS：

```css
/* 发送按钮：模拟聚光灯打在演员身上的高光激活 */
.stage-send-btn {
    background: #1C2E4A;
    color: #E6C57E; /* 经典金 */
    border: 1px solid #D9B36C;
    transition: all 0.3s ease;
}

.stage-send-btn:hover {
    /* 鼠标悬停时，像聚光灯聚焦一样，按钮爆发出明亮的光芒 */
    background: #D9B36C;
    color: #120B0B;
    box-shadow: 0 0 15px rgba(217, 179, 108, 0.6);
    transform: scale(1.02);
}
```