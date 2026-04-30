use crate::session::model::{MessageRole, Session};

/// Trim conversation to fit within `max_turns` user-assistant pairs,
/// keeping system messages and tool results near the end.
pub fn compact_session(session: &mut Session, max_turns: usize) {
    if max_turns == 0 {
        return;
    }

    // count user messages (one user message ≈ one turn)
    let user_count = session
        .messages
        .iter()
        .filter(|m| m.role == MessageRole::User)
        .count();

    if user_count <= max_turns {
        return;
    }

    let remove_count = user_count - max_turns;
    let mut removed = 0usize;

    // Remove oldest user and the assistant response that follows each.
    // Also remove any tool results that are tied to those old turns.
    let mut i = 0;
    while i < session.messages.len() && removed < remove_count {
        if session.messages[i].role == MessageRole::User {
            // remove this user message
            session.messages.remove(i);
            removed += 1;

            // remove the assistant response right after it (if any)
            if i < session.messages.len() && session.messages[i].role == MessageRole::Assistant {
                session.messages.remove(i);
            }
            // also remove any tool results that immediately follow
            while i < session.messages.len() && session.messages[i].role == MessageRole::Tool {
                session.messages.remove(i);
            }
        } else {
            i += 1;
        }
    }
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
        // 4 turns: user1-assistant1, user2-assistant2, user3-assistant3, user4-assistant4
        for i in 1..=4 {
            session
                .messages
                .push(text_msg(MessageRole::User, &format!("u{i}")));
            session
                .messages
                .push(text_msg(MessageRole::Assistant, &format!("a{i}")));
        }

        compact_session(&mut session, 2);

        // should keep the last 2 turns
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

    fn extract_text(msg: &Message) -> &str {
        match &msg.blocks[0] {
            ContentBlock::Text { text } => text,
            _ => "",
        }
    }
}
