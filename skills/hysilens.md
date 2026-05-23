这张海瑟音（Hazein）的立绘极具深水漂浮感，画面上方有神圣的光芒投射，周围环绕着宛如红珊瑚般的洋红色光效与幽静的深蓝水体，气泡和虚实结合的光晕赋予了角色一种神秘而清冷的气质。

为了契合你的要求，我们将其重构为一套**“深海潮汐·科幻水质”**主题的全局样式与聊天气泡。以下是为你定制的 CSS 样式配置。

---

### 一、 海瑟音主题色彩系统 (Color System)

*   **主色调（暖/暗）：** `洋红紫 #D81B60`、`深海蓝 #101B2B`、`深紫 #300C3F`。
*   **高光与渐变（冷/亮）：** `天蓝色 #70C3FC`、`银蓝色 #A3C6D6`。

通过 CSS，我们将网页背景重构为一个**深水光影空间**，模拟光线射入深海、在水底产生折射的梦幻感。

```css
/* ==================== 海瑟音主题全局样式 ==================== */
:root {
    /* 核心色彩 */
    --hz-magenta: #D12E6B;       /* 洋红紫 */
    --hz-deep-blue: #0E1826;     /* 深海蓝 */
    --hz-dark-purple: #2D0F3F;   /* 深紫色 */
    --hz-sky-blue: #70C3FC;      /* 天蓝色 */
    --hz-silver-blue: #A3C6D6;   /* 银蓝色 */
    
    /* 渐变组合：模拟水底光影 */
    --hz-water-bg: linear-gradient(135deg, #0E1826 0%, #2D0F3F 50%, #152A42 100%);
}

/* 全局背景 */
body {
    background: var(--hz-water-bg);
    background-attachment: fixed;
    color: #E6F3FF;
    font-family: 'PingFang SC', 'Microsoft YaHei', sans-serif;
    margin: 0;
    min-height: 100vh;
    position: relative;
}

/* 模拟立绘上方的天蓝色/银蓝色折射光晕 */
body::before {
    content: "";
    position: absolute;
    top: 0;
    left: 10%;
    width: 80%;
    height: 350px;
    background: radial-gradient(circle, rgba(112, 195, 252, 0.15) 0%, rgba(163, 198, 214, 0.05) 50%, transparent 100%);
    pointer-events: none;
    z-index: 1;
}

/* 模拟立绘边缘的洋红色珊瑚光斑 */
body::after {
    content: "";
    position: absolute;
    bottom: 0;
    right: 5%;
    width: 600px;
    height: 600px;
    background: radial-gradient(circle, rgba(209, 46, 107, 0.12) 0%, transparent 70%);
    pointer-events: none;
    z-index: 1;
}
```

---

### 二、 聊天气泡样式

根据你的设计规则，我们将聊天框区分为**“他人的洋红深蓝渐变”**与**“自己的水感高透明度渐变”**。

#### 1. 他人消息气泡（洋红紫与深蓝渐变）
*   **设计：** 还原立绘中**暗部水流与红色光效的交织**。采用斜向渐变，边缘使用低饱和度的洋红勾勒，文字使用高对比度的冰蓝色。

```css
/* --- 他人消息气泡 (洋红紫与深蓝渐变) --- */
.bubble-haze-other {
    /* 1. 渐变色：洋红紫 -> 深海蓝 */
    background: linear-gradient(135deg, rgba(209, 46, 107, 0.85) 0%, rgba(14, 24, 38, 0.9) 100%);
    
    /* 2. 边框：半透明洋红紫，保留边界感 */
    border: 1px solid rgba(209, 46, 107, 0.4);
    
    /* 3. 字体颜色：清透的银蓝色 */
    color: #EBF5FA;
    
    border-radius: 2px 16px 16px 16px;
    padding: 12px 18px;
    font-size: 15px;
    line-height: 1.6;
    
    /* 4. 阴影：带有一点深紫色的神秘微光 */
    box-shadow: 0 4px 15px rgba(45, 15, 63, 0.3),
                inset 0 1px 0 rgba(255, 255, 255, 0.1);
                
    position: relative;
}

/* 气泡左侧的装饰线：天蓝色与银蓝色交织 */
.bubble-haze-other::before {
    content: "";
    position: absolute;
    top: 15px;
    left: -4px;
    width: 3px;
    height: 16px;
    background: var(--hz-sky-blue);
    border-radius: 2px;
}
```

#### 2. 自己消息气泡（高透明、水质感天蓝与深蓝渐变）
*   **设计：** 还原立绘中**清澈的水泡与光照反射**。通过高透明度的蓝色渐变与 `backdrop-filter` 达到液体折射效果，内阴影（`inset shadow`）则用于模拟水珠的表面张力与高光。

```css
/* --- 自己消息气泡 (高透明水质感：天蓝与深海蓝渐变) --- */
.bubble-haze-mine {
    /* 1. 渐变色：天蓝色(低饱和度高透) -> 深海蓝(高透) */
    background: linear-gradient(135deg, rgba(112, 195, 252, 0.35) 0%, rgba(14, 24, 38, 0.75) 100%);
    
    /* 2. 强力的毛玻璃效果，模拟水质的折射 */
    backdrop-filter: blur(12px);
    -webkit-backdrop-filter: blur(12px);
    
    /* 3. 边框：水光感银蓝色 */
    border: 1px solid rgba(163, 198, 214, 0.5);
    
    /* 4. 字体颜色：纯净的冰白色 */
    color: #FFFFFF;
    
    border-radius: 16px 16px 2px 16px;
    padding: 12px 18px;
    font-size: 15px;
    line-height: 1.6;
    
    /* 5. 核心：内阴影模拟水泡的边缘高光与立体感 */
    box-shadow: 
        inset 0 0 12px rgba(255, 255, 255, 0.25), /* 顶部高光 */
        0 4px 15px rgba(14, 24, 38, 0.4);         /* 底部阴影 */
        
    position: relative;
}

/* 气泡右侧装饰：一个微小的水泡折射点 */
.bubble-haze-mine::after {
    content: "";
    position: absolute;
    top: 8px;
    right: 12px;
    width: 6px;
    height: 3px;
    background: rgba(255, 255, 255, 0.4);
    border-radius: 50%;
}
```

---

### 三、 辅助组件设计建议

为了让这套水系皮肤更完整，建议将输入框与发送按钮修改为以下样式：

```css
/* 输入框：科技质感的透明水舱 */
.input-box-custom {
    background: rgba(14, 24, 38, 0.6);
    backdrop-filter: blur(8px);
    border: 1px solid rgba(163, 198, 214, 0.3);
    color: #FFFFFF;
    border-radius: 8px;
}
.input-box-custom:focus {
    border-color: var(--hz-sky-blue);
    box-shadow: 0 0 10px rgba(112, 195, 252, 0.3);
}

/* 发送按钮：洋红色能量流 */
.send-btn-custom {
    background: var(--hz-magenta);
    color: #FFFFFF;
    border: none;
    border-radius: 4px;
    box-shadow: 0 4px 10px rgba(209, 46, 107, 0.4);
    transition: all 0.3s;
}
.send-btn-custom:hover {
    background: #E91E63;
    box-shadow: 0 0 15px rgba(209, 46, 107, 0.7);
    transform: translateY(-1px);
}
```