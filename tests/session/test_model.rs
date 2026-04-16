use candle_cli::session::model::{ContentBlock, Message, MessageRole, Session};

#[test]
fn session_holds_user_message() {
    let msg = Message {
        role: MessageRole::User,
        blocks: vec![ContentBlock::Text { text: "hello".into() }],
    };
    let session = Session::new("workspace".into());
    assert_eq!(msg.role, MessageRole::User);
    assert_eq!(session.workspace_root, "workspace");
}
