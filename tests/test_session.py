from candle_cli.runtime.session import SessionStore, UserMessage


def test_session_round_trip(tmp_path):
    store = SessionStore(tmp_path / ".candle-cli" / "sessions")
    session = store.create_session(workspace_root=tmp_path)
    session.append(UserMessage(text="hello"))
    store.save(session)

    loaded = store.load(session.session_id)
    assert loaded.messages[0].role == "user"
    assert loaded.messages[0].text == "hello"

