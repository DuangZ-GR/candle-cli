use candle_cli::cli::args::{Cli, CommandMode, MigrateCommand, ScanOutputFormat};
use clap::Parser;

#[test]
fn parses_prompt_mode() {
    let cli = Cli::parse_from(["candle-cli", "prompt", "hello"]);
    assert!(matches!(cli.command, Some(CommandMode::Prompt { .. })));
}

#[test]
fn parses_resume_flag() {
    let cli = Cli::parse_from(["candle-cli", "--resume"]);
    assert!(cli.resume);
}

#[test]
fn parses_migrate_scan_mode() {
    let cli = Cli::parse_from([
        "candle-cli",
        "migrate",
        "scan",
        "project",
        "--pretty",
        "--max-file-bytes",
        "4096",
    ]);

    match cli.command {
        Some(CommandMode::Migrate {
            command: MigrateCommand::Scan(arguments),
        }) => {
            assert_eq!(arguments.path.to_string_lossy(), "project");
            assert!(arguments.pretty);
            assert_eq!(arguments.max_file_bytes, 4096);
            assert_eq!(arguments.format, ScanOutputFormat::Json);
        }
        other => panic!("unexpected command: {other:?}"),
    }
}

#[test]
fn parses_migrate_map_mode() {
    let cli = Cli::parse_from(["candle-cli", "migrate", "map", "torch.sum", "--pretty"]);

    match cli.command {
        Some(CommandMode::Migrate {
            command: MigrateCommand::Map(arguments),
        }) => {
            assert_eq!(arguments.api, "torch.sum");
            assert!(arguments.pretty);
        }
        other => panic!("unexpected command: {other:?}"),
    }
}
