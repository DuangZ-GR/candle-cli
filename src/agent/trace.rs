use std::time::Instant;

use crate::model::types::TokenUsage;

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum TraceEvent {
    BuildTurnRequest,
    RuntimeGenerateTurn,
    ParseToolCall,
    ToolCall { name: String },
    ToolResult { tool: String, status: String },
    FinalAnswer,
}

#[derive(Debug, Clone)]
struct TimedStep {
    event: TraceEvent,
    elapsed_ms: u64,
}

#[derive(Debug, Clone, Default)]
pub struct ExecutionTrace {
    steps: Vec<TimedStep>,
    started: Option<Instant>,
    last_mark: Option<Instant>,
    usage: TokenUsage,
}

impl ExecutionTrace {
    pub fn new() -> Self {
        Self {
            steps: Vec::new(),
            started: Some(Instant::now()),
            last_mark: Some(Instant::now()),
            usage: TokenUsage::default(),
        }
    }

    pub fn push(&mut self, event: TraceEvent) {
        let now = Instant::now();
        let elapsed = self
            .last_mark
            .map(|t| t.elapsed().as_millis() as u64)
            .unwrap_or(0);
        self.steps.push(TimedStep {
            event,
            elapsed_ms: elapsed,
        });
        self.last_mark = Some(now);
    }

    pub fn is_empty(&self) -> bool {
        self.steps.is_empty()
    }

    pub fn record_usage(&mut self, usage: &TokenUsage) {
        self.usage.merge(usage);
    }

    pub fn usage(&self) -> &TokenUsage {
        &self.usage
    }

    pub fn render_lines(&self) -> Vec<String> {
        let total_ms = self
            .started
            .map(|s| s.elapsed().as_millis() as u64)
            .unwrap_or(0);
        let mut lines = vec![format!(
            "Last trace ({:.1}s total)",
            total_ms as f64 / 1000.0
        )];
        for (idx, step) in self.steps.iter().enumerate() {
            let timing = format!("+{}ms", step.elapsed_ms);
            let line = match &step.event {
                TraceEvent::BuildTurnRequest => {
                    format!("{}. build_turn_request  [{timing}]", idx + 1)
                }
                TraceEvent::RuntimeGenerateTurn => {
                    format!("{}. runtime.generate_turn  [{timing}]", idx + 1)
                }
                TraceEvent::ParseToolCall => {
                    format!("{}. parse_tool_call  [{timing}]", idx + 1)
                }
                TraceEvent::ToolCall { name } => {
                    format!("{}. tool: {name}  [{timing}]", idx + 1)
                }
                TraceEvent::ToolResult { tool: _, status } => {
                    format!("{}. tool result: {status}  [{timing}]", idx + 1)
                }
                TraceEvent::FinalAnswer => {
                    format!("{}. final answer  [{timing}]", idx + 1)
                }
            };
            lines.push(line);
        }
        lines.push(format!(
            "Provider usage: {}/{} requests reported",
            self.usage.usage_reported_request_count, self.usage.request_count
        ));
        lines.push(format!(
            "- retries: {} provider latency: {}ms",
            self.usage.retry_count, self.usage.provider_latency_ms
        ));
        if self.usage.usage_complete() {
            lines.push(format!(
                "- tokens: prompt={} completion={} total={}",
                self.usage.prompt_tokens, self.usage.completion_tokens, self.usage.total_tokens
            ));
        } else {
            lines.push("- tokens: unavailable (provider usage incomplete)".to_string());
        }
        match self.usage.provider_cache_hit_rate() {
            Some(rate) => lines.push(format!("- provider cache hit rate: {:.2}%", rate * 100.0)),
            None => lines.push("- provider cache hit rate: unavailable".to_string()),
        }
        lines
    }

    pub fn to_json(&self) -> serde_json::Value {
        let total_ms = self
            .started
            .map(|s| s.elapsed().as_millis() as u64)
            .unwrap_or(0);
        let steps: Vec<_> = self
            .steps
            .iter()
            .map(|s| {
                serde_json::json!({
                    "step": s.event.step_name(),
                    "elapsed_ms": s.elapsed_ms,
                })
            })
            .collect();
        serde_json::json!({
            "total_ms": total_ms,
            "total_s": format!("{:.2}", total_ms as f64 / 1000.0),
            "steps": steps,
            "usage": self.usage.to_json(),
        })
    }
}

impl TraceEvent {
    fn step_name(&self) -> &str {
        match self {
            Self::BuildTurnRequest => "build_turn_request",
            Self::RuntimeGenerateTurn => "runtime.generate_turn",
            Self::ParseToolCall => "parse_tool_call",
            Self::ToolCall { name } => name.as_str(),
            Self::ToolResult { status, .. } => status.as_str(),
            Self::FinalAnswer => "final_answer",
        }
    }
}
