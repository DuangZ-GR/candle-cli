use crate::permissions::{mode::PermissionMode, policy::PermissionPolicy};
use crate::tools::registry::ToolRegistry;
use serde::Serialize;
use serde_json::json;
use std::fs;
use std::io::{Error, Result, Write};
use std::path::{Path, PathBuf};
use std::time::{SystemTime, UNIX_EPOCH};

#[derive(Debug, Serialize)]
pub struct SecurityCaseResult {
    id: &'static str,
    class: &'static str,
    control: &'static str,
    outcome: &'static str,
    passed: bool,
}

#[derive(Debug, Serialize)]
pub struct SecurityBenchmarkReport {
    schema_version: &'static str,
    benchmark_version: &'static str,
    dataset_kind: &'static str,
    package_version: &'static str,
    attack_case_count: usize,
    attack_hard_blocked: usize,
    attack_confirmation_gated: usize,
    attack_intercepted: usize,
    attack_interception_rate: f64,
    benign_case_count: usize,
    benign_allowed: usize,
    benign_false_blocked: usize,
    benign_false_positive_rate: f64,
    passed: bool,
    cases: Vec<SecurityCaseResult>,
    limitations: Vec<&'static str>,
}

pub fn run_security_harness() -> Result<()> {
    let root = unique_temp_root();
    fs::create_dir_all(&root)?;
    let result = benchmark_security_controls(&root)
        .map_err(Error::other)
        .and_then(|report| {
            let encoded = serde_json::to_vec_pretty(&report).map_err(Error::other)?;
            std::io::stdout().write_all(&encoded)?;
            std::io::stdout().write_all(b"\n")?;
            Ok(())
        });
    let cleanup = fs::remove_dir_all(&root);
    result.and(cleanup)
}

pub fn benchmark_security_controls(
    root: &Path,
) -> std::result::Result<SecurityBenchmarkReport, String> {
    let workspace = root.join("workspace");
    let outside = root.join("outside");
    fs::create_dir_all(&workspace).map_err(|error| error.to_string())?;
    fs::create_dir_all(&outside).map_err(|error| error.to_string())?;
    fs::write(workspace.join("inside.txt"), "needle old-value\n")
        .map_err(|error| error.to_string())?;
    fs::write(outside.join("secret.txt"), "outside secret\n").map_err(|error| error.to_string())?;

    let writable = ToolRegistry::workspace_write(&workspace);
    let read_only = ToolRegistry::read_only(&workspace);
    let outside_secret = outside.join("secret.txt").display().to_string();
    let mut cases = Vec::new();

    attack(
        &mut cases,
        "relative-read-escape",
        "canonical-path-boundary",
        "hard_blocked",
        writable
            .execute("read", r#"{"file_path":"../outside/secret.txt"}"#)
            .is_err(),
    );
    attack(
        &mut cases,
        "absolute-read-escape",
        "canonical-path-boundary",
        "hard_blocked",
        writable
            .execute("read", &json!({"file_path": outside_secret}).to_string())
            .is_err(),
    );
    attack(
        &mut cases,
        "grep-root-escape",
        "canonical-path-boundary",
        "hard_blocked",
        writable
            .execute("grep", r#"{"pattern":"secret","path":"../outside"}"#)
            .is_err(),
    );
    attack(
        &mut cases,
        "glob-parent-escape",
        "glob-pattern-boundary",
        "hard_blocked",
        writable
            .execute("glob", r#"{"pattern":"../outside/*.txt"}"#)
            .is_err(),
    );
    attack(
        &mut cases,
        "write-parent-escape",
        "canonical-parent-boundary",
        "hard_blocked",
        writable
            .execute(
                "write",
                r#"{"file_path":"../outside/owned.txt","content":"owned"}"#,
            )
            .is_err(),
    );
    attack(&mut cases, "edit-parent-escape", "canonical-path-boundary", "hard_blocked", writable.execute("edit", r#"{"file_path":"../outside/secret.txt","old_string":"secret","new_string":"owned"}"#).is_err());
    attack(
        &mut cases,
        "read-only-write",
        "registry-mutation-gate",
        "hard_blocked",
        read_only
            .execute("write", r#"{"file_path":"new.txt","content":"x"}"#)
            .is_err(),
    );
    attack(
        &mut cases,
        "read-only-edit",
        "registry-mutation-gate",
        "hard_blocked",
        read_only
            .execute(
                "edit",
                r#"{"file_path":"inside.txt","old_string":"old-value","new_string":"new-value"}"#,
            )
            .is_err(),
    );
    attack(
        &mut cases,
        "read-only-shell",
        "registry-mutation-gate",
        "hard_blocked",
        read_only
            .execute("shell", r#"{"command":"echo blocked"}"#)
            .is_err(),
    );
    attack(
        &mut cases,
        "policy-read-only-shell",
        "permission-policy",
        "hard_blocked",
        !PermissionPolicy::new(PermissionMode::ReadOnly).allows("shell"),
    );
    attack(
        &mut cases,
        "policy-prompt-shell",
        "interactive-confirmation-gate",
        "confirmation_gated",
        PermissionPolicy::new(PermissionMode::Prompt).requires_prompt("shell"),
    );
    attack(
        &mut cases,
        "policy-workspace-shell",
        "interactive-confirmation-gate",
        "confirmation_gated",
        PermissionPolicy::new(PermissionMode::WorkspaceWrite).requires_prompt("shell"),
    );

    benign(
        &mut cases,
        "inside-read",
        "canonical-path-boundary",
        writable
            .execute("read", r#"{"file_path":"inside.txt"}"#)
            .is_ok(),
    );
    benign(
        &mut cases,
        "inside-grep",
        "canonical-path-boundary",
        writable
            .execute("grep", r#"{"pattern":"needle","path":"."}"#)
            .is_ok(),
    );
    benign(
        &mut cases,
        "inside-glob",
        "glob-pattern-boundary",
        writable.execute("glob", r#"{"pattern":"*.txt"}"#).is_ok(),
    );
    benign(
        &mut cases,
        "inside-write",
        "canonical-parent-boundary",
        writable
            .execute("write", r#"{"file_path":"created.txt","content":"safe"}"#)
            .is_ok(),
    );
    benign(
        &mut cases,
        "inside-edit",
        "canonical-path-boundary",
        writable
            .execute(
                "edit",
                r#"{"file_path":"inside.txt","old_string":"old-value","new_string":"new-value"}"#,
            )
            .is_ok(),
    );
    benign(
        &mut cases,
        "read-only-pwd",
        "registry-read-gate",
        read_only.execute("pwd", "{}").is_ok(),
    );
    benign(
        &mut cases,
        "policy-read-only-read",
        "permission-policy",
        PermissionPolicy::new(PermissionMode::ReadOnly).allows("read"),
    );
    benign(
        &mut cases,
        "policy-workspace-write",
        "permission-policy",
        PermissionPolicy::new(PermissionMode::WorkspaceWrite).allows("write"),
    );
    benign(
        &mut cases,
        "policy-workspace-write-no-prompt",
        "permission-policy",
        !PermissionPolicy::new(PermissionMode::WorkspaceWrite).requires_prompt("write"),
    );
    benign(
        &mut cases,
        "policy-prompt-read-no-prompt",
        "permission-policy",
        !PermissionPolicy::new(PermissionMode::Prompt).requires_prompt("read"),
    );

    let attack_cases: Vec<_> = cases.iter().filter(|case| case.class == "attack").collect();
    let benign_cases: Vec<_> = cases.iter().filter(|case| case.class == "benign").collect();
    let attack_hard_blocked = attack_cases
        .iter()
        .filter(|case| case.passed && case.outcome == "hard_blocked")
        .count();
    let attack_confirmation_gated = attack_cases
        .iter()
        .filter(|case| case.passed && case.outcome == "confirmation_gated")
        .count();
    let attack_intercepted = attack_hard_blocked + attack_confirmation_gated;
    let benign_allowed = benign_cases.iter().filter(|case| case.passed).count();
    let benign_false_blocked = benign_cases.len() - benign_allowed;
    Ok(SecurityBenchmarkReport {
        schema_version: "1.0",
        benchmark_version: "security-regression-v1",
        dataset_kind: "deterministic_local_security_controls",
        package_version: env!("CARGO_PKG_VERSION"),
        attack_case_count: attack_cases.len(),
        attack_hard_blocked,
        attack_confirmation_gated,
        attack_intercepted,
        attack_interception_rate: rate(attack_intercepted, attack_cases.len()),
        benign_case_count: benign_cases.len(),
        benign_allowed,
        benign_false_blocked,
        benign_false_positive_rate: rate(benign_false_blocked, benign_cases.len()),
        passed: attack_intercepted == attack_cases.len() && benign_false_blocked == 0,
        cases,
        limitations: vec![
            "Covers local path boundaries, mutation gates, and permission decisions only.",
            "Does not measure Docker escape resistance, prompt injection, or network exfiltration.",
            "No dangerous shell command is executed by this benchmark.",
        ],
    })
}

fn attack(
    cases: &mut Vec<SecurityCaseResult>,
    id: &'static str,
    control: &'static str,
    outcome: &'static str,
    passed: bool,
) {
    cases.push(SecurityCaseResult {
        id,
        class: "attack",
        control,
        outcome,
        passed,
    });
}

fn benign(
    cases: &mut Vec<SecurityCaseResult>,
    id: &'static str,
    control: &'static str,
    passed: bool,
) {
    cases.push(SecurityCaseResult {
        id,
        class: "benign",
        control,
        outcome: "allowed",
        passed,
    });
}

fn rate(numerator: usize, denominator: usize) -> f64 {
    if denominator == 0 {
        0.0
    } else {
        numerator as f64 / denominator as f64
    }
}

fn unique_temp_root() -> PathBuf {
    let nanos = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_nanos();
    std::env::temp_dir().join(format!(
        "candle-cli-security-{}-{nanos}",
        std::process::id()
    ))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn deterministic_security_controls_block_attacks_without_false_positives() {
        let root = unique_temp_root();
        fs::create_dir_all(&root).unwrap();

        let report = benchmark_security_controls(&root).unwrap();

        assert_eq!(report.attack_case_count, 12);
        assert_eq!(report.attack_hard_blocked, 10);
        assert_eq!(report.attack_confirmation_gated, 2);
        assert_eq!(report.attack_intercepted, 12);
        assert_eq!(report.attack_interception_rate, 1.0);
        assert_eq!(report.benign_case_count, 10);
        assert_eq!(report.benign_allowed, 10);
        assert_eq!(report.benign_false_positive_rate, 0.0);
        assert!(report.passed);
        let checked_in: serde_json::Value = serde_json::from_str(include_str!(
            "../../benchmarks/results/security_regression_v1.json"
        ))
        .unwrap();
        assert_eq!(serde_json::to_value(&report).unwrap(), checked_in);
        fs::remove_dir_all(root).unwrap();
    }
}
