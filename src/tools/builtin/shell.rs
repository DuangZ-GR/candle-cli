use std::io::Read;
use std::path::Path;
use std::process::{Child, Command, Stdio};
use std::thread;
use std::thread::JoinHandle;
use std::time::{Duration, Instant};

const DEFAULT_MAX_STREAM_BYTES: usize = 1024 * 1024;

struct BoundedOutput {
    bytes: Vec<u8>,
    truncated_bytes: usize,
}

pub fn run(command: &str, workspace_root: &Path, timeout: Duration) -> Result<String, String> {
    run_with_limits(command, workspace_root, timeout, max_stream_bytes())
}

pub(crate) fn run_with_limits(
    command: &str,
    workspace_root: &Path,
    timeout: Duration,
    max_stream_bytes: usize,
) -> Result<String, String> {
    let sandbox = std::env::var("CANDLE_CLI_SANDBOX").unwrap_or_default();

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
                command,
            ]);
            command_builder
        }
        _ => native_shell_command(command, workspace_root),
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
        max_stream_bytes,
    );
    let stderr_reader = spawn_reader(
        child
            .stderr
            .take()
            .ok_or_else(|| "shell stderr unavailable".to_string())?,
        max_stream_bytes,
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

fn spawn_reader<R>(mut reader: R, max_bytes: usize) -> JoinHandle<Result<BoundedOutput, String>>
where
    R: Read + Send + 'static,
{
    thread::spawn(move || {
        let mut bytes = Vec::new();
        let mut truncated_bytes = 0usize;
        let mut chunk = [0u8; 8192];
        loop {
            let count = reader
                .read(&mut chunk)
                .map_err(|error| format!("failed to read shell output: {error}"))?;
            if count == 0 {
                break;
            }
            let remaining = max_bytes.saturating_sub(bytes.len());
            let keep = remaining.min(count);
            bytes.extend_from_slice(&chunk[..keep]);
            truncated_bytes = truncated_bytes.saturating_add(count - keep);
        }
        Ok(BoundedOutput {
            bytes,
            truncated_bytes,
        })
    })
}

#[cfg(unix)]
fn native_shell_command(command: &str, workspace_root: &Path) -> Command {
    let mut command_builder = Command::new("sh");
    command_builder
        .arg("-c")
        .arg(command)
        .current_dir(workspace_root);
    command_builder
}

#[cfg(windows)]
fn native_shell_command(command: &str, workspace_root: &Path) -> Command {
    let mut command_builder = Command::new("cmd");
    command_builder
        .args(["/D", "/S", "/C", command])
        .current_dir(workspace_root);
    command_builder
}

fn finish_reader(reader: JoinHandle<Result<BoundedOutput, String>>) -> Result<String, String> {
    let output = reader
        .join()
        .map_err(|_| "shell output reader panicked".to_string())??;
    let mut text = String::from_utf8_lossy(&output.bytes).trim().to_string();
    if output.truncated_bytes > 0 {
        text.push_str(&format!(
            "\n[shell output truncated: {} bytes omitted]",
            output.truncated_bytes
        ));
    }
    Ok(text)
}

fn max_stream_bytes() -> usize {
    std::env::var("CANDLE_CLI_MAX_SHELL_OUTPUT_BYTES")
        .ok()
        .and_then(|value| value.parse::<usize>().ok())
        .filter(|value| *value > 0)
        .unwrap_or(DEFAULT_MAX_STREAM_BYTES)
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

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Cursor;

    #[test]
    fn shell_reader_bounds_memory_and_reports_omitted_bytes() {
        let reader = spawn_reader(Cursor::new(vec![b'x'; 4096]), 1024);
        let output = finish_reader(reader).unwrap();

        assert!(output.starts_with(&"x".repeat(1024)));
        assert!(output.ends_with("[shell output truncated: 3072 bytes omitted]"));
        assert!(output.len() < 1200);
    }
}
