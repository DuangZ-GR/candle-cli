use clap::{Args, Parser, Subcommand, ValueEnum};
use std::path::PathBuf;

#[derive(Parser, Debug)]
#[command(name = "candle-cli")]
pub struct Cli {
    #[arg(long)]
    pub resume: bool,
    #[command(subcommand)]
    pub command: Option<CommandMode>,
}

#[derive(Subcommand, Debug)]
pub enum CommandMode {
    Prompt {
        input: String,
    },
    Harness,
    SecurityHarness,
    ContextHarness,
    Doctor,
    Migrate {
        #[command(subcommand)]
        command: MigrateCommand,
    },
}

#[derive(Subcommand, Debug)]
pub enum MigrateCommand {
    Run(RunArgs),
    Scan(ScanArgs),
    Map(MapArgs),
    Compare(CompareArgs),
    ImportMsprobe(ImportMsprobeArgs),
    Rewrite(RewriteArgs),
    Rollback(RollbackArgs),
}

#[derive(Args, Debug)]
pub struct RunArgs {
    pub path: PathBuf,
    #[arg(long)]
    pub output: Option<PathBuf>,
    #[arg(long, value_enum, default_value = "json")]
    pub format: ScanOutputFormat,
    #[arg(long)]
    pub force: bool,
    #[arg(long)]
    pub knowledge_base: Option<PathBuf>,
    #[arg(long, default_value_t = 2 * 1024 * 1024)]
    pub max_file_bytes: u64,
    #[arg(long)]
    pub include_differences: bool,
    #[arg(long)]
    pub apply: bool,
    #[arg(long)]
    pub allow_partial: bool,
    #[arg(long)]
    pub validate_program: Option<String>,
    #[arg(long = "validate-arg", allow_hyphen_values = true)]
    pub validate_args: Vec<String>,
    #[arg(long, default_value_t = 300.0)]
    pub validation_timeout: f64,
    #[arg(long)]
    pub source_trace: Option<PathBuf>,
    #[arg(long)]
    pub target_trace: Option<PathBuf>,
    #[arg(long)]
    pub runtime_manifest: Option<PathBuf>,
    #[arg(long, default_value_t = 1e-5)]
    pub relative_tolerance: f64,
    #[arg(long, default_value_t = 1e-8)]
    pub absolute_tolerance: f64,
    #[arg(long)]
    pub pretty: bool,
}

#[derive(Args, Debug)]
pub struct MapArgs {
    pub api: String,
    #[arg(long)]
    pub knowledge_base: Option<PathBuf>,
    #[arg(long)]
    pub pretty: bool,
}

#[derive(Args, Debug)]
pub struct CompareArgs {
    pub source_trace: PathBuf,
    pub target_trace: PathBuf,
    #[arg(long)]
    pub knowledge_base: Option<PathBuf>,
    #[arg(long, default_value_t = 1e-5)]
    pub relative_tolerance: f64,
    #[arg(long, default_value_t = 1e-8)]
    pub absolute_tolerance: f64,
    #[arg(long)]
    pub pretty: bool,
}

#[derive(Args, Debug)]
pub struct ImportMsprobeArgs {
    pub dump_path: PathBuf,
    pub output_path: PathBuf,
    #[arg(long, value_parser = ["pytorch", "mindspore"])]
    pub framework: String,
    #[arg(long)]
    pub framework_version: String,
    #[arg(long)]
    pub run_id: Option<String>,
    #[arg(long)]
    pub force: bool,
    #[arg(long)]
    pub pretty: bool,
}

#[derive(Args, Debug)]
pub struct RewriteArgs {
    pub path: PathBuf,
    #[arg(long)]
    pub knowledge_base: Option<PathBuf>,
    #[arg(long, default_value_t = 2 * 1024 * 1024)]
    pub max_file_bytes: u64,
    #[arg(long)]
    pub include_differences: bool,
    #[arg(long)]
    pub apply: bool,
    #[arg(long)]
    pub allow_partial: bool,
    #[arg(long)]
    pub validate_program: Option<String>,
    #[arg(long = "validate-arg", allow_hyphen_values = true)]
    pub validate_args: Vec<String>,
    #[arg(long, default_value_t = 300.0)]
    pub validation_timeout: f64,
    #[arg(long)]
    pub pretty: bool,
}

#[derive(Args, Debug)]
pub struct RollbackArgs {
    pub manifest: PathBuf,
    #[arg(long)]
    pub force: bool,
    #[arg(long)]
    pub pretty: bool,
}

#[derive(Args, Debug)]
pub struct ScanArgs {
    pub path: PathBuf,
    #[arg(long)]
    pub output: Option<PathBuf>,
    #[arg(long)]
    pub pretty: bool,
    #[arg(long, value_enum, default_value = "json")]
    pub format: ScanOutputFormat,
    #[arg(long)]
    pub force: bool,
    #[arg(long, default_value_t = 2 * 1024 * 1024)]
    pub max_file_bytes: u64,
    #[arg(long)]
    pub knowledge_base: Option<PathBuf>,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, ValueEnum)]
pub enum ScanOutputFormat {
    Json,
    Markdown,
}
