"""Artefato verificável da suíte: report.md, report.json, transcrições e exemplos."""

import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .judge import PASS_THRESHOLDS, Judgement
from .runner import ToolCall, Transcript, Turn
from .scenario import Scenario

STATUS_LABEL = {"passed": "✅ passou", "failed": "❌ falhou", "skipped": "⏭️ pulado"}
JUDGE_OFF_LABEL = "desativado (EMPORIO_JUDGE=off)"


@dataclass(frozen=True, slots=True)
class RunInfo:
    timestamp: str
    model: str
    judge_model: str | None


def reset_directory(directory: Path) -> None:
    shutil.rmtree(directory, ignore_errors=True)
    (directory / "transcripts").mkdir(parents=True)


def write_report(
    scenarios: list[Scenario], run: RunInfo, report_dir: Path, examples_dir: Path
) -> None:
    (report_dir / "report.json").write_text(
        json.dumps(_report_payload(scenarios, run), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (report_dir / "report.md").write_text(_report_markdown(scenarios, run), encoding="utf-8")
    for scenario in scenarios:
        transcript_path = report_dir / "transcripts" / f"{scenario.name}.md"
        transcript_path.write_text(_transcript_markdown(scenario, run), encoding="utf-8")
        if scenario.example and scenario.passed:
            example_path = (
                examples_dir / f"{scenario.example.number:02d}-{scenario.example.slug}.md"
            )
            example_path.write_text(_example_markdown(scenario, run), encoding="utf-8")


def _report_payload(scenarios: list[Scenario], run: RunInfo) -> dict[str, Any]:
    return {
        "run_timestamp": run.timestamp,
        "model": run.model,
        "judge_model": run.judge_model,
        "summary": {
            "total": len(scenarios),
            "passed": sum(scenario.passed for scenario in scenarios),
            "failed": sum(scenario.outcome == "failed" for scenario in scenarios),
        },
        "scenarios": [_scenario_payload(scenario) for scenario in scenarios],
    }


def _scenario_payload(scenario: Scenario) -> dict[str, Any]:
    return {
        "name": scenario.name,
        "description": scenario.description,
        "outcome": scenario.outcome,
        "error": scenario.error,
        "duration_seconds": round(scenario.duration_seconds, 2),
        "frozen_clock": sorted({transcript.now for transcript in scenario.transcripts}),
        "checks": [
            {"name": check.name, "passed": check.passed, "detail": check.detail}
            for check in scenario.checks
        ],
        "judge": _judge_payload(scenario.judgement),
        "runs": [_transcript_payload(transcript) for transcript in scenario.transcripts],
    }


def _judge_payload(judgement: Judgement | None) -> dict[str, Any] | None:
    if judgement is None:
        return None
    return {
        "model": judgement.model,
        "passed": judgement.passed,
        "average": judgement.average,
        "error": judgement.error,
        "criteria": {
            score.criterion: {
                "score": score.score,
                "threshold": score.threshold,
                "passed": score.passed,
                "justification": score.justification,
            }
            for score in judgement.scores
        },
    }


def _transcript_payload(transcript: Transcript) -> dict[str, Any]:
    return {
        "session_id": transcript.session_id,
        "now": transcript.now,
        "duration_seconds": round(transcript.duration_seconds, 2),
        "turns": [
            {
                "user": turn.user,
                "reply": turn.reply,
                "tool_calls": [
                    {"name": call.name, "arguments": call.arguments, "is_error": call.is_error}
                    for call in turn.tool_calls
                ],
            }
            for turn in transcript.turns
        ],
    }


def _report_markdown(scenarios: list[Scenario], run: RunInfo) -> str:
    passed = sum(scenario.passed for scenario in scenarios)
    lines = [
        "# Relatório E2E — Empório da Música",
        "",
        f"- **Execução:** {run.timestamp}",
        f"- **Modelo:** `{run.model}`",
        f"- **Juiz:** {_judge_header(run)}",
        f"- **Resultado:** {passed}/{len(scenarios)} cenários passaram",
        "",
        "| Cenário | Resultado | Juiz | Relógio da loja | Duração | Tools |",
        "|---|---|---|---|---|---|",
    ]
    lines += [_summary_row(scenario) for scenario in scenarios]
    for scenario in scenarios:
        lines += ["", *_scenario_section(scenario)]
    return "\n".join(lines) + "\n"


def _summary_row(scenario: Scenario) -> str:
    clocks = ", ".join(sorted({transcript.now for transcript in scenario.transcripts})) or "—"
    tools = ", ".join(
        call.name for transcript in scenario.transcripts for call in transcript.tool_calls
    )
    return (
        f"| [{scenario.name}](transcripts/{scenario.name}.md) | {_status(scenario)} "
        f"| {_judge_average(scenario.judgement)} | {clocks} "
        f"| {scenario.duration_seconds:.1f}s | {tools or '—'} |"
    )


def _scenario_section(scenario: Scenario) -> list[str]:
    lines = [f"## {scenario.name} — {_status(scenario)}", "", scenario.description, ""]
    judged = _judged_check_names(scenario.judgement)
    lines += [
        f"- {'✅' if check.passed else '❌'} **{check.name}** — {_single_line(check.detail)}"
        for check in scenario.checks
        if check.name not in judged
    ]
    if scenario.judgement and scenario.judgement.scores:
        lines += ["", *_judge_table(scenario.judgement)]
    if scenario.error:
        lines += ["", "```text", scenario.error, "```"]
    return lines


def _judged_check_names(judgement: Judgement | None) -> set[str]:
    """Critérios que vão para a tabela do juiz em vez da lista de verificações."""
    return {score.check_name for score in judgement.scores} if judgement else set()


def _judge_header(run: RunInfo) -> str:
    if run.judge_model is None:
        return JUDGE_OFF_LABEL
    thresholds = ", ".join(f"{name} ≥ {minimum}" for name, minimum in PASS_THRESHOLDS.items())
    return f"`{run.judge_model}` (notas 1–5; mínimos: {thresholds})"


def _judge_average(judgement: Judgement | None) -> str:
    if judgement is None:
        return "—"
    if judgement.average is None:
        return "❌ sem veredito"
    return f"{'✅' if judgement.passed else '❌'} {judgement.average:.1f}/5"


def _judge_table(judgement: Judgement) -> list[str]:
    rows = [
        f"| {score.criterion} | {'✅' if score.passed else '❌'} {score.score}/5 "
        f"(mín. {score.threshold}) | {_single_line(score.justification).replace('|', '/')} |"
        for score in judgement.scores
    ]
    return [
        f"Juiz (`{judgement.model}`):",
        "",
        "| Critério | Nota | Justificativa |",
        "|---|---|---|",
        *rows,
    ]


def _transcript_markdown(scenario: Scenario, run: RunInfo) -> str:
    header = [
        f"# {scenario.name}",
        "",
        scenario.description,
        "",
        f"Resultado: {_status(scenario)} · {_metadata(scenario, run)}",
    ]
    return "\n".join([*header, "", *_conversation(scenario.transcripts)]) + "\n"


def _example_markdown(scenario: Scenario, run: RunInfo) -> str:
    assert scenario.example is not None
    lines = [
        f"# {scenario.example.title}",
        "",
        scenario.description,
        "",
        _metadata(scenario, run),
        "",
        *_conversation(scenario.transcripts),
        "---",
        "",
        f"Gerado automaticamente por `pytest tests/e2e` em {run.timestamp}.",
    ]
    return "\n".join(lines) + "\n"


def _metadata(scenario: Scenario, run: RunInfo) -> str:
    clocks = ", ".join(sorted({transcript.now for transcript in scenario.transcripts}))
    judge = _judge_metadata(scenario.judgement)
    return f"*Modelo: `{run.model}` · Data/hora simulada da loja: {clocks or '—'}{judge}*"


def _judge_metadata(judgement: Judgement | None) -> str:
    if judgement is None or judgement.average is None:
        return ""
    return f" · Avaliação do juiz: média {judgement.average:.1f}/5"


def _conversation(transcripts: list[Transcript]) -> list[str]:
    lines: list[str] = []
    for index, transcript in enumerate(transcripts, start=1):
        if len(transcripts) > 1:
            lines += [f"## Sessão {index} (novo processo, sessão `{transcript.session_id}`)", ""]
        for turn in transcript.turns:
            lines += _turn(turn)
    return lines


def _turn(turn: Turn) -> list[str]:
    lines = [f"**Cliente:** {turn.user}", "", f"**Lia:** {turn.reply}", ""]
    if turn.tool_calls:
        lines += ["<details><summary>Ferramentas consultadas</summary>", ""]
        lines += [f"- {_tool_line(call)}" for call in turn.tool_calls]
        lines += ["", "</details>", ""]
    return lines


def _tool_line(call: ToolCall) -> str:
    arguments = json.dumps(call.arguments, ensure_ascii=False)
    error = " — retornou erro" if call.is_error else ""
    return f"`{call.name}` `{arguments}`{error}"


def _status(scenario: Scenario) -> str:
    return STATUS_LABEL.get(scenario.outcome, scenario.outcome)


def _single_line(text: str) -> str:
    return " ".join(text.split())
