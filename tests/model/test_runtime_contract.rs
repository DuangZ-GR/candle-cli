use candle_cli::model::types::TurnRequest;

#[test]
fn turn_request_exists() {
    let req = TurnRequest {
        system_prompt: "sys".into(),
        messages_json: "[]".into(),
        tools_json: "[]".into(),
        timeout_ms: None,
        deadline_unix_ms: None,
    };
    assert_eq!(req.system_prompt, "sys");
}
