"""Infraestrutura E2E: CLI real + LLM real, com relatório gravado mesmo quando há falhas."""

import os
from collections.abc import Generator
from datetime import datetime
from pathlib import Path

import pytest
from dotenv import dotenv_values

from .support.judge import Judge
from .support.report import RunInfo, reset_directory, write_report
from .support.runner import ConversationRunner, RunConversation, Transcript
from .support.scenario import Example, Scenario

REPO_ROOT = Path(__file__).resolve().parents[2]
REPORT_DIR = REPO_ROOT / "reports" / "e2e" / "latest"
EXAMPLES_DIR = REPO_ROOT / "examples"
DEFAULT_MODEL = "claude-opus-5-5"
SKIP_REASON = (
    "ANTHROPIC_API_KEY não definida (nem no ambiente nem no .env): a suíte E2E usa o LLM real"
)

SCENARIOS_KEY = pytest.StashKey[list[Scenario]]()
SCENARIO_KEY = pytest.StashKey[Scenario]()
JUDGE_KEY = pytest.StashKey[Judge | None]()


def cli_environment() -> dict[str, str]:
    """Ambiente do processo completado pelo .env do repositório (o ambiente tem prioridade)."""
    dotenv = {key: value for key, value in dotenv_values(REPO_ROOT / ".env").items() if value}
    return {**dotenv, **os.environ}


def api_key_available() -> bool:
    return bool(cli_environment().get("ANTHROPIC_API_KEY"))


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers", "example(number, slug, title): cenário também publicado em examples/"
    )
    config.stash[SCENARIOS_KEY] = []
    config.stash[JUDGE_KEY] = (
        Judge.from_environment(cli_environment()) if api_key_available() else None
    )


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    if api_key_available():
        return
    for item in items:
        item.add_marker(pytest.mark.skip(reason=SKIP_REASON))


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(
    item: pytest.Item, call: pytest.CallInfo[None]
) -> Generator[None, pytest.TestReport, pytest.TestReport]:
    report = yield
    scenario = item.stash.get(SCENARIO_KEY, None)
    if scenario is not None and (report.when == "call" or report.failed):
        scenario.outcome = report.outcome
        scenario.duration_seconds += report.duration
        if call.excinfo is not None:
            scenario.error = call.excinfo.exconly()
    return report


def pytest_sessionfinish(session: pytest.Session) -> None:
    scenarios = session.config.stash[SCENARIOS_KEY]
    if not scenarios:
        return
    judge = session.config.stash[JUDGE_KEY]
    run = RunInfo(
        timestamp=datetime.now().astimezone().isoformat(timespec="seconds"),
        model=cli_environment().get("EMPORIO_MODEL") or DEFAULT_MODEL,
        judge_model=judge.model if judge else None,
    )
    # Reset only when a fresh report replaces it: a run that executed nothing (e.g. --collect-only)
    # must never wipe the last published artifact.
    reset_directory(REPORT_DIR)
    write_report(scenarios, run, REPORT_DIR, EXAMPLES_DIR)


@pytest.fixture
def scenario(request: pytest.FixtureRequest) -> Scenario:
    test_function = request.function
    record = Scenario(
        name=test_function.__name__.removeprefix("test_"),
        description=" ".join((test_function.__doc__ or "").split()),
        example=_example_from_marker(request.node.get_closest_marker("example")),
        judge=request.config.stash[JUDGE_KEY],
    )
    request.node.stash[SCENARIO_KEY] = record
    request.config.stash[SCENARIOS_KEY].append(record)
    return record


@pytest.fixture
def sessions_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "sessions"
    directory.mkdir()
    return directory


@pytest.fixture
def run_conversation(scenario: Scenario, tmp_path: Path, sessions_dir: Path) -> RunConversation:
    """`run_conversation(session_id, mensagens, agora)`: um processo da CLI por chamada."""
    runner = ConversationRunner(
        repo_root=REPO_ROOT,
        work_dir=tmp_path,
        base_env=cli_environment(),
        sessions_dir=sessions_dir,
    )

    def run(session_id: str, messages: list[str], now: str) -> Transcript:
        return scenario.record(runner.run(session_id, messages, now))

    return run


def _example_from_marker(marker: pytest.Mark | None) -> Example | None:
    return Example(**marker.kwargs) if marker else None
