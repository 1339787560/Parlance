precision highp float;

uniform float u_time;
uniform vec2 u_resolution;
uniform vec3 u_color_a;
uniform vec3 u_color_b;
uniform vec3 u_color_c;

void main() {
    vec2 uv = gl_FragCoord.xy / u_resolution;
    vec2 p = uv - 0.5;

    // 基础底色：主题深色/浅色纸色微染（半透明，让背景图透出）
    vec3 col = u_color_c * 0.10;

    // 三色缓慢游走光晕
    vec2 centers[3];
    centers[0] = vec2(0.5 + sin(u_time * 0.10) * 0.38, 0.5 + cos(u_time * 0.08) * 0.38);
    centers[1] = vec2(0.5 + sin(u_time * 0.07 + 2.1) * 0.32, 0.5 + cos(u_time * 0.12 + 2.1) * 0.32);
    centers[2] = vec2(0.5 + sin(u_time * 0.13 + 4.2) * 0.34, 0.5 + cos(u_time * 0.09 + 4.2) * 0.34);

    vec3 glowColors[3];
    glowColors[0] = u_color_a;
    glowColors[1] = u_color_b;
    glowColors[2] = u_color_a * 0.6 + u_color_b * 0.4;

    for (int i = 0; i < 3; i++) {
        float dist = length(uv - centers[i]);
        float glow = exp(-dist * 6.0);
        float pulse = sin(u_time * 0.35 + float(i) * 2.1) * 0.5 + 0.5;
        col += glowColors[i] * glow * pulse * 0.055;
    }

    // 微弱流光波线（分割线/边缘高光的氛围来源）
    float wave = sin(uv.y * 55.0 + u_time * 0.7 + sin(uv.x * 9.0 + u_time * 1.2) * 1.4);
    col += u_color_a * wave * 0.010;

    // 另一组反向波线，增加层次
    float wave2 = cos(uv.x * 45.0 - u_time * 0.5 + cos(uv.y * 7.0 + u_time * 0.9) * 1.1);
    col += u_color_b * wave2 * 0.008;

    // 边缘暗角
    vec2 vig = uv * (1.0 - uv);
    float vignette = 1.0 - pow(vig.x * vig.y * 8.0, 0.25);
    col *= vignette;

    // 半透明输出：让背景图/底色透出，形成“背景图 + shader 特效”双层效果
    gl_FragColor = vec4(col, 0.60);
}
