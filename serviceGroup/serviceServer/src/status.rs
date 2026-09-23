//! 服务状态抽象 + TTL 缓存。
//!
//! 对应程序实现文档 "path 与 status 拆分": status 是动态的, 走 Win32 查询,
//! 用 TTL 缓存避免每请求重复 SCM syscall。trait 抽象便于 mock + cfg(windows) 实现分离。

use std::collections::HashMap;
use std::sync::RwLock;
use std::time::{Duration, Instant};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ServiceState {
    Running,
    Stopped,
    /// START_PENDING / CONTINUE_PENDING: 启动中 (SCM 中间态, 启动/停止双向可能被拒)。
    StartPending,
    /// STOP_PENDING: 停止中 (卡死时进程仍在, 是「页面说未运行但进程还活着」的根源)。
    StopPending,
    /// PAUSED / PAUSE_PENDING: 已暂停 (服务不支持暂停, 正常不会出现)。
    Paused,
    NotFound,
    QueryFailed,
}

impl ServiceState {
    pub fn is_running(self) -> bool {
        matches!(self, ServiceState::Running)
    }
    /// SCM 中间态: 既不是跑着也不是停着, 启停都会受影响。
    pub fn is_pending(self) -> bool {
        matches!(
            self,
            ServiceState::StartPending | ServiceState::StopPending | ServiceState::Paused
        )
    }
    pub fn label(self) -> &'static str {
        match self {
            ServiceState::Running => "运行中",
            ServiceState::Stopped => "未运行",
            ServiceState::StartPending => "启动中",
            ServiceState::StopPending => "停止中",
            ServiceState::Paused => "已暂停",
            ServiceState::NotFound => "未部署",
            ServiceState::QueryFailed => "查询失败",
        }
    }
}

/// 服务状态查询抽象 (Win32 SCM 实现走 cfg(windows), 测试用 mock)。
pub trait ServiceStatusProvider: Send + Sync {
    fn query(&self, service_name: &str) -> ServiceState;
}

/// TTL 缓存: 同 service_id 在 ttl 窗口内命中缓存, 不重复调 provider。
pub struct StatusCache {
    ttl: Duration,
    inner: RwLock<HashMap<String, (ServiceState, Instant)>>,
}

impl StatusCache {
    pub fn new(ttl: Duration) -> Self {
        Self {
            ttl,
            inner: RwLock::new(HashMap::new()),
        }
    }

    pub fn get_or_query(
        &self,
        id: &str,
        provider: &dyn ServiceStatusProvider,
    ) -> ServiceState {
        let now = Instant::now();
        if let Some((s, t)) = self.inner.read().unwrap().get(id) {
            if now.duration_since(*t) < self.ttl {
                return *s;
            }
        }
        let s = provider.query(id);
        self.inner.write().unwrap().insert(id.into(), (s, now));
        s
    }

    pub fn invalidate(&self, id: &str) {
        self.inner.write().unwrap().remove(id);
    }

    pub fn clear(&self) {
        self.inner.write().unwrap().clear();
    }
}

/// 默认 provider: windows 走 SCM, 非 windows 走 stub。
pub fn default_provider() -> Box<dyn ServiceStatusProvider> {
    #[cfg(windows)]
    {
        Box::new(crate::win32::scm::ScmProvider)
    }
    #[cfg(not(windows))]
    {
        Box::new(StubProvider)
    }
}

struct StubProvider;
impl ServiceStatusProvider for StubProvider {
    fn query(&self, _: &str) -> ServiceState {
        ServiceState::NotFound
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use rstest::rstest;
    use std::sync::atomic::{AtomicUsize, Ordering};

    struct CountingProvider {
        calls: AtomicUsize,
        state: ServiceState,
    }
    impl ServiceStatusProvider for CountingProvider {
        fn query(&self, _: &str) -> ServiceState {
            self.calls.fetch_add(1, Ordering::SeqCst);
            self.state
        }
    }

    /// TTL 内命中缓存, 不重复查 provider。
    #[rstest]
    fn test_status_cache_hits_within_ttl() {
        let prov = CountingProvider {
            calls: AtomicUsize::new(0),
            state: ServiceState::Running,
        };
        let cache = StatusCache::new(Duration::from_secs(10));
        let s1 = cache.get_or_query("a", &prov);
        let s2 = cache.get_or_query("a", &prov);
        assert_eq!(s1, ServiceState::Running);
        assert_eq!(prov.calls.load(Ordering::SeqCst), 1, "TTL 内应命中缓存不重复查");
        let _ = s2;
    }

    /// 不同 id 各查一次。
    #[rstest]
    fn test_status_cache_misses_different_id() {
        let prov = CountingProvider {
            calls: AtomicUsize::new(0),
            state: ServiceState::Running,
        };
        let cache = StatusCache::new(Duration::from_secs(10));
        cache.get_or_query("a", &prov);
        cache.get_or_query("b", &prov);
        assert_eq!(prov.calls.load(Ordering::SeqCst), 2);
    }

    /// 过期后重查。
    #[rstest]
    fn test_status_cache_expired_requeries() {
        let prov = CountingProvider {
            calls: AtomicUsize::new(0),
            state: ServiceState::Running,
        };
        let cache = StatusCache::new(Duration::from_millis(1));
        cache.get_or_query("a", &prov);
        std::thread::sleep(Duration::from_millis(5));
        cache.get_or_query("a", &prov);
        assert_eq!(prov.calls.load(Ordering::SeqCst), 2, "过期应重查");
    }

    /// invalidate 强制下次重查。
    #[rstest]
    fn test_status_cache_invalidate_forces_requery() {
        let prov = CountingProvider {
            calls: AtomicUsize::new(0),
            state: ServiceState::Running,
        };
        let cache = StatusCache::new(Duration::from_secs(10));
        cache.get_or_query("a", &prov);
        cache.invalidate("a");
        cache.get_or_query("a", &prov);
        assert_eq!(prov.calls.load(Ordering::SeqCst), 2);
    }

    /// ServiceState::is_running 矩阵。
    #[rstest]
    #[case(ServiceState::Running, true)]
    #[case(ServiceState::Stopped, false)]
    #[case(ServiceState::StartPending, false)]
    #[case(ServiceState::StopPending, false)]
    #[case(ServiceState::Paused, false)]
    #[case(ServiceState::NotFound, false)]
    #[case(ServiceState::QueryFailed, false)]
    fn test_service_state_is_running_matrix(#[case] s: ServiceState, #[case] expected: bool) {
        assert_eq!(s.is_running(), expected);
    }

    /// pending 三态如实命名 (2026-09-23): STOP_PENDING 不再折叠成「未运行」。
    #[rstest]
    #[case(ServiceState::StartPending, "启动中", true)]
    #[case(ServiceState::StopPending, "停止中", true)]
    #[case(ServiceState::Paused, "已暂停", true)]
    #[case(ServiceState::Running, "运行中", false)]
    #[case(ServiceState::Stopped, "未运行", false)]
    fn test_service_state_pending_labels(
        #[case] s: ServiceState,
        #[case] label: &str,
        #[case] pending: bool,
    ) {
        assert_eq!(s.label(), label);
        assert_eq!(s.is_pending(), pending);
    }
}
