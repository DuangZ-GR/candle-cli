use crate::model::types::{RuntimeCapabilities, RuntimeHealth, TurnRequest, TurnResult};

pub trait CandleTargetRuntime {
    fn generate_turn(&mut self, request: TurnRequest) -> Result<TurnResult, String>;
    fn healthcheck(&self) -> RuntimeHealth;
    fn capabilities(&self) -> RuntimeCapabilities;
}
