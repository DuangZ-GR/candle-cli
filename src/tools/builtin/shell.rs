use std::path::Path;
use std::process::{Command, Stdio};
use std::thread;
use std::time::{Duration, Instant};

pub fn run(command: &str, workspace_root: &Path, timeout: Duration) -> Result<String, String> {
    let mut child = Command::new("sh")
        .arg("-lc")
        .arg(command)
        .current_dir(workspace_root)
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .map_err(|e| e.to_string())?;

    let started = Instant::now();
    loop {
        if let Some(status) = child.try_wait().map_err(|e| e.to_string())? {
            let output = child.wait_with_output().map_err(|e| e.to_string())?;
            let stdout = String::from_utf8_lossy(&output.stdout).trim().to_string();
            let stderr = String::from_utf8_lossy(&output.stderr).trim().to_string();
            let exit_code = status.code().unwrap_or(-1);
            let formatted = format_shell_result(status.success(), exit_code, &stdout, &stderr);
            if status.success() {
                return Ok(formatted);
            }
            return Err(formatted);
        }

        if started.elapsed() >= timeout {
            let _ = child.kill();
            let _ = child.wait();
            return Err(format!(
                "status: error\ntool: shell\ntimeout: true\nmessage: command timed out after {}s\nstdout:\n\nstderr:\n",
                timeout.as_secs()
            ));
        }

        thread::sleep(Duration::from_millis(50));
    }
}

fn format_shell_result(success: bool, exit_code: i32, stdout: &str, stderr: &str) -> String {
    let status = if success { "ok" } else { "error" };
    format!(
        "status: {status}\ntool: shell\nexit_code: {exit_code}\nstdout:\n{stdout}\n\nstderr:\n{stderr}"
    )
}
