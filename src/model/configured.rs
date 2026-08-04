use crate::model::bridge::LocalBridgeRuntime;
use crate::model::mock::MockRuntime;
use crate::model::runtime::CandleTargetRuntime;
use crate::model::types::{RuntimeCapabilities, RuntimeHealth, TurnRequest, TurnResult};

#[cfg(windows)]
const DEFAULT_BRIDGE_COMMAND: &str = "python python/bridge_worker.py";
#[cfg(not(windows))]
const DEFAULT_BRIDGE_COMMAND: &str = "python3 python/bridge_worker.py";

/// Runtime selected from the CLI environment and reused for the lifetime of a
/// prompt or interactive session.
pub enum ConfiguredRuntime {
    Mock(MockRuntime),
    Bridge {
        runtime: LocalBridgeRuntime,
        command: String,
        model_id: Option<String>,
    },
    Invalid {
        message: String,
    },
}

impl ConfiguredRuntime {
    pub fn from_environment() -> Self {
        let runtime_name = std::env::var("CANDLE_CLI_RUNTIME").ok();
        Self::from_runtime_name(runtime_name.as_deref())
    }

    fn from_runtime_name(runtime_name: Option<&str>) -> Self {
        match runtime_name.map(|value| value.trim().to_ascii_lowercase()) {
            Some(name) if name == "bridge" => {
                let command = std::env::var("CANDLE_CLI_BRIDGE_COMMAND")
                    .unwrap_or_else(|_| DEFAULT_BRIDGE_COMMAND.to_string());
                Self::Bridge {
                    runtime: LocalBridgeRuntime::new(command.clone()),
                    command,
                    model_id: std::env::var("CANDLE_CLI_MODEL_ID").ok(),
                }
            }
            None => Self::Mock(MockRuntime),
            Some(name) if name == "mock" => Self::Mock(MockRuntime),
            Some(name) => Self::Invalid {
                message: format!(
                    "unsupported CANDLE_CLI_RUNTIME '{name}'; expected 'mock' or 'bridge'"
                ),
            },
        }
    }

    fn refresh_bridge_if_model_changed(&mut self) {
        let Self::Bridge {
            runtime,
            command,
            model_id,
        } = self
        else {
            return;
        };

        let current_model_id = std::env::var("CANDLE_CLI_MODEL_ID").ok();
        if *model_id != current_model_id {
            *runtime = LocalBridgeRuntime::new(command.clone());
            *model_id = current_model_id;
        }
    }
}

impl CandleTargetRuntime for ConfiguredRuntime {
    fn generate_turn(&mut self, request: TurnRequest) -> Result<TurnResult, String> {
        self.refresh_bridge_if_model_changed();
        match self {
            Self::Mock(runtime) => runtime.generate_turn(request),
            Self::Bridge { runtime, .. } => runtime.generate_turn(request),
            Self::Invalid { message } => Err(message.clone()),
        }
    }

    fn healthcheck(&self) -> RuntimeHealth {
        match self {
            Self::Mock(runtime) => runtime.healthcheck(),
            Self::Bridge { runtime, .. } => runtime.healthcheck(),
            Self::Invalid { message } => RuntimeHealth {
                ok: false,
                message: message.clone(),
            },
        }
    }

    fn capabilities(&self) -> RuntimeCapabilities {
        match self {
            Self::Mock(runtime) => runtime.capabilities(),
            Self::Bridge { runtime, .. } => runtime.capabilities(),
            Self::Invalid { .. } => RuntimeCapabilities {
                supports_tools: false,
                supports_streaming: false,
            },
        }
    }
}

#[cfg(test)]
mod tests {
    use super::ConfiguredRuntime;
    use crate::model::runtime::CandleTargetRuntime;

    #[test]
    fn unknown_runtime_is_an_explicit_error() {
        let runtime = ConfiguredRuntime::from_runtime_name(Some("typo"));
        let health = runtime.healthcheck();

        assert!(!health.ok);
        assert!(health
            .message
            .contains("unsupported CANDLE_CLI_RUNTIME 'typo'"));
    }

    #[test]
    fn runtime_name_is_trimmed_and_case_insensitive() {
        let runtime = ConfiguredRuntime::from_runtime_name(Some(" Mock "));
        assert!(runtime.healthcheck().ok);
    }
}
