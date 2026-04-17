pub fn run(file_path: &str, content: &str) -> Result<String, String> {
    std::fs::write(file_path, content).map_err(|e| e.to_string())?;
    Ok(format!("wrote {}", file_path))
}
