//! 统计 API：聚合、请求明细、按日汇总、任务切分（Median+2×MAD）、会话建议。
//!
//! 对齐线上 `proxy_server.py::handle_api` 语义（V4 峰谷计价，聚合用落库 cost 求和）。

use axum::extract::{Query, State};
use axum::Json;
use serde::Deserialize;
use serde_json::{json, Value};

use crate::state::AppState;

/// 请求明细 /api/stats/detail — 最近 100 条。
pub async fn detail(State(state): State<std::sync::Arc<AppState>>) -> Json<Value> {
    let conn = state.db.lock().unwrap();
    let mut stmt = conn
        .prepare(
            "SELECT ts,session_id,model,prompt_tokens,completion_tokens,total_tokens,
             cache_hit_tokens,cache_miss_tokens,latency_ms
             FROM requests ORDER BY ts DESC LIMIT 100",
        )
        .unwrap();
    let rows = stmt
        .query_map([], |r| {
            Ok(json!({
                "ts": r.get::<_, String>(0)?,
                "session": r.get::<_, String>(1)?,
                "model": r.get::<_, String>(2)?,
                "prompt": r.get::<_, i64>(3)?,
                "completion": r.get::<_, i64>(4)?,
                "total": r.get::<_, i64>(5)?,
                "cache_hit": r.get::<_, i64>(6)?,
                "cache_miss": r.get::<_, i64>(7)?,
                "latency_ms": r.get::<_, i64>(8)?,
            }))
        })
        .unwrap()
        .collect::<Result<Vec<_>, _>>()
        .unwrap();
    Json(Value::Array(rows))
}

/// 按日汇总 /api/stats/daily — 每日请求数、token、费用（SUM 落库 cost）。
pub async fn daily(State(state): State<std::sync::Arc<AppState>>) -> Json<Value> {
    let conn = state.db.lock().unwrap();
    let mut stmt = conn
        .prepare(
            "SELECT date(ts) as day, model,
             COUNT(*), COALESCE(SUM(prompt_tokens),0), COALESCE(SUM(completion_tokens),0),
             COALESCE(SUM(total_tokens),0), COALESCE(SUM(cache_hit_tokens),0),
             COALESCE(SUM(latency_ms),0), COALESCE(SUM(cache_miss_tokens),0),
             COALESCE(SUM(cost),0)
             FROM requests GROUP BY day, model ORDER BY day DESC",
        )
        .unwrap();
    let rows = stmt
        .query_map([], |r| {
            Ok((
                r.get::<_, String>(0)?,
                r.get::<_, String>(1)?,
                r.get::<_, i64>(2)?,
                r.get::<_, i64>(3)?,
                r.get::<_, i64>(4)?,
                r.get::<_, i64>(5)?,
                r.get::<_, i64>(6)?,
                r.get::<_, i64>(7)?,
                r.get::<_, i64>(8)?,
                r.get::<_, f64>(9)?,
            ))
        })
        .unwrap()
        .collect::<Result<Vec<_>, _>>()
        .unwrap();

    let mut days: Vec<DayAgg> = Vec::new();
    for (day, model, count, prompt, completion, total, hit, latency, miss, cost) in rows {
        if let Some(d) = days.iter_mut().find(|d| d.date == day) {
            d.requests += count;
            d.prompt_tokens += prompt;
            d.completion_tokens += completion;
            d.total_tokens += total;
            d.cache_hit_tokens += hit;
            d.cache_miss_tokens += miss;
            d.total_latency_ms += latency;
            d.cost += cost;
            *d.model_costs.entry(model.clone()).or_insert(0.0) += cost;
        } else {
            let mut model_costs = std::collections::HashMap::new();
            model_costs.insert(model, cost);
            days.push(DayAgg {
                date: day,
                requests: count,
                prompt_tokens: prompt,
                completion_tokens: completion,
                total_tokens: total,
                cache_hit_tokens: hit,
                cache_miss_tokens: miss,
                total_latency_ms: latency,
                cost,
                model_costs,
            });
        }
    }

    let out: Vec<Value> = days
        .into_iter()
        .map(|d| {
            let avg = if d.requests > 0 { d.total_latency_ms / d.requests } else { 0 };
            json!({
                "date": d.date,
                "requests": d.requests,
                "prompt_tokens": d.prompt_tokens,
                "completion_tokens": d.completion_tokens,
                "total_tokens": d.total_tokens,
                "cache_hit_tokens": d.cache_hit_tokens,
                "cache_miss_tokens": d.cache_miss_tokens,
                "avg_latency_ms": avg,
                "cost": round6(d.cost),
                "model_costs": d.model_costs.iter().map(|(k, v)| (k.clone(), round6(*v))).collect::<std::collections::HashMap<_, _>>(),
            })
        })
        .collect();
    Json(Value::Array(out))
}

#[derive(Default)]
struct DayAgg {
    date: String,
    requests: i64,
    prompt_tokens: i64,
    completion_tokens: i64,
    total_tokens: i64,
    cache_hit_tokens: i64,
    cache_miss_tokens: i64,
    total_latency_ms: i64,
    cost: f64,
    model_costs: std::collections::HashMap<String, f64>,
}

/// 任务列表查询参数。
#[derive(Deserialize)]
pub struct TasksQuery {
    pub limit: Option<i64>,
    pub session: Option<String>,
    pub gap: Option<String>,
    pub mode: Option<String>,
}

/// 任务切分 /api/stats/tasks — 同会话 + 时间邻近归为一任务。
pub async fn tasks(
    State(state): State<std::sync::Arc<AppState>>,
    Query(q): Query<TasksQuery>,
) -> Json<Value> {
    let conn = state.db.lock().unwrap();
    let limit = q.limit.unwrap_or(50).min(500);
    let session = q.session.unwrap_or_default();
    let mode = q.mode.unwrap_or_default();

    let (sql, params) = if session.is_empty() {
        (
            "SELECT ts,session_id,model,prompt_tokens,completion_tokens,total_tokens,
             cache_hit_tokens,latency_ms,cache_miss_tokens,cost
             FROM requests ORDER BY ts ASC",
            vec![],
        )
    } else {
        (
            "SELECT ts,session_id,model,prompt_tokens,completion_tokens,total_tokens,
             cache_hit_tokens,latency_ms,cache_miss_tokens,cost
             FROM requests WHERE session_id=?1 ORDER BY ts ASC",
            vec![session],
        )
    };

    let mut stmt = conn.prepare(sql).unwrap();
    let mut rows: Vec<(String, String, String, i64, i64, i64, i64, i64, i64, f64)> = Vec::new();
    {
        let mut it = stmt.query(rusqlite::params_from_iter(params)).unwrap();
        while let Some(r) = it.next().unwrap() {
            rows.push((
                r.get(0).unwrap(),
                r.get(1).unwrap(),
                r.get(2).unwrap(),
                r.get(3).unwrap(),
                r.get(4).unwrap(),
                r.get(5).unwrap(),
                r.get(6).unwrap(),
                r.get(7).unwrap(),
                r.get(8).unwrap(),
                r.get(9).unwrap(),
            ));
        }
    }

    let gap = if mode != "fixed" && rows.len() >= 3 {
        adaptive_gap(&rows)
    } else {
        q.gap.and_then(|s| s.parse::<i64>().ok()).unwrap_or(60).clamp(10, 600)
    };

    let mut tasks_out: Vec<Value> = Vec::new();
    let mut cur: Option<super::stats_internal::TaskAccum> = None;
    let mut prev_ts: Option<i64> = None;
    let mut prev_session: Option<String> = None;

    for (ts, r_session, model, prompt, completion, total, hit, latency, miss, cost) in &rows {
        let ts_ms = parse_ts_ms(ts);
        let r_session = if r_session.is_empty() { String::new() } else { r_session.clone() };
        let is_new = match &cur {
            None => true,
            Some(_) => {
                r_session != prev_session.as_deref().unwrap_or("")
                    || (prev_ts.is_some()
                        && r_session == prev_session.as_deref().unwrap_or("")
                        && (ts_ms - prev_ts.unwrap()) > gap * 1000)
            }
        };
        if is_new {
            if let Some(c) = cur.take() {
                tasks_out.push(c.finish());
            }
            cur = Some(super::stats_internal::TaskAccum::new(ts.clone(), r_session.clone()));
        }
        if let Some(c) = cur.as_mut() {
            let peak = crate::model::is_peak_time(ts);
            c.add(
                ts, &r_session, model, *prompt, *completion, *total, *hit, *latency, *miss, *cost, peak,
            );
        }
        prev_ts = Some(ts_ms);
        prev_session = Some(r_session);
    }
    if let Some(c) = cur.take() {
        tasks_out.push(c.finish());
    }

    tasks_out.reverse();
    tasks_out.truncate(limit as usize);
    Json(Value::Array(tasks_out))
}

/// 聚合 /api/stats — 总用量 + 模型费用（SUM 落库 cost）+ 会话列表。
pub async fn aggregate(
    State(state): State<std::sync::Arc<AppState>>,
    Query(q): Query<AggQuery>,
) -> Json<Value> {
    let conn = state.db.lock().unwrap();
    let session = q.session.unwrap_or_default();

    let (where_clause, params) = if session.is_empty() {
        ("", vec![])
    } else {
        (" WHERE session_id=?1", vec![session.clone()])
    };

    let mut stmt = conn
        .prepare(&format!(
            "SELECT COUNT(*), COALESCE(SUM(prompt_tokens),0), COALESCE(SUM(completion_tokens),0),
             COALESCE(SUM(total_tokens),0), COALESCE(SUM(cache_hit_tokens),0),
             COALESCE(AVG(latency_ms),0), COALESCE(SUM(latency_ms),0),
             COALESCE(SUM(cache_miss_tokens),0), COALESCE(SUM(cost),0) FROM requests{where_clause}"
        ))
        .unwrap();
    let row = stmt
        .query_row(rusqlite::params_from_iter(params.iter()), |r| {
            Ok((
                r.get::<_, i64>(0)?,
                r.get::<_, i64>(1)?,
                r.get::<_, i64>(2)?,
                r.get::<_, i64>(3)?,
                r.get::<_, i64>(4)?,
                r.get::<_, f64>(5)?,
                r.get::<_, i64>(6)?,
                r.get::<_, i64>(7)?,
                r.get::<_, f64>(8)?,
            ))
        })
        .unwrap();

    if row.0 == 0 {
        return Json(json!({"total_requests": 0, "sessions": []}));
    }

    // 模型费用（落库 cost 已含峰谷，直接 SUM）
    let mut stmt = conn
        .prepare(&format!(
            "SELECT model, SUM(cost) FROM requests{where_clause} GROUP BY model"
        ))
        .unwrap();
    let model_costs: std::collections::HashMap<String, f64> = stmt
        .query_map(rusqlite::params_from_iter(params.iter()), |r| {
            Ok((r.get::<_, String>(0)?, r.get::<_, f64>(1)?))
        })
        .unwrap()
        .collect::<Result<_, _>>()
        .unwrap();
    let model_costs_rounded = model_costs
        .iter()
        .map(|(k, v)| (k.clone(), round6(*v)))
        .collect::<std::collections::HashMap<_, _>>();

    // 会话列表（未指定 session 时）
    let mut sessions: Vec<Value> = Vec::new();
    if session.is_empty() {
        let mut stmt = conn
            .prepare(
                "SELECT session_id, MIN(ts), MAX(ts), COUNT(*), COALESCE(SUM(total_tokens),0)
                 FROM requests WHERE session_id != '' GROUP BY session_id ORDER BY MAX(ts) DESC LIMIT 50",
            )
            .unwrap();
        let sess_rows = stmt
            .query_map([], |r| {
                Ok((
                    r.get::<_, String>(0)?,
                    r.get::<_, String>(1)?,
                    r.get::<_, String>(2)?,
                    r.get::<_, i64>(3)?,
                    r.get::<_, i64>(4)?,
                ))
            })
            .unwrap()
            .collect::<Result<Vec<_>, _>>()
            .unwrap();
        let mut stmt = conn
            .prepare(
                "SELECT session_id, SUM(cost) FROM requests WHERE session_id != '' GROUP BY session_id",
            )
            .unwrap();
        let sess_costs: std::collections::HashMap<String, f64> = stmt
            .query_map([], |r| Ok((r.get::<_, String>(0)?, r.get::<_, f64>(1)?)))
            .unwrap()
            .collect::<Result<_, _>>()
            .unwrap();
        for (sid, first, last, count, tokens) in sess_rows {
            sessions.push(json!({
                "id": sid, "first": first, "last": last,
                "count": count, "tokens": tokens,
                "cost": round6(sess_costs.get(&sid).copied().unwrap_or(0.0)),
            }));
        }
    }

    Json(json!({
        "total_requests": row.0,
        "total_prompt_tokens": row.1,
        "total_completion_tokens": row.2,
        "total_tokens": row.3,
        "total_cache_hit_tokens": row.4,
        "total_cache_miss_tokens": row.7,
        "avg_latency_ms": row.5.round() as i64,
        "total_time_ms": row.6,
        "total_cost": round6(row.8),
        "model_costs": model_costs_rounded,
        "sessions": sessions,
    }))
}

#[derive(Deserialize)]
pub struct AggQuery {
    pub session: Option<String>,
}

/// 会话缓存策略建议查询参数。
#[derive(Deserialize)]
pub struct AdviceQuery {
    pub session: String,
}

/// /api/stats/session/advice — 会话「重置 vs 继续」token 开销建议。
pub async fn session_advice(
    State(state): State<std::sync::Arc<AppState>>,
    Query(q): Query<AdviceQuery>,
) -> Json<Value> {
    let conn = state.db.lock().unwrap();
    let session = q.session;
    if session.is_empty() {
        return Json(json!({"verdict": "insufficient", "reason": "缺少 session 参数", "requests": 0}));
    }

    // 近 N 次请求的统计窗口
    const WINDOW: usize = 10;
    const HORIZON: i64 = 32;

    let mut stmt = conn
        .prepare(
            "SELECT ts, model, cache_hit_tokens, cache_miss_tokens
             FROM requests WHERE session_id=?1 AND (prompt_tokens>0 OR completion_tokens>0)
             ORDER BY ts ASC",
        )
        .unwrap();
    let rows: Vec<(String, String, i64, i64)> = stmt
        .query_map(rusqlite::params![session], |r| {
            Ok((r.get(0)?, r.get(1)?, r.get(2)?, r.get(3)?))
        })
        .unwrap()
        .collect::<Result<_, _>>()
        .unwrap();

    if rows.is_empty() {
        return Json(json!({"verdict": "insufficient", "reason": "该会话暂无有效请求", "requests": 0}));
    }
    let n = rows.len();

    let total_miss: i64 = rows.iter().map(|r| r.3).sum();
    let hits: Vec<i64> = rows.iter().map(|r| r.2).collect();
    let recent_hit = hits.iter().rev().take(WINDOW).max().copied().unwrap_or(0);

    let pricing = crate::model::get_pricing(&rows.last().unwrap().1);
    let reset_cost = total_miss as f64 * pricing.miss / 1_000_000.0;
    let per_req_hit_cost = recent_hit as f64 * pricing.hit / 1_000_000.0;
    let continue_cost = HORIZON as f64 * per_req_hit_cost;

    let (verdict, reason) = if total_miss <= 0 {
        ("continue", "当前会话无未命中, 缓存由共享前缀维持, 重置无必要")
    } else if recent_hit <= 0 {
        ("continue", "近10次无缓存命中, 继续执行无命中开销, 重置无收益")
    } else if reset_cost < continue_cost {
        (
            "reset",
            &format!("未命中总额 ¥{:.3} < {}次请求命中 ¥{:.3}, 重启会话更省", reset_cost, HORIZON, continue_cost)[..],
        )
    } else {
        (
            "continue",
            &format!("未命中总额 ¥{:.3} ≥ {}次请求命中 ¥{:.3}, 继续更省", reset_cost, HORIZON, continue_cost)[..],
        )
    };
    let break_even = if per_req_hit_cost > 0.0 {
        Some((reset_cost / per_req_hit_cost) as i64 + 1)
    } else {
        None
    };

    Json(json!({
        "session": session, "requests": n, "verdict": verdict, "reason": reason,
        "total_miss_tokens": total_miss,
        "reset_cost": round6(reset_cost),
        "recent_window": WINDOW,
        "recent_hit_tokens": recent_hit,
        "recent_hit_cost": round6(per_req_hit_cost),
        "horizon": HORIZON,
        "continue_cost": round6(continue_cost),
        "break_even_requests": break_even,
        "tier": if pricing as *const _ == &crate::model::PRICING_PRO as *const _ { "Pro" } else { "Flash" },
        "hit_price": pricing.hit,
        "miss_price": pricing.miss,
    }))
}

/// 手动触发前端刷新。
pub async fn refresh(State(state): State<std::sync::Arc<AppState>>) -> Json<Value> {
    crate::sse::broadcast(&state.sse, "new_data", json!({}));
    Json(json!({"status": "ok", "broadcast": "new_data"}))
}

// ---- 内部辅助 ----

/// 自适应 gap：Median + 2×MAD（对齐旧逻辑），钳制 [10, 600] 秒。
fn adaptive_gap(rows: &[(String, String, String, i64, i64, i64, i64, i64, i64, f64)]) -> i64 {
    let mut ts_list: Vec<i64> = Vec::new();
    for r in rows {
        let ms = parse_ts_ms(&r.0);
        if ms >= 0 {
            ts_list.push(ms);
        }
    }
    if ts_list.len() < 2 {
        return 60;
    }
    let mut gaps: Vec<i64> = ts_list.windows(2).map(|w| (w[1] - w[0]) / 1000).collect();
    gaps.sort_unstable();
    let n = gaps.len();
    let median = gaps[n / 2];
    let mut mad_vals: Vec<i64> = gaps.iter().map(|g| (g - median).abs()).collect();
    mad_vals.sort_unstable();
    let mad = mad_vals[n / 2];
    (median + 2 * mad).clamp(10, 600)
}

/// 解析 ISO 时间戳为毫秒；失败返回 -1。
fn parse_ts_ms(ts: &str) -> i64 {
    let s = ts.replace('Z', "").replace('+', "T");
    let (date_part, time_part) = s.split_once('T').unwrap_or((&s, "00:00:00"));
    let mut it = date_part.split('-');
    let y: i64 = it.next().and_then(|v| v.parse().ok()).unwrap_or(0);
    let mo: i64 = it.next().and_then(|v| v.parse().ok()).unwrap_or(1);
    let d: i64 = it.next().and_then(|v| v.parse().ok()).unwrap_or(1);
    let mut tit = time_part.split(':');
    let h: i64 = tit.next().and_then(|v| v.parse().ok()).unwrap_or(0);
    let mi: i64 = tit.next().and_then(|v| v.parse().ok()).unwrap_or(0);
    let sec_part = tit.next().unwrap_or("0");
    let sec: i64 = sec_part.split('.').next().and_then(|v| v.parse().ok()).unwrap_or(0);
    let ms_part = sec_part.split('.').nth(1).unwrap_or("");
    let ms: i64 = ms_part.parse().unwrap_or(0);
    let days = y * 365 + mo * 30 + d;
    (days * 86400 + h * 3600 + mi * 60 + sec) * 1000 + ms
}

fn round6(v: f64) -> f64 {
    (v * 1_000_000.0).round() / 1_000_000.0
}

/// 计算任务 wall_time_ms（结束 - 开始，毫秒）。
pub(crate) fn wall_time_ms(start: &str, end: &str) -> i64 {
    let s = parse_ts_ms(start);
    let e = parse_ts_ms(end);
    if s >= 0 && e >= 0 && e >= s {
        e - s
    } else {
        0
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parse_and_wall_time() {
        let a = "2026-08-20T00:00:00";
        let b = "2026-08-20T00:00:10";
        assert_eq!(wall_time_ms(a, b), 10_000);
    }

    #[test]
    fn adaptive_gap_basic() {
        let rows = vec![
            ("2026-08-20T00:00:00".into(), String::new(), String::new(), 0, 0, 0, 0, 0, 0, 0.0),
            ("2026-08-20T00:00:10".into(), String::new(), String::new(), 0, 0, 0, 0, 0, 0, 0.0),
            ("2026-08-20T00:00:21".into(), String::new(), String::new(), 0, 0, 0, 0, 0, 0, 0.0),
            ("2026-08-20T00:00:33".into(), String::new(), String::new(), 0, 0, 0, 0, 0, 0, 0.0),
        ];
        let gap = adaptive_gap(&rows);
        assert_eq!(gap, 13);
    }
}
