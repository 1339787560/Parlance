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

/// 价格表（元/百万 token，DeepSeek V4 平时价）。
pub struct Pricing {
    pub miss: f64,
    pub hit: f64,
    pub out: f64,
}

/// V4 价格：flash 与 pro。
pub const PRICING_FLASH: Pricing = Pricing { miss: 1.5, hit: 0.05, out: 4.5 };
pub const PRICING_PRO: Pricing = Pricing { miss: 4.5, hit: 0.15, out: 13.5 };

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

/// 北京时间高峰时段（含起始不含结束）。
pub const PEAK_WINDOWS: [(u32, u32); 2] = [(9, 12), (14, 18)];
/// 高峰翻倍。
pub const PEAK_MULTIPLIER: f64 = 2.0;

/// 定价版本：修改 PRICING 后递增，启动时据此重算所有历史 cost。
pub const PRICING_VERSION: &str = "2026-08-20-v2";

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

/// 北京时间峰谷判定。ts 为本地 naive ISO（中国时区 = UTC+8）。
pub fn is_peak_time(ts: &str) -> bool {
    let h = ts
        .split(['T', ' '])
        .nth(1)
        .and_then(|t| t.split(':').next())
        .and_then(|v| v.parse::<u32>().ok());
    let Some(h) = h else { return false };
    PEAK_WINDOWS.iter().any(|(lo, hi)| *lo <= h && h < *hi)
}

/// 费用（元）= 未命中×未命中价 + 命中×命中价 + 输出×输出价，高峰时段翻倍。
///
/// prompt 为总输入（含命中），miss = prompt - hit，避免缓存命中段重复计费。
pub fn calc_cost(model: &str, prompt: i64, hit: i64, out: i64, ts: Option<&str>) -> f64 {
    let p = get_pricing(model);
    let miss = (prompt - hit).max(0);
    let mut cost =
        (miss as f64 * p.miss + hit as f64 * p.hit + out as f64 * p.out) / 1_000_000.0;
    if let Some(ts) = ts {
        if is_peak_time(ts) {
            cost *= PEAK_MULTIPLIER;
        }
    }
    cost
}

/// 超算平台 credits 消耗（每 1M token，无峰谷）。
///
/// 输入未命中 × 输入价 + 命中 × 命中价 + 输出 × 输出价，除以 1M。
pub fn calc_credits(model: &str, prompt: i64, hit: i64, out: i64) -> f64 {
    let c = get_credits(model);
    let miss = (prompt - hit).max(0);
    (miss as f64 * c.input + hit as f64 * c.hit + out as f64 * c.output) / 1_000_000.0
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
pub fn extract_usage(usage: &Value, fmt: ApiFormat) -> Usage {
    let get = |k: &str| usage.get(k).and_then(Value::as_i64).unwrap_or(0);
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
        assert_eq!(p.miss, 1.5);
        assert_eq!(p.hit, 0.05);
        assert_eq!(p.out, 4.5);
    }

    #[test]
    fn calc_cost_flash_1m() {
        // 100万未命中输入 = 1.5 元（非高峰）
        let c = calc_cost("deepseek-v4-flash", 1_000_000, 0, 0, None);
        assert!((c - 1.5).abs() < 1e-9);
    }

    #[test]
    fn peak_time_doubles_cost() {
        let ts = "2026-08-20T10:00:00";
        assert!(is_peak_time(ts));
        let c = calc_cost("deepseek-v4-flash", 1_000_000, 0, 0, Some(ts));
        assert!((c - 3.0).abs() < 1e-9); // 高峰 ×2
    }

    #[test]
    fn non_peak_time() {
        let ts = "2026-08-20T08:00:00";
        assert!(!is_peak_time(ts));
        assert!(!is_peak_time("2026-08-20T12:00:00")); // 12 不含
    }

    #[test]
    fn miss_excludes_hit() {
        // prompt=100, hit=40 → miss=60；费用 = miss*1.5 + hit*0.05
        let c = calc_cost("deepseek-v4-flash", 100, 40, 0, None);
        let expect = (60.0 * 1.5 + 40.0 * 0.05) / 1_000_000.0;
        assert!((c - expect).abs() < 1e-9);
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
