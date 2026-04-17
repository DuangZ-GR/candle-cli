use std::process::Command;

pub fn run(command: &str) -> Result<String, String> {
    let output = Command::new("sh")
        .arg("-lc")
        .arg(command)
        .output()
        .map_err(|e| e.to_string())?;

    let stdout = String::from_utf8_lossy(&output.stdout).to_string();
    let stderr = String::from_utf8_lossy(&output.stderr).to_string();

    if output.status.success() {
        Ok(stdout.trim().to_string())
    } else {
        Err(format!("{}{}", stdout, stderr))
    }
}
