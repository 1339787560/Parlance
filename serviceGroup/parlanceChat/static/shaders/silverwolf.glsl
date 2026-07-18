precision highp float;

uniform float u_time;
uniform vec2 u_resolution;

void main() {
    vec2 uv = gl_FragCoord.xy / u_resolution;

    // --- Base: 极深墨紫 #070312 ---
    vec3 col = vec3(0.027, 0.012, 0.071);

    // --- 全息网格 ---
    vec2 gv = uv * 32.0;
    vec2 gw = 1.0 - abs(fract(gv) - 0.5) * 2.0;
    float grid = 1.0 - min(gw.x, gw.y);
    grid = pow(grid, 14.0);
    col += vec3(0.0, 1.0, 0.8) * grid * 0.035;

    // --- 微扫描线 ----
    float scan = sin(uv.y * u_resolution.y * 0.5 + u_time * 2.0) * 0.5 + 0.5;
    col *= 1.0 - scan * 0.012;

    // --- 扫描线脉冲 ---
    float sweep = 1.0 - abs(fract(uv.y * 20.0 - u_time * 0.25) - 0.5) * 2.0;
    sweep = pow(sweep, 48.0);
    col += vec3(0.0, 1.0, 0.8) * sweep * 0.08;

    // --- 霓虹光晕游走 ---
    vec2 centers[3];
    centers[0] = vec2(0.5 + sin(u_time * 0.11) * 0.35, 0.5 + cos(u_time * 0.09) * 0.35);
    centers[1] = vec2(0.5 + sin(u_time * 0.08 + 2.1) * 0.30, 0.5 + cos(u_time * 0.13 + 2.1) * 0.30);
    centers[2] = vec2(0.5 + sin(u_time * 0.14 + 4.2) * 0.32, 0.5 + cos(u_time * 0.10 + 4.2) * 0.32);

    for (int i = 0; i < 3; i++) {
        vec2 delta = uv - centers[i];
        float dist = length(delta);
        float glow = exp(-dist * 5.5);
        float pulse = sin(u_time * 0.35 + float(i) * 2.1) * 0.5 + 0.5;
        // 青色光晕 (cyan)
        col += vec3(0.0, 1.0, 0.8) * glow * pulse * 0.05;
        // 品红光晕 (magenta) 偏移
        float p2 = sin(u_time * 0.3 + float(i) * 2.1 + 1.0) * 0.5 + 0.5;
        col += vec3(1.0, 0.0, 0.5) * glow * p2 * 0.03;
    }

    // --- 屏幕边缘暗角 ---
    vec2 vig = uv * (1.0 - uv);
    float vignette = 1.0 - pow(vig.x * vig.y * 8.0, 0.3);
    col *= vignette;

    gl_FragColor = vec4(col, 1.0);
}
