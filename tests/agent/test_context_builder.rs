use candle_cli::context::builder::build_turn_request;
use candle_cli::session::model::Session;

#[test]
fn builds_turn_request_from_session() {
    let session = Session::new("/tmp/workspace".into());
    let req = build_turn_request(&session, "sys", "[]").unwrap();
    assert_eq!(req.system_prompt, "sys");
}
