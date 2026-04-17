use crate::session::model::Session;
use std::fs;
use std::io;
use std::path::PathBuf;

pub struct SessionStore {
    root: PathBuf,
}

impl SessionStore {
    pub fn new(root: PathBuf) -> Self {
        Self { root }
    }

    pub fn save(&self, session: &Session) -> io::Result<()> {
        fs::create_dir_all(&self.root)?;
        let path = self.root.join(format!("{}.json", session.session_id));
        let body = serde_json::to_vec_pretty(session).map_err(io::Error::other)?;
        fs::write(path, body)
    }

    pub fn load(&self, id: &str) -> io::Result<Session> {
        let path = self.root.join(format!("{}.json", id));
        let body = fs::read(path)?;
        serde_json::from_slice(&body).map_err(io::Error::other)
    }

    pub fn list(&self) -> io::Result<Vec<String>> {
        fs::create_dir_all(&self.root)?;
        let mut ids = Vec::new();
        for entry in fs::read_dir(&self.root)? {
            let entry = entry?;
            if let Some(stem) = entry.path().file_stem().and_then(|value| value.to_str()) {
                ids.push(stem.to_string());
            }
        }
        Ok(ids)
    }
}
