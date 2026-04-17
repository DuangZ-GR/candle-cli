use crate::model::runtime::CandleTargetRuntime;
use crate::model::types::{RuntimeCapabilities, RuntimeHealth, TurnRequest, TurnResult};

pub struct LocalBridgeRuntime {
    command: String,
}

impl LocalBridgeRuntime {
    pub fn new(command: String) -> Self {
        Self { command }
    }
}

impl CandleTargetRuntime for LocalBridgeRuntime {
    fn generate_turn(&mut self, _request: TurnRequest) -> Result<TurnResult, String> {
        Err("bridge runtime not implemented".into())
    }

    fn healthcheck(&self) -> RuntimeHealth {
        RuntimeHealth {
            ok: !self.command.is_empty(),
            message: "bridge placeholder".into(),
        }
    }

    fn capabilities(&self) -> RuntimeCapabilities {
        RuntimeCapabilities {
            supports_tools: true,
            supports_streaming: false,
        }
    }
}
