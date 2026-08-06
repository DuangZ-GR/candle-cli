use crate::agent::r#loop::run_single_turn_with_budget;
use crate::agent::state::AgentRunBudget;
use crate::model::runtime::CandleTargetRuntime;
use crate::model::types::TurnResult;
use crate::permissions::policy::PermissionPolicy;
use crate::session::model::{ContentBlock, Message, MessageRole, Session};
use crate::tools::registry::ToolRegistry;

/// Dispatch a subtask to a sub-agent with limited context.
/// The sub-agent runs a short bounded loop and returns a plain-text result.
pub fn run<R: CandleTargetRuntime>(
    description: &str,
    runtime: &mut R,
    _parent_tools: &ToolRegistry,
    _parent_policy: &PermissionPolicy,
) -> Result<TurnResult, String> {
    let mut budget = AgentRunBudget::new(3, 3);
    run_with_budget(
        description,
        runtime,
        _parent_tools,
        _parent_policy,
        &mut budget,
    )
}

pub fn run_with_budget<R: CandleTargetRuntime>(
    description: &str,
    runtime: &mut R,
    parent_tools: &ToolRegistry,
    _parent_policy: &PermissionPolicy,
    budget: &mut AgentRunBudget,
) -> Result<TurnResult, String> {
    // Sub-agent uses read-only tools only (safe by default)
    let sub_tools = ToolRegistry::read_only(parent_tools.workspace_root());
    let sub_policy = PermissionPolicy::new(crate::permissions::mode::PermissionMode::ReadOnly);

    let mut sub_session = Session::new(parent_tools.workspace_root().display().to_string());
    sub_session.messages.push(Message {
        role: MessageRole::User,
        blocks: vec![ContentBlock::Text {
            text: format!(
                "You are a sub-agent. Complete this subtask using only read tools:\n\n{description}\n\nReturn ONLY the result, no extra explanation."
            ),
        }],
    });

    // Short loop: max 3 steps for sub-agents
    run_single_turn_with_budget(
        &mut sub_session,
        runtime,
        &sub_tools,
        &sub_policy,
        3,
        budget,
    )
}
