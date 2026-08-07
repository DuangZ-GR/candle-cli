use serde::Serialize;
use std::env;
use std::io::{Result, Write};
use std::path::Path;
use std::process::Command;

#[derive(Debug, Serialize)]
struct DoctorCheck {
    name: &'static str,
    status: &'static str,
    required_for: &'static str,
    detail: String,
}

#[derive(Debug, Serialize)]
struct DoctorReport {
    schema_version: &'static str,
    package_version: &'static str,
    platform: String,
    runtime: String,
    ready_for_mock: bool,
    ready_for_bridge: bool,
    ready_for_dual_runtime: bool,
    checks: Vec<DoctorCheck>,
}

pub fn run_doctor(json: bool) -> Result<()> {
    let report = build_report();
    if json {
        serde_json::to_writer_pretty(std::io::stdout(), &report)?;
        std::io::stdout().write_all(b"\n")?;
    } else {
        println!("candle-cli doctor v{}", report.package_version);
        println!("platform: {}", report.platform);
        println!("runtime: {}", report.runtime);
        for check in &report.checks {
            println!(
                "[{}] {} ({}): {}",
                check.status, check.name, check.required_for, check.detail
            );
        }
        println!("ready_for_mock: {}", report.ready_for_mock);
        println!("ready_for_bridge: {}", report.ready_for_bridge);
        println!("ready_for_dual_runtime: {}", report.ready_for_dual_runtime);
    }
    Ok(())
}

fn build_report() -> DoctorReport {
    let runtime = env::var("CANDLE_CLI_RUNTIME").unwrap_or_else(|_| "mock".to_string());
    let default_python = env::var("CANDLE_CLI_PYTHON").unwrap_or_else(|_| {
        if cfg!(windows) {
            "python".to_string()
        } else {
            "python3".to_string()
        }
    });
    let rust = version_check("rust", "optional-build", "rustc", &["--version"]);
    let python = version_check(
        "python",
        "bridge-and-migration",
        &default_python,
        &["--version"],
    );
    let torch = python_package_check("pytorch", "dual-runtime-source", &default_python, "torch");
    let mindspore = python_package_check(
        "mindspore",
        "dual-runtime-target",
        &default_python,
        "mindspore",
    );
    let docker = version_check("docker", "optional-shell-sandbox", "docker", &["--version"]);
    let bridge_worker = path_check(
        "python-bridge-worker",
        "bridge",
        Path::new("python/bridge_worker.py"),
    );

    let source_python = env::var("CANDLE_CLI_PYTORCH_PYTHON").ok();
    let target_python = env::var("CANDLE_CLI_MINDSPORE_PYTHON").ok();
    let source = configured_python_check(
        "pytorch-python-env",
        "dual-runtime-source",
        source_python.as_deref(),
        "torch",
    );
    let target = configured_python_check(
        "mindspore-python-env",
        "dual-runtime-target",
        target_python.as_deref(),
        "mindspore",
    );
    let provider = DoctorCheck {
        name: "provider-config",
        status: if runtime == "bridge" && env::var_os("CANDLE_CLI_API_BASE_URL").is_none() {
            "warning"
        } else {
            "ok"
        },
        required_for: "remote-provider",
        detail: if env::var_os("CANDLE_CLI_API_BASE_URL").is_some() {
            "API base URL configured; credentials are not displayed".to_string()
        } else {
            "API base URL not configured; local model or mock runtime may still work".to_string()
        },
    };

    let ready_for_bridge = python.status == "ok" && bridge_worker.status == "ok";
    let ready_for_dual_runtime = source.status == "ok" && target.status == "ok";
    DoctorReport {
        schema_version: "1.0",
        package_version: env!("CARGO_PKG_VERSION"),
        platform: format!("{}-{}", env::consts::OS, env::consts::ARCH),
        runtime,
        ready_for_mock: true,
        ready_for_bridge,
        ready_for_dual_runtime,
        checks: vec![
            rust,
            python,
            torch,
            mindspore,
            docker,
            bridge_worker,
            source,
            target,
            provider,
        ],
    }
}

fn version_check(
    name: &'static str,
    required_for: &'static str,
    program: &str,
    args: &[&str],
) -> DoctorCheck {
    match Command::new(program).args(args).output() {
        Ok(output) if output.status.success() => {
            let stdout = String::from_utf8_lossy(&output.stdout).trim().to_string();
            let stderr = String::from_utf8_lossy(&output.stderr).trim().to_string();
            DoctorCheck {
                name,
                status: "ok",
                required_for,
                detail: if stdout.is_empty() { stderr } else { stdout },
            }
        }
        Ok(output) => DoctorCheck {
            name,
            status: "warning",
            required_for,
            detail: format!("{program} exited with {}", output.status),
        },
        Err(error) => DoctorCheck {
            name,
            status: "warning",
            required_for,
            detail: format!("{program} unavailable: {error}"),
        },
    }
}

fn python_package_check(
    name: &'static str,
    required_for: &'static str,
    python: &str,
    package: &str,
) -> DoctorCheck {
    let script = "import importlib.metadata,sys; print(importlib.metadata.version(sys.argv[1]))";
    match Command::new(python).args(["-c", script, package]).output() {
        Ok(output) if output.status.success() => DoctorCheck {
            name,
            status: "ok",
            required_for,
            detail: format!(
                "{} via {}",
                String::from_utf8_lossy(&output.stdout).trim(),
                python
            ),
        },
        _ => DoctorCheck {
            name,
            status: "warning",
            required_for,
            detail: format!("{package} not found via {python}"),
        },
    }
}

fn configured_python_check(
    name: &'static str,
    required_for: &'static str,
    python: Option<&str>,
    package: &str,
) -> DoctorCheck {
    match python {
        Some(program) => python_package_check(name, required_for, program, package),
        None => DoctorCheck {
            name,
            status: "warning",
            required_for,
            detail: format!(
                "{} is not configured",
                if package == "torch" {
                    "CANDLE_CLI_PYTORCH_PYTHON"
                } else {
                    "CANDLE_CLI_MINDSPORE_PYTHON"
                }
            ),
        },
    }
}

fn path_check(name: &'static str, required_for: &'static str, path: &Path) -> DoctorCheck {
    DoctorCheck {
        name,
        status: if path.is_file() { "ok" } else { "warning" },
        required_for,
        detail: if path.is_file() {
            path.display().to_string()
        } else {
            format!("{} not found from current directory", path.display())
        },
    }
}
