use candle_cli::model::mock::MockRuntime;
use candle_cli::model::runtime::CandleTargetRuntime;
use candle_cli::model::types::TurnRequest;

#[test]
fn mock_runtime_returns_text() {
    let mut runtime = MockRuntime::default();
    let result = runtime.generate_turn(TurnRequest {
        system_prompt: "sys".into(),
        messages_json: "[]".into(),
        tools_json: "[]".into(),
    }).unwrap();
    assert!(!result.final_text.is_empty());
}
