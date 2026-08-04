use std::io::Read;
use std::path::Path;
use std::process::{Child, Command, Stdio};
use std::thread;
use std::thread::JoinHandle;
use std::time::{Duration, Instant};

pub fn run(command: &str, workspace_root: &Path, timeout: Duration) -> Result<String, String> {
    let sandbox = std::env::var("CANDLE_CLI_SANDBOX").unwrap_or_default();
    let supervised_command = supervise_background_jobs(command);

    let mut child_command = match sandbox.as_str() {
        "docker" => {
            let ws = workspace_root.display().to_string();
            let mut command_builder = Command::new("docker");
            command_builder.args([
                "run",
                "--rm",
                "--network=none",
                "-v",
                &format!("{ws}:{ws}:ro"),
                "-w",
                &ws,
                "alpine:latest",
                "sh",
                "-c",
                &supervised_command,
            ]);
            command_builder
        }
        _ => {
            let mut command_builder = Command::new("sh");
            command_builder
                .arg("-c")
                .arg(&supervised_command)
                .current_dir(workspace_root);
            command_builder
        }
    };
    configure_process_group(&mut child_command);
    let mut child = child_command
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .map_err(|e| e.to_string())?;

    let stdout_reader = spawn_reader(
        child
            .stdout
            .take()
            .ok_or_else(|| "shell stdout unavailable".to_string())?,
    );
    let stderr_reader = spawn_reader(
        child
            .stderr
            .take()
            .ok_or_else(|| "shell stderr unavailable".to_string())?,
    );

    let started = Instant::now();
    loop {
        if let Some(status) = child.try_wait().map_err(|e| e.to_string())? {
            // A non-interactive shell may exit while background descendants
            // still hold the inherited output pipes. Clean up the process tree
            // before joining reader threads so a tool call cannot hang forever.
            terminate_process_tree(&mut child);
            let stdout = finish_reader(stdout_reader)?;
            let stderr = finish_reader(stderr_reader)?;
            let exit_code = status.code().unwrap_or(-1);
            let formatted = format_shell_result(status.success(), exit_code, &stdout, &stderr);
            if status.success() {
                return Ok(formatted);
            }
            return Err(formatted);
        }

        if started.elapsed() >= timeout {
            terminate_process_tree(&mut child);
            let _ = child.wait();
            let stdout = finish_reader(stdout_reader)?;
            let stderr = finish_reader(stderr_reader)?;
            return Err(format!(
                "status: error\ntool: shell\ntimeout: true\nmessage: command timed out after {}s\nstdout:\n{}\n\nstderr:\n{}",
                timeout.as_secs(), stdout, stderr
            ));
        }

        thread::sleep(Duration::from_millis(50));
    }
}

fn supervise_background_jobs(command: &str) -> String {
    format!(
        "cleanup_candle_cli_jobs() {{ for pid in $(jobs -p); do kill -KILL \"$pid\" 2>/dev/null; done; wait 2>/dev/null; }}; trap cleanup_candle_cli_jobs EXIT; {command}"
    )
}

fn spawn_reader<R>(mut reader: R) -> JoinHandle<Result<Vec<u8>, String>>
where
    R: Read + Send + 'static,
{
    thread::spawn(move || {
        let mut bytes = Vec::new();
        reader
            .read_to_end(&mut bytes)
            .map_err(|error| format!("failed to read shell output: {error}"))?;
        Ok(bytes)
    })
}

fn finish_reader(reader: JoinHandle<Result<Vec<u8>, String>>) -> Result<String, String> {
    let bytes = reader
        .join()
        .map_err(|_| "shell output reader panicked".to_string())??;
    Ok(String::from_utf8_lossy(&bytes).trim().to_string())
}

#[cfg(unix)]
fn configure_process_group(command: &mut Command) {
    use std::os::unix::process::CommandExt;
    command.process_group(0);
}

#[cfg(not(unix))]
fn configure_process_group(_command: &mut Command) {}

fn terminate_process_tree(child: &mut Child) {
    let process_id = child.id().to_string();

    #[cfg(unix)]
    {
        let _ = Command::new("kill")
            .args(["-KILL", "--", &format!("-{process_id}")])
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .status();
    }

    #[cfg(windows)]
    {
        let _ = Command::new("taskkill")
            .args(["/PID", &process_id, "/T", "/F"])
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .status();
    }

    let _ = child.kill();
}

fn format_shell_result(success: bool, exit_code: i32, stdout: &str, stderr: &str) -> String {
    let status = if success { "ok" } else { "error" };
    format!(
        "status: {status}\ntool: shell\nexit_code: {exit_code}\nstdout:\n{stdout}\n\nstderr:\n{stderr}"
    )
}
