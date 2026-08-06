use std::fs;
use std::path::Path;

pub fn run(pattern: &str, _root: Option<&str>) -> Result<String, String> {
    let mut matches = Vec::new();
    let normalized_pattern = pattern.replace('\\', "/");
    collect_matches(&normalized_pattern, &mut matches)?;
    matches.sort();
    Ok(matches.join("\n"))
}

fn collect_matches(pattern: &str, matches: &mut Vec<String>) -> Result<(), String> {
    if let Some(prefix) = pattern.strip_suffix("/**/*.rs") {
        collect_by_extension(Path::new(prefix), "rs", matches)?;
        return Ok(());
    }

    if let Some(prefix) = pattern.strip_suffix("/*.rs") {
        collect_direct_by_extension(Path::new(prefix), "rs", matches)?;
        return Ok(());
    }

    if let Some((dir, suffix)) = pattern.rsplit_once("/*") {
        collect_direct_by_suffix(Path::new(dir), suffix, matches)?;
        return Ok(());
    }

    let path = Path::new(pattern);
    if path.exists() {
        matches.push(path.display().to_string());
    }
    Ok(())
}

fn collect_by_extension(
    dir: &Path,
    extension: &str,
    matches: &mut Vec<String>,
) -> Result<(), String> {
    if !dir.exists() {
        return Ok(());
    }

    for entry in
        fs::read_dir(dir).map_err(|err| format!("failed to read dir {}: {err}", dir.display()))?
    {
        let entry = entry.map_err(|err| err.to_string())?;
        let path = entry.path();
        let metadata = fs::symlink_metadata(&path)
            .map_err(|error| format!("failed to inspect {}: {error}", path.display()))?;
        if metadata.file_type().is_symlink() {
            continue;
        }
        if metadata.is_dir() {
            collect_by_extension(&path, extension, matches)?;
        } else if metadata.is_file() && has_extension(&path, extension) {
            matches.push(path.display().to_string());
        }
    }
    Ok(())
}

fn collect_direct_by_extension(
    dir: &Path,
    extension: &str,
    matches: &mut Vec<String>,
) -> Result<(), String> {
    if !dir.exists() {
        return Ok(());
    }

    for entry in
        fs::read_dir(dir).map_err(|err| format!("failed to read dir {}: {err}", dir.display()))?
    {
        let entry = entry.map_err(|err| err.to_string())?;
        let path = entry.path();
        let metadata = fs::symlink_metadata(&path)
            .map_err(|error| format!("failed to inspect {}: {error}", path.display()))?;
        if metadata.is_file()
            && !metadata.file_type().is_symlink()
            && has_extension(&path, extension)
        {
            matches.push(path.display().to_string());
        }
    }
    Ok(())
}

fn collect_direct_by_suffix(
    dir: &Path,
    suffix: &str,
    matches: &mut Vec<String>,
) -> Result<(), String> {
    if !dir.exists() {
        return Ok(());
    }

    for entry in
        fs::read_dir(dir).map_err(|err| format!("failed to read dir {}: {err}", dir.display()))?
    {
        let entry = entry.map_err(|err| err.to_string())?;
        let path = entry.path();
        let metadata = fs::symlink_metadata(&path)
            .map_err(|error| format!("failed to inspect {}: {error}", path.display()))?;
        if metadata.is_file()
            && !metadata.file_type().is_symlink()
            && path.to_string_lossy().ends_with(suffix)
        {
            matches.push(path.display().to_string());
        }
    }
    Ok(())
}

fn has_extension(path: &Path, extension: &str) -> bool {
    path.extension()
        .and_then(|value| value.to_str())
        .is_some_and(|value| value == extension)
}
