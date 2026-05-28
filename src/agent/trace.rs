#[derive(Debug, Clone, PartialEq, Eq)]
pub enum TraceEvent {
    BuildTurnRequest,
    RuntimeGenerateTurn,
    ParseToolCall,
    ToolCall { name: String },
    ToolResult { tool: String, status: String },
    FinalAnswer,
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct ExecutionTrace {
    steps: Vec<TraceEvent>,
}

impl ExecutionTrace {
    pub fn new() -> Self {
        Self { steps: Vec::new() }
    }

    pub fn push(&mut self, event: TraceEvent) {
        self.steps.push(event);
    }

    pub fn is_empty(&self) -> bool {
        self.steps.is_empty()
    }

    pub fn render_lines(&self) -> Vec<String> {
        let mut lines = vec!["Last trace".to_string()];
        for (idx, step) in self.steps.iter().enumerate() {
            let line = match step {
                TraceEvent::BuildTurnRequest => format!("{}. build_turn_request", idx + 1),
                TraceEvent::RuntimeGenerateTurn => format!("{}. runtime.generate_turn", idx + 1),
                TraceEvent::ParseToolCall => format!("{}. parse_tool_call", idx + 1),
                TraceEvent::ToolCall { name } => format!("{}. tool: {name}", idx + 1),
                TraceEvent::ToolResult { tool: _, status } => {
                    format!("{}. tool result: {status}", idx + 1)
                }
                TraceEvent::FinalAnswer => format!("{}. final answer", idx + 1),
            };
            lines.push(line);
        }
        lines
    }
}
