use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct AgentRunBudget {
    max_model_requests: usize,
    max_tool_steps: usize,
    model_requests_used: usize,
    tool_steps_used: usize,
    subagent_invocations: usize,
    deadline: Option<Instant>,
    deadline_wall_clock: Option<SystemTime>,
}

impl AgentRunBudget {
    pub fn new(max_model_requests: usize, max_tool_steps: usize) -> Self {
        Self {
            max_model_requests,
            max_tool_steps,
            ..Self::default()
        }
    }

    pub fn with_timeout(
        max_model_requests: usize,
        max_tool_steps: usize,
        timeout: Duration,
    ) -> Self {
        Self {
            deadline: Some(Instant::now() + timeout),
            deadline_wall_clock: Some(SystemTime::now() + timeout),
            ..Self::new(max_model_requests, max_tool_steps)
        }
    }

    pub fn consume_model_request(&mut self) -> bool {
        if self.model_requests_used >= self.max_model_requests {
            return false;
        }
        self.model_requests_used += 1;
        true
    }

    pub fn consume_tool_step(&mut self) -> bool {
        if self.tool_steps_used >= self.max_tool_steps {
            return false;
        }
        self.tool_steps_used += 1;
        true
    }

    pub fn record_subagent_invocation(&mut self) {
        self.subagent_invocations += 1;
    }

    pub fn max_model_requests(&self) -> usize {
        self.max_model_requests
    }

    pub fn max_tool_steps(&self) -> usize {
        self.max_tool_steps
    }

    pub fn model_requests_used(&self) -> usize {
        self.model_requests_used
    }

    pub fn tool_steps_used(&self) -> usize {
        self.tool_steps_used
    }

    pub fn subagent_invocations(&self) -> usize {
        self.subagent_invocations
    }

    pub fn timed_out(&self) -> bool {
        self.deadline
            .is_some_and(|deadline| Instant::now() >= deadline)
    }

    pub fn remaining_timeout_ms(&self) -> Option<u64> {
        let deadline = self.deadline?;
        let remaining = deadline.saturating_duration_since(Instant::now());
        if remaining.is_zero() {
            return Some(0);
        }
        Some(
            u64::try_from(remaining.as_millis())
                .unwrap_or(u64::MAX)
                .max(1),
        )
    }

    pub fn deadline_unix_ms(&self) -> Option<u64> {
        let millis = self
            .deadline_wall_clock?
            .duration_since(UNIX_EPOCH)
            .ok()?
            .as_millis();
        Some(u64::try_from(millis).unwrap_or(u64::MAX))
    }
}

#[cfg(test)]
mod tests {
    use super::AgentRunBudget;
    use std::time::Duration;

    #[test]
    fn timed_budget_exposes_a_bounded_provider_timeout() {
        let budget = AgentRunBudget::with_timeout(2, 2, Duration::from_secs(1));
        let remaining = budget.remaining_timeout_ms().unwrap();

        assert!((1..=1_000).contains(&remaining));
        assert!(!budget.timed_out());
        assert!(budget.deadline_unix_ms().is_some());
    }
}

#[derive(Default)]
pub struct AgentState;
