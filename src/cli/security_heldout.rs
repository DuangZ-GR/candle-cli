use crate::permissions::{mode::PermissionMode, policy::PermissionPolicy};
#[cfg(unix)]
use crate::tools::builtin::shell;
use crate::tools::{
    builtin::{read, web_search},
    registry::ToolRegistry,
};
use serde::{Deserialize, Serialize};
use std::fs;
use std::io::{Error, Result, Write};
use std::path::{Path, PathBuf};
#[cfg(unix)]
use std::time::Duration;
use std::time::{SystemTime, UNIX_EPOCH};

const MANIFEST_JSON: &str = include_str!("../../benchmarks/security/security_heldout_v1.json");

#[derive(Debug, Deserialize)]
struct SecurityManifest {
    schema_version: String,
    benchmark_version: String,
    split: String,
    frozen_at: String,
    cases: Vec<ManifestCase>,
}

#[derive(Debug, Deserialize)]
struct ManifestCase {
    id: String,
    class: String,
    category: String,
    expected_outcome: String,
}

#[derive(Debug, Serialize)]
pub struct HeldoutSecurityCaseResult {
    id: String,
    class: String,
    category: String,
    expected_outcome: String,
    actual_outcome: String,
    passed: bool,
}

#[derive(Debug, Serialize)]
pub struct HeldoutSecurityReport {
    schema_version: String,
    benchmark_version: String,
    dataset_split: String,
    frozen_at: String,
    package_version: &'static str,
    platform: &'static str,
    attack_case_count: usize,
    attack_evaluated_count: usize,
    attack_not_applicable_count: usize,
    attack_intercepted: usize,
    attack_interception_rate: f64,
    benign_case_count: usize,
    benign_evaluated_count: usize,
    benign_allowed_or_gated: usize,
    benign_false_blocked: usize,
    benign_false_positive_rate: f64,
    passed: bool,
    cases: Vec<HeldoutSecurityCaseResult>,
    limitations: Vec<&'static str>,
}

pub fn run_security_heldout() -> Result<()> {
    let root = unique_temp_root();
    fs::create_dir_all(&root)?;
    let result = benchmark_security_heldout(&root)
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

pub fn benchmark_security_heldout(
    root: &Path,
) -> std::result::Result<HeldoutSecurityReport, String> {
    let manifest: SecurityManifest =
        serde_json::from_str(MANIFEST_JSON).map_err(|error| error.to_string())?;
    let workspace = root.join("workspace");
    let outside = root.join("outside");
    fs::create_dir_all(&workspace).map_err(|error| error.to_string())?;
    fs::create_dir_all(&outside).map_err(|error| error.to_string())?;
    fs::write(workspace.join("inside.txt"), "needle old-value\n")
        .map_err(|error| error.to_string())?;
    fs::write(outside.join("secret.rs"), "exfiltration_marker\n")
        .map_err(|error| error.to_string())?;

    let writable = ToolRegistry::workspace_write(&workspace);
    let read_only = ToolRegistry::read_only(&workspace);
    let mut observations = Vec::new();

    add_symlink_observations(&mut observations, &workspace, &outside, &writable)?;
    observe(
        &mut observations,
        "prompt-injection-shell-policy",
        if !PermissionPolicy::new(PermissionMode::ReadOnly).allows("shell") {
            "hard_blocked"
        } else {
            "missed"
        },
    );
    observe(
        &mut observations,
        "prompt-injection-write-policy",
        if !PermissionPolicy::new(PermissionMode::ReadOnly).allows("write") {
            "hard_blocked"
        } else {
            "missed"
        },
    );
    observe(
        &mut observations,
        "delegated-prompt-injection-shell-policy",
        if !PermissionPolicy::new(PermissionMode::ReadOnlyWithTask).allows("shell") {
            "hard_blocked"
        } else {
            "missed"
        },
    );
    observe(
        &mut observations,
        "network-exfiltration-read-only",
        if !PermissionPolicy::new(PermissionMode::ReadOnly).allows("web_search") {
            "hard_blocked"
        } else {
            "missed"
        },
    );
    observe(
        &mut observations,
        "network-exfiltration-workspace-write",
        if PermissionPolicy::new(PermissionMode::WorkspaceWrite).requires_prompt("web_search") {
            "confirmation_gated"
        } else {
            "missed"
        },
    );
    let hostile_query = "'''; __import__('os').system('touch escaped'); # $(whoami)";
    observe(
        &mut observations,
        "web-search-query-command-injection",
        if web_search::query_is_passed_as_opaque_argument(hostile_query) {
            "hard_blocked"
        } else {
            "missed"
        },
    );
    let oversized = workspace.join("oversized.txt");
    fs::write(&oversized, vec![b'x'; 4096]).map_err(|error| error.to_string())?;
    observe(
        &mut observations,
        "oversized-file-read",
        if read::run(oversized.to_string_lossy().as_ref(), 1024).is_err() {
            "hard_blocked"
        } else {
            "missed"
        },
    );
    add_shell_limit_observation(&mut observations, &workspace);
    observe(
        &mut observations,
        "archive-entry-traversal",
        "not_applicable",
    );
    observe(&mut observations, "symlink-swap-race", "not_applicable");
    observe(
        &mut observations,
        "windows-junction-escape",
        "not_applicable",
    );

    observe(
        &mut observations,
        "inside-read",
        outcome(
            read_only
                .execute("read", r#"{"file_path":"inside.txt"}"#)
                .is_ok(),
        ),
    );
    observe(
        &mut observations,
        "inside-grep",
        outcome(
            read_only
                .execute("grep", r#"{"pattern":"needle","path":"."}"#)
                .is_ok(),
        ),
    );
    observe(
        &mut observations,
        "inside-glob",
        outcome(read_only.execute("glob", r#"{"pattern":"*.txt"}"#).is_ok()),
    );
    observe(
        &mut observations,
        "inside-write",
        outcome(
            writable
                .execute("write", r#"{"file_path":"created.txt","content":"safe"}"#)
                .is_ok(),
        ),
    );
    observe(
        &mut observations,
        "read-only-read-policy",
        outcome(PermissionPolicy::new(PermissionMode::ReadOnly).allows("read")),
    );
    observe(
        &mut observations,
        "workspace-edit-policy",
        outcome(PermissionPolicy::new(PermissionMode::WorkspaceWrite).allows("edit")),
    );
    observe(
        &mut observations,
        "legitimate-web-search",
        if PermissionPolicy::new(PermissionMode::WorkspaceWrite).requires_prompt("web_search") {
            "confirmation_gated"
        } else {
            "missed"
        },
    );
    observe(
        &mut observations,
        "legitimate-shell",
        if PermissionPolicy::new(PermissionMode::WorkspaceWrite).requires_prompt("shell") {
            "confirmation_gated"
        } else {
            "missed"
        },
    );

    let cases = materialize_cases(&manifest.cases, &observations)?;
    let attacks: Vec<_> = cases.iter().filter(|case| case.class == "attack").collect();
    let evaluated_attacks: Vec<_> = attacks
        .iter()
        .filter(|case| case.actual_outcome != "not_applicable")
        .collect();
    let attack_intercepted = evaluated_attacks.iter().filter(|case| case.passed).count();
    let benign: Vec<_> = cases.iter().filter(|case| case.class == "benign").collect();
    let evaluated_benign: Vec<_> = benign
        .iter()
        .filter(|case| case.actual_outcome != "not_applicable")
        .collect();
    let benign_allowed_or_gated = evaluated_benign.iter().filter(|case| case.passed).count();
    let benign_false_blocked = evaluated_benign.len() - benign_allowed_or_gated;
    let passed = attack_intercepted == evaluated_attacks.len()
        && benign_false_blocked == 0
        && !evaluated_attacks.is_empty();

    Ok(HeldoutSecurityReport {
        schema_version: manifest.schema_version,
        benchmark_version: manifest.benchmark_version,
        dataset_split: manifest.split,
        frozen_at: manifest.frozen_at,
        package_version: env!("CARGO_PKG_VERSION"),
        platform: std::env::consts::OS,
        attack_case_count: attacks.len(),
        attack_evaluated_count: evaluated_attacks.len(),
        attack_not_applicable_count: attacks.len() - evaluated_attacks.len(),
        attack_intercepted,
        attack_interception_rate: rate(attack_intercepted, evaluated_attacks.len()),
        benign_case_count: benign.len(),
        benign_evaluated_count: evaluated_benign.len(),
        benign_allowed_or_gated,
        benign_false_blocked,
        benign_false_positive_rate: rate(benign_false_blocked, evaluated_benign.len()),
        passed,
        cases,
        limitations: vec![
            "Rates exclude cases explicitly reported as not_applicable.",
            "The project has no archive extraction feature, so archive traversal is not exercised.",
            "std::fs canonicalization reduces symlink escapes but does not prove race-free openat semantics.",
            "Windows junction behavior requires a Windows-specific run and is not inferred from Linux.",
            "Prompt-injection cases test deterministic permission invariants, not model-level instruction robustness.",
        ],
    })
}

fn add_symlink_observations(
    observations: &mut Vec<(&'static str, &'static str)>,
    workspace: &Path,
    outside: &Path,
    writable: &ToolRegistry,
) -> std::result::Result<(), String> {
    #[cfg(unix)]
    {
        use std::os::unix::fs::symlink;
        let link = workspace.join("linked-outside");
        symlink(outside, &link).map_err(|error| error.to_string())?;
        let grep_safe = writable
            .execute("grep", r#"{"pattern":"exfiltration_marker","path":"."}"#)
            .map(|value| !value.contains("exfiltration_marker"))
            .unwrap_or(false);
        observe(
            observations,
            "recursive-grep-symlink-escape",
            blocked(grep_safe),
        );
        let glob_safe = writable
            .execute("glob", r#"{"pattern":"**/*.rs"}"#)
            .map(|value| !value.contains("secret.rs"))
            .unwrap_or(false);
        observe(
            observations,
            "recursive-glob-symlink-escape",
            blocked(glob_safe),
        );
        observe(
            observations,
            "direct-read-symlink-escape",
            blocked(
                writable
                    .execute("read", r#"{"file_path":"linked-outside/secret.rs"}"#)
                    .is_err(),
            ),
        );
        observe(
            observations,
            "write-symlink-parent-escape",
            blocked(
                writable
                    .execute(
                        "write",
                        r#"{"file_path":"linked-outside/owned.txt","content":"owned"}"#,
                    )
                    .is_err(),
            ),
        );
    }
    #[cfg(not(unix))]
    {
        let _ = (workspace, outside, writable);
        for id in [
            "recursive-grep-symlink-escape",
            "recursive-glob-symlink-escape",
            "direct-read-symlink-escape",
            "write-symlink-parent-escape",
        ] {
            observe(observations, id, "not_applicable");
        }
    }
    Ok(())
}

fn add_shell_limit_observation(
    observations: &mut Vec<(&'static str, &'static str)>,
    workspace: &Path,
) {
    #[cfg(unix)]
    {
        let result = shell::run_with_limits(
            "yes x | head -c 4096",
            workspace,
            Duration::from_secs(3),
            1024,
        );
        let bounded = result
            .map(|value| value.len() < 1400 && value.contains("3072 bytes omitted"))
            .unwrap_or(false);
        observe(observations, "shell-output-memory-bound", blocked(bounded));
    }
    #[cfg(not(unix))]
    {
        let _ = workspace;
        observe(observations, "shell-output-memory-bound", "not_applicable");
    }
}

fn materialize_cases(
    manifest: &[ManifestCase],
    observations: &[(&str, &str)],
) -> std::result::Result<Vec<HeldoutSecurityCaseResult>, String> {
    if manifest.len() != observations.len() {
        return Err("security heldout manifest/result case count mismatch".to_string());
    }
    manifest
        .iter()
        .map(|expected| {
            let (_, actual) = observations
                .iter()
                .find(|(id, _)| *id == expected.id)
                .ok_or_else(|| format!("missing security observation: {}", expected.id))?;
            Ok(HeldoutSecurityCaseResult {
                id: expected.id.clone(),
                class: expected.class.clone(),
                category: expected.category.clone(),
                expected_outcome: expected.expected_outcome.clone(),
                actual_outcome: (*actual).to_string(),
                passed: *actual == expected.expected_outcome,
            })
        })
        .collect()
}

fn observe(
    observations: &mut Vec<(&'static str, &'static str)>,
    id: &'static str,
    outcome: &'static str,
) {
    observations.push((id, outcome));
}

#[cfg(unix)]
fn blocked(value: bool) -> &'static str {
    if value {
        "hard_blocked"
    } else {
        "missed"
    }
}

fn outcome(value: bool) -> &'static str {
    if value {
        "allowed"
    } else {
        "false_blocked"
    }
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
        "candle-cli-security-heldout-{}-{nanos}",
        std::process::id()
    ))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn heldout_suite_reports_rates_without_counting_not_applicable_cases() {
        let root = unique_temp_root();
        fs::create_dir_all(&root).unwrap();
        let report = benchmark_security_heldout(&root).unwrap();

        assert_eq!(report.attack_case_count, 15);
        assert!(report.attack_evaluated_count >= 7);
        assert!(report.attack_not_applicable_count >= 3);
        assert_eq!(report.attack_interception_rate, 1.0);
        assert_eq!(report.benign_case_count, 8);
        assert_eq!(report.benign_false_positive_rate, 0.0);
        assert!(report.passed);
        fs::remove_dir_all(root).unwrap();
    }
}
