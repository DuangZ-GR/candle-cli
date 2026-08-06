use crate::cli::args::{
    CompareArgs, ImportMsprobeArgs, MapArgs, MigrateCommand, RewriteArgs, RollbackArgs, RunArgs,
    ScanArgs, ScanOutputFormat,
};
use crate::migration::{
    MappingResolution, MigrationRunReport, MsprobeImportReport, RewriteApplyReport,
    RewritePlanReport, RewriteRollbackReport, ScanReport, TraceComparisonResult,
};
use std::ffi::OsString;
use std::io::{Error, ErrorKind, Result, Write};
use std::path::{Path, PathBuf};
use std::process::{Command, Output};

pub fn run_migrate(command: MigrateCommand) -> Result<()> {
    match command {
        MigrateCommand::Run(arguments) => run_workflow(arguments),
        MigrateCommand::Scan(arguments) => run_scan(arguments),
        MigrateCommand::Map(arguments) => run_map(arguments),
        MigrateCommand::Compare(arguments) => run_compare(arguments),
        MigrateCommand::ImportMsprobe(arguments) => run_import_msprobe(arguments),
        MigrateCommand::Rewrite(arguments) => run_rewrite(arguments),
        MigrateCommand::Rollback(arguments) => run_rollback(arguments),
    }
}

fn run_workflow(arguments: RunArgs) -> Result<()> {
    if arguments.apply
        && arguments.validate_program.is_none()
        && arguments.runtime_manifest.is_none()
    {
        return Err(Error::new(
            ErrorKind::InvalidInput,
            "--apply requires --validate-program or --runtime-manifest",
        ));
    }
    if !arguments.apply
        && (arguments.validate_program.is_some() || !arguments.validate_args.is_empty())
    {
        return Err(Error::new(
            ErrorKind::InvalidInput,
            "validation arguments require --apply",
        ));
    }
    if arguments.validate_program.is_none() && !arguments.validate_args.is_empty() {
        return Err(Error::new(
            ErrorKind::InvalidInput,
            "--validate-arg requires --validate-program",
        ));
    }
    if arguments.source_trace.is_some() != arguments.target_trace.is_some() {
        return Err(Error::new(
            ErrorKind::InvalidInput,
            "--source-trace and --target-trace must be provided together",
        ));
    }
    if arguments.runtime_manifest.is_some()
        && (arguments.source_trace.is_some() || arguments.validate_program.is_some())
    {
        return Err(Error::new(
            ErrorKind::InvalidInput,
            "--runtime-manifest cannot be combined with explicit traces or validation",
        ));
    }
    if arguments.output.as_deref().is_some_and(Path::exists) && !arguments.force {
        return Err(Error::new(
            ErrorKind::AlreadyExists,
            "output file already exists; pass --force to replace it",
        ));
    }

    let python_root = python_root();
    let mut command = python_command(&python_root)?;
    command
        .args(["-m", "migration.workflow"])
        .arg(&arguments.path)
        .arg("--max-file-bytes")
        .arg(arguments.max_file_bytes.to_string())
        .arg("--validation-timeout")
        .arg(arguments.validation_timeout.to_string())
        .arg("--relative-tolerance")
        .arg(arguments.relative_tolerance.to_string())
        .arg("--absolute-tolerance")
        .arg(arguments.absolute_tolerance.to_string());
    if let Some(path) = &arguments.knowledge_base {
        command.arg("--knowledge-base").arg(path);
    }
    if arguments.include_differences {
        command.arg("--include-differences");
    }
    if arguments.apply {
        command.arg("--apply");
    }
    if arguments.allow_partial {
        command.arg("--allow-partial");
    }
    if arguments.pretty {
        command.arg("--pretty");
    }
    if let (Some(source), Some(target)) = (&arguments.source_trace, &arguments.target_trace) {
        command
            .arg("--source-trace")
            .arg(source)
            .arg("--target-trace")
            .arg(target);
    }
    if let Some(manifest) = &arguments.runtime_manifest {
        command.arg("--runtime-manifest").arg(manifest);
    }
    if let Some(report) = &arguments.data_pipeline_report {
        command.arg("--data-pipeline-report").arg(report);
    }
    if let Some(program) = &arguments.validate_program {
        command.arg("--validate-command").arg(program);
        command.args(&arguments.validate_args);
    }
    let output = command.output().map_err(|error| {
        Error::new(
            error.kind(),
            format!("failed to start migration workflow: {error}"),
        )
    })?;
    if output.stdout.is_empty() {
        let message = String::from_utf8_lossy(&output.stderr).trim().to_string();
        return Err(Error::other(if message.is_empty() {
            "migration workflow produced no JSON output".to_string()
        } else {
            message
        }));
    }
    let report: MigrationRunReport = serde_json::from_slice(&output.stdout).map_err(|error| {
        Error::new(
            ErrorKind::InvalidData,
            format!("migration workflow returned invalid JSON: {error}"),
        )
    })?;
    report.validate().map_err(|error| {
        Error::new(
            ErrorKind::InvalidData,
            format!("migration workflow returned an invalid report: {error}"),
        )
    })?;
    let rendered = match arguments.format {
        ScanOutputFormat::Json => output.stdout,
        ScanOutputFormat::Markdown => render_workflow_markdown(&report).into_bytes(),
    };
    write_report(arguments.output.as_deref(), &rendered)?;
    if !output.status.success() {
        return Err(Error::other(format!(
            "migration workflow ended with status {}",
            report.status
        )));
    }
    Ok(())
}

fn render_workflow_markdown(report: &MigrationRunReport) -> String {
    let trace_equivalent = match report.summary.trace_equivalent {
        Some(value) => value.to_string(),
        None => "not_run".to_string(),
    };
    let mut lines = vec![
        "# Torch2MindSpore Migration Run".to_string(),
        String::new(),
        format!("- Run ID: `{}`", escape_markdown(&report.run_id)),
        format!("- Mode: `{}`", escape_markdown(&report.mode_name)),
        format!("- Status: `{}`", escape_markdown(&report.status)),
        format!("- Verified: `{}`", report.verified),
        format!("- Duration: `{:.3} ms`", report.duration_ms),
        String::new(),
        "## Summary".to_string(),
        String::new(),
        format!(
            "- Files scanned: {}/{}",
            report.summary.files_scanned, report.summary.files_discovered
        ),
        format!("- Findings: {}", report.summary.finding_count),
        format!(
            "- Rewrite edits: {} in {} file(s)",
            report.summary.edit_count, report.summary.files_changed
        ),
        format!(
            "- Validation: `{}`",
            escape_markdown(&report.summary.validation_status)
        ),
        format!("- Trace equivalent: `{trace_equivalent}`"),
        format!(
            "- First divergence: `{}`",
            report
                .summary
                .first_divergence_category
                .as_deref()
                .unwrap_or("none")
        ),
    ];
    if let Some(runtime) = &report.summary.runtime_collection {
        let patch_adoption = runtime
            .patch_adoption_rate
            .map(|value| value.to_string())
            .unwrap_or_else(|| "not_applicable".to_string());
        let trace_rate = runtime
            .trace_equivalence_rate
            .map(|value| value.to_string())
            .unwrap_or_else(|| "not_run".to_string());
        let rollback_succeeded = runtime
            .rollback_succeeded
            .map(|value| value.to_string())
            .unwrap_or_else(|| "not_run".to_string());
        lines.extend([
            String::new(),
            "## Dual-runtime collection".to_string(),
            String::new(),
            format!("- Manifest: `{}`", escape_markdown(&runtime.manifest_id)),
            format!(
                "- Source files/lines: `{}/{}`",
                runtime.source_file_count, runtime.source_line_count
            ),
            format!(
                "- Mapping coverage: `{:.2}%`",
                runtime.mapping_coverage * 100.0
            ),
            format!("- Unknown APIs: `{}`", runtime.unknown_api_count),
            format!(
                "- Automatic/manual patches: `{}/{}`",
                runtime.automatic_patch_count, runtime.manual_patch_count
            ),
            format!("- Patch adoption rate: `{patch_adoption}`"),
            format!(
                "- Source/target runtime: `{}/{}`",
                escape_markdown(&runtime.source_status),
                escape_markdown(&runtime.target_status)
            ),
            format!(
                "- Source/target trace calls: `{}/{}`",
                runtime.source_trace_calls, runtime.target_trace_calls
            ),
            format!("- Trace equivalence rate: `{trace_rate}`"),
            format!(
                "- Rollback performed/succeeded: `{}/{rollback_succeeded}`",
                runtime.rollback_performed
            ),
        ]);
    }
    if let Some(pipeline) = &report.summary.data_pipeline {
        lines.extend([
            String::new(),
            "## Data pipeline and randomness".to_string(),
            String::new(),
            format!(
                "- Benchmark: `{}`",
                escape_markdown(&pipeline.benchmark_version)
            ),
            format!(
                "- Complete/passed: `{}/{}`",
                pipeline.complete, pipeline.passed
            ),
            format!(
                "- Cases/faults/stochastic: `{}/{}/{}`",
                pipeline.case_count, pipeline.fault_case_count, pipeline.stochastic_case_count
            ),
            format!(
                "- Classification accuracy: `{:.2}%`",
                pipeline.classification_accuracy * 100.0
            ),
            format!(
                "- First-divergence Top-1: `{:.2}%`",
                pipeline.first_divergence_top1_accuracy * 100.0
            ),
            format!(
                "- Deterministic/statistical equivalence: `{:.2}%/{:.2}%`",
                pipeline.deterministic_equivalence_rate * 100.0,
                pipeline.statistical_equivalence_rate * 100.0
            ),
            format!(
                "- Minimum stochastic sample size: `{}`",
                pipeline.minimum_stochastic_sample_size
            ),
        ]);
    }
    lines.extend([
        String::new(),
        "## Steps".to_string(),
        String::new(),
        "| Step | Status | Duration (ms) |".to_string(),
        "| --- | --- | ---: |".to_string(),
    ]);
    for step in &report.steps {
        lines.push(format!(
            "| `{}` | `{}` | {:.3} |",
            escape_markdown(&step.name),
            escape_markdown(&step.status),
            step.duration_ms
        ));
    }
    if let Some(error) = &report.error {
        lines.extend([
            String::new(),
            "## Error".to_string(),
            String::new(),
            format!("- Stage: `{}`", escape_markdown(&error.stage)),
            format!("- Type: `{}`", escape_markdown(&error.error_type)),
            format!("- Message: {}", escape_markdown(&error.message)),
        ]);
    }
    lines.push(String::new());
    lines.join("\n")
}

fn run_rewrite(arguments: RewriteArgs) -> Result<()> {
    if arguments.validate_program.is_none() && !arguments.validate_args.is_empty() {
        return Err(Error::new(
            ErrorKind::InvalidInput,
            "--validate-arg requires --validate-program",
        ));
    }
    let python_root = python_root();
    let mut command = python_command(&python_root)?;
    command
        .args(["-m", "migration.rewriter", "plan"])
        .arg(&arguments.path)
        .arg("--max-file-bytes")
        .arg(arguments.max_file_bytes.to_string())
        .arg("--validation-timeout")
        .arg(arguments.validation_timeout.to_string());
    if let Some(path) = &arguments.knowledge_base {
        command.arg("--knowledge-base").arg(path);
    }
    if arguments.include_differences {
        command.arg("--include-differences");
    }
    if arguments.apply {
        command.arg("--apply");
    }
    if arguments.allow_partial {
        command.arg("--allow-partial");
    }
    if arguments.pretty {
        command.arg("--pretty");
    }
    if let Some(program) = &arguments.validate_program {
        command.arg("--validate-command").arg(program);
        command.args(&arguments.validate_args);
    }
    let output = command.output().map_err(|error| {
        Error::new(
            error.kind(),
            format!("failed to start deterministic rewrite: {error}"),
        )
    })?;
    if !output.status.success() {
        return Err(Error::other(
            String::from_utf8_lossy(&output.stderr).trim().to_string(),
        ));
    }
    if arguments.apply {
        let report: RewriteApplyReport =
            serde_json::from_slice(&output.stdout).map_err(|error| {
                Error::new(
                    ErrorKind::InvalidData,
                    format!("rewrite apply returned invalid JSON: {error}"),
                )
            })?;
        report.validate().map_err(|error| {
            Error::new(
                ErrorKind::InvalidData,
                format!("rewrite apply returned an invalid report: {error}"),
            )
        })?;
    } else {
        let report: RewritePlanReport =
            serde_json::from_slice(&output.stdout).map_err(|error| {
                Error::new(
                    ErrorKind::InvalidData,
                    format!("rewrite preview returned invalid JSON: {error}"),
                )
            })?;
        report.validate().map_err(|error| {
            Error::new(
                ErrorKind::InvalidData,
                format!("rewrite preview returned an invalid report: {error}"),
            )
        })?;
    }
    write_report(None, &output.stdout)
}

fn run_rollback(arguments: RollbackArgs) -> Result<()> {
    let python_root = python_root();
    let mut command = python_command(&python_root)?;
    command
        .args(["-m", "migration.rewriter", "rollback"])
        .arg(&arguments.manifest);
    if arguments.force {
        command.arg("--force");
    }
    if arguments.pretty {
        command.arg("--pretty");
    }
    let output = command
        .output()
        .map_err(|error| Error::new(error.kind(), format!("failed to start rollback: {error}")))?;
    if !output.status.success() {
        return Err(Error::other(
            String::from_utf8_lossy(&output.stderr).trim().to_string(),
        ));
    }
    let report: RewriteRollbackReport =
        serde_json::from_slice(&output.stdout).map_err(|error| {
            Error::new(
                ErrorKind::InvalidData,
                format!("rewrite rollback returned invalid JSON: {error}"),
            )
        })?;
    report.validate().map_err(|error| {
        Error::new(
            ErrorKind::InvalidData,
            format!("rewrite rollback returned an invalid report: {error}"),
        )
    })?;
    write_report(None, &output.stdout)
}

fn run_import_msprobe(arguments: ImportMsprobeArgs) -> Result<()> {
    if arguments.output_path.exists() && !arguments.force {
        return Err(Error::new(
            ErrorKind::AlreadyExists,
            "output trace already exists; pass --force to replace it",
        ));
    }
    let python_root = python_root();
    let mut command = python_command(&python_root)?;
    command
        .args(["-m", "migration.msprobe_import"])
        .arg(&arguments.dump_path)
        .arg(&arguments.output_path)
        .arg("--framework")
        .arg(&arguments.framework)
        .arg("--framework-version")
        .arg(&arguments.framework_version);
    if let Some(run_id) = &arguments.run_id {
        command.arg("--run-id").arg(run_id);
    }
    if arguments.force {
        command.arg("--force");
    }
    if arguments.pretty {
        command.arg("--pretty");
    }
    let output = command.output().map_err(|error| {
        Error::new(
            error.kind(),
            format!("failed to start msprobe import: {error}"),
        )
    })?;
    if !output.status.success() {
        return Err(Error::other(
            String::from_utf8_lossy(&output.stderr).trim().to_string(),
        ));
    }
    let report: MsprobeImportReport = serde_json::from_slice(&output.stdout).map_err(|error| {
        Error::new(
            ErrorKind::InvalidData,
            format!("msprobe import returned invalid JSON: {error}"),
        )
    })?;
    report.validate().map_err(|error| {
        Error::new(
            ErrorKind::InvalidData,
            format!("msprobe import returned an invalid report: {error}"),
        )
    })?;
    write_report(None, &output.stdout)
}

fn run_compare(arguments: CompareArgs) -> Result<()> {
    let python_root = python_root();
    let mut command = python_command(&python_root)?;
    command
        .args(["-m", "migration.trace_compare"])
        .arg(&arguments.source_trace)
        .arg(&arguments.target_trace)
        .arg("--relative-tolerance")
        .arg(arguments.relative_tolerance.to_string())
        .arg("--absolute-tolerance")
        .arg(arguments.absolute_tolerance.to_string());
    if arguments.pretty {
        command.arg("--pretty");
    }
    if let Some(path) = &arguments.knowledge_base {
        command.arg("--knowledge-base").arg(path);
    }
    let output = command.output().map_err(|error| {
        Error::new(
            error.kind(),
            format!("failed to start trace comparison: {error}"),
        )
    })?;
    if !output.status.success() {
        return Err(Error::other(
            String::from_utf8_lossy(&output.stderr).trim().to_string(),
        ));
    }
    let result: TraceComparisonResult =
        serde_json::from_slice(&output.stdout).map_err(|error| {
            Error::new(
                ErrorKind::InvalidData,
                format!("trace comparison returned invalid JSON: {error}"),
            )
        })?;
    result.validate().map_err(|error| {
        Error::new(
            ErrorKind::InvalidData,
            format!("trace comparison returned an invalid result: {error}"),
        )
    })?;
    write_report(None, &output.stdout)
}

fn run_map(arguments: MapArgs) -> Result<()> {
    let python_root = python_root();
    let mut command = python_command(&python_root)?;
    command
        .args(["-m", "migration.mapping"])
        .arg(&arguments.api);
    if arguments.pretty {
        command.arg("--pretty");
    }
    if let Some(path) = &arguments.knowledge_base {
        command.arg("--knowledge-base").arg(path);
    }
    let output = command.output().map_err(|error| {
        Error::new(
            error.kind(),
            format!("failed to start mapping query: {error}"),
        )
    })?;
    if !output.status.success() {
        return Err(Error::other(
            String::from_utf8_lossy(&output.stderr).trim().to_string(),
        ));
    }
    let resolution: MappingResolution =
        serde_json::from_slice(&output.stdout).map_err(|error| {
            Error::new(
                ErrorKind::InvalidData,
                format!("mapping query returned invalid JSON: {error}"),
            )
        })?;
    resolution.validate().map_err(|error| {
        Error::new(
            ErrorKind::InvalidData,
            format!("mapping query returned an invalid result: {error}"),
        )
    })?;
    write_report(None, &output.stdout)
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
        format!("- Mapping status: {:?}", report.summary.mapping_counts),
        format!("- Issues: {}", report.summary.issue_count),
        String::new(),
        "## Findings".to_string(),
        String::new(),
    ];
    if report.findings.is_empty() {
        lines.push("No PyTorch API calls were detected.".to_string());
    } else {
        lines.push("| ID | Location | PyTorch API | MindSpore API | Mapping | Confidence | Risk | Expression |".to_string());
        lines.push("| --- | --- | --- | --- | --- | ---: | --- | --- |".to_string());
        for finding in &report.findings {
            lines.push(format!(
                "| `{}` | `{}:{}:{}` | `{}` | `{}` | `{}` | {:.2} | `{}` | `{}` |",
                escape_markdown(&finding.finding_id),
                escape_markdown(&finding.location.file),
                finding.location.line,
                finding.location.column,
                escape_markdown(&finding.api),
                escape_markdown(finding.mapping.target_api.as_deref().unwrap_or("-")),
                finding.mapping.status.as_str(),
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
    let python_root = python_root();
    let mut command = python_command(&python_root)?;
    command
        .args(["-m", "migration.scanner"])
        .arg(&arguments.path)
        .arg("--max-file-bytes")
        .arg(arguments.max_file_bytes.to_string());
    if arguments.pretty {
        command.arg("--pretty");
    }
    if let Some(path) = &arguments.knowledge_base {
        command.arg("--knowledge-base").arg(path);
    }
    command.output().map_err(|error| {
        Error::new(
            error.kind(),
            format!("failed to start migration scanner: {error}"),
        )
    })
}

fn python_root() -> PathBuf {
    std::env::var_os("CANDLE_CLI_PYTHON_ROOT")
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("python"))
}

fn python_command(python_root: &Path) -> Result<Command> {
    let python = std::env::var("CANDLE_CLI_PYTHON").unwrap_or_else(|_| {
        if cfg!(windows) {
            "python".to_string()
        } else {
            "python3".to_string()
        }
    });
    let python_path = prepend_python_path(python_root)?;

    let mut command = Command::new(python);
    command
        .env("PYTHONPATH", python_path)
        .env("PYTHONUTF8", "1")
        .env("PYTHONIOENCODING", "utf-8");
    Ok(command)
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
