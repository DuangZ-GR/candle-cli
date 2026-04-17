use candle_cli::tools::registry::ToolRegistry;

#[test]
fn pwd_tool_runs() {
    let registry = ToolRegistry::default_read_only();
    let result = registry.execute("pwd", "{}").unwrap();
    assert!(!result.is_empty());
}
