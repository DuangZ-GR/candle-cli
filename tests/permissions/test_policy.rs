use candle_cli::permissions::mode::PermissionMode;
use candle_cli::permissions::policy::PermissionPolicy;
use std::str::FromStr;

#[test]
fn read_only_allows_read_tools_and_blocks_write_tools() {
    let policy = PermissionPolicy::new(PermissionMode::ReadOnly);
    assert!(policy.allows("read"));
    assert!(policy.allows("glob"));
    assert!(!policy.allows("shell"));
    assert!(!policy.allows("edit"));
}

#[test]
fn prompt_mode_requires_confirmation_for_dangerous_tools() {
    let policy = PermissionPolicy::new(PermissionMode::Prompt);
    assert!(policy.allows("read"));
    assert!(policy.requires_prompt("shell"));
    assert!(policy.requires_prompt("edit"));
    assert!(policy.requires_prompt("write"));
    assert!(policy.requires_prompt("web_search"));
    assert!(!policy.requires_prompt("read"));
}

#[test]
fn read_only_with_task_allows_delegation_but_not_mutation() {
    let policy = PermissionPolicy::new(PermissionMode::ReadOnlyWithTask);
    assert!(policy.allows("read"));
    assert!(policy.allows("task"));
    assert!(!policy.allows("shell"));
    assert!(!policy.allows("edit"));
    assert!(!policy.requires_prompt("task"));
}

#[test]
fn workspace_write_prompts_for_host_or_network_access_but_not_file_edits() {
    let policy = PermissionPolicy::new(PermissionMode::WorkspaceWrite);
    assert!(policy.allows("shell"));
    assert!(policy.allows("edit"));
    assert!(policy.requires_prompt("shell"));
    assert!(policy.requires_prompt("web_search"));
    assert!(!policy.requires_prompt("edit"));
}

#[test]
fn danger_full_access_allows_current_tools_without_prompt() {
    let policy = PermissionPolicy::new(PermissionMode::DangerFullAccess);
    assert!(policy.allows("shell"));
    assert!(!policy.requires_prompt("shell"));
    assert!(policy.allows("write"));
    assert!(!policy.requires_prompt("edit"));
}

#[test]
fn parses_permission_mode_from_string_values() {
    assert_eq!(
        PermissionMode::from_str("read-only").ok(),
        Some(PermissionMode::ReadOnly)
    );
    assert_eq!(
        PermissionMode::from_str("read-only-with-task").ok(),
        Some(PermissionMode::ReadOnlyWithTask)
    );
    assert_eq!(
        PermissionMode::from_str("workspace-write").ok(),
        Some(PermissionMode::WorkspaceWrite)
    );
    assert_eq!(
        PermissionMode::from_str("prompt").ok(),
        Some(PermissionMode::Prompt)
    );
    assert_eq!(
        PermissionMode::from_str("danger-full-access").ok(),
        Some(PermissionMode::DangerFullAccess)
    );
    assert_eq!(PermissionMode::from_str("unknown").ok(), None);
}
