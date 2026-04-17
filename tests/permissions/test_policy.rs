use candle_cli::permissions::mode::PermissionMode;
use candle_cli::permissions::policy::PermissionPolicy;

#[test]
fn read_tool_allowed_in_read_only() {
    let policy = PermissionPolicy::new(PermissionMode::ReadOnly);
    assert!(policy.allows("read"));
    assert!(!policy.allows("shell"));
}
