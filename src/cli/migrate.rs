use crate::cli::args::{MigrateCommand, ScanArgs, ScanOutputFormat};
use crate::migration::ScanReport;
use std::ffi::OsString;
use std::io::{Error, ErrorKind, Result, Write};
use std::path::{Path, PathBuf};
use std::process::{Command, Output};

pub fn run_migrate(command: MigrateCommand) -> Result<()> {
    match command {
        MigrateCommand::Scan(arguments) => run_scan(arguments),
    }
}

fn run_scan(arguments: ScanArgs) -> Result<()> {
    if arguments.output.as_deref().is_some_and(Path::exists) && !arguments.force {
        return Err(Error::new(
            ErrorKind::AlreadyExists,
            "output file already exists; pass --force to replace it",
        ));
    }

    let output = execute_scanner(&arguments)?;
    if output.stdout.is_empty() {
        let message = String::from_utf8_lossy(&output.stderr).trim().to_string();
        return Err(Error::other(if message.is_empty() {
            "migration scanner produced no JSON output".to_string()
        } else {
            message
        }));
    }

    let report: ScanReport = serde_json::from_slice(&output.stdout).map_err(|error| {
        Error::new(
            ErrorKind::InvalidData,
            format!("migration scanner returned invalid JSON: {error}"),
        )
    })?;
    report.validate().map_err(|error| {
        Error::new(
            ErrorKind::InvalidData,
            format!("migration scanner returned an invalid report: {error}"),
        )
    })?;

    let rendered = match arguments.format {
        ScanOutputFormat::Json => output.stdout,
        ScanOutputFormat::Markdown => render_markdown(&report).into_bytes(),
    };
    write_report(arguments.output.as_deref(), &rendered)?;

    if !output.status.success() {
        let issue_count = report.summary.issue_count;
        return Err(Error::other(format!(
            "scan completed with {issue_count} issue(s); the partial report was preserved"
        )));
    }
    Ok(())
}

fn render_markdown(report: &ScanReport) -> String {
    let mut lines = vec![
        "# Torch2MindSpore Scan Report".to_string(),
        String::new(),
        format!("- Schema: `{}`", escape_markdown(&report.schema_version)),
        format!("- Python files discovered: {}", report.files_discovered),
        format!("- Python files scanned: {}", report.files_scanned),
        format!("- Findings: {}", report.summary.finding_count),
        format!("- Unique APIs: {}", report.summary.unique_api_count),
        format!("- Issues: {}", report.summary.issue_count),
        String::new(),
        "## Findings".to_string(),
        String::new(),
    ];
    if report.findings.is_empty() {
        lines.push("No PyTorch API calls were detected.".to_string());
    } else {
        lines.push("| ID | Location | API | Kind | Confidence | Risk | Expression |".to_string());
        lines.push("| --- | --- | --- | --- | ---: | --- | --- |".to_string());
        for finding in &report.findings {
            lines.push(format!(
                "| `{}` | `{}:{}:{}` | `{}` | `{}` | {:.2} | `{}` | `{}` |",
                escape_markdown(&finding.finding_id),
                escape_markdown(&finding.location.file),
                finding.location.line,
                finding.location.column,
                escape_markdown(&finding.api),
                finding.call_kind.as_str(),
                finding.confidence,
                finding.risk_level.as_str(),
                escape_markdown(&finding.expression),
            ));
        }
    }
    lines.extend([String::new(), "## Scan Issues".to_string(), String::new()]);
    if report.issues.is_empty() {
        lines.push("No scan issues were reported.".to_string());
    } else {
        lines.push("| File | Kind | Location | Message |".to_string());
        lines.push("| --- | --- | --- | --- |".to_string());
        for issue in &report.issues {
            let location = issue
                .line
                .map(|line| match issue.column {
                    Some(column) => format!("{line}:{column}"),
                    None => line.to_string(),
                })
                .unwrap_or_else(|| "-".to_string());
            lines.push(format!(
                "| `{}` | `{}` | `{}` | {} |",
                escape_markdown(&issue.file),
                escape_markdown(&issue.kind),
                location,
                escape_markdown(&issue.message),
            ));
        }
    }
    lines.push(String::new());
    lines.join("\n")
}

fn escape_markdown(value: &str) -> String {
    value
        .replace('\\', "\\\\")
        .replace('|', "\\|")
        .replace(['\r', '\n'], " ")
        .replace('`', "\\`")
}

fn execute_scanner(arguments: &ScanArgs) -> Result<Output> {
    let python = std::env::var("CANDLE_CLI_PYTHON").unwrap_or_else(|_| {
        if cfg!(windows) {
            "python".to_string()
        } else {
            "python3".to_string()
        }
    });
    let python_root = std::env::var_os("CANDLE_CLI_PYTHON_ROOT")
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("python"));
    let python_path = prepend_python_path(&python_root)?;

    let mut command = Command::new(python);
    command
        .args(["-m", "migration.scanner"])
        .arg(&arguments.path)
        .arg("--max-file-bytes")
        .arg(arguments.max_file_bytes.to_string())
        .env("PYTHONPATH", python_path)
        .env("PYTHONUTF8", "1")
        .env("PYTHONIOENCODING", "utf-8");
    if arguments.pretty {
        command.arg("--pretty");
    }
    command.output().map_err(|error| {
        Error::new(
            error.kind(),
            format!("failed to start migration scanner: {error}"),
        )
    })
}

fn prepend_python_path(python_root: &Path) -> Result<OsString> {
    let mut paths = vec![python_root.to_path_buf()];
    if let Some(existing) = std::env::var_os("PYTHONPATH") {
        paths.extend(std::env::split_paths(&existing));
    }
    std::env::join_paths(paths).map_err(|error| {
        Error::new(
            ErrorKind::InvalidInput,
            format!("failed to construct PYTHONPATH: {error}"),
        )
    })
}

fn write_report(path: Option<&Path>, contents: &[u8]) -> Result<()> {
    if let Some(path) = path {
        if let Some(parent) = path.parent() {
            if !parent.as_os_str().is_empty() {
                std::fs::create_dir_all(parent)?;
            }
        }
        std::fs::write(path, contents)
    } else {
        let mut stdout = std::io::stdout().lock();
        stdout.write_all(contents)?;
        if !contents.ends_with(b"\n") {
            stdout.write_all(b"\n")?;
        }
        stdout.flush()
    }
}
