use crate::model::types::TurnRequest;
use crate::session::model::Session;

pub fn build_turn_request(
    session: &Session,
    system_prompt: &str,
    tools_json: &str,
) -> Result<TurnRequest, String> {
    Ok(TurnRequest {
        system_prompt: system_prompt.to_string(),
        messages_json: serde_json::to_string(&session.messages).map_err(|e| e.to_string())?,
        tools_json: tools_json.to_string(),
    })
}
