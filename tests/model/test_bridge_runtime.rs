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

#[test]
fn bridge_runtime_worker_still_reports_health_after_worker_split() {
    let runtime = LocalBridgeRuntime::new("python3 python/bridge_worker.py".into());
    let health = runtime.healthcheck();
    assert!(health.ok);
    assert!(health.message.contains("bridge worker ok"));
}

#[test]
fn bridge_runtime_uses_latest_user_text() {
    let mut runtime = LocalBridgeRuntime::new("python3 python/bridge_worker.py".into());
    let messages_json = r#"[{"role":"User","blocks":[{"Text":{"text":"hello bridge"}}]}]"#;
    let result = runtime
        .generate_turn(TurnRequest {
            system_prompt: "sys".into(),
            messages_json: messages_json.into(),
            tools_json: "[]".into(),
        })
        .unwrap();
    assert!(result.final_text.contains("hello bridge"));
}

#[test]
fn bridge_runtime_generation_is_not_stub_text() {
    let mut runtime = LocalBridgeRuntime::new("python3 python/bridge_worker.py".into());
    let result = runtime
        .generate_turn(TurnRequest {
            system_prompt: "sys".into(),
            messages_json: r#"[{"role":"User","blocks":[{"Text":{"text":"abc"}}]}]"#.into(),
            tools_json: "[]".into(),
        })
        .unwrap();
    assert_ne!(result.final_text, "bridge response");
}
