use candle_cli::context::builder::build_turn_request;
use candle_cli::session::model::{ContentBlock, Message, MessageRole, Session};

#[test]
fn build_turn_request_includes_messages() {
    let mut session = Session::new(".".to_string());
    session.messages.push(Message {
        role: MessageRole::User,
        blocks: vec![ContentBlock::Text {
            text: "hello".to_string(),
        }],
    });

    let request = build_turn_request(&mut session, "[]").unwrap();

    assert!(request
        .system_prompt
        .contains("terminal-based AI assistant"));
    assert!(request.messages_json.contains("hello"));
}

#[test]
fn build_turn_request_adds_tool_call_protocol_guidance_when_tools_are_available() {
    let mut session = Session::new(".".to_string());
    let request = build_turn_request(&mut session, "[{\"name\":\"read\"}]").unwrap();

    assert!(request.system_prompt.contains("<tool_call>"));
    assert!(request.system_prompt.contains("exactly one"));
    assert!(request.system_prompt.contains("read"));
}
