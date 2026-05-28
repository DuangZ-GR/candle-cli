use candle_cli::context::builder::build_turn_request;
use candle_cli::session::model::{ContentBlock, Message, MessageRole, Session};

#[test]
fn builds_turn_request_from_session() {
    let mut session = Session::new("/tmp/workspace".into());
    let req = build_turn_request(&mut session, "[]").unwrap();
    assert!(!req.system_prompt.is_empty());
    assert!(!req.messages_json.is_empty());
}

#[test]
fn build_turn_request_includes_user_messages() {
    let mut session = Session::new(".".to_string());
    session.messages.push(Message {
        role: MessageRole::User,
        blocks: vec![ContentBlock::Text {
            text: "hello".to_string(),
        }],
    });

    let request = build_turn_request(&mut session, "[]").unwrap();

    assert!(request.messages_json.contains("hello"));
}

#[test]
fn build_turn_request_adds_tool_call_protocol_guidance_when_tools_are_available() {
    let mut session = Session::new(".".to_string());
    let request = build_turn_request(&mut session, r#"[{"name":"read"}]"#).unwrap();

    assert!(request.system_prompt.contains("<tool_call>"));
    assert!(request.system_prompt.contains("TOOL USE PROTOCOL"));
    assert!(request.system_prompt.contains("read"));
}

#[test]
fn build_turn_request_omits_tool_guidance_when_no_tools() {
    let mut session = Session::new(".".to_string());
    let request = build_turn_request(&mut session, "[]").unwrap();

    assert!(!request.system_prompt.contains("<tool_call>"));
    assert!(!request.system_prompt.contains("TOOL USE PROTOCOL"));
}
