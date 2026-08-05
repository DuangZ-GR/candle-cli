use crate::model::runtime::CandleTargetRuntime;
use crate::model::types::{
    RuntimeCapabilities, RuntimeHealth, TokenUsage, TurnRequest, TurnResult,
};

#[derive(Default)]
pub struct MockRuntime;

impl CandleTargetRuntime for MockRuntime {
    fn generate_turn(&mut self, _request: TurnRequest) -> Result<TurnResult, String> {
        Ok(TurnResult {
            final_text: "mock response".into(),
            tool_calls: Vec::new(),
            usage: TokenUsage::unreported_request(),
        })
    }

    fn healthcheck(&self) -> RuntimeHealth {
        RuntimeHealth {
            ok: true,
            message: "ok".into(),
        }
    }

    fn capabilities(&self) -> RuntimeCapabilities {
        RuntimeCapabilities {
            supports_tools: true,
            supports_streaming: false,
        }
    }
}
