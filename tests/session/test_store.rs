use candle_cli::session::model::Session;
use candle_cli::session::store::SessionStore;
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
