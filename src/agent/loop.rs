use crate::agent::turn::finish_turn;
use crate::model::mock::MockRuntime;
use crate::model::runtime::CandleTargetRuntime;
use crate::model::types::TurnResult;
use crate::session::model::{ContentBlock, Message, MessageRole, Session};
use crate::tools::registry::ToolRegistry;

pub fn run_single_turn(
    session: &mut Session,
    runtime: &mut MockRuntime,
    _tools: &ToolRegistry,
    system_prompt: &str,
) -> Result<TurnResult, String> {
    let request = crate::context::builder::build_turn_request(session, system_prompt, "[]")?;
    let result = runtime.generate_turn(request)?;
    session.messages.push(Message {
        role: MessageRole::Assistant,
        blocks: vec![ContentBlock::Text {
            text: finish_turn(result.final_text.clone()),
        }],
    });
    Ok(result)
}
