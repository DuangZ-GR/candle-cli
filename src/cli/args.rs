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
    Doctor,
    Migrate {
        #[command(subcommand)]
        command: MigrateCommand,
    },
}

#[derive(Subcommand, Debug)]
pub enum MigrateCommand {
    Scan(ScanArgs),
    Map(MapArgs),
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
