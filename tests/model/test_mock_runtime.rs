use candle_cli::model::mock::MockRuntime;
use candle_cli::model::runtime::CandleTargetRuntime;
use candle_cli::model::types::TurnRequest;

#[test]
fn mock_runtime_returns_text() {
    let mut runtime = MockRuntime;
    let result = runtime
        .generate_turn(TurnRequest {
            system_prompt: "sys".into(),
            messages_json: "[]".into(),
            tools_json: "[]".into(),
            timeout_ms: None,
            deadline_unix_ms: None,
        })
        .unwrap();
    assert!(!result.final_text.is_empty());
}
