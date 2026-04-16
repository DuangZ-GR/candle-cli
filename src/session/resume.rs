use std::fs;
use std::io;
use std::path::Path;

pub fn latest_session_id(root: &Path) -> io::Result<Option<String>> {
    let mut newest: Option<(std::time::SystemTime, String)> = None;

    if !root.exists() {
        return Ok(None);
    }

    for entry in fs::read_dir(root)? {
        let entry = entry?;
        let metadata = entry.metadata()?;
        let modified = metadata.modified()?;
        if let Some(stem) = entry.path().file_stem().and_then(|value| value.to_str()) {
            match &newest {
                Some((current, _)) if modified <= *current => {}
                _ => newest = Some((modified, stem.to_string())),
            }
        }
    }

    Ok(newest.map(|(_, id)| id))
}
