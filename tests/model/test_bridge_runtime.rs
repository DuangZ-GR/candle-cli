use candle_cli::model::bridge::LocalBridgeRuntime;
use candle_cli::model::runtime::CandleTargetRuntime;

#[test]
fn bridge_runtime_reports_health() {
    let runtime = LocalBridgeRuntime::new("python3".into());
    assert!(runtime.healthcheck().ok);
}
