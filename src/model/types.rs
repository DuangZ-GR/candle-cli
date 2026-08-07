#[derive(Debug, Clone, PartialEq, Eq)]
pub struct TurnRequest {
    pub system_prompt: String,
    pub messages_json: String,
    pub tools_json: String,
    /// Remaining wall-clock budget for this provider request. `None` keeps
    /// the runtime default for non-experiment callers.
    pub timeout_ms: Option<u64>,
    /// Absolute Unix deadline so bridge process startup is included in the
    /// same wall-clock budget as provider inference.
    pub deadline_unix_ms: Option<u64>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ToolCallIntent {
    pub id: String,
    pub name: String,
    pub input_json: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum RuntimeEvent {
    TextDelta(String),
    ToolCall(ToolCallIntent),
    Warning(String),
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct TurnResult {
    pub final_text: String,
    pub tool_calls: Vec<ToolCallIntent>,
    pub usage: TokenUsage,
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct TokenUsage {
    pub request_count: u64,
    pub retry_count: u64,
    pub provider_latency_ms: u64,
    pub usage_reported_request_count: u64,
    pub prompt_tokens: u64,
    pub completion_tokens: u64,
    pub total_tokens: u64,
    pub cache_metrics_reported_request_count: u64,
    pub cached_prompt_tokens: u64,
    pub cache_miss_prompt_tokens: Option<u64>,
}

impl TokenUsage {
    pub fn unreported_request() -> Self {
        Self {
            request_count: 1,
            ..Self::default()
        }
    }

    pub fn merge(&mut self, other: &Self) {
        self.request_count += other.request_count;
        self.retry_count += other.retry_count;
        self.provider_latency_ms += other.provider_latency_ms;
        self.usage_reported_request_count += other.usage_reported_request_count;
        self.prompt_tokens += other.prompt_tokens;
        self.completion_tokens += other.completion_tokens;
        self.total_tokens += other.total_tokens;
        self.cache_metrics_reported_request_count += other.cache_metrics_reported_request_count;
        self.cached_prompt_tokens += other.cached_prompt_tokens;
        self.cache_miss_prompt_tokens = match (
            self.cache_miss_prompt_tokens,
            other.cache_miss_prompt_tokens,
        ) {
            (Some(left), Some(right)) => Some(left + right),
            (None, Some(right))
                if self.cache_metrics_reported_request_count
                    == other.cache_metrics_reported_request_count =>
            {
                Some(right)
            }
            _ => None,
        };
    }

    pub fn usage_complete(&self) -> bool {
        self.request_count > 0 && self.usage_reported_request_count == self.request_count
    }

    pub fn cache_metrics_complete(&self) -> bool {
        self.usage_complete() && self.cache_metrics_reported_request_count == self.request_count
    }

    pub fn provider_cache_hit_rate(&self) -> Option<f64> {
        if self.cache_metrics_complete() && self.prompt_tokens > 0 {
            Some(self.cached_prompt_tokens as f64 / self.prompt_tokens as f64)
        } else {
            None
        }
    }

    pub fn to_json(&self) -> serde_json::Value {
        let usage_complete = self.usage_complete();
        let cache_complete = self.cache_metrics_complete();
        serde_json::json!({
            "request_count": self.request_count,
            "retry_count": self.retry_count,
            "provider_latency_ms": self.provider_latency_ms,
            "usage_reported_request_count": self.usage_reported_request_count,
            "usage_complete": usage_complete,
            "prompt_tokens": usage_complete.then_some(self.prompt_tokens),
            "completion_tokens": usage_complete.then_some(self.completion_tokens),
            "total_tokens": usage_complete.then_some(self.total_tokens),
            "cache_metrics_reported_request_count": self.cache_metrics_reported_request_count,
            "cache_metrics_complete": cache_complete,
            "cached_prompt_tokens": cache_complete.then_some(self.cached_prompt_tokens),
            "cache_miss_prompt_tokens": if cache_complete { self.cache_miss_prompt_tokens } else { None },
            "provider_cache_hit_rate": self.provider_cache_hit_rate(),
        })
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RuntimeCapabilities {
    pub supports_tools: bool,
    pub supports_streaming: bool,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RuntimeHealth {
    pub ok: bool,
    pub message: String,
}

#[cfg(test)]
mod tests {
    use super::TokenUsage;

    fn reported_usage(prompt: u64, cached: Option<u64>) -> TokenUsage {
        TokenUsage {
            request_count: 1,
            retry_count: 0,
            provider_latency_ms: 25,
            usage_reported_request_count: 1,
            prompt_tokens: prompt,
            completion_tokens: 10,
            total_tokens: prompt + 10,
            cache_metrics_reported_request_count: u64::from(cached.is_some()),
            cached_prompt_tokens: cached.unwrap_or_default(),
            cache_miss_prompt_tokens: cached.map(|value| prompt - value),
        }
    }

    #[test]
    fn usage_json_keeps_missing_provider_metrics_null() {
        let usage = TokenUsage::unreported_request();
        let json = usage.to_json();

        assert_eq!(json["usage_complete"], false);
        assert!(json["prompt_tokens"].is_null());
        assert!(json["provider_cache_hit_rate"].is_null());
    }

    #[test]
    fn usage_merge_calculates_cache_rate_only_when_every_request_reports_it() {
        let mut usage = reported_usage(100, Some(80));
        usage.merge(&reported_usage(50, Some(20)));

        assert!(usage.usage_complete());
        assert!(usage.cache_metrics_complete());
        assert_eq!(usage.prompt_tokens, 150);
        assert_eq!(usage.provider_latency_ms, 50);
        assert_eq!(usage.cached_prompt_tokens, 100);
        assert_eq!(usage.provider_cache_hit_rate(), Some(2.0 / 3.0));
    }

    #[test]
    fn one_unreported_request_invalidates_aggregate_rates() {
        let mut usage = reported_usage(100, Some(80));
        usage.merge(&TokenUsage::unreported_request());

        assert!(!usage.usage_complete());
        assert!(!usage.cache_metrics_complete());
        assert_eq!(usage.provider_cache_hit_rate(), None);
        assert!(usage.to_json()["prompt_tokens"].is_null());
    }
}
