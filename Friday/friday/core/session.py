import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class SessionTurn(BaseModel):
    """Represents a single conversational/execution turn in a session."""

    user_prompt: str
    thoughts: List[str] = Field(default_factory=list)
    tool_calls: List[Dict[str, Any]] = Field(default_factory=list)
    status: str = "DONE"
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class Session(BaseModel):
    """Represents an interactive or autonomous agent session with history."""

    session_id: str
    workspace_path: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    turns: List[SessionTurn] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class SessionManager:
    """Manages creation, recording, persistence, and retrieval of agent sessions."""

    def create_session(self, workspace_path: Path, metadata: Optional[Dict[str, Any]] = None) -> Session:
        session_id = f"session-{datetime.now(timezone.utc).strftime('%Y%m%d')}-{uuid.uuid4().hex[:8]}"
        return Session(
            session_id=session_id,
            workspace_path=str(workspace_path.resolve()),
            metadata=metadata or {},
        )

    def record_turn(
        self,
        session: Session,
        prompt: str,
        thoughts: Optional[List[str]] = None,
        tool_calls: Optional[List[Dict[str, Any]]] = None,
        status: str = "DONE",
    ) -> SessionTurn:
        turn = SessionTurn(
            user_prompt=prompt,
            thoughts=thoughts or [],
            tool_calls=tool_calls or [],
            status=status,
        )
        session.turns.append(turn)
        return turn

    def save_session(self, session: Session, target_dir: Optional[Path] = None) -> Path:
        base_dir = target_dir or Path(session.workspace_path)
        sessions_dir = base_dir / ".friday" / "sessions"
        sessions_dir.mkdir(parents=True, exist_ok=True)

        session_file = sessions_dir / f"{session.session_id}.json"
        session_file.write_text(session.model_dump_json(indent=2), encoding="utf-8")
        return session_file

    def load_session(self, session_file: Path) -> Session:
        content = session_file.read_text(encoding="utf-8")
        data = json.loads(content)
        return Session(**data)

    def list_sessions(self, target_dir: Path) -> List[Dict[str, Any]]:
        sessions_dir = target_dir / ".friday" / "sessions"
        if not sessions_dir.is_dir():
            return []

        results: List[Dict[str, Any]] = []
        for file in sorted(sessions_dir.glob("*.json"), reverse=True):
            try:
                session = self.load_session(file)
                results.append(
                    {
                        "session_id": session.session_id,
                        "created_at": session.created_at.isoformat(),
                        "turns_count": len(session.turns),
                        "file_path": str(file),
                    }
                )
            except Exception:
                continue

        return results

    def reset_session(self, session: Session) -> Session:
        session.turns.clear()
        return session
