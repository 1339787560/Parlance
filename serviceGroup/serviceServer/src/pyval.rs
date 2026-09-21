//! Python 值语义助手 —— 把 legacy 的 Python 判定逐条复刻到 Rust。
//!
//! 迁端点时最容易漂的是**边界语义**，而这些边界在 Python 里都由「真值判定」和 `int()` 决定。
//! 例：`if not gold_count` 会把 `0` 判成「缺参数」，而字符串 `"0"` 是 truthy、进 `int()` 后
//! 才被 `<= 0` 拦下 —— 两条分支的**文案不同**（「参数不完整」vs「金币数量必须为正整数」）。
//! 故这些语义必须集中一处、共用，不要各模块各写一份。
//!
//! 使用方：`routes/money.rs`（货币/礼包校验）、`routes/pages.rs`（模板参数校验）。

use serde_json::Value;

/// Python 的 `if x:` 语义 —— `None` / `""` / `0` / `False` / `[]` / `{}` 均为假。
pub fn truthy(v: Option<&Value>) -> bool {
    match v {
        None | Some(Value::Null) => false,
        Some(Value::String(s)) => !s.is_empty(),
        Some(Value::Number(n)) => n.as_f64().map(|f| f != 0.0).unwrap_or(true),
        Some(Value::Bool(b)) => *b,
        Some(Value::Array(a)) => !a.is_empty(),
        Some(Value::Object(o)) => !o.is_empty(),
    }
}

/// Python 的 `int(x)` 语义 —— 接受数字与可解析字符串（含前后空白）；`bool` 按 0/1；
/// 其余（列表/对象/`None`/非法字符串）返 `None`（对应 legacy 的 `except (ValueError, TypeError)`）。
pub fn py_int(v: &Value) -> Option<i64> {
    match v {
        Value::Number(n) => n.as_i64().or_else(|| n.as_f64().map(|f| f as i64)),
        Value::String(s) => s.trim().parse::<i64>().ok(),
        Value::Bool(b) => Some(if *b { 1 } else { 0 }),
        _ => None,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn test_truthy_matches_python_falsy() {
        // Python falsy 全谱
        assert!(!truthy(None));
        assert!(!truthy(Some(&json!(null))));
        assert!(!truthy(Some(&json!(""))));
        assert!(!truthy(Some(&json!(0))));
        assert!(!truthy(Some(&json!(false))));
        assert!(!truthy(Some(&json!([]))));
        assert!(!truthy(Some(&json!({}))));
        // truthy 代表
        assert!(truthy(Some(&json!("x"))));
        assert!(truthy(Some(&json!("0"))), "字符串 \"0\" 在 Python 里是 truthy");
        assert!(truthy(Some(&json!(1))));
        assert!(truthy(Some(&json!([1]))));
        assert!(truthy(Some(&json!({"a": 1}))));
    }

    #[test]
    fn test_py_int_semantics() {
        assert_eq!(py_int(&json!(5)), Some(5));
        assert_eq!(py_int(&json!("5")), Some(5));
        assert_eq!(py_int(&json!(" 5 ")), Some(5), "Python int() 容忍前后空白");
        assert_eq!(py_int(&json!("-3")), Some(-3));
        assert_eq!(py_int(&json!(true)), Some(1));
        assert_eq!(py_int(&json!(false)), Some(0));
        assert_eq!(py_int(&json!("x")), None);
        assert_eq!(py_int(&json!("5.5")), None, "int('5.5') 在 Python 里抛错");
        assert_eq!(py_int(&json!(null)), None);
        assert_eq!(py_int(&json!([1])), None);
    }
}
