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

#[test]
fn build_turn_request_adds_strict_tool_call_few_shot_guidance() {
    let mut session = Session::new(".".to_string());
    let request = build_turn_request(&mut session, "[{\"name\":\"read\"}]").unwrap();

    assert!(request
        .system_prompt
        .contains("Do not output Markdown code fences"));
    assert!(request.system_prompt.contains("Do not output read(...)"));
    assert!(request.system_prompt.contains("User: 读取 README.md"));
    assert!(request.system_prompt.contains("<tool_call>{\"id\":\"call-1\",\"name\":\"read\",\"input\":{\"file_path\":\"README.md\"}}</tool_call>"));
}

#[test]
fn build_turn_request_requires_non_empty_final_answer_after_tool_results() {
    let mut session = Session::new(".".to_string());
    let request = build_turn_request(&mut session, "[{\"name\":\"read\"}]").unwrap();

    assert!(request.system_prompt.contains("After receiving a tool result, you must either request exactly one more tool or provide a non-empty final answer."));
    assert!(request
        .system_prompt
        .contains("Do not return an empty response."));
    assert!(request
        .system_prompt
        .contains("Assistant: 这个项目可以通过 cargo run 或 cargo test 运行"));
}
