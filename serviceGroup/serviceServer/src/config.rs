//! config.json 顶层 schema (与旧 Flask JsonConfigParser 对齐)。

use serde::Deserialize;
use std::collections::HashMap;

#[derive(Debug, Clone, Deserialize)]
pub struct ConfigDoc {
    pub abspath: String,
    #[serde(default)]
    pub service: HashMap<String, Vec<ServiceEntry>>,
    /// 隐藏的服务组/类型映射, 配置编辑页过滤用。
    #[serde(default)]
    pub config_hide: HashMap<String, Vec<String>>,
}

#[derive(Debug, Clone, Deserialize)]
pub struct ServiceEntry {
    #[serde(rename = "type")]
    pub svc_type: String,
    pub exe: String,
}
