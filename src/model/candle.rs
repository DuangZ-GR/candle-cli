use crate::model::runtime::CandleTargetRuntime;
use crate::model::types::{RuntimeCapabilities, RuntimeHealth, TurnRequest, TurnResult};

pub struct CandleRuntime;

impl CandleTargetRuntime for CandleRuntime {
    fn generate_turn(&mut self, _request: TurnRequest) -> Result<TurnResult, String> {
        Err("candle runtime not implemented".into())
    }

    fn healthcheck(&self) -> RuntimeHealth {
        RuntimeHealth {
            ok: false,
            message: "not implemented".into(),
        }
    }

    fn capabilities(&self) -> RuntimeCapabilities {
        RuntimeCapabilities {
            supports_tools: true,
            supports_streaming: false,
        }
    }
}
