use candle_cli::context::builder::build_turn_request;
use candle_cli::session::model::Session;

#[test]
fn builds_turn_request_from_session() {
    let mut session = Session::new("/tmp/workspace".into());
    let req = build_turn_request(&mut session, "[]").unwrap();
    assert!(!req.system_prompt.is_empty());
    assert!(!req.messages_json.is_empty());
}
