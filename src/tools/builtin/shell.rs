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
            if status.success() {
                return Ok(stdout);
            }
            return Err(format!("{}{}", stdout, stderr));
        }

        if started.elapsed() >= timeout {
            let _ = child.kill();
            let _ = child.wait();
            return Err(format!("command timed out after {}s", timeout.as_secs()));
        }

        thread::sleep(Duration::from_millis(50));
    }
}
