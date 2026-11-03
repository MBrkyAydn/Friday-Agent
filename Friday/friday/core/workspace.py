from pathlib import Path
import os

class SecurityError(Exception):
    """Raised when a tool attempts to access a path outside the designated workspace."""
    pass

class WorkspaceGuard:
    def __init__(self, target_dir: str | Path, allow_self_dev: bool = False) -> None:
        self.target_dir = Path(target_dir).resolve()
        self.allow_self_dev = allow_self_dev
        if not self.target_dir.exists():
            self.target_dir.mkdir(parents=True, exist_ok=True)

    def resolve_path(self, relative_or_absolute: str | Path) -> Path:
        raw_path = Path(relative_or_absolute)
        if raw_path.is_absolute():
            resolved = raw_path.resolve()
        else:
            resolved = (self.target_dir / raw_path).resolve()

        # Enforce jail containment
        try:
            resolved.relative_to(self.target_dir)
        except ValueError:
            raise SecurityError(
                f"Access denied: path '{resolved}' escapes target workspace '{self.target_dir}'"
            )

        return resolved

    def is_safe(self, path: str | Path) -> bool:
        try:
            self.resolve_path(path)
            return True
        except SecurityError:
            return False
