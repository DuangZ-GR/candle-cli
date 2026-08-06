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
fn parses_security_harness_mode() {
    let cli = Cli::parse_from(["candle-cli", "security-harness"]);
    assert!(matches!(cli.command, Some(CommandMode::SecurityHarness)));
}

#[test]
fn parses_context_harness_mode() {
    let cli = Cli::parse_from(["candle-cli", "context-harness"]);
    assert!(matches!(cli.command, Some(CommandMode::ContextHarness)));
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
fn parses_migrate_run_mode() {
    let cli = Cli::parse_from([
        "candle-cli",
        "migrate",
        "run",
        "project",
        "--apply",
        "--validate-program",
        "python",
        "--validate-arg=-m",
        "--validate-arg=pytest",
        "--source-trace",
        "torch.jsonl",
        "--target-trace",
        "mindspore.jsonl",
    ]);

    match cli.command {
        Some(CommandMode::Migrate {
            command: MigrateCommand::Run(arguments),
        }) => {
            assert_eq!(arguments.path.to_string_lossy(), "project");
            assert!(arguments.apply);
            assert_eq!(arguments.validate_program.as_deref(), Some("python"));
            assert_eq!(arguments.validate_args, ["-m", "pytest"]);
            assert_eq!(
                arguments.source_trace.unwrap().to_string_lossy(),
                "torch.jsonl"
            );
            assert_eq!(
                arguments.target_trace.unwrap().to_string_lossy(),
                "mindspore.jsonl"
            );
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

#[test]
fn parses_migrate_compare_mode() {
    let cli = Cli::parse_from([
        "candle-cli",
        "migrate",
        "compare",
        "torch.jsonl",
        "mindspore.jsonl",
        "--relative-tolerance",
        "0.001",
    ]);

    match cli.command {
        Some(CommandMode::Migrate {
            command: MigrateCommand::Compare(arguments),
        }) => {
            assert_eq!(arguments.source_trace.to_string_lossy(), "torch.jsonl");
            assert_eq!(arguments.target_trace.to_string_lossy(), "mindspore.jsonl");
            assert_eq!(arguments.relative_tolerance, 0.001);
        }
        other => panic!("unexpected command: {other:?}"),
    }
}

#[test]
fn parses_migrate_import_msprobe_mode() {
    let cli = Cli::parse_from([
        "candle-cli",
        "migrate",
        "import-msprobe",
        "dump.json",
        "trace.jsonl",
        "--framework",
        "mindspore",
        "--framework-version",
        "2.9.0",
        "--run-id",
        "run-1",
    ]);

    match cli.command {
        Some(CommandMode::Migrate {
            command: MigrateCommand::ImportMsprobe(arguments),
        }) => {
            assert_eq!(arguments.dump_path.to_string_lossy(), "dump.json");
            assert_eq!(arguments.output_path.to_string_lossy(), "trace.jsonl");
            assert_eq!(arguments.framework, "mindspore");
            assert_eq!(arguments.framework_version, "2.9.0");
            assert_eq!(arguments.run_id.as_deref(), Some("run-1"));
        }
        other => panic!("unexpected command: {other:?}"),
    }
}

#[test]
fn parses_migrate_rewrite_and_rollback_modes() {
    let rewrite = Cli::parse_from([
        "candle-cli",
        "migrate",
        "rewrite",
        "project",
        "--include-differences",
        "--apply",
        "--validate-program",
        "python",
        "--validate-arg=-m",
        "--validate-arg",
        "pytest",
    ]);
    match rewrite.command {
        Some(CommandMode::Migrate {
            command: MigrateCommand::Rewrite(arguments),
        }) => {
            assert_eq!(arguments.path.to_string_lossy(), "project");
            assert!(arguments.include_differences);
            assert!(arguments.apply);
            assert_eq!(arguments.validate_program.as_deref(), Some("python"));
            assert_eq!(arguments.validate_args, ["-m", "pytest"]);
        }
        other => panic!("unexpected command: {other:?}"),
    }

    let rollback = Cli::parse_from([
        "candle-cli",
        "migrate",
        "rollback",
        "manifest.json",
        "--force",
    ]);
    match rollback.command {
        Some(CommandMode::Migrate {
            command: MigrateCommand::Rollback(arguments),
        }) => {
            assert_eq!(arguments.manifest.to_string_lossy(), "manifest.json");
            assert!(arguments.force);
        }
        other => panic!("unexpected command: {other:?}"),
    }
}
