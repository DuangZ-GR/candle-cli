use crate::agent::r#loop::run_single_turn;
use crate::model::bridge::LocalBridgeRuntime;
use crate::permissions::mode::PermissionMode;
use crate::permissions::policy::PermissionPolicy;
use crate::session::model::{ContentBlock, Message, MessageRole, Session};
use crate::tools::registry::ToolRegistry;
use std::io::{self, Write};
use std::path::PathBuf;
use std::time::Instant;

#[derive(Debug, serde::Serialize)]
pub struct ScenarioResult {
    pub name: String,
    pub passed: bool,
    pub elapsed_ms: u64,
    pub tool_steps: usize,
    pub api_rounds: usize,
    pub token_est: usize,
    pub final_text: String,
}

pub fn run_harness(session_dir: PathBuf) -> io::Result<()> {
    let scenarios: Vec<(&str, &str)> = vec![
        ("read_file", "Read the file README.md and tell me what license this project uses."),
        ("glob_search", "Use glob to find all .rs files in the src directory."),
        ("code_search", "Search for the string 'fn run_single_turn' in the project source code."),
        ("shell_command", "Run 'ls src/' and report what directories you see."),
    ];

    let workspace = std::env::current_dir()?;
    let tools = ToolRegistry::workspace_write(workspace.clone());
    let policy = PermissionPolicy::new(PermissionMode::WorkspaceWrite);
    let mut results: Vec<ScenarioResult> = Vec::new();

    println!("candle-cli harness");
    println!("{:=<50}", "");

    let total_start = Instant::now();
    for (name, prompt) in &scenarios {
        let mut session = Session::new(workspace.display().to_string());
        session.messages.push(Message {
            role: MessageRole::User,
            blocks: vec![ContentBlock::Text {
                text: prompt.to_string(),
            }],
        });

        let scenario_start = Instant::now();
        let result = if std::env::var("CANDLE_CLI_RUNTIME").ok().as_deref() == Some("bridge") {
            let mut runtime =
                LocalBridgeRuntime::new("python3 python/bridge_worker.py".into());
            run_single_turn(&mut session, &mut runtime, &tools, &policy)
        } else {
            // Mock mode for testing
            use crate::model::mock::MockRuntime;
            let mut runtime = MockRuntime;
            run_single_turn(&mut session, &mut runtime, &tools, &policy)
        };

        let elapsed = scenario_start.elapsed().as_millis() as u64;
        let (passed, err_msg, final_text) = match &result {
            Ok(r) => (true, String::new(), r.final_text.clone()),
            Err(e) => (false, e.clone(), String::new()),
        };
        let tool_steps = session
            .messages
            .iter()
            .filter(|m| m.role == MessageRole::Tool)
            .count();
        let api_rounds = session
            .messages
            .iter()
            .filter(|m| m.role == MessageRole::Assistant)
            .count();
        let msg_json = serde_json::to_string(&session.messages).unwrap_or_default();
        let token_est = crate::context::budget::estimate_tokens_json(&msg_json);

        let status = if passed { "PASS" } else { "FAIL" };
        println!(
            "  [{status}] {name}  ({:.1}s, {tool_steps} tools, {api_rounds} API calls, ~{token_est} tokens)",
            elapsed as f64 / 1000.0
        );
        if !passed {
            println!("         error: {:.80}", err_msg);
        }

        results.push(ScenarioResult {
            name: name.to_string(),
            passed,
            elapsed_ms: elapsed,
            tool_steps,
            api_rounds,
            token_est,
            final_text,
        });

        // Save session
        let store = crate::session::store::SessionStore::new(session_dir.clone());
        store.save(&session).ok();
    }

    let total = total_start.elapsed().as_millis() as u64;
    let passed = results.iter().filter(|r| r.passed).count();
    let total_scenarios = results.len();
    println!("{:=<50}", "");
    println!(
        "  Total: {passed}/{total_scenarios} passed  ({:.1}s total)",
        total as f64 / 1000.0
    );

    // Save JSON report
    let report = serde_json::json!({
        "passed": passed,
        "total": total_scenarios,
        "total_ms": total,
        "results": results,
    });
    let mut path = session_dir;
    path.push("harness_report.json");
    if let Ok(json) = serde_json::to_string_pretty(&report) {
        let _ = std::fs::write(&path, json);
        println!("  Report: {}", path.display());
    }

    Ok(())
}
