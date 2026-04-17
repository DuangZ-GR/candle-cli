use candle_cli::model::types::TurnRequest;

#[test]
fn turn_request_exists() {
    let req = TurnRequest {
        system_prompt: "sys".into(),
        messages_json: "[]".into(),
        tools_json: "[]".into(),
    };
    assert_eq!(req.system_prompt, "sys");
}
