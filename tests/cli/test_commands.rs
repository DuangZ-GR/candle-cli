use candle_cli::cli::commands::parse_slash_command;

#[test]
fn parses_help_command() {
    let parsed = parse_slash_command("/help");
    assert_eq!(parsed.as_deref(), Some("help"));
}
