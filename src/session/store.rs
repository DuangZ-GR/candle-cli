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
        let path = self.session_path(&session.session_id)?;
        let body = serde_json::to_vec_pretty(session).map_err(io::Error::other)?;
        fs::write(path, body)
    }

    pub fn load(&self, id: &str) -> io::Result<Session> {
        let path = self.session_path(id)?;
        let body = fs::read(path)?;
        let session: Session = serde_json::from_slice(&body).map_err(io::Error::other)?;
        if session.session_id != id {
            return Err(io::Error::new(
                io::ErrorKind::InvalidData,
                "session id does not match its file name",
            ));
        }
        Ok(session)
    }

    pub fn list(&self) -> io::Result<Vec<String>> {
        fs::create_dir_all(&self.root)?;
        let mut ids = Vec::new();
        for entry in fs::read_dir(&self.root)? {
            let entry = entry?;
            let path = entry.path();
            if path.extension().and_then(|value| value.to_str()) != Some("json") {
                continue;
            }
            if let Some(stem) = path.file_stem().and_then(|value| value.to_str()) {
                if is_valid_session_id(stem) {
                    ids.push(stem.to_string());
                }
            }
        }
        ids.sort();
        Ok(ids)
    }

    fn session_path(&self, id: &str) -> io::Result<PathBuf> {
        if !is_valid_session_id(id) {
            return Err(io::Error::new(
                io::ErrorKind::InvalidInput,
                "invalid session id",
            ));
        }
        Ok(self.root.join(format!("{id}.json")))
    }
}

fn is_valid_session_id(id: &str) -> bool {
    !id.is_empty()
        && id.len() <= 128
        && id
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'-' | b'_'))
}
