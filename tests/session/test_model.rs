use candle_cli::session::model::Session;

#[test]
fn session_holds_user_message() {
    let session = Session::new("/tmp/workspace".into());
    assert_eq!(session.workspace_root, "/tmp/workspace");
    assert!(session.messages.is_empty());
}

#[test]
fn session_ids_are_unique_for_back_to_back_sessions() {
    let first = Session::new("/tmp/workspace".into());
    let second = Session::new("/tmp/workspace".into());
    assert_ne!(first.session_id, second.session_id);
}
