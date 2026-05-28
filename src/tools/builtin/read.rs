use std::fs;
use std::path::Path;

pub fn run(file_path: &str) -> Result<String, String> {
    let path = Path::new(file_path);
    if !path.is_file() {
        return Err(format!("not a file: {file_path}"));
    }

    fs::read_to_string(path).map_err(|err| format!("failed to read {file_path}: {err}"))
}
