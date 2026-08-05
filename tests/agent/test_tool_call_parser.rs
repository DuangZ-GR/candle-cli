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
fn parses_fallback_function_style_tool_call() {
    let parsed = parse_tool_call(r#"read({"file_path":"README.md"})"#)
        .expect("fallback function-style call should parse")
        .expect("fallback function-style tool call should be present");

    assert_eq!(parsed.id, "call-fallback");
    assert_eq!(parsed.name, "read");
    assert_eq!(parsed.input_json, r#"{"file_path":"README.md"}"#);
}

#[test]
fn parses_fallback_function_style_with_empty_object() {
    let parsed = parse_tool_call("pwd({})")
        .expect("pwd fallback function-style call should parse")
        .expect("pwd fallback function-style tool call should be present");

    assert_eq!(parsed.id, "call-fallback");
    assert_eq!(parsed.name, "pwd");
    assert_eq!(parsed.input_json, "{}");
}

#[test]
fn parses_fallback_calls_for_every_registered_non_pwd_tool() {
    let cases = [
        ("read", r#"{"file_path":"README.md"}"#),
        ("glob", r#"{"pattern":"src/**/*.rs"}"#),
        ("grep", r#"{"pattern":"main","path":"src"}"#),
        ("web_search", r#"{"query":"MindSpore"}"#),
        ("task", r#"{"description":"inspect the migration code"}"#),
        ("write", r#"{"file_path":"report.txt","content":"ok"}"#),
        (
            "edit",
            r#"{"file_path":"report.txt","old_string":"ok","new_string":"done"}"#,
        ),
        ("shell", r#"{"command":"pwd"}"#),
    ];

    for (name, input) in cases {
        let parsed = parse_tool_call(&format!("{name}({input})"))
            .expect("registered fallback call should parse")
            .expect("registered fallback call should be present");
        assert_eq!(parsed.name, name);
    }
}

#[test]
fn rejects_unknown_fallback_function_name() {
    let parsed = parse_tool_call(r#"foo({"file_path":"README.md"})"#)
        .expect("unknown function-style output should be treated as final text");
    assert!(parsed.is_none());
}

#[test]
fn rejects_invalid_json_in_fallback_function_style() {
    let err = parse_tool_call(r#"read({"file_path":"README.md",})"#)
        .expect_err("invalid JSON payload should fail");

    assert!(matches!(err, ToolCallParseError::InvalidJson(_)));
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

#[test]
fn canonical_tool_call_takes_precedence_over_fallback() {
    let mixed = r#"read({"file_path":"unused"})
<tool_call>{"id":"call-1","name":"glob","input":{"pattern":"src/*.rs"}}</tool_call>"#;

    let parsed = parse_tool_call(mixed)
        .expect("mixed output should parse without error")
        .expect("canonical tool call should be selected");

    assert_eq!(parsed.id, "call-1");
    assert_eq!(parsed.name, "glob");
    assert_eq!(parsed.input_json, "{\"pattern\":\"src/*.rs\"}");
}
