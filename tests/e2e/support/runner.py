"""Executa a CLI real como subprocesso e transforma stdout + trace JSONL em uma transcrição."""

import json
import subprocess
import sys
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

CLI_TIMEOUT_SECONDS = 240
REPLY_PREFIX = "Lia: "
PROMPT_PREFIX = "Você: "


@dataclass(frozen=True, slots=True)
class ToolCall:
    name: str
    arguments: dict[str, Any]
    is_error: bool
    content: str


@dataclass(frozen=True, slots=True)
class Turn:
    user: str
    reply: str
    tool_calls: tuple[ToolCall, ...]


@dataclass(frozen=True, slots=True)
class Transcript:
    session_id: str
    now: str
    turns: tuple[Turn, ...]
    duration_seconds: float

    @property
    def replies(self) -> list[str]:
        return [turn.reply for turn in self.turns]

    @property
    def tool_calls(self) -> list[ToolCall]:
        return [call for turn in self.turns for call in turn.tool_calls]

    def calls_to(self, name: str) -> list[ToolCall]:
        return [call for call in self.tool_calls if call.name == name]


RunConversation = Callable[[str, list[str], str], Transcript]


@dataclass(slots=True)
class ConversationRunner:
    """Uma chamada a `run` = um processo da CLI com todas as mensagens no stdin."""

    repo_root: Path
    work_dir: Path
    base_env: Mapping[str, str]
    sessions_dir: Path
    _runs: int = field(default=0, init=False)

    def run(self, session_id: str, messages: list[str], now: str) -> Transcript:
        self._runs += 1
        trace_path = self.work_dir / f"trace-{self._runs:02d}-{session_id}.jsonl"
        started = time.perf_counter()
        completed = subprocess.run(
            self._command(session_id, trace_path),
            input="".join(f"{message}\n" for message in messages),
            capture_output=True,
            text=True,
            encoding="utf-8",
            cwd=self.repo_root,
            env=self._env(now),
            timeout=CLI_TIMEOUT_SECONDS,
            check=False,
        )
        duration = time.perf_counter() - started
        _assert_success(completed)
        replies = parse_replies(completed.stdout)
        tool_calls = parse_tool_calls(trace_path)
        _assert_turn_count(messages, replies, tool_calls, completed.stdout)
        turns = tuple(
            Turn(user, reply, calls)
            for user, reply, calls in zip(messages, replies, tool_calls, strict=True)
        )
        return Transcript(session_id, now, turns, duration)

    def _command(self, session_id: str, trace_path: Path) -> list[str]:
        return [
            sys.executable,
            "-m",
            "emporio_agent",
            "chat",
            "--session",
            session_id,
            "--trace",
            str(trace_path),
        ]

    def _env(self, now: str) -> dict[str, str]:
        return {
            **self.base_env,
            "EMPORIO_SESSIONS_DIR": str(self.sessions_dir),
            "EMPORIO_NOW": now,
            "PYTHONIOENCODING": "utf-8",
            "PYTHONUTF8": "1",
        }


def parse_replies(stdout: str) -> list[str]:
    """Cada resposta começa numa linha `Lia: ` e vai até a próxima resposta ou o fim da saída."""
    replies: list[list[str]] = []
    for raw_line in stdout.splitlines():
        line = _strip_prompts(raw_line)
        if line.startswith(REPLY_PREFIX):
            replies.append([line.removeprefix(REPLY_PREFIX)])
        elif replies:
            replies[-1].append(line)
    return ["\n".join(lines).strip() for lines in replies]


def parse_tool_calls(trace_path: Path) -> list[tuple[ToolCall, ...]]:
    """Agrupa os eventos `tool_call` entre cada `user` e o `assistant` seguinte."""
    turns: list[list[ToolCall]] = []
    for event in _read_events(trace_path):
        match event["event"]:
            case "user":
                turns.append([])
            case "tool_call" if turns:
                turns[-1].append(
                    ToolCall(
                        name=event["name"],
                        arguments=event.get("arguments") or {},
                        is_error=bool(event.get("is_error")),
                        content=str(event.get("content", "")),
                    )
                )
    return [tuple(calls) for calls in turns]


def _read_events(trace_path: Path) -> list[dict[str, Any]]:
    if not trace_path.exists():
        raise AssertionError(f"A CLI não gerou o arquivo de trace {trace_path}")
    lines = trace_path.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def _strip_prompts(line: str) -> str:
    while line.startswith(PROMPT_PREFIX):
        line = line.removeprefix(PROMPT_PREFIX)
    return line


def _assert_success(completed: subprocess.CompletedProcess[str]) -> None:
    if completed.returncode != 0:
        raise AssertionError(
            f"CLI terminou com código {completed.returncode}.\n"
            f"stderr:\n{completed.stderr}\nstdout:\n{completed.stdout}"
        )


def _assert_turn_count(
    messages: list[str],
    replies: list[str],
    tool_calls: list[tuple[ToolCall, ...]],
    stdout: str,
) -> None:
    if len(replies) != len(messages) or len(tool_calls) != len(messages):
        raise AssertionError(
            f"Esperava {len(messages)} turnos; stdout tem {len(replies)} respostas e o trace "
            f"{len(tool_calls)} turnos.\nstdout:\n{stdout}"
        )
