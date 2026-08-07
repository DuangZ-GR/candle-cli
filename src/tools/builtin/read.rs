use std::fs;
use std::path::Path;

pub fn run(file_path: &str, max_bytes: u64) -> Result<String, String> {
    let path = Path::new(file_path);
    if !path.is_file() {
        return Err(format!("not a file: {file_path}"));
    }

    let size = fs::metadata(path)
        .map_err(|err| format!("failed to inspect {file_path}: {err}"))?
        .len();
    if size > max_bytes {
        return Err(format!(
            "file exceeds read limit: {size} bytes > {max_bytes} bytes"
        ));
    }

    fs::read_to_string(path).map_err(|err| format!("failed to read {file_path}: {err}"))
}
