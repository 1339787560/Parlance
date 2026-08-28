/**
 * skin-manifest.js — 统一皮肤清单
 *
 * 每个皮肤固定三部分：
 *   1. bg      背景图及资源（image + overlay）
 *   2. css     颜色变量（--cn-* 由 infoServer static/style.css 提供）+ 共享组件 CSS（skin-runner 注入）
 *   3. shader  全屏特殊效果（GLSL；custom = 专属文件，generic = 通用主题色 shader）
 *
 * 使用：<script src="http://localhost:5001/static/skin-manifest.js"></script>
 * 之后 window.SKIN_MANIFEST 可用。
 */
window.SKIN_MANIFEST = {
  red: {
    label: "朱砂红",
    dark: false,
    bg: { image: "", overlay: "" },
    colors: ["#B32A26", "#C39A5B", "#2C251F"],
    shader: "generic",
  },
  default: {
    label: "简约配色",
    dark: false,
    bg: { image: "", overlay: "" },
    colors: ["#1A73E8", "#5F6368", "#1A1A1A"],
    shader: "generic",
  },
  kokomi: {
    label: "珊瑚宫心海",
    dark: false,
    bg: {
      image: "/style/kokomi/kokomi.png",
      overlay:
        "linear-gradient(135deg, rgba(225,240,255,.55), rgba(252,232,240,.55))",
    },
    colors: ["#F29CB2", "#8CB9D6", "#2A4365"],
    shader: "generic",
  },
  firefly: {
    label: "流萤·萨姆",
    dark: false,
    bg: {
      image: "/style/firefly/firefly.png",
      overlay:
        "linear-gradient(135deg, rgba(229,243,241,.55), rgba(236,233,242,.55), rgba(245,235,240,.55))",
    },
    colors: ["#FF5E3A", "#FFBF00", "#16463C"],
    shader: "generic",
  },
  furina: {
    label: "芙宁娜·歌剧院",
    dark: true,
    bg: {
      image: "/style/furina/furina.png",
      overlay:
        "radial-gradient(circle 900px at top center, rgba(255,235,190,.15) 0%, rgba(255,250,230,.03) 50%, rgba(18,11,11,.7) 100%), linear-gradient(135deg, rgba(18,11,11,.45), rgba(18,11,11,.25))",
    },
    colors: ["#D9B36C", "#E6C57E", "#120B0B"],
    shader: "generic",
  },
  hysilens: {
    label: "海瑟音·深境",
    dark: true,
    bg: {
      image: "/style/Hysilens/Hysilens.jpg",
      overlay:
        "radial-gradient(ellipse 80% 35% at 50% 0%, rgba(112,195,252,.12) 0%, transparent 70%), radial-gradient(ellipse 40% 30% at 10% 100%, rgba(209,46,107,.10) 0%, transparent 70%), linear-gradient(135deg, rgba(14,24,38,.4), rgba(45,15,63,.3), rgba(21,42,66,.4))",
    },
    colors: ["#D12E6B", "#70C3FC", "#0E1826"],
    shader: "generic",
  },
  geniusclub: {
    label: "天才俱乐部",
    dark: true,
    bg: {
      image: "/style/geniusclub/geniusclub.png",
      overlay:
        "radial-gradient(ellipse 70% 40% at 50% 0%, rgba(138,79,255,.08) 0%, transparent 70%), radial-gradient(ellipse 40% 25% at 80% 100%, rgba(229,193,123,.06) 0%, transparent 60%), linear-gradient(135deg, rgba(15,18,31,.5), rgba(34,18,48,.4))",
    },
    colors: ["#8A4FFF", "#E5C17B", "#0F121F"],
    shader: "generic",
  },
  silverwolf: {
    label: "狼尊 LV.999",
    dark: true,
    bg: {
      image: "/style/silverwolf/silverwolf.png",
      overlay: "linear-gradient(#070312, rgba(7,3,18,.4))",
    },
    colors: ["#FF007F", "#00FFCC", "#070312"],
    shader: "custom",
  },
  odette: {
    label: "奥黛塔·月夜羽翼",
    dark: true,
    bg: {
      image: "/style/odette/odette.jpg",
      overlay:
        "radial-gradient(circle at 50% 30%, rgba(123,228,255,.15) 0%, transparent 60%), linear-gradient(to bottom, rgba(8,13,36,.2), rgba(8,13,36,.85))",
    },
    colors: ["#7BE4FF", "#FF5C98", "#080D24"],
    shader: "generic",
  },
};
