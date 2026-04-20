use candle_cli::model::bridge::LocalBridgeRuntime;
use candle_cli::model::runtime::CandleTargetRuntime;

#[test]
fn bridge_runtime_reports_health_with_worker_command() {
    let runtime = LocalBridgeRuntime::new("python3 python/bridge_worker.py".into());
    let health = runtime.healthcheck();
    assert!(health.ok);
    assert!(health.message.contains("python3"));
}
