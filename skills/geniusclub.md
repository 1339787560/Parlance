在这张《崩坏：星穹铁道》的欢聚原画中，**大黑塔**优雅神秘的“人偶魔女”质感与**阮·梅**古典内敛的“基因学者”风格形成了鲜明的对比。

为了满足你的要求，我们将整套 UI 和聊天气泡拆分为两个完全不同的风格包：**【大黑塔·智识星空】**与**【阮·梅·梅染青花】**。你可以通过切换 CSS 变量来一键改变页面风格。

---

### 方案一：【大黑塔·智识星空】风格包

*   **设计精髓：** 突出神秘、精致与天文感。大面积使用**深蓝色与深紫色**作为深夜般的星空幕布，而将**紫罗兰与浅紫色**作为关键高光（模拟她魔女帽上的紫罗兰花朵与人偶关节上的晶体光泽）。

```css
/* ==================== 1. 大黑塔·全局与聊天框样式 ==================== */
:root {
    /* 大黑塔配色系统 */
    --ht-bg-gradient: linear-gradient(135deg, #0F121F 0%, #221230 100%); /* 深蓝到深紫的夜空 */
    --ht-violet: #8A4FFF;          /* 紫罗兰 (关键色) */
    --ht-purple-deep: #3A154E;     /* 深紫 */
    --ht-purple-light: #D3B6F3;    /* 浅紫 (高光) */
    --ht-blue-deep: #141A29;       /* 深蓝色 */
}

/* 页面背景 */
.theme-herta {
    background: var(--ht-bg-gradient);
    color: var(--ht-purple-light);
}

/* 聊天气泡：大黑塔人偶质感 */
.bubble-herta {
    /* 深蓝底色与浅紫透光结合，模拟魔女礼服的丝绒质感 */
    background: linear-gradient(135deg, rgba(20, 26, 41, 0.9) 0%, rgba(58, 21, 78, 0.8) 100%);
    backdrop-filter: blur(8px);
    -webkit-backdrop-filter: blur(8px);
    
    /* 边框：紫罗兰与浅紫的交织线 */
    border: 1.5px solid var(--ht-violet);
    border-radius: 16px 16px 2px 16px;
    
    color: #F3EEF9;
    padding: 12px 18px;
    font-size: 15px;
    line-height: 1.6;
    
    /* 浅紫色的微弱星空发光 */
    box-shadow: 0 4px 20px rgba(138, 79, 255, 0.2),
                inset 0 0 10px rgba(211, 182, 243, 0.15);
    position: relative;
}

/* 气泡顶部的钥匙装饰：代表黑塔的秘密锁匙 */
.bubble-herta::before {
    content: "❖";
    position: absolute;
    top: -8px;
    right: 15px;
    color: var(--ht-purple-light);
    font-size: 12px;
    text-shadow: 0 0 8px var(--ht-violet);
}
```

---

### 方案二：【阮·梅·梅染青花】风格包

*   **设计精髓：** 突出古典、生机与科学儒雅。大面积使用**深青色（旗袍主色）**模拟传统园林的幽静，以**淡金色**勾勒丝弦与器皿，并用点缀性的**洋红紫色（衣服上的梅花刺绣）**作为关键的视觉闪光点。

```css
/* ==================== 2. 阮·梅·全局与聊天框样式 ==================== */
:root {
    /* 阮梅配色系统 */
    --rm-bg-gradient: linear-gradient(135deg, #091C1B 0%, #122D2A 100%); /* 深青色底色 */
    --rm-teal-deep: #133835;       /* 深青色 */
    --rm-gold-light: #E5C17B;      /* 淡金色 */
    --rm-magenta: #BF306F;         /* 洋红紫色 (梅花点缀) */
    --rm-cream: #F4EFEB;           /* 牙白色 */
}

/* 页面背景 */
.theme-ruanmei {
    background: var(--rm-bg-gradient);
    color: var(--rm-cream);
}

/* 聊天气泡：刺绣与丝绸质感 */
.bubble-ruanmei {
    /* 采用高纯度深青色，具有玉石般的半透光泽 */
    background: rgba(19, 56, 53, 0.85);
    backdrop-filter: blur(10px);
    -webkit-backdrop-filter: blur(10px);
    
    /* 边框：极其纤细的淡金色琴弦边 */
    border: 1px solid var(--rm-gold-light);
    border-radius: 12px; /* 较小的圆角，更显典雅稳重 */
    
    color: var(--rm-cream);
    padding: 12px 18px;
    font-size: 15px;
    line-height: 1.6;
    
    /* 阴影：带有洋红紫色的微弱梅香投影 */
    box-shadow: 0 4px 15px rgba(191, 48, 111, 0.15),
                inset 0 0 8px rgba(229, 193, 123, 0.1);
    position: relative;
}

/* 气泡左上角的梅花刺绣图案点缀 */
.bubble-ruanmei::after {
    content: "✿";
    position: absolute;
    top: 6px;
    left: -8px;
    color: var(--rm-magenta);
    font-size: 14px;
    text-shadow: 0 0 6px var(--rm-magenta);
}
```

---

### 三、 功能按钮及交互重构（Skill 融合）

为了让这两种风格在局域网工具中彻底成型，我们可以为输入栏和发送按钮设计**双重主题适配**：

```css
/* --- 输入区域通用基底 --- */
.input-area-custom {
    background: transparent;
    border-top: 1px solid rgba(255, 255, 255, 0.1);
}

/* --- 大黑塔：按键（像发光的星体） --- */
.theme-herta .send-btn {
    background: var(--ht-violet);
    color: #FFF;
    border: none;
    border-radius: 20px;
    box-shadow: 0 4px 12px rgba(138, 79, 255, 0.4);
    transition: all 0.3s;
}
.theme-herta .send-btn:hover {
    background: var(--ht-purple-light);
    color: var(--ht-purple-deep);
    box-shadow: 0 0 15px var(--ht-purple-light);
}

/* --- 阮·梅：按键（像古典印章/金丝镶边） --- */
.theme-ruanmei .send-btn {
    background: var(--rm-teal-deep);
    color: var(--rm-gold-light);
    border: 1px solid var(--rm-gold-light);
    border-radius: 4px; /* 传统直角 */
    font-weight: bold;
    transition: all 0.3s;
}
.theme-ruanmei .send-btn:hover {
    background: var(--rm-magenta); /* 悬停时，如梅花绽放般转为洋红色 */
    color: #FFF;
    border-color: var(--rm-magenta);
    box-shadow: 0 0 12px rgba(191, 48, 111, 0.5);
}
```

### 四、 部署建议

你在前端代码中，只需要将最外层的容器（例如 `<body>` 或 `#app`）加上 `.theme-herta` 或 `.theme-ruanmei` 这一 Class 名字，聊天界面就会在**智识科幻的黑塔魔女风**与**古典儒雅的阮梅园林风**之间自如切换。