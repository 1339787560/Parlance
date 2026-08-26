结合这张**奥黛塔（Odette / 天鹅湖与月夜羽翼）**的插画气质，整个设计应突显**“空灵冷艳、月影流光、冰晶羽毛、轻盈与破笼之美”**。

以下为你量身定制的应用程序 **CSS 样式体系、调色方案、UI 组件样式及专属动效/技能卡片实现**：

---

### 一、 视觉调色板与设计变量（Design Tokens）

基于插画提取的关键色彩与光效变量：

```css
:root {
  /* 主色调：深邃夜空与纯白羽翼 */
  --bg-deep-night: #080d24;
  --swan-white: #f8fbff;
  --swan-silver: rgba(240, 246, 255, 0.85);

  /* 核心高光色：月光青、冰晶蓝与星辰金 */
  --moon-cyan: #7be4ff;
  --ice-blue: #93c5fd;
  --star-gold: #fef08a;

  /* 点缀色：缎带玫粉（破笼与执念） */
  --accent-ribbon-pink: #ff5c98;
  --accent-ribbon-glow: rgba(255, 92, 152, 0.4);

  /* 玻璃拟态与流光边框 */
  --glass-bg: rgba(15, 23, 56, 0.55);
  --glass-border: rgba(147, 197, 253, 0.25);
  --glass-glow: 0 8px 32px 0 rgba(0, 180, 255, 0.15);
  
  /* 字体推荐：空灵典雅风格 */
  --font-title: 'Cinzel', 'Cormorant Garamond', 'Songti SC', serif;
  --font-ui: 'Plus Jakarta Sans', system-ui, sans-serif;
}
```

---

### 二、 背景壁纸与主容器排版（Background Setup）

为确保上层 UI 清晰可读，同时不掩盖壁纸的月夜光华，建议叠加一层带有冷光径向渐变的遮罩层：

```css
/* 应用主容器背景 */
.app-container {
  min-height: 100vh;
  width: 100vw;
  position: relative;
  background-color: var(--bg-deep-night);
  /* 替换为你的壁纸路径 */
  background-image: 
    radial-gradient(circle at 50% 30%, rgba(123, 228, 255, 0.15) 0%, transparent 60%),
    linear-gradient(to bottom, rgba(8, 13, 36, 0.2), rgba(8, 13, 36, 0.85)),
    url('your-odette-wallpaper.png');
  background-size: cover;
  background-position: center top;
  background-attachment: fixed;
  color: var(--swan-white);
  font-family: var(--font-ui);
  overflow-x: hidden;
}
```

---

### 三、 专属 UI 组件与羽翼光效（CSS Component Styles）

#### 1. 月影玻璃卡片 (Moonlit Glass Card)
带有冰晶边缘高光和轻微羽毛漂浮浮雕感：

```css
.odette-card {
  background: var(--glass-bg);
  backdrop-filter: blur(16px);
  -webkit-backdrop-filter: blur(16px);
  border: 1px solid var(--glass-border);
  border-radius: 16px;
  box-shadow: var(--glass-glow), inset 0 1px 0 rgba(255, 255, 255, 0.2);
  padding: 24px;
  position: relative;
  overflow: hidden;
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
}

.odette-card::before {
  content: '';
  position: absolute;
  top: 0;
  left: -100%;
  width: 100%;
  height: 100%;
  background: linear-gradient(
    90deg,
    transparent,
    rgba(255, 255, 255, 0.08),
    transparent
  );
  transition: 0.5s;
}

.odette-card:hover {
  transform: translateY(-4px);
  border-color: var(--moon-cyan);
  box-shadow: 0 12px 40px rgba(123, 228, 255, 0.25), 
              0 0 15px rgba(255, 92, 152, 0.2);
}

.odette-card:hover::before {
  left: 100%;
}
```

#### 2. 星芒粉缎按钮 (Starlight & Ribbon Button)

```css
.odette-btn {
  position: relative;
  background: linear-gradient(135deg, rgba(123, 228, 255, 0.2), rgba(255, 92, 152, 0.25));
  border: 1px solid rgba(255, 255, 255, 0.4);
  color: var(--swan-white);
  padding: 10px 24px;
  border-radius: 9999px;
  font-family: var(--font-title);
  font-size: 14px;
  letter-spacing: 2px;
  cursor: pointer;
  box-shadow: 0 4px 15px rgba(0, 0, 0, 0.3);
  transition: all 0.3s ease;
}

.odette-btn:hover {
  background: linear-gradient(135deg, var(--moon-cyan), var(--accent-ribbon-pink));
  color: #050a1e;
  font-weight: 600;
  box-shadow: 0 0 20px var(--moon-cyan), 0 0 35px var(--accent-ribbon-glow);
  transform: scale(1.03);
}
```

---

### 四、 角色技能/状态展示卡片（Skill / Profile Card 示例）

以下是一个可直接复用的 HTML/CSS 代码段，展现奥黛塔的**天鹅月华技能（Swan Feather Burst）**：

```html
<div class="skill-container">
  <div class="odette-card skill-card">
    <div class="skill-header">
      <span class="skill-tag">ELEMENTAL BURST</span>
      <h2 class="skill-title">月辉·绝响天鹅之誓</h2>
    </div>
    
    <div class="skill-icon-wrapper">
      <div class="skill-orb"></div>
    </div>
    
    <p class="skill-desc">
      解开束缚之笼，舒展纯白光羽。在月影湖面唤起持续的冰晶羽刃，对大范围敌人造成连续的月华伤害，并为全队附加「羽化破茧」状态。
    </p>

    <div class="skill-stats">
      <div class="stat-item">
        <span class="label">冷却时间</span>
        <span class="val">18.0s</span>
      </div>
      <div class="stat-item">
        <span class="label">能量消耗</span>
        <span class="val">60</span>
      </div>
    </div>

    <button class="odette-btn">释放誓约</button>
  </div>
</div>
```

```css
/* 技能卡片特化样式 */
.skill-container {
  display: flex;
  justify-content: center;
  align-items: center;
  padding: 40px;
}

.skill-card {
  max-width: 380px;
  text-align: center;
}

.skill-tag {
  font-size: 11px;
  color: var(--accent-ribbon-pink);
  letter-spacing: 3px;
  font-weight: 700;
  text-shadow: 0 0 8px var(--accent-ribbon-glow);
}

.skill-title {
  font-family: var(--font-title);
  font-size: 22px;
  margin: 8px 0 16px;
  color: var(--swan-white);
  text-shadow: 0 0 12px rgba(123, 228, 255, 0.6);
}

.skill-icon-wrapper {
  margin: 16px auto;
  width: 70px;
  height: 70px;
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
}

/* 仿月球/技能核心光球动效 */
.skill-orb {
  width: 50px;
  height: 50px;
  border-radius: 50%;
  background: radial-gradient(circle, #fff 0%, var(--moon-cyan) 60%, transparent 100%);
  box-shadow: 0 0 25px var(--moon-cyan), inset 0 0 10px #fff;
  animation: pulseGlow 3s infinite alternate ease-in-out;
}

.skill-desc {
  font-size: 13px;
  line-height: 1.6;
  color: var(--swan-silver);
  margin-bottom: 20px;
}

.skill-stats {
  display: flex;
  justify-content: space-around;
  margin-bottom: 24px;
  padding: 12px 0;
  border-top: 1px solid rgba(255, 255, 255, 0.1);
  border-bottom: 1px solid rgba(255, 255, 255, 0.1);
}

.stat-item .label {
  display: block;
  font-size: 12px;
  color: rgba(255, 255, 255, 0.5);
}

.stat-item .val {
  font-size: 15px;
  font-weight: bold;
  color: var(--moon-cyan);
}

@keyframes pulseGlow {
  0% {
    transform: scale(0.95);
    box-shadow: 0 0 15px var(--moon-cyan);
  }
  100% {
    transform: scale(1.08);
    box-shadow: 0 0 30px var(--moon-cyan), 0 0 45px var(--accent-ribbon-glow);
  }
}
```