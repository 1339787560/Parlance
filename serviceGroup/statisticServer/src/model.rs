//! 代理核心纯逻辑：格式检测、路径规范化、模型映射、usage 归一化、费用计算。
//!
//! 对齐线上 `proxy_server.py`（feat/debug-relay-multi-client 分支）语义：
//! - DeepSeek V4 模型映射 + 峰谷计价
//! - 每次请求按时刻落库 cost（聚合直接 SUM(cost)）

use serde_json::Value;

/// 支持的 API 格式。
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ApiFormat {
    Anthropic,
    OpenAI,
}

/// 模型映射表（V4）：Claude 系列 → DeepSeek V4 系列。
///
/// 对齐线上 MODEL_MAP：
/// - claude-haiku/sonnet → deepseek-v4-flash
/// - claude-opus → deepseek-v4-pro
/// - deepseek-chat / deepseek-reasoner（旧别名）→ deepseek-v4-flash
/// - deepseek-* 最新名 → 透传
pub const MODEL_MAP: [(&str, &str); 4] = [
    ("claude-.*(haiku|sonnet).*", "deepseek-v4-flash"),
    ("claude-.*opus.*", "deepseek-v4-pro"),
    ("deepseek-chat", "deepseek-v4-flash"),
    ("deepseek-reasoner", "deepseek-v4-flash"),
];

/// 价格表（CNY/百万 token，DeepSeek 官方中文刊例，**数值为高峰价**，空闲时段 5 折）。
pub struct Pricing {
    pub miss: f64,
    pub hit: f64,
    pub out: f64,
}

/// V4.1 价格：flash 与 pro（api-docs.deepseek.com/zh-cn/quick_start/pricing，2026-09-10 核实）。
/// flash 空闲 ¥1/¥0.02/¥4、高峰 ¥2/¥0.04/¥8；pro 空闲 ¥4.5/¥0.15/¥13.5、高峰 ¥9/¥0.30/¥27。
pub const PRICING_FLASH: Pricing = Pricing { miss: 2.0, hit: 0.04, out: 8.0 };
pub const PRICING_PRO: Pricing = Pricing { miss: 9.0, hit: 0.3, out: 27.0 };

/// 超算平台 credits 定价（每 1M token，用户提供，折扣已含）。
///
/// 三个方向：输入 / 输出 / 命中缓存。无峰谷翻倍。
pub struct Credits {
    pub input: f64,
    pub output: f64,
    pub hit: f64,
}

/// 超算平台 credits 表：按模型名匹配。
pub const CREDITS_PRO: Credits = Credits { input: 10286.0, output: 20571.0, hit: 86.0 };
pub const CREDITS_FLASH: Credits = Credits { input: 1200.0, output: 2400.0, hit: 24.0 };
pub const CREDITS_FLASH_0731: Credits = Credits { input: 1543.0, output: 3086.0, hit: 31.0 };

/// 取模型 credits 档。
/// - DeepSeek-V4-Pro / 含 pro → Pro 档
/// - DeepSeek-V4-Flash-0731 → 0731 档（更早版本单独定价）
/// - 其余 flash → Flash 档
pub fn get_credits(model: &str) -> &'static Credits {
    let m = model.to_lowercase();
    if m.contains("deepseek-v4-pro") || m.ends_with("pro") {
        &CREDITS_PRO
    } else if m.contains("0731") {
        &CREDITS_FLASH_0731
    } else {
        &CREDITS_FLASH
    }
}

/// 北京时间高峰时段（含起始不含结束），**仅工作日**生效。
pub const PEAK_WINDOWS: [(u32, u32); 2] = [(9, 12), (14, 18)];
/// 错峰折扣：官方语义为基准=高峰价，错峰时段 ×0.5（原「基价×2」模型已废弃）。
pub const OFF_PEAK_DISCOUNT: f64 = 0.5;

/// GLM coding plan 积分折算系数（docs.bigmodel.cn/cn/coding-plan/team，每万 token）。
pub struct GlmCoef {
    pub input: f64,
    pub cached: f64,
    pub output: f64,
}

/// GLM-5.3 / GLM-5.3-Flash 系数（团队版刊例，2026-09 核实）。
pub const GLM_53: GlmCoef = GlmCoef { input: 6.9, cached: 1.7, output: 24.0 };
pub const GLM_53_FLASH: GlmCoef = GlmCoef { input: 2.3, cached: 0.56, output: 8.0 };

/// GLM 高峰窗口：仅工作日 14:00-18:00（与 DS 的 9-12/14-18 不同）。
pub const GLM_PEAK_WINDOWS: [(u32, u32); 1] = [(14, 18)];

/// GLM MCP 工具积分（联网搜索/网页读取/开源仓库，每次调用 1.2，官方团队版刊例；
/// 从 usage.server_tool_use 数值字段求和，随总积分一起吃非峰 ×0.5）。
pub const GLM_MCP_TOOL_CREDITS: f64 = 1.2;

/// 定价版本：修改 PRICING 后递增，启动时据此重算所有历史 cost。
/// v4-cny：USD 刊例 → CNY 刊例（币种变更必须全量重算，否则总额混币种）。
pub const PRICING_VERSION: &str = "2026-09-10-v4-cny";

/// Pro 有序下线切换点：北京时间 2026-09-14 12:00（本地朴素 ISO，同 ts 落库格式）。
/// 官方公告：此后至 V4.1 Pro 上线前，deepseek-v4-pro 请求全部路由到 V4.1 Flash 并按 Flash 计费。
pub const PRO_RETIRE_TS: &str = "2026-09-14T12:00:00";

/// 将 Claude 模型名映射为 DeepSeek V4 模型名。
pub fn map_model(m: &str) -> &str {
    for (pat, repl) in MODEL_MAP {
        if let Ok(re) = regex::Regex::new(pat) {
            if re.is_match(m) {
                return repl;
            }
        }
    }
    // deepseek-v4-* 最新名透传，其余回退 deepseek-v4-flash（对齐旧逻辑）
    m
}

/// 取模型价格档。deepseek-v4-pro → Pro；其余（flash/chat/reasoner 旧别名）→ Flash。
pub fn get_pricing(model: &str) -> &'static Pricing {
    let m = model.to_lowercase();
    if m.contains("deepseek-v4-pro") || m.ends_with("pro") {
        &PRICING_PRO
    } else {
        &PRICING_FLASH
    }
}

/// 取指定时刻生效的价格档：Pro 自 [`PRO_RETIRE_TS`] 起按 Flash 价计费
/// （官方：请求全部路由到 V4.1 Flash）。其余模型与 Pro 切换前不变。
/// ts 为本地朴素 ISO：空格归一化为 `T` 后字典序即时间序（落库格式恒带秒与毫秒）；
/// ts 缺失时不切换（落库路径恒带 ts，缺失只出现在无时刻的补算）。
pub fn get_pricing_at(model: &str, ts: Option<&str>) -> &'static Pricing {
    let p = get_pricing(model);
    if std::ptr::eq(p, &PRICING_PRO) {
        if let Some(t) = ts {
            if t.replace(' ', "T").as_str() >= PRO_RETIRE_TS {
                return &PRICING_FLASH;
            }
        }
    }
    p
}

/// 是否 GLM 系模型（走 GLM 计费分支：cost=0、credits=coding plan 折算）。
pub fn is_glm_model(model: &str) -> bool {
    model.to_lowercase().contains("glm")
}

/// 按模型分派峰谷判定（GLM → 工作日 14-18；其余 DS → 工作日 9-12/14-18）。
/// 供看板峰谷标志与任务切分累计使用。
pub fn is_peak_for_model(model: &str, ts: &str) -> bool {
    if is_glm_model(model) {
        is_glm_peak_time(ts)
    } else {
        is_peak_time(ts)
    }
}

/// 北京时间峰谷判定。ts 为本地 naive ISO（中国时区 = UTC+8）。
/// **仅工作日**命中窗口才算高峰（官方：peak hours are Mon-Fri；旧实现不判星期，周末被误翻倍）。
pub fn is_peak_time(ts: &str) -> bool {
    peak_in_windows(ts, &PEAK_WINDOWS)
}

/// GLM 峰谷判定：工作日 14:00-18:00（coding plan 非高峰 50% 抵扣）。
pub fn is_glm_peak_time(ts: &str) -> bool {
    peak_in_windows(ts, &GLM_PEAK_WINDOWS)
}

/// 通用：ts 解析出 (工作日?, 小时)，命中窗口且为工作日才算高峰。
/// 解析失败回退 false（按错峰处理，不放大费用）。
fn peak_in_windows(ts: &str, windows: &[(u32, u32)]) -> bool {
    use chrono::Datelike;
    let Some((date_part, time_part)) = ts.split_once(['T', ' ']) else {
        return false;
    };
    let Some(h) = time_part.split(':').next().and_then(|v| v.parse::<u32>().ok()) else {
        return false;
    };
    let weekday = chrono::NaiveDate::parse_from_str(date_part, "%Y-%m-%d")
        .ok()
        .map(|d| d.weekday().num_days_from_monday() < 5) // 0-4 = 周一至周五
        .unwrap_or(false);
    weekday && windows.iter().any(|(lo, hi)| *lo <= h && h < *hi)
}

/// 费用（CNY）= 未命中×未命中价 + 命中×命中价 + 输出×输出价（基准=高峰价），
/// 空闲时段 ×OFF_PEAK_DISCOUNT。GLM 模型不计按量 cost（D2 决策）。
/// Pro 自 [`PRO_RETIRE_TS`] 起按 Flash 档（见 [`get_pricing_at`]）。
///
/// prompt 为总输入（含命中），miss = prompt - hit，避免缓存命中段重复计费。
pub fn calc_cost(model: &str, prompt: i64, hit: i64, out: i64, ts: Option<&str>) -> f64 {
    if is_glm_model(model) {
        return 0.0;
    }
    let p = get_pricing_at(model, ts);
    let miss = (prompt - hit).max(0);
    let mut cost =
        (miss as f64 * p.miss + hit as f64 * p.hit + out as f64 * p.out) / 1_000_000.0;
    if let Some(ts) = ts {
        if !is_peak_time(ts) {
            cost *= OFF_PEAK_DISCOUNT;
        }
    }
    cost
}

/// 超算平台 credits 消耗（每 1M token，无峰谷）。GLM 模型返回 0（走 GLM 积分）。
///
/// 输入未命中 × 输入价 + 命中 × 命中价 + 输出 × 输出价，除以 1M。
pub fn calc_credits(model: &str, prompt: i64, hit: i64, out: i64) -> f64 {
    if is_glm_model(model) {
        return 0.0;
    }
    let c = get_credits(model);
    let miss = (prompt - hit).max(0);
    (miss as f64 * c.input + hit as f64 * c.hit + out as f64 * c.output) / 1_000_000.0
}

/// 取 GLM 积分系数档：含 flash → Flash 档；其余 glm → GLM-5.3 档。
pub fn get_glm_coef(model: &str) -> &'static GlmCoef {
    if model.to_lowercase().contains("flash") {
        &GLM_53_FLASH
    } else {
        &GLM_53
    }
}

/// GLM coding plan 积分折算：
/// `(输入未命中×Input + 缓存命中×Cached + 输出×Output) ÷ 10000 + MCP工具次数×1.2`，
/// 非高峰（工作日 14-18 之外）整体 ×0.5。
/// 「输入Token」按未命中解释（命中段走 Cached 系数），与官方缓存省钱叙事一致。
pub fn calc_glm_credits(
    model: &str,
    prompt: i64,
    hit: i64,
    out: i64,
    tools: i64,
    ts: Option<&str>,
) -> f64 {
    let c = get_glm_coef(model);
    let miss = (prompt - hit).max(0);
    let mut v = (miss as f64 * c.input + hit as f64 * c.cached + out as f64 * c.output) / 10_000.0
        + tools as f64 * GLM_MCP_TOOL_CREDITS;
    if let Some(ts) = ts {
        if !is_glm_peak_time(ts) {
            v *= 0.5;
        }
    }
    v
}

/// 落库计费分派：glm → (0, coding plan 积分)；其余 → (超算 cost, 超算 credits)。
pub fn calc_charges(
    model: &str,
    prompt: i64,
    hit: i64,
    out: i64,
    tools: i64,
    ts: Option<&str>,
) -> (f64, f64) {
    if is_glm_model(model) {
        (0.0, calc_glm_credits(model, prompt, hit, out, tools, ts))
    } else {
        (
            calc_cost(model, prompt, hit, out, ts),
            calc_credits(model, prompt, hit, out),
        )
    }
}

/// 根据请求路径推断格式与目标 base 前缀。
pub fn detect_format(path: &str) -> (ApiFormat, &'static str) {
    let p = path.trim_start_matches('/').to_lowercase();
    if p.starts_with("chat/completions")
        || p.starts_with("v1/chat/completions")
        || p.starts_with("v1/models")
        || p.starts_with("models")
        || p.starts_with("v1/embeddings")
        || p.starts_with("embeddings")
    {
        (ApiFormat::OpenAI, "openai")
    } else {
        // 含 messages → anthropic；默认 anthropic（向后兼容）
        (ApiFormat::Anthropic, "anthropic")
    }
}

/// 把请求路径规范化为目标 API 期望的路径。
///
/// OpenAI target 已含 /v1，路径不能再带 v1/ 前缀；
/// Anthropic target 需带 v1/ 前缀。
pub fn normalize_path(path: &str, fmt: ApiFormat) -> String {
    let p = path.trim_start_matches('/');
    match fmt {
        ApiFormat::OpenAI => {
            if let Some(rest) = p.strip_prefix("v1/") {
                rest.to_string()
            } else {
                p.to_string()
            }
        }
        ApiFormat::Anthropic => {
            if p.starts_with("v1/") {
                p.to_string()
            } else {
                format!("v1/{p}")
            }
        }
    }
}

/// usage 归一化，统一为内部 schema（与 OpenAI 语义一致）。
///
/// - prompt_tokens = cache_hit_tokens + cache_miss_tokens
/// - Anthropic: input_tokens 不含缓存；总 prompt = input + cache_read + cache_creation
/// - tool_calls = GLM usage.server_tool_use 数值字段求和（MCP 工具调用次数）
pub fn extract_usage(usage: &Value, fmt: ApiFormat) -> Usage {
    let get = |k: &str| usage.get(k).and_then(Value::as_i64).unwrap_or(0);
    let tool_calls = usage
        .get("server_tool_use")
        .and_then(Value::as_object)
        .map(|o| o.values().filter_map(Value::as_i64).sum())
        .unwrap_or(0);
    match fmt {
        ApiFormat::OpenAI => {
            let prompt = get("prompt_tokens");
            let completion = get("completion_tokens");
            Usage {
                prompt_tokens: prompt,
                completion_tokens: completion,
                total_tokens: prompt + completion,
                cache_hit_tokens: get("prompt_cache_hit_tokens"),
                cache_miss_tokens: get("prompt_cache_miss_tokens"),
                tool_calls,
            }
        }
        ApiFormat::Anthropic => {
            let new_input = get("input_tokens");
            let cache_hit = get("cache_read_input_tokens");
            let cache_creation = get("cache_creation_input_tokens");
            let prompt = new_input + cache_hit + cache_creation;
            let completion = get("output_tokens");
            Usage {
                prompt_tokens: prompt,
                completion_tokens: completion,
                total_tokens: prompt + completion,
                cache_hit_tokens: cache_hit,
                cache_miss_tokens: new_input + cache_creation,
                tool_calls,
            }
        }
    }
}

/// 归一化后的 usage 结构。
#[derive(Debug, Clone, Copy, Default)]
pub struct Usage {
    pub prompt_tokens: i64,
    pub completion_tokens: i64,
    pub total_tokens: i64,
    pub cache_hit_tokens: i64,
    pub cache_miss_tokens: i64,
    /// GLM MCP 工具调用次数（联网搜索/网页读取等，server_tool_use 求和）。
    pub tool_calls: i64,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn detect_anthropic_messages() {
        assert_eq!(detect_format("/v1/messages").0, ApiFormat::Anthropic);
    }

    #[test]
    fn detect_openai_chat() {
        assert_eq!(detect_format("/chat/completions").0, ApiFormat::OpenAI);
        assert_eq!(detect_format("/v1/chat/completions").0, ApiFormat::OpenAI);
    }

    #[test]
    fn detect_openai_models() {
        assert_eq!(detect_format("/v1/models").0, ApiFormat::OpenAI);
    }

    #[test]
    fn normalize_openai_strips_v1() {
        assert_eq!(normalize_path("/v1/chat/completions", ApiFormat::OpenAI), "chat/completions");
        assert_eq!(normalize_path("/chat/completions", ApiFormat::OpenAI), "chat/completions");
    }

    #[test]
    fn normalize_anthropic_adds_v1() {
        assert_eq!(normalize_path("/v1/messages", ApiFormat::Anthropic), "v1/messages");
        assert_eq!(normalize_path("/messages", ApiFormat::Anthropic), "v1/messages");
    }

    #[test]
    fn map_claude_sonnet_to_v4_flash() {
        assert_eq!(map_model("claude-3-5-sonnet-20241022"), "deepseek-v4-flash");
        assert_eq!(map_model("claude-3-5-haiku-20241022"), "deepseek-v4-flash");
    }

    #[test]
    fn map_claude_opus_to_v4_pro() {
        assert_eq!(map_model("claude-3-opus-20240229"), "deepseek-v4-pro");
        assert_eq!(map_model("claude-opus-4-8"), "deepseek-v4-pro");
    }

    #[test]
    fn map_old_aliases_to_flash() {
        assert_eq!(map_model("deepseek-chat"), "deepseek-v4-flash");
        assert_eq!(map_model("deepseek-reasoner"), "deepseek-v4-flash");
    }

    #[test]
    fn map_v4_passthrough() {
        assert_eq!(map_model("deepseek-v4-flash"), "deepseek-v4-flash");
        assert_eq!(map_model("deepseek-v4-pro"), "deepseek-v4-pro");
    }

    #[test]
    fn pricing_flash_v4() {
        let p = get_pricing("deepseek-v4-flash");
        assert_eq!(p.miss, 2.0);
        assert_eq!(p.hit, 0.04);
        assert_eq!(p.out, 8.0);
    }

    #[test]
    fn calc_cost_flash_1m_peak() {
        // 100万未命中输入 = 2.0 CNY（基准=高峰价；无 ts 按峰算保守值）
        let c = calc_cost("deepseek-v4-flash", 1_000_000, 0, 0, None);
        assert!((c - 2.0).abs() < 1e-9);
    }

    #[test]
    fn cost_v4_flash_off_peak_half() {
        // 工作日 08:00 非高峰：峰价 ×0.5
        let ts = "2026-08-20T08:00:00";
        let c = calc_cost("deepseek-v4-flash", 1_000_000, 0, 0, Some(ts));
        assert!((c - 1.0).abs() < 1e-9);
    }

    #[test]
    fn cost_v4_pro_pricing() {
        // 9/14 12:00 前 pro 仍按 Pro 档：100万未命中输入 = 9.0 CNY（高峰）
        let ts_peak = "2026-08-20T10:00:00";
        let c = calc_cost("deepseek-v4-pro", 1_000_000, 0, 0, Some(ts_peak));
        assert!((c - 9.0).abs() < 1e-9);
    }

    #[test]
    fn pro_routed_to_flash_after_retire() {
        // 2026-09-14 = 周一（高峰窗口 9-12/14-18 生效）
        // 切换点（含）起按 Flash 档计费；切换前仍按 Pro 档
        let pro_off_before = calc_cost("deepseek-v4-pro", 1_000_000, 0, 0, Some("2026-09-14T08:00:00"));
        assert!((pro_off_before - 4.5).abs() < 1e-9, "切换前非峰 = Pro ¥4.5");
        let pro_peak_before = calc_cost("deepseek-v4-pro", 1_000_000, 0, 0, Some("2026-09-14T11:59:59"));
        assert!((pro_peak_before - 9.0).abs() < 1e-9, "切换前高峰 = Pro ¥9");

        // 12:00 整为切换点，且该时刻属非峰（12:00 不含在 9-12 窗口）→ Flash 非峰 ¥1
        let at_cutoff = calc_cost("deepseek-v4-pro", 1_000_000, 0, 0, Some("2026-09-14T12:00:00"));
        assert!((at_cutoff - 1.0).abs() < 1e-9, "切换点（含）按 Flash 非峰 ¥1");

        let pro_peak_after = calc_cost("deepseek-v4-pro", 1_000_000, 0, 0, Some("2026-09-14T14:00:00"));
        assert!((pro_peak_after - 2.0).abs() < 1e-9, "切换后高峰 = Flash ¥2");
        let pro_off_after = calc_cost("deepseek-v4-pro", 1_000_000, 0, 0, Some("2026-09-15T08:00:00"));
        assert!((pro_off_after - 1.0).abs() < 1e-9, "切换后非峰 = Flash ¥1");

        // flash 自身与切换无关
        let flash_after = calc_cost("deepseek-v4-flash", 1_000_000, 0, 0, Some("2026-09-15T14:00:00"));
        assert!((flash_after - 2.0).abs() < 1e-9);
    }

    #[test]
    fn get_pricing_at_switches_pro_tier() {
        assert_eq!(get_pricing_at("deepseek-v4-pro", Some("2026-09-13T10:00:00")).miss, 9.0, "切换前 Pro 档");
        assert_eq!(get_pricing_at("deepseek-v4-pro", Some("2026-09-14T12:00:00")).miss, 2.0, "切换点（含）Flash 档");
        assert_eq!(get_pricing_at("deepseek-v4-pro", Some("2026-09-14T14:00:00")).miss, 2.0, "切换后 Flash 档");
        assert_eq!(get_pricing_at("deepseek-v4-pro", None).miss, 9.0, "无时刻不切换");
        // 空格分隔的落库格式与 T 分隔等价
        assert_eq!(get_pricing_at("deepseek-v4-pro", Some("2026-09-14 14:00:00")).miss, 2.0);
        // 非 pro 恒 Flash
        assert_eq!(get_pricing_at("deepseek-v4-flash", Some("2026-09-14T14:00:00")).miss, 2.0);
    }

    #[test]
    fn peak_time_respects_weekday() {
        // 2026-08-20 = 周四，2026-08-22 = 周六，2026-08-23 = 周日
        assert!(is_peak_time("2026-08-20T09:00:00"), "工作日 09:00 峰");
        assert!(!is_peak_time("2026-08-20T08:59:00"), "工作日 08:59 非峰");
        assert!(is_peak_time("2026-08-20T11:59:00"), "工作日 11:59 峰");
        assert!(!is_peak_time("2026-08-20T12:00:00"), "12 不含");
        assert!(!is_peak_time("2026-08-20T13:59:00"), "午间非峰");
        assert!(is_peak_time("2026-08-20T14:00:00"), "工作日 14:00 峰");
        assert!(is_peak_time("2026-08-20T17:59:00"), "工作日 17:59 峰");
        assert!(!is_peak_time("2026-08-20T18:00:00"), "18 不含");
        // 周末全天非峰（旧实现 bug：只看小时不判星期）
        assert!(!is_peak_time("2026-08-22T10:00:00"), "周六 10:00 非峰");
        assert!(!is_peak_time("2026-08-23T15:00:00"), "周日 15:00 非峰");
    }

    #[test]
    fn non_peak_time() {
        assert!(!is_peak_time("2026-08-20T08:00:00"));
        assert!(!is_peak_time("2026-08-20T12:00:00")); // 12 不含
    }

    #[test]
    fn miss_excludes_hit() {
        // prompt=100, hit=40 → miss=60；费用 = miss*2.0 + hit*0.04（峰）
        let ts = "2026-08-20T10:00:00";
        let c = calc_cost("deepseek-v4-flash", 100, 40, 0, Some(ts));
        let expect = (60.0 * 2.0 + 40.0 * 0.04) / 1_000_000.0;
        assert!((c - expect).abs() < 1e-9);
    }

    #[test]
    fn glm_peak_window_differs_from_ds() {
        // 2026-08-20 = 周四
        assert!(is_peak_time("2026-08-20T10:00:00"), "DS 工作日 10:00 峰");
        assert!(!is_glm_peak_time("2026-08-20T10:00:00"), "GLM 工作日 10:00 非峰");
        assert!(is_glm_peak_time("2026-08-20T15:00:00"), "GLM 工作日 15:00 峰");
        assert!(is_peak_time("2026-08-20T15:00:00"), "DS 工作日 15:00 峰");
        assert!(!is_glm_peak_time("2026-08-22T15:00:00"), "GLM 周六非峰");
    }

    #[test]
    fn glm_credits_formula() {
        // glm-5.3 峰：miss=9000 hit=1000 out=2000 → (9000*6.9 + 1000*1.7 + 2000*24)/10000
        let ts_peak = "2026-08-20T15:00:00";
        let v = calc_glm_credits("glm-5.3", 10_000, 1_000, 2_000, 0, Some(ts_peak));
        let expect = (9000.0 * 6.9 + 1000.0 * 1.7 + 2000.0 * 24.0) / 10_000.0;
        assert!((v - expect).abs() < 1e-9);

        // 非高峰 ×0.5
        let v_off = calc_glm_credits("glm-5.3", 10_000, 1_000, 2_000, 0, Some("2026-08-20T10:00:00"));
        assert!((v_off - expect * 0.5).abs() < 1e-9);

        // flash 系数档
        let vf = calc_glm_credits("glm-5.3-flash", 10_000, 0, 1_000, 0, Some(ts_peak));
        assert!((vf - (10_000.0 * 2.3 + 1_000.0 * 8.0) / 10_000.0).abs() < 1e-9);
    }

    #[test]
    fn glm_mcp_tool_credits() {
        // 纯工具调用：3 次 × 1.2；非峰整体 ×0.5
        let v = calc_glm_credits("glm-5.3", 0, 0, 0, 3, Some("2026-08-20T15:00:00"));
        assert!((v - 3.6).abs() < 1e-9);
        let v_off = calc_glm_credits("glm-5.3", 0, 0, 0, 3, Some("2026-08-20T10:00:00"));
        assert!((v_off - 1.8).abs() < 1e-9);
        // token + 工具混合：先加总再乘峰谷系数
        let vm = calc_glm_credits("glm-5.3", 10_000, 0, 0, 2, Some("2026-08-20T15:00:00"));
        assert!((vm - (10_000.0 * 6.9 / 10_000.0 + 2.4)).abs() < 1e-9);
    }

    #[test]
    fn is_peak_for_model_dispatches_by_provider() {
        // 周三 10:00：DS 峰、GLM 非峰（窗口不同）
        let ts = "2026-08-19T10:00:00";
        assert!(is_peak_for_model("deepseek-v4-flash", ts));
        assert!(!is_peak_for_model("glm-5.3", ts));
        // 周三 15:00：两者皆峰；周六：皆非峰
        let ts2 = "2026-08-19T15:00:00";
        assert!(is_peak_for_model("deepseek-v4-flash", ts2));
        assert!(is_peak_for_model("glm-5.3", ts2));
        assert!(!is_peak_for_model("glm-5.3", "2026-08-22T15:00:00"));
        assert!(!is_peak_for_model("deepseek-v4-flash", "2026-08-22T10:00:00"));
    }

    #[test]
    fn usage_anthropic_server_tool_use() {
        let v = serde_json::json!({
            "input_tokens": 10, "output_tokens": 20,
            "cache_read_input_tokens": 5,
            "server_tool_use": {"web_search_requests": 3, "web_reader_requests": 1},
        });
        let u = extract_usage(&v, ApiFormat::Anthropic);
        assert_eq!(u.tool_calls, 4, "server_tool_use 数值求和");
        // 无该字段 → 0
        let v2 = serde_json::json!({"input_tokens": 10, "output_tokens": 20});
        assert_eq!(extract_usage(&v2, ApiFormat::Anthropic).tool_calls, 0);
    }

    #[test]
    fn calc_charges_dispatches_glm_vs_ds() {
        let ts = "2026-08-20T15:00:00";
        let (c, cr) = calc_charges("glm-5.3", 10_000, 1_000, 2_000, 0, Some(ts));
        assert_eq!(c, 0.0, "GLM 不计按量 cost（D2）");
        assert!(cr > 0.0, "GLM 记 coding plan 积分");

        let (c2, cr2) = calc_charges("deepseek-v4-flash", 1_000_000, 0, 0, 0, Some(ts));
        assert!((c2 - 2.0).abs() < 1e-9);
        assert!((cr2 - 1200.0).abs() < 1e-6);
    }

    #[test]
    fn usage_openai() {
        let v = serde_json::json!({
            "prompt_tokens": 100,
            "completion_tokens": 50,
            "total_tokens": 150,
            "prompt_cache_hit_tokens": 40,
            "prompt_cache_miss_tokens": 60,
        });
        let u = extract_usage(&v, ApiFormat::OpenAI);
        assert_eq!(u.prompt_tokens, 100);
        assert_eq!(u.cache_hit_tokens, 40);
        assert_eq!(u.cache_miss_tokens, 60);
    }

    #[test]
    fn usage_anthropic() {
        let v = serde_json::json!({
            "input_tokens": 10,            "output_tokens": 20,
            "cache_read_input_tokens": 30,
            "cache_creation_input_tokens": 5,
        });
        let u = extract_usage(&v, ApiFormat::Anthropic);
        assert_eq!(u.prompt_tokens, 45);
        assert_eq!(u.completion_tokens, 20);
        assert_eq!(u.cache_hit_tokens, 30);
        assert_eq!(u.cache_miss_tokens, 15);
    }

    #[test]
    fn credits_flash_1m() {
        // 100万输入未命中，无命中无输出 → 1200 credits
        let c = calc_credits("deepseek-v4-flash", 1_000_000, 0, 0);
        assert!((c - 1200.0).abs() < 1e-6);
    }

    #[test]
    fn credits_pro() {
        // 100万输入未命中 → 10286 credits
        let c = calc_credits("deepseek-v4-pro", 1_000_000, 0, 0);
        assert!((c - 10286.0).abs() < 1e-6);
    }

    #[test]
    fn credits_flash_0731() {
        let c = calc_credits("deepseek-v4-flash-0731", 1_000_000, 0, 0);
        assert!((c - 1543.0).abs() < 1e-6);
    }

    #[test]
    fn credits_mixed_usage() {
        // prompt=100, hit=40, out=5 → miss=60
        // flash: (60*1200 + 40*24 + 5*2400)/1e6 = (72000+960+12000)/1e6 = 0.08496
        let c = calc_credits("deepseek-v4-flash", 100, 40, 5);
        let expect = (60.0 * 1200.0 + 40.0 * 24.0 + 5.0 * 2400.0) / 1_000_000.0;
        assert!((c - expect).abs() < 1e-9);
    }

    #[test]
    fn credits_no_peak() {
        // credits 不受峰谷影响：高峰与平时一致
        let c1 = calc_credits("deepseek-v4-flash", 100, 0, 0);
        assert!((c1 - 100.0 * 1200.0 / 1_000_000.0).abs() < 1e-9);
    }
}
