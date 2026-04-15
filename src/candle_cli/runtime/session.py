"""Session persistence models for candle-cli."""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass(kw_only=True)
class BaseMessage:
    role: str
    text: str


@dataclass(kw_only=True)
class SystemMessage(BaseMessage):
    role: str = "system"


@dataclass(kw_only=True)
class UserMessage(BaseMessage):
    role: str = "user"


@dataclass(kw_only=True)
class AssistantMessage(BaseMessage):
    role: str = "assistant"


@dataclass(kw_only=True)
class ToolMessage(BaseMessage):
    role: str = "tool"


@dataclass
class Session:
    session_id: str
    workspace_root: str
    messages: list[BaseMessage] = field(default_factory=list)

    def append(self, message: BaseMessage) -> None:
        self.messages.append(message)


class SessionStore:
    def __init__(self, session_dir: Path):
        self.session_dir = Path(session_dir)
        self.session_dir.mkdir(parents=True, exist_ok=True)

    def create_session(self, workspace_root: Path) -> Session:
        return Session(session_id=uuid.uuid4().hex, workspace_root=str(workspace_root))

    def save(self, session: Session) -> None:
        path = self.session_dir / f"{session.session_id}.json"
        payload = {
            "session_id": session.session_id,
            "workspace_root": session.workspace_root,
            "messages": [asdict(message) for message in session.messages],
        }
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def load(self, session_id: str) -> Session:
        path = self.session_dir / f"{session_id}.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        messages = [BaseMessage(**message) for message in payload.get("messages", [])]
        return Session(
            session_id=payload["session_id"],
            workspace_root=payload["workspace_root"],
            messages=messages,
        )
