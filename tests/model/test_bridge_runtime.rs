use candle_cli::model::bridge::LocalBridgeRuntime;
use candle_cli::model::runtime::CandleTargetRuntime;
use candle_cli::model::types::TurnRequest;

#[test]
fn bridge_runtime_reports_health_with_worker_command() {
    let runtime = LocalBridgeRuntime::new("python3 python/bridge_worker.py".into());
    let health = runtime.healthcheck();
    assert!(health.ok);
    assert!(runtime.capabilities().supports_tools);
}

#[test]
fn bridge_runtime_healthcheck_uses_worker_protocol() {
    let runtime = LocalBridgeRuntime::new("python3 python/bridge_worker.py".into());
    let health = runtime.healthcheck();
    assert!(health.ok);
    assert!(health.message.contains("bridge worker ok"));
}

#[test]
fn bridge_runtime_returns_turn_result() {
    let mut runtime = LocalBridgeRuntime::new("python3 python/bridge_worker.py".into());
    let result = runtime
        .generate_turn(TurnRequest {
            system_prompt: "sys".into(),
            messages_json: "[]".into(),
            tools_json: "[]".into(),
        })
        .unwrap();
    assert!(!result.final_text.is_empty());
}
