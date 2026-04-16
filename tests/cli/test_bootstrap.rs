use assert_cmd::Command;

#[test]
fn binary_starts_and_shows_help() {
    let mut cmd = Command::cargo_bin("candle-cli").unwrap();
    cmd.arg("--help");
    cmd.assert().success();
}
