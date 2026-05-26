为了完美呈现《崩坏：星穹铁道》中顶级黑客**“银狼（Silver Wolf）”**——即游戏主宰“狼尊 LV.99”的赛博朋克黑客风，我们将整个界面重构为**“全息全真终端面板”**。

设计核心围绕她那标志性的**炫彩防辐射眼镜/镜片折射光**，并为所有 UI 元素注入高饱和度的**霓虹光晕（Neon Glow）**与**像素电子风**。

---

### 一、 镜片色聊天气泡设计

我们根据银狼防辐射眼镜在不同光线下的双色渐变，设计了两款极具赛博霓虹感的聊天框：

#### 1. 气泡 A：【量子霓虹】（青色到紫色渐变）
*   **设计：** 模拟镜片左侧折射出的全息青色到霓虹深紫。边缘采用高亮霓虹青色包边，自带闪烁微光。

#### 2. 气泡 B：【狂热朋克】（洋红紫色到金黄色渐变）
*   **设计：** 模拟镜片右侧折射出的爆裂洋红与街机金黄。带有些许复古像素游戏机的狂热感。

```css
/* ==================== 1. 银狼镜片色聊天框 ==================== */

/* --- [气泡 A：量子霓虹（青色 to 紫色）] --- */
.bubble-sw-cyan-purple {
    /* 1. 镜片青紫渐变 */
    background: linear-gradient(135deg, rgba(0, 255, 204, 0.75) 0%, rgba(154, 0, 255, 0.75) 100%);
    backdrop-filter: blur(10px);
    -webkit-backdrop-filter: blur(10px);
    
    /* 2. 霓虹青色发光边框 */
    border: 1.5px solid #00FFCC;
    border-radius: 12px 12px 2px 12px; /* 较硬朗的圆角 */
    
    color: #FFFFFF;
    font-weight: 500;
    padding: 12px 18px;
    font-size: 15px;
    line-height: 1.6;
    
    /* 3. 青色与紫色交织的双重霓虹投影 */
    box-shadow: 0 0 15px rgba(0, 255, 204, 0.3),
                inset 0 0 10px rgba(154, 0, 255, 0.4);
    position: relative;
}

/* 气泡全息点缀（角落像素十字花） */
.bubble-sw-cyan-purple::before {
    content: "✚";
    position: absolute;
    top: 6px;
    right: 12px;
    color: #00FFCC;
    font-size: 10px;
    text-shadow: 0 0 5px #00FFCC;
}

/* --- [气泡 B：狂热朋克（洋红紫 to 金黄色）] --- */
.bubble-sw-magenta-gold {
    /* 1. 镜片洋红金黄渐变 */
    background: linear-gradient(135deg, rgba(255, 0, 127, 0.8) 0%, rgba(255, 174, 0, 0.8) 100%);
    backdrop-filter: blur(10px);
    -webkit-backdrop-filter: blur(10px);
    
    /* 2. 霓虹洋红发光边框 */
    border: 1.5px solid #FF007F;
    border-radius: 12px 12px 12px 2px;
    
    color: #FFFFFF;
    font-weight: 500;
    padding: 12px 18px;
    font-size: 15px;
    line-height: 1.6;
    
    /* 3. 街机金红色的亮烈阴影 */
    box-shadow: 0 0 15px rgba(255, 0, 127, 0.4),
                inset 0 0 10px rgba(255, 174, 0, 0.3);
    position: relative;
}

.bubble-sw-magenta-gold::before {
    content: "✚";
    position: absolute;
    top: 6px;
    left: 12px;
    color: #FFAE00;
    font-size: 10px;
    text-shadow: 0 0 5px #FFAE00;
}
```

---

### 二、 其他组件的“霓虹全息”重构样式

我们将局域网的其余组件改造为类似游戏 HUD（平视显示器）的质感，黑夜深处闪烁着红蓝霓虹。

```css
/* ==================== 2. 全息 HUD 霓虹组件 ==================== */

/* --- 全局背景：赛博街机暗室 + 幽灵霓虹网格 --- */
body {
    background-color: #070312; /* 极深墨紫 */
    /* 带有极其淡雅的赛博数字网格底纹 */
    background-image: 
        linear-gradient(rgba(154, 0, 255, 0.04) 1px, transparent 1px),
        linear-gradient(90deg, rgba(154, 0, 255, 0.04) 1px, transparent 1px);
    background-size: 30px 30px;
    background-attachment: fixed;
    color: #00FFCC;
}

/* --- 顶栏/标题 (模拟全息游戏公告牌) --- */
.header-container {
    background: rgba(11, 7, 24, 0.8);
    backdrop-filter: blur(10px);
    /* 洋红底线 border */
    border-bottom: 2px solid #FF007F;
    /* 霓虹发光文字 */
    color: #00FFCC;
    font-family: 'Consolas', monospace;
    text-shadow: 0 0 8px #00FFCC, 0 0 15px rgba(0, 255, 204, 0.6);
    box-shadow: 0 4px 20px rgba(255, 0, 127, 0.15);
}

/* --- 底部输入框 (黑客终端输入栏) --- */
.input-box {
    background: #0C0819;
    border: 1.5px solid #9A00FF; /* 霓虹紫 */
    color: #00FFCC;
    border-radius: 4px; /* 采用硬朗风格 */
    box-shadow: inset 0 0 8px rgba(154, 0, 255, 0.3);
    font-family: 'Consolas', monospace;
    transition: all 0.3s ease;
}

.input-box:focus {
    outline: none;
    border-color: #00FFCC; /* 激活时切换至量子青色 */
    box-shadow: 0 0 15px rgba(0, 255, 204, 0.4), 
                inset 0 0 10px rgba(0, 255, 204, 0.2);
}

/* --- 发送按钮 (GAME START 街机实体按键) --- */
.send-btn {
    background: #FF007F; /* 洋红底色 */
    color: #FFFFFF;
    border: none;
    border-radius: 4px;
    font-family: 'Consolas', monospace;
    font-weight: bold;
    letter-spacing: 1px;
    cursor: pointer;
    /* 亮黄色霓虹投影 */
    box-shadow: 0 0 12px rgba(255, 0, 127, 0.6), 
                0 0 20px rgba(255, 174, 0, 0.2);
    transition: all 0.2s;
}

.send-btn:hover {
    background: #FF2E93;
    /* 悬停时转换为金黄色耀眼光芒 */
    box-shadow: 0 0 20px #FFCC00, 
                0 0 30px rgba(255, 0, 127, 0.8);
    transform: translateY(-1px);
}

.send-btn:active {
    transform: translateY(1px);
    box-shadow: 0 0 5px #FF007F;
}
```

### 三、 氛围提升建议 (Glitch Details)

在界面的一些边角细节处，可以使用这种**黑客特性的像素点缀**：

1.  **指示灯：** 在状态连接（127.0.0.1:5000）的小圆点上，加入强烈的高光：
    ```css
    .status-dot {
        background-color: #00FFCC;
        box-shadow: 0 0 10px #00FFCC, 0 0 20px #00FFCC;
    }
    ```
2.  **文件图标：** 将附件图标换成像素风的“游戏手柄”或者“骷髅头/电子狼”的线性图样。

这套设计完全释放了赛博朋克的叛逆与高对比色之美，能够将你的局域网服务变成一个炫酷的“狼尊黑客终端”！