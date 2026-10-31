"""Registro de um cenário E2E: todas as verificações são anotadas antes de o teste falhar."""

from collections.abc import Callable
from dataclasses import dataclass, field

from .judge import CHECK_PREFIX, Judge, Judgement
from .runner import ToolCall, Transcript
from .text import mentioned

EXCERPT_LENGTH = 160


@dataclass(frozen=True, slots=True)
class Check:
    name: str
    passed: bool
    detail: str


@dataclass(frozen=True, slots=True)
class Example:
    number: int
    slug: str
    title: str


@dataclass(slots=True)
class Scenario:
    name: str
    description: str
    example: Example | None = None
    transcripts: list[Transcript] = field(default_factory=list)
    checks: list[Check] = field(default_factory=list)
    outcome: str = "not_run"
    error: str | None = None
    duration_seconds: float = 0.0
    judge: Judge | None = None
    judgement: Judgement | None = None

    @property
    def passed(self) -> bool:
        return self.outcome == "passed"

    def record(self, transcript: Transcript) -> Transcript:
        self.transcripts.append(transcript)
        return transcript

    def check(self, name: str, passed: bool, detail: str) -> None:
        self.checks.append(Check(name, passed, detail))

    def expect_tool(
        self,
        transcript: Transcript,
        names: tuple[str, ...],
        matches: Callable[[ToolCall], bool] = lambda _: True,
        requirement: str = "",
    ) -> None:
        candidates = [call for call in transcript.tool_calls if call.name in names]
        satisfying = [call for call in candidates if matches(call)]
        label = " ou ".join(names) + (f" com {requirement}" if requirement else "")
        detail = f"chamadas: {_describe(candidates) or 'nenhuma'}"
        self.check(f"tool {label}", bool(satisfying), detail)

    def expect_mentions(self, name: str, text: str, terms: list[str], at_least: int = 1) -> None:
        found = mentioned(text, terms)
        detail = f"encontrados {found} (mínimo {at_least}) em: {_excerpt(text)}"
        self.check(name, len(found) >= at_least, detail)

    def expect_absent(self, name: str, text: str, terms: list[str]) -> None:
        found = mentioned(text, terms)
        detail = f"proibidos encontrados: {found}" if found else "nenhum termo proibido"
        self.check(name, not found, detail)

    def expect_fact(self, name: str, text: str, holds: bool) -> None:
        self.check(name, holds, _excerpt(text))

    def assert_all_checks_passed(self) -> None:
        """Último passo de todo teste: o juiz avalia as conversas e então falha se algo falhou."""
        self._judge_transcripts()
        failed = [check for check in self.checks if not check.passed]
        if failed:
            lines = "\n".join(f"- {check.name}: {check.detail}" for check in failed)
            raise AssertionError(f"{len(failed)} verificação(ões) falharam:\n{lines}")

    def _judge_transcripts(self) -> None:
        if self.judge is None or not self.transcripts:
            return
        self.judgement = self.judge.evaluate(self.description, self.transcripts)
        if self.judgement.error:
            self.check(f"{CHECK_PREFIX}avaliação", False, self.judgement.error)
        for score in self.judgement.scores:
            detail = f"nota {score.score}/5 (mínimo {score.threshold}) — {score.justification}"
            self.check(score.check_name, score.passed, detail)


def _describe(calls: list[ToolCall]) -> str:
    return "; ".join(f"{call.name}({call.arguments}) is_error={call.is_error}" for call in calls)


def _excerpt(text: str) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= EXCERPT_LENGTH else f"{flat[:EXCERPT_LENGTH]}…"
