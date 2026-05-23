太棒了！从古风瞬间切换到**二次元/原神珊瑚宫心海（Sangonomiya Kokomi）**的风格，这个跨度非常有创意。

心海的视觉核心词汇是：**“海祇岛”、“真珠”、“水母”、“梦幻”、“水波”、“浅蓝与浅珊瑚粉的交织”**。

为了体现这种“水月镜花”的梦幻感，我们不能只用死板的纯色块。我们需要引入**“毛玻璃效果 (Glassmorphism)”**来模拟水体的清透感，并使用**“大量圆角 (Bubble Shapes)”**来模拟水泡。

以下是为你量身定制的“珊瑚宫心海——海祇真珠”主题 CSS 改造方案：

### 一、 视觉设计基调 (Design System)

1.  **核心色板 (Kokomi Palette)：**
    *   **背景：** `浅海蓝` 向 `珊瑚粉` 过渡的柔和渐变色，模拟阳光穿透海面的梦幻感。
    *   **主色（强调/按钮）：** `珊瑚粉 #F29CB2` 与 `海祇蓝 #8CB9D6`。
    *   **面板/气泡：** 采用带透明度的白色 `rgba(255, 255, 255, 0.65)`，配合毛玻璃模糊效果。
    *   **文本颜色：** 放弃纯黑，使用深海蓝（藏青色） `#2C3E50`，保证清晰度的同时融入水系主题。
2.  **UI 形状与质感 (Bubble & Pearl)：**
    *   **气泡化圆角：** 所有的聊天框、输入框全部采用大圆角（`16px` 到 `24px`），像水母和气泡一样圆润。
    *   **真珠光泽（发光与阴影）：** 使用轻柔的粉色和蓝色投影，代替生硬的黑色阴影，营造“发光体”的感觉。

---

### 二、 改造 CSS 代码参考 (Skill 注入)

请将以下 CSS 代码覆盖到你的项目中。这段代码会利用 CSS3 的渐变和背景模糊属性，打造极具二次元梦幻感的界面。

```css
/* 1. 定义心海主题色彩与渐变变量 */
:root {
    /* 梦幻水面渐变背景 (浅海蓝 -> 珊瑚粉) */
    --koko-bg-gradient: linear-gradient(135deg, #E1F0FF 0%, #FCE8F0 100%);
    
    /* 核心点缀色 */
    --koko-pink: #F29CB2;         /* 珊瑚粉 */
    --koko-pink-hover: #E0859E;   /* 珊瑚粉加深 */
    --koko-blue: #8CB9D6;         /* 海祇蓝 */
    --koko-deep-blue: #2A4365;    /* 深海蓝 (主文字色) */
    --koko-text-light: #718096;   /* 浅灰蓝 (次要文字色/时间) */
    
    /* 毛玻璃质感 (水泡/贝壳) */
    --koko-glass-bg: rgba(255, 255, 255, 0.65);
    --koko-glass-border: rgba(255, 255, 255, 0.8);
    --koko-shadow: 0 8px 32px rgba(140, 185, 214, 0.15); /* 浅蓝色柔和投影 */
}

/* 2. 全局设定 (水系柔和排版) */
body {
    background: var(--koko-bg-gradient);
    background-attachment: fixed; /* 背景固定，滚动时更梦幻 */
    color: var(--koko-deep-blue);
    font-family: 'Nunito', 'PingFang SC', 'Microsoft YaHei', sans-serif; /* 推荐使用圆润的无衬线字体 */
    letter-spacing: 0.2px;
}

/* 3. 顶栏 (模拟水面漂浮的控制台) */
.header-container { 
    background: var(--koko-glass-bg);
    backdrop-filter: blur(12px); /* 毛玻璃模糊效果 */
    -webkit-backdrop-filter: blur(12px);
    border-bottom: 1px solid var(--koko-glass-border);
    color: var(--koko-deep-blue);
    font-weight: bold;
    box-shadow: 0 2px 10px rgba(242, 156, 178, 0.1); /* 微微的粉色高光 */
}

/* 4. 聊天消息容器 (水泡形设计) */
.message-bubble { 
    background: var(--koko-glass-bg);
    backdrop-filter: blur(8px);
    -webkit-backdrop-filter: blur(8px);
    border: 1px solid var(--koko-glass-border);
    /* 像水滴一样的圆角设计：三个大圆角，一个尖角指向发送方 */
    border-radius: 20px 20px 20px 4px; 
    box-shadow: var(--koko-shadow);
    color: var(--koko-deep-blue);
    padding: 12px 18px;
    font-size: 15px;
    line-height: 1.5;
    transition: transform 0.2s ease;
}
.message-bubble:hover {
    transform: translateY(-2px); /* 鼠标悬停时像气泡一样微微上浮 */
}

/* 自己发送的消息可以换向 (如果你的HTML有区分的话) */
.message-bubble.mine {
    border-radius: 20px 20px 4px 20px; 
    background: rgba(252, 232, 240, 0.7); /* 自己发的消息偏粉色一点 */
}

/* 5. 发送者IP标识 (像一颗小珍珠/贝壳标签) */
.sender-ip { 
    background: linear-gradient(135deg, var(--koko-blue), var(--koko-pink));
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent; /* 字体渐变色 */
    background-clip: text;
    color: var(--koko-pink); /* Fallback */
    font-weight: 800;
    font-size: 0.85em;
    padding: 0;
    margin-bottom: 6px;
    display: inline-block;
}

/* 6. 时间标签 (浅水色) */
.message-time {
    color: var(--koko-text-light);
    font-size: 0.8em;
    margin-left: 8px;
}

/* 7. 文件下载框 (水母的包裹) */
.file-box {
    background: rgba(255, 255, 255, 0.5);
    border: 1px solid var(--koko-glass-border);
    border-radius: 16px;
    padding: 10px;
    margin-top: 8px;
}
/* 下载按钮 - 采用心海服装的蓝粉渐变 */
.download-btn {
    background: linear-gradient(135deg, var(--koko-blue), var(--koko-pink));
    color: white;
    border: none;
    border-radius: 20px; /* 胶囊形按钮 */
    padding: 6px 16px;
    font-weight: bold;
    box-shadow: 0 4px 10px rgba(242, 156, 178, 0.3);
    transition: all 0.3s ease;
    cursor: pointer;
}
.download-btn:hover {
    box-shadow: 0 6px 15px rgba(242, 156, 178, 0.5);
    transform: translateY(-1px);
    filter: brightness(1.1); /* 悬停变亮 */
}

/* 8. 底部输入区域 (悬浮玻璃台) */
.input-area {
    background: transparent;
    padding: 15px;
    border: none;
}
.input-box { 
    background: var(--koko-glass-bg);
    backdrop-filter: blur(10px);
    border: 2px solid var(--koko-glass-border);
    color: var(--koko-deep-blue);
    border-radius: 24px; /* 极圆润的输入框 */
    padding: 12px 20px;
    box-shadow: var(--koko-shadow);
    transition: border-color 0.3s;
}
.input-box:focus {
    outline: none;
    border-color: var(--koko-pink); /* 聚焦时亮粉色边框 */
    background: rgba(255, 255, 255, 0.9);
}
.input-box::placeholder {
    color: #A0AEC0;
}

/* 9. 发送按钮 (水泡按键) */
.send-btn {
    background: var(--koko-pink);
    color: white;
    border: none;
    border-radius: 50%; /* 如果按钮是图标，建议做成正圆形；如果是文字，用24px大圆角 */
    border-radius: 24px; 
    padding: 12px 24px;
    font-weight: bold;
    cursor: pointer;
    box-shadow: 0 4px 12px rgba(242, 156, 178, 0.4);
    transition: all 0.3s cubic-bezier(0.25, 0.8, 0.25, 1);
}
.send-btn:hover {
    background: var(--koko-pink-hover);
    transform: scale(1.05); /* 悬停时微微放大，像呼吸一样 */
    box-shadow: 0 6px 16px rgba(242, 156, 178, 0.6);
}
```

### 三、 进阶“海祇岛”氛围感拉满的建议

1.  **水泡漂浮动画 (CSS Animation)：**
    如果你愿意加一点点动效，可以在背景里用纯 CSS 加上几个缓慢上升的水泡。心海的技能满屏幕都是水母和水泡，加上这个效果会绝杀。
2.  **字体推荐：**
    中式古典要求“娟秀”，但心海的二次元风格要求“可爱、圆润”。强烈建议在 CSS 的 `font-family` 中引入 **“Nunito”** (Google Fonts 可免费引入) 或者 **“圆体 (STYuanTi)”**，这会让整体的气质温柔很多。
3.  **图标替换 (Iconography)：**
    *   将聊天框左下角的“曲别针(附件)”换成**“粉色的小贝壳”**图标。
    *   将“打包箱(压缩包)”换成**“一颗漂浮的珍珠”**或者**“水母”**的简笔画图标。
    *   如果你用 FontAwesome 等图标库，可以寻找 rounded 风格的图标。
4.  **滚动条 (Scrollbar) 隐藏化：**
    二次元清爽风格最忌讳粗笨的滚动条。建议用伪类把滚动条改得极细，或者设置成半透明的浅蓝色，甚至在非 hover 状态下隐藏它。

这套配置应用上去之后，你的聊天界面会立刻变得像“水族馆”一样晶莹剔透、充满治愈感！你可以对比一下这套“水系毛玻璃”和上一套“宣纸枯木”的效果，挑选最适合你心境的一个。