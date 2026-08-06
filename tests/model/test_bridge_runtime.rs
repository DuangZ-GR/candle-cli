use candle_cli::model::bridge::LocalBridgeRuntime;
use candle_cli::model::runtime::CandleTargetRuntime;
use candle_cli::model::types::TurnRequest;

fn bridge_command() -> String {
    let python = std::env::var("CANDLE_CLI_TEST_PYTHON").unwrap_or_else(|_| "python3".into());
    format!("{python} tests/fixtures/counting_bridge.py")
}

#[test]
fn bridge_runtime_reports_health_with_worker_command() {
    let runtime = LocalBridgeRuntime::new(bridge_command());
    let health = runtime.healthcheck();
    assert!(health.ok);
    assert!(runtime.capabilities().supports_tools);
}

#[test]
fn bridge_runtime_healthcheck_uses_worker_protocol() {
    let runtime = LocalBridgeRuntime::new(bridge_command());
    let health = runtime.healthcheck();
    assert!(health.ok);
    assert!(health.message.contains("counting bridge ok"));
}

#[test]
fn bridge_runtime_returns_turn_result() {
    let mut runtime = LocalBridgeRuntime::new(bridge_command());
    let result = runtime
        .generate_turn(TurnRequest {
            system_prompt: "sys".into(),
            messages_json: "[]".into(),
            tools_json: "[]".into(),
            timeout_ms: None,
            deadline_unix_ms: None,
        })
        .unwrap();
    assert_eq!(result.final_text, "bridge turn 1");
    assert_eq!(result.usage.prompt_tokens, 100);
    assert_eq!(result.usage.cached_prompt_tokens, 80);
    assert_eq!(result.usage.provider_cache_hit_rate(), Some(0.8));
}

#[test]
fn bridge_runtime_worker_still_reports_health_after_worker_split() {
    let runtime = LocalBridgeRuntime::new(bridge_command());
    let health = runtime.healthcheck();
    assert!(health.ok);
    assert!(health.message.contains("counting bridge ok"));
}

#[test]
fn bridge_runtime_reuses_worker_for_multiple_turns() {
    let mut runtime = LocalBridgeRuntime::new(bridge_command());
    let messages_json = r#"[{"role":"User","blocks":[{"Text":{"text":"hello bridge"}}]}]"#;
    let first = runtime
        .generate_turn(TurnRequest {
            system_prompt: "sys".into(),
            messages_json: messages_json.into(),
            tools_json: "[]".into(),
            timeout_ms: None,
            deadline_unix_ms: None,
        })
        .unwrap();
    let second = runtime
        .generate_turn(TurnRequest {
            system_prompt: "sys".into(),
            messages_json: messages_json.into(),
            tools_json: "[]".into(),
            timeout_ms: None,
            deadline_unix_ms: None,
        })
        .unwrap();
    assert_eq!(first.final_text, "bridge turn 1");
    assert_eq!(second.final_text, "bridge turn 2");
}

#[test]
fn bridge_runtime_returns_fixture_output_without_runtime_fallback() {
    let mut runtime = LocalBridgeRuntime::new(bridge_command());
    let result = runtime
        .generate_turn(TurnRequest {
            system_prompt: "sys".into(),
            messages_json: r#"[{"role":"User","blocks":[{"Text":{"text":"abc"}}]}]"#.into(),
            tools_json: "[]".into(),
            timeout_ms: None,
            deadline_unix_ms: None,
        })
        .unwrap();
    assert_eq!(result.final_text, "bridge turn 1");
}

#[test]
fn bridge_runtime_preserves_unicode_json_lines_on_windows() {
    let mut runtime = LocalBridgeRuntime::new(bridge_command());
    let result = runtime
        .generate_turn(TurnRequest {
            system_prompt: "你是迁移诊断助手".into(),
            messages_json:
                r#"[{"role":"User","blocks":[{"Text":{"text":"读取源码并定位首个差异"}}]}]"#.into(),
            tools_json: "[]".into(),
            timeout_ms: None,
            deadline_unix_ms: None,
        })
        .unwrap();

    assert_eq!(result.final_text, "bridge turn 1");
}
