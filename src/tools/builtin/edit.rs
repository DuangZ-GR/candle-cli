pub fn run(file_path: &str, old_string: &str, new_string: &str) -> Result<String, String> {
    let content = std::fs::read_to_string(file_path).map_err(|e| e.to_string())?;
    let updated = content.replace(old_string, new_string);
    std::fs::write(file_path, updated).map_err(|e| e.to_string())?;
    Ok(format!("edited {}", file_path))
}
