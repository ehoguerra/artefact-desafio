import json
import os
import re
from pathlib import Path

_SESSION_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")


class ConversationStore:
    """Persists each session's message list as one JSON file."""

    def __init__(self, directory: Path) -> None:
        self._directory = directory

    def load(self, session_id: str) -> list[dict]:
        path = self._path(session_id)
        if not path.exists():
            return []
        return json.loads(path.read_text(encoding="utf-8"))

    def save(self, session_id: str, messages: list[dict]) -> None:
        path = self._path(session_id)
        self._directory.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f"{path.name}.tmp")
        temporary.write_text(json.dumps(messages, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(temporary, path)

    def _path(self, session_id: str) -> Path:
        if not _SESSION_ID.fullmatch(session_id):
            raise ValueError(f"ID de sessão inválido: {session_id!r} (use letras, números, _ ou -)")
        return self._directory / f"{session_id}.json"
