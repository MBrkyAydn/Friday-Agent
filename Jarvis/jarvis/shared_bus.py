import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple


class SharedBusProtocol:
    def __init__(self, shared_root: str | Path, logs_root: str | Path, agent_name: str = "Jarvis") -> None:
        self.shared_root = Path(shared_root).resolve()
        self.logs_root = Path(logs_root).resolve()
        self.agent_name = agent_name

        self.mailboxes = self.shared_root / "mailboxes"
        self.inbox = self.mailboxes / f"{self.agent_name.lower()}_inbox"
        self.inbox.mkdir(parents=True, exist_ok=True)
        self.logs_root.mkdir(parents=True, exist_ok=True)

    def send_message(self, recipient: str, action: str, payload: Dict[str, Any]) -> str:
        recipient_inbox = self.mailboxes / f"{recipient.lower()}_inbox"
        recipient_inbox.mkdir(parents=True, exist_ok=True)

        msg_id = f"msg-{uuid.uuid4().hex[:8]}"
        msg_data = {
            "message_id": msg_id,
            "sender": self.agent_name,
            "recipient": recipient,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "action": action,
            "payload": payload,
        }

        msg_file = recipient_inbox / f"{msg_id}.json"
        msg_file.write_text(json.dumps(msg_data, indent=2), encoding="utf-8")
        self.log_event("MESSAGE_SENT", {"to": recipient, "action": action, "id": msg_id})
        return msg_id

    def read_inbox(self) -> List[Dict[str, Any]]:
        messages = []
        for file in sorted(self.inbox.glob("*.json")):
            try:
                data = json.loads(file.read_text(encoding="utf-8"))
                messages.append(data)
            except Exception:
                continue
        return messages

    def read_inbox_files(self) -> List[Tuple[Path, Dict[str, Any]]]:
        """Read inbox returning tuples of (file_path, message_dict)."""
        messages = []
        for file in sorted(self.inbox.glob("*.json")):
            try:
                data = json.loads(file.read_text(encoding="utf-8"))
                messages.append((file, data))
            except Exception:
                continue
        return messages

    def delete_message(self, msg_id_or_path: str | Path) -> bool:
        """Remove a message file from inbox by ID or Path."""
        if isinstance(msg_id_or_path, Path):
            target = msg_id_or_path
        else:
            target = self.inbox / f"{msg_id_or_path}.json"
        if target.exists():
            target.unlink(missing_ok=True)
            return True
        return False

    def archive_message(self, msg_id_or_path: str | Path, archive_dir: Path | None = None) -> bool:
        """Move a message file from inbox to archive folder."""
        if isinstance(msg_id_or_path, Path):
            src = msg_id_or_path
        else:
            src = self.inbox / f"{msg_id_or_path}.json"
        if not src.exists():
            return False
        dest_dir = archive_dir or (self.mailboxes / "archive")
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / src.name
        try:
            src.replace(dest)
            return True
        except Exception:
            try:
                dest.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
                src.unlink(missing_ok=True)
                return True
            except Exception:
                return False

    def log_event(self, event_type: str, data: Dict[str, Any]) -> None:
        log_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "agent": self.agent_name,
            "event_type": event_type,
            "data": data,
        }
        log_file = self.logs_root / f"{self.agent_name.lower()}.log"
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(log_entry) + "\n")
