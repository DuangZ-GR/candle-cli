use crate::session::model::{MessageRole, Session};

/// Trim conversation to fit within `max_turns` complete user turns.
///
/// A turn starts at a user message and includes every assistant/tool message up
/// to the next user message. System messages are retained regardless of where
/// they appear. Treating the whole range as one unit avoids leaving orphaned
/// tool calls or tool results in the request sent to a model provider.
pub fn compact_session(session: &mut Session, max_turns: usize) {
    if max_turns == 0 {
        return;
    }

    let user_count = session
        .messages
        .iter()
        .filter(|message| message.role == MessageRole::User)
        .count();

    if user_count <= max_turns {
        return;
    }

    let remove_count = user_count - max_turns;
    let keep_from = session
        .messages
        .iter()
        .enumerate()
        .filter(|(_, message)| message.role == MessageRole::User)
        .nth(remove_count)
        .map(|(index, _)| index)
        .expect("user_count is greater than remove_count");

    let removed_messages: Vec<_> = session
        .messages
        .iter()
        .enumerate()
        .filter(|(index, message)| *index < keep_from && message.role != MessageRole::System)
        .map(|(_, message)| message.clone())
        .collect();
    session.task_state.absorb_messages(&removed_messages);

    session.messages = std::mem::take(&mut session.messages)
        .into_iter()
        .enumerate()
        .filter_map(|(index, message)| {
            (index >= keep_from || message.role == MessageRole::System).then_some(message)
        })
        .collect();
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::session::model::{ContentBlock, Message};

    fn text_msg(role: MessageRole, content: &str) -> Message {
        Message {
            role,
            blocks: vec![ContentBlock::Text {
                text: content.into(),
            }],
        }
    }

    #[test]
    fn compact_keeps_last_n_turns() {
        let mut session = Session::new("ws".into());
        for i in 1..=4 {
            session
                .messages
                .push(text_msg(MessageRole::User, &format!("u{i}")));
            session
                .messages
                .push(text_msg(MessageRole::Assistant, &format!("a{i}")));
        }

        compact_session(&mut session, 2);

        assert_eq!(session.messages.len(), 4);
        assert_eq!(extract_text(&session.messages[0]), "u3");
        assert_eq!(extract_text(&session.messages[1]), "a3");
        assert_eq!(extract_text(&session.messages[2]), "u4");
        assert_eq!(extract_text(&session.messages[3]), "a4");
    }

    #[test]
    fn compact_noop_when_under_limit() {
        let mut session = Session::new("ws".into());
        session.messages.push(text_msg(MessageRole::User, "hi"));
        session
            .messages
            .push(text_msg(MessageRole::Assistant, "hello"));

        compact_session(&mut session, 5);

        assert_eq!(session.messages.len(), 2);
    }

    #[test]
    fn compact_removes_an_entire_multi_tool_turn() {
        let mut session = Session::new("ws".into());
        session.messages.extend([
            text_msg(MessageRole::User, "old question"),
            tool_call_msg("call-1", "read"),
            tool_result_msg("call-1", "first result"),
            tool_call_msg("call-2", "grep"),
            tool_result_msg("call-2", "second result"),
            text_msg(MessageRole::Assistant, "old answer"),
            text_msg(MessageRole::User, "new question"),
            text_msg(MessageRole::Assistant, "new answer"),
        ]);

        compact_session(&mut session, 1);

        assert_eq!(session.messages.len(), 2);
        assert_eq!(extract_text(&session.messages[0]), "new question");
        assert_eq!(extract_text(&session.messages[1]), "new answer");
        assert!(!session.messages.iter().any(|message| {
            message.role == MessageRole::Tool
                || message
                    .blocks
                    .iter()
                    .any(|block| matches!(block, ContentBlock::ToolCall { .. }))
        }));
    }

    #[test]
    fn compact_preserves_system_messages_before_removed_turns() {
        let mut session = Session::new("ws".into());
        session.messages.extend([
            text_msg(MessageRole::System, "system policy"),
            text_msg(MessageRole::User, "old question"),
            text_msg(MessageRole::Assistant, "old answer"),
            text_msg(MessageRole::User, "new question"),
            text_msg(MessageRole::Assistant, "new answer"),
        ]);

        compact_session(&mut session, 1);

        assert_eq!(session.messages.len(), 3);
        assert_eq!(extract_text(&session.messages[0]), "system policy");
        assert_eq!(extract_text(&session.messages[1]), "new question");
        assert_eq!(extract_text(&session.messages[2]), "new answer");
    }

    fn tool_call_msg(id: &str, name: &str) -> Message {
        Message {
            role: MessageRole::Assistant,
            blocks: vec![ContentBlock::ToolCall {
                id: id.into(),
                name: name.into(),
                input: "{}".into(),
            }],
        }
    }

    fn tool_result_msg(id: &str, output: &str) -> Message {
        Message {
            role: MessageRole::Tool,
            blocks: vec![ContentBlock::ToolResult {
                tool_call_id: id.into(),
                output: output.into(),
                is_error: false,
            }],
        }
    }

    fn extract_text(msg: &Message) -> &str {
        match &msg.blocks[0] {
            ContentBlock::Text { text } => text,
            _ => "",
        }
    }
}
