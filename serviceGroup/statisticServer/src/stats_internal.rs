//! 任务切分累加器（stats.rs 内部辅助，独立成模块便于测试）。

use serde_json::{json, Value};

/// 一个任务的累加状态。
pub struct TaskAccum {
    start: String,
    end: String,
    requests: i64,
    session: String,
    prompt_tokens: i64,
    completion_tokens: i64,
    total_tokens: i64,
    cache_hit_tokens: i64,
    cache_miss_tokens: i64,
    total_latency_ms: i64,
    cost: f64,
    peak_requests: i64,
}

impl TaskAccum {
    pub fn new(start_ts: String, session: String) -> Self {
        Self {
            start: start_ts.clone(),
            end: start_ts,
            requests: 0,
            session,
            prompt_tokens: 0,
            completion_tokens: 0,
            total_tokens: 0,
            cache_hit_tokens: 0,
            cache_miss_tokens: 0,
            total_latency_ms: 0,
            cost: 0.0,
            peak_requests: 0,
        }
    }

    /// 累计一条请求；cost 为落库已含峰谷的 cost。
    #[allow(clippy::too_many_arguments)]
    pub fn add(
        &mut self,
        ts: &str,
        _session: &str,
        _model: &str,
        prompt: i64,
        completion: i64,
        total: i64,
        hit: i64,
        latency: i64,
        miss: i64,
        cost: f64,
        peak: bool,
    ) {
        self.end = ts.to_string();
        self.requests += 1;
        self.prompt_tokens += prompt;
        self.completion_tokens += completion;
        self.total_tokens += total;
        self.cache_hit_tokens += hit;
        self.cache_miss_tokens += miss;
        self.total_latency_ms += latency;
        self.cost += cost;
        if peak {
            self.peak_requests += 1;
        }
    }

    /// 计算 wall_time_ms 与 is_peak，输出任务 JSON。
    pub fn finish(self) -> Value {
        let wall_ms = crate::stats::wall_time_ms(&self.start, &self.end);
        json!({
            "task_id": 0,
            "start": self.start,
            "end": self.end,
            "requests": self.requests,
            "session": self.session,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "cache_hit_tokens": self.cache_hit_tokens,
            "cache_miss_tokens": self.cache_miss_tokens,
            "total_latency_ms": self.total_latency_ms,
            "wall_time_ms": wall_ms,
            "cost": (self.cost * 1_000_000.0).round() / 1_000_000.0,
            "peak_requests": self.peak_requests,
            "is_peak": self.peak_requests > 0,
        })
    }
}
