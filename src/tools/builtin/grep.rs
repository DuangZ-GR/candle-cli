use std::fs;
use std::path::{Path, PathBuf};

pub fn run(pattern: &str, path: Option<&str>) -> Result<String, String> {
    let root = path.unwrap_or(".");
    let mut files = Vec::new();
    collect_files(Path::new(root), &mut files)?;
    files.sort();

    let mut lines = Vec::new();
    for file in files {
        let Ok(contents) = fs::read_to_string(&file) else {
            continue;
        };
        for (idx, line) in contents.lines().enumerate() {
            if line.contains(pattern) {
                lines.push(format!("{}:{}:{}", file.display(), idx + 1, line));
            }
        }
    }

    Ok(lines.join("\n"))
}

fn collect_files(path: &Path, files: &mut Vec<PathBuf>) -> Result<(), String> {
    let metadata = fs::symlink_metadata(path)
        .map_err(|error| format!("failed to inspect {}: {error}", path.display()))?;
    if metadata.file_type().is_symlink() {
        return Ok(());
    }
    if metadata.is_file() {
        files.push(path.to_path_buf());
        return Ok(());
    }

    if !metadata.is_dir() {
        return Err(format!("path does not exist: {}", path.display()));
    }

    for entry in
        fs::read_dir(path).map_err(|err| format!("failed to read dir {}: {err}", path.display()))?
    {
        let entry = entry.map_err(|err| err.to_string())?;
        let child = entry.path();
        let metadata = fs::symlink_metadata(&child)
            .map_err(|error| format!("failed to inspect {}: {error}", child.display()))?;
        if metadata.file_type().is_symlink() {
            continue;
        }
        if metadata.is_dir() {
            collect_files(&child, files)?;
        } else if metadata.is_file() {
            files.push(child);
        }
    }
    Ok(())
}
