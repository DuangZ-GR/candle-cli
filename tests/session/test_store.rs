use candle_cli::session::model::Session;
use candle_cli::session::store::SessionStore;
use std::fs;
use std::io::ErrorKind;
use tempfile::tempdir;

#[test]
fn saves_and_loads_session() {
    let dir = tempdir().unwrap();
    let store = SessionStore::new(dir.path().into());
    let session = Session::new("/tmp/workspace".into());
    store.save(&session).unwrap();
    let loaded = store.load(&session.session_id).unwrap();
    assert_eq!(loaded.workspace_root, "/tmp/workspace");
}

#[test]
fn load_rejects_session_id_path_traversal() {
    let dir = tempdir().unwrap();
    let store = SessionStore::new(dir.path().into());

    let error = store.load("../../outside").unwrap_err();

    assert_eq!(error.kind(), ErrorKind::InvalidInput);
}

#[test]
fn save_rejects_an_untrusted_session_id() {
    let dir = tempdir().unwrap();
    let store = SessionStore::new(dir.path().into());
    let mut session = Session::new("/tmp/workspace".into());
    session.session_id = "../outside".into();

    let error = store.save(&session).unwrap_err();

    assert_eq!(error.kind(), ErrorKind::InvalidInput);
    assert!(!dir.path().parent().unwrap().join("outside.json").exists());
}

#[test]
fn load_rejects_a_session_whose_embedded_id_does_not_match() {
    let dir = tempdir().unwrap();
    let store = SessionStore::new(dir.path().into());
    let mut session = Session::new("/tmp/workspace".into());
    session.session_id = "different-id".into();
    fs::write(
        dir.path().join("expected-id.json"),
        serde_json::to_vec(&session).unwrap(),
    )
    .unwrap();

    let error = store.load("expected-id").unwrap_err();

    assert_eq!(error.kind(), ErrorKind::InvalidData);
}

#[test]
fn list_only_returns_valid_json_session_files() {
    let dir = tempdir().unwrap();
    let store = SessionStore::new(dir.path().into());
    let session = Session::new("/tmp/workspace".into());
    store.save(&session).unwrap();
    fs::write(dir.path().join("notes.txt"), "not a session").unwrap();
    fs::write(dir.path().join("invalid.name.json"), "{}").unwrap();

    assert_eq!(store.list().unwrap(), vec![session.session_id]);
}
