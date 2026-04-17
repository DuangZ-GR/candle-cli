use candle_cli::tools::registry::ToolRegistry;

#[test]
fn shell_tool_executes_command() {
    let registry = ToolRegistry::default_workspace_write();
    let result = registry.execute("shell", r#"{"command":"pwd"}"#).unwrap();
    assert!(!result.is_empty());
}
