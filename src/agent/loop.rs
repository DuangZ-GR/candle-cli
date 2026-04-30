use crate::agent::turn::finish_turn;
use crate::model::runtime::CandleTargetRuntime;
use crate::model::types::TurnResult;
use crate::session::model::{ContentBlock, Message, MessageRole, Session};
use crate::tools::registry::ToolRegistry;

pub fn run_single_turn<R: CandleTargetRuntime>(
    session: &mut Session,
    runtime: &mut R,
    _tools: &ToolRegistry,
) -> Result<TurnResult, String> {
    let request = crate::context::builder::build_turn_request(session, "[]")?;
    let result = runtime.generate_turn(request)?;
    session.messages.push(Message {
        role: MessageRole::Assistant,
        blocks: vec![ContentBlock::Text {
            text: finish_turn(result.final_text.clone()),
        }],
    });
    Ok(result)
}
