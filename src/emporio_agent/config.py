import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[2]
EFFORT_LEVELS = frozenset({"low", "medium", "high", "xhigh", "max"})


@dataclass(frozen=True, slots=True)
class Settings:
    data_dir: Path
    knowledge_path: Path
    sessions_dir: Path
    model: str
    effort: str
    max_tool_rounds: int
    frozen_now: datetime | None

    def clock(self) -> datetime:
        return self.frozen_now or datetime.now(UTC)


def load_settings() -> Settings:
    """Load `.env` from the repo root (real environment variables take precedence) and validate."""
    load_dotenv(REPO_ROOT / ".env", override=False)
    return Settings(
        data_dir=REPO_ROOT / "data",
        knowledge_path=REPO_ROOT / "knowledge" / "politicas_da_loja.md",
        sessions_dir=REPO_ROOT / os.environ.get("EMPORIO_SESSIONS_DIR", ".sessions"),
        model=os.environ.get("EMPORIO_MODEL", "claude-opus-5-5"),
        effort=_parse_effort(os.environ.get("EMPORIO_EFFORT", "low")),
        max_tool_rounds=6,
        frozen_now=_parse_now(os.environ.get("EMPORIO_NOW")),
    )


def _parse_effort(value: str) -> str:
    if value not in EFFORT_LEVELS:
        raise ValueError(f"EMPORIO_EFFORT inválido: {value!r} (use um de {sorted(EFFORT_LEVELS)})")
    return value


def _parse_now(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        moment = datetime.fromisoformat(value)
    except ValueError as error:
        raise ValueError(f"EMPORIO_NOW não é ISO 8601: {value!r}") from error
    if moment.tzinfo is None:
        raise ValueError(f"EMPORIO_NOW precisa de fuso horário (ex.: -04:00): {value!r}")
    return moment
