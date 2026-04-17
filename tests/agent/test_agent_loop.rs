use candle_cli::agent::r#loop::run_single_turn;
use candle_cli::model::mock::MockRuntime;
use candle_cli::session::model::Session;
use candle_cli::tools::registry::ToolRegistry;

#[test]
fn agent_loop_returns_final_text() {
    let mut session = Session::new("/tmp/workspace".into());
    let mut runtime = MockRuntime;
    let tools = ToolRegistry::default_read_only();
    let result = run_single_turn(&mut session, &mut runtime, &tools, "sys").unwrap();
    assert!(!result.final_text.is_empty());
}
