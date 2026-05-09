use candle_cli::agent::tool_call::{parse_tool_call, ToolCallParseError};

#[test]
fn parses_valid_tool_call_block() {
    let parsed = parse_tool_call(
        r#"<tool_call>{"id":"call-1","name":"read","input":{"file_path":"README.md"}}</tool_call>"#,
    )
    .expect("valid tool call should parse")
    .expect("tool call block should be present");

    assert_eq!(parsed.id, "call-1");
    assert_eq!(parsed.name, "read");
    assert_eq!(parsed.input_json, r#"{"file_path":"README.md"}"#);
}

#[test]
fn parses_tool_call_even_with_surrounding_text() {
    let parsed = parse_tool_call(
        r#"I will inspect the file now.
<tool_call>{"id":"call-2","name":"read","input":{"file_path":"README.md"}}</tool_call>
Thanks."#,
    )
    .expect("surrounding text should still parse")
    .expect("tool call block should be present");

    assert_eq!(parsed.id, "call-2");
    assert_eq!(parsed.name, "read");
}

#[test]
fn returns_none_when_no_tool_call_block_exists() {
    let parsed = parse_tool_call("final answer only").expect("plain text should not error");
    assert!(parsed.is_none());
}

#[test]
fn rejects_malformed_json_inside_tool_call() {
    let err = parse_tool_call(r#"<tool_call>{"id":"call-1"</tool_call>"#)
        .expect_err("malformed JSON should fail");

    assert!(matches!(err, ToolCallParseError::InvalidJson(_)));
}

#[test]
fn rejects_missing_name() {
    let err = parse_tool_call(r#"<tool_call>{"id":"call-1","input":{}}</tool_call>"#)
        .expect_err("missing name should fail");

    assert_eq!(err.to_string(), "tool call is missing string field: name");
}

#[test]
fn rejects_non_object_input() {
    let err = parse_tool_call(
        r#"<tool_call>{"id":"call-1","name":"read","input":"README.md"}</tool_call>"#,
    )
    .expect_err("input must be an object");

    assert_eq!(err.to_string(), "tool call field 'input' must be an object");
}
