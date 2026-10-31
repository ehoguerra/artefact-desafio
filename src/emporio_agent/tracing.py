import json
from datetime import UTC, datetime
from pathlib import Path
from types import TracebackType
from typing import Any, Self, TextIO


class Tracer:
    """Writes one JSON object per line: `{"event": ..., "ts": ..., ...}`, flushed immediately."""

    def __init__(self, stream: TextIO | None) -> None:
        self._stream = stream

    @classmethod
    def open(cls, path: Path) -> Self:
        path.parent.mkdir(parents=True, exist_ok=True)
        return cls(path.open("a", encoding="utf-8"))

    @classmethod
    def null(cls) -> Self:
        return cls(None)

    def user(self, text: str) -> None:
        self._write("user", text=text)

    def tool_call(self, name: str, arguments: dict, is_error: bool, content: str) -> None:
        self._write("tool_call", name=name, arguments=arguments, is_error=is_error, content=content)

    def assistant(self, text: str) -> None:
        self._write("assistant", text=text)

    def close(self) -> None:
        if self._stream is not None:
            self._stream.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def _write(self, event: str, **fields: Any) -> None:
        if self._stream is None:
            return
        record = {"event": event, "ts": datetime.now(UTC).isoformat(), **fields}
        self._stream.write(json.dumps(record, ensure_ascii=False) + "\n")
        self._stream.flush()
