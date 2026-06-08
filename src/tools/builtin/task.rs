use crate::agent::r#loop::run_single_turn_with_limit;
use crate::model::runtime::CandleTargetRuntime;
use crate::permissions::policy::PermissionPolicy;
use crate::session::model::{ContentBlock, Message, MessageRole, Session};

/// Dispatch a subtask to a sub-agent with limited context.
/// The sub-agent runs a short bounded loop and returns a plain-text result.
pub fn run<R: CandleTargetRuntime>(
    description: &str,
    runtime: &mut R,
    _parent_tools: &crate::tools::registry::ToolRegistry,
    _parent_policy: &PermissionPolicy,
) -> Result<String, String> {
    // Sub-agent uses read-only tools only (safe by default)
    let sub_tools = ToolRegistry::read_only(".");
    let sub_policy = PermissionPolicy::new(crate::permissions::mode::PermissionMode::ReadOnly);

    let mut sub_session = Session::new(".".to_string());
    sub_session.messages.push(Message {
        role: MessageRole::User,
        blocks: vec![ContentBlock::Text {
            text: format!(
                "You are a sub-agent. Complete this subtask using only read tools:\n\n{description}\n\nReturn ONLY the result, no extra explanation."
            ),
        }],
    });

    // Short loop: max 3 steps for sub-agents
    let result = run_single_turn_with_limit(&mut sub_session, runtime, &sub_tools, &sub_policy, 3)?;
    Ok(result.final_text)
}
