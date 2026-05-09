use std::fs;

pub fn run(file_path: &str, old_string: &str, new_string: &str) -> Result<String, String> {
    let contents = fs::read_to_string(file_path)
        .map_err(|err| format!("failed to read {file_path}: {err}"))?;

    let matches = contents.matches(old_string).count();
    if matches == 0 {
        return Err(format!("old_string not found in {file_path}"));
    }
    if matches > 1 {
        return Err(format!("old_string matched {matches} times in {file_path}"));
    }

    let updated = contents.replacen(old_string, new_string, 1);
    fs::write(file_path, updated).map_err(|err| format!("failed to write {file_path}: {err}"))?;
    Ok("edited".to_string())
}
