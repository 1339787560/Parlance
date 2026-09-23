//! config.json 顶层 schema (与旧 Flask JsonConfigParser 对齐)。

use serde::Deserialize;
use std::collections::HashMap;

#[derive(Debug, Clone, Deserialize)]
pub struct ConfigDoc {
    pub abspath: String,
    #[serde(default)]
    pub service: HashMap<String, Vec<ServiceEntry>>,
    /// 卡片显示顺序 (顶层 `serviceOrder` = 服务类型列表, 见 serviceserver_spec/05)。
    /// 每个游戏组内按该列表排序; 未列入的类型排最后 (仍按 service_id 字典序)。
    /// 缺省空 = 全部按 service_id 字典序 (旧行为)。
    #[serde(rename = "serviceOrder", default)]
    pub service_order: Vec<String>,
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
